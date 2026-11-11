"""Round-trip Wherewith's PostgreSQL output through a real PostgreSQL server.

    temper build -b py
    uv run tests/engines/postgres_roundtrip.py [--out temper.out/py] [-v]

Uses psycopg 3 and the Python library Temper generates in
`temper.out/py`, with the checks in `roundtrip.py`, for many hostile
inputs: quoted strings read back exactly as text, quoted names make a
table and column that read back exactly from `information_schema` and
`pg_catalog`, values bound with `%s` (psycopg's server-side and
client-side cursors) and `$1` (its raw cursor, which sends the SQL
unchanged) come back equal with the type asked for, and nested
queries, operators, and random templates give the expected rows. The
common corpus runs once more with every value sent untyped, as text
of unknown type, as node-postgres (`pg`) sends them, so PostgreSQL
types each from what's around it.
Inputs Wherewith rejects (NUL and lone surrogates in strings; empty
names, NUL, lone surrogates, and names over 63 bytes) must be rejected.
It also checks that `standard_conforming_strings` is on, as the profile
assumes, and records the server's own limits.

The server comes from these variables, with defaults matching CI:
WHEREWITH_PG_HOST (127.0.0.1), WHEREWITH_PG_PORT (5432),
WHEREWITH_PG_USER (postgres), WHEREWITH_PG_PASSWORD (wherewith, a
throwaway for the CI service container), and WHEREWITH_PG_DATABASE
(postgres). Tests run in a schema `wherewith_roundtrip`, dropped and
made again. With no server reachable, it skips, exiting 0, unless
`--require-server` is given.

Exits 1, printing a minimal repro for each, if the engine disagrees.
"""

import contextlib
import os
import sys
import time

import roundtrip as rt
from roundtrip import H, Style

SCHEMA = "wherewith_roundtrip"


def untyped_dumper(psycopg):
    """A psycopg dumper sending a value as text of unknown type (OID 0),
    as node-postgres (`pg`) sends every value. psycopg already sends
    `str` and `None` that way."""

    class Untyped(psycopg.adapt.Dumper):
        oid = 0

        def dump(self, obj):
            if isinstance(obj, bool):
                return b"true" if obj else b"false"
            return str(obj).encode()

    return Untyped


class Postgres(rt.Engine):
    corpus_name = "postgres"

    def __init__(self, host: str, port: int) -> None:
        import psycopg  # noqa: PLC0415

        self.psycopg = psycopg
        ww = rt.ww
        self.dialect = ww.Dialect.postgres
        self.tag_class = ww.PostgresTag
        env = os.environ.get
        self.conn = psycopg.connect(
            host=host, port=port, user=env("WHEREWITH_PG_USER", "postgres"),
            password=env("WHEREWITH_PG_PASSWORD", "wherewith"),
            dbname=env("WHEREWITH_PG_DATABASE", "postgres"),
            client_encoding="utf8", autocommit=True, prepare_threshold=None,
        )
        self.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        self.execute(f"CREATE SCHEMA {SCHEMA}")
        self.execute(f"SET search_path TO {SCHEMA}")
        # Every adapter must pass a parameter list, even an empty one,
        # so psycopg turns `%%` back into `%`.
        self._styles = [
            Style("percentS", ww.PlaceholderStyle.percent_s, self.runner(psycopg.Cursor)),
            # Client-side, psycopg writes -0.0 as a numeric literal,
            # which has no negative zero.
            Style("percentS client-side", ww.PlaceholderStyle.percent_s, self.runner(psycopg.ClientCursor),
                  exact_floats=False),
            Style("dollarNumbered raw", ww.PlaceholderStyle.dollar_numbered, self.runner(psycopg.RawCursor)),
        ]
        # The common corpus also runs with every value untyped, as `pg`
        # sends them, which the casts rendering writes must make work.
        self._corpus_styles = [*self._styles, Style(
            "dollarNumbered raw, untyped", ww.PlaceholderStyle.dollar_numbered,
            self.runner(psycopg.RawCursor, untyped=True))]

    def runner(self, cursor_class, untyped=False):
        dumper = untyped_dumper(self.psycopg) if untyped else None

        def run(r, with_description=False):
            cur = cursor_class(self.conn)
            if dumper:
                for t in (bool, int, float):
                    cur.adapters.register_dumper(t, dumper)
            cur.execute(r.sql, [rt.py_value(p) for p in r.params])
            rows = [tuple(row) for row in cur.fetchall()] if cur.description else []
            return (rows, cur.description) if with_description else rows

        return run

    def close(self) -> None:
        self.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        self.conn.close()

    def describe(self) -> str:
        version = self.execute("SHOW server_version")[0][0]
        return (f"PostgreSQL {version}, psycopg {self.psycopg.__version__}, "
                f"Python {sys.version.split()[0]}, "
                f"standard_conforming_strings {self.setting('standard_conforming_strings')}")

    def setting(self, name: str) -> str:
        return self.execute("SELECT current_setting(%s)", [name])[0][0]

    def execute(self, sql: str, params=()) -> list[tuple]:
        cur = self.conn.execute(sql, list(params) if params else None)
        return [tuple(row) for row in cur.fetchall()] if cur.description else []

    def execute_described(self, sql: str):
        cur = self.conn.execute(sql)
        return [tuple(row) for row in cur.fetchall()], cur.description

    def styles(self) -> list[Style]:
        return self._styles

    def corpus_styles(self) -> list[Style]:
        return self._corpus_styles

    # Text can't hold NUL, even as a parameter.
    def bindable(self, s: str) -> bool:
        return "\x00" not in s and not rt.has_surrogate(s)

    def hole_text(self):
        # Nothing types a parameter alone in `SELECT $1`, so cast it.
        return "CAST(", " AS text)"

    # Longer names are truncated, so two could become one.
    def rejects_name(self, n: str) -> bool:
        return super().rejects_name(n) or len(n.encode("utf-8", "surrogatepass")) > 63

    @contextlib.contextmanager
    def name_table(self, qt: str, qn: str):
        # DDL is transactional, so a rollback cleans up.
        with self.conn.transaction(force_rollback=True):
            self.execute(f"CREATE TABLE {qt} ({qn} text)")
            yield

    def catalogs(self, table: str):
        info_tables = [r[0] for r in self.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [SCHEMA])]
        info_cols = [r[0] for r in self.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", [SCHEMA, table])]
        pg_tables = [r[0] for r in self.execute(
            "SELECT c.relname FROM pg_catalog.pg_class c"
            " JOIN pg_catalog.pg_namespace s ON s.oid = c.relnamespace"
            " WHERE s.nspname = %s AND c.relkind = 'r'", [SCHEMA])]
        pg_cols = [r[0] for r in self.execute(
            "SELECT a.attname FROM pg_catalog.pg_attribute a"
            " JOIN pg_catalog.pg_class c ON c.oid = a.attrelid"
            " JOIN pg_catalog.pg_namespace s ON s.oid = c.relnamespace"
            " WHERE s.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped"
            " ORDER BY a.attnum", [SCHEMA, table])]
        return [("information_schema", info_tables, info_cols), ("pg_catalog", pg_tables, pg_cols)]

    def result_name(self, description) -> str:
        return description[0].name

    def result_names(self, description) -> list[str]:
        return [d.name for d in description]

    def nul_texts(self) -> list[str]:
        return []

    TYPES = {"SqlText": "text", "SqlNull": "text", "SqlInt": "bigint", "SqlFloat": "double precision",
             "SqlBool": "boolean"}
    COLUMNS = {"SqlText": "t", "SqlNull": "t", "SqlInt": "n", "SqlFloat": "f", "SqlBool": "b"}

    def value_exprs(self, v):
        return [("CAST(", f" AS {self.TYPES[type(v).__name__]})")]

    def expected_row(self, v) -> tuple:
        return (rt.py_value(v),)

    values_table = "CREATE TABLE v (i integer PRIMARY KEY, t text, n bigint, f double precision, b boolean)"
    values_select = "SELECT i, t, n, f, b FROM v ORDER BY i"

    def value_column(self, v) -> str:
        return self.COLUMNS[type(v).__name__]

    def table_row(self, v) -> tuple:
        column = self.value_column(v)
        return tuple(rt.py_value(v) if c == column else None for c in "tnfb")

    def nesting_setup(self) -> None:
        self.execute("CREATE TABLE n (a integer, b integer, c integer)")
        self.execute("INSERT INTO n VALUES (1, NULL, 9), (1, 2, 9), (5, 5, 3), (1, NULL, 3)")
        self.execute('CREATE TABLE "n t" ("a""b`c" integer)')
        self.execute('INSERT INTO "n t" VALUES (42)')

    def nesting_teardown(self) -> None:
        self.execute("DROP TABLE n")
        self.execute('DROP TABLE "n t"')

    def nesting_cases(self):
        ww = rt.ww

        def tag(*pieces):
            return rt.template(ww.PostgresTag, *pieces)

        def text(v):
            return tag("CAST(", H(v), " AS text)")

        neg = tag("-1")
        empty = tag("")
        commented = tag("SELECT 1 -- note")
        where = tag("WHERE a = ", H(1), " AND b IS NOT DISTINCT FROM CAST(", H(None), " AS integer)")
        inner = tag("b = ", H(2), " OR c = ", H(3))
        deepest = text("c")
        deeper = tag(H(text("b")), " || ", H(deepest))
        deep = tag(H(text("a")), " || ", H(deeper), " || ", H(text("d")))
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
            (tag("SELECT ", H(7), "/CAST(", H(2.0), " AS double precision)"), [(3.5,)]),
            (tag("SELECT ", H(7), "%", H(4)), [(3,)]),
            (tag("SELECT ", H(text("a")), "||", H(text("b"))), [("ab",)]),
            (tag("SELECT 'x'||", H(text("y")), "||'z'"), [("xyz",)]),
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
            (tag("SELECT ", H(1), " -- what? 'x\n, ", H(2), " /* ? /* $1 */ ' */ AS \"a?\", 0 AS \"b:c\", ",
                 H(3), " AS \"$d\", $$ ? $$ AS e, $x$ $1 $x$ AS f"),
             [(1, 2, 0, 3, " ? ", " $1 ")]),
            (tag("SELECT ", H(1), " IN (", H(1), ", ", H(2), "), ", H(text(None)), " IS NULL"), [(True, True)]),
            (tag("SELECT CASE WHEN ", H(True), " THEN ", H(text("y")), " ELSE ", H(text("n")), " END"), [("y",)]),
            # A carriage return ends a line comment.
            (tag("SELECT 1 -- c\r, ", H(2)), [(1, 2)]),
            # An E string goes on past a doubled quote, and past
            # whitespace and line comments with a line break.
            (tag("SELECT E'a''b\\'c'\n -- x\r\n'd\\'', ", H(3)), [("a'b'cd'", 3)]),
        ]

    def random_comment(self, rng, body: str) -> str:
        r = rng.random()
        # Block comments nest, so each `/*` needs its own `*/`. An
        # unclosed one could be closed by a later literal holding `*/`,
        # shifting everything after it (the Temper tests cover unclosed
        # comments). Spaces keep a body's `/` or `*` from joining a
        # marker, as `a/` before `*/` would make `/*`.
        if r < 0.25:
            a, b = sorted(rng.randint(0, len(body)) for _ in range(2))
            x, y, z = (rt.without(t, "*/", "/*") for t in (body[:a], body[a:b], body[b:]))
            return f"/* {x} /* {y} */ {z} */"
        if r < 0.5:
            return "/* " + rt.without(body, "*/", "/*") + " */"
        # A line feed or a carriage return ends a line comment.
        return "--" + rt.without(body, "\n", "\r") + rng.choice(["\n", "\r", "\r\n"])

    def limits(self) -> None:
        d = self.dialect
        scs = self.setting("standard_conforming_strings")
        if scs != "on":
            rt.fail("limits", f"standard_conforming_strings is {scs}, but the profile assumes on")
        encoding = self.setting("server_encoding")
        if encoding != "UTF8":
            rt.fail("limits", f"server_encoding is {encoding}, not UTF8, so many inputs can't be stored")
        notes = [f"standard_conforming_strings {scs}", f"server_encoding {encoding}"]
        # Names over 63 bytes are truncated, which is why they're
        # rejected; Wherewith must reject them.
        long_name = "x" * 64
        if d.name_problem(long_name) is None or d.name_problem("x" * 63) is not None:
            rt.fail("limits", "the postgres profile doesn't stop at 63 bytes")
        with self.conn.transaction(force_rollback=True):
            self.execute(f'CREATE TABLE "{long_name}" (c text)')
            got = self.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [SCHEMA])
            notes.append(f"a 64-byte name becomes {len(got[0][0])} bytes")
        # NUL can't be in text at all: not in a literal, not bound.
        for label, sql, params in [("chr(0)", "SELECT chr(0)", None), ("a bound NUL", "SELECT %s::text", ["a\x00b"])]:
            try:
                self.conn.execute(sql, params)
                notes.append(f"{label} accepted")
                rt.fail("limits", f"{label} was accepted, though text can't hold NUL")
            except (self.psycopg.Error, ValueError) as err:
                notes.append(f"{label} rejected ({type(err).__name__})")
        # Why common queries cast a value alone in a SELECT list: psycopg
        # sends text untyped, as `pg` sends every value. PostgreSQL 10
        # and later read an untyped value alone as text (older versions
        # can't type it), so a number sent that way comes back as text;
        # the cast gives it its type.
        claim = "[docs/design.md: rendering table, a `$1` with no context]"
        for label, sql, want in [("an untyped value alone", "SELECT %s", "7"),
                                 ("an untyped value cast", "SELECT CAST(%s AS BIGINT)", 7)]:
            try:
                got = self.execute(sql, ["7"])[0][0]
                notes.append(f"{label} gives {got!r}")
                if got != want or type(got) is not type(want):
                    rt.fail("limits", f"{label} gave {got!r}, not {want!r} {claim}")
            except self.psycopg.Error as err:
                notes.append(f"{label} fails ({type(err).__name__})")
                rt.fail("limits", f"{label} failed, not giving {want!r}: {rt.describe(err)} {claim}")
        # Why common queries cast values in the other places decision 8
        # names: sent untyped, each gives something other than the
        # typed value's result, or fails, and with the cast, gives it.
        # What each gives uncast is recorded, as the design describes it.
        from decimal import Decimal  # noqa: PLC0415

        claim = "[docs/design.md: decided 8, and the rendering table's `$1` with no context]"
        for label, uncast, cast, params, want in [
            ("an untyped value compared with values", "SELECT %s < %s",
             "SELECT CAST(%s AS BIGINT) < CAST(%s AS BIGINT)", ["10", "9"], False),
            ("an untyped value beside an integer literal", "SELECT %s + 1",
             "SELECT CAST(%s AS DOUBLE PRECISION) + 1", ["2.5"], 3.5),
            ("an untyped value in a list of values", "SELECT %s IN (%s)",
             "SELECT CAST(%s AS BIGINT) IN (CAST(%s AS DOUBLE PRECISION))", ["1", "1.0"], True),
            ("an untyped value between values", "SELECT %s BETWEEN %s AND %s",
             "SELECT CAST(%s AS BIGINT) BETWEEN CAST(%s AS BIGINT) AND CAST(%s AS BIGINT)", ["5", "4", "10"], True),
            ("an untyped value after -", "SELECT -%s", "SELECT -CAST(%s AS BIGINT)", ["3"], -3),
            ("an untyped value after +", "SELECT +%s", "SELECT +CAST(%s AS BIGINT)", ["3"], 3),
            ("an untyped value before IS NULL", "SELECT %s IS NULL", "SELECT CAST(%s AS TEXT) IS NULL", [None], True),
            ("an untyped value as a CASE subject", "SELECT CASE %s WHEN 1 THEN 'a' END",
             "SELECT CASE CAST(%s AS BIGINT) WHEN 1 THEN 'a' END", ["1"], "a"),
            ("an untyped value in ABS", "SELECT abs(%s)", "SELECT abs(CAST(%s AS BIGINT))", ["-3"], 3),
            ("an untyped value in MIN", "SELECT min(%s)", "SELECT min(CAST(%s AS BIGINT))", ["10"], 10),
            ("an untyped value in SUM", "SELECT sum(%s)", "SELECT sum(CAST(%s AS BIGINT))", ["2"], Decimal(2)),
            ("an untyped value in COUNT", "SELECT count(%s)", "SELECT count(CAST(%s AS BIGINT))", ["1"], 1),
            ("a BIGINT start in SUBSTR", "SELECT substr('abc', CAST(%s AS BIGINT))",
             "SELECT substr('abc', CAST(CAST(%s AS BIGINT) AS INTEGER))", ["2"], "bc"),
        ]:
            try:
                got = self.execute(uncast, params)[0][0]
                notes.append(f"{label} gives {got!r}")
                if got == want and type(got) is type(want) and not label.endswith("COUNT"):
                    rt.fail("limits", f"{label} gave {got!r}, as with the cast {claim}")
            except self.psycopg.Error as err:
                notes.append(f"{label} fails ({type(err).__name__})")
            try:
                got = self.execute(cast, params)[0][0]
                if got != want or type(got) is not type(want):
                    rt.fail("limits", f"{label}, cast, gave {got!r}, not {want!r} {claim}")
            except self.psycopg.Error as err:
                rt.fail("limits", f"{label}, cast, failed, not giving {want!r}: {rt.describe(err)} {claim}")
        rt.count("limits checked", len(notes))
        print("  limits: " + "; ".join(notes))


def main() -> int:
    parser = rt.arguments(__doc__, ("PostgreSQL", "WHEREWITH_PG_HOST", "WHEREWITH_PG_PORT", 5432))
    args = parser.parse_args()
    if (status := rt.start(args, "PostgreSQL")) is not None:
        return status
    started = time.perf_counter()
    engine = Postgres(args.host, args.port)
    try:
        rt.run_all(engine, args)
    finally:
        engine.close()
    return rt.finish(args, started)


if __name__ == "__main__":
    sys.exit(main())
