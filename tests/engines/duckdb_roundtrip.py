"""Round-trip Wherewith's DuckDB output through the real DuckDB engine.

    temper build -b py
    uv run tests/engines/duckdb_roundtrip.py [--out temper.out/py] [-v]

Uses the `duckdb` package (embedded, in memory, so no server) and the
Python library Temper generates in `temper.out/py`, with the checks in
`roundtrip.py`, for many hostile inputs: quoted strings read back
exactly, quoted names make a table and column that read back exactly
from `information_schema` and `duckdb_tables()` and `duckdb_columns()`,
values bound in each style the Python API takes (`?` and `$1` with a
list, and `$1` with a dict keyed by number) come back equal with the
type asked for, and nested queries, operators, and random templates
give the expected rows. Inputs Wherewith rejects (NUL and lone
surrogates in strings, and empty names, NUL, and lone surrogates in
names) must be rejected.

It also checks DuckDB's Unicode space pass, which turns some Unicode
spaces into plain ones before parsing: that the spaces it changes are
the ones the lexer knows, and, for random text in a block comment, that
the lexer finds the pass out of step exactly when DuckDB's is. And it
records DuckDB's own limits.

Exits 1, printing a minimal repro for each, if the engine disagrees.
"""

import random
import sys
import time
import unicodedata

import roundtrip as rt
from roundtrip import H, Style

OUT_OF_STEP = "quote or comment DuckDB's Unicode space pass misreads"
CHANGED = "Unicode space DuckDB would change inside a quote"


class Duckdb(rt.Engine):
    corpus_name = "duckdb"
    corpus_types = {"int": "BIGINT", "text": "VARCHAR", "float": "DOUBLE", "bool": "BOOLEAN"}

    def __init__(self) -> None:
        import duckdb  # noqa: PLC0415

        self.duckdb = duckdb
        ww = rt.ww
        self.dialect = ww.Dialect.duckdb
        self.tag_class = ww.DuckdbTag
        # Few threads and a modest memory limit: these are small queries,
        # and DuckDB's default of a thread per core reserves much memory.
        self.conn = duckdb.connect(":memory:", config={"threads": 2, "memory_limit": "1GB"})

        def by_position(ps):
            return [rt.py_value(p) for p in ps]

        def by_number(ps):
            return {str(i): rt.py_value(p) for i, p in enumerate(ps, 1)}

        # Each style the Python API takes: `?` and `$1` by position, and
        # `$1` by name, as DuckDB's `$name` with names that are numbers.
        self._styles = [
            Style("question", ww.PlaceholderStyle.question, self.runner(by_position)),
            Style("dollarNumbered", ww.PlaceholderStyle.dollar_numbered, self.runner(by_position)),
            Style("dollarNumbered by name", ww.PlaceholderStyle.dollar_numbered, self.runner(by_number)),
        ]

    def runner(self, bind):
        def run(r, with_description=False):
            cur = self.conn.execute(r.sql, bind(r.params))
            rows = cur.fetchall() if cur.description else []
            return (rows, cur.description) if with_description else rows

        return run

    def close(self) -> None:
        self.conn.close()

    def describe(self) -> str:
        return f"DuckDB {self.duckdb.__version__}, Python {sys.version.split()[0]}"

    def execute(self, sql: str, params=()) -> list[tuple]:
        cur = self.conn.execute(sql, list(params))
        return cur.fetchall() if cur.description else []

    def execute_described(self, sql: str):
        cur = self.conn.execute(sql)
        return cur.fetchall(), cur.description

    def styles(self) -> list[Style]:
        return self._styles

    def catalogs(self, table: str):
        info_tables = [r[0] for r in self.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'")]
        info_cols = [r[0] for r in self.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position", [table])]
        tables = [r[0] for r in self.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main' AND NOT internal")]
        cols = [r[0] for r in self.execute(
            "SELECT column_name FROM duckdb_columns()"
            " WHERE schema_name = 'main' AND table_name = ? ORDER BY column_index", [table])]
        return [("information_schema", info_tables, info_cols), ("duckdb_tables and duckdb_columns", tables, cols)]

    TYPES = {"SqlText": "VARCHAR", "SqlNull": "VARCHAR", "SqlInt": "BIGINT", "SqlFloat": "DOUBLE",
             "SqlBool": "BOOLEAN"}
    COLUMNS = {"SqlText": "t", "SqlNull": "t", "SqlInt": "n", "SqlFloat": "f", "SqlBool": "b"}

    def value_exprs(self, v):
        # Cast to the type asked for, and bare, as DuckDB infers it.
        return [("CAST(", f" AS {self.TYPES[type(v).__name__]})"), ("", "")]

    def expected_row(self, v) -> tuple:
        return rt.py_value(v), rt.py_value(v)

    values_table = "CREATE TABLE v (i INTEGER PRIMARY KEY, t VARCHAR, n BIGINT, f DOUBLE, b BOOLEAN)"
    values_select = "SELECT i, t, n, f, b FROM v ORDER BY i"

    def value_column(self, v) -> str:
        return self.COLUMNS[type(v).__name__]

    def table_row(self, v) -> tuple:
        column = self.value_column(v)
        return tuple(rt.py_value(v) if c == column else None for c in "tnfb")

    def nesting_setup(self) -> None:
        self.execute("CREATE TABLE n (a INTEGER, b INTEGER, c INTEGER)")
        self.execute("INSERT INTO n VALUES (1, NULL, 9), (1, 2, 9), (5, 5, 3), (1, NULL, 3)")
        self.execute('CREATE TABLE "n t" ("a""b`c" INTEGER)')
        self.execute('INSERT INTO "n t" VALUES (42)')

    def nesting_teardown(self) -> None:
        self.execute("DROP TABLE n")
        self.execute('DROP TABLE "n t"')

    def nesting_cases(self):
        ww = rt.ww

        def tag(*pieces):
            return rt.template(ww.DuckdbTag, *pieces)

        neg = tag("-1")
        empty = tag("")
        commented = tag("SELECT 1 -- note")
        where = tag("WHERE a = ", H(1), " AND b IS NOT DISTINCT FROM ", H(None))
        inner = tag("b = ", H(2), " OR c = ", H(3))
        deepest = tag(H("c"))
        deeper = tag(H("b"), " || ", H(deepest))
        deep = tag(H("a"), " || ", H(deeper), " || ", H("d"))
        t = ww.Identifier.named("n t")
        c = ww.Identifier.named("a\"b`c")
        sp = "\xa0"
        return [
            (tag("SELECT 5-", H(-1)), [(6,)]),
            (tag("SELECT -", H(-1)), [(1,)]),
            (tag("SELECT - ", H(-1), "-", H(-1)), [(2,)]),
            (tag("SELECT 2*-", H(3)), [(-6,)]),
            (tag("SELECT 5-", H(neg)), [(6,)]),
            (tag("SELECT ", H(neg), "-1"), [(-2,)]),
            # The empty query keeps `1-` and `-1` apart: 1 - -1, not a comment.
            (tag("SELECT 1-", H(empty), "-1"), [(2,)]),
            (tag("SELECT ", H(1), "+", H(2), "*", H(3)), [(7,)]),
            (tag("SELECT ", H(7), "/", H(2.0)), [(3.5,)]),
            (tag("SELECT ", H(7), "%", H(4), ", ", H(7), "//", H(2)), [(3, 3)]),
            (tag("SELECT ", H("a"), "||", H("b")), [("ab",)]),
            (tag("SELECT 'x'||", H("y"), "||'z'"), [("xyz",)]),
            (tag("SELECT ", H(1), "<", H(2), ", ", H(2), "<=", H(2), ", ", H(1), "<>", H(1)), [(True, True, False)]),
            (tag("SELECT ", H(6), "&", H(3), ", ", H(6), "|", H(3), ", ", H(1), "<<", H(4), ", ~", H(0)),
             [(2, 7, 16, -1)]),
            (tag("SELECT ", H(deep), ", ", H(deep)), [("abcd", "abcd")]),
            (tag(H(commented), " UNION ALL SELECT ", H(2)), [(1,), (2,)]),
            (tag("SELECT a, b, c FROM n ", H(where), " ORDER BY c LIMIT ", H(10)), [(1, None, 3), (1, None, 9)]),
            (tag("SELECT count(*) FROM n WHERE a = ", H(1), " AND (", H(inner), ")"), [(2,)]),
            (tag("SELECT ", H(c), " FROM ", H(t)), [(42,)]),
            (tag("SELECT ", H(t), ".", H(c), " FROM ", H(t)), [(42,)]),
            (tag("SELECT x.", H(c), " FROM ", H(t), " AS x"), [(42,)]),
            (tag("SELECT (SELECT ", H(c), " FROM ", H(t), " WHERE ", H(c), " = ", H(42), ") + ", H(1)), [(43,)]),
            (tag("SELECT ", H(1), " -- what? 'x\n, ", H(2), " /* ? /* $1 */ '' */ AS \"a?\", 0 AS `b:c`, ",
                 H(3), " AS \"$d\", $$ ? $$ AS e, $x$ $1 $x$ AS f, [10, 20, 30][2:", H(3), "] AS g"),
             [(1, 2, 0, 3, " ? ", " $1 ", [20, 30])]),
            (tag("SELECT ", H(1), " IN (", H(1), ", ", H(2), "), ", H(None), " IS NULL"), [(True, True)]),
            (tag("SELECT CASE WHEN ", H(True), " THEN ", H("y"), " ELSE ", H("n"), " END"), [("y",)]),
            (tag("SELECT {'a': ", H(1), "}.a, list_transform([", H(2), "], lambda x: x + 1)"), [(1, [3])]),
            # A carriage return ends a line comment.
            (tag("SELECT 1 -- c\r, ", H(2)), [(1, 2)]),
            # An E string goes on past a doubled quote, and past
            # whitespace and line comments with a line break.
            (tag("SELECT E'a''b\\\\c'\n -- x\r\n'd\\\\', ", H(3)), [("a'b\\cd\\", 3)]),
            # Unicode spaces: plain spaces in code, so one before `E'`
            # makes an E string, and one before a line break lets an E
            # string go on; kept in quotes.
            (tag(f"SELECT{sp}", H(1), f",﻿'a{sp}b', $$c{sp}$$, 1 AS \"d{sp}\", {sp}E'\\\\'"),
             [(1, f"a{sp}b", f"c{sp}", 1, "\\")]),
            (tag(f"SELECT E'a'{sp}\n'\\\\', ", H(2)), [("a\\", 2)]),
            (tag("SELECT 1 /* it''s */, ", H(f"x{sp}"), f", 'y{sp}'"), [(1, f"x{sp}", f"y{sp}")]),
        ]

    def random_comment(self, rng, body: str) -> str:
        r = rng.random()
        # Mostly without what puts DuckDB's Unicode space pass out of
        # step in a block comment, so most templates build; with it,
        # many are refused, and those are skipped.
        if rng.random() < 0.8:
            body = rt.without(body, "'", '"', "$", "--")
        # Block comments nest, so each `/*` needs its own `*/`. Spaces
        # keep a body's `/` or `*` from joining a marker.
        if r < 0.25:
            a, b = sorted(rng.randint(0, len(body)) for _ in range(2))
            x, y, z = (rt.without(t, "*/", "/*") for t in (body[:a], body[a:b], body[b:]))
            return f"/* {x} /* {y} */ {z} */"
        if r < 0.5:
            return "/* " + rt.without(body, "*/", "/*") + " */"
        # A line feed or a carriage return ends a line comment.
        return "--" + rt.without(body, "\n", "\r") + rng.choice(["\n", "\r", "\r\n"])

    def random_alias(self, rng, names: list[str]) -> str:
        name = rng.choice(names)
        if rng.random() < 0.7:
            return " AS " + self.dialect.quote_name(name)
        # Backtick names, mostly without what the Unicode space pass
        # misreads in them.
        if rng.random() < 0.8:
            name = "".join(ch for ch in rt.without(name, "'", '"', "$", "--") if ch not in UNICODE_SPACES)
        name = name.replace("`", "``")
        return " AS `" + (name or "x") + "`"

    def limits(self) -> None:
        d = self.dialect
        notes = []
        # Long names: DuckDB keeps them whole.
        long_name = "x" * 100_000
        self.execute(f"CREATE TABLE {d.quote_name(long_name)} (c INTEGER)")
        got = self.execute("SELECT length(table_name) FROM duckdb_tables() WHERE schema_name = 'main'")
        notes.append(f"a 100,000-character name stays {got[0][0]}")
        self.execute(f"DROP TABLE {d.quote_name(long_name)}")
        if d.name_problem(long_name) is not None:
            rt.fail("limits", "the duckdb profile limits names, though DuckDB doesn't")
        # Names match without regard to ASCII case, even quoted.
        try:
            self.execute('CREATE TABLE "Case" ("A" INTEGER, "a" INTEGER)')
            notes.append('"A" and "a" are different columns')
            self.execute('DROP TABLE "Case"')
        except self.duckdb.Error:
            notes.append('"A" and "a" are the same column')
        # What DuckDB takes that Wherewith rejects anyway: NUL in names
        # and in string literals (its C API ends SQL text at a NUL).
        for label, sql in [("a NUL in a name", 'SELECT 1 AS "a\x00b"'), ("a NUL in a literal", "SELECT 'a\x00b'")]:
            try:
                self.execute(sql)
                notes.append(f"{label} accepted")
            except self.duckdb.Error:
                notes.append(f"{label} rejected")
        try:
            self.execute('SELECT 1 AS ""')
            rt.fail("limits", "DuckDB took an empty name")
        except self.duckdb.Error:
            notes.append("an empty name rejected")
        # The Unicode spaces DuckDB changes, among separators, controls,
        # and format characters: each is whitespace in code, and the
        # lexer must refuse it in a backtick name, where DuckDB changes
        # it, and no other.
        spaces = []
        for cp in range(0x80, 0x110000):
            ch = chr(cp)
            if unicodedata.category(ch) not in ("Zs", "Zl", "Zp", "Cc", "Cf") or rt.has_surrogate(ch):
                continue
            rt.count("unicode spaces checked")
            try:
                changed = self.execute(f"SELECT 1{ch}+{ch}1") == [(2,)]
            except self.duckdb.Error:
                changed = False
            if changed:
                spaces.append(cp)
            b = rt.ww.QueryBuilder(d)
            b.append_safe(f"SELECT 1 AS `a{ch}b`")
            if (b.template_problem == CHANGED) != changed:
                rt.fail("limits", f"U+{cp:04X}: DuckDB {'changes' if changed else 'keeps'} it,"
                        f" but the lexer says {b.template_problem!r}")
        if set(spaces) != UNICODE_SPACES_CP:
            rt.fail("limits", f"DuckDB's Unicode spaces are {[f'U+{c:04X}' for c in spaces]}")
        notes.append(f"{len(spaces)} Unicode spaces changed")
        rt.count("limits checked", len(notes))
        print("  limits: " + "; ".join(notes))


UNICODE_SPACES_CP = {0xA0, *range(0x2000, 0x200C), 0x202F, 0x205F, 0x2060, 0x3000, 0xFEFF}
UNICODE_SPACES = {chr(c) for c in UNICODE_SPACES_CP}


def check_space_pass(e: Duckdb, seed: int, n: int) -> None:
    """Random text in a block comment, which DuckDB's parser skips but
    its Unicode space pass reads as code. After the comment, a quoted
    Unicode space must stay and one in code must become a plain space
    exactly when the lexer finds the pass in step."""
    d = e.dialect
    rng = random.Random(seed)
    sp = "\xa0"
    pieces = ["'", '"', "`", "$", "$$", "$a$", "$b$", "$1", "--", "\n", "\r", "a", " ", "1", "\\", "E", "_",
              "é", sp, "﻿", "$a", "b$", "''", "*", "/"]
    for _ in range(n):
        body = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
        body = rt.without(body, "/*", "*/")
        if body.endswith(("/", "*", "-")):
            body += " "
        sql = f"SELECT 1 /* {body} */, '{sp}' = chr(160), 1{sp}+{sp}1"
        rt.count("space pass")
        b = rt.ww.QueryBuilder(d)
        b.append_safe(sql)
        problem = b.template_problem
        if problem not in (None, OUT_OF_STEP):
            fail_text = f"lexer gave {problem!r} for {body!r}"
            rt.fail("space pass", fail_text)
            continue
        try:
            in_step = e.execute(sql) == [(1, True, 2)]
        except e.duckdb.Error:
            in_step = False
        if in_step != (problem is None):
            rt.fail("space pass", f"DuckDB's pass is {'in' if in_step else 'out of'} step after {body!r},"
                    f" but the lexer says {problem!r}")
        elif problem:
            rt.count("space pass out of step")


def main() -> int:
    args = rt.arguments(__doc__).parse_args()
    if (status := rt.start(args)) is not None:
        return status
    started = time.perf_counter()
    engine = Duckdb()
    try:
        rt.run_all(engine, args)
        t = time.perf_counter()
        before = len(rt.failures)
        check_space_pass(engine, args.seed, args.templates)
        if args.verbose or len(rt.failures) > before:
            print(f"  space pass: {len(rt.failures) - before} failures, {time.perf_counter() - t:.1f} s")
    finally:
        engine.close()
    return rt.finish(args, started)


if __name__ == "__main__":
    sys.exit(main())
