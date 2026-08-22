/* Схема маршрутов и клякса-алфавит на главной.
 *
 * Скрипт — надстройка: разметка в route_map.html уже читаема без него, здесь
 * она заменяется схемой на широком экране и вертикальной линией на телефоне.
 * Данные приходят из apps/school/schematic.py через json_script, поэтому
 * ни одного языка, уровня или набора тут не придумывается.
 */
(function () {
  "use strict";

  var data = document.getElementById("rt-data");
  var root = document.querySelector("[data-route]");
  if (!data || !root) return;

  var schematic;
  try {
    schematic = JSON.parse(data.textContent);
  } catch (error) {
    return; // без данных остаётся серверный список — он рабочий
  }
  if (!schematic.lines || !schematic.lines.length) return;

  var LEVELS = schematic.levels;
  var LINES = schematic.lines;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  var picker = root.querySelector("[data-picker]");
  var mapBox = root.querySelector("[data-map]");
  var list = root.querySelector("[data-list]");
  var washBox = root.querySelector("[data-wash]");
  var washCanvas = root.querySelector("[data-wash-canvas]");
  var washGlyph = root.querySelector("[data-wash-glyph]");
  var washName = root.querySelector("[data-wash-name]");

  var active = LINES[0];

  /* ---------- Геометрия схемы ---------- */

  var SVG_NS = "http://www.w3.org/2000/svg";
  var NAME_X = 228;
  var ALONG_0 = 258;
  var LANE_STEP = 46;
  var LANE_TOP = 76;

  var along = function (index) {
    var step = LEVELS.length > 1 ? (1100 - ALONG_0) / (LEVELS.length - 1) : 0;
    return ALONG_0 + index * step;
  };
  // Линии с веткой занимают две полосы: ветка уходит вверх, и без свободной
  // полосы над ней она наезжает на шкалу уровней или на соседний язык.
  var SLOTS = (function () {
    var slots = {};
    var slot = 0;
    LINES.forEach(function (line) {
      if (line.branch) slot += 1;
      slots[line.id] = slot;
      slot += 1;
    });
    return slots;
  })();
  var SLOT_COUNT = (function () {
    var max = 0;
    for (var id in SLOTS) max = Math.max(max, SLOTS[id]);
    return max + 1;
  })();
  var lane = function (slot) { return LANE_TOP + slot * LANE_STEP; };

  function node(name, attrs, text) {
    var element = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      if (attrs[key] !== undefined && attrs[key] !== null) element.setAttribute(key, attrs[key]);
    }
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function open(url) { window.location.href = url; }

  function buildMap() {
    var height = lane(SLOT_COUNT - 1) + 92;
    var svg = node("svg", {
      viewBox: "0 0 1160 " + height,
      role: "img",
      "aria-label": "Схема языков школы по уровням"
    });

    var scale = node("g", {});
    var tracks = node("g", {});
    var names = node("g", {});
    var groups = node("g", {});
    svg.appendChild(scale);
    svg.appendChild(tracks);
    svg.appendChild(names);
    svg.appendChild(groups);

    // Шкала уровней — она же колонки схемы, поэтому подписи у каждой станции
    // не нужны: уровень читается по вертикали.
    scale.appendChild(node("text", { class: "rt-scale", x: NAME_X, y: 30, "text-anchor": "end" }, "УРОВЕНЬ"));
    LEVELS.forEach(function (level, index) {
      var x = along(index);
      scale.appendChild(node("text", { class: "rt-scale", x: x, y: 30, "text-anchor": "middle" }, level));
      scale.appendChild(node("line", { class: "rt-guide", x1: x, y1: 46, x2: x, y2: height - 46 }));
    });

    LINES.forEach(function (line) {
      var y = lane(SLOTS[line.id]);
      var path = node("path", {
        class: "rt-track",
        d: "M" + along(line.from_index) + " " + y + " L" + along(line.to_index) + " " + y,
        stroke: line.color,
        "stroke-width": 9
      });
      tracks.appendChild(path);
      line._path = path;

      var label = node("text", {
        class: "rt-name", x: NAME_X, y: y + 6, fill: line.color, "text-anchor": "end"
      }, line.name.toUpperCase());
      names.appendChild(label);
      line._label = label;

      var group = node("g", { class: "rt-group" });
      groups.appendChild(group);
      line._group = group;

      // Ветка подготовки к экзамену — настоящее ветвление, отсюда и поворот под 45°.
      if (line.branch) {
        var branchY = y - LANE_STEP;
        var start = along(line.branch.from_index);
        var end = along(line.branch.to_index);
        group.appendChild(node("path", {
          d: "M" + start + " " + y + " L" + (start + LANE_STEP) + " " + branchY + " L" + end + " " + branchY,
          stroke: line.color, "stroke-width": 9, fill: "none",
          "stroke-linecap": "round", "stroke-linejoin": "round"
        }));
        group.appendChild(node("circle", {
          cx: end, cy: branchY, r: 12, fill: line.color, stroke: "#F2EFE7", "stroke-width": 3.5
        }));
        group.appendChild(node("text", {
          class: "rt-name", x: end, y: branchY - 22, fill: line.color,
          "text-anchor": "middle", "font-size": 17
        }, line.branch.name.toUpperCase()));
      }

      for (var index = line.from_index; index <= line.to_index; index++) {
        var x = along(index);
        var last = index === line.to_index;
        var stop = node("g", { class: "rt-stop", tabindex: "0", role: "button" });
        stop.appendChild(node("title", {}, line.name + ", уровень " + LEVELS[index]));
        stop.appendChild(node("circle", {
          cx: x, cy: y, r: last ? 12 : 9,
          fill: last ? line.color : "#182430", stroke: "#F2EFE7", "stroke-width": 3.5
        }));
        (function (url) {
          stop.addEventListener("click", function () { open(url); });
          stop.addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(url); }
          });
        })(line.url);
        group.appendChild(stop);
      }

      line.marks.forEach(function (mark) {
        var x = along(mark.index);
        var text = mark.schedule + " · " + mark.seats + " " + mark.seats_word;
        var width = text.length * 8.2 + 26;
        // Выноска у станции с веткой уходит вниз: сверху её перекрыл бы поворот.
        var below = !!(line.branch && mark.index === line.branch.from_index);
        var boxX = Math.max(NAME_X + 18, Math.min(x - 26, 1160 - width - 12));
        var boxY = below ? y + 24 : y - 52;
        group.appendChild(node("line", {
          class: "rt-leader", x1: x, y1: below ? y + 12 : boxY + 28, x2: x, y2: below ? boxY : y - 12
        }));
        group.appendChild(node("rect", { class: "rt-flagbox", x: boxX, y: boxY, width: width, height: 28, rx: 6 }));
        var flag = node("text", {
          class: "rt-flagtext", x: boxX + width / 2, y: boxY + 19, "text-anchor": "middle"
        }, text);
        group.appendChild(flag);
      });
    });

    mapBox.textContent = "";
    mapBox.appendChild(svg);
    mapBox.hidden = false;
  }

  function drawLine(line) {
    if (reduced.matches || !line._path.getTotalLength) return;
    var length = line._path.getTotalLength();
    line._path.style.transition = "none";
    line._path.style.strokeDasharray = length;
    line._path.style.strokeDashoffset = length;
    void line._path.getBoundingClientRect(); // иначе браузер склеит два состояния в одно
    line._path.style.transition = "stroke-dashoffset .62s cubic-bezier(.22,.61,.36,1)";
    line._path.style.strokeDashoffset = 0;
  }

  /* ---------- Вертикальная линия на телефоне ---------- */

  var rail = document.createElement("div");
  rail.className = "rt__rail";
  list.parentNode.insertBefore(rail, list.nextSibling);

  function buildRail() {
    rail.textContent = "";
    rail.style.setProperty("--line-color", active.color);
    for (var index = active.from_index; index <= active.to_index; index++) {
      var last = index === active.to_index;
      var mark = active.marks.filter(function (m) { return m.index === index; })[0];
      var item = document.createElement("button");
      item.type = "button";
      item.className = "rt-rail__item" + (last ? " is-end" : "");
      item.innerHTML =
        '<span class="rt-rail__mark"><span class="rt-rail__dot"></span></span>' +
        '<span class="rt-rail__body">' +
          '<span class="rt-rail__lvl">' + LEVELS[index] + (last ? " · конечная" : "") + "</span>" +
          (mark ? '<span class="rt-rail__flag">' + mark.schedule + " · " + mark.seats + " " + mark.seats_word + "</span>" : "") +
        "</span>";
      (function (url) {
        item.addEventListener("click", function () { open(url); });
      })(mark ? mark.url : active.url);
      rail.appendChild(item);
    }
  }

  /* ---------- Клякса-алфавит ---------- */

  var washSheet = document.createElement("canvas");
  var washCtx = null;
  var trail = [];
  var pos = { x: 150, y: 150 };
  var target = { x: 150, y: 150 };
  var frame = null;

  function jitter(seed) { var x = Math.sin(seed * 127.1) * 43758.5453; return x - Math.floor(x); }

  function fitWash() {
    var box = washCanvas.getBoundingClientRect();
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    washCanvas.width = Math.max(1, Math.round(box.width * ratio));
    washCanvas.height = Math.max(1, Math.round(box.height * ratio));
    var ctx = washCanvas.getContext("2d");
    ctx.setTransform(washCanvas.width / 300, 0, 0, washCanvas.height / 300, 0, 0);
    return ctx;
  }

  function blot(ctx, x, y, color, radius, alpha) {
    var grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
    grad.addColorStop(0, color);
    grad.addColorStop(0.55, color);
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.globalAlpha = alpha;
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function dark() { return document.documentElement.getAttribute("data-theme") === "dark"; }
  function ground() {
    return getComputedStyle(document.body).getPropertyValue("--paper").trim() || "#FBFCFD";
  }

  // Заливка пишется один раз в офскрин: перерисовывать её каждый кадр дорого,
  // а затирать полупрозрачным фоном — значит получить грязь вместо акварели.
  function buildSheet() {
    washSheet.width = 300;
    washSheet.height = 300;
    var ctx = washSheet.getContext("2d");
    ctx.clearRect(0, 0, 300, 300);
    var index = LINES.indexOf(active);
    var night = dark();
    [
      { line: active, x: 144, y: 132, r: 112 },
      { line: LINES[(index + 1) % LINES.length], x: 76, y: 214, r: 74 },
      { line: LINES[(index + LINES.length - 1) % LINES.length], x: 228, y: 206, r: 70 },
      { line: LINES[(index + 3) % LINES.length], x: 214, y: 74, r: 60 }
    ].forEach(function (spot, order) {
      blot(ctx, spot.x + (jitter(order * 4.4) * 14 - 7), spot.y + (jitter(order * 7.1) * 14 - 7),
           spot.line.color, spot.r,
           order === 0 ? (night ? 0.46 : 0.4) : (night ? 0.3 : 0.24));
    });
  }

  function renderWash() {
    if (!washCtx) return;
    var night = dark();
    washCtx.globalCompositeOperation = "source-over";
    washCtx.fillStyle = ground();
    washCtx.fillRect(0, 0, 300, 300);
    washCtx.drawImage(washSheet, 0, 0, 300, 300);
    washCtx.globalCompositeOperation = night ? "screen" : "multiply";
    trail.forEach(function (point, index) {
      var weight = (index + 1) / trail.length;
      blot(washCtx, point.x, point.y, point.color, 24 + weight * 42, (night ? 0.09 : 0.12) * weight);
    });
    // Мягкая маска: без неё пятно обрезается прямоугольником по краю холста.
    washCtx.globalCompositeOperation = "destination-out";
    [[150, 146, 92, 158], [116, 178, 74, 132], [190, 118, 70, 128]].forEach(function (mask) {
      var grad = washCtx.createRadialGradient(mask[0], mask[1], mask[2], mask[0], mask[1], mask[3]);
      grad.addColorStop(0, "rgba(0,0,0,0)");
      grad.addColorStop(1, "rgba(0,0,0,0.62)");
      washCtx.fillStyle = grad;
      washCtx.fillRect(0, 0, 300, 300);
    });
    washCtx.globalCompositeOperation = "source-over";
  }

  function washTick() {
    pos.x += (target.x - pos.x) * 0.18;
    pos.y += (target.y - pos.y) * 0.18;
    var last = trail[trail.length - 1];
    // Курсор стоит — след стекает, а не выжигает пятно на одном месте.
    if (!last || Math.hypot(pos.x - last.x, pos.y - last.y) > 1.6) {
      trail.push({ x: pos.x, y: pos.y, color: active.color });
    } else if (trail.length) {
      trail.shift();
    }
    if (trail.length > 24) trail.shift();
    renderWash();
    frame = window.requestAnimationFrame(washTick);
  }

  function refreshWash() {
    washCtx = fitWash();
    buildSheet();
    renderWash();
    if (!reduced.matches && frame === null) frame = window.requestAnimationFrame(washTick);
  }

  washBox.addEventListener("pointermove", function (event) {
    var box = washBox.getBoundingClientRect();
    var clamp = function (value) { return Math.max(56, Math.min(244, value)); };
    target = {
      x: clamp(((event.clientX - box.left) / box.width) * 300),
      y: clamp(((event.clientY - box.top) / box.height) * 300)
    };
    if (reduced.matches) {
      pos = { x: target.x, y: target.y };
      trail = [{ x: target.x, y: target.y, color: active.color }];
      renderWash();
    }
  });

  washBox.setAttribute("data-clickable", "");
  washBox.addEventListener("click", function () {
    setActive(LINES[(LINES.indexOf(active) + 1) % LINES.length]);
  });

  /* ---------- Сборка ---------- */

  function setActive(line) {
    active = line;
    LINES.forEach(function (other) {
      var on = other === line;
      other._path.setAttribute("stroke-width", on ? 11 : 7);
      other._path.classList.toggle("is-dim", !on);
      other._group.classList.toggle("is-on", on);
      other._label.classList.toggle("is-dim", !on);
      other._label.setAttribute("font-size", on ? 20 : 17);
    });
    line._path.parentNode.appendChild(line._path); // активная линия поверх остальных
    drawLine(line);
    buildRail();
    washGlyph.textContent = line.glyph;
    washName.textContent = line.name.toLowerCase();
    if (washCtx) { buildSheet(); renderWash(); }
    Array.prototype.forEach.call(picker.children, function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.line === line.id));
    });
  }

  LINES.forEach(function (line) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "rt-pick";
    button.dataset.line = line.id;
    button.style.setProperty("--line-color", line.color);
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = '<i></i>' + line.name;
    button.addEventListener("click", function () { setActive(line); });
    picker.appendChild(button);
  });
  picker.hidden = false;

  buildMap();
  setActive(LINES[0]);
  refreshWash();
  list.hidden = true;

  if (window.ResizeObserver) new ResizeObserver(refreshWash).observe(washBox);

  // Переключатель темы живёт в app.js и просто ставит data-theme на <html>.
  // Следим за атрибутом, чтобы не заводить между файлами лишний уговор о событии.
  if (window.MutationObserver) {
    new MutationObserver(function () { buildSheet(); renderWash(); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
})();
