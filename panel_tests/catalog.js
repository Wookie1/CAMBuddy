"use strict";
// Independent copy of connector/catalog.py @ 681f551 (catalog_schemas.md), used by the tests and the mock
// parent. "extended" adds the inputs being built in parallel: origin, document_id and the four 90° tips.
(function (root) {
  const MM_FIELDS = ["stock_xy", "stock_x", "stock_y", "stock_top", "stock_bottom", "floor_z", "tool_diameter",
    "corner_radius", "flute_length", "stepdown", "optimal_load", "stock_to_leave", "rest_stepup", "feed", "ramp_feed",
    "stepover", "rough_tool_diameter", "rough_corner_radius", "rough_flute_length", "rough_stepdown",
    "rough_optimal_load", "rough_stock_to_leave", "rough_rest_stepup", "min_rest"];
  const N = (min, max, dflt, type) => ({ type: type || "number", minimum: min, maximum: max, default: dflt });
  const ORIENT = ["as_modeled", "flip_x_180", "flip_y_180", "flip_z_180"];
  const TIPS = ["rot_x_90", "rot_x_270", "rot_y_90", "rot_y_270"];
  const ORIGINS = ["stock_bottom_centre", "stock_top_centre", "model_origin"];
  function roughing(p) {
    return {
      [p + "tool_type"]: { type: "string", enum: ["flat", "bull"], default: "bull" },
      [p + "tool_diameter"]: N(1, 32, 12.7), [p + "corner_radius"]: N(0, 8, 0.127), [p + "flute_length"]: N(1, 150, 30.0),
      [p + "stepdown"]: N(0.1, 25.4, 19.05), [p + "optimal_load"]: N(0.05, 10, 2.03), [p + "stock_to_leave"]: N(0, 5, 0.381),
      [p + "rest_stepup"]: N(0.1, 10, 1.905),
    };
  }
  function catalog(extended) {
    const model = { model: { "x-steve": "file", format: "step", required: true } };
    const orient = { orientation: { type: "string", enum: extended ? ORIENT.concat(TIPS) : ORIENT.slice(), default: "as_modeled" } };
    const stock = { stock_xy: N(0, 25.4, 1.0), stock_x: N(0, null, null), stock_y: N(0, null, null),
      stock_top: N(0, 25.4, 1.0), stock_bottom: N(0, 25.4, 1.0), floor_z: N(0, 200, 0.0) };
    const cutting = { rpm: N(100, 30000, 7500, "integer"), feed: N(10, 20000, 3429.0), ramp_feed: N(10, 20000, 1270.0),
      units: { type: "string", enum: ["inch", "mm"], default: "inch" }, program_number: N(1, 9999, 1001, "integer") };
    const extra = extended ? { origin: { type: "string", enum: ORIGINS, default: "stock_bottom_centre" }, document_id: { type: "string" } } : {};
    return {
      adaptive_rough: Object.assign({}, model, orient, stock, roughing(""), cutting, { tool_number: N(1, 999, null, "integer") }, extra),
      slope_split_finish: Object.assign({}, model, orient, stock,
        { tool_diameter: N(1, 25, 6.0), stepover: N(0.05, 2, 0.3), stepdown: N(0.05, 2, 0.3), slope_threshold: N(10, 80, 40.0) },
        cutting, { tool_number: N(1, 999, null, "integer"), rest_tool_number: N(1, 999, null, "integer"), min_rest: N(0.1, null, 0.5) },
        roughing("rough_"), extra),
      check_program: Object.assign({ program: { "x-steve": "program", required: true } }, model, orient,
        extended ? { origin: { type: "string", enum: ORIGINS, required: true } } : {},
        { stock_xy: stock.stock_xy, stock_x: stock.stock_x, stock_y: stock.stock_y, stock_top: stock.stock_top, stock_bottom: stock.stock_bottom },
        { tool_number: N(1, 999, null, "integer") }),
      "model.measure": Object.assign({}, model, orient),
    };
  }
  // Server rule: MM_FIELDS * 25.4 when units == "inch", BEFORE range checks.
  function toServerMm(inputs) {
    const inch = (inputs.units || "inch") === "inch";
    const out = {};
    for (const k in inputs) out[k] = inch && MM_FIELDS.includes(k) && typeof inputs[k] === "number" ? inputs[k] * 25.4 : inputs[k];
    return out;
  }
  // Mirrors validate_inputs: unknown names, enums, ranges (after the unit rule), integers, bull/flat rules.
  function validate(action, inputs, extended) {
    const props = catalog(extended)[action];
    const problems = [];
    for (const k in inputs) if (!props[k]) problems.push("input_unknown: " + k);
    const mm = toServerMm(inputs);
    for (const k in props) {
      const p = props[k];
      if (!(k in mm)) continue;
      const v = mm[k];
      if (p.enum && !p.enum.includes(v)) problems.push("enum: " + k + "=" + v);
      if (p.type === "number" || p.type === "integer") {
        if (typeof v !== "number" || !Number.isFinite(v)) { problems.push("not a number: " + k); continue; }
        if (p.type === "integer" && !Number.isInteger(v)) problems.push("not an integer: " + k + "=" + v);
        if (p.minimum != null && v < p.minimum) problems.push("input_out_of_range: " + k + "=" + v + " < " + p.minimum);
        if (p.maximum != null && v > p.maximum) problems.push("input_out_of_range: " + k + "=" + v + " > " + p.maximum);
      }
    }
    for (const pre of ["", "rough_"]) {
      if (!((pre + "tool_type") in mm)) continue;
      const cr = mm[pre + "corner_radius"], d = mm[pre + "tool_diameter"];
      if (mm[pre + "tool_type"] === "bull" && !(cr > 0 && cr < d / 2)) problems.push("bull rule: " + pre + "corner_radius=" + cr + " dia=" + d);
      if (mm[pre + "tool_type"] === "flat" && cr !== undefined && cr !== 0) problems.push("flat rule: " + pre + "corner_radius=" + cr);
    }
    return problems;
  }
  const api = { MM_FIELDS, ORIENT, TIPS, ORIGINS, catalog, toServerMm, validate };
  root.CATALOG = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
