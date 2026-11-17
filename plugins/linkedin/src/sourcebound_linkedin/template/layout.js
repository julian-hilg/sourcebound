/* Places labels that would collide, then measures every slide and writes a report.
   Deterministic: the same deck in the same design gives the same layout. The renderer reads
   #sb-report, then stores the laid-out page without this script and photographs that. */
(function () {
  "use strict";
  var cfg = JSON.parse(document.getElementById("sb-config").textContent);
  var GAP = cfg.min_gap_px, MIN_FONT = cfg.min_font_px;
  var EMPTY = cfg.empty_warn_pct || 25;      // warn when more of a slide's content area than this stays empty
  var remedies = [], problems = [], warnings = [], space = [], faceState = {};
  // Every slide is laid out and measured in one pass. The renderer then stores the page as it
  // stands, without this script; opened by hand, the page shows all slides below each other.
  document.body.classList.add("all");

  function rect(el) { var r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; }
  function ink(el) {                          // the box of the text itself, not of the element that holds it
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), n, out = null, range = document.createRange();
    while ((n = walker.nextNode())) {
      if (!n.textContent.trim()) continue;
      range.selectNodeContents(n);
      Array.prototype.forEach.call(range.getClientRects(), function (r) {
        if (!r.width || !r.height) return;
        out = out ? { l: Math.min(out.l, r.left), t: Math.min(out.t, r.top), r: Math.max(out.r, r.right), b: Math.max(out.b, r.bottom) }
                  : { l: r.left, t: r.top, r: r.right, b: r.bottom };
      });
    }
    if (!out) return rect(el);
    out.w = out.r - out.l; out.h = out.b - out.t; return out;
  }
  function near(a, b, gap) { return a.l < b.r + gap && b.l < a.r + gap && a.t < b.b + gap && b.t < a.b + gap; }
  function slideOf(el) { return Number(el.closest(".slide").dataset.slide); }
  function blockOf(el) { var b = el.closest("[data-block]"); return b ? b.dataset.block : "slide"; }
  function words(el) { return (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60); }
  function remedy(el, what) { remedies.push({ slide: slideOf(el), block: blockOf(el), what: what }); }
  function problem(el, what) { problems.push({ slide: slideOf(el), block: blockOf(el), what: what }); }
  function textWidth(el) {                   // width the text wants on one line
    var range = document.createRange(); range.selectNodeContents(el);
    var old = el.style.whiteSpace; el.style.whiteSpace = "nowrap";
    var w = range.getBoundingClientRect().width; el.style.whiteSpace = old; return w;
  }

  // ---- grown blocks -----------------------------------------------------------------------
  // A block with `grow: true` takes the free height of the slide. Its chart is spread over that
  // height (rows, bars, table rows and numbers get larger, each up to a limit) instead of sitting
  // small in the middle of an empty area. What the limits leave over stays around the chart.
  var ROW_MAX = 2.2, MARK_MAX = 1.6, PAD_MAX = 2.5, SIZE_MAX = 1.8, FONT_MAX = 1.35;
  function px(el, prop) { return parseFloat(getComputedStyle(el)[prop]) || 0; }
  function host(block) { return block.querySelector(":scope > .panel") || block; }   // the box that took the height
  function free(box) {                       // height in `box` its content does not use
    var inner = box.clientHeight - px(box, "paddingTop") - px(box, "paddingBottom"), used = 0;
    Array.prototype.forEach.call(box.children, function (c) {
      if (getComputedStyle(c).display === "none") return;
      used += c.getBoundingClientRect().height + px(c, "marginTop") + px(c, "marginBottom");
    });
    return Math.max(0, inner - used);
  }
  function each(el, sel, fn) { Array.prototype.forEach.call(el.querySelectorAll(sel), fn); }
  function taller(rows, f, rowMax, marks) {  // share `f` px among rows; marks inside grow with their row
    if (!rows.length || f < 1) return;
    var add = f / rows.length;
    rows.forEach(function (r) {
      var h = r.getBoundingClientRect().height, nh = Math.min(h + add, h * rowMax), k = nh / h;
      r.style.minHeight = nh.toFixed(1) + "px";
      if (r.style.height) r.style.height = nh.toFixed(1) + "px";
      marks(r).forEach(function (m) {
        var mh = px(m, "height");
        if (mh > 0) m.style.height = Math.min(mh * k, mh * MARK_MAX).toFixed(1) + "px";
      });
    });
  }
  function grow(block) {
    var box = host(block), f = free(box), c;
    if (f < 8) return;
    var start = f;
    if ((c = box.querySelector(".bars"))) {
      taller(Array.prototype.slice.call(c.querySelectorAll(".row")), f, ROW_MAX, function (r) { return [r.querySelector(".track"), r.querySelector(".bar")]; });
    } else if ((c = box.querySelector(".gantt"))) {
      taller(Array.prototype.slice.call(c.querySelectorAll(".r")), f, ROW_MAX, function (r) { return Array.prototype.slice.call(r.querySelectorAll(".seg:not(.ext)")); });
    } else if ((c = box.querySelector(".win"))) {
      var wr = Array.prototype.slice.call(c.querySelectorAll(".wr"));
      wr.forEach(function (r) { r.style.height = r.getBoundingClientRect().height + "px"; });
      taller(wr, f, ROW_MAX, function (r) { return Array.prototype.slice.call(r.querySelectorAll(".w")); });
    } else if ((c = box.querySelector(".colchart"))) {
      var h = c.getBoundingClientRect().height;
      c.style.height = Math.min(h + f, h * SIZE_MAX).toFixed(1) + "px";
    } else if ((c = box.querySelector(".linechart"))) {
      var lh = c.getBoundingClientRect().height, nh = Math.min(lh + f, lh * SIZE_MAX);
      c.style.height = nh.toFixed(1) + "px";
      each(c, ".end", function (e) { e.style.top = ((nh - 44) * parseFloat(e.dataset.y) / 100).toFixed(1) + "px"; });
    } else if ((c = box.querySelector("table"))) {
      var trs = Array.prototype.slice.call(c.querySelectorAll("tbody tr"));
      if (trs.length) {
        var side = f / trs.length / 2;
        trs.forEach(function (tr) {
          Array.prototype.forEach.call(tr.children, function (td) {
            var t = px(td, "paddingTop"), b = px(td, "paddingBottom");
            td.style.paddingTop = Math.min(t + side, t * PAD_MAX).toFixed(1) + "px";
            td.style.paddingBottom = Math.min(b + side, b * PAD_MAX).toFixed(1) + "px";
          });
        });
      }
    } else if ((c = box.querySelector(".kpis"))) {
      each(c, ".kpi .n", function (n) {                 // larger numbers, as long as each still fits its box
        var size = px(n, "fontSize"), best = size;
        for (var k = FONT_MAX; k > 1.001 && best === size; k -= 0.05) {
          n.style.fontSize = (size * k).toFixed(1) + "px";
          if (n.scrollWidth <= n.clientWidth + 1) best = size * k;
        }
        n.style.fontSize = best.toFixed(1) + "px";
      });
      var kpis = Array.prototype.slice.call(c.children), top = {}, rows = 0;
      kpis.forEach(function (k) { var t = Math.round(k.getBoundingClientRect().top); if (!(t in top)) { top[t] = 1; rows++; } });
      var left = free(box);
      if (rows > 1 && left > 0) c.style.rowGap = (px(c, "rowGap") + Math.min(left / (rows - 1), 120)).toFixed(1) + "px";
    }
    if (free(box) < start - 0.5) remedy(block, "the chart was spread over the height of its grown block");
  }

  // ---- remedies ---------------------------------------------------------------------------
  function bars(el) {
    var rows = Array.prototype.slice.call(el.querySelectorAll(".row"));
    if (!el.hasAttribute("data-fixed") && rows.length) {      // label column as wide as the longest label
      var need = Math.max.apply(null, rows.map(function (r) { return textWidth(r.querySelector(".l")); })) + 18;
      var max = el.getBoundingClientRect().width * 0.45;
      // the standard column stays unless a label needs more; beyond 45 % of the chart labels wrap
      var lw = Math.ceil(Math.min(need, max));
      if (lw > 240) { el.style.setProperty("--lw", lw + "px"); remedy(el, "label column widened to " + lw + " px to fit the labels"); }
    }
    rows.forEach(function (r) {
      var track = rect(r.querySelector(".track")), bar = r.querySelector(".bar"), v = r.querySelector(".v");
      if (rect(v).r <= track.r + 0.5) return;
      if (rect(bar).w >= rect(v).w + 32) {                    // value inside the bar, at its end
        v.classList.add("in"); v.style.left = rect(bar).w + "px";
        remedy(v, "value “" + words(v) + "” moved inside its bar");
      } else problem(v, "the value label “" + words(v) + "” fits neither beside nor inside its bar: lower `max`, or shorten the label");
    });
  }

  function day(el) {
    var labs = Array.prototype.slice.call(el.querySelectorAll(".lab"));
    var box = rect(el);
    function set(lab, below, right) { lab.classList.toggle("below", below); lab.classList.toggle("right", right); }
    function state(lab) { return { below: lab.classList.contains("below"), right: lab.classList.contains("right") }; }
    function clash(lab, placed) {
      var a = ink(lab);
      if (a.l < box.l - 0.5 || a.r > box.r + 0.5) return true;
      return placed.some(function (p) { return near(a, ink(p), GAP); });
    }
    var placed = [];
    labs.forEach(function (lab, i) {
      var s = state(lab), alignSet = lab.hasAttribute("data-align-set");
      var pos = parseFloat(lab.parentNode.style.left) || 0;
      // where the deck says nothing a label sits above the axis and turns towards the middle
      if (!alignSet) s.right = pos > 60;
      set(lab, s.below, s.right);
      if (clash(lab, placed)) {
        var tries = [[!s.below, s.right], [s.below, !s.right], [!s.below, !s.right]], done = false;
        for (var k = 0; k < tries.length && !done; k++) {
          set(lab, tries[k][0], tries[k][1]);
          if (!clash(lab, placed)) { done = true; remedy(lab, "label “" + words(lab) + "” moved " + (tries[k][0] ? "below" : "above") + " the axis, aligned " + (tries[k][1] ? "right" : "left")); }
        }
        if (!done) { set(lab, s.below, s.right); problem(lab, "the label “" + words(lab) + "” overlaps a neighbour on both sides of the axis: spread the events, shorten the text or use fewer"); }
      }
      placed.push(lab);
    });
  }

  function windows(el) {
    Array.prototype.forEach.call(el.querySelectorAll(".wd"), function (d) {
      var track = rect(d.parentNode);
      if (rect(d).r <= track.r + 0.5) return;
      d.style.left = "auto"; d.style.right = "calc(" + (100 - parseFloat(d.dataset.before)) + "% + 12px)";
      if (rect(d).l < track.l - 0.5) problem(d, "the date label “" + words(d) + "” fits on neither side of its bar");
      else remedy(d, "date label “" + words(d) + "” moved to the left of its bar");
    });
  }

  function line(el) {
    var ends = Array.prototype.slice.call(el.querySelectorAll(".end"));
    var plot = rect(el.querySelector(".plot")), moved = false;
    ends.sort(function (a, b) { return ink(a).t - ink(b).t; });
    for (var pass = 0; pass < 20; pass++) {                    // push neighbours apart until they clear
      var changed = false;
      for (var i = 1; i < ends.length; i++) {
        var a = ink(ends[i - 1]), b = ink(ends[i]), over = a.b + GAP + 1 - b.t;
        if (over > 0.5) {
          ends[i - 1].style.top = (parseFloat(getComputedStyle(ends[i - 1]).top) - over / 2) + "px";
          ends[i].style.top = (parseFloat(getComputedStyle(ends[i]).top) + over / 2) + "px";
          changed = moved = true;
        }
      }
      if (!changed) break;
    }
    if (moved) remedy(el, "end labels moved apart");
    ends.forEach(function (e) {
      var r = rect(e);
      if (r.t < plot.t - 24 || r.b > plot.b + 24) problem(e, "too many series end close together: the label “" + words(e) + "” no longer sits at its line");
      if (r.r > rect(el).r + 0.5) problem(e, "the end label “" + words(e) + "” is wider than the label column: shorten it or set `gutter`");
    });
    var ticks = Array.prototype.slice.call(el.querySelectorAll("[data-xt]")), kept = [], dropped = 0;
    ticks.forEach(function (t, i) {                           // thin the x labels until none touch; first and last stay
      var last = i === ticks.length - 1;
      var hit = kept.some(function (k) { return near(rect(k), rect(t), GAP); });
      if (hit && last) { while (kept.length > 1 && near(rect(kept[kept.length - 1]), rect(t), GAP)) { kept.pop().style.display = "none"; dropped++; } kept.push(t); }
      else if (hit) { t.style.display = "none"; dropped++; }
      else kept.push(t);
    });
    if (dropped) remedy(el, dropped + " x-axis labels left out so the rest do not touch");
  }

  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide")).filter(function (s) { return getComputedStyle(s).display !== "none"; });

  function run() {
    slides.forEach(function (s) { Array.prototype.forEach.call(s.querySelectorAll(".block.grow"), grow); });
    slides.forEach(function (s) {
      Array.prototype.forEach.call(s.querySelectorAll(".bars"), bars);
      Array.prototype.forEach.call(s.querySelectorAll(".day"), day);
      Array.prototype.forEach.call(s.querySelectorAll(".win"), windows);
      Array.prototype.forEach.call(s.querySelectorAll(".linechart"), line);
    });
    slides.forEach(measure);
    // Which of the design's typefaces this machine has: a family that is missing draws like the fallback.
    var fonts = {}, ctx = document.createElement("canvas").getContext("2d"), probe = "Hamburgefonstiv 0123456789 mwil";
    function width(font) { ctx.font = font; return ctx.measureText(probe).width; }
    Array.prototype.forEach.call(document.querySelectorAll(".title, .title-cover, p, .exhibit .name"), function (e) {
      getComputedStyle(e).fontFamily.split(",").slice(0, 8).forEach(function (raw) {
        var fam = raw.replace(/["']/g, "").trim();
        if (fam in fonts || /^(serif|sans-serif|monospace|system-ui)$/.test(fam)) return;
        fonts[fam] = width("40px \"" + fam + "\", monospace") !== width("40px monospace") || width("40px \"" + fam + "\", serif") !== width("40px serif");
      });
    });
    // Every @font-face of the page (the design's and the template's), with the names it asks the
    // machine for and whether it loaded: the renderer names the missing ones.
    var faces = [];
    Array.prototype.forEach.call(document.styleSheets, function (sheet) {
      var rules; try { rules = sheet.cssRules; } catch (e) { return; }
      Array.prototype.forEach.call(rules, function (r) {
        if (!(r instanceof CSSFontFaceRule)) return;
        var st = r.style, src = st.getPropertyValue("src") || "", local = [];
        src.replace(/local\(\s*["']?([^"')]+?)["']?\s*\)/g, function (_, name) { local.push(name); return _; });
        var face = { family: unquote(st.getPropertyValue("font-family")), weight: weightOf(st.getPropertyValue("font-weight")),
                     local: local, file: /url\(/.test(src) };
        face.ok = faceState[face.family + "|" + face.weight] === true;
        faces.push(face);
      });
    });
    document.getElementById("sb-report").textContent = JSON.stringify({ slides: slides.length, remedies: remedies, problems: problems, warnings: warnings, space: space, fonts: fonts, faces: faces });
    document.documentElement.setAttribute("data-sb-done", "1");
  }
  function unquote(s) { return String(s || "").replace(/["']/g, "").trim(); }
  function weightOf(w) {
    return String(w || "400").trim().replace(/\bnormal\b/g, "400").replace(/\bbold\b/g, "700").replace(/\s+/g, " ");
  }
  // Load every face once, so that a face the page names but the machine lacks is known as such.
  function loadFaces() {
    if (!document.fonts || !document.fonts.forEach) return Promise.resolve();
    var list = [];
    document.fonts.forEach(function (f) { list.push(f); });
    return Promise.all(list.map(function (f) {
      return f.load().then(function () { return true; }, function () { return false; });
    })).then(function (oks) {
      list.forEach(function (f, i) { var k = unquote(f.family) + "|" + weightOf(f.weight); faceState[k] = faceState[k] === true || oks[i]; });
    });
  }

  // ---- measuring --------------------------------------------------------------------------
  function hex(color) {
    var m = /rgba?\(([^)]+)\)/.exec(color); if (!m) return null;
    var p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (p.length > 3 && p[3] === 0) return null;
    return "#" + p.slice(0, 3).map(function (n) { return ("0" + Math.round(n).toString(16)).slice(-2); }).join("");
  }

  function measure(s) {
    var box = rect(s), seen = {};
    function once(el, what) { var key = slideOf(el) + "|" + what; if (!seen[key]) { seen[key] = 1; problem(el, what); } }

    // the title: at most three lines
    var title = s.querySelector(".title");
    if (title) {
      var lines = Math.round(rect(title).h / parseFloat(getComputedStyle(title).lineHeight));
      if (lines > 3) problem(title, "the title runs to " + lines + " lines (at most 3): shorten it");
    }
    // nothing leaves the slide, nothing is squeezed out of the body
    var body = s.querySelector(".body"), foot = s.querySelector(".foot");
    if (body && foot) {
      var last = body.lastElementChild;
      if (last && rect(last).b > rect(foot).t - 16 + 0.5) problem(last, "the content is " + Math.ceil(rect(last).b - rect(foot).t + 16) + " px too tall for the slide: remove a block, shorten texts, or split the slide");
      if (rect(foot).b > box.b - 24) problem(foot, "the footer is pushed off the slide");
      // how much of the content area stays empty: below the last block, inside grown blocks
      // (what their limits left over), and where a pushed block left a gap
      var top = rect(body).t + px(body, "paddingTop"), bottom = rect(body).b - px(body, "paddingBottom");
      var blocks = Array.prototype.filter.call(body.children, function (b) { return getComputedStyle(b).display !== "none"; });
      if (blocks.length && bottom - top > 0) {
        var empty = Math.max(0, bottom - rect(blocks[blocks.length - 1]).b);
        blocks.forEach(function (b, i) {
          if (b.classList.contains("grow")) empty += free(host(b));
          if (i && b.classList.contains("push")) empty += Math.max(0, rect(b).t - rect(blocks[i - 1]).b - 64);
        });
        var pct = Math.round(empty / (bottom - top) * 100 / 5) * 5;
        space.push({ slide: Number(s.dataset.slide), empty_pct: pct });
        if (pct >= EMPTY) warnings.push({ slide: Number(s.dataset.slide), block: "slide",
          what: "about " + pct + " % of the content area is empty: let an exhibit take the height (`grow: true`), add a block, or merge slides" });
      }
    }
    Array.prototype.forEach.call(s.querySelectorAll("*"), function (el) {
      var cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") return;
      var r = rect(el);
      if (r.w === 0 && r.h === 0) return;
      var ownText = Array.prototype.some.call(el.childNodes, function (n) { return n.nodeType === 3 && n.textContent.trim(); });
      if (ownText || el.tagName === "IMG" || el.hasAttribute("data-mark")) {
        if (r.l < box.l - 0.5 || r.r > box.r + 0.5 || r.t < box.t - 0.5 || r.b > box.b + 0.5) once(el, "“" + (words(el) || el.tagName.toLowerCase()) + "” is cut off at the edge of the slide");
      }
      if (ownText) {
        if (parseFloat(cs.fontSize) < MIN_FONT - 0.01) once(el, "text of " + parseFloat(cs.fontSize) + " px is below the design's minimum of " + MIN_FONT + " px (“" + words(el) + "”)");
        if (el.scrollWidth > el.clientWidth + 1 && cs.overflow !== "visible") once(el, "“" + words(el) + "” overflows its box");
        if (el.hasAttribute("data-fit") && el.scrollWidth > el.clientWidth + 1) once(el, "“" + words(el) + "” is wider than its box: shorten it, or use fewer items per kpis block");
        // a single long word wider than its column
        var parent = el.closest(".cm, .kpi, .collabels div, td, .l, .wl");
        if (parent && rect(el).w > rect(parent).w + 1) once(el, "“" + words(el) + "” is wider than its column");
      }
      // colours: only those of the design
      [["color", ownText], ["backgroundColor", true], ["borderTopColor", parseFloat(cs.borderTopWidth) > 0], ["borderLeftColor", parseFloat(cs.borderLeftWidth) > 0],
       ["borderBottomColor", parseFloat(cs.borderBottomWidth) > 0], ["stroke", el instanceof SVGElement && cs.stroke !== "none"]].forEach(function (p) {
        if (!p[1]) return;
        var h = hex(cs[p[0]]);
        if (h && cfg.colors.indexOf(h) === -1) once(el, "colour " + h + " is not in the design (" + p[0] + " of “" + (words(el) || el.className) + "”)");
      });
    });
    // labels and marks inside one chart must not touch
    Array.prototype.forEach.call(s.querySelectorAll("[data-block]"), function (block) {
      var labels = Array.prototype.filter.call(block.querySelectorAll("[data-label]"), function (l) { return getComputedStyle(l).display !== "none"; });
      var area = rect(block);
      labels.forEach(function (l) {                                       // a label stays inside its own exhibit
        var r = ink(l);
        if (r.t < area.t - 0.5 || r.b > area.b + 0.5 || r.l < area.l - 0.5 || r.r > area.r + 0.5) once(l, "the label \u201c" + words(l) + "\u201d leaves its exhibit and runs into the rest of the slide");
      });
      var marks = Array.prototype.slice.call(block.querySelectorAll("[data-mark]"));
      for (var i = 0; i < labels.length; i++) {
        for (var j = i + 1; j < labels.length; j++) {
          if (near(ink(labels[i]), ink(labels[j]), GAP - 0.5)) once(labels[i], "the labels “" + words(labels[i]) + "” and “" + words(labels[j]) + "” overlap or are closer than " + GAP + " px");
        }
        if (labels[i].classList.contains("in")) continue;                // deliberately inside its own bar
        marks.forEach(function (m) {
          if (m.parentNode === labels[i].parentNode && !labels[i].classList.contains("wd")) return;   // a label next to its own mark
          var a = ink(labels[i]), b = rect(m);
          if (b.w > 0 && b.h > 0 && near(a, b, 0) && m.parentNode !== labels[i].parentNode) once(labels[i], "the label “" + words(labels[i]) + "” lies on a bar");
          if (labels[i].classList.contains("wd") && m.parentNode === labels[i].parentNode && near(a, b, 4)) once(labels[i], "the label “" + words(labels[i]) + "” touches its bar");
        });
      }
    });
  }

  function start() { loadFaces().then(run, run); }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(start); else run();
})();
