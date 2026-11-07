// @ts-check
// Wherewith's site: the language tabs. Everything else is built into the
// page by build.py, so it shows before, and without, any script.

const DEFAULT_LANGUAGE = "py";

const tabs = /** @type {HTMLButtonElement[]} */ ([...document.querySelectorAll('[role="tab"]')]);

/**
 * Shows one language's code.
 *
 * @param {string} lang
 * @param {boolean} [focus]
 */
function select(lang, focus = false) {
  for (const tab of tabs) {
    const on = tab.dataset.lang === lang;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    const panel = document.getElementById(tab.getAttribute("aria-controls") ?? "");
    if (panel) panel.hidden = !on;
    if (on && focus) tab.focus();
  }
}

for (const [i, tab] of tabs.entries()) {
  tab.addEventListener("click", () => select(tab.dataset.lang ?? DEFAULT_LANGUAGE));
  // Arrow keys move along the tabs, and Home and End go to either end, as
  // ARIA's tabs pattern has it.
  tab.addEventListener("keydown", (event) => {
    const last = tabs.length - 1;
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const to = tabs[(next + tabs.length) % tabs.length];
    select(to.dataset.lang ?? DEFAULT_LANGUAGE, true);
  });
}
