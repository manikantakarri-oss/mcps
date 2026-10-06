"""Offline checks for the plan arithmetic (no GAM). Run: python test_plan.py"""
import datetime as dt

import plan

S, E = dt.date(2026, 9, 1), dt.date(2026, 11, 15)


def opt(pos, method, rate, available=0, units=0, size="300x250", source="forecast"):
    return {"position": pos, "ad_unit_id": pos, "size": size, "method": method, "rate": rate,
            "available": available, "units": units, "source": source}


def test_max_reach_fills_cheapest_first_and_reports_unspent():
    p = plan.build(1000, S, E, [opt("A", "CPM", 10, 50_000), opt("B", "CPM", 2, 100_000)])
    rows = {r["position"]: r for r in p["rows"]}
    assert rows["B"]["units"] == 100_000 and rows["B"]["cost"] == 200.0   # cheapest, filled to the cap
    assert rows["A"]["units"] == 50_000 and rows["A"]["cost"] == 500.0    # then the next, also capped
    assert p["spent"] == 700.0 and p["unspent"] == 300.0 and "could not be placed" in p["notes"][0]


def test_max_reach_stops_at_budget():
    p = plan.build(100, S, E, [opt("A", "CPM", 2, 1_000_000), opt("B", "CPM", 5, 1_000_000)])
    assert [r["position"] for r in p["rows"]] == ["A"] and p["rows"][0]["units"] == 50_000 and p["unspent"] == 0


def test_balanced_gives_every_position_a_share_within_caps():
    p = plan.build(1000, S, E, [opt("A", "CPM", 5, 1_000_000), opt("B", "CPM", 5, 100_000)], strategy="balanced")
    rows = {r["position"]: r for r in p["rows"]}
    assert set(rows) == {"A", "B"} and rows["B"]["units"] <= 100_000
    assert abs(p["spent"] - 1000) < 0.02


def test_cpv_like_the_media_plan_screenshot():
    # $51,000 at $0.06 CPV = 850,000 video views, as in the sample plan
    p = plan.build(51_000, S, E, [opt("PSG4529", "CPV", 0.06, 2_000_000, size="640x480")])
    r = p["rows"][0]
    assert r["units"] == 850_000 and r["cost"] == 51_000.0 and r["unit_type"] == "Video views"
    assert r["creative_type"] == "Video" and r["flight"] == "09/01/2026 - 11/15/2026"


def test_estimates_are_flagged_and_bad_input_refused():
    p = plan.build(10, S, E, [opt("A", "CPM", 1, 100, source="estimate")])
    assert any("estimated" in n for n in p["notes"])
    for bad in (dict(budget=0), dict(end=dt.date(2026, 1, 1)), dict(options=[]), dict(strategy="random")):
        args = dict(budget=10, start=S, end=E, options=[opt("A", "CPM", 1, 100)], strategy="max_reach")
        args.update(bad)
        try:
            plan.build(**args)
        except plan.PlanError:
            continue
        raise AssertionError("accepted %s" % bad)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
            print("PASS", name)
    print("--- %d passed ---" % n)
