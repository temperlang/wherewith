// @ts-check
// Wherewith's site: the language tabs, and running the tour. Everything
// else is built into the page by build.py, so it shows before, and
// without, any script.

import { runTour } from "./tourrun.js";

const DEFAULT_LANGUAGE = "py";

// Each row of tabs: the example's, and the tour's, which has Temper too.
// Choosing a language in one chooses it in the other, where it's there.
const groups = /** @type {HTMLElement[]} */ ([...document.querySelectorAll('[role="tablist"]')]).map(
  (list) => /** @type {HTMLButtonElement[]} */ ([...list.querySelectorAll('[role="tab"]')]),
);

/**
 * Shows one language's code in every row of tabs that has it.
 *
 * @param {string} lang
 * @param {HTMLButtonElement} [focus] the tab to focus
 */
function select(lang, focus) {
  for (const tabs of groups) {
    if (!tabs.some((tab) => tab.dataset.lang === lang)) continue;
    for (const tab of tabs) {
      const on = tab.dataset.lang === lang;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      for (const id of (tab.getAttribute("aria-controls") ?? "").split(" ")) {
        const panel = document.getElementById(id);
        if (panel) panel.hidden = !on;
      }
      if (on) reveal(tab);
    }
  }
  focus?.focus();
}

/**
 * Scrolls a row of tabs that scrolls sideways, as the tour's does on
 * phones, to center a tab, without scrolling the page.
 *
 * @param {HTMLButtonElement} tab
 */
function reveal(tab) {
  const list = tab.parentElement;
  if (!list || list.scrollWidth <= list.clientWidth) return;
  list.scrollLeft = tab.offsetLeft - list.offsetLeft - (list.clientWidth - tab.offsetWidth) / 2;
}

for (const tabs of groups) {
  const chosen = tabs.find((tab) => tab.getAttribute("aria-selected") === "true");
  if (chosen) reveal(chosen);
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
      select(to.dataset.lang ?? DEFAULT_LANGUAGE, to);
    });
  }
}

// The JavaScript tour runs in the page (tourrun.js, which the build also
// runs in Node), with Wherewith and Temper's runtime from the page's
// import map, loaded only now, and its output is compared with the text
// every language's tour prints.

const runButton = /** @type {HTMLButtonElement} */ (document.getElementById("tour-run"));
const output = /** @type {HTMLElement} */ (document.getElementById("tour-output"));
const note = /** @type {HTMLElement} */ (document.getElementById("tour-run-note"));

runButton.addEventListener("click", async () => {
  select("js");
  output.hidden = false;
  output.textContent = "Running…";
  runButton.disabled = true;
  try {
    // A name the import map resolves, kept in a variable so TypeScript
    // doesn't look for it.
    const library = "wherewith";
    const [wherewith, source, expected] = await Promise.all([
      import(library),
      fetchText("tour/tour.js"),
      fetchText("tour/expected.txt"),
    ]);
    const out = await runTour(source, { wherewith });
    output.textContent = out;
    note.textContent =
      out === expected
        ? "✓ The JavaScript tour ran in this page, and printed the same as every other language."
        : "✗ The JavaScript tour ran in this page, and printed something else.";
  } catch (error) {
    output.textContent = String(error);
    note.textContent = "The tour couldn't run in this page.";
  } finally {
    runButton.disabled = false;
  }
});

/**
 * @param {string} url
 * @returns {Promise<string>}
 */
async function fetchText(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Couldn't load ${url} (${response.status}).`);
  return response.text();
}
