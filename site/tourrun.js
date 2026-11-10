// Runs the JavaScript tour in a page, or in Node for the build's check
// (tour-node.mjs), the same way in both: the tour's source becomes the body
// of an async function, each `import { … } from "…";` line's names become
// its parameters, and console.log is collected.

/**
 * Runs the tour's source, giving it the modules it imports, by specifier,
 * and returns what it printed.
 *
 * @param {string} source
 * @param {Record<string, any>} modules
 * @returns {Promise<string>}
 */
export async function runTour(source, modules) {
  /** @type {Map<string, unknown>} */
  const given = new Map();
  const code = source.replace(/^import \{([^}]*)\} from "([^"]+)";$/gm, (_, list, from) => {
    const module = modules[from];
    if (!module) throw new Error(`The tour imports ${from}, which isn't given.`);
    for (const name of String(list).split(",").map((n) => n.trim()).filter(Boolean)) {
      if (!(name in module)) throw new Error(`${from} has no ${name}.`);
      given.set(name, module[name]);
    }
    return "";
  });
  if (/^\s*import\b/m.test(code)) throw new Error("The tour has an import this can't run.");
  /** @type {string[]} */
  const lines = [];
  const log = (/** @type {unknown[]} */ ...args) => lines.push(args.map(String).join(" "));
  const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
  await new AsyncFunction(...given.keys(), "console", code)(...given.values(), { log });
  return lines.map((line) => line + "\n").join("");
}
