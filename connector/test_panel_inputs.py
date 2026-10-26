"""The panel's untouched-default inputs pass the REAL server validation.

connector/testdata/panel_default_inputs.json holds the exact inputs the panel
sends with its defaults, per units and action. Each set goes through the same
path as connector.py: catalog.to_mm, then catalog.validate_inputs. The
"extended" sets carry the inputs Track 2 adds (origin, document_id); they are
skipped until Track 2 merges.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import catalog  # noqa: E402

DATA = os.path.join(HERE, "testdata", "panel_default_inputs.json")


def _load():
    with open(DATA) as fh:
        return json.load(fh)


def check_sets(sets):
    """Every {units: {action: inputs}} set must validate after to_mm; the
    first failure names the set, the field and the value the server saw."""
    for units, actions in sets.items():
        for action, inputs in actions.items():
            mm = catalog.to_mm(inputs)
            ok, code, msg = catalog.validate_inputs(mm, action)
            assert ok, "%s/%s rejected (%s): %s" % (units, action, code, msg)


def test_panel_defaults_validate_681f551():
    check_sets(_load()["catalog_681f551"])


def test_panel_defaults_validate_extended():
    props = catalog.get_action(catalog.ACTION)["inputs"]["properties"]
    if "origin" not in props or "document_id" not in props:
        pytest.skip("origin/document_id inputs arrive with Track 2 (toollib); "
                    "Track 2 removes this skip with item (e)")
    check_sets(_load()["extended"])


def test_check_sets_catches_unit_slip():
    """Fault: an inch set whose tool_diameter was sent as mm (x 25.4 too
    much) must be rejected on that field."""
    sets = _load()["catalog_681f551"]
    bad = {"inch": {"adaptive_rough": dict(
        sets["inch"]["adaptive_rough"],
        tool_diameter=sets["inch"]["adaptive_rough"]["tool_diameter"] * 25.4)}}
    with pytest.raises(AssertionError) as ei:
        check_sets(bad)
    assert "tool_diameter" in str(ei.value), str(ei.value)
