"use strict";
/* CAMBuddy panel: form fields, units and client-side checks. No DOM, no bridge.

   Units rule (connector/catalog.py): when units == "inch" the server multiplies every
   MM_FIELDS value by 25.4 BEFORE its range checks. So every length and feed is shown
   AND sent in the selected unit. Rpm, degrees and numbers are never converted.

   A field's state never changes when the units change, so toggling cannot drift:
     {dflt:true}                    schema default (shown as the unit's own default)
     {mm, src:{unit, value}}        a number the person typed (or a tool filled) in `unit`
     {v}                            enum / integer / degrees
     {empty:true} | {bad:"text"}    blank, or not a number
*/
(function (root) {
  const MM_PER_IN = 25.4;
  const DECIMALS = { inch: 4, mm: 3 };

  const ORIENT_BASE = [
    ["as_modeled", "As modeled"],
    ["flip_x_180", "Flip over X (180°)"],
    ["flip_y_180", "Flip over Y (180°)"],
    ["flip_z_180", "Turn on Z (180°)"],
  ];
  const ORIENT_TIPS = [
    ["rot_x_90", "Tip onto side: +90° about X"],
    ["rot_x_270", "Tip onto side: −90° about X"],
    ["rot_y_90", "Tip onto side: +90° about Y"],
    ["rot_y_270", "Tip onto side: −90° about Y"],
  ];
  const ORIGINS = [
    ["stock_bottom_centre", "Stock bottom centre"],
    ["stock_top_centre", "Stock top centre"],
    ["model_origin", "Model's own origin"],
  ];
  const TOOL_TYPES = [["bull", "Bull nose"], ["flat", "Flat"]];

  // kind: len | feed (MM_FIELDS), int, deg, enum.  mm = schema default (mm).
  // inch = shop default in inch (the round inch number the mm default came from).
  function roughTool(p) {
    return [
      { name: p + "tool_type", kind: "enum", label: "Type", options: TOOL_TYPES, dflt: "bull" },
      { name: p + "tool_diameter", kind: "len", label: "Tool dia", min: 1, max: 32, mm: 12.7, inch: 0.5 },
      { name: p + "corner_radius", kind: "len", label: "Corner radius", min: 0, max: 8, mm: 0.127, inch: 0.005 },
      { name: p + "flute_length", kind: "len", label: "Flute length", min: 1, max: 150, mm: 30, inch: 1.18 },
      { name: p + "stepdown", kind: "len", label: "Stepdown", min: 0.1, max: 25.4, mm: 19.05, inch: 0.75 },
      { name: p + "optimal_load", kind: "len", label: "Optimal load", min: 0.05, max: 10, mm: 2.03, inch: 0.08 },
      { name: p + "stock_to_leave", kind: "len", label: "Stock to leave", min: 0, max: 5, mm: 0.381, inch: 0.015 },
      { name: p + "rest_stepup", kind: "len", label: "Rest step-up", min: 0.1, max: 10, mm: 1.905, inch: 0.075 },
    ];
  }
  const CUTTING = [
    { name: "rpm", kind: "int", label: "Spindle", unitText: "rpm", min: 100, max: 30000, dflt: 7500 },
    { name: "feed", kind: "feed", label: "Feed", min: 10, max: 20000, mm: 3429, inch: 135 },
    { name: "ramp_feed", kind: "feed", label: "Ramp feed", min: 10, max: 20000, mm: 1270, inch: 50 },
    { name: "program_number", kind: "int", label: "Program number", min: 1, max: 9999, dflt: 1001 },
  ];
  const TOOL_NUMBER = { name: "tool_number", kind: "int", label: "Tool number (T)", min: 1, max: 999,
    optional: true, placeholder: "auto" };

  const FORMS = {
    setup: [
      { name: "orientation", kind: "enum", label: "Orientation", options: ORIENT_BASE, dflt: "as_modeled" },
      { name: "origin", kind: "enum", label: "Origin", options: ORIGINS, dflt: "stock_bottom_centre", newInput: true },
      { name: "stock_xy", kind: "len", label: "Extra per side", min: 0, max: 25.4, mm: 1.0, inch: 0.04 },
      { name: "stock_top", kind: "len", label: "Extra on top", min: 0, max: 25.4, mm: 1.0, inch: 0.04 },
      { name: "stock_bottom", kind: "len", label: "Extra on bottom", min: 0, max: 25.4, mm: 1.0, inch: 0.04 },
      { name: "floor_z", kind: "len", label: "Roughing floor", min: 0, max: 200, mm: 0, inch: 0 },
      { name: "stock_x", kind: "len", label: "Side X", min: 0, max: null, optional: true, placeholder: "same" },
      { name: "stock_y", kind: "len", label: "Side Y", min: 0, max: null, optional: true, placeholder: "same" },
    ],
    blank: [
      { name: "blank_x", kind: "len", label: "Blank X", min: 0, max: null, optional: true, local: true },
      { name: "blank_y", kind: "len", label: "Blank Y", min: 0, max: null, optional: true, local: true },
      { name: "blank_z", kind: "len", label: "Blank Z", min: 0, max: null, optional: true, local: true },
    ],
    rough: [TOOL_NUMBER].concat(roughTool(""), CUTTING),
    finish: [
      TOOL_NUMBER,
      { name: "tool_diameter", kind: "len", label: "Ball dia", min: 1, max: 25, mm: 6.0 },
      { name: "stepover", kind: "len", label: "Stepover", min: 0.05, max: 2, mm: 0.3, inch: 0.012 },
      { name: "stepdown", kind: "len", label: "Stepdown", min: 0.05, max: 2, mm: 0.3, inch: 0.012 },
      { name: "slope_threshold", kind: "deg", label: "Steep wall angle", unitText: "°", min: 10, max: 80, dflt: 40 },
    ].concat(CUTTING, [
      { name: "rest_tool_number", kind: "int", label: "Rest ball (T)", min: 1, max: 999, optional: true,
        placeholder: "none" },
      { name: "min_rest", kind: "len", label: "Rest: min leftover", min: 0.1, max: null, mm: 0.5, inch: 0.02 },
    ], roughTool("rough_")),
  };

  function isLen(spec) { return spec.kind === "len" || spec.kind === "feed"; }

  function round(x, d) { return Number(x.toFixed(d)); }
  function numText(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "";
    if (Object.is(n, -0)) n = 0;
    return String(n);
  }
  function unitText(spec, unit) {
    if (spec.kind === "len") return unit === "inch" ? "in" : "mm";
    if (spec.kind === "feed") return unit === "inch" ? "in/min" : "mm/min";
    return spec.unitText || "";
  }

  function initial(spec) {
    if (isLen(spec)) return spec.mm === undefined ? { empty: true } : { dflt: true };
    if (spec.dflt === undefined) return { empty: true };
    return { v: spec.dflt };
  }

  function parse(spec, text, unit) {
    const t = String(text).trim().replace(",", ".");
    if (t === "") return { empty: true };
    const n = Number(t);
    if (!Number.isFinite(n)) return { bad: String(text) };
    if (!isLen(spec)) return { v: n };
    return { mm: unit === "inch" ? n * MM_PER_IN : n, src: { unit, value: n } };
  }

  function fromMm(mm) { return { mm, src: { unit: "mm", value: mm } }; }
  function fromUnit(value, unit) { return { mm: unit === "inch" ? value * MM_PER_IN : value, src: { unit, value } }; }

  // Keep a converted inch value inside the mm range the server checks (v * 25.4).
  function fitInch(v, mm, lim) {
    for (let i = 0; i < 6; i++) {
      const back = v * MM_PER_IN;
      if (lim && lim.min != null && back < lim.min && mm >= lim.min) v += Math.abs(v) * Number.EPSILON || Number.MIN_VALUE;
      else if (lim && lim.max != null && back > lim.max && mm <= lim.max) v -= Math.abs(v) * Number.EPSILON;
      else break;
    }
    return v;
  }

  // -> {text: what the field shows, send: number|string|null (NaN = not a number), mm}
  function view(st, spec, unit, lim) {
    if (st.bad !== undefined) return { text: st.bad, send: NaN, mm: NaN };
    if (st.empty) return { text: "", send: null, mm: null };
    if (!isLen(spec)) return { text: st.v == null ? "" : String(st.v), send: st.v, mm: null };
    let exact, mm;
    if (st.dflt) { mm = spec.mm; exact = unit === "mm" ? spec.mm : spec.inch; }
    else { mm = st.mm; exact = st.src && st.src.unit === unit ? st.src.value : undefined; }
    if (exact !== undefined) {
      return { text: numText(exact), send: exact, mm: unit === "inch" ? exact * MM_PER_IN : exact };
    }
    if (unit === "mm") return { text: numText(round(mm, DECIMALS.mm)), send: round(mm, 6), mm };
    const v = fitInch(mm / MM_PER_IN, mm, lim || spec);
    return { text: numText(round(v, DECIMALS.inch)), send: v, mm };
  }

  // The value the server ends up with, in mm (its own rule: value * 25.4 when inch).
  function serverMm(spec, send, unit) {
    return isLen(spec) && unit === "inch" ? send * MM_PER_IN : send;
  }

  function limText(x, unit, up, spec) {
    if (!isLen(spec)) return numText(x);
    const d = DECIMALS[unit], f = Math.pow(10, d);
    const v = unit === "inch" ? x / MM_PER_IN : x;
    const r = up ? Math.ceil(v * f - 1e-9) / f : Math.floor(v * f + 1e-9) / f;
    return numText(round(r, d));
  }
  function rangeText(spec, lim, unit) {
    const u = unitText(spec, unit);
    const tail = u ? (u === "°" ? "°" : " " + u) : "";
    if (lim.min != null && lim.max != null) {
      return "from " + limText(lim.min, unit, true, spec) + " to " + limText(lim.max, unit, false, spec) + tail;
    }
    if (lim.min != null) return "at least " + limText(lim.min, unit, true, spec) + tail;
    if (lim.max != null) return "at most " + limText(lim.max, unit, false, spec) + tail;
    return "";
  }

  // -> null or a plain sentence naming the field.
  function check(spec, v, unit, lim) {
    const label = spec.label;
    if (v.send === null) return spec.optional ? null : label + " needs a number.";
    if (typeof v.send === "number" && Number.isNaN(v.send)) return label + ": “" + v.text + "” is not a number.";
    if (spec.kind === "enum") return null;
    if (spec.kind === "int" && !Number.isInteger(v.send)) return label + " must be a whole number.";
    const mm = serverMm(spec, v.send, unit);
    if ((lim.min != null && mm < lim.min) || (lim.max != null && mm > lim.max)) {
      return label + " must be " + rangeText(spec, lim, unit) + ".";
    }
    return null;
  }

  function specOf(form, name) { return (FORMS[form] || []).find((s) => s.name === name) || null; }

  root.CAMBuddyFields = {
    MM_PER_IN, DECIMALS, FORMS, ORIENT_BASE, ORIENT_TIPS, ORIGINS,
    isLen, round, numText, unitText, initial, parse, fromMm, fromUnit, view, serverMm,
    rangeText, check, specOf, limText,
  };
})(typeof window !== "undefined" ? window : globalThis);
