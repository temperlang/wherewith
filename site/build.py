# /// script
# requires-python = ">=3.11"
# ///
"""Builds Wherewith's site into `site/build/`.

    npm ci --prefix site
    uv run site/build.py
    python3 -m http.server --bind 127.0.0.1 -d site/build

The page is static: everything on it is built into `index.html` here, and
its one small script only switches the language tabs. It needs no Temper
output, so no `temper build` first. Type-checks that script with
TypeScript first (`--no-check` skips that, for a quick look).

The code comes from code that runs, so it can't go stale:

- The Temper is the `snippet: temper` part of the site's example test, in
  `src/query-tests.temper.md`, which runs on every backend.
- Each language's code is the `snippet: example` part of its program in
  `demos/example/`, and the output shown is `demos/example/expected.txt`,
  which CI checks every program prints (`demos/run.py`).
- The opening's rendered queries are that output, and its template is the
  Temper's.
- The dialect table, and the placeholder styles, come from
  `docs/design.md`.

A snippet is the lines between a comment `snippet: NAME` and a comment
`end snippet`, each alone on its line, dedented. The build fails if one is
missing, or if the page has a slot left unfilled.
"""

import gzip
import hashlib
import html
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = SITE / "build"
EXAMPLE = ROOT / "demos" / "example"
TEMPER_TEST = ROOT / "src" / "query-tests.temper.md"
DESIGN = ROOT / "docs" / "design.md"
REPO = "https://github.com/temperlang/wherewith"

# Each language's program, in the site's (alphabetical) order: name, id, the
# program in demos/example/, its line comment, and how to run it there, as
# demos/README.md says.
LANGUAGES = [
    ("C++", "cpp", "cpp/example.cpp", "//", "cmake -B build && cmake --build build && ./build/example"),
    ("C#", "cs", "csharp/Program.cs", "//", "dotnet run"),
    ("Java", "java", "java/src/main/java/Example.java", "//", "./gradlew run"),
    ("JavaScript", "js", "js/example.js", "//", "npm ci && npm start"),
    ("Lua", "lua", "lua/example.lua", "--", "lua -l paths example.lua"),
    ("Python", "py", "py/example.py", "#", "uv run example.py"),
    ("Rust", "rs", "rust/src/main.rs", "//", "cargo run"),
]
DEFAULT_LANGUAGE = "py"

# How the page names each dialect in the example's output.
DIALECTS = {
    "sqlite": "SQLite",
    "postgres": "PostgreSQL",
    "mysql": "MySQL and MariaDB",
    "duckdb": "DuckDB",
}

PLACEHOLDER_STYLES = ["question", "dollarNumbered", "percentS", "atNamed", "colonNamed"]


def esc(text):
    return html.escape(text, quote=True)


def snippet(path, name, comment):
    """The dedented lines between `<comment> snippet: name` and
    `<comment> end snippet`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == f"{comment} snippet: {name}"]
    if len(starts) != 1:
        raise SystemExit(f"{path.relative_to(ROOT)} needs one `{comment} snippet: {name}` line.")
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].strip() == f"{comment} end snippet"), None)
    if end is None:
        raise SystemExit(f"{path.relative_to(ROOT)}: snippet {name!r} has no `{comment} end snippet`.")
    return textwrap.dedent("\n".join(lines[start:end])).strip("\n") + "\n"


# A small highlighter, after the one on Hrefine's and Chromarite's sites,
# run here so the page needs no script for it.
KEYWORDS = set(
    (
        "and as auto bool break case catch class const continue def do double else elif end except export "
        "false final fn for from function if import in include int let local match mut new None nil not null "
        "of or orelse panic private public return self static string struct this throw true True False try "
        "type typename use using var void while Some Ok"
    ).split()
)


def highlight(source, comment):
    """Source as HTML, with comments, strings, numbers, keywords, and
    type-like names in spans."""
    comment_pattern = {"#": r"#[^\n]*", "--": r"--[^\n]*"}.get(comment, r"//[^\n]*|/\*[\s\S]*?\*/")
    token = re.compile(
        rf"({comment_pattern})|"
        r'("""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\')|'
        r"\b(\d+(?:\.\d+)?)\b|([A-Za-z_]\w*)"
    )
    out = []
    last = 0
    for m in token.finditer(source):
        out.append(esc(source[last : m.start()]))
        text, is_comment, is_string, is_number, word = m[0], m[1], m[2], m[3], m[4]
        if is_comment:
            cls = "comment"
        elif is_string:
            cls = "string"
        elif is_number:
            cls = "number"
        elif word in KEYWORDS:
            cls = "keyword"
        elif re.match(r"[A-Z][a-z]", word):
            cls = "type"
        else:
            cls = None
        out.append(f'<span class="tok-{cls}">{esc(text)}</span>' if cls else esc(text))
        last = m.end()
    out.append(esc(source[last:]))
    return "".join(out)


def code_block(source, comment, label):
    return f'<pre class="source" tabindex="0" aria-label="{esc(label)}"><code>{highlight(source, comment)}</code></pre>'


def example_output():
    """The example's output, as dialect and SQL pairs, and the rest."""
    text = (EXAMPLE / "expected.txt").read_text(encoding="utf-8")
    rendered = []
    rest = {}
    for line in text.splitlines():
        key, _, value = line.partition(": ")
        if key in DIALECTS:
            rendered.append((key, value))
        else:
            rest[key] = value
    if [k for k, _ in rendered] != list(DIALECTS) or set(rest) != {"params", "refused"}:
        raise SystemExit("demos/example/expected.txt isn't what the page expects.")
    return text, rendered, rest


def sql_html(sql):
    """Rendered SQL with its quoted names and its placeholder marked."""
    out = esc(sql)
    out = re.sub(r"(&quot;[^&]*&quot;|`[^`]*`)", r'<span class="q-name">\1</span>', out)
    return re.sub(r"(\S+)$", r'<span class="q-param">\1</span>', out)


def template_html(line):
    """The Temper template, with its holes marked."""
    m = re.search(r'(\w+)"(.*)"', line)
    if not m:
        raise SystemExit(f"Can't find the template in {line!r}.")
    body = re.sub(r"\$\{(\w+)\}", lambda h: f'<span class="hole">${{{esc(h[1])}}}</span>', esc(m[2]))
    return f'<span class="tag">{esc(m[1])}</span>"{body}"'


def hero(temper, rendered, rest):
    """The opening: the Temper template, the hostile value, and the query
    as each database gets it."""
    template = next((line for line in temper.splitlines() if re.search(r'= \w+"', line)), None)
    value = re.search(r'let name = "(.*)";', temper)
    if not template or not value:
        raise SystemExit("The Temper snippet needs a template and a `let name`.")
    if rest["params"] != "1":
        raise SystemExit("The example should have one parameter.")
    rows = []
    for key, sql in rendered:
        placeholder = sql.rsplit(" ", 1)[1]
        rows.append(
            f'<li><span class="db">{esc(DIALECTS[key])}</span>'
            f'<span class="style">with <code>{esc(placeholder)}</code></span>'
            f'<code class="sql">{sql_html(sql)}</code></li>'
        )
    return (
        '<div class="hero-demo">'
        '<div class="given">'
        f'<p class="label">Written once</p><p class="template"><code>{template_html(template)}</code></p>'
        f'<p class="value"><span class="label">where <code>name</code> is</span> <code>"{esc(value[1])}"</code></p>'
        "</div>"
        '<p class="arrow" aria-hidden="true">↓</p>'
        '<p class="label">Rendered for each database</p>'
        f'<ul class="rendered">{"".join(rows)}</ul>'
        f'<p class="params"><span class="q-param-key">Parameter 1</span> <code>"{esc(value[1])}"</code>'
        ' <span class="label">sent apart, for the driver to bind</span></p>'
        "</div>"
    )


def tabs():
    out = []
    for name, id, _, _, _ in LANGUAGES:
        on = id == DEFAULT_LANGUAGE
        out.append(
            f'<button type="button" role="tab" id="tab-{id}" data-lang="{id}" aria-controls="panel-{id}" '
            f'aria-selected="{str(on).lower()}" tabindex="{0 if on else -1}">{esc(name)}</button>'
        )
    return "\n".join(out)


def panels():
    out = []
    for name, id, path, comment, run in LANGUAGES:
        source = snippet(EXAMPLE / path, "example", comment)
        hidden = "" if id == DEFAULT_LANGUAGE else " hidden"
        folder = path.split("/")[0]
        out.append(
            f'<div class="lang-panel" role="tabpanel" id="panel-{id}" aria-labelledby="tab-{id}"{hidden}>'
            f"{code_block(source, comment, name)}"
            f'<p class="run">Run it in <a href="{REPO}/tree/main/demos/example/{folder}"><code>demos/example/{folder}</code></a>:'
            f" <code>{esc(run)}</code></p>"
            "</div>"
        )
    return "\n".join(out)


def inline_md(text):
    """A Markdown table cell as HTML: code spans, and the rest as text."""
    parts = re.split(r"(`[^`]*`)", text.strip())
    return "".join(f"<code>{esc(p[1:-1])}</code>" if p.startswith("`") else esc(p) for p in parts)


def md_table(lines):
    """A Markdown table's rows, as lists of cells, without the divider."""
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    return [row for row in rows if not all(set(cell) <= set("-: ") for cell in row)]


def table_after(text, heading, first_cell=None):
    """The first table after a heading, or the row starting with
    `first_cell` in it."""
    at = text.index(heading)
    lines = text[at:].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    end = next((i for i in range(start, len(lines)) if not lines[i].startswith("|")), len(lines))
    rows = md_table(lines[start:end])
    if first_cell is None:
        return rows
    return next(row for row in rows if row[0] == first_cell)


def dialects(design):
    """The dialect table: each driver's placeholders, by language and
    database, under what the database itself reads."""
    drivers = table_after(design, "## Parameters per driver")
    head, body = drivers[0], drivers[1:]
    if head[1:] != list(DIALECTS.values()):
        raise SystemExit(f"docs/design.md's driver table has other columns: {head}")
    sql = table_after(design, "## Model: a shared core plus profiles", "Parameters in SQL")
    names = [inline_md(c) for c in head[1:]]
    th = "".join(f'<th scope="col">{n}</th>' for n in names)

    def row(label, cells, cls=""):
        tds = "".join(f'<td data-label="{esc(head[i + 1])}"><span>{inline_md(c)}</span></td>' for i, c in enumerate(cells))
        return f'<tr{cls}><th scope="row">{label}</th>{tds}</tr>'

    rows = [row("In the SQL itself", sql[1:], ' class="server"')]
    rows += [row(esc(r[0]), r[1:]) for r in body]
    return (
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Placeholders by language and database">'
        '<table class="dialects">'
        f'<thead><tr><th scope="col">Language</th>{th}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def styles(design):
    """Each placeholder style's marker, as the design lists them."""
    flat = " ".join(design.split())
    found = dict(re.findall(r"`(\w+)` \(`([^`]+)`", flat))
    missing = [s for s in PLACEHOLDER_STYLES if s not in found]
    if missing:
        raise SystemExit(f"docs/design.md doesn't list these placeholder styles: {missing}")
    markers = [f"<code>{esc(found[s])}</code>" for s in PLACEHOLDER_STYLES]
    return ", ".join(markers[:-1]) + ", or " + markers[-1]


def sizes(files):
    data = b"".join(f.read_bytes() for f in files)
    return len(data), len(gzip.compress(data, 9))


def check_js():
    """Type-checks the page's script, as Chromarite's site does."""
    tsc = SITE / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        raise SystemExit("Install the site's tools first (npm ci --prefix site), or pass --no-check.")
    subprocess.run(["npm", "run", "-s", "check"], cwd=SITE, check=True)


def main():
    if "--no-check" not in sys.argv[1:]:
        check_js()
    temper = snippet(TEMPER_TEST, "temper", "//")
    text, rendered, rest = example_output()
    design = DESIGN.read_text(encoding="utf-8")

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    # GitHub Pages serves files as they are, without Jekyll.
    (OUT / ".nojekyll").touch()
    for name in ["style.css", "app.js"]:
        shutil.copyfile(SITE / name, OUT / name)

    page = (SITE / "index.html").read_text(encoding="utf-8")
    parts = {
        "HERO": hero(temper, rendered, rest),
        "TEMPER": f'<p class="code-label">Temper</p>{code_block(temper, "//", "Temper")}',
        "TABS": tabs(),
        "PANELS": panels(),
        "OUTPUT": f'<pre class="output" tabindex="0" aria-label="Output">{esc(text)}</pre>',
        "STYLES": styles(design),
        "DIALECTS": dialects(design),
    }
    for key, value in parts.items():
        if f"<!--{key}-->" not in page:
            raise SystemExit(f"index.html has no <!--{key}-->.")
        page = page.replace(f"<!--{key}-->", value)
    left = re.findall(r"<!--[A-Z_]+-->", page)
    if left:
        raise SystemExit(f"Unfilled in index.html: {', '.join(left)}")
    # Each reference gets its file's hash, so browsers fetch changed files
    # instead of reusing cached ones.
    for ref in ["style.css", "app.js"]:
        digest = hashlib.sha256((OUT / ref).read_bytes()).hexdigest()[:10]
        page = page.replace(f'"{ref}"', f'"{ref}?v={digest}"')
    (OUT / "index.html").write_text(page, encoding="utf-8")

    raw, gz = sizes([OUT / "index.html", OUT / "style.css", OUT / "app.js"])
    print(f"The page, with its style and script: {raw} bytes, {gz} gzipped")
    print(f"Built {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
