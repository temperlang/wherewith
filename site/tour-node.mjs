// Runs the built site's JavaScript tour in Node, as the page's "Run in your
// browser" button does (tourrun.js), and prints its output. `build.py` runs
// it on the built site and fails unless it prints `tour/expected.txt`.
//
//     node site/tour-node.mjs site/build
//
// Loads Wherewith from the built site's `lib/`, the files the page loads,
// resolving the page's import map names the same way.

import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { pathToFileURL } from "node:url";
import { runTour } from "./tourrun.js";

const build = pathToFileURL(`${process.argv[2] ?? "site/build"}/`);
// As in index.html's import map.
const imports = {
  wherewith: new URL("lib/wherewith/index.js", build).href,
  "@temperlang/core": new URL("lib/temper-core/index.js", build).href,
};
registerHooks({
  resolve: (specifier, context, next) =>
    Object.hasOwn(imports, specifier)
      ? { url: imports[/** @type {keyof imports} */ (specifier)], shortCircuit: true }
      : next(specifier, context),
});

const modules = { wherewith: await import("wherewith") };
const source = readFileSync(new URL("tour/tour.js", build), "utf8");
process.stdout.write(await runTour(source, modules));
