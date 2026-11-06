# /// script
# requires-python = ">=3.11"
# ///
"""Round-trip Wherewith's SQLite output through the real SQLite engine.

    temper build -b py
    uv run tests/engines/sqlite_roundtrip.py [--out temper.out/py] [-v]

Uses only Python's standard library: `sqlite3` for the engine, and the
Python library Temper generates in `temper.out/py`. Checks, for many
hostile inputs (fixed cases, every ASCII control character, quotes,
comment starts, non-BMP, combining marks, very long text, and seeded
random fuzz):

1. Strings: `SELECT <quoteString(s)>` gives back exactly `s`, and inputs
   Wherewith rejects (NUL and lone surrogates) are rejected.
2. Names: a table and column made with `quoteName(n)` read back exactly
   from `sqlite_schema` and `pragma_table_info`, and work for an insert
   and a select.
3. Parameters: queries from the builder and the `sqlite` tag, rendered
   in each placeholder style Python's `sqlite3` takes, bind values that
   come back equal with the type SQLite stores.
4. Nested queries, holes beside operators, and random templates mixing
   holes with quoted literals, names, and comments give the expected
   rows.

Exits 1, printing a minimal repro for each, if the engine disagrees.
"""

import argparse
import math
import random
import sqlite3
import struct
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Set by load_wherewith.
ww = None

failures: list[str] = []
counts: dict[str, int] = {}


def load_wherewith(out: Path) -> None:
    global ww
    for sub in ("temper-core", "std", "wherewith"):
        sys.path.insert(0, str(out / sub))
    import wherewith  # noqa: PLC0415

    ww = wherewith


def count(kind: str, n: int = 1) -> None:
    counts[kind] = counts.get(kind, 0) + n


def fail(kind: str, message: str) -> None:
    failures.append(f"[{kind}] {message}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    # A "..." that names no column reads as a string unless DQS is off,
    # which would hide a misquoted name. Python 3.12 can turn it off.
    if hasattr(conn, "setconfig"):
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DDL, False)
    return conn


def short(s: str, n: int = 60) -> str:
    r = repr(s)
    return r if len(r) <= n else f"{r[:n]}... ({len(s)} chars)"


# Inputs


def hostile_strings(seed: int, fuzz: int) -> list[str]:
    """Hostile text: the Temper tests' cases, then generated ones."""
    cases = [
        # From src/*-tests.temper.md.
        "", "plain", "it's", "'", "x'; DROP TABLE t; --", "\"", "`", "-- x",
        "/* x */", "# x", "a\nb", "a\r\nb", "\t", "$$", "?", "%s", ":x",
        "\U0001F600", "e\u0301", "\ufeff", "\u2028", "\uffff", "\U0010ffff",
        "\\", "\x00", "/*", "\"; DROP TABLE t; --", "Robert'); DROP TABLE students; --",
        "weird \"col\"", "my schema", "a\"b`c", "100%", "zq'\"`\\%?$1@p1:p1-- /*",
        "a.b", "a\\", "a'\\" * 3, "n\"" * 5, "t ", "x" * 65,
        # More by hand.
        "''", "'''", "\\'", "\\''", "'\\", "\\\\'", "a''b", "a'' OR ''='",
        "*/", "/* /* */", "--", "-- \n", "--\r", ";", "; SELECT 1", "';--",
        "\x1a", "\\0", "\\Z", "\\x27", "\\u0027", "&#39;", "%27", "\r", "\n\n",
        "[", "]", "[a]", "`a`", "\"\"", "\"a\"\"", "$1", "?1", "@a", "$a", ":a",
        " ", "  ", " a ", "\u00a0", "\u3000", "\u200b", "\u200d", "\u202e",
        "\x7f", "\x80", "\x85", "\x9f", "\u00e9", "e\u0301\u0302\u0303",
        "\U0001F468\u200d\U0001F469\u200d\U0001F467", "\U0001D11E", "\U000E0001",
        "\ufffe", "\ufffd", "\U0010fffe",
    ]
    # Every ASCII control character, alone and between text.
    for c in [*range(0x20), 0x7F]:
        ch = chr(c)
        cases += [ch, f"a{ch}b", f"'{ch}'", f"{ch}'{ch}"]
    # Quotes of every kind, alone, doubled, and around text.
    quotes = "'\"`\u00b4\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u2032\u2033\u02bc\uff07\uff02\uff40\u02b9\u02ba"
    for q in quotes:
        cases += [q, q * 2, f"{q}a{q}", f"a{q}{q}b", f"\\{q}", f"{q}\\"]
    # Combining marks: on a letter, on a quote, and alone.
    for m in ("\u0300", "\u0301", "\u0327", "\u0338", "\u20dd", "\ufe0f"):
        cases += [m, f"a{m}", f"'{m}", f"{m}'", f"\"{m}"]
    # Lone surrogates, which Python strings can hold.
    cases += ["\ud800", "a\udfffb", "\udbff\ud800"]
    # Very long.
    cases += ["a'\\" * 50_000, "'" * 100_000, "x" * 1_000_000, "\U0001F600" * 10_000]
    # Random fuzz, from a pool weighted toward trouble.
    rng = random.Random(seed)
    pool = list("'\"`\\;-/*?:@$%#[]() \t\r\n\x1a\x7f") + [
        "--", "/*", "*/", "''", "\u0301", "\U0001F600", "\u2028", "\ufeff",
    ]
    for _ in range(fuzz):
        n = rng.randint(1, 40)
        parts = []
        for _ in range(n):
            r = rng.random()
            if r < 0.01:
                # Rejected in SQL text, so rare, to keep most usable.
                parts.append(rng.choice(["\x00", "\ud800", "\udfff"]))
            elif r < 0.6:
                parts.append(rng.choice(pool))
            elif r < 0.8:
                parts.append(chr(rng.randint(0x20, 0x7E)))
            else:
                # Any code point, surrogates included.
                parts.append(chr(rng.randint(0, 0x10FFFF)))
        cases.append("".join(parts))
    return cases


def sqlite_rejects_string(s: str) -> bool:
    return "\x00" in s or any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def sqlite_rejects_name(s: str) -> bool:
    return s == "" or sqlite_rejects_string(s)


# 1. Strings


def check_strings(conn: sqlite3.Connection, inputs: list[str]) -> None:
    d = ww.Dialect.sqlite
    for s in inputs:
        count("strings")
        problem = d.string_problem(s)
        try:
            q = d.quote_string(s)
        except Exception:  # noqa: BLE001 (Temper's bubble)
            q = None
        expect_reject = sqlite_rejects_string(s)
        if (q is None) != (problem is not None):
            fail("strings", f"quoteString and stringProblem disagree for {short(s)}")
        if expect_reject:
            if q is not None:
                fail("strings", f"accepted {short(s)} as {short(q)}")
            else:
                count("strings rejected")
            continue
        if q is None:
            fail("strings", f"rejected {short(s)}: {problem}")
            continue
        try:
            got = conn.execute(f"SELECT {q}, typeof({q})").fetchone()
        except sqlite3.Error as e:
            fail("strings", f"SELECT {short(q)} failed: {e}")
            continue
        if got != (s, "text"):
            fail("strings", f"SELECT {short(q)} gave {short(str(got[0]))}, not {short(s)}")
        # The builder's lexer must agree with the engine on where the
        # literal ends, so a hole after it is still code.
        b = ww.QueryBuilder(d)
        b.append_safe(f"SELECT {q} = ")
        b.append_string(s)
        b.append_safe(f", {q}")
        try:
            r = b.build().render(d, ww.PlaceholderStyle.question)
            got = conn.execute(r.sql, bind_question(r.params)).fetchone()
            if got != (1, s):
                fail("strings", f"builder with {short(q)} gave {got!r}")
        except Exception as e:  # noqa: BLE001
            fail("strings", f"builder with {short(q)} failed: {e!r}")


# 2. Names


def check_names(conn: sqlite3.Connection, inputs: list[str]) -> None:
    d = ww.Dialect.sqlite
    style = ww.PlaceholderStyle.question
    for n in inputs:
        count("names")
        try:
            qn = d.quote_name(n)
        except Exception:  # noqa: BLE001
            qn = None
        if sqlite_rejects_name(n):
            if qn is not None:
                fail("names", f"accepted {short(n)} as {short(qn)}")
            else:
                count("names rejected")
            continue
        if qn is None:
            fail("names", f"rejected {short(n)}: {d.name_problem(n)}")
            continue
        # SQLite reserves table names starting with sqlite_, whatever
        # the quoting, so those test as a column only.
        table = f"t_{n}" if n.lower().startswith("sqlite_") else n
        qt = qn if table == n else d.quote_name(table)
        try:
            conn.execute(f"CREATE TABLE {qt} ({qn} TEXT)")
        except sqlite3.Error as e:
            fail("names", f"CREATE TABLE {short(qt)} ({short(qn)} TEXT) failed: {e}")
            continue
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")]
            if tables != [table]:
                fail("names", f"sqlite_schema has {[short(t) for t in tables]}, not {short(table)}")
            cols = [r[0] for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))]
            if cols != [n]:
                fail("names", f"table_info for {short(table)} has {[short(c) for c in cols]}, not {short(n)}")
            # Insert and select through the names, as a QueryName where
            # Identifier takes the name, or else as checked text. The
            # longest skip the builder, whose lexer is slow in Python.
            value = f"v:{n[:20]}"
            if len(n) > 100_000:
                ins_sql, sel_sql = (
                    f"INSERT INTO {qt} ({qn}) VALUES (?)",
                    f"SELECT {qn}, {qt}.{qn} FROM {qt} WHERE {qn} = ?",
                )
                params = (value,)
            else:
                names = {"T": name_piece(table, qt), "C": name_piece(n, qn)}
                ins = names_query(d, names, ["INSERT INTO ", "T", " (", "C", ") VALUES (", "V", ")"], value)
                sel = names_query(d, names, ["SELECT ", "C", ", ", "T", ".", "C", " FROM ", "T", " WHERE ", "C", " = ", "V"], value)
                r = ins.render(d, style)
                ins_sql = r.sql
                r = sel.render(d, style)
                sel_sql = r.sql
                params = bind_question(r.params)
            conn.execute(ins_sql, params)
            cur = conn.execute(sel_sql, params)
            rows = cur.fetchall()
            if rows != [(value, value)]:
                fail("names", f"select through {short(n)} gave {rows!r}")
            if cur.description[0][0] != n:
                fail("names", f"result column for {short(n)} is {short(cur.description[0][0])}")
        except Exception as e:  # noqa: BLE001
            fail("names", f"using {short(n)} failed: {e!r}")
        finally:
            conn.execute(f"DROP TABLE {qt}")


def name_piece(name: str, quoted: str):
    """An Identifier where it takes the name, or else the quoted text."""
    return ww.Identifier.named(name) if ww.identifier_problem(name) is None else quoted


def names_query(d, names: dict, pieces: list[str], value: str):
    """Builds pieces, with T and C from names, and V the value."""
    b = ww.QueryBuilder(d)
    for p in pieces:
        if p == "V":
            b.append_string(value)
        elif p in names:
            name = names[p]
            if isinstance(name, str):
                b.append_safe(name)
            else:
                b.append_identifier(name)
        else:
            b.append_safe(p)
    return b.build()


# 3. Parameters


def py_value(v):
    if isinstance(v, ww.SqlText | ww.SqlInt | ww.SqlFloat | ww.SqlBool):
        return v.value
    if isinstance(v, ww.SqlNull):
        return None
    raise TypeError(v)


def bind_question(params) -> tuple:
    return tuple(py_value(p) for p in params)


# Each style Python's sqlite3 takes, with how it binds: `?` by
# position, and names by key without their first character, so `$1`
# (SQLite's `$` names) binds too. `%s` isn't SQLite syntax.
def styles():
    return [
        ("question", ww.PlaceholderStyle.question, bind_question),
        ("colonNamed", ww.PlaceholderStyle.colon_named, lambda ps: {f"p{i}": py_value(p) for i, p in enumerate(ps, 1)}),
        ("atNamed", ww.PlaceholderStyle.at_named, lambda ps: {f"p{i}": py_value(p) for i, p in enumerate(ps, 1)}),
        ("dollarNumbered", ww.PlaceholderStyle.dollar_numbered, lambda ps: {str(i): py_value(p) for i, p in enumerate(ps, 1)}),
    ]


def expected(v):
    """What SQLite gives back for a value, and its typeof."""
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


def same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return struct.pack("<d", a) == struct.pack("<d", b)
    return type(a) is type(b) and a == b


def param_values(strings: list[str]):
    ints = [0, 1, -1, 7, 2**31 - 1, -(2**31), 2**53 + 1, 2**63 - 1, -(2**63)]
    floats = [0.0, -0.0, 1.5, -2.25, 1e308, -1e-308, 5e-324, math.inf, -math.inf, math.nan, 0.1]
    values = [ww.SqlText(s) for s in strings if not sqlite_rejects_string(s)]
    # NUL can't be written in SQLite's SQL text, but binds fine.
    values += [ww.SqlText("a\x00b"), ww.SqlText("\x00")]
    values += [ww.SqlInt(i) for i in ints] + [ww.SqlFloat(f) for f in floats]
    values += [ww.SqlBool(True), ww.SqlBool(False), ww.SqlNull()]
    return values


def append_typed(b, v) -> None:
    """Appends with the builder's typed overloads, as a tag would."""
    if isinstance(v, ww.SqlText):
        b.append_string(v.value)
    elif isinstance(v, ww.SqlInt):
        b.append_int64(v.value)
    elif isinstance(v, ww.SqlFloat):
        b.append_float64(v.value)
    elif isinstance(v, ww.SqlBool):
        b.append_boolean(v.value)
    else:
        b.append_string(None)


def check_params(conn: sqlite3.Connection, strings: list[str]) -> None:
    d = ww.Dialect.sqlite
    values = param_values(strings)
    conn.execute("CREATE TABLE v (i INTEGER, x)")
    try:
        for name, style, bind in styles():
            # One value per query, through the tag, the builder, and a
            # table with no column affinity.
            for v in values:
                count("params")
                tag = ww.SqliteTag()
                tag.append_safe("SELECT ")
                append_typed(tag, v)
                tag.append_safe(", typeof(")
                tag.append_value(v)
                tag.append_safe(")")
                q = tag.accumulated
                want = expected(v)
                try:
                    r = q.render(d, style)
                    got = conn.execute(r.sql, bind(r.params)).fetchone()
                    if not (same(got[0], want[0]) and got[1] == want[1]):
                        fail("params", f"{name}: {short(str(py_value(v)))} came back as {got!r}, not {want!r}")
                except Exception as e:  # noqa: BLE001
                    fail("params", f"{name}: {short(str(py_value(v)))} failed: {e!r}")
            # Many values in one query, numbered straight through.
            for start in range(0, len(values), 200):
                chunk = values[start : start + 200]
                count("params batches")
                b = ww.QueryBuilder(d)
                b.append_safe("SELECT ")
                for i, v in enumerate(chunk):
                    if i:
                        b.append_safe(", ")
                    b.append_value(v)
                r = b.build().render(d, style)
                got = conn.execute(r.sql, bind(r.params)).fetchone()
                for v, g in zip(chunk, got, strict=True):
                    if not same(g, expected(v)[0]):
                        fail("params", f"{name} batch: {short(str(py_value(v)))} came back as {short(str(g))}")
            # Through a table.
            conn.execute("DELETE FROM v")
            for i, v in enumerate(values):
                b = ww.QueryBuilder(d)
                b.append_safe("INSERT INTO v (i, x) VALUES (")
                b.append_int(i)
                b.append_safe(", ")
                b.append_value(v)
                b.append_safe(")")
                r = b.build().render(d, style)
                conn.execute(r.sql, bind(r.params))
            rows = conn.execute("SELECT i, x, typeof(x) FROM v ORDER BY i").fetchall()
            count("params table rows", len(rows))
            for (i, x, t), v in zip(rows, values, strict=True):
                want = expected(v)
                if not (same(x, want[0]) and t == want[1]):
                    fail("params", f"{name} table row {i}: {short(str(py_value(v)))} came back as {(x, t)!r}")
    finally:
        conn.execute("DROP TABLE v")


# 4. Nested queries, holes beside operators, and random templates


def tag(*pieces):
    """A sqlite"…" template: str pieces are text, anything else a hole."""
    t = ww.SqliteTag()
    for p in pieces:
        if isinstance(p, str):
            t.append_safe(p)
        elif isinstance(p, Hole):
            p.append(t)
        else:
            raise TypeError(p)
    return t.accumulated


class Hole:
    def __init__(self, v):
        self.v = v

    def append(self, t) -> None:
        v = self.v
        if isinstance(v, bool):
            t.append_boolean(v)
        elif isinstance(v, int):
            t.append_int64(v)
        elif isinstance(v, float):
            t.append_float64(v)
        elif isinstance(v, str) or v is None:
            t.append_string(v)
        elif isinstance(v, ww.Identifier):
            t.append_identifier(v)
        elif isinstance(v, ww.Query):
            t.append_query(v)
        else:
            t.append_value(v)


def H(v):  # noqa: N802
    return Hole(v)


def check_nesting(conn: sqlite3.Connection) -> None:
    d = ww.Dialect.sqlite
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
    conn.execute('CREATE TABLE n (a, b, c)')
    conn.executemany("INSERT INTO n VALUES (?, ?, ?)", [(1, None, 9), (1, 2, 9), (5, 5, 3), (1, None, 3)])
    conn.execute('CREATE TABLE "n t" ("a""b`c")')
    conn.execute('INSERT INTO "n t" VALUES (42)')
    cases = [
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
        (tag("SELECT ", H(1), " -- what? 'x\n, ", H(2), " /* ? */ AS [a?], 0 AS `b:c`, ", H(3), " AS \"$d\""), [(1, 2, 0, 3)]),
        (tag("SELECT ", H(1), " IN (", H(1), ", ", H(2), "), ", H(None), " IS NULL"), [(1, 1)]),
        (tag("SELECT CASE WHEN ", H(True), " THEN ", H("y"), " ELSE ", H("n"), " END"), [("y",)]),
    ]
    try:
        for q, want in cases:
            for name, style, bind in styles():
                count("nesting")
                try:
                    r = q.render(d, style)
                    got = conn.execute(r.sql, bind(r.params)).fetchall()
                    if got != want:
                        fail("nesting", f"{name}: {r.sql!r} gave {got!r}, not {want!r}")
                except Exception as e:  # noqa: BLE001
                    sql = q.render(d, ww.PlaceholderStyle.question).sql
                    marker = {"colonNamed": ":", "atNamed": "@"}.get(name)
                    if marker and marker in sql:
                        # Named styles refuse text holding their marker.
                        count("nesting refused by design")
                    else:
                        fail("nesting", f"{name}: {sql!r} failed: {e!r}")
    finally:
        conn.execute("DROP TABLE n")
        conn.execute('DROP TABLE "n t"')


def check_random_templates(conn: sqlite3.Connection, strings: list[str], seed: int, n: int) -> None:
    """Random SELECT lists mixing holes with quoted strings, quoted
    aliases, and comments holding hostile text. The builder's lexer and
    the engine must agree on every boundary, or a hole lands inside a
    literal or comment and the row comes back wrong."""
    d = ww.Dialect.sqlite
    rng = random.Random(seed)
    ok = [s for s in strings if not sqlite_rejects_string(s) and len(s) < 200]
    ok_names = [s for s in ok if s]
    for _ in range(n):
        count("random templates")
        b = ww.QueryBuilder(d)
        b.append_safe("SELECT ")
        want = []
        for i in range(rng.randint(1, 8)):
            if i:
                b.append_safe(rng.choice([", ", ",", " ,\n"]))
            r = rng.random()
            if r < 0.15:
                body = rng.choice(ok)
                while "*/" in body:
                    body = body.replace("*/", "")
                b.append_safe(f"/*{body}*/")
            elif r < 0.3:
                body = rng.choice(ok).replace("\n", "")
                b.append_safe(f"--{body}\n")
            s = rng.choice(ok)
            kind = rng.random()
            if kind < 0.4:
                b.append_string(s)
                want.append(s)
            elif kind < 0.7:
                b.append_safe(d.quote_string(s))
                want.append(s)
            else:
                b.append_int64(i)
                want.append(i)
            alias = rng.random()
            if alias < 0.2:
                b.append_safe(" AS " + d.quote_name(rng.choice(ok_names)))
            elif alias < 0.3:
                b.append_safe(" AS [" + rng.choice(ok_names).replace("]", "") + "]")
            elif alias < 0.4:
                b.append_safe(" AS `" + rng.choice(ok_names).replace("`", "") + "`")
        try:
            q = b.build()
        except Exception:  # noqa: BLE001
            # Only an alias in brackets or back quotes emptied by the
            # replace, or holding a stray, can fail the build here.
            count("random templates skipped")
            continue
        name, style, bind = rng.choice(styles())
        try:
            r = q.render(d, style)
        except Exception:  # noqa: BLE001
            # Named styles fail if their marker is in the text.
            name, style, bind = styles()[0]
            r = q.render(d, style)
        try:
            got = conn.execute(r.sql, bind(r.params)).fetchone()
            if list(got) != want:
                fail("random", f"{name}: {r.sql!r} gave {got!r}, not {want!r}")
        except Exception as e:  # noqa: BLE001
            fail("random", f"{name}: {r.sql!r} failed: {e!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=REPO / "temper.out" / "py",
                        help="Temper's Python output (default: temper.out/py)")
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--fuzz", type=int, default=3000, help="random strings to add")
    parser.add_argument("--templates", type=int, default=3000, help="random templates to run")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every failure")
    args = parser.parse_args()
    if not (args.out / "wherewith" / "wherewith").is_dir():
        print(f"No Wherewith Python library in {args.out}; run `temper build -b py` first.")
        return 2
    load_wherewith(args.out)
    start = time.perf_counter()
    conn = connect()
    print(f"SQLite {sqlite3.sqlite_version}, Python {sys.version.split()[0]}, "
          f"DQS {'off' if hasattr(conn, 'setconfig') else 'on (Python < 3.12)'}")
    strings = hostile_strings(args.seed, args.fuzz)
    for label, run in [
        ("strings", lambda: check_strings(conn, strings)),
        ("names", lambda: check_names(conn, strings)),
        ("params", lambda: check_params(conn, strings)),
        ("nesting", lambda: check_nesting(conn)),
        ("random templates", lambda: check_random_templates(conn, strings, args.seed, args.templates)),
    ]:
        t = time.perf_counter()
        run()
        if args.verbose:
            print(f"  ({label}: {time.perf_counter() - t:.1f} s)")
    elapsed = time.perf_counter() - start
    for kind, n in counts.items():
        print(f"  {kind}: {n}")
    print(f"{len(failures)} failures in {elapsed:.1f} s")
    shown = failures if args.verbose else failures[:30]
    for f in shown:
        print(f"  {f}")
    if len(shown) < len(failures):
        print(f"  ... and {len(failures) - len(shown)} more (-v lists all)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
