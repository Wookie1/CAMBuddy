"""Track 2 (f): agent-facing errors and the result envelope.

Every refusal is {code, message, field?, got?, allowed?, next_step}
(make_error). Every result carries {verdict, summary, attention} (see
envelope.py); attention items are {code, severity, message, where?,
next_step}. NEXT_STEPS is the one table of codes: docs/agent_guide.md's
code table is generated from it (render_code_table; test_track2 fails on
drift; regenerate with `python3 connector/errors.py`).
"""
import os
import re

# code -> (kind, next_step). kind: "error" (the run is refused or fails) or
# "blocker" / "review" / "info" (attention items in a result).
CODES = {
    # --- input validation (rejected before anything runs) ---
    "input_missing": ("error", "Add the missing input named in `field`."),
    "input_unknown": ("error", "Remove or rename the input in `field`; "
                      "`allowed` lists the closest valid names."),
    "input_out_of_range": ("error", "Use a value inside `allowed` (in the "
                           "units you sent) for `field`, then run again."),
    "action_unknown": ("error", "Use one of the connector's actions (see "
                       "the catalog)."),
    "input_digest_mismatch": ("error", "Send the run again: the downloaded "
                              "file did not match its sha256/size."),
    # --- tool library / jobs ---
    "unknown_tool": ("error", "Use a tool_id from tools.list."),
    "duplicate_t": ("error", "Pick a T no other tool uses in this job "
                    "(job.get / tools.list show the T numbers in use), or "
                    "renumber the other tool first."),
    "out_of_range": ("error", "Use a T inside `allowed` (job.renumber: "
                     "1..pockets; tools.update: 1..999); tools.update "
                     "{pockets} changes the pocket count."),
    "invalid_field": ("error", "Fix the field named in `field` (see "
                      "`allowed`)."),
    "unknown_holder": ("error", "Use a holder name from `allowed`, or null."),
    "duplicate_tool": ("error", "Change the type, diameter or corner so the "
                       "tool differs from the one named in the message."),
    "bad_document_id": ("error", "Pass the STEVE document id as sent by "
                        "STEVE (letters, digits, '.', '_', '-', <= 128)."),
    "no_library": ("error", "Run the connector with its state directory "
                   "(~/.stevecam or --home)."),
    "library_error": ("error", "Check ~/.stevecam/tools.json is valid JSON; "
                      "delete it to re-seed from the repo table."),
    "tool_not_in_table": ("error", "add this tool to tools/x7_tools.json "
                          "(the table the engine and judges read), or pick a "
                          "tool that is in it"),
    "tool_table_unreadable": ("error", "Fix or re-seed the tool library "
                              "file named in the message."),
    "tool_entry_incomplete": ("error", "Fill the missing field of that tool "
                              "with tools.update."),
    "finish_tool_not_in_table": ("error", "Pass tool_number for the finish "
                                 "ball, or add the ball to the library."),
    "rest_tool_no_holder": ("error", "Set the rest tool's holder (and "
                            "stick-out) in the library, or pick a rest tool "
                            "that has one."),
    "rest_tool_not_ball": ("error", "Pick a ball nose for rest_tool_number."),
    "rest_tool_too_big": ("error", "Pick a rest ball smaller than the "
                          "finishing ball."),
    "multi_tool_program": ("error", "Split the program into one program per "
                           "tool (program, program_2, program_3)."),
    "no_t_word": ("error", "Add a T word to the program or pass "
                  "tool_number."),
    "tool_number_mismatch": ("error", "Leave tool_number empty or set it to "
                             "the program's own T."),
    "tool_geometry_mismatch": ("error", "Set that library tool's field to "
                               "the value tools/x7_tools.json shows."),
    # --- gates (blockers: the run fails, no .nc is uploaded) ---
    "gouges": ("blocker", "Check orientation, tool size and stepdown at the "
               "spot in `where`, then run again."),
    "rapid_collisions": ("blocker", "Check floor_z and the stock sizes; the "
                         "first offending line is in `where`."),
    "over_flute": ("blocker", "Use a longer-flute or necked tool, or split "
                   "the depth."),
    "holder_unknown": ("blocker", "Give the tool a holder and stick-out in "
                       "the library (tools.update), or pick a tool that "
                       "has one."),
    "holder_hits": ("blocker", "Use more stick-out or a slimmer holder; the "
                    "first line is in `where`."),
    "axial_plunges": ("blocker", "Raise floor_z or use a ramp-capable "
                      "entry; the first line is in `where`."),
    "clcheck": ("blocker", "Check the ball diameter and tool number against "
                "the library and run again."),
    "unsupported_code": ("blocker", "Remove the code named in the message "
                         "(line in `where`) or post with the supported "
                         "subset."),
    "outside_grid": ("blocker", "Make the stock box cover every move, or "
                     "check the program's origin."),
    "posted_units_mismatch": ("blocker", "Report this: the post did not "
                              "honour `units`."),
    "stale_artifact": ("blocker", "Run again; a stale intermediate file "
                       "was refused."),
    "engine_failed": ("blocker", "Read the message; fix the inputs it "
                      "names, or report it with the run id."),
    "nothing_to_cut": ("blocker", "Nothing was cleared: finish or rest the "
                       "exterior instead, or check the orientation, stock "
                       "and floor inputs."),
    "internal_error": ("blocker", "Report it with the run id; the details "
                       "are in the connector's run log."),
    # --- review items (verdict needs_review) ---
    "engagement_overload": ("review", "Look at the listed lines; lower "
                            "optimal_load or stepover if they chatter."),
    "steep_plunge": ("review", "Check the entries at the listed lines "
                     "before running."),
    "reduced_feed_windows": ("review", "Check the slowed sections; they "
                             "cost cycle time."),
    "credit_fallback": ("review", "Check the regions the engine cut with "
                        "its fallback strategy."),
    "failed_region_emitted": ("review", "Inspect the region the engine "
                              "could not plan cleanly before running."),
    "stock_bottom_unchecked": ("review", "Run again; if it repeats, "
                               "report it with the run id (the judge got "
                               "no stock box for this program)."),
    # --- info items ---
    "area_left_for_next_op": ("info", "Plan the next operation (finish or "
                              "rest) for the stock left."),
    "leftover": ("info", "No action: leftover summary for the program."),
    "tool_without_holder": ("info", "Add holder + stick-out if you will "
                            "cut with it (tools.update)."),
}

NEXT_STEPS = {k: v[1] for k, v in CODES.items()}


def make_error(code, message, field=None, got=None, allowed=None,
               where=None):
    err = {"code": code, "message": str(message)[:400],
           "next_step": NEXT_STEPS.get(code, "")}
    for k, v in (("field", field), ("got", got), ("allowed", allowed),
                 ("where", where)):
        if v is not None:
            err[k] = v
    return err


def error_issues(err):
    """Problems with one error dict (empty list = agent-ready)."""
    out = []
    for k in ("code", "message", "next_step"):
        if not (isinstance(err.get(k), str) and err[k].strip()):
            out.append("missing %s" % k)
    return out


def render_code_table():
    lines = ["| code | kind | next_step |", "| --- | --- | --- |"]
    for code, (kind, step) in CODES.items():
        lines.append("| `%s` | %s | %s |" % (code, kind, step))
    return "\n".join(lines)


GUIDE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "docs", "agent_guide.md")
BEGIN, END = "<!-- codes:begin -->", "<!-- codes:end -->"


def guide_codes_section(text):
    m = re.search(re.escape(BEGIN) + r"\n(.*?)\n" + re.escape(END), text,
                  re.S)
    return m.group(1) if m else None


if __name__ == "__main__":  # regenerate the guide's code table
    with open(GUIDE) as fh:
        text = fh.read()
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END),
                 lambda _m: BEGIN + "\n" + render_code_table() + "\n" + END,
                 text, flags=re.S)
    with open(GUIDE, "w") as fh:
        fh.write(new)
    print("updated %s" % GUIDE)
