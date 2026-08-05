/* ==========================================================================
   Виджет записи: сетка свободных слотов преподавателя.
   Работает и на публичном сайте (пробный урок), и в кабинете ученика.
   ========================================================================== */
(function () {
  "use strict";

  const widget = document.getElementById("booking");
  if (!widget) return;

  const api = window.Linguich.api;
  const slotsUrl = widget.dataset.slotsUrl;
  const bookUrl = widget.dataset.bookUrl;
  const grid = widget.querySelector("[data-slots]");
  const summary = widget.querySelector("[data-summary]");
  const submit = widget.querySelector("[data-book]");
  const teacherSelect = widget.querySelector('[name="teacher"]');
  const modeInputs = widget.querySelectorAll('[name="mode"]');

  let selected = null;

  function skeleton() {
    grid.innerHTML =
      '<div class="stack">' +
      Array.from({ length: 3 })
        .map(function () {
          return (
            '<div><div class="skeleton" style="height:14px;width:140px;margin-bottom:12px"></div>' +
            '<div class="slot-grid">' +
            Array.from({ length: 6 }).map(function () {
              return '<div class="skeleton" style="height:42px"></div>';
            }).join("") +
            "</div></div>"
          );
        })
        .join("") +
      "</div>";
  }

  function currentMode() {
    let mode = "";
    modeInputs.forEach(function (input) { if (input.checked) mode = input.value; });
    return mode;
  }

  async function load() {
    if (!teacherSelect || !teacherSelect.value) {
      grid.innerHTML = '<div class="empty"><h4>Выберите преподавателя</h4>' +
        "<p>Покажем свободное время на две недели вперёд.</p></div>";
      return;
    }
    skeleton();
    selected = null;
    updateSummary();

    try {
      const params = new URLSearchParams({ teacher: teacherSelect.value, mode: currentMode() });
      const data = await api(slotsUrl + "?" + params.toString());
      renderDays(data.days);
    } catch (error) {
      grid.innerHTML = '<div class="alert alert--err">' + error.message + "</div>";
    }
  }

  // «1 слот · 2 слота · 5 слотов» — русская форма множественного числа.
  function plural(n, one, few, many) {
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return many;
    const mod10 = n % 10;
    if (mod10 === 1) return one;
    if (mod10 >= 2 && mod10 <= 4) return few;
    return many;
  }

  function renderDays(days) {
    if (!days.length) {
      grid.innerHTML =
        '<div class="empty"><h4>Свободных слотов нет</h4>' +
        "<p>Оставьте заявку — подберём время вручную или предложим другого преподавателя.</p></div>";
      return;
    }
    grid.innerHTML = days
      .map(function (day) {
        return (
          '<div class="day-block">' +
            '<div class="day-block__title">' + day.label + " <span>· " + day.slots.length +
              " " + plural(day.slots.length, "слот", "слота", "слотов") + "</span></div>" +
            '<div class="slot-grid">' +
              day.slots.map(function (slot) {
                return (
                  '<button type="button" class="slot" data-start="' + slot.start +
                  '" data-label="' + day.label + ", " + slot.time + '">' + slot.time + "</button>"
                );
              }).join("") +
            "</div>" +
          "</div>"
        );
      })
      .join("");

    grid.querySelectorAll(".slot").forEach(function (button) {
      button.addEventListener("click", function () {
        grid.querySelectorAll(".slot").forEach(function (other) { other.classList.remove("is-selected"); });
        button.classList.add("is-selected");
        selected = { start: button.dataset.start, label: button.dataset.label };
        updateSummary();
      });
    });
  }

  function updateSummary() {
    if (!summary) return;
    if (selected) {
      summary.innerHTML = '<strong>' + selected.label + "</strong>";
      summary.hidden = false;
    } else {
      summary.hidden = true;
    }
    if (submit) submit.disabled = !selected;
  }

  if (submit) {
    submit.addEventListener("click", async function () {
      if (!selected) return;
      window.Linguich.busy(submit, true);
      try {
        const data = await api(bookUrl, {
          method: "POST",
          json: {
            teacher: teacherSelect.value,
            start: selected.start,
            mode: currentMode(),
            course: (widget.querySelector('[name="course"]') || {}).value || null,
          },
        });
        window.Linguich.toast(data.message || "Записали!", "ok");
        if (data.redirect) { location.href = data.redirect; return; }
        load();
      } catch (error) {
        window.Linguich.toast(error.message, "err");
        load();
      } finally {
        window.Linguich.busy(submit, false);
      }
    });
  }

  if (teacherSelect) teacherSelect.addEventListener("change", load);
  modeInputs.forEach(function (input) { input.addEventListener("change", load); });

  load();
})();
