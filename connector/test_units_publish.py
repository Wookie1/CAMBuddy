"""Units vs STEVE's input check (James's first panel run, 2026-10-29: inch
rest_stepup 0.075 refused by STEVE as "rest_stepup: at least 0.1",
code inputs_invalid).

STEVE checks every number input's minimum/maximum on the RAW value, before
units are known (docs/steve_connector_protocol.md, Values). CATALOG's bounds
for length/feed inputs are millimetres, so the PUBLISHED catalog must admit
the inch numbers too, while validate() keeps the exact mm ranges.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import catalog as catalog_mod  # noqa: E402

DATA = os.path.join(HERE, "testdata", "panel_default_inputs.json")


def _published():
    # on main there is no published_catalog(): STEVE got CATALOG itself
    return getattr(catalog_mod, "published_catalog", lambda: catalog_mod.CATALOG)()


def _steve_raw_check(cat, action, values):
    """STEVE's rule as documented: each number input's minimum/maximum is
    checked against the value exactly as sent. -> list of refusals."""
    spec = next(a for a in cat["actions"] if a["name"] == action)
    props = spec["inputs"]["properties"]
    bad = []
    for k, v in values.items():
        p = props.get(k)
        if p is None or p.get("type") not in ("number", "integer") or \
                not isinstance(v, (int, float)):
            continue
        if "minimum" in p and v < p["minimum"]:
            bad.append("%s.%s=%r: at least %r" % (action, k, v, p["minimum"]))
        if "maximum" in p and v > p["maximum"]:
            bad.append("%s.%s=%r: at most %r" % (action, k, v, p["maximum"]))
    return bad


def test_units_steve_admits_the_panel_defaults_in_both_units():
    """The panel's exact default inputs (inch AND mm) clear STEVE's raw
    min/max check against the published catalog. Fails on 42e1500 with
    adaptive_rough.rest_stepup=0.075: at least 0.1 (and the slope rough's)."""
    cat = _published()
    with open(DATA) as fh:
        sets = json.load(fh)["extended"]
    bad = []
    for unit in ("inch", "mm"):
        for action, values in sets[unit].items():
            if any(a["name"] == action for a in cat["actions"]):
                bad += ["%s: %s" % (unit, b) for b in
                        _steve_raw_check(cat, action, values)]
    assert not bad, "STEVE would refuse the panel's defaults: %s" % bad


def test_units_published_bounds_admit_every_valid_value_in_both_units():
    """For every length/feed input: the inch number of its mm minimum and of
    its mm maximum both clear the published bounds (so does the mm number),
    and published bounds never TIGHTEN the mm range."""
    cat = _published()
    bad = []
    for a, pa in zip(catalog_mod.CATALOG["actions"], cat["actions"]):
        props = (a.get("inputs") or {}).get("properties", {})
        pprops = (pa.get("inputs") or {}).get("properties", {})
        for k, v in props.items():
            if k not in catalog_mod.MM_FIELDS:
                continue
            lo, hi = v.get("minimum"), v.get("maximum")
            plo, phi = pprops[k].get("minimum"), pprops[k].get("maximum")
            for x in [y for y in (lo, hi) if y is not None]:
                for val in (x, x / 25.4):
                    if plo is not None and val < plo - 1e-12:
                        bad.append("%s.%s %r < published min %r" % (a["name"], k, val, plo))
                    if phi is not None and val > phi + 1e-12:
                        bad.append("%s.%s %r > published max %r" % (a["name"], k, val, phi))
    assert not bad, bad


def test_units_every_length_or_feed_input_is_converted():
    """Every number input that follows `units` (length or feed) is in
    MM_FIELDS, so to_mm() converts it; non-length numbers (rpm, program and
    tool numbers, angles, counts) are not. (Passes on 42e1500 too: the
    conversion list was complete; the refusal came from the published bounds.)"""
    bad = []
    for a in catalog_mod.CATALOG["actions"]:
        for k, v in (a.get("inputs") or {}).get("properties", {}).items():
            if v.get("type") not in ("number", "integer"):
                continue
            follows = "follows `units`" in v.get("description", "")
            if follows != (k in catalog_mod.MM_FIELDS):
                bad.append("%s.%s follows-units=%s in-MM_FIELDS=%s" % (
                    a["name"], k, follows, k in catalog_mod.MM_FIELDS))
    assert not bad, bad


def test_units_inch_rest_stepup_validates_and_lands_in_mm():
    """The connector side: inch rest_stepup 0.075 is accepted by
    validate() after to_mm and reaches the run as 1.905 mm."""
    with open(DATA) as fh:
        values = json.load(fh)["extended"]["inch"]["adaptive_rough"]
    mm = catalog_mod.to_mm(dict(values), catalog_mod.ACTION)
    ok, code, out = catalog_mod.validate_inputs(mm, catalog_mod.ACTION)
    assert ok, (code, out)
    assert abs(out["rest_stepup"] - 1.905) < 1e-9, out["rest_stepup"]
