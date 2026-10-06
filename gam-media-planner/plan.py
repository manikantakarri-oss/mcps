"""Turn a budget into a media plan: pure arithmetic, no GAM calls, so it can be
tested on its own and explained line by line.

An option is one position the plan may buy: an ad unit and size, how it is
priced (cost method and rate) and how much of it is available in the flight.
Strategies:
  max_reach  cheapest cost per impression first, each filled up to what is
             available, until the budget is spent (most impressions for it)
  balanced   the budget spread in proportion to what is available, so every
             position gets a share (more variety, fewer impressions)
Whatever cannot be spent because inventory runs out is reported, never hidden.
"""
from __future__ import annotations

import datetime as dt

# How each cost method turns money into units, and what the unit is called.
METHODS = {
    "CPM": {"per": 1000, "unit": "Impressions"},
    "VCPM": {"per": 1000, "unit": "Viewable impressions"},
    "CPV": {"per": 1, "unit": "Video views"},
    "CPC": {"per": 1, "unit": "Clicks"},
    "CPD": {"per": 1, "unit": "Days"},
}
IMPRESSION_BASED = {"CPM", "VCPM", "CPV"}
VIDEO_SIZES = {"640x480", "640x360", "1280x720", "1920x1080", "400x300"}


class PlanError(Exception):
    pass


def creative_type(size: str, method: str) -> str:
    if method == "CPV" or size in VIDEO_SIZES:
        return "Video"
    if size in ("1x1", "0x0"):
        return "Native / custom"
    return "Display"


def _cost_per_unit(method: str, rate: float) -> float:
    return rate / METHODS[method]["per"]


def build(budget: float, start: dt.date, end: dt.date, options: list[dict], strategy: str = "max_reach",
          currency: str = "USD") -> dict:
    """options: [{position, ad_unit_id, size, method, rate, available, source}].
    `available` is in the method's own units for impression-based methods;
    CPC and CPD are bought as asked (`units` on the option) since GAM does not
    forecast clicks or days."""
    if budget <= 0:
        raise PlanError("The budget must be more than zero.")
    if end < start:
        raise PlanError("The end date is before the start date.")
    if not options:
        raise PlanError("There is nothing to plan: no positions were chosen.")
    if strategy not in ("max_reach", "balanced"):
        raise PlanError("Strategy must be max_reach or balanced.")
    days = (end - start).days + 1
    opts = []
    for o in options:
        m = str(o.get("method") or "CPM").upper()
        if m not in METHODS:
            raise PlanError("Unknown cost method %s (use CPM, VCPM, CPV, CPC or CPD)." % m)
        rate = float(o.get("rate") or 0)
        if rate <= 0:
            raise PlanError("%s has no rate." % o.get("position", "A position"))
        cap = int(o.get("available") or 0) if m in IMPRESSION_BASED else int(o.get("units") or (days if m == "CPD" else 0))
        opts.append({**o, "method": m, "rate": rate, "cap": max(0, cap), "cpu": _cost_per_unit(m, rate)})

    spend = {i: 0.0 for i in range(len(opts))}
    left = float(budget)
    if strategy == "max_reach":
        for i in sorted(range(len(opts)), key=lambda i: opts[i]["cpu"]):
            if left <= 0:
                break
            take = min(left, opts[i]["cap"] * opts[i]["cpu"])
            spend[i] += take
            left -= take
    else:
        # Proportional to available value, re-spreading what a full position cannot take.
        active = [i for i in range(len(opts)) if opts[i]["cap"] > 0]
        for _ in range(len(opts) + 1):
            if left <= 0.005 or not active:
                break
            weight = sum(opts[i]["cap"] * opts[i]["cpu"] - spend[i] for i in active)
            if weight <= 0:
                break
            share_left, nxt = left, []
            for i in active:
                room = opts[i]["cap"] * opts[i]["cpu"] - spend[i]
                take = min(room, share_left * room / weight)
                spend[i] += take
                left -= take
                if opts[i]["cap"] * opts[i]["cpu"] - spend[i] > 0.005:
                    nxt.append(i)
            active = nxt

    flight = "%s - %s" % (start.strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y"))
    rows = []
    for i, o in enumerate(opts):
        if spend[i] <= 0.004:
            continue
        units = int(spend[i] / o["cpu"])
        cost = round(units * o["cpu"], 2)
        rows.append({
            "position": o.get("position") or o.get("ad_unit_id", ""),
            "ad_unit_id": o.get("ad_unit_id", ""),
            "ad_size": o.get("size", ""),
            "creative_type": creative_type(o.get("size", ""), o["method"]),
            "served_by": "Google Ad Manager",
            "flight": flight,
            "cost_method": o["method"],
            "unit_type": METHODS[o["method"]]["unit"],
            "rate": o["rate"],
            "units": units,
            "cost": cost,
            "availability_source": o.get("source", ""),
        })
    spent = round(sum(r["cost"] for r in rows), 2)
    unspent = round(budget - spent, 2)
    notes = []
    if unspent >= 0.01:
        notes.append("%s %s of the budget could not be placed: the chosen positions do not have enough available "
                     "inventory in this flight. Add positions, widen the dates or raise availability." % (currency, format(unspent, ",.2f")))
    if any(o.get("source") == "estimate" for o in opts):
        notes.append("Some availability is estimated from recent delivery, not forecast by Google Ad Manager.")
    return {"strategy": strategy, "flight": flight, "days": days, "budget": round(budget, 2), "spent": spent,
            "unspent": unspent, "currency": currency, "rows": rows,
            "totals": {"units_by_type": _sum_units(rows), "cost": spent}, "notes": notes}


def _sum_units(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        out[r["unit_type"]] = out.get(r["unit_type"], 0) + r["units"]
    return out


def to_markdown(plan: dict) -> str:
    head = "| Position | Ad size | Creative type | Flight | Cost method | Unit type | Rate | Units | Cost |\n|---|---|---|---|---|---|---|---|---|"
    lines = [head]
    for r in plan["rows"]:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["position"], r["ad_size"], r["creative_type"], r["flight"], r["cost_method"], r["unit_type"],
            "$%.4f" % r["rate"], format(r["units"], ","), "$" + format(r["cost"], ",.2f")))
    lines.append("| **Total** | | | | | | | | **$%s** |" % format(plan["spent"], ",.2f"))
    return "\n".join(lines)
