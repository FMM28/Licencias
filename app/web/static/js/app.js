/* Comportamiento del panel. Sin scripts en línea (CSP): todo se activa con data-attributes. */
(() => {
  "use strict";
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // Fechas en la zona horaria del navegador.
  const fmt = new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" });
  $$("time[data-local]").forEach((t) => {
    const d = new Date(t.getAttribute("datetime"));
    if (!isNaN(d)) t.textContent = fmt.format(d);
  });

  // Copiar al portapapeles.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const label = btn.querySelector("[data-copy-label]") || btn;
    const original = label.textContent;
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
      label.textContent = btn.dataset.copied || "Copiado";
    } catch {
      const key = document.querySelector("[data-key]");
      if (key) {
        const r = document.createRange();
        r.selectNodeContents(key);
        const s = getSelection();
        s.removeAllRanges();
        s.addRange(r);
      }
      label.textContent = "Selecciona y copia";
    }
    setTimeout(() => { label.textContent = original; }, 2000);
  });

  // Confirmación antes de acciones destructivas; evita doble envío.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const msg = form.dataset && form.dataset.confirm;
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    if (form.method && form.method.toLowerCase() === "post") {
      if (form.dataset.sent) { e.preventDefault(); return; }
      form.dataset.sent = "1";
      $$("button[type=submit]", form).forEach((b) => b.setAttribute("aria-disabled", "true"));
    }
  });
  window.addEventListener("pageshow", () => {
    $$("form[data-sent]").forEach((f) => {
      delete f.dataset.sent;
      $$("button[aria-disabled]", f).forEach((b) => b.removeAttribute("aria-disabled"));
    });
  });

  // Botones que rellenan un campo.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fill]");
    if (!b) return;
    const input = document.querySelector(b.dataset.fill);
    if (input) { input.value = b.dataset.value; input.focus(); }
  });

  // Mostrar/ocultar campos según el plan.
  const radios = $$("input[name=plan]");
  const blocks = $$("[data-when-plan]");
  const sync = () => {
    const cur = (radios.find((r) => r.checked) || {}).value;
    blocks.forEach((b) => {
      const on = b.dataset.whenPlan.split(/\s+/).includes(cur);
      b.hidden = !on;
      $$("input,select,textarea", b).forEach((i) => { i.disabled = !on; });
    });
  };
  if (radios.length && blocks.length) {
    radios.forEach((r) => r.addEventListener("change", sync));
    sync();
  }

  // Menú de usuario: cerrar al hacer clic fuera o con Escape.
  document.addEventListener("click", (e) => {
    $$("details.menu[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$("details.menu[open]").forEach((d) => { d.open = false; d.querySelector("summary")?.focus(); });
    const tag = (e.target.tagName || "").toLowerCase();
    if (e.key === "/" && !["input", "textarea", "select"].includes(tag) && !e.metaKey && !e.ctrlKey) {
      const s = document.getElementById("bar-search");
      if (s) { e.preventDefault(); s.focus(); }
    }
  });
})();
