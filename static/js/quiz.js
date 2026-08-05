/* ==========================================================================
   Адаптивный тест уровня.
   Сложность подбирается сервером: 5 вопросов на уровень, вверх/вниз по лестнице.
   Клавиатура (1–4), мгновенный разбор ответа, результат по навыкам.
   ========================================================================== */
(function () {
  "use strict";

  const root = document.getElementById("quiz");
  if (!root) return;

  const api = window.Linguich.api;
  const urls = {
    start: root.dataset.startUrl,
    answer: root.dataset.answerUrl,
    lead: root.dataset.leadUrl,
  };

  const state = { session: null, question: null, askedAt: 0, locked: false, answered: 0, total: 20 };

  const shell = root.querySelector(".quiz__shell");

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : text;
    return div.innerHTML;
  }

  function render(html) {
    shell.innerHTML = html;
    shell.querySelectorAll(".quiz-option").forEach(function (button) {
      button.addEventListener("click", function () { answer(Number(button.dataset.index)); });
    });
    window.Linguich.bindAsyncForms(shell);
  }

  // --- Screens -----------------------------------------------------------
  function renderIntro() {
    render(
      '<div class="stack text-center" style="margin:auto">' +
        '<div class="eyebrow" style="justify-content:center">Бесплатно · 5 минут</div>' +
        "<h2>Узнайте свой уровень английского</h2>" +
        '<p class="lead">20 вопросов, которые подстраиваются под ваши ответы: ' +
        "чем увереннее отвечаете, тем сложнее становится. В конце — уровень по шкале CEFR, " +
        "разбор по навыкам и подходящая программа.</p>" +
        '<div class="chip-row" style="justify-content:center">' +
          '<span class="chip">Грамматика</span><span class="chip">Лексика</span>' +
          '<span class="chip">Чтение</span><span class="chip">Речевые ситуации</span>' +
        "</div>" +
        '<div><button class="btn btn--lg" id="quiz-start">Начать тест</button></div>' +
        '<p class="tiny muted">Регистрация не нужна. Результат покажем сразу.</p>' +
      "</div>"
    );
    shell.querySelector("#quiz-start").addEventListener("click", start);
  }

  function renderQuestion(question, progress) {
    state.question = question;
    state.askedAt = Date.now();
    state.locked = false;

    const options = question.options
      .map(function (option, index) {
        return (
          '<button class="quiz-option" data-index="' + index + '">' +
            '<span class="quiz-option__key">' + (index + 1) + "</span>" +
            "<span>" + esc(option) + "</span>" +
          "</button>"
        );
      })
      .join("");

    render(
      '<div class="quiz__bar">' +
        '<span class="quiz__level">' + esc(question.level) + "</span>" +
        '<div class="progress"><div class="progress__bar" style="width:' + progress + '%"></div></div>' +
        '<span class="tiny muted tabnum">' + (state.answered + 1) + "/" + state.total + "</span>" +
      "</div>" +
      (question.hint ? '<p class="quiz__hint">' + esc(question.hint) + "</p>" : "") +
      '<h3 class="quiz__q">' + esc(question.prompt) + "</h3>" +
      '<div class="quiz__options">' + options + "</div>" +
      '<div class="quiz__foot"><span class="tiny muted">Нажмите 1–4 на клавиатуре</span></div>'
    );
  }

  function renderResult(result) {
    const skills = (result.skills || [])
      .map(function (row) {
        return (
          '<div class="skill-bar">' +
            '<div class="skill-bar__head"><span>' + esc(row.skill) + "</span>" +
              '<strong class="tabnum">' + row.percent + "%</strong></div>" +
            '<div class="progress"><div class="progress__bar" style="width:' + row.percent + '%"></div></div>' +
          "</div>"
        );
      })
      .join("");

    render(
      '<div class="stack text-center">' +
        '<div class="eyebrow" style="justify-content:center">Ваш уровень</div>' +
        '<div class="quiz-result__level">' + esc(result.level) + "</div>" +
        "<h3>" + esc(result.title) + "</h3>" +
        '<p class="lead">' + esc(result.message) + "</p>" +
        '<div class="row" style="justify-content:center;gap:2rem">' +
          '<div><strong class="tabnum" style="font-size:var(--step-2)">' + result.correct + "/" + result.total +
            '</strong><br><span class="tiny muted">верных ответов</span></div>' +
          '<div><strong class="tabnum" style="font-size:var(--step-2)">' + result.minutes +
            '</strong><br><span class="tiny muted">минут</span></div>' +
        "</div>" +
      "</div>" +
      '<hr><div class="text-left">' + skills + "</div>" +
      '<div class="card card--flat" style="background:var(--brand-50);border:0">' +
        "<h4>Что дальше</h4>" +
        '<p class="tiny muted mb-4">Оставьте контакт — подберём программу под ваш уровень ' +
        "и пришлём план на первый месяц. Перезвоним в течение рабочего дня.</p>" +
        '<form data-async action="' + urls.lead + '" method="post" data-success="Спасибо! Скоро свяжемся."' +
        ' data-success-html="#quiz-thanks">' +
          '<input type="hidden" name="session" value="' + state.session + '">' +
          '<div class="form-grid">' +
            '<label class="field"><span class="label">Как вас зовут</span>' +
              '<input type="text" name="name" required placeholder="Имя"></label>' +
            '<label class="field"><span class="label">Телефон</span>' +
              '<input type="tel" name="phone" required placeholder="+7 (___) ___-__-__"></label>' +
          "</div>" +
          '<button class="btn btn--accent btn--block" type="submit">Получить программу</button>' +
        "</form>" +
        '<div id="quiz-thanks" hidden class="alert alert--ok mt-4">' +
          "<div><strong>Заявка принята</strong>Мы уже увидели ваш результат и скоро позвоним.</div></div>" +
      "</div>"
    );
    window.Linguich.bindAsyncForms(shell);
  }

  // --- Flow --------------------------------------------------------------
  async function start() {
    try {
      const data = await api(urls.start, { method: "POST", json: {} });
      state.session = data.session;
      state.total = data.total;
      state.answered = 0;
      renderQuestion(data.question, 0);
    } catch (error) {
      window.Linguich.toast(error.message, "err");
    }
  }

  async function answer(index) {
    if (state.locked) return;
    state.locked = true;

    const buttons = shell.querySelectorAll(".quiz-option");
    buttons.forEach(function (button) { button.disabled = true; });

    try {
      const data = await api(urls.answer, {
        method: "POST",
        json: {
          session: state.session,
          question: state.question.id,
          chosen: index,
          seconds: Math.round((Date.now() - state.askedAt) / 1000),
        },
      });

      buttons[data.correct_index] && buttons[data.correct_index].classList.add("is-correct");
      if (!data.is_correct && buttons[index]) buttons[index].classList.add("is-wrong");

      if (data.explanation) {
        const note = document.createElement("div");
        note.className = "quiz__explain";
        note.textContent = data.explanation;
        shell.querySelector(".quiz__options").after(note);
      }

      state.answered = data.answered;

      setTimeout(function () {
        if (data.finished) renderResult(data.result);
        else renderQuestion(data.question, data.progress);
      }, data.explanation ? 1500 : 750);
    } catch (error) {
      state.locked = false;
      buttons.forEach(function (button) { button.disabled = false; });
      window.Linguich.toast(error.message, "err");
    }
  }

  document.addEventListener("keydown", function (event) {
    if (state.locked || !state.question) return;
    const index = "1234".indexOf(event.key);
    if (index >= 0 && index < state.question.options.length) answer(index);
  });

  renderIntro();
})();
