# /// script
# requires-python = ">=3.11"
# ///
"""Builds Wherewith's site into `site/build/`.

    npm ci --prefix site
    temper build -b js
    uv run site/build.py
    python3 -m http.server --bind 127.0.0.1 -d site/build

The page is static: everything on it is built into `index.html` here, and
its small script only switches the language tabs, and runs the tour when
asked. Type-checks that script with TypeScript first (`--no-check` skips
that, for a quick look).

The code comes from code that runs, so it can't go stale:

- The Temper is the `snippet: temper` part of the site's example test, in
  `src/query-tests.temper.md`, which runs on every backend.
- Each language's code is the `snippet: example` part of its program in
  `demos/example/`, and the output shown is `demos/example/expected.txt`,
  which CI checks every program prints (`demos/run.py`).
- The opening's common query is the Temper's, and what each database's
  driver gets is that output. Its notes on why each differs name pieces
  of that SQL, and the build fails if one isn't there.
- The dialect table, and the placeholder styles, come from
  `docs/design.md`.
- Each card on where dialects differ shows the rows of a test in
  `src/query-tests.temper.md`, between a comment `card: NAME` and a
  comment `end card`: its values, and what each dialect gives for them,
  as the test's asserts check.
- The tour shows each step's snippet from each program in `demos/tour/`,
  and from the Temper tour, a test in `src/tour-tests.temper.md`, with
  that step's part of `demos/tour/expected.txt`, which every one prints
  (`demos/run.py`, and `temper test` for the Temper). Every program must
  have every step, and the output's headings must be the steps'.

A snippet is the lines between a comment `snippet: NAME` and a comment
`end snippet`, each alone on its line, dedented. The build fails if one is
missing, or if the page has a slot left unfilled, and a card fails it if
its lines aren't the few shapes `cards` reads. A tour's step can be in
more than one block, such as a helper function and the code that calls
it, and the page shows them in order.

The tour runs in the page too, from a copy of Temper's JS output for
Wherewith, with Temper's JS runtime, as plain ES modules, which the page's
import map names, loaded only when the button is pressed. The build runs
the JavaScript tour in Node the way the page does (`tour-node.mjs` and
`tourrun.js`, as on Hrefine's and Kelpto's sites), against the built
`lib/`, and fails unless it prints `demos/tour/expected.txt`.
"""

import difflib
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
TOUR = ROOT / "demos" / "tour"
TEMPER_TOUR = ROOT / "src" / "tour-tests.temper.md"
JS = ROOT / "temper.out" / "js"
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

# The tour's programs, as LANGUAGES has them, in demos/tour/, and then the
# Temper, from the library's tests.
TOUR_LANGUAGES = [
    ("C++", "cpp", "cpp/tour.cpp", "//", "cmake -B build && cmake --build build && ./build/tour"),
    ("C#", "cs", "csharp/Program.cs", "//", "dotnet run"),
    ("Java", "java", "java/src/main/java/Tour.java", "//", "./gradlew run"),
    ("JavaScript", "js", "js/tour.js", "//", "npm ci && npm start"),
    ("Lua", "lua", "lua/tour.lua", "--", "lua -l paths tour.lua"),
    ("Python", "py", "py/tour.py", "#", "uv run tour.py"),
    ("Rust", "rs", "rust/src/main.rs", "//", "cargo run"),
    ("Temper", "temper", None, "//", "temper test"),
]

# The tour's steps: each snippet's name, and its heading in the output,
# where it has one.
TOUR_STEPS = [
    ("setup", None),
    ("write-once", "1. Write it once"),
    ("bound", "2. Values are bound, never spliced"),
    ("refused", "3. Refused when it's built"),
    ("differs", "4. What differs, handled"),
    ("nested", "5. Queries in queries"),
    ("dynamic", "6. Building queries in code"),
    ("placeholders", "7. Placeholders for each driver"),
    ("own-sql", "8. Each database's own SQL"),
    ("quoting", "9. Quoting by hand"),
]

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


def snippet_blocks(path, comment):
    """Every snippet in a file, by name: each of its blocks, dedented,
    joined by a blank line, in order."""
    found = {}
    name = None
    block = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text.startswith(f"{comment} snippet: "):
            if name is not None:
                raise SystemExit(f"{path.relative_to(ROOT)}: snippet {text!r} starts inside snippet {name!r}.")
            name, block = text.removeprefix(f"{comment} snippet: "), []
        elif text == f"{comment} end snippet":
            if name is None:
                raise SystemExit(f"{path.relative_to(ROOT)}: `{comment} end snippet` outside a snippet.")
            found.setdefault(name, []).append(textwrap.dedent("\n".join(block)).strip("\n"))
            name = None
        elif name is not None:
            block.append(line)
    if name is not None:
        raise SystemExit(f"{path.relative_to(ROOT)}: snippet {name!r} has no `{comment} end snippet`.")
    return {name: "\n\n".join(blocks) + "\n" for name, blocks in found.items()}


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


# What the opening says about each database's SQL: the pieces that differ
# from the others, marked, and why. Each piece must be in that database's
# SQL, and each `absent` must not, so the notes can't outlive the output.
RENDER_NOTES = {
    "sqlite": {
        "marks": ["NULLS LAST"],
        "absent": [],
        "why": "Sorts nulls first going up, so it keeps <code>NULLS LAST</code>.",
    },
    "postgres": {
        "marks": ["CAST($1 AS TEXT)"],
        "absent": ["NULLS"],
        "why": (
            "Already sorts nulls last going up, so <code>NULLS LAST</code> goes. "
            "The value gets a cast, so <code>||</code> reads it as text, whatever type the driver sends."
        ),
    },
    "mysql": {
        "marks": ["CONCAT", "`dueDate` IS NULL,", "'%%'"],
        "absent": ["||", "NULLS"],
        "why": (
            "<code>||</code> means <code>OR</code> here, so it&#8217;s <code>CONCAT</code>. "
            "No <code>NULLS LAST</code>, so it sorts by <code>IS NULL</code> first. "
            "With <code>%s</code> placeholders, <code>%</code> doubles."
        ),
    },
    "duckdb": {
        "marks": ["NULLS LAST"],
        "absent": [],
        "why": "Where nulls sort is a setting, so <code>NULLS LAST</code> is always written.",
    },
}

SQL_TOKEN = r"('(?:[^']|'')*')|(\"[^\"]*\"|`[^`]*`)|(\?|\$\d+|%s)"


def sql_tokens_html(sql):
    """SQL as HTML, with quoted names and placeholders marked, and a line
    break before each clause, outside quotes."""
    out = []
    last = 0
    for m in re.finditer(SQL_TOKEN, sql):
        plain = esc(sql[last : m.start()])
        out.append(re.sub(r" (WHERE|ORDER BY|LIMIT) ", r"\n\1 ", plain))
        if m[1]:
            out.append(f'<span class="q-str">{esc(m[1])}</span>')
        elif m[2]:
            out.append(f'<span class="q-name">{esc(m[2])}</span>')
        else:
            out.append(f'<span class="q-param">{esc(m[3])}</span>')
        last = m.end()
    out.append(re.sub(r" (WHERE|ORDER BY|LIMIT) ", r"\n\1 ", esc(sql[last:])))
    return "".join(out)


def sql_html(key, sql):
    """A database's SQL, with the pieces its notes name marked."""
    notes = RENDER_NOTES[key]
    for piece in notes["marks"]:
        if piece not in sql:
            raise SystemExit(f"The {key} SQL has no {piece!r}, which the opening marks: {sql}")
    for piece in notes["absent"]:
        if piece in sql:
            raise SystemExit(f"The {key} SQL has {piece!r}, which the opening says it doesn't: {sql}")
    marks = "|".join(re.escape(p) for p in sorted(notes["marks"], key=len, reverse=True))
    out = []
    last = 0
    for m in re.finditer(marks, sql):
        out.append(sql_tokens_html(sql[last : m.start()]))
        out.append(f"<mark>{sql_tokens_html(m[0])}</mark>")
        last = m.end()
    out.append(sql_tokens_html(sql[last:]))
    return "".join(out)


def common_query(temper):
    """The Temper's common query, from `let q = sql\"\"\"` to its `;`, as
    highlighted HTML, and its holes' values, in order."""
    lines = temper.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith('let q = sql"""')]
    if len(starts) != 1:
        raise SystemExit('The Temper snippet needs one `let q = sql"""` query.')
    end = next((i for i in range(starts[0], len(lines)) if lines[i].strip() == ";"), None)
    if end is None:
        raise SystemExit("The Temper snippet's query needs its own `;` line.")
    values = dict(re.findall(r'let (\w+) = ("[^"]*");', temper))
    holes = []

    def hole(m):
        expr = m[1]
        if not (expr.isdigit() or expr in values):
            raise SystemExit(f"The opening can't show the value of ${{{expr}}}.")
        holes.append(values.get(expr, expr))
        return f'<span class="hole">${{{esc(expr)}}}</span>'

    out = ['<span class="tok-keyword">let</span> q = <span class="tag">sql</span>"""']
    for line in lines[starts[0] + 1 : end]:
        m = re.fullmatch(r'(\s*)"(.*)', line)
        if not m:
            raise SystemExit(f"Each line of the query starts with a quote: {line!r}")
        body = re.sub(r"\$\{(\w+)\}", hole, esc(m[2]))
        out.append(f'{m[1]}<span class="margin">"</span>{body}')
    out.append(";")
    return "\n".join(out), values, holes


def hero(temper, rendered, rest):
    """The opening: one common query, as written in Temper, then what each
    database's driver gets, with what differs marked, and why."""
    query, values, holes = common_query(temper)
    if rest["params"] != str(len(holes)):
        raise SystemExit(f"The example has {rest['params']} parameters, and the query {len(holes)} holes.")
    if "word" not in values:
        raise SystemExit("The Temper snippet needs a `let word`.")
    # What the note under the query names.
    for piece in ['"dueDate"', "ESCAPE"]:
        if esc(piece) not in query:
            raise SystemExit(f"The opening's note names {piece}, which the query doesn't have.")
    rows = []
    for key, sql in rendered:
        placeholder = re.search(r"\?|\$1|%s", sql)
        if not placeholder:
            raise SystemExit(f"The {key} SQL has no placeholder: {sql}")
        rows.append(
            '<li class="target">'
            f'<p class="db">{esc(DIALECTS[key])} <span class="style"><code>{esc(placeholder[0])}</code> placeholders</span></p>'
            f'<pre class="sql" tabindex="0" aria-label="SQL for {esc(DIALECTS[key])}"><code>{sql_html(key, sql)}</code></pre>'
            f'<p class="why">{RENDER_NOTES[key]["why"]}</p>'
            "</li>"
        )
    params = ", ".join(f"<code>{esc(v)}</code>" for v in holes)
    return (
        '<div class="hero-demo">'
        f'<p class="label">Written once, in Temper, where <code>word</code> is <code>{esc(values["word"])}</code></p>'
        f'<pre class="source common-query" tabindex="0" aria-label="The common query"><code>{query}</code></pre>'
        '<p class="checked">Checked once, for all four: bare names are lowercase, since PostgreSQL folds them, '
        "so <code>\"dueDate\"</code> is quoted to keep its case, and a pattern that isn&#8217;t a literal "
        "needs <code>ESCAPE</code>, since PostgreSQL and MySQL read <code>\\</code> in it as an escape, "
        "and SQLite and DuckDB don&#8217;t.</p>"
        '<p class="label">What each database&#8217;s driver gets, with what differs marked</p>'
        f'<ul class="rendered">{"".join(rows)}</ul>'
        f'<p class="params"><span class="q-param-key">Parameters</span> {params}'
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


# The cards on where dialects differ, in the page's order. Each is a test
# in TEMPER_TEST, whose lines between `// card: NAME` and `// end card`
# are `let` values and `assert` rows.
CARDS = ["backslashes", "names", "comments"]

# How a card names a profile's or tag's call.
CALLS = {"quotedString": "quoteString", "quotedName": "quoteName"}

TEMPER_STRING = r'"(?:[^"\\]|\\.)*"'


def temper_string(literal):
    """A Temper string literal's text, for the few escapes cards use."""
    body = literal[1:-1]
    if "${" in body:
        raise SystemExit(f"Cards take no interpolation: {literal}")

    def unescape(m):
        if m[1] not in '\\"':
            raise SystemExit(f"Cards take only \\\\ and \\\" escapes: {literal}")
        return m[1]

    return re.sub(r"\\(.)", unescape, body)


def card_lines(name):
    """A card's statements, each joined onto one line."""
    lines = TEMPER_TEST.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == f"// card: {name}"]
    if len(starts) != 1:
        raise SystemExit(f"src/query-tests.temper.md needs one `// card: {name}` line.")
    statements = []
    pending = ""
    for line in lines[starts[0] + 1 :]:
        if line.strip() == "// end card":
            if pending:
                raise SystemExit(f"Card {name!r} has an unfinished line: {pending}")
            return statements
        pending = f"{pending} {line.strip()}".strip()
        if pending.endswith(";"):
            statements.append(pending)
            pending = ""
    raise SystemExit(f"Card {name!r} has no `// end card`.")


def card(name):
    """A card's example: for each call, the rows of what each dialect
    gives, with dialects that give the same joined in one row."""
    s = TEMPER_STRING
    values = {}
    blocks = []
    for line in card_lines(name):
        if m := re.fullmatch(rf"let (\w+) = ({s});", line):
            values[m[1]] = temper_string(m[2])
            continue
        if m := re.fullmatch(rf"assert\((quotedString|quotedName)\(Dialect\.(\w+), (\w+)\) == ({s})\);", line):
            call, dialect, var, want = m[1], m[2], m[3], m[4]
            head = f'<code>{CALLS[call]}({esc(var)})</code>'
        elif m := re.fullmatch(rf"assert\(withHole\(Dialect\.(\w+), ({s}), (\w+), ({s})\) == ({s})\);", line):
            dialect, before, var, after, want = m[1], m[2], m[3], m[4], m[5]
            before, after = (esc(temper_string(t)) for t in (before, after))
            head = f'Template <code>"{before}<span class="hole">${{{esc(var)}}}</span>{after}"</code>'
        else:
            raise SystemExit(f"Card {name!r} can't show this line: {line}")
        if var not in values:
            raise SystemExit(f"Card {name!r} uses {var}, which it doesn't set.")
        want = temper_string(want)
        if want.startswith("refused: "):
            result = f'<span class="refused">Refused:</span> {esc(want.removeprefix("refused: "))}'
        else:
            result = f"<code>{esc(want)}</code>"
        if not blocks or blocks[-1][0] != head:
            blocks.append((head, var, []))
        rows = blocks[-1][2]
        if rows and rows[-1][1] == result:
            rows[-1][0].append(dialect)
        else:
            rows.append(([dialect], result))
    if not blocks:
        raise SystemExit(f"Card {name!r} has no rows.")
    out = ['<div class="card-example">']
    shown = set()
    for head, var, rows in blocks:
        # Each value's text, quoted so its spaces show, where it's first used.
        where = "" if var in shown else f', where <code>{esc(var)}</code> is <code>"{esc(values[var])}"</code>'
        shown.add(var)
        out.append(f'<p class="card-call">{head}{where}</p>')
        out.append('<ul class="card-rows">')
        for dialects, result in rows:
            who = ", ".join(f"<code>{esc(d)}</code>" for d in dialects)
            out.append(f'<li><span class="who">{who}</span><span class="gives">{result}</span></li>')
        out.append("</ul>")
    out.append("</div>")
    return "".join(out)


def tour_output():
    """The tour's output, by step: each heading's lines, checked against
    the steps."""
    text = (TOUR / "expected.txt").read_text(encoding="utf-8")
    parts = re.split(r"^## (.*)$", text, flags=re.M)
    if parts[0].strip() != "# Wherewith tour":
        raise SystemExit("demos/tour/expected.txt doesn't start with the tour's title.")
    found = dict(zip(parts[1::2], (p.strip("\n") + "\n" for p in parts[2::2])))
    titles = [title for _, title in TOUR_STEPS if title]
    if list(found) != titles:
        raise SystemExit(f"demos/tour/expected.txt's headings aren't the tour's steps: {list(found)}")
    return text, found


def tour_sources():
    """Each tour language's snippets, by step, checked for every step."""
    sources = {}
    names = [name for name, _ in TOUR_STEPS]
    for lang, id, path, comment, _ in TOUR_LANGUAGES:
        file = TEMPER_TOUR if path is None else TOUR / path
        found = snippet_blocks(file, comment)
        if set(found) != set(names):
            raise SystemExit(f"{file.relative_to(ROOT)} has steps {sorted(found)}, not {sorted(names)}.")
        sources[id] = found
    return sources


def tour_html(sources, outputs):
    """The tour: a row of language tabs, then each step's code in each
    language, and what it prints."""
    tabs = []
    for name, id, _, _, _ in TOUR_LANGUAGES:
        on = id == DEFAULT_LANGUAGE
        controls = " ".join(f"tour-{step}-{id}" for step, _ in TOUR_STEPS) + f" tour-run-{id}"
        tabs.append(
            f'<button type="button" role="tab" id="tour-tab-{id}" data-lang="{id}" aria-controls="{controls}" '
            f'aria-selected="{str(on).lower()}" tabindex="{0 if on else -1}">{esc(name)}</button>'
        )
    out = [f'<div class="tabs tour-tabs" role="tablist" aria-label="Tour language">{"".join(tabs)}</div>']
    for name, id, path, comment, run in TOUR_LANGUAGES:
        hidden = "" if id == DEFAULT_LANGUAGE else " hidden"
        if path is None:
            where = (
                f'<a href="{REPO}/blob/main/src/tour-tests.temper.md"><code>src/tour-tests.temper.md</code></a>, '
                f"a test, which checks it prints the same: <code>{esc(run)}</code>"
            )
        else:
            folder = path.split("/")[0]
            where = (
                f'<a href="{REPO}/tree/main/demos/tour/{folder}"><code>demos/tour/{folder}</code></a>:'
                f" <code>{esc(run)}</code>"
            )
        out.append(
            f'<p class="run" role="tabpanel" id="tour-run-{id}" aria-labelledby="tour-tab-{id}"{hidden}>'
            f"The whole {esc(name)} tour is in {where}</p>"
        )
    for step, title in TOUR_STEPS:
        heading = title or "Setup"
        out.append(f'<div class="step" id="tour-{step}"><h3>{esc(heading)}</h3>')
        for name, id, _, comment, _ in TOUR_LANGUAGES:
            hidden = "" if id == DEFAULT_LANGUAGE else " hidden"
            out.append(
                f'<div class="lang-panel" role="tabpanel" id="tour-{step}-{id}" aria-labelledby="tour-tab-{id}"{hidden}>'
                f"{code_block(sources[id][step], comment, f'{heading}, in {name}')}</div>"
            )
        if title:
            out.append(
                f'<p class="output-label">It prints:</p>'
                f'<pre class="output step-output" tabindex="0" aria-label="What {esc(heading)} prints">'
                f"{''.join(f'<span>{esc(line)}</span>' for line in outputs[title].splitlines())}</pre>"
            )
        out.append("</div>")
    return "\n".join(out)


def copy_module(source, dest):
    """A JS module without its source map comment, as the maps aren't copied."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    dest.write_text(re.sub(r"\n//# sourceMappingURL=\S+\s*$", "\n", text), encoding="utf-8")


def link_modules(name):
    """Gives each `./x.js` that a built module imports its file's hash, as
    the page's references get theirs."""
    path = OUT / name
    text = path.read_text(encoding="utf-8")

    def hashed(m):
        digest = hashlib.sha256((OUT / m[2]).read_bytes()).hexdigest()[:10]
        return f'{m[1]}"./{m[2]}?v={digest}";'

    path.write_text(re.sub(r'^(import .* from )"\./([\w-]+\.js)";$', hashed, text, flags=re.M), encoding="utf-8")


def check_tour_run(expected):
    """Fails unless the built JS tour, run as the page runs it, prints
    what every tour prints."""
    try:
        run = subprocess.run(
            ["node", str(SITE / "tour-node.mjs"), str(OUT)], capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError:
        raise SystemExit("The build needs Node (24 or later), to run the JS tour.")
    if run.returncode:
        raise SystemExit(f"The JS tour doesn't run as the page runs it:\n{run.stderr}")
    if run.stdout != expected:
        diff = difflib.unified_diff(
            expected.splitlines(keepends=True), run.stdout.splitlines(keepends=True), "expected.txt", "in the page"
        )
        raise SystemExit(f"The JS tour, run as the page runs it, prints otherwise:\n{''.join(diff)}")


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
    if not (JS / "wherewith" / "wherewith.internal.js").exists():
        raise SystemExit("Build the JS library first: temper build -b js")
    if "--no-check" not in sys.argv[1:]:
        check_js()
    temper = snippet(TEMPER_TEST, "temper", "//")
    text, rendered, rest = example_output()
    tour_text, tour_outputs = tour_output()
    tour_snippets = tour_sources()
    design = DESIGN.read_text(encoding="utf-8")

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    # GitHub Pages serves files as they are, without Jekyll.
    (OUT / ".nojekyll").touch()
    for name in ["style.css", "app.js", "tourrun.js"]:
        shutil.copyfile(SITE / name, OUT / name)
    link_modules("app.js")

    # The library, for running the tour in the page.
    lib = []
    for package, folder in [("wherewith", "wherewith"), ("temper-core", "temper-core")]:
        for path in sorted((JS / folder).glob("*.js")):
            copy_module(path, OUT / "lib" / package / path.name)
            lib.append(OUT / "lib" / package / path.name)
    (OUT / "tour").mkdir()
    shutil.copyfile(TOUR / "js" / "tour.js", OUT / "tour" / "tour.js")
    shutil.copyfile(TOUR / "expected.txt", OUT / "tour" / "expected.txt")
    check_tour_run(tour_text)

    page = (SITE / "index.html").read_text(encoding="utf-8")
    parts = {
        "HERO": hero(temper, rendered, rest),
        "TEMPER": f'<p class="code-label">Temper</p>{code_block(temper, "//", "Temper")}',
        "TABS": tabs(),
        "PANELS": panels(),
        "OUTPUT": f'<pre class="output" tabindex="0" aria-label="Output">{esc(text)}</pre>',
        "STYLES": styles(design),
        "DIALECTS": dialects(design),
        "TOUR": tour_html(tour_snippets, tour_outputs),
        "TOUR_LINES": str(len(tour_text.splitlines())),
        **{f"CARD_{name.upper()}": card(name) for name in CARDS},
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

    raw, gz = sizes([OUT / "index.html", OUT / "style.css", OUT / "app.js", OUT / "tourrun.js"])
    print(f"The page, with its style and scripts: {raw} bytes, {gz} gzipped")
    raw, gz = sizes(lib)
    print(f"Wherewith and Temper's JS runtime, loaded to run the tour: {raw} bytes, {gz} gzipped")
    print(f"Built {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
