"""Tool library + per-document job renumbering (track 2, toollib).

Library: <home>/tools.json, seeded once from the repo's tools/x7_tools.json
(the connector never rewrites the repo file). Every tool has a stable
`tool_id`; its `number` is the library default T.

Job: <home>/jobs/<document_id>.json = {tool_id: T}, one per STEVE document.
Posting uses the job's T, else the library T, for T/H/D. Renumbering never
changes the library. Tools a document's runs used: <home>/jobs/used/
<document_id>.json = [tool_id].

Errors are ToolLibError(code, message): unknown_tool, duplicate_t,
out_of_range, invalid_field, unknown_holder, duplicate_tool,
bad_document_id, no_library.
"""
import copy
import json
import os
import re

DEFAULT_POCKETS = 12
DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TOOL_TYPES = ("flat", "bull", "ball")
TOL = 0.001

# tools.list / tools.update field -> library entry key ("h"/"d" follow "t")
FIELDS = {"t": "number", "name": "description", "type": "type",
          "dia_mm": "diameter_mm", "corner_r_mm": "corner_radius_mm",
          "flute_len_mm": "flute_mm", "reach_mm": "reach_mm",
          "stickout_mm": "stickout_mm", "holder": "holder", "rpm": "rpm",
          "feed_mm_min": "feed_mm_min", "plunge_mm_min": "plunge_mm_min"}
_POSITIVE = ("flute_mm", "reach_mm", "stickout_mm", "rpm", "feed_mm_min",
             "plunge_mm_min")


class ToolLibError(Exception):
    def __init__(self, code, message, field=None, got=None, allowed=None):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.detail = {"field": field, "got": got, "allowed": allowed}

    def as_dict(self):
        """The agent error {code, message, field?, got?, allowed?,
        next_step} (task f)."""
        import errors
        return errors.make_error(self.code, self.message, **self.detail)


def _read(path):
    with open(path) as fh:
        return json.load(fh)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)


def repo_table_path(repo_root):
    return os.path.join(repo_root, "tools", "x7_tools.json")


def load_library(home, repo_root):
    """The library dict. Without a state dir (unit callers) the repo table,
    read-only; with one, <home>/tools.json, seeded from the repo table."""
    if not home:
        return _read(repo_table_path(repo_root))
    path = os.path.join(home, "tools.json")
    if not os.path.exists(path):
        write_json(path, _read(repo_table_path(repo_root)))
    return _read(path)


def pockets(lib):
    return int(lib.get("pockets") or DEFAULT_POCKETS)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _find(lib, tool_id):
    t = next((t for t in lib.get("tools", [])
              if t.get("tool_id") == tool_id), None)
    if t is None:
        raise ToolLibError("unknown_tool",
                           "no tool %r in the library" % (tool_id,),
                           field="tool_id", got=tool_id,
                           allowed=[x.get("tool_id")
                                    for x in lib.get("tools", [])])
    return t


def _set_t(entry, t):
    entry["number"] = t
    entry["length_offset"] = None if t is None else "H%02d" % t
    entry["diameter_offset"] = None if t is None else "D%02d" % t


def _offset(s):
    m = re.match(r"^[HD](\d+)$", s or "")
    return int(m.group(1)) if m else None


def list_entry(t):
    return {"tool_id": t.get("tool_id"), "t": t.get("number"),
            "h": _offset(t.get("length_offset")),
            "d": _offset(t.get("diameter_offset")),
            "name": t.get("description"), "type": t.get("type"),
            "dia_mm": t.get("diameter_mm"),
            "corner_r_mm": t.get("corner_radius_mm"),
            "flute_len_mm": t.get("flute_mm"), "reach_mm": t.get("reach_mm"),
            "stickout_mm": t.get("stickout_mm"), "holder": t.get("holder"), "rpm": t.get("rpm"),
            "feed_mm_min": t.get("feed_mm_min"),
            "plunge_mm_min": t.get("plunge_mm_min")}


def tools_list(home, repo_root):
    lib = load_library(home, repo_root)
    return {"tools": [list_entry(t) for t in lib.get("tools", [])],
            "pockets": pockets(lib)}


def _check_t(t, n_pockets):
    if not _is_int(t) or not 1 <= t <= n_pockets:
        raise ToolLibError("out_of_range",
                           "T%s is outside 1..%d (pockets)" % (t, n_pockets),
                           field="t", got=t,
                           allowed={"minimum": 1, "maximum": n_pockets})


def _check_library_t(t):
    # TL2 item 3: library T allows 1..999; only job.renumber is 1..pockets.
    if not _is_int(t) or not 1 <= t <= 999:
        raise ToolLibError("out_of_range",
                           "T%s is outside 1..999 (library)" % (t,),
                           field="t", got=t,
                           allowed={"minimum": 1, "maximum": 999})


def update_tool(home, repo_root, tool_id=None, changes=None, new_pockets=None):
    """tools.update: edit one library tool and/or the pocket count. Returns
    {tool: <tools.list entry or null>, pockets}. Saved to <home>/tools.json
    only."""
    if not home:
        raise ToolLibError("no_library", "no state dir for the library")
    lib = load_library(home, repo_root)
    if new_pockets is not None:
        if not _is_int(new_pockets) or not 1 <= new_pockets <= 999:
            raise ToolLibError("out_of_range",
                               "pockets %r is outside 1..999" % (new_pockets,),
                               field="pockets", got=new_pockets,
                               allowed={"minimum": 1, "maximum": 999})
        lib["pockets"] = new_pockets
    out = None
    if tool_id is not None:
        changes = changes or {}
        if not isinstance(changes, dict):
            raise ToolLibError("invalid_field", "changes must be an object",
                               field="changes", got=changes)
        bad = sorted(k for k in changes if k not in FIELDS)
        if bad:
            raise ToolLibError("invalid_field",
                               "not editable: %s (h and d follow t; tool_id "
                               "never changes)" % ", ".join(bad),
                               field=bad[0], allowed=sorted(FIELDS))
        old = _find(lib, tool_id)
        new = copy.deepcopy(old)
        for k, v in changes.items():
            if k == "t":
                if v is not None:
                    _check_library_t(v)
                    other = next((o for o in lib["tools"] if o is not old
                                  and o.get("number") == v), None)
                    if other is not None:
                        raise ToolLibError(
                            "duplicate_t", "T%d is already %s in the library"
                            % (v, other.get("tool_id")), field="t", got=v,
                            allowed={"not": sorted(
                                o.get("number") for o in lib["tools"]
                                if o.get("number") is not None)})
                _set_t(new, v)
            else:
                new[FIELDS[k]] = v
        _validate_shape(new, lib)
        for o in lib["tools"]:
            if o is not old and o.get("type") == new["type"] and \
                    abs(o["diameter_mm"] - new["diameter_mm"]) <= TOL and \
                    abs((o.get("corner_radius_mm") or 0.0)
                        - new["corner_radius_mm"]) <= TOL:
                raise ToolLibError("duplicate_tool",
                                   "same type/diameter/corner as %s"
                                   % o.get("tool_id"), field="dia_mm",
                                   got=new["diameter_mm"])
        old.clear()
        old.update(new)
        out = list_entry(old)
    elif new_pockets is None:
        raise ToolLibError("invalid_field", "give tool_id and/or pockets",
                           field="tool_id")
    write_json(os.path.join(home, "tools.json"), lib)
    return {"tool": out, "pockets": pockets(lib)}


def _validate_shape(e, lib):
    if e.get("type") not in TOOL_TYPES:
        raise ToolLibError("invalid_field", "type must be one of %s"
                           % ", ".join(TOOL_TYPES), field="type",
                           got=e.get("type"), allowed=list(TOOL_TYPES))
    dia, cr = e.get("diameter_mm"), e.get("corner_radius_mm")
    if not _is_num(dia) or dia <= 0:
        raise ToolLibError("invalid_field", "dia_mm must be > 0",
                           field="dia_mm", got=dia,
                           allowed={"exclusive_minimum": 0})
    if not _is_num(cr) or cr < 0:
        raise ToolLibError("invalid_field", "corner_r_mm must be >= 0",
                           field="corner_r_mm", got=cr,
                           allowed={"minimum": 0})
    if e["type"] == "flat" and cr > TOL:
        raise ToolLibError("invalid_field", "a flat has corner_r_mm 0",
                           field="corner_r_mm", got=cr, allowed=[0])
    if e["type"] == "ball" and abs(cr - dia / 2.0) > TOL:
        raise ToolLibError("invalid_field", "a ball has corner_r_mm = dia/2",
                           field="corner_r_mm", got=cr, allowed=[dia / 2.0])
    if e["type"] == "bull" and not 0 < cr < dia / 2.0:
        raise ToolLibError("invalid_field", "a bull needs 0 < corner < dia/2",
                           field="corner_r_mm", got=cr,
                           allowed={"exclusive_minimum": 0,
                                    "exclusive_maximum": dia / 2.0})
    for k in _POSITIVE:
        v = e.get(k)
        if v is not None and (not _is_num(v) or v <= 0):
            raise ToolLibError("invalid_field", "%s must be > 0 or null" % k,
                               field=next(f for f, key in FIELDS.items()
                                          if key == k), got=v,
                               allowed={"exclusive_minimum": 0})
    name = e.get("description")
    if name is not None and (not isinstance(name, str) or len(name) > 120):
        raise ToolLibError("invalid_field", "name must be text <= 120 chars",
                           field="name", allowed={"maxLength": 120})
    h = e.get("holder")
    if h is not None and h not in lib.get("holders", {}):
        raise ToolLibError("unknown_holder",
                           "holder %r is not in the library holders" % (h,),
                           field="holder", got=h,
                           allowed=sorted(lib.get("holders", {})))


# --------------------------------------------------------------- jobs ----

def _job_path(home, doc_id, *sub):
    if not isinstance(doc_id, str) or not DOC_ID_RE.match(doc_id):
        raise ToolLibError("bad_document_id",
                           "document id %r is not [A-Za-z0-9._-], <= 128"
                           % (doc_id,), field="document_id", got=doc_id,
                           allowed={"pattern": DOC_ID_RE.pattern})
    return os.path.join(home, "jobs", *sub, doc_id + ".json")


def _load_job_file(home, doc_id):
    p = _job_path(home, doc_id)
    return _read(p) if os.path.exists(p) else {}


def _save_job_file(home, doc_id, renumber_map, setup):
    obj = dict(renumber_map)
    if setup is not None:
        obj["setup"] = setup  # reserved key: never a tool_id
    write_json(_job_path(home, doc_id), obj)


def load_job(home, doc_id):
    """The job's renumbering {tool_id: T} (the file's `setup` key aside)."""
    return {k: v for k, v in _load_job_file(home, doc_id).items()
            if k != "setup"}


def job_get(home, doc_id):
    if not home:
        raise ToolLibError("no_library", "no state dir for jobs")
    used = _job_path(home, doc_id, "used")
    return {"document_id": doc_id, "renumber": load_job(home, doc_id),
            "tools_used": _read(used) if os.path.exists(used) else [],
            "setup": _load_job_file(home, doc_id).get("setup")}


# job.setup (track 2 c): the setup fields, validated against the cutting
# actions' own catalog specs (mm values). blank = raw blank size or null.
SETUP_FIELDS = ("orientation", "origin", "units", "stock_xy", "stock_x",
                "stock_y", "stock_top", "stock_bottom", "floor_z")


def _validate_setup(setup):
    import catalog as catalog_mod  # connector-local module, no cycle
    if not isinstance(setup, dict):
        raise ToolLibError("invalid_field", "setup must be an object",
                           field="setup")
    bad = sorted(k for k in setup
                 if k not in SETUP_FIELDS + ("blank", "load_limit"))
    if bad:
        raise ToolLibError("invalid_field",
                           "not a setup field: %s" % ", ".join(bad),
                           field="setup." + bad[0],
                           allowed=list(SETUP_FIELDS) + ["blank",
                                                         "load_limit"])
    props = catalog_mod.get_action(catalog_mod.ACTION)["inputs"]["properties"]
    out = {}
    for k in SETUP_FIELDS:
        spec = props[k]
        v = setup.get(k, spec.get("default"))
        if v is None:
            out[k] = None
            continue
        if "enum" in spec:
            if v not in spec["enum"]:
                raise ToolLibError("out_of_range", "%s=%r not in %s"
                                   % (k, v, spec["enum"]),
                                   field="setup." + k, got=v,
                                   allowed={"enum": spec["enum"]})
        else:
            if not _is_num(v):
                raise ToolLibError("invalid_field", "%s must be a number "
                                   "(mm)" % k, field="setup." + k, got=v)
            lo, hi = spec.get("minimum"), spec.get("maximum")
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                raise ToolLibError("out_of_range", "%s=%s outside %s..%s mm"
                                   % (k, v, lo, "" if hi is None else hi),
                                   field="setup." + k, got=v,
                                   allowed={"minimum": lo, "maximum": hi,
                                            "units": "mm"})
        out[k] = v
    blank = setup.get("blank")
    if blank is not None:
        if not isinstance(blank, dict) or set(blank) != {"x", "y", "z"} or \
                not all(_is_num(blank[a]) and blank[a] > 0 for a in "xyz"):
            raise ToolLibError("invalid_field",
                               "blank must be {x, y, z} > 0 mm or null",
                               field="setup.blank", got=blank)
        blank = {a: blank[a] for a in "xyz"}
    out["blank"] = blank
    ll = setup.get("load_limit")   # FL-LOAD: per-document limiter switch
    if ll is not None and not isinstance(ll, bool):
        raise ToolLibError("invalid_field", "load_limit must be true, false "
                           "or null", field="setup.load_limit", got=ll)
    if ll is not None:             # stored only when given (old setups
        out["load_limit"] = ll     # keep their exact shape)
    return out


def setup_load_limit(home, doc_id):
    """The document's saved job.setup load_limit (True/False), or None when
    there is no document, no saved setup or no such field."""
    if not (home and doc_id):
        return None
    try:
        return (_load_job_file(home, doc_id).get("setup") or {}).get(
            "load_limit")
    except (ToolLibError, OSError, ValueError):
        return None


def set_setup(home, doc_id, setup):
    """job.setup: save the document's setup (mm values); returns the job."""
    if not home:
        raise ToolLibError("no_library", "no state dir for jobs")
    _job_path(home, doc_id)  # validates the id first
    clean = _validate_setup(setup)
    _save_job_file(home, doc_id, load_job(home, doc_id), clean)
    return job_get(home, doc_id)


def renumber(home, repo_root, doc_id, tool_id, t):
    """job.renumber: this document's tool_id posts as T `t`. The library is
    never touched; t equal to the library T clears the override."""
    if not home:
        raise ToolLibError("no_library", "no state dir for jobs")
    lib = load_library(home, repo_root)
    tool = _find(lib, tool_id)
    if not (_is_int(t) and t == tool.get("number")):  # back to the library T
        _check_t(t, pockets(lib))                      # is always allowed
    job = load_job(home, doc_id)
    for o in lib["tools"]:
        oid = o.get("tool_id")
        if oid != tool_id and job.get(oid, o.get("number")) == t:
            raise ToolLibError("duplicate_t",
                               "T%d is already %s in this job" % (t, oid),
                               field="t", got=t,
                               allowed={"not": sorted(
                                   job.get(x.get("tool_id"), x.get("number"))
                                   for x in lib["tools"]
                                   if x.get("tool_id") != tool_id and
                                   job.get(x.get("tool_id"),
                                           x.get("number")) is not None)})
    if t == tool.get("number"):
        job.pop(tool_id, None)
    else:
        job[tool_id] = t
    _save_job_file(home, doc_id, job,
                   _load_job_file(home, doc_id).get("setup"))
    return job_get(home, doc_id)


def effective_table(home, repo_root, doc_id=None):
    """The library with the document's job renumbering applied (numbers and
    H/D offsets), as a full table dict (holders included). Two tools on one
    T -> duplicate_t; a job T outside 1..pockets -> out_of_range."""
    lib = load_library(home, repo_root)
    tab = copy.deepcopy(lib)
    job = load_job(home, doc_id) if home and doc_id else {}
    seen = {}
    for e in tab.get("tools", []):
        if e.get("tool_id") in job:
            _check_t(job[e["tool_id"]], pockets(lib))
            _set_t(e, job[e["tool_id"]])
        n = e.get("number")
        if n is not None:
            if n in seen:
                raise ToolLibError("duplicate_t", "T%d is both %s and %s"
                                   % (n, seen[n], e.get("tool_id")),
                                   field="t", got=n)
            seen[n] = e.get("tool_id")
    return tab


def record_used(home, doc_id, table, numbers):
    """Add the tools behind posted/checked T numbers to the job's
    tools_used list."""
    if not home or not doc_id:
        return
    p = _job_path(home, doc_id, "used")
    used = _read(p) if os.path.exists(p) else []
    for n in numbers:
        tid = next((e.get("tool_id") for e in table.get("tools", [])
                    if e.get("number") == n), None)
        if tid and tid not in used:
            used.append(tid)
    write_json(p, used)
