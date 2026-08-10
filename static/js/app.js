/* ==========================================================================
   Лингвич — ядро фронтенда.
   Никаких фреймворков: маленький слой поверх fetch + пара UI-хелперов.
   ========================================================================== */
(function () {
  "use strict";

  // --- CSRF --------------------------------------------------------------
  function csrfToken() {
    const match = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[2]);
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  // --- Toasts ------------------------------------------------------------
  function toastHost() {
    let host = document.querySelector(".toasts");
    if (!host) {
      host = document.createElement("div");
      host.className = "toasts";
      host.setAttribute("role", "status");
      host.setAttribute("aria-live", "polite");
      document.body.appendChild(host);
    }
    return host;
  }

  function toast(message, kind) {
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " toast--" + kind : "");
    el.textContent = message;
    toastHost().appendChild(el);
    setTimeout(function () {
      el.classList.add("is-leaving");
      setTimeout(function () { el.remove(); }, 260);
    }, 4200);
  }

  // --- API ---------------------------------------------------------------
  async function api(url, options) {
    options = options || {};
    const headers = Object.assign(
      { "X-Requested-With": "XMLHttpRequest" },
      options.headers || {}
    );
    if (options.method && options.method.toUpperCase() !== "GET") {
      headers["X-CSRFToken"] = csrfToken();
    }
    if (options.json !== undefined) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.json);
      options.method = options.method || "POST";
      delete options.json;
    }
    const response = await fetch(url, Object.assign({}, options, { headers: headers }));
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const message = (payload && payload.error) || "Что-то пошло не так. Попробуйте ещё раз.";
      const err = new Error(message);
      err.payload = payload;
      err.status = response.status;
      throw err;
    }
    return payload;
  }

  function busy(button, isBusy) {
    if (!button) return;
    button.classList.toggle("is-loading", !!isBusy);
    button.disabled = !!isBusy;
  }

  // --- Async forms -------------------------------------------------------
  // <form data-async data-success="Спасибо!"> отправляется без перезагрузки.
  function bindAsyncForms(root) {
    (root || document).querySelectorAll("form[data-async]").forEach(function (form) {
      if (form.dataset.bound) return;
      form.dataset.bound = "1";

      form.addEventListener("submit", async function (event) {
        event.preventDefault();
        const submit = event.submitter || form.querySelector('[type="submit"]');
        form.querySelectorAll(".error").forEach(function (n) { n.remove(); });
        busy(submit, true);
        try {
          // Второй аргумент FormData добавляет name/value нажатой кнопки —
          // без него формы с двумя submit-кнопками теряют выбор действия.
          const body = new FormData(form, event.submitter);
          if (event.submitter && event.submitter.name && !body.has(event.submitter.name)) {
            body.append(event.submitter.name, event.submitter.value);
          }
          const data = await api(form.action || location.pathname, {
            method: form.method || "POST",
            body: body,
          });
          if (data.redirect) { location.href = data.redirect; return; }
          if (data.replace) {
            const target = document.querySelector(form.dataset.target || "");
            if (target) { target.outerHTML = data.replace; bindAsyncForms(document); initPhoneInputs(document); }
          }
          if (form.dataset.successHtml) {
            const box = document.querySelector(form.dataset.successHtml);
            if (box) { box.hidden = false; box.scrollIntoView({ block: "center", behavior: "smooth" }); }
            form.hidden = true;
          } else {
            form.reset();
          }
          toast(data.message || form.dataset.success || "Готово", "ok");
          form.dispatchEvent(new CustomEvent("async:success", { detail: data, bubbles: true }));
        } catch (error) {
          const fields = (error.payload && error.payload.fields) || {};
          Object.keys(fields).forEach(function (name) {
            const input = form.querySelector('[name="' + name + '"]');
            if (!input) return;
            input.setAttribute("aria-invalid", "true");
            const note = document.createElement("span");
            note.className = "error";
            note.textContent = fields[name];
            (input.closest(".field") || input.parentNode).appendChild(note);
          });
          toast(error.message, "err");
        } finally {
          busy(submit, false);
        }
      });

      form.addEventListener("input", function (event) {
        event.target.removeAttribute("aria-invalid");
      });
    });
  }

  // --- Async actions -----------------------------------------------------
  // <button data-action="/url/" data-confirm="Точно?" data-reload>
  function bindActions(root) {
    (root || document).querySelectorAll("[data-action]").forEach(function (el) {
      if (el.dataset.bound) return;
      el.dataset.bound = "1";
      el.addEventListener("click", async function (event) {
        event.preventDefault();
        if (el.dataset.confirm && !window.confirm(el.dataset.confirm)) return;
        busy(el, true);
        try {
          const payload = el.dataset.payload ? JSON.parse(el.dataset.payload) : {};
          const data = await api(el.dataset.action, { method: "POST", json: payload });
          toast(data.message || "Готово", "ok");
          if (el.dataset.reload !== undefined) { location.reload(); return; }
          if (data.replace && el.dataset.target) {
            const target = document.querySelector(el.dataset.target);
            if (target) { target.outerHTML = data.replace; bindActions(document); bindAsyncForms(document); initPhoneInputs(document); }
          }
          if (el.dataset.remove !== undefined) {
            const node = el.closest(el.dataset.remove || "*");
            if (node) node.remove();
          }
        } catch (error) {
          toast(error.message, "err");
        } finally {
          busy(el, false);
        }
      });
    });
  }

  // --- Theme -------------------------------------------------------------
  function initTheme() {
    const stored = localStorage.getItem("linguich-theme");
    if (stored) document.documentElement.setAttribute("data-theme", stored);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        const isDark =
          document.documentElement.getAttribute("data-theme") === "dark" ||
          (!document.documentElement.hasAttribute("data-theme") &&
            window.matchMedia("(prefers-color-scheme: dark)").matches);
        const next = isDark ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("linguich-theme", next);
      });
    });
  }

  // --- Scroll reveal -----------------------------------------------------
  function initReveal() {
    const nodes = document.querySelectorAll(".reveal");
    if (!nodes.length) return;
    if (!("IntersectionObserver" in window)) {
      nodes.forEach(function (n) { n.classList.add("is-visible"); });
      return;
    }
    const observer = new IntersectionObserver(function (entries) {
      var shown = 0;
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        // Каскад ограничиваем: при быстрой прокрутке в одну пачку попадает
        // десяток блоков, и последний иначе ждал бы больше секунды.
        setTimeout(function () { entry.target.classList.add("is-visible"); }, Math.min(shown, 5) * 70);
        shown += 1;
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -60px 0px", threshold: 0.05 });
    nodes.forEach(function (n) { observer.observe(n); });
  }

  // --- Header / menus ----------------------------------------------------
  function initChrome() {
    const header = document.querySelector(".site-header");
    if (header) {
      const onScroll = function () { header.classList.toggle("is-stuck", window.scrollY > 8); };
      onScroll();
      window.addEventListener("scroll", onScroll, { passive: true });
    }

    const burger = document.querySelector("[data-burger]");
    const menu = document.querySelector(".mobile-menu");
    if (burger && menu) {
      burger.addEventListener("click", function () {
        const open = menu.classList.toggle("is-open");
        burger.setAttribute("aria-expanded", String(open));
        document.body.style.overflow = open ? "hidden" : "";
      });
      menu.querySelectorAll("a").forEach(function (link) {
        link.addEventListener("click", function () {
          menu.classList.remove("is-open");
          document.body.style.overflow = "";
        });
      });
    }

    const side = document.querySelector(".cab-side");
    const scrim = document.querySelector(".cab-side__scrim");
    document.querySelectorAll("[data-cab-burger]").forEach(function (button) {
      button.addEventListener("click", function () {
        side.classList.toggle("is-open");
        if (scrim) scrim.classList.toggle("is-open");
      });
    });
    if (scrim) {
      scrim.addEventListener("click", function () {
        side.classList.remove("is-open");
        scrim.classList.remove("is-open");
      });
    }
  }

  // --- Modals ------------------------------------------------------------
  function initModals() {
    document.querySelectorAll("[data-modal-open]").forEach(function (trigger) {
      trigger.addEventListener("click", function (event) {
        event.preventDefault();
        const modal = document.querySelector(trigger.dataset.modalOpen);
        if (!modal) return;
        modal.setAttribute("open", "");
        document.body.style.overflow = "hidden";
        const first = modal.querySelector("input, textarea, select, button");
        if (first) first.focus();
        // Позволяем триггеру передать контекст в форму модалки.
        Object.keys(trigger.dataset).forEach(function (key) {
          if (!key.startsWith("set")) return;
          const name = key.slice(3).toLowerCase();
          const field = modal.querySelector('[name="' + name + '"]');
          if (field) field.value = trigger.dataset[key];
          const slot = modal.querySelector('[data-slot="' + name + '"]');
          if (slot) slot.textContent = trigger.dataset[key];
        });
      });
    });

    function close(modal) {
      modal.removeAttribute("open");
      document.body.style.overflow = "";
    }
    document.querySelectorAll(".modal").forEach(function (modal) {
      modal.addEventListener("click", function (event) {
        if (event.target === modal || event.target.closest("[data-modal-close]")) close(modal);
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      document.querySelectorAll(".modal[open]").forEach(close);
    });
  }

  // --- Countdown ---------------------------------------------------------
  function initCountdowns() {
    const nodes = document.querySelectorAll("[data-countdown]");
    if (!nodes.length) return;
    function tick() {
      nodes.forEach(function (node) {
        const target = new Date(node.dataset.countdown).getTime();
        let diff = Math.floor((target - Date.now()) / 1000);
        if (diff <= 0) { node.textContent = "идёт сейчас"; return; }
        const days = Math.floor(diff / 86400); diff %= 86400;
        const hours = Math.floor(diff / 3600); diff %= 3600;
        const minutes = Math.floor(diff / 60);
        node.textContent = days
          ? "через " + days + " дн " + hours + " ч"
          : hours
          ? "через " + hours + " ч " + minutes + " мин"
          : "через " + minutes + " мин";
      });
    }
    tick();
    setInterval(tick, 30000);
  }

  // --- Phone mask --------------------------------------------------------
  // Школа российская, номер всегда +7. Что бы человек ни начал набирать —
  // 8, +7 или сразу 9 — на выходе один формат: +7 (999) 123-45-67.
  const isDigit = function (ch) { return ch >= "0" && ch <= "9"; };
  const digitsOf = function (value) { return (value || "").replace(/\D/g, ""); };

  function phoneDigits(value) {
    let d = digitsOf(value);
    if (!d) return "";
    // 8 — это тот же код страны на старый лад, а любую другую первую цифру
    // считаем началом самого номера и дописываем семёрку перед ней.
    if (d[0] === "8") d = "7" + d.slice(1);
    else if (d[0] !== "7") d = "7" + d;
    return d.slice(0, 11);
  }

  function phoneFormat(d) {
    if (!d) return "";
    let out = "+7";
    if (d.length > 1) out += " (" + d.slice(1, 4);
    if (d.length >= 5) out += ") " + d.slice(4, 7);
    if (d.length >= 8) out += "-" + d.slice(7, 9);
    if (d.length >= 10) out += "-" + d.slice(9, 11);
    return out;
  }

  // Каретку держим не по номеру символа, а по количеству цифр слева от неё:
  // разделители появляются и исчезают, а цифры — единственный устойчивый
  // ориентир. Без этого курсор прыгает в конец на каждом нажатии.
  function caretForDigits(formatted, wanted, skipSeparators) {
    let index = 0;
    let seen = 0;
    while (index < formatted.length && seen < wanted) {
      if (isDigit(formatted[index])) seen++;
      index++;
    }
    if (skipSeparators) {
      while (index < formatted.length && !isDigit(formatted[index])) index++;
    }
    return index;
  }

  function applyPhoneMask(input, movingForward) {
    const raw = input.value;
    const caret = input.selectionStart === null ? raw.length : input.selectionStart;
    const rawDigits = digitsOf(raw);
    // Если код страны дописали мы, слева от каретки стало на цифру больше.
    const added = rawDigits && rawDigits[0] !== "7" && rawDigits[0] !== "8" ? 1 : 0;
    const wanted = digitsOf(raw.slice(0, caret)).length + added;

    const formatted = phoneFormat(phoneDigits(raw));
    if (formatted !== raw) input.value = formatted;
    const position = caretForDigits(formatted, wanted, movingForward);
    try {
      input.setSelectionRange(position, position);
    } catch (err) {
      /* поле может не поддерживать выделение — не страшно */
    }
  }

  function initPhoneInputs(scope) {
    (scope || document).querySelectorAll('input[type="tel"]').forEach(function (input) {
      if (input.dataset.phoneMask) return;
      input.dataset.phoneMask = "1";

      // Backspace через разделитель должен стирать цифру, а не упираться
      // в скобку: иначе номер невозможно исправить, не очистив его целиком.
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Backspace") return;
        const start = input.selectionStart;
        if (start === null || start !== input.selectionEnd || start === 0) return;
        let cut = start - 1;
        while (cut >= 0 && !isDigit(input.value[cut])) cut--;
        if (cut === start - 1) return; // слева цифра, обычное поведение
        event.preventDefault();
        input.value = cut < 0 ? "" : input.value.slice(0, cut) + input.value.slice(start);
        input.setSelectionRange(Math.max(cut, 0), Math.max(cut, 0));
        applyPhoneMask(input, false);
      });

      input.addEventListener("input", function (event) {
        applyPhoneMask(input, event.inputType !== "deleteContentBackward");
      });

      input.addEventListener("focus", function () {
        if (!input.value) {
          input.value = "+7 ";
          input.setSelectionRange(input.value.length, input.value.length);
        }
      });

      // Пустая заготовка «+7» не должна уходить на сервер как «номер с
      // опечаткой» — обязательное поле обязано ругаться, что оно пустое.
      input.addEventListener("blur", function () {
        if (phoneDigits(input.value).length <= 1) input.value = "";
      });
    });
  }

  // --- Bootstrap ---------------------------------------------------------
  function init() {
    initTheme();
    initChrome();
    initReveal();
    initModals();
    initCountdowns();
    initPhoneInputs();
    bindAsyncForms(document);
    bindActions(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.Linguich = { api: api, toast: toast, busy: busy, csrfToken: csrfToken, bindAsyncForms: bindAsyncForms, bindActions: bindActions };
})();
