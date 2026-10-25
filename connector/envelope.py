"""Track 2 (f): the result envelope {verdict, summary, attention} added to
every action's result (and written into check.json).

verdict: "failed" when attention has a blocker (a gate failed: no .nc),
"needs_review" when it has a review item, else "ready". Attention items:
{code, severity: blocker|review|info, message, where?, next_step}.
"""
import errors

SEVERITY = {code: kind for code, (kind, _s) in errors.CODES.items()}
# engine/judge counters that mean "review this" when > 0 (recognised when a
# check or stats dict carries them; this base's engine does not emit the
# last three yet)
_REVIEW_KEYS = ("reduced_feed_windows", "credit_fallback",
                "failed_region_emitted")


def item(code, message, where=None, severity=None):
    it = {"code": code, "severity": severity or SEVERITY.get(code, "info"),
          "message": message, "next_step": errors.NEXT_STEPS.get(code, "")}
    if where:
        it["where"] = where
    return it


def _count(v):
    if isinstance(v, dict):
        return v.get("count", 0) or 0
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, list):
        return len(v)
    return 0


def _first_line(d):
    for k in ("first_line", "line"):
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    spikes = (d or {}).get("spikes") or (d or {}).get("flags") or []
    if spikes and isinstance(spikes[0], dict):
        return spikes[0].get("line")
    return None


def program_items(program, check):
    """review + info items for one judged program's zmap check dict."""
    out = []
    eng = check.get("engagement") or {}
    if _count(eng) > 0 and eng.get("threshold_mm") is not None:
        out.append(item(
            "engagement_overload",
            "%s: %d cutting moves bite more than %.3f mm (max %.3f mm)"
            % (program, eng["count"], eng["threshold_mm"],
               eng.get("max_mm") or 0.0),
            where={"program": program, "line": _first_line(eng)}))
    pl = check.get("plunge") or {}
    if _count(pl) > 0:
        out.append(item(
            "steep_plunge", "%s: %d steep feed entries into stock (over "
            "%.1f deg)" % (program, pl["count"],
                           pl.get("ramp_angle_deg") or 3.0),
            where={"program": program, "line": _first_line(pl)}))
    bsb = check.get("below_stock_bottom") or {}
    if bsb.get("status") == "unknown":
        out.append(item(
            "stock_bottom_unchecked", "%s: the cut below the stock bottom "
            "was not checked (%s)" % (program, bsb.get("reason") or
                                      "no stock box"),
            where={"program": program}))
    for k in _REVIEW_KEYS:
        if _count(check.get(k)) > 0:
            out.append(item(k, "%s: %s = %s" % (program, k,
                                                _count(check.get(k))),
                            where={"program": program}))
    lo = check.get("leftover") or {}
    if lo:
        frac = check.get("within_0p5mm_fraction")
        out.append(item(
            "leftover", "%s: leftover mean %.3f / p95 %.3f / max %.3f mm"
            % (program, lo.get("mean", 0.0), lo.get("p95", 0.0),
               lo.get("max", 0.0)), where={"program": program}))
        if frac is not None and frac < 1.0:
            out.append(item(
                "area_left_for_next_op",
                "%s: %.1f %% of the part is still more than 0.5 mm from "
                "finished" % (program, 100.0 * (1.0 - frac)),
                where={"program": program}))
    return out


def judged_programs(action, check):
    """[(program name, check dict)] from an action's check.json."""
    if not isinstance(check, dict):
        return []
    if "programs" in check and isinstance(check["programs"], list):
        return [(e.get("name"), e.get("check") or {})
                for e in check["programs"]]
    if "chain" in check:
        return [(n + ".nc", check.get(n) or {}) for n in check["chain"]]
    return [("rough.nc", check)]


def verdict_of(attention):
    sev = {a["severity"] for a in attention}
    return ("failed" if "blocker" in sev else
            "needs_review" if "review" in sev else "ready")


def build(attention, what):
    v = verdict_of(attention)
    n_rev = sum(a["severity"] == "review" for a in attention)
    n_blk = sum(a["severity"] == "blocker" for a in attention)
    if v == "failed":
        summary = "%s failed: %s" % (what, next(
            a["message"] for a in attention if a["severity"] == "blocker"))
    elif v == "needs_review":
        summary = "%s is ready to check, with %d item%s to review first." % (
            what, n_rev, "" if n_rev == 1 else "s")
    else:
        summary = "%s is ready." % what
    if n_blk > 1:
        summary += " (%d blockers)" % n_blk
    return {"verdict": v, "summary": summary, "attention": attention}


_WHAT = {"adaptive_rough": "The roughing program",
         "slope_split_finish": "The rough + finish programs",
         "check_program": "The checked program",
         "model.measure": "The measurement"}


def for_result(action, check):
    attention = []
    for name, c in judged_programs(action, check):
        attention += program_items(name, c)
    return build(attention, _WHAT.get(action, action))


def for_failure(action, err):
    """A failed or refused run: one blocker carrying the error."""
    it = item(err["code"], err["message"], where=err.get("where"),
              severity="blocker")
    it["next_step"] = err.get("next_step") or it["next_step"]
    return build([it], _WHAT.get(action, action))


def for_tool_action(action, result):
    attention = []
    for t in result.get("tools", []) if isinstance(result, dict) else []:
        if not t.get("holder"):
            attention.append(item(
                "tool_without_holder", "%s has no holder: runs with it "
                "fail the holder gate" % t.get("tool_id"),
                where=None))
    summary = {
        "tools.list": "%d tools, %s pockets." % (
            len(result.get("tools", [])), result.get("pockets")),
        "tools.update": "Library tool saved.",
        "job.get": "Job for document %s." % result.get("document_id"),
        "job.renumber": "Job renumbering saved.",
        "job.setup": "Job setup saved.",
    }.get(action, "Done.")
    return {"verdict": verdict_of(attention), "summary": summary,
            "attention": attention}
