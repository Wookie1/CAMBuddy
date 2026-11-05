"use strict";
/* CAMBuddy panel: turns run.result and check.json into a plain Results view.
   Every field is optional: a missing field is skipped, a null shows as "unknown",
   extra fields are ignored. */
(function (root) {
  const MM_PER_IN = 25.4;
  const own = (o, k) => o && typeof o === "object" && Object.prototype.hasOwnProperty.call(o, k);
  const isObj = (o) => o !== null && typeof o === "object" && !Array.isArray(o);
  const num = (x) => typeof x === "number" && Number.isFinite(x);

  // ------------------------------------------------------------ format --
  function minus(s) { return String(s).replace(/^-/, "−"); }
  function len(mm, unit, dIn, dMm) {
    if (!num(mm)) return "unknown";
    return unit === "inch"
      ? minus((mm / MM_PER_IN).toFixed(dIn == null ? 4 : dIn)) + " in"
      : minus(mm.toFixed(dMm == null ? 3 : dMm)) + " mm";
  }
  function coord(mm, unit) {
    return minus(unit === "inch" ? (mm / MM_PER_IN).toFixed(3) : mm.toFixed(2));
  }
  function duration(s) {
    if (!num(s)) return "unknown";
    s = Math.round(s);
    if (s < 60) return s + " s";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h) return h + " h " + String(m).padStart(2, "0") + " min";
    return m + " min" + (r ? " " + r + " s" : "");
  }
  function pct(f) {
    if (!num(f)) return "unknown";
    const p = f <= 1 ? f * 100 : f;
    return (p >= 99.95 || p === Math.round(p) ? Math.round(p) : p.toFixed(1)) + "%";
  }
  function where(w, unit) {
    if (!isObj(w)) return "";
    const parts = [];
    if (w.program) parts.push(String(w.program));
    if (w.line != null) parts.push("line " + w.line);
    const xyz = ["x", "y", "z"].filter((k) => num(w[k])).map((k) => k.toUpperCase() + " " + coord(w[k], unit));
    if (xyz.length) parts.push(xyz.join(" "));
    return parts.join(" · ");
  }
  function item(x, unit) {
    if (x === null || x === undefined) return "unknown";
    if (typeof x !== "object") return String(x);
    if (Array.isArray(x)) return x.map((y) => item(y, unit)).join(", ");
    if (x.code != null && (x.line != null || x.lines != null)) {
      const lines = x.lines != null ? [].concat(x.lines).join(", ") : x.line;
      return x.code + " on line " + lines;
    }
    if (x.__attn) return [x.message || x.code || "unknown", where(x.where, unit)].filter(Boolean).join(" \u00b7 ");
    if (x.message) return String(x.message);
    const w = where(x, unit);
    const rest = Object.keys(x).filter((k) => !["program", "line", "x", "y", "z"].includes(k)).map((k) => {
      const v = x[k];
      if (num(v) && /_mm$/.test(k)) return k.replace(/_mm$/, "").replace(/_/g, " ") + " " + len(v, unit);
      if (num(v) && /_deg$/.test(k)) return k.replace(/_deg$/, "").replace(/_/g, " ") + " " + v + "°";
      if (v !== null && typeof v === "object") return null;
      return k.replace(/_/g, " ") + " " + (v === null ? "unknown" : v);
    }).filter(Boolean);
    return [w].concat(rest).filter(Boolean).join(" · ");
  }

  // ------------------------------------------------------------ lookup --
  const CONTAINERS = [null, "chain", "chained", "gates", "zmap", "checks", "summary", "totals"];
  function lookup(sources, names) {
    for (const src of sources) {
      if (!isObj(src)) continue;
      for (const c of CONTAINERS) {
        const o = c ? src[c] : src;
        if (!isObj(o)) continue;
        for (const n of names) if (own(o, n)) return { found: true, value: o[n] };
      }
    }
    return { found: false, value: undefined };
  }
  function firstNum(o, keys) {
    if (!isObj(o)) return undefined;
    for (const k of keys) if (own(o, k)) return o[k];
    return undefined;
  }

  // -> {state: pass|fail|unknown, n, o}
  function gateOf(v) {
    if (v === null || v === undefined) return { state: "unknown", n: null };
    if (num(v)) return { state: v === 0 ? "pass" : v > 0 ? "fail" : "unknown", n: v };
    if (typeof v === "boolean") return { state: "unknown", n: null };
    if (typeof v === "string") return { state: /^(pass|ok|clear)/i.test(v) ? "pass" : /fail/i.test(v) ? "fail" : "unknown", n: null };
    if (Array.isArray(v)) return { state: v.length ? "fail" : "pass", n: v.length, items: v };
    let n = firstNum(v, ["count", "n", "hits", "total", "found"]);
    if (n === undefined) {
      for (const k of ["items", "list", "places", "where"]) if (Array.isArray(v[k])) { n = v[k].length; break; }
    }
    let state = null;
    for (const k of ["pass", "ok", "passed"]) if (typeof v[k] === "boolean") state = v[k] ? "pass" : "fail";
    if (num(n)) state = (state === "fail" || n > 0) ? "fail" : "pass";
    else if (n === null && state === null) state = "unknown";
    return { state: state || "unknown", n: num(n) ? n : null, o: v };
  }
  function gateDetail(g, unit, extra) {
    if (g.state === "unknown") return "unknown";
    if (g.n === 0) return "none";
    const o = g.o || {};
    const bits = [];
    if (num(g.n)) bits.push(g.n + " found");
    const depth = firstNum(o, ["max_depth", "max_depth_mm", "worst_mm", "depth_mm", "max_intrusion", "max_mm"]);
    if (num(depth) && depth > 0) bits.push("worst " + len(depth, unit));
    if (o.first_line != null) bits.push("first at line " + o.first_line);
    if (extra) bits.push(extra);
    return bits.join(", ") || (g.state === "pass" ? "passed" : "failed");
  }

  const GATES = [
    { label: "Gouges", names: ["zmap_gouges", "chain_zmap_gouges", "chained_zmap_gouges", "gouges"] },
    { label: "Rapid collisions", names: ["rapid_collisions", "chain_rapid_collisions", "chained_rapid_collisions", "rapids"] },
    { label: "Over-flute / shank", names: ["over_flute", "over_flute_shank", "shank"] },
    { label: "Plunge over flute", names: ["plunge_over_flute"] },
    { label: "Holder", names: ["holder_hits", "holder_collisions"] },
    { label: "Probe clcheck", names: ["probe_clcheck", "clcheck"], note: "0 needed" },
    { label: "Outside check area", names: ["outside_grid"] },
  ];

  function leftoverOf(sources) {
    let o = lookup(sources, ["leftover", "chain_leftover", "chained_leftover"]);
    const lv = isObj(o.value) ? o.value : null;
    const pick = (keys, flat) => {
      const v = lv ? firstNum(lv, keys) : undefined;
      if (v !== undefined) return v;
      const f = lookup(sources, flat);
      return f.found ? f.value : undefined;
    };
    const res = {
      mean: pick(["mean_mm", "mean"], ["leftover_mean_mm"]),
      p95: pick(["p95_mm", "p95"], ["leftover_p95_mm"]),
      max: pick(["max_mm", "max"], ["leftover_max_mm"]),
      within: pick(["within_0p5mm_fraction", "within_0p5mm", "within_0p5mm_share"], ["within_0p5mm_fraction", "leftover_within_0p5mm_fraction"]),
    };
    if (!o.found && Object.values(res).every((v) => v === undefined)) return null;
    if (o.found && o.value === null) return { mean: null, p95: null, max: undefined, within: res.within === undefined ? null : res.within };
    return res;
  }

  // ------------------------------------------------------------- build --
  function programModel(p, unit) {
    const c = isObj(p.check) ? p.check : {};
    const rows = [];
    const gate = (label, v, extra, note) => {
      if (v === undefined) return;
      const g = gateOf(v);
      rows.push({ label, state: g.state, detail: gateDetail(g, unit, g.state === "unknown" ? null : extra), note });
    };
    gate("Gouges", c.gouges);
    gate("Rapid collisions", c.rapid_collisions);
    gate("Over-flute / shank", c.over_flute);
    gate("Plunge over flute", c.plunge_over_flute,
      isObj(c.plunge_over_flute) && num(c.plunge_over_flute.flute_mm) ? "flute " + len(c.plunge_over_flute.flute_mm, unit) : null);
    gate("Holder", c.holder_hits);
    gate("Outside check area", c.outside_grid);
    const info = [];
    if (isObj(c.holder)) {
      const h = c.holder;
      if (h.status && h.status !== "checked") rows.push({ label: "Holder check", state: "unknown", detail: "not checked (" + h.status + ")" });
      if (h.dimension_source === "estimated") {
        info.push("Holder size was estimated" + (h.name ? " (" + h.name + ")" : "") + ", not measured. Check the real holder.");
      }
    }
    if (c.axial_plunges !== undefined) {
      const g = gateOf(c.axial_plunges), a = isObj(c.axial_plunges) ? c.axial_plunges : {};
      const floor = num(a.floor_mm) ? " deeper than " + len(a.floor_mm, unit) : "";
      rows.push({ label: "Straight-down plunges", state: g.state === "fail" ? "review" : g.state,
        detail: g.state === "unknown" ? "unknown" : (g.n ? g.n + floor + (a.first_line != null ? ", first at line " + a.first_line : "") : "none" + floor) });
    }
    const eng = isObj(c.engagement) ? c.engagement : null;
    if (eng) {
      const ov = eng.overload_feeds;
      if (ov !== undefined) {
        const g = gateOf(ov);
        const lim = isObj(ov) && num(ov.width_mm_above) ? " (cut wider than " + len(ov.width_mm_above, unit) + ")" : "";
        rows.push({ label: "Overload feeds", state: g.state === "fail" ? "review" : g.state, detail: g.state === "unknown" ? "unknown" : (g.n ? g.n + lim : "none" + lim) });
      }
      const fw = eng.full_width_slots;
      if (fw !== undefined) {
        const g = gateOf(fw);
        const l = isObj(fw) && num(fw.total_length_mm) && fw.total_length_mm > 0 ? ", " + len(fw.total_length_mm, unit, 2, 1) + " long" : "";
        rows.push({ label: "Full-width slots", state: g.state === "fail" ? "review" : g.state, detail: g.state === "unknown" ? "unknown" : (g.n ? g.n + l : "none") });
      }
    }
    if (c.unsupported !== undefined || c.unsupported_codes !== undefined) {
      const u = c.unsupported !== undefined ? c.unsupported : c.unsupported_codes;
      const list = Array.isArray(u) ? u : isObj(u) ? Object.keys(u).map((k) => ({ code: k, lines: u[k] })) : null;
      rows.push({ label: "Codes the check skipped", state: list === null ? "unknown" : list.length ? "review" : "pass",
        detail: list === null ? "unknown" : list.length ? list.map((x) => item(x, unit)).join("; ") : "none" });
    }
    if (isObj(c.cutter_comp)) {
      const n = c.cutter_comp.active_moves;
      rows.push({ label: "Cutter comp", state: "info",
        detail: n == null ? "unknown" : n ? n + " moves with comp on (the check can't judge comp)" : "not used" });
    }
    const plunge = isObj(c.plunge) ? c.plunge : null;
    const flags = plunge && Array.isArray(plunge.flags) ? plunge.flags : [];
    return {
      name: p.name || "program",
      tool: isObj(p.tool) ? p.tool : null,
      rows, info,
      time_s: num(c.cycle_time_s) ? c.cycle_time_s : c.cycle_time_s === null ? null : undefined,
      cut_mm: num(c.cutting_length_mm) ? c.cutting_length_mm : c.cutting_length_mm === null ? null : undefined,
      leftover: leftoverOf([c]),
      plungeTitle: "Ramps steeper than " + (plunge && num(plunge.ramp_angle_deg) ? plunge.ramp_angle_deg + "°" : "the ramp angle"),
      plungeFlags: flags,
    };
  }

  function build(result, check) {
    const r = isObj(result) ? result : {};
    const ck = isObj(check) ? check : null;
    const programs = ck && Array.isArray(ck.programs) ? ck.programs : null;
    const gateSrc = programs ? [r] : [r, ck];
    const env = (own(r, "verdict") || own(r, "attention") || own(r, "summary")) ? r : (ck || {});
    const m = {
      verdict: env.verdict, summary: env.summary,
      attention: [],
      gates: [], warnings: [], lists: [], programs: [],
    };
    // "Left for another operation" arrives as attention items; they go in that list, not under "Good to know".
    const LEFT_CODES = ["area_left_for_next_op"];
    const leftAttn = [];
    for (const a of Array.isArray(env.attention) ? env.attention : []) {
      if (isObj(a) && LEFT_CODES.includes(a.code)) leftAttn.push(Object.assign({ __attn: true }, a));
      else m.attention.push(a);
    }
    // time and cut length
    let t = lookup([r], ["estimated_time_min", "chain_time_min", "time_min", "total_time_min"]);
    if (t.found) m.time_s = num(t.value) ? t.value * 60 : null;
    else {
      t = lookup([r], ["estimated_time_s", "chain_time_s", "cycle_time_s", "time_s"]);
      if (t.found) m.time_s = num(t.value) ? t.value : null;
    }
    const cl = lookup([r], ["cut_length_mm", "chain_cut_length_mm", "cutting_length_mm"]);
    if (cl.found) m.cut_mm = num(cl.value) ? cl.value : null;

    for (const g of GATES) {
      const f = lookup(gateSrc, g.names);
      if (!f.found) continue;
      const s = gateOf(f.value);
      m.gates.push({ label: g.label, state: s.state, detail: gateDetail(s, "inch") , raw: s, note: g.note });
    }
    m.leftover = leftoverOf(gateSrc);

    // warnings
    const eng = lookup(gateSrc, ["engagement", "engagement_report"]);
    if (eng.found && eng.value != null) {
      const e = eng.value;
      const n = Array.isArray(e) ? e.length : num(e.overloads) ? e.overloads : Array.isArray(e.overloads) ? e.overloads.length
        : num(e.overload_count) ? e.overload_count : isObj(e.overload_feeds) ? e.overload_feeds.count : num(e.count) ? e.count : null;
      if (num(n) && n > 0) m.warnings.push({ text: "Tool load over 1.2× optimal in " + n + (n === 1 ? " place" : " places"), mm: firstNum(e, ["limit_mm", "threshold_mm"]) });
      const win = isObj(e) ? (e.reduced_feed_windows || e.feed_windows) : null;
      if (Array.isArray(win) && win.length) m.warnings.push({ text: "Feed is slowed in " + win.length + (win.length === 1 ? " window" : " windows"), items: win });
    }
    const rf = lookup(gateSrc, ["reduced_feed_windows"]);
    if (rf.found && Array.isArray(rf.value) && rf.value.length && !m.warnings.some((w) => w.items)) {
      m.warnings.push({ text: "Feed is slowed in " + rf.value.length + " windows", items: rf.value });
    }
    const pw = lookup(gateSrc, ["plunge_warnings"]);
    if (pw.found && Array.isArray(pw.value) && pw.value.length) m.warnings.push({ text: "Plunge warnings: " + pw.value.length, items: pw.value });
    if (!m.attention.length && Array.isArray(r.warnings)) {
      for (const w of r.warnings) m.warnings.push({ text: typeof w === "string" ? w : item(w, "mm") });
    }
    // lists
    const LISTS = [
      { title: "Codes the check skipped", names: ["unsupported_codes", "unsupported"] },
      { title: "Left for another operation", left: true, names: ["areas_left", "left_for_next_op", "left_for_other_operation", "uncut_areas", "not_machined"] },
    ];
    for (const L of LISTS) {
      const f = lookup(gateSrc, L.names);
      const v = f.found ? f.value : null;
      let items = v == null ? [] : Array.isArray(v) ? v : isObj(v) ? Object.keys(v).map((k) => ({ code: k, lines: v[k] })) : [v];
      if (L.left) items = leftAttn.concat(items);
      if (items.length) m.lists.push({ title: L.title, items });
    }
    if (programs) m.programs = programs.filter(isObj);
    return m;
  }

  // ------------------------------------------------------------ render --
  function h(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  const STATE_TEXT = { pass: "PASS", fail: "FAIL", review: "CHECK", info: "INFO", unknown: "UNKNOWN" };
  function row(label, state, detail) {
    const r = h("div", "gate");
    r.dataset.state = state;
    r.append(h("span", "badge b-" + state, STATE_TEXT[state] || state), h("span", "g-name", label), h("span", "g-detail", detail || ""));
    return r;
  }
  function fact(label, value) {
    const d = h("div", "fact");
    d.append(h("span", "f-label", label), h("span", "f-value", value));
    return d;
  }
  function leftoverFacts(box, lo, unit) {
    if (!lo) return;
    const facts = h("div", "facts");
    if (lo.mean !== undefined) facts.append(fact("Leftover mean", len(lo.mean, unit)));
    if (lo.p95 !== undefined) facts.append(fact("Leftover p95", len(lo.p95, unit)));
    if (lo.max !== undefined) facts.append(fact("Leftover max", len(lo.max, unit)));
    if (lo.within !== undefined) facts.append(fact(unit === "inch" ? "Within 0.5 mm (0.020 in)" : "Within 0.5 mm", pct(lo.within)));
    if (facts.childNodes.length) box.append(facts);
  }
  const VERDICT = {
    ready: ["Ready to run", "pass"], needs_review: ["Needs review", "review"], failed: ["Failed", "fail"],
  };
  const SEVERITY = [["blocker", "Must fix"], ["review", "Please review"], ["info", "Good to know"]];

  function renderAttention(box, list, unit) {
    if (!list.length) return;
    const known = SEVERITY.map((s) => s[0]);
    for (const [sev, title] of SEVERITY.concat([["other", "Notes"]])) {
      const items = list.filter((a) => isObj(a) && (sev === "other" ? !known.includes(a.severity) : a.severity === sev));
      if (!items.length) continue;
      const g = h("div", "attn attn-" + sev);
      g.append(h("h4", null, title + " (" + items.length + ")"));
      const ul = h("ul");
      for (const a of items) {
        const li = h("li");
        li.append(h("div", "a-msg", a.message || a.code || "unknown"));
        const w = where(a.where, unit);
        if (w) li.append(h("div", "a-where", w));
        if (a.next_step) li.append(h("div", "a-next", "Next: " + a.next_step));
        ul.append(li);
      }
      g.append(ul);
      box.append(g);
    }
  }

  function render(m, unit, extra) {
    extra = extra || {};
    const box = h("div", "results");
    const pms = m.programs.map((p) => programModel(p, unit));
    // The badge is never milder than the rows below it.
    const anyFail = m.gates.some((g) => g.state === "fail") || pms.some((pm) => pm.rows.some((r) => r.state === "fail"));
    if (m.verdict != null || m.summary) {
      const said = VERDICT[m.verdict] || [m.verdict == null ? "Result" : String(m.verdict), "unknown"];
      const override = anyFail && m.verdict !== "failed";
      const v = override ? VERDICT.failed : said;
      const head = h("div", "verdict");
      const b = h("span", "vbadge b-" + v[1], v[0]);
      b.dataset.verdict = override ? "failed" : m.verdict == null ? "" : String(m.verdict);
      head.append(b);
      if (m.summary) head.append(h("span", "v-summary", m.summary));
      if (override) {
        head.append(h("span", "v-override", "A safety check below failed, even though the result said \u201c" + said[0] + "\u201d."));
      }
      box.append(head);
    }
    renderAttention(box, m.attention, unit);

    const facts = h("div", "facts");
    if (m.time_s !== undefined) facts.append(fact("Time", duration(m.time_s)));
    if (m.cut_mm !== undefined) facts.append(fact("Cut length", len(m.cut_mm, unit, 1, 1)));
    if (facts.childNodes.length) box.append(facts);

    if (m.gates.length) {
      box.append(h("h4", null, "Safety checks"));
      for (const g of m.gates) {
        const d = gateDetail(g.raw, unit, g.note && g.raw.state !== "unknown" ? g.note : null);
        box.append(row(g.label, g.state, d));
      }
    }
    leftoverFacts(box, m.leftover, unit);
    if (m.warnings.length) {
      box.append(h("h4", null, "Warnings"));
      const ul = h("ul", "warn");
      for (const w of m.warnings) {
        const li = h("li", null, w.text + (num(w.mm) ? " (" + len(w.mm, unit) + ")" : ""));
        if (w.items) {
          const sub = h("ul");
          for (const it of w.items.slice(0, 12)) sub.append(h("li", null, item(it, unit)));
          if (w.items.length > 12) sub.append(h("li", null, "and " + (w.items.length - 12) + " more"));
          li.append(sub);
        }
        ul.append(li);
      }
      box.append(ul);
    }
    for (const L of m.lists) {
      box.append(h("h4", null, L.title));
      const ul = h("ul", "plain");
      for (const it of L.items.slice(0, 20)) ul.append(h("li", null, item(it, unit)));
      if (L.items.length > 20) ul.append(h("li", null, "and " + (L.items.length - 20) + " more"));
      box.append(ul);
    }
    for (const pm of pms) box.append(renderProgram(pm, unit));

    const nc = (extra.files || []).filter((f) => /\.nc$/i.test(f));
    if (nc.length) {
      box.append(h("h4", null, "Programs"));
      const p = h("p", "programs");
      p.append(h("strong", null, nc.join(", ")));
      p.append(document.createTextNode(" — attached to this run in STEVE" +
        (extra.outputDir ? "; also saved on the CAMBuddy computer in " + extra.outputDir : "") + "."));
      box.append(p);
    }
    return box;
  }

  function renderProgram(pm, unit) {
    const sec = h("section", "prog");
    const t = pm.tool;
    let title = pm.name;
    if (t) {
      const bits = [];
      if (t.number != null) bits.push("T" + t.number);
      if (num(t.diameter_mm)) bits.push(len(t.diameter_mm, unit) + (t.type ? " " + t.type : ""));
      else if (t.type) bits.push(t.type);
      if (bits.length) title += " · " + bits.join(" ");
    }
    sec.append(h("h4", null, title));
    const facts = h("div", "facts");
    if (pm.time_s !== undefined) facts.append(fact("Cycle time", duration(pm.time_s)));
    if (pm.cut_mm !== undefined) facts.append(fact("Cut length", len(pm.cut_mm, unit, 1, 1)));
    if (facts.childNodes.length) sec.append(facts);
    for (const r of pm.rows) sec.append(row(r.label, r.state, r.detail));
    for (const i of pm.info) sec.append(row("Holder size", "info", i));
    leftoverFacts(sec, pm.leftover, unit);
    if (pm.plungeFlags.length) {
      sec.append(row(pm.plungeTitle, "review", pm.plungeFlags.length + (pm.plungeFlags.length === 1 ? " place" : " places")));
      const ul = h("ul", "plain flags");
      for (const f of pm.plungeFlags.slice(0, 15)) {
        const bits = [where(f, unit)];
        if (num(f.angle_deg)) bits.push(f.angle_deg + "°");
        if (num(f.depth_mm)) bits.push(len(f.depth_mm, unit) + " deep");
        ul.append(h("li", null, bits.filter(Boolean).join(" · ")));
      }
      if (pm.plungeFlags.length > 15) ul.append(h("li", null, "and " + (pm.plungeFlags.length - 15) + " more"));
      sec.append(ul);
    }
    return sec;
  }

  root.CAMBuddyReport = { build, render, len, duration, pct, where, item, gateOf };
})(typeof window !== "undefined" ? window : globalThis);
