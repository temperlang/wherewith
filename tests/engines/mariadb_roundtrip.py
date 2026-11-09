"""Round-trip Wherewith's MySQL output through a real MariaDB server.

    temper build -b py
    uv run tests/engines/mariadb_roundtrip.py [--out temper.out/py] [-v]

Uses PyMySQL and the Python library Temper generates in
`temper.out/py`, with the checks in `roundtrip.py`, in four SQL modes:
the server's default, then with `NO_BACKSLASH_ESCAPES`, `ANSI_QUOTES`,
and both, each with the matching profile (`mysqlNoBackslashEscapes`
where backslashes don't escape, else `mysql`). In each, for many
hostile inputs: quoted strings read back exactly, quoted names make a
table and column that read back exactly from `information_schema`,
values bound with `%s` come back equal with the expected type, and
nested queries, operators, and random templates give the expected rows.
Inputs Wherewith rejects (lone surrogates in strings, and NUL under
`NO_BACKSLASH_ESCAPES`; empty names, NUL, lone surrogates, names over
64 characters or above U+FFFF, names ending in whitespace, and names
starting with `#mysql50#`) must be rejected.

The default `mysql` profile is also checked in every mode, as the
design claims it's safe in all: under `NO_BACKSLASH_ESCAPES` each
string must still end where Wherewith ends it, reading back with its
escapes as plain text.

The server comes from these variables, with defaults matching CI:
WHEREWITH_MARIADB_HOST (127.0.0.1), WHEREWITH_MARIADB_PORT (3306),
WHEREWITH_MARIADB_USER (root), WHEREWITH_MARIADB_PASSWORD (wherewith, a
throwaway for the CI service container), and WHEREWITH_MARIADB_DATABASE
(wherewith), which should be empty. With no server reachable, it skips,
exiting 0, unless `--require-server` is given.

Exits 1, printing a minimal repro for each, if the engine disagrees.
"""

import os
import sys
import time

import roundtrip as rt
from roundtrip import H, Style

CHARSET = "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"


class Mariadb(rt.Engine):
    # MariaDB's DOUBLE has no NaN or infinities (PyMySQL refuses them),
    # and its documented range leaves out subnormals, so those aren't
    # bound; the sign of a zero isn't checked.
    exact_floats = False
    table_options = f" {CHARSET}"
    corpus_name = "mariadb"
    corpus_types = {"int": "BIGINT", "text": "VARCHAR(100)", "float": "DOUBLE", "bool": "BOOLEAN"}
    # The server's default collation, which the corpus documents.
    corpus_options = " DEFAULT CHARSET=utf8mb4"

    def __init__(self, conn, mode: str, extra: list[str], dialect) -> None:
        self.conn = conn
        self.mode = mode
        self.nbe = "NO_BACKSLASH_ESCAPES" in extra
        self.dialect = dialect
        self.tag_class = rt.ww.MysqlTag
        modes = [m for m in mode.split(",") if m] + extra
        self.execute("SET SESSION sql_mode = %s", [",".join(modes)])
        self.sql_mode = self.execute("SELECT @@SESSION.sql_mode")[0][0]
        # PyMySQL fills in parameters on the client, with Python's `%`
        # formatting, so every adapter must pass a parameter list, even
        # an empty one, to turn `%%` back into `%`.
        self._styles = [Style("percentS", rt.ww.PlaceholderStyle.percent_s, self.run)]

    def run(self, r, with_description=False):
        with self.conn.cursor() as cur:
            cur.execute(r.sql, [rt.py_value(p) for p in r.params])
            rows = [tuple(row) for row in cur.fetchall()] if cur.description else []
            return (rows, cur.description) if with_description else rows

    def describe(self) -> str:
        import pymysql  # noqa: PLC0415

        version = self.execute("SELECT VERSION()")[0][0]
        return (f"MariaDB {version}, PyMySQL {pymysql.VERSION_STRING}, Python {sys.version.split()[0]}, "
                f"profile {self.dialect.name}, sql_mode {self.sql_mode or '(empty)'}")

    def execute(self, sql: str, params=()) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(sql, list(params) if params else None)
            return [tuple(row) for row in cur.fetchall()] if cur.description else []

    def styles(self) -> list[Style]:
        return self._styles

    def escapes(self) -> bool:
        """Whether the profile escapes with backslashes."""
        return self.dialect.name == "mysql"

    def rejects_string(self, s: str) -> bool:
        return rt.has_surrogate(s) or ("\x00" in s and not self.escapes())

    def reads_as(self, s: str, q: str) -> str:
        # Under NO_BACKSLASH_ESCAPES only '' is special, so the default
        # profile's escapes read back as plain text.
        return q[1:-1].replace("''", "'") if self.nbe else s

    # Under NO_BACKSLASH_ESCAPES, PyMySQL only doubles quotes, leaving a
    # NUL as a raw byte in the SQL, so those aren't bound there.
    def bindable(self, s: str) -> bool:
        return not rt.has_surrogate(s) and not (self.nbe and "\x00" in s)

    # Templates refuse a backslash before a quote or backslash in a
    # string, which NO_BACKSLASH_ESCAPES reads differently.
    def literal_in_template(self, q: str) -> bool:
        return "\\\\" not in q and "\\'" not in q

    def nul_texts(self) -> list[str]:
        return [] if self.nbe else super().nul_texts()

    # The server rejects names ending in any of its space characters
    # (my_isspace), and reads table names starting with #mysql50# as
    # file names.
    def rejects_name(self, n: str) -> bool:
        return (super().rejects_name(n) or len(n) > 64 or any(ord(c) > 0xFFFF for c in n)
                or n[-1:] in tuple(" \t\n\v\f\r") or n.startswith("#mysql50#"))

    # A table is a file, its name encoded with up to 5 bytes for each
    # character other than ASCII letters, digits, and `_`, and a file
    # name can't be over 255 bytes. Names that might be too long test as
    # a column only.
    def table_for(self, n: str) -> str:
        size = sum(1 if c.isascii() and (c.isalnum() or c == "_") else 5 for c in n)
        return "t" if size > 240 else n

    def catalogs(self, table: str):
        tables = [r[0] for r in self.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")]
        cols = [r[0] for r in self.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION", [table])]
        return [("information_schema", tables, cols)]

    def floats(self) -> list[float]:
        return [0.0, -0.0, 1.5, -2.25, 1e308, -1e308, 2.2250738585072014e-308, 0.1]

    def value_exprs(self, v):
        if isinstance(v, rt.ww.SqlInt):
            # A literal below -2**63 + 1 would otherwise be DECIMAL.
            return [("CAST(", " AS SIGNED)")]
        return [("", "")]

    def expected_row(self, v) -> tuple:
        # Booleans are TINYINT(1): 1 and 0.
        value = rt.py_value(v)
        return (int(value) if isinstance(value, bool) else value,)

    values_table = f"CREATE TABLE v (i INT PRIMARY KEY, t LONGTEXT, n BIGINT, f DOUBLE, b BOOLEAN) {CHARSET}"
    values_select = "SELECT i, t, n, f, b FROM v ORDER BY i"
    COLUMNS = {"SqlText": "t", "SqlNull": "t", "SqlInt": "n", "SqlFloat": "f", "SqlBool": "b"}

    def value_column(self, v) -> str:
        return self.COLUMNS[type(v).__name__]

    def table_row(self, v) -> tuple:
        column = self.value_column(v)
        return tuple(self.expected_row(v)[0] if c == column else None for c in "tnfb")

    def nesting_setup(self) -> None:
        self.execute(f"CREATE TABLE n (a INT, b INT, c INT) {CHARSET}")
        self.execute("INSERT INTO n VALUES (1, NULL, 9), (1, 2, 9), (5, 5, 3), (1, NULL, 3)")
        self.execute(f"CREATE TABLE `n t` (`a\"b``c` INT) {CHARSET}")
        self.execute("INSERT INTO `n t` VALUES (42)")

    def nesting_teardown(self) -> None:
        self.execute("DROP TABLE n")
        self.execute("DROP TABLE `n t`")

    def nesting_cases(self):
        ww = rt.ww

        def tag(*pieces):
            return rt.template(ww.MysqlTag, *pieces)

        neg = tag("-1")
        empty = tag("")
        commented = tag("SELECT 1 -- note")
        where = tag("WHERE a = ", H(1), " AND b <=> ", H(None))
        inner = tag("b = ", H(2), " OR c = ", H(3))
        deepest = tag(H("c"))
        deeper = tag("CONCAT(", H("b"), ", ", H(deepest), ")")
        deep = tag("CONCAT(", H("a"), ", ", H(deeper), ", ", H("d"), ")")
        t = ww.Identifier.named("n t")
        c = ww.Identifier.named("a\"b`c")
        return [
            (tag("SELECT 5-", H(-1)), [(6,)]),
            (tag("SELECT -", H(-1)), [(1,)]),
            (tag("SELECT - ", H(-1), "-", H(-1)), [(2,)]),
            (tag("SELECT 2*-", H(3)), [(-6,)]),
            (tag("SELECT 5-", H(neg)), [(6,)]),
            (tag("SELECT ", H(neg), "-1"), [(-2,)]),
            # The empty query keeps `1-` and `-1` apart.
            (tag("SELECT 1-", H(empty), "-1"), [(2,)]),
            (tag("SELECT ", H(1), "+", H(2), "*", H(3)), [(7,)]),
            (tag("SELECT ", H(7), "/", H(2.0)), [(3.5,)]),
            (tag("SELECT ", H(7), "%", H(4)), [(3,)]),
            (tag("SELECT CONCAT(", H("a"), ",", H("b"), ")"), [("ab",)]),
            (tag("SELECT CONCAT('x',", H("y"), ",'z')"), [("xyz",)]),
            (tag("SELECT ", H(1), "<", H(2), ", ", H(2), "<=", H(2), ", ", H(1), "<>", H(1)), [(1, 1, 0)]),
            (tag("SELECT ", H(6), "&", H(3), ", ", H(6), "|", H(3), ", ", H(1), "<<", H(4), ", ~", H(0)),
             [(2, 7, 16, 2**64 - 1)]),
            (tag("SELECT ", H(deep), ", ", H(deep)), [("abcd", "abcd")]),
            (tag(H(commented), " UNION ALL SELECT ", H(2)), [(1,), (2,)]),
            (tag("SELECT a, b, c FROM n ", H(where), " ORDER BY c LIMIT ", H(10)), [(1, None, 3), (1, None, 9)]),
            (tag("SELECT count(*) FROM n WHERE a = ", H(1), " AND (", H(inner), ")"), [(2,)]),
            (tag("SELECT ", H(c), " FROM ", H(t)), [(42,)]),
            (tag("SELECT ", H(t), ".", H(c), " FROM ", H(t)), [(42,)]),
            (tag("SELECT x.", H(c), " FROM ", H(t), " AS x"), [(42,)]),
            (tag("SELECT (SELECT ", H(c), " FROM ", H(t), " WHERE ", H(c), " = ", H(42), ") + ", H(1)), [(43,)]),
            (tag("SELECT ", H(1), " -- what? 'x\n, ", H(2), " /* ? ' */ AS `a?`, 0 AS `b:c`, ", H(3),
                 " # $1 \"\n AS `$d`, 'it''s' AS e"),
             [(1, 2, 0, 3, "it's")]),
            (tag("SELECT ", H(1), " IN (", H(1), ", ", H(2), "), ", H(None), " IS NULL"), [(1, 1)]),
            (tag("SELECT CASE WHEN ", H(True), " THEN ", H("y"), " ELSE ", H("n"), " END"), [("y",)]),
            # `--` before DEL starts a comment, and only a line feed
            # ends one, not a carriage return.
            (tag("SELECT 5--\x7f x\n, ", H(1)), [(5, 1)]),
            (tag("SELECT 1 # c\r, 2\n, ", H(3)), [(1, 3)]),
        ]

    def random_comment(self, rng, body: str) -> str:
        # Raw NUL bytes in SQL text are another question; the default
        # profile writes them as \0 in strings.
        body = body.replace("\x00", "")
        r = rng.random()
        # The space after `/*` keeps it from being an executable comment.
        if r < 0.4:
            return "/* " + rt.without(body, "*/") + "*/"
        # Only a line feed ends a line comment.
        if r < 0.7:
            return "-- " + rt.without(body, "\n") + "\n"
        return "#" + rt.without(body, "\n") + "\n"

    def limits(self) -> None:
        notes = []
        for label, name, wherewith_rejects in [
            ("64 characters", "x" * 64, False),
            ("65 characters", "x" * 65, True),
            ("above U+FFFF", "\U0001F600", True),
            ("a trailing space", "a ", True),
            ("a trailing tab", "a\t", True),
            ("a trailing line feed", "a\n", True),
            ("a trailing vertical tab", "a\v", True),
            ("a trailing form feed", "a\f", True),
            ("a trailing carriage return", "a\r", True),
            ("a trailing U+00A0", "a\xa0", False),
        ]:
            if (self.dialect.name_problem(name) is not None) != wherewith_rejects:
                rt.fail("limits", f"the profile {'accepts' if wherewith_rejects else 'rejects'} a name with {label}")
            quoted = "`" + name.replace("`", "``") + "`"
            try:
                self.execute(f"CREATE TABLE limits_t ({quoted} INT)")
                self.execute("DROP TABLE limits_t")
                notes.append(f"a column with {label} accepted")
            except Exception as err:  # noqa: BLE001
                notes.append(f"a column with {label} rejected ({err.args[0] if err.args else err!r})")
        # A table named with the #mysql50# prefix names a file.
        try:
            self.execute("CREATE TABLE `#mysql50#limits_u` (c INT)")
            got = self.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")
            self.execute("DROP TABLE `#mysql50#limits_u`")
            notes.append(f"a #mysql50# table accepted, listed as {[r[0] for r in got]}")
        except Exception as err:  # noqa: BLE001
            notes.append(f"a #mysql50# table rejected ({err.args[0] if err.args else err!r})")
        rt.count("limits checked", len(notes))
        print("  limits: " + "; ".join(notes))


def main() -> int:
    parser = rt.arguments(__doc__, ("MariaDB", "WHEREWITH_MARIADB_HOST", "WHEREWITH_MARIADB_PORT", 3306))
    args = parser.parse_args()
    if (status := rt.start(args, "MariaDB")) is not None:
        return status
    import pymysql  # noqa: PLC0415

    env = os.environ.get
    conn = pymysql.connect(
        host=args.host, port=args.port, user=env("WHEREWITH_MARIADB_USER", "root"),
        password=env("WHEREWITH_MARIADB_PASSWORD", "wherewith"),
        database=env("WHEREWITH_MARIADB_DATABASE", "wherewith"),
        charset="utf8mb4", autocommit=True,
    )
    started = time.perf_counter()
    ww = rt.ww
    strings = rt.hostile_strings(args.seed, args.fuzz)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT @@SESSION.sql_mode")
            default_mode = cur.fetchone()[0]
        nbe = ["NO_BACKSLASH_ESCAPES"]
        aq = ["ANSI_QUOTES"]
        for extra in [[], nbe, aq, nbe + aq]:
            label = "+".join(extra) or "default"
            profile = ww.Dialect.mysql_no_backslash_escapes if extra[:1] == nbe else ww.Dialect.mysql
            e = Mariadb(conn, default_mode, extra, profile)
            rt.run_all(e, args, f"{label}: ", strings)
            if profile is not ww.Dialect.mysql:
                # The default profile must be safe here too.
                e = Mariadb(conn, default_mode, extra, ww.Dialect.mysql)
                t = time.perf_counter()
                before = len(rt.failures)
                rt.check_strings(e, strings, "strings with the mysql profile")
                print(f"  {label}: strings with the mysql profile: {len(rt.failures) - before} failures, "
                      f"{time.perf_counter() - t:.1f} s")
    finally:
        conn.close()
    return rt.finish(args, started)


if __name__ == "__main__":
    sys.exit(main())
