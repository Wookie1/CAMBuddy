# Task M4: connector runs must FAIL on any failed gate (connector/ only). Do not commit; mock STEVE only.
Every action (adaptive_rough, slope_split_finish) runs its zmap gate itself and reports the run FAILED (state failed,
clear error) when zmap gouges > 0, rapid collisions > 0, probe_clcheck > 0 (finish), or - once verify/zmap.py has
the shank/over-flute check (Task Z2) - shank or over-flute hits > 0. A failed run must never upload only a .nc: either
upload nothing but check.json/preview.png for diagnosis, or no files; never a postable program.
Tests (mock STEVE): a deliberately gouging program (inject via a test hook / monkeypatched engine output) -> run
failed, no .nc uploaded; a clean run still succeeds. Keep all connector tests passing.
