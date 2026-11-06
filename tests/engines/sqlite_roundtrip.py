"""Round-trip Wherewith's SQLite output through the real SQLite engine.

    temper build -b py
    uv run tests/engines/sqlite_roundtrip.py [--out temper.out/py] [-v]

Uses Python's standard `sqlite3` and the Python library Temper generates
in `temper.out/py`, with the checks in `roundtrip.py`, for many hostile
inputs: SQLite reads quoted strings back exactly, quoted names make a
table and column that read back exactly from `sqlite_schema` and
`pragma_table_info`, values bound in each style `sqlite3` takes (`?`,
`:p1`, `@p1`, and `$1`) come back equal with the type SQLite stores,
and nested queries, operators, and random templates give the expected
rows. Inputs Wherewith rejects (NUL and lone surrogates in strings, and
empty names) must be rejected.

Exits 1, printing a minimal repro for each, if the engine disagrees.
"""

import math
import sqlite3
import sys
import time

import roundtrip as rt
from roundtrip import H, Style


class Sqlite(rt.Engine):
    def __init__(self) -> None:
        ww = rt.ww
        self.dialect = ww.Dialect.sqlite
        self.tag_class = ww.SqliteTag
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        # A "..." that names no column reads as a string unless DQS is
        # off, which would hide a misquoted name. Python 3.12 can turn
        # it off.
        self.dqs_off = hasattr(self.conn, "setconfig")
        if self.dqs_off:
            self.conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)
            self.conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DDL, False)

        def by_position(ps):
            return tuple(rt.py_value(p) for p in ps)

        def by_name(ps):
            return {f"p{i}": rt.py_value(p) for i, p in enumerate(ps, 1)}

        def by_number(ps):
            return {str(i): rt.py_value(p) for i, p in enumerate(ps, 1)}

        # Each style Python's sqlite3 takes: `?` by position, and names
        # by key without their first character, so `$1` (SQLite's `$`
        # names) binds too. `%s` isn't SQLite syntax.
        self._styles = [
            Style("question", ww.PlaceholderStyle.question, self.runner(by_position)),
            Style("colonNamed", ww.PlaceholderStyle.colon_named, self.runner(by_name)),
            Style("atNamed", ww.PlaceholderStyle.at_named, self.runner(by_name)),
            Style("dollarNumbered", ww.PlaceholderStyle.dollar_numbered, self.runner(by_number)),
        ]

    def runner(self, bind):
        def run(r, with_description=False):
            cur = self.conn.execute(r.sql, bind(r.params))
            rows = cur.fetchall()
            return (rows, cur.description) if with_description else rows

        return run

    def describe(self) -> str:
        return (f"SQLite {sqlite3.sqlite_version}, Python {sys.version.split()[0]}, "
                f"DQS {'off' if self.dqs_off else 'on (Python < 3.12)'}")

    def execute(self, sql: str, params=()) -> list[tuple]:
        return self.conn.execute(sql, params).fetchall()

    def styles(self) -> list[Style]:
        return self._styles

    def read_string(self, q: str):
        got, kind = self.execute(f"SELECT {q}, typeof({q})")[0]
        return got if kind == "text" else (got, kind)

    # NUL ends SQLite's SQL text, but binds fine.
    def bindable(self, s: str) -> bool:
        return not rt.has_surrogate(s)

    # SQLite reserves table names starting with sqlite_, whatever the
    # quoting, so those test as a column only.
    def table_for(self, n: str) -> str:
        return f"t_{n}" if n.lower().startswith("sqlite_") else n

    def catalogs(self, table: str):
        tables = [r[0] for r in self.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")]
        cols = [r[0] for r in self.execute("SELECT name FROM pragma_table_info(?)", (table,))]
        return [("sqlite_schema and table_info", tables, cols)]

    def value_exprs(self, v):
        return [("", ""), ("typeof(", ")")]

    def expected_row(self, v) -> tuple:
        """What SQLite gives back for a value, and its typeof."""
        ww = rt.ww
        if isinstance(v, ww.SqlText):
            return v.value, "text"
        if isinstance(v, ww.SqlBool):
            return int(v.value), "integer"
        if isinstance(v, ww.SqlInt):
            return v.value, "integer"
        if isinstance(v, ww.SqlFloat):
            # SQLite stores NaN as NULL.
            return (None, "null") if math.isnan(v.value) else (v.value, "real")
        return None, "null"

    values_table = "CREATE TABLE v (i INTEGER, x)"
    values_select = "SELECT i, x, typeof(x) FROM v ORDER BY i"

    def value_column(self, v) -> str:
        return "x"

    def table_row(self, v) -> tuple:
        return self.expected_row(v)

    def nesting_setup(self) -> None:
        self.execute("CREATE TABLE n (a, b, c)")
        self.conn.executemany("INSERT INTO n VALUES (?, ?, ?)", [(1, None, 9), (1, 2, 9), (5, 5, 3), (1, None, 3)])
        self.execute('CREATE TABLE "n t" ("a""b`c")')
        self.execute('INSERT INTO "n t" VALUES (42)')

    def nesting_teardown(self) -> None:
        self.execute("DROP TABLE n")
        self.execute('DROP TABLE "n t"')

    def nesting_cases(self):
        ww = rt.ww

        def tag(*pieces):
            return rt.template(ww.SqliteTag, *pieces)

        neg = tag("-1")
        empty = tag("")
        commented = tag("SELECT 1 -- note")
        where = tag("WHERE a = ", H(1), " AND b IS ", H(None))
        inner = tag("b = ", H(2), " OR c = ", H(3))
        deepest = tag(H("c"))
        deeper = tag(H("b"), " || ", H(deepest))
        deep = tag(H("a"), " || ", H(deeper), " || ", H("d"))
        t = ww.Identifier.named("n t")
        c = ww.Identifier.named("a\"b`c")
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
            (tag("SELECT ", H(7), "%", H(4)), [(3,)]),
            (tag("SELECT ", H("a"), "||", H("b")), [("ab",)]),
            (tag("SELECT 'x'||", H("y"), "||'z'"), [("xyz",)]),
            (tag("SELECT ", H(1), "<", H(2), ", ", H(2), "<=", H(2), ", ", H(1), "<>", H(1)), [(1, 1, 0)]),
            (tag("SELECT ", H(6), "&", H(3), ", ", H(6), "|", H(3), ", ", H(1), "<<", H(4), ", ~", H(0)), [(2, 7, 16, -1)]),
            (tag("SELECT ", H(deep), ", ", H(deep)), [("abcd", "abcd")]),
            (tag(H(commented), " UNION ALL SELECT ", H(2)), [(1,), (2,)]),
            (tag("SELECT a, b, c FROM n ", H(where), " ORDER BY c LIMIT ", H(10)), [(1, None, 3), (1, None, 9)]),
            (tag("SELECT count(*) FROM n WHERE a = ", H(1), " AND (", H(inner), ")"), [(2,)]),
            (tag("SELECT ", H(c), " FROM ", H(t)), [(42,)]),
            (tag("SELECT ", H(t), ".", H(c), " FROM ", H(t)), [(42,)]),
            (tag("SELECT x.", H(c), " FROM ", H(t), " AS x"), [(42,)]),
            (tag("SELECT (SELECT ", H(c), " FROM ", H(t), " WHERE ", H(c), " = ", H(42), ") + ", H(1)), [(43,)]),
            (tag("SELECT ", H(1), " -- what? 'x\n, ", H(2), " /* ? */ AS [a?], 0 AS `b:c`, ", H(3), " AS \"$d\""),
             [(1, 2, 0, 3)]),
            (tag("SELECT ", H(1), " IN (", H(1), ", ", H(2), "), ", H(None), " IS NULL"), [(1, 1)]),
            (tag("SELECT CASE WHEN ", H(True), " THEN ", H("y"), " ELSE ", H("n"), " END"), [("y",)]),
        ]

    def random_comment(self, rng, body: str) -> str:
        if rng.random() < 0.5:
            return "/*" + body.replace("*/", "") + "*/"
        return "--" + body.replace("\n", "") + "\n"

    def random_alias(self, rng, names: list[str]) -> str:
        r = rng.random()
        name = rng.choice(names)
        if r < 0.5:
            return " AS " + self.dialect.quote_name(name)
        if r < 0.75:
            return " AS [" + name.replace("]", "") + "]"
        return " AS `" + name.replace("`", "") + "`"


def main() -> int:
    args = rt.arguments(__doc__).parse_args()
    if (status := rt.start(args)) is not None:
        return status
    started = time.perf_counter()
    rt.run_all(Sqlite(), args)
    return rt.finish(args, started)


if __name__ == "__main__":
    sys.exit(main())
