"""Read-only access to one Google Ad Manager network.

Credentials come from the client's Databricks secret scope, given to this app
as resources: GAM_KEY_JSON (the service account key, as JSON text) and
GAM_NETWORK_CODE. Nothing here creates or changes anything in GAM.

Learnt against a live network (Oct 2026):
- API versions are retired after about a year (v202508 already answered
  "deprecated and is now disabled"), so the newest the library offers is tried
  first.
- A network or ad unit without enough traffic history answers forecasts with
  ForecastingError.NO_FORECAST_YET. Then availability is estimated from the
  last 30 days of delivery (ReportService) and labelled as an estimate.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import os
import tempfile
import threading
import time

from googleads import ad_manager, errors, oauth2

VERSIONS = ("v202608", "v202605", "v202602", "v202511")
_lock = threading.Lock()
_client = None
_cache: dict = {}


class GamError(Exception):
    """A problem worth showing as-is to the person asking."""


def network_code() -> str:
    code = (os.environ.get("GAM_NETWORK_CODE") or "").strip()
    if not code.isdigit():
        raise GamError("This tool is not connected to Google Ad Manager yet: the network code is missing. "
                       "An admin sets it in the Portal Deployer under the client's GAM connection.")
    return code


def client():
    """One Ad Manager client per process. The key is written to a private
    temporary file only because the library reads keys from a file."""
    global _client
    with _lock:
        if _client is not None:
            return _client
        raw = os.environ.get("GAM_KEY_JSON") or ""
        try:
            key = json.loads(raw)
            assert key.get("type") == "service_account" and key.get("private_key")
        except (ValueError, AssertionError):
            raise GamError("This tool is not connected to Google Ad Manager yet: the service account key is missing "
                           "or not valid. An admin sets it in the Portal Deployer under the client's GAM connection.")
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(key, f)
        os.chmod(path, 0o600)
        auth = oauth2.GoogleServiceAccountClient(path, oauth2.GetAPIScope("ad_manager"))
        _client = ad_manager.AdManagerClient(auth, "agent-portal-media-planner", network_code=network_code())
        return _client


def service(name: str):
    c = client()
    last = None
    for v in VERSIONS:
        try:
            return c.GetService(name, version=v), v
        except Exception as exc:  # noqa: BLE001 - an unknown version for this library build
            last = exc
    raise GamError("Google Ad Manager could not be reached (%s)." % last)


def _statement(version: str, where: str = "", limit: int = 500, offset: int = 0, values: dict | None = None):
    sb = ad_manager.StatementBuilder(version=version)
    if where:
        sb.Where(where)
        for k, v in (values or {}).items():
            sb.WithBindVariable(k, v)
    sb.Limit(limit).Offset(offset)
    return sb


def _cached(key: str, seconds: int, fn):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    value = fn()
    _cache[key] = (time.time() + seconds, value)
    return value


# --- inventory --------------------------------------------------------------

def network() -> dict:
    def load():
        svc, _ = service("NetworkService")
        n = svc.getCurrentNetwork()
        return {"code": str(n["networkCode"]), "name": n["displayName"], "currency": n["currencyCode"],
                "time_zone": n["timeZone"], "root_ad_unit": str(n["effectiveRootAdUnitId"])}
    return _cached("network", 3600, load)


def ad_units() -> list[dict]:
    """Every active ad unit: id, name, full path and sizes. Cached ten minutes."""
    def load():
        svc, v = service("InventoryService")
        out, offset = [], 0
        while True:
            page = svc.getAdUnitsByStatement(_statement(v, "status = 'ACTIVE'", 500, offset).ToStatement())
            rows = (page["results"] if page and "results" in page else []) or []
            for u in rows:
                sizes = []
                for s in (u["adUnitSizes"] or []):
                    size = s["size"]
                    if size and not size["isAspectRatio"]:
                        sizes.append("%dx%d" % (size["width"], size["height"]))
                out.append({"id": str(u["id"]), "name": u["name"], "parent_id": str(u["parentId"] or ""),
                            "sizes": sorted(set(sizes)), "code": u["adUnitCode"] or ""})
            offset += 500
            if offset >= (page["totalResultSetSize"] if page else 0):
                break
        by_id = {u["id"]: u for u in out}
        root = network()["root_ad_unit"]
        for u in out:  # the path people recognise, e.g. "Sports > Cricket > Top banner"
            parts, cur, seen = [], u, set()
            while cur and cur["id"] not in seen and cur["id"] != root:  # the network root is not a position
                seen.add(cur["id"])
                parts.append(cur["name"])
                cur = by_id.get(cur["parent_id"])
            u["path"] = " > ".join(reversed(parts)) or u["name"]
        return [u for u in out if u["id"] != root]
    return _cached("ad_units", 600, load)


# --- prices -----------------------------------------------------------------

def rate_card() -> list[dict]:
    """Typical prices by cost type, from the network's own line items (the last
    500 delivering, ready, completed or paused). GAM rarely holds a separate
    sell-side rate card, so what was actually sold is the best default."""
    def load():
        svc, v = service("LineItemService")
        page = svc.getLineItemsByStatement(_statement(
            v, "status IN ('DELIVERING','READY','COMPLETED','PAUSED')", 500).ToStatement())
        rows = (page["results"] if page and "results" in page else []) or []
        groups: dict = {}
        currency = ""
        for li in rows:
            cpu = li["costPerUnit"]
            if not cpu or not cpu["microAmount"]:
                continue
            currency = cpu["currencyCode"]
            groups.setdefault((li["costType"], li["lineItemType"]), []).append(cpu["microAmount"] / 1e6)
        out = []
        for (cost_type, kind), vals in sorted(groups.items()):
            vals.sort()
            out.append({"cost_type": cost_type, "line_item_type": kind, "typical_rate": vals[len(vals) // 2],
                        "min_rate": vals[0], "max_rate": vals[-1], "lines": len(vals), "currency": currency})
        return out
    return _cached("rates", 1800, load)


# --- availability -------------------------------------------------------------

def _date(d: dt.date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day}


def forecast(ad_unit_id: str, size: str, start: dt.date, end: dt.date) -> dict | None:
    """GAM's availability forecast for a prospective line on one ad unit and
    size, or None when GAM has no forecast for it (NO_FORECAST_YET)."""
    tz = network()["time_zone"]
    w, h = (int(x) for x in size.lower().split("x"))
    line = {
        "lineItemType": "STANDARD",
        "costType": "CPM",
        "primaryGoal": {"goalType": "LIFETIME", "unitType": "IMPRESSIONS", "units": 1000},
        "creativePlaceholders": [{"size": {"width": w, "height": h}}],
        "targeting": {"inventoryTargeting": {"targetedAdUnits": [{"adUnitId": ad_unit_id, "includeDescendants": True}]}},
        "startDateTime": {"date": _date(start), "hour": 0, "minute": 0, "second": 0, "timeZoneId": tz},
        "endDateTime": {"date": _date(end), "hour": 23, "minute": 59, "second": 0, "timeZoneId": tz},
    }
    svc, _ = service("ForecastService")
    try:
        f = svc.getAvailabilityForecast({"lineItem": line}, {"includeContendingLineItems": False,
                                                             "includeTargetingCriteriaBreakdown": False})
    except errors.GoogleAdsServerFault as exc:
        if "NO_FORECAST_YET" in str(exc) or "NOT_ENOUGH_INVENTORY" in str(exc):
            return None
        raise GamError("Google Ad Manager could not forecast this: %s" % str(exc)[:200])
    return {"available": int(f["availableUnits"] or 0), "matched": int(f["matchedUnits"] or 0)}


def delivered_last_30_days() -> dict[str, int]:
    """Impressions served per ad unit in the last 30 days (ReportService).
    Cached for an hour: one report covers every ad unit."""
    def load():
        svc, v = service("ReportService")
        end = dt.date.today() - dt.timedelta(days=1)
        start = end - dt.timedelta(days=29)
        job = {"reportQuery": {
            "dimensions": ["AD_UNIT_ID"],
            "columns": ["AD_SERVER_IMPRESSIONS"],
            "adUnitView": "FLAT",
            "dateRangeType": "CUSTOM_DATE",
            "startDate": _date(start),
            "endDate": _date(end),
        }}
        downloader = client().GetDataDownloader(version=v)
        job_id = downloader.WaitForReport(svc.runReportJob(job))
        buf = io.BytesIO()
        downloader.DownloadReportToFile(job_id, "CSV_DUMP", buf, use_gzip_compression=True)
        text = gzip.decompress(buf.getvalue()).decode("utf-8")
        out: dict[str, int] = {}
        for row in csv.DictReader(io.StringIO(text)):
            uid = row.get("Dimension.AD_UNIT_ID") or ""
            n = row.get("Column.AD_SERVER_IMPRESSIONS") or "0"
            if uid:
                out[uid] = out.get(uid, 0) + int(float(n))
        return out
    return _cached("delivered", 3600, load)


def availability(ad_unit_id: str, size: str, start: dt.date, end: dt.date) -> dict:
    """Available impressions for one ad unit, size and flight, saying where the
    number came from: GAM's forecast, or the last 30 days of delivery scaled
    to the flight (an estimate, which ignores what is already booked)."""
    if end < start:
        raise GamError("The end date is before the start date.")
    f = forecast(ad_unit_id, size, start, end)
    if f is not None:
        return {"available": f["available"], "source": "forecast",
                "note": "Google Ad Manager forecast"}
    days = (end - start).days + 1
    served = delivered_last_30_days().get(ad_unit_id, 0)
    estimate = int(served / 30 * days)
    return {"available": estimate, "source": "estimate",
            "note": "Estimated from the last 30 days of delivery (%s impressions); Google Ad Manager has no forecast "
                    "for this yet, and bookings already made are not subtracted." % format(served, ",")}
