"use strict";
// SteveCAM panel 3D viewer (task VIEW3D): display-only rendering of a run's
// view.bin/view.json for runs THIS panel started. WebGL (orbit/pan/zoom,
// layer toggles: part, stock-left heat map with below-part in red, each
// program's path, markers; follows the STEVE light/dark theme). When
// getContext("webgl") returns null an automatic 2D fallback draws a
// height-shaded top view of the stock left plus one draggable section slice
// (along X) from the same data. No network, no storage, no console output.
(function () {
  var live = [];  // mounted viewers (for theme redraws)

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function theme() {
    var dark = document.documentElement.getAttribute("data-theme") === "dark";
    return dark
      ? { bg: [0.086, 0.090, 0.106], css: "#16171b", fg: "#e9e9ee", line: "#3a3b44", part: [0.55, 0.57, 0.62] }
      : { bg: [0.957, 0.957, 0.965], css: "#f4f4f6", fg: "#1b1c20", line: "#d6d7dc", part: [0.62, 0.64, 0.70] };
  }
  // leftover heat: 0 mm -> green, more stock left -> yellow/orange
  function heat(t) {
    t = Math.max(0, Math.min(1, t / 0.6));
    return [0.20 + 0.75 * t, 0.72 - 0.30 * t, 0.32];
  }
  var BELOW = [0.92, 0.16, 0.14];   // stock below the part surface: red
  var PATHC = [0.95, 0.50, 0.10];
  var MARKC = [0.80, 0.20, 0.85];

  function decode(hdr, buf) {
    var dv = new DataView(buf);
    var g = hdr.grid, z = hdr.z, o = hdr.offsets, n = g.nx * g.ny;
    var part = new Float32Array(n), stock = new Float32Array(n);
    var ND = z.nodata === undefined ? -1 : z.nodata;
    for (var i = 0; i < n; i++) {
      var qp = dv.getUint16(o.part + i * 2, true), qs = dv.getUint16(o.stock + i * 2, true);
      part[i] = z.offset + (qp === ND ? 0 : qp) * z.scale;          // no data: grid floor
      stock[i] = qs === ND ? part[i] : z.offset + qs * z.scale;     // no stock: nothing left
    }
    var progs = (hdr.programs || []).map(function (p) {
      var pts = new Float32Array(p.points * 3), fl = new Uint8Array(p.points);
      for (var j = 0; j < p.points; j++) {
        pts[j * 3] = dv.getFloat32(p.xyz_offset + j * 12, true);
        pts[j * 3 + 1] = dv.getFloat32(p.xyz_offset + j * 12 + 4, true);
        pts[j * 3 + 2] = dv.getFloat32(p.xyz_offset + j * 12 + 8, true);
        fl[j] = dv.getUint8(p.flags_offset + j);
      }
      return { name: p.name, pts: pts, flags: fl };
    });
    return { part: part, stock: stock, progs: progs };
  }

  // scene fit: model mm -> roughly [-1, 1]
  function fit(scene, hdr) {
    var g = hdr.grid, lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    lo[0] = g.x0; hi[0] = g.x0 + g.nx * g.cell;
    lo[1] = g.y0; hi[1] = g.y0 + g.ny * g.cell;
    for (var i = 0; i < scene.part.length; i++) {
      if (scene.part[i] < lo[2]) lo[2] = scene.part[i];
      if (scene.stock[i] > hi[2]) hi[2] = scene.stock[i];
    }
    scene.progs.forEach(function (p) {
      for (var j = 0; j < p.pts.length; j += 3)
        for (var k = 0; k < 3; k++) {
          if (p.pts[j + k] < lo[k]) lo[k] = p.pts[j + k];
          if (p.pts[j + k] > hi[k]) hi[k] = p.pts[j + k];
        }
    });
    var c = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
    var span = Math.max(hi[0] - lo[0], hi[1] - lo[1], (hi[2] - lo[2]) * 2, 1);
    return { c: c, s: 1.7 / span };
  }

  var VS = [
    "attribute vec3 aP; attribute vec3 aC;",
    "uniform vec4 uR; uniform vec3 uC; uniform vec4 uT; uniform float uPs;",
    "varying vec3 vC;",
    "void main() {",
    "  vec3 q = (aP - uC) * uT.w;",
    "  float x = q.x * uR.x - q.y * uR.y;",
    "  float y = q.x * uR.y + q.y * uR.x;",
    "  float y2 = y * uR.z - q.z * uR.w;",
    "  float z2 = y * uR.w + q.z * uR.z;",
    "  gl_Position = vec4(x * uT.z + uT.x, y2 * uT.z + uT.y, z2 * 0.05, 1.0);",
    "  gl_PointSize = uPs;",
    "  vC = aC;",
    "}"].join("\n");
  var FS = ["precision mediump float;", "varying vec3 vC;",
    "void main() { gl_FragColor = vec4(vC, 1.0); }"].join("\n");

  function glInit(canvas) {
    var gl = canvas.getContext("webgl", { preserveDrawingBuffer: true, alpha: false });
    if (!gl) return null;
    function sh(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) return null;
      return s;
    }
    var vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) return null;
    var pr = gl.createProgram();
    gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return null;
    gl.useProgram(pr);
    return { gl: gl, pr: pr,
      aP: gl.getAttribLocation(pr, "aP"), aC: gl.getAttribLocation(pr, "aC"),
      uR: gl.getUniformLocation(pr, "uR"), uC: gl.getUniformLocation(pr, "uC"),
      uT: gl.getUniformLocation(pr, "uT"), uPs: gl.getUniformLocation(pr, "uPs") };
  }

  function buildMesh(hdr, scene) {
    // grid surface -> two triangles per cell: [xyz, rgb] per vertex
    function surf(getZ, colFn) {
      var g = hdr.grid, out = [];
      for (var iy = 0; iy < g.ny - 1; iy++) {
        for (var ix = 0; ix < g.nx - 1; ix++) {
          var a = iy * g.nx + ix, b = a + 1, c = a + g.nx, d = c + 1;
          var pts = [[a, b, c], [b, d, c]];
          for (var t = 0; t < 2; t++) {
            for (var v = 0; v < 3; v++) {
              var p = pts[t][v];
              var px = g.x0 + (p % g.nx) * g.cell, py = g.y0 + Math.floor(p / g.nx) * g.cell;
              var col = colFn(p, px, py);
              out.push(px, py, getZ(p), col[0], col[1], col[2]);
            }
          }
        }
      }
      return new Float32Array(out);
    }
    var zmin = 1e9, zmax = -1e9;
    for (var i = 0; i < scene.part.length; i++) {
      if (scene.stock[i] > zmax) zmax = scene.stock[i];
      if (scene.part[i] < zmin) zmin = scene.part[i];
    }
    var partMesh = surf(function (p) { return scene.part[p]; }, function (p) {
      var t = (scene.part[p] - zmin) / Math.max(zmax - zmin, 1e-6);
      return [0.45 + 0.35 * t, 0.47 + 0.35 * t, 0.52 + 0.35 * t];
    });
    var stockMesh = surf(function (p) { return scene.stock[p]; }, function (p) {
      var left = scene.stock[p] - scene.part[p];
      return left < 0 ? BELOW : heat(left);
    });
    var line = [], mark = [];
    scene.progs.forEach(function (pr) {
      for (var j = 0; j + 2 < pr.pts.length; j += 3) {
        if (pr.flags[j / 3] !== pr.flags[j / 3 + 1]) continue;
        line.push(pr.pts[j], pr.pts[j + 1], pr.pts[j + 2], PATHC[0], PATHC[1], PATHC[2],
                  pr.pts[j + 3], pr.pts[j + 4], pr.pts[j + 5], PATHC[0], PATHC[1], PATHC[2]);
      }
    });
    (hdr.markers || []).forEach(function (m) {
      mark.push(m.x, m.y, m.z || 0, MARKC[0], MARKC[1], MARKC[2]);
    });
    return { part: partMesh, stock: stockMesh,
      path: new Float32Array(line), markers: new Float32Array(mark) };
  }

  function mountWebGL(v, canvas) {
    var gi = glInit(canvas);
    if (!gi) return false;
    v.gl = gi.gl;
    canvas.__v3dgl = gi.gl;
    var gl = gi.gl;
    gl.enable(gl.DEPTH_TEST);
    v.cam = { az: -0.7, el: 0.95, zoom: 1, px: 0, py: 0 };
    v.buffers = {};
    Object.keys(v.mesh).forEach(function (k) {
      if (!v.mesh[k].length) return;
      var b = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, v.mesh[k], gl.STATIC_DRAW);
      v.buffers[k] = b;
    });
    v.redraw = function () {
      var th = theme();
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(th.bg[0], th.bg[1], th.bg[2], 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(gi.pr);
      var c = v.cam;
      gl.uniform4f(gi.uR, Math.cos(c.az), Math.sin(c.az), Math.cos(c.el), Math.sin(c.el));
      gl.uniform3f(gi.uC, v.fit.c[0], v.fit.c[1], v.fit.c[2]);
      gl.uniform4f(gi.uT, c.px, c.py, c.zoom, v.fit.s);
      gl.uniform1f(gi.uPs, 7);
      [["part", gl.TRIANGLES], ["stock", gl.TRIANGLES],
       ["path", gl.LINES], ["markers", gl.POINTS]].forEach(function (pair) {
        var key = pair[0];
        if (!v.on[key] || !v.buffers[key]) return;
        gl.bindBuffer(gl.ARRAY_BUFFER, v.buffers[key]);
        gl.enableVertexAttribArray(gi.aP);
        gl.vertexAttribPointer(gi.aP, 3, gl.FLOAT, false, 24, 0);
        gl.enableVertexAttribArray(gi.aC);
        gl.vertexAttribPointer(gi.aC, 3, gl.FLOAT, false, 24, 12);
        gl.drawArrays(pair[1], 0, v.mesh[key].length / 6);
      });
      canvas.dataset.drawn = "1";
    };
    // orbit / pan / zoom
    var drag = null;
    canvas.addEventListener("mousedown", function (e) {
      drag = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button !== 0 };
      e.preventDefault();
    });
    window.addEventListener("mousemove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) {
        v.cam.px += dx * 0.004 / v.cam.zoom;
        v.cam.py -= dy * 0.004 / v.cam.zoom;
      } else {
        v.cam.az += dx * 0.01;
        v.cam.el = Math.max(0.05, Math.min(1.55, v.cam.el + dy * 0.01));
      }
      v.redraw();
    });
    window.addEventListener("mouseup", function () { drag = null; });
    canvas.addEventListener("wheel", function (e) {
      v.cam.zoom = Math.max(0.2, Math.min(8, v.cam.zoom * Math.exp(-e.deltaY * 0.001)));
      e.preventDefault();
      v.redraw();
    }, { passive: false });
    canvas.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    return true;
  }

  function mount2D(v, canvas) {
    var ctx = canvas.getContext("2d");
    if (!ctx) return false;
    var g = v.hdr.grid;
    var topH = canvas.height - 70, cut = Math.floor(g.ny / 2);
    v.cut = cut;
    function mx(x) { return (x - g.x0) / (g.nx * g.cell) * canvas.width; }
    function my(y) { return topH - (y - g.y0) / (g.ny * g.cell) * topH; }
    v.redraw = function () {
      var th = theme();
      ctx.fillStyle = th.css;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      var cw = canvas.width / g.nx, ch = topH / g.ny;
      var zmin = 1e9, zmax = -1e9, i;
      for (i = 0; i < v.scene.part.length; i++) {
        if (v.scene.stock[i] > zmax) zmax = v.scene.stock[i];
        if (v.scene.part[i] < zmin) zmin = v.scene.part[i];
      }
      if (v.on.stock) {
        for (var iy = 0; iy < g.ny; iy++) {
          for (var ix = 0; ix < g.nx; ix++) {
            var p = iy * g.nx + ix;
            var left = v.scene.stock[p] - v.scene.part[p];
            var col = left < 0 ? BELOW : heat(left);
            var sh2 = 0.7 + 0.3 * (v.scene.stock[p] - zmin) / Math.max(zmax - zmin, 1e-6);
            ctx.fillStyle = "rgb(" + Math.round(col[0] * 255 * sh2) + "," +
              Math.round(col[1] * 255 * sh2) + "," + Math.round(col[2] * 255 * sh2) + ")";
            ctx.fillRect(ix * cw, topH - (iy + 1) * ch, Math.ceil(cw), Math.ceil(ch));
          }
        }
      }
      if (v.on.part) {  // part outline shading (slope darkens)
        ctx.fillStyle = "rgba(90,95,110,0.35)";
        for (var jy = 0; jy < g.ny; jy++) {
          for (var jx = 0; jx < g.nx; jx++) {
            var q = jy * g.nx + jx;
            var grad = Math.abs(v.scene.part[q] - v.scene.part[Math.max(q - 1, 0)]) +
              Math.abs(v.scene.part[q] - v.scene.part[Math.max(q - g.nx, 0)]);
            if (grad > 0.15) ctx.fillRect(jx * cw, topH - (jy + 1) * ch, Math.ceil(cw), Math.ceil(ch));
          }
        }
      }
      if (v.on.path) {
        v.scene.progs.forEach(function (pr) {
          ctx.strokeStyle = "rgb(242,128,26)";
          ctx.lineWidth = 1.5;
          for (var j = 0; j + 2 < pr.pts.length; j += 3) {
            if (pr.flags[j / 3] !== pr.flags[j / 3 + 1]) continue;
            ctx.setLineDash(pr.flags[j / 3] ? [] : [3, 3]);
            ctx.beginPath();
            ctx.moveTo(mx(pr.pts[j]), my(pr.pts[j + 1]));
            ctx.lineTo(mx(pr.pts[j + 3]), my(pr.pts[j + 4]));
            ctx.stroke();
          }
          ctx.setLineDash([]);
        });
      }
      if (v.on.markers) {
        (v.hdr.markers || []).forEach(function (m) {
          ctx.strokeStyle = "rgb(204,51,217)";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(mx(m.x), my(m.y), 5, 0, 6.29);
          ctx.stroke();
        });
      }
      // section slice along X at row v.cut: draggable line + profile strip
      var secY = topH - (v.cut + 0.5) * ch;
      ctx.strokeStyle = th.fg;
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 3]);
      ctx.beginPath(); ctx.moveTo(0, secY); ctx.lineTo(canvas.width, secY); ctx.stroke();
      ctx.setLineDash([]);
      var stripTop = topH + 4, stripH = canvas.height - stripTop - 4;
      ctx.strokeStyle = th.line;
      ctx.strokeRect(0.5, stripTop + 0.5, canvas.width - 1, stripH);
      function prof(getZ, col) {
        ctx.strokeStyle = col;
        ctx.beginPath();
        for (var ix = 0; ix < g.nx; ix++) {
          var p = v.cut * g.nx + ix;
          var yy = stripTop + stripH - (getZ(p) - zmin) / Math.max(zmax - zmin, 1e-6) * stripH;
          if (ix === 0) ctx.moveTo(ix / (g.nx - 1) * canvas.width, yy);
          else ctx.lineTo(ix / (g.nx - 1) * canvas.width, yy);
        }
        ctx.stroke();
      }
      prof(function (p) { return v.scene.stock[p]; }, "rgb(60,120,200)");
      prof(function (p) { return v.scene.part[p]; }, "rgb(120,124,140)");
      canvas.dataset.drawn = "1";
    };
    var drag = false;
    canvas.addEventListener("mousedown", function (e) { drag = true; move(e); e.preventDefault(); });
    window.addEventListener("mousemove", function (e) { if (drag) move(e); });
    window.addEventListener("mouseup", function () { drag = false; });
    function move(e) {
      var r = canvas.getBoundingClientRect();
      var y = e.clientY - r.top;
      if (y < 0 || y > topH) return;
      v.cut = Math.max(0, Math.min(g.ny - 1, Math.floor((topH - y) / topH * g.ny)));
      v.redraw();
    }
    return true;
  }

  function mount(container, hdr, scene, binBuf) {
    var wrap = el("div", "v3d");
    var canvas = el("canvas", "v3d-canvas");
    canvas.width = 420; canvas.height = 300;
    var tools = el("div", "v3d-tools");
    var status = el("div", "v3d-status", "");
    var v = { hdr: hdr, scene: scene, on: { part: true, stock: true, path: true, markers: true },
      fit: fit(scene, hdr), mesh: null, gl: null, redraw: null };
    function toggle(cls, key) {
      var cb = el("input", cls);
      cb.type = "checkbox"; cb.checked = true;
      cb.addEventListener("change", function () {
        v.on[key] = cb.checked;
        if (v.redraw) v.redraw();
      });
      var lbl = el("label", null);
      lbl.append(cb, document.createTextNode(" " + key));
      tools.append(lbl);
    }
    toggle("v3d-part", "part");
    toggle("v3d-stock", "stock");
    toggle("v3d-path", "path");
    toggle("v3d-markers", "markers");
    wrap.append(canvas, tools, status);
    container.append(wrap);
    v.mesh = buildMesh(hdr, scene);
    canvas.dataset.mode = "2d";
    if (mountWebGL(v, canvas)) canvas.dataset.mode = "webgl";
    else mount2D(v, canvas);
    var npts = scene.progs.reduce(function (s, p) { return s + p.pts.length / 3; }, 0);
    status.textContent = (canvas.dataset.mode === "webgl" ? "3D view: " : "2D fallback: ") +
      hdr.grid.nx + "\u00d7" + hdr.grid.ny + " cells, " + npts + " path points, " +
      (hdr.markers || []).length + " markers";
    if (v.redraw) v.redraw();
    live.push(v);
    return v;
  }

  var api = {
    // a run the panel did NOT start: a plain note, never the viewer
    noteInto: function (box) {
      if (box.querySelector(".v3d-note")) return;
      box.append(el("p", "v3d-note",
        "3D view: this run was not started in this panel, so its files are not available here."));
    },
    // mount the viewer into a finished run the panel started
    attach: function (card, run, files, call) {
      if (!files || files.indexOf("view.bin") < 0 || files.indexOf("view.json") < 0) return;
      if (card.v3dRun === String(run.id)) {
        if (card.v3dEl && card.v3dEl.parentNode !== card.results) card.results.append(card.v3dEl);
        return;
      }
      card.v3dRun = String(run.id);
      var holder = el("div");
      card.v3dEl = holder;
      card.results.append(holder);
      var fail = function (why) {
        holder.replaceChildren(el("p", "v3d-note", "3D view unavailable: " + why));
      };
      Promise.all([
        call("run.file", { id: run.id, name: "view.json" }),
        call("run.file", { id: run.id, name: "view.bin" })
      ]).then(function (res) {
        if (!res[0] || !res[0].blob || !res[1] || !res[1].blob) return fail("no view data");
        return res[0].blob.text().then(function (txt) {
          return res[1].blob.arrayBuffer().then(function (buf) {
            var hdr = JSON.parse(txt);
            if (hdr.format !== "stevecam-view" || hdr.version !== 1) return fail("unknown view format");
            mount(holder, hdr, decode(hdr, buf), buf);
          });
        });
      }, function () { fail("the run files could not be read"); });
    },
    theme: function () { live.forEach(function (v) { if (v.redraw) v.redraw(); }); }
  };
  window.SteveCAMViewer = api;
})();
