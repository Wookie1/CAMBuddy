"""SK1/M2 tool-table lookups (cli.table_flute / table_holder): the exact tool
number wins; a number missing from the table falls back to type + diameter
and says so on stderr (never silently)."""
import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import cli  # noqa: E402

TABLE = {"tools": [
    {"number": 3, "type": "bull", "diameter_mm": 12.7, "flute_mm": 31.75,
     "holder": "H", "stickout_mm": 41.275},
    {"number": 7, "type": "bull", "diameter_mm": 12.7, "flute_mm": 50.0,
     "holder": "H", "stickout_mm": 80.0}],
    "holders": {"H": {"segments": [[0, 10, 15, 20]]}}}


def test_exact_number_wins_and_fallback_is_logged():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "tools.json")
        with open(p, "w") as fh:
            json.dump(TABLE, fh)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.table_flute("bull", 12.7, 7, p) == 50.0
            assert cli.table_holder("bull", 12.7, 7, p) == (20.0, 80.0)
        assert err.getvalue() == ""          # exact number: no fallback
        with contextlib.redirect_stderr(err):
            assert cli.table_flute("bull", 12.7, 9, p) == 31.75
            assert cli.table_holder("bull", 12.7, 9, p) == (20.0, 41.275)
        log = err.getvalue()
        assert log.count("warning: tool T9 not in") == 2, log
        assert "entry T3" in log, log
    print("PASS table fallback: exact number wins; T9 -> T3 logged")


if __name__ == "__main__":
    test_exact_number_wins_and_fallback_is_logged()
