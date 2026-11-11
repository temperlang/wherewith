"""Shared code for the round trips through real engines in this directory.

Each runner (`sqlite_roundtrip.py`, `postgres_roundtrip.py`,
`mariadb_roundtrip.py`, which runs MySQL too, and `duckdb_roundtrip.py`)
describes its engine with an `Engine` subclass: how to run SQL, which
inputs the engine can't take, and what it gives back. The checks here are the same for every engine:

1. Strings: `SELECT <quoteString(s)>` gives back exactly `s` (or, for an
   engine setting that reads a profile's escapes differently, what that
   setting reads), and inputs the engine can't take are rejected.
2. Names: a table and column made with `quoteName(n)` read back exactly
   from the engine's catalog, and work for an insert and a select.
3. Parameters: queries rendered in each placeholder style the driver
   takes bind values that come back equal, with the expected type.
4. Nested queries and holes beside operators give the expected rows,
   and random templates mixing holes with quoted literals, names, and
   comments check that the builder's lexer and the engine agree on
   every boundary.
5. Common queries, rendered for the engine, give the rows the shared
   corpus in `common_corpus.py` expects, the same on every engine but
   for documented differences, and random ones give SQLite's rows.
"""

import argparse
import contextlib
import math
import os
import random
import socket
import struct
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The generated Python library, set by load_wherewith.
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


def describe(err: BaseException) -> str:
    """An exception's type and the first line of its message."""
    lines = str(err).strip().splitlines()
    return f"{type(err).__name__}: {lines[0] if lines else ''}"


def short(s: str, n: int = 60) -> str:
    r = repr(s)
    return r if len(r) <= n else f"{r[:n]}... ({len(s)} chars)"


def has_surrogate(s: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def without(s: str, *marks: str) -> str:
    """s with every mark removed, repeating until none is left, since
    removing one can make another (as `**//` without `*/` is `*/`)."""
    while any(m in s for m in marks):
        for m in marks:
            s = s.replace(m, "")
    return s


# Inputs


def hostile_strings(seed: int, fuzz: int) -> list[str]:
    """Hostile text: the Temper tests' cases, then generated ones."""
    cases = [
        # From src/*-tests.temper.md.
        "", "plain", "it's", "'", "x'; DROP TABLE t; --", "\"", "`", "-- x",
        "/* x */", "# x", "a\nb", "a\r\nb", "\t", "$$", "?", "%s", ":x",
        "\U0001F600", "é", "﻿", " ", "￿", "\U0010ffff",
        "\\", "\x00", "/*", "\"; DROP TABLE t; --", "Robert'); DROP TABLE students; --",
        "weird \"col\"", "my schema", "a\"b`c", "100%", "zq'\"`\\%?$1@p1:p1-- /*",
        "a.b", "a\\", "a'\\" * 3, "n\"" * 5, "t ", "x" * 65,
        # More by hand.
        "''", "'''", "\\'", "\\''", "'\\", "\\\\'", "a''b", "a'' OR ''='",
        "*/", "/* /* */", "--", "-- \n", "--\r", ";", "; SELECT 1", "';--",
        "\x1a", "\\0", "\\Z", "\\x27", "\\u0027", "&#39;", "%27", "\r", "\n\n",
        "[", "]", "[a]", "`a`", "\"\"", "\"a\"\"", "$1", "?1", "@a", "$a", ":a",
        " ", "  ", " a ", " ", "　", "​", "‍", "‮",
        "\x7f", "\x80", "\x85", "\x9f", "é", "é̂̃",
        "\U0001F468‍\U0001F469‍\U0001F467", "\U0001D11E", "\U000E0001",
        "￾", "�", "\U0010fffe",
        # Near the name limits: 63 and 64 bytes, and 64 and 65 characters.
        "x" * 63, "x" * 64, "é" * 31 + "x", "é" * 32, "一" * 21,
        "一" * 22, "é" * 64, "é" * 65,
        # MariaDB reads table names with this prefix as file names.
        "#mysql50#t", "#mysql50#a@0020b", "a#mysql50#",
    ]
    # Every ASCII control character, alone and between text.
    for c in [*range(0x20), 0x7F]:
        ch = chr(c)
        cases += [ch, f"a{ch}b", f"'{ch}'", f"{ch}'{ch}"]
    # Quotes of every kind, alone, doubled, and around text.
    quotes = "'\"`´‘’‚‛“”„′″ʼ＇＂｀ʹʺ"
    for q in quotes:
        cases += [q, q * 2, f"{q}a{q}", f"a{q}{q}b", f"\\{q}", f"{q}\\"]
    # Combining marks: on a letter, on a quote, and alone.
    for m in ("̀", "́", "̧", "̸", "⃝", "️"):
        cases += [m, f"a{m}", f"'{m}", f"{m}'", f"\"{m}"]
    # Lone surrogates, which Python strings can hold.
    cases += ["\ud800", "a\udfffb", "\udbff\ud800"]
    # Very long.
    cases += ["a'\\" * 50_000, "'" * 100_000, "x" * 1_000_000, "\U0001F600" * 10_000]
    # Random fuzz, from a pool weighted toward trouble.
    rng = random.Random(seed)
    pool = list("'\"`\\;-/*?:@$%#[]() \t\r\n\x1a\x7f") + [
        "--", "/*", "*/", "''", "́", "\U0001F600", " ", "﻿",
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


INTS = [0, 1, -1, 7, 2**31 - 1, -(2**31), 2**53 + 1, 2**63 - 1, -(2**63)]
FLOATS = [0.0, -0.0, 1.5, -2.25, 1e308, -1e-308, 5e-324, math.inf, -math.inf, math.nan, 0.1]


# Values


def py_value(v):
    if isinstance(v, ww.SqlText | ww.SqlInt | ww.SqlFloat | ww.SqlBool):
        return v.value
    if isinstance(v, ww.SqlNull):
        return None
    raise TypeError(v)


def same(a, b, exact_floats: bool = True) -> bool:
    """Equal with the same type, and floats equal to the bit, NaN
    included, unless exact_floats is off (then 0.0 == -0.0)."""
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        if not exact_floats:
            return a == b
        return struct.pack("<d", a) == struct.pack("<d", b)
    return type(a) is type(b) and a == b


def same_row(got, want, exact_floats: bool = True) -> bool:
    return got is not None and len(got) == len(want) and all(
        same(g, w, exact_floats) for g, w in zip(got, want, strict=True)
    )


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


class Hole:
    """A template hole, as `${v}` would be."""

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


def template(tag_class, *pieces):
    """A tagged template: str pieces are text, Holes are holes."""
    t = tag_class()
    for p in pieces:
        if isinstance(p, str):
            t.append_safe(p)
        elif isinstance(p, Hole):
            p.append(t)
        else:
            raise TypeError(p)
    return t.accumulated


# Engines


@dataclass
class Style:
    """A placeholder style a driver takes, and how to run a rendered
    query with it, giving all its rows as tuples."""

    name: str
    style: object
    run: Callable
    # Off where the driver loses the sign of a zero.
    exact_floats: bool = True


class Engine:
    """One engine, through one driver, in one setting. Subclasses fill
    in the engine's specifics; the defaults suit most."""

    dialect = None
    tag_class = None
    # Float comparisons to the bit, or only by value.
    exact_floats = True
    # After CREATE TABLE's column list.
    table_options = ""
    # For the common corpus: the engine's name there, and its column
    # types and table options.
    corpus_name = ""
    corpus_types = {"int": "BIGINT", "text": "TEXT", "float": "DOUBLE PRECISION", "bool": "BOOLEAN"}
    corpus_options = ""

    def describe(self) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def execute(self, sql: str, params=()) -> list[tuple]:
        """Runs setup or catalog SQL, with the driver's usual style."""
        raise NotImplementedError

    def styles(self) -> list[Style]:
        raise NotImplementedError

    def corpus_styles(self) -> list[Style]:
        """The styles the common corpus runs in: the others, and any
        that only common queries need to work in."""
        return self.styles()

    # Strings

    def rejects_string(self, s: str) -> bool:
        """Whether the profile must reject `s` as a string literal."""
        return "\x00" in s or has_surrogate(s)

    def read_string(self, q: str):
        """What `SELECT q` gives back."""
        return self.execute(f"SELECT {q}")[0][0]

    def reads_as(self, s: str, q: str) -> str:
        """What the engine reads the literal q (quoting s) as."""
        return s

    def bindable(self, s: str) -> bool:
        """Whether the driver can bind s as a text parameter."""
        return not has_surrogate(s)

    def literal_in_template(self, q: str) -> bool:
        """Whether a template's text may hold the literal q."""
        return True

    def hole_text(self) -> tuple[str, str]:
        """SQL around a text parameter, to give it a type if needed."""
        return "", ""

    # Names

    def rejects_name(self, n: str) -> bool:
        return n == "" or "\x00" in n or has_surrogate(n)

    def table_for(self, n: str) -> str:
        """The table name to test n with (a column always uses n)."""
        return n

    @contextlib.contextmanager
    def name_table(self, qt: str, qn: str) -> Iterator[None]:
        """Creates table qt with text column qn, dropping it after."""
        self.execute(f"CREATE TABLE {qt} ({qn} TEXT){self.table_options}")
        try:
            yield
        finally:
            self.execute(f"DROP TABLE {qt}")

    def catalogs(self, table: str) -> list[tuple[str, list[str], list[str]]]:
        """(catalog, tables, columns) from each catalog, where only
        `table` should be there, with its one column."""
        raise NotImplementedError

    def result_name(self, description) -> str:
        return description[0][0]

    def result_names(self, description) -> list[str]:
        return [d[0] for d in description]

    def execute_described(self, sql: str) -> tuple[list[tuple], object]:
        """Runs SQL as written, giving its rows and the cursor's
        description."""
        raise NotImplementedError

    # Parameters

    def param_values(self, strings: list[str]) -> list:
        values = [ww.SqlText(s) for s in strings if self.bindable(s) and "\x00" not in s]
        values += [ww.SqlText(s) for s in self.nul_texts()]
        values += [ww.SqlInt(i) for i in INTS] + [ww.SqlFloat(f) for f in self.floats()]
        values += [ww.SqlBool(True), ww.SqlBool(False), ww.SqlNull()]
        return values

    def nul_texts(self) -> list[str]:
        """Texts with NUL that bind fine, though they can't be written."""
        return ["a\x00b", "\x00"]

    def floats(self) -> list[float]:
        return FLOATS

    def value_exprs(self, v) -> list[tuple[str, str]]:
        """SQL around each copy of v's parameter in a SELECT list."""
        raise NotImplementedError

    def expected_row(self, v) -> tuple:
        """What that SELECT gives back."""
        raise NotImplementedError

    values_table = ""  # CREATE TABLE v (i ..., ...)
    values_select = ""  # SELECT i, ... FROM v ORDER BY i

    def value_column(self, v) -> str:
        raise NotImplementedError

    def table_row(self, v) -> tuple:
        """The columns after i that values_select gives back for v."""
        raise NotImplementedError

    # Nesting and random templates

    def nesting_setup(self) -> None:
        pass

    def nesting_teardown(self) -> None:
        pass

    def nesting_cases(self) -> list:
        raise NotImplementedError

    def random_comment(self, rng: random.Random, body: str) -> str:
        raise NotImplementedError

    def random_alias(self, rng: random.Random, names: list[str]) -> str:
        return " AS " + self.dialect.quote_name(rng.choice(names))

    def limits(self) -> None:
        """Checks and records the engine's own limits."""


# 1. Strings


def check_strings(e: Engine, inputs: list[str], label: str = "strings") -> None:
    d = e.dialect
    pre, post = e.hole_text()
    first = e.styles()[0]
    for s in inputs:
        count(label)
        problem = d.string_problem(s)
        try:
            q = d.quote_string(s)
        except Exception:  # noqa: BLE001 (Temper's bubble)
            q = None
        if (q is None) != (problem is not None):
            fail(label, f"quoteString and stringProblem disagree for {short(s)}")
        if e.rejects_string(s):
            if q is not None:
                fail(label, f"accepted {short(s)} as {short(q)}")
            else:
                count(f"{label} rejected")
            continue
        if q is None:
            fail(label, f"rejected {short(s)}: {problem}")
            continue
        want = e.reads_as(s, q)
        try:
            got = e.read_string(q)
        except Exception as err:  # noqa: BLE001
            fail(label, f"SELECT {short(q)} failed: {describe(err)}")
            continue
        if not (isinstance(got, str) and got == want):
            fail(label, f"SELECT {short(q)} gave {short(str(got))}, not {short(want)}")
        if not e.bindable(s):
            continue
        # The builder's lexer must agree with the engine on where the
        # literal ends, so a hole after it is still code.
        b = ww.QueryBuilder(d)
        b.append_safe(f"SELECT {q}, {pre}")
        b.append_string(s)
        b.append_safe(f"{post}, {q}")
        if not e.literal_in_template(q):
            if b.template_problem is None:
                fail(label, f"builder took {short(q)}, which templates refuse")
            else:
                count(f"{label} refused in templates by design")
            continue
        try:
            r = b.build().render(d, first.style)
            got = first.run(r)
            if got != [(want, s, want)]:
                fail(label, f"builder with {short(q)} gave {short(repr(got))}")
        except Exception as err:  # noqa: BLE001
            fail(label, f"builder with {short(q)} failed: {describe(err)}")


# 2. Names


def check_names(e: Engine, inputs: list[str]) -> None:
    d = e.dialect
    first = e.styles()[0]
    for n in inputs:
        count("names")
        try:
            qn = d.quote_name(n)
        except Exception:  # noqa: BLE001
            qn = None
        if (qn is None) != (d.name_problem(n) is not None):
            fail("names", f"quoteName and nameProblem disagree for {short(n)}")
        if e.rejects_name(n):
            if qn is not None:
                fail("names", f"accepted {short(n)} as {short(qn)}")
            else:
                count("names rejected")
            continue
        if qn is None:
            fail("names", f"rejected {short(n)}: {d.name_problem(n)}")
            continue
        table = e.table_for(n)
        qt = qn if table == n else d.quote_name(table)
        try:
            with e.name_table(qt, qn):
                for catalog, tables, cols in e.catalogs(table):
                    if tables != [table]:
                        fail("names", f"{catalog} has tables {[short(t) for t in tables]}, not {short(table)}")
                    if cols != [n]:
                        fail("names", f"{catalog} has columns {[short(c) for c in cols]}, not {short(n)}")
                # Insert and select through the names, as a QueryName
                # where Identifier takes the name, or else as checked
                # text. The longest skip the builder, whose lexer is
                # slow in Python.
                value = f"v:{n[:20]}"
                names = {"T": name_piece(table, qt), "C": name_piece(n, qn)}
                build = names_query if len(n) <= 100_000 else unchecked_query
                ins = build(d, names, ["INSERT INTO ", "T", " (", "C", ") VALUES (", "V", ")"], value)
                sel = build(
                    d, names, ["SELECT ", "C", ", ", "T", ".", "C", " FROM ", "T", " WHERE ", "C", " = ", "V"], value
                )
                first.run(ins.render(d, first.style))
                rows, description = first.run(sel.render(d, first.style), with_description=True)
                if rows != [(value, value)]:
                    fail("names", f"select through {short(n)} gave {rows!r}")
                if e.result_name(description) != n:
                    fail("names", f"result column for {short(n)} is {short(e.result_name(description))}")
        except Exception as err:  # noqa: BLE001
            fail("names", f"using {short(n)} failed: {describe(err)}")


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


def unchecked_query(d, names: dict, pieces: list[str], value: str):
    """As names_query, but with Query.unchecked, skipping the lexer."""
    parts = []
    for p in pieces:
        if p == "V":
            parts.append(ww.QueryParam(ww.SqlText(value)))
        elif p in names:
            name = names[p]
            parts.append(ww.QueryText(name) if isinstance(name, str) else ww.QueryName(name))
        else:
            parts.append(ww.QueryText(p))
    return ww.Query.unchecked(d, parts)


# 3. Parameters


def check_params(e: Engine, strings: list[str]) -> None:
    d = e.dialect
    values = e.param_values(strings)
    e.execute(e.values_table)
    try:
        for st in e.styles():
            ex = e.exact_floats and st.exact_floats
            # One value per query, through the tag, with the typed
            # overloads and as a SqlValue.
            for v in values:
                count("params")
                tag = e.tag_class()
                tag.append_safe("SELECT ")
                for i, (pre, post) in enumerate(e.value_exprs(v)):
                    tag.append_safe(f"{', ' if i else ''}{pre}")
                    if i:
                        tag.append_value(v)
                    else:
                        append_typed(tag, v)
                    tag.append_safe(post)
                want = e.expected_row(v)
                try:
                    got = st.run(tag.accumulated.render(d, st.style))
                    if not (len(got) == 1 and same_row(got[0], want, ex)):
                        fail("params", f"{st.name}: {short(str(py_value(v)))} came back as {got!r}, not {want!r}")
                except Exception as err:  # noqa: BLE001
                    fail("params", f"{st.name}: {short(str(py_value(v)))} failed: {describe(err)}")
            # Many values in one query, numbered straight through.
            for start in range(0, len(values), 200):
                chunk = values[start : start + 200]
                count("params batches")
                b = ww.QueryBuilder(d)
                b.append_safe("SELECT ")
                for i, v in enumerate(chunk):
                    pre, post = e.value_exprs(v)[0]
                    b.append_safe(f"{', ' if i else ''}{pre}")
                    b.append_value(v)
                    b.append_safe(post)
                try:
                    got = st.run(b.build().render(d, st.style))[0]
                    for v, g in zip(chunk, got, strict=True):
                        if not same(g, e.expected_row(v)[0], ex):
                            fail("params", f"{st.name} batch: {short(str(py_value(v)))} came back as {short(str(g))}")
                except Exception as err:  # noqa: BLE001
                    fail("params", f"{st.name} batch at {start} failed: {describe(err)}")
            # Through a table.
            e.execute("DELETE FROM v")
            for i, v in enumerate(values):
                b = ww.QueryBuilder(d)
                b.append_safe(f"INSERT INTO v (i, {e.value_column(v)}) VALUES (")
                b.append_int(i)
                b.append_safe(", ")
                b.append_value(v)
                b.append_safe(")")
                try:
                    st.run(b.build().render(d, st.style))
                except Exception as err:  # noqa: BLE001
                    fail("params", f"{st.name} insert of {short(str(py_value(v)))} failed: {describe(err)}")
            rows = {r[0]: r[1:] for r in e.execute(e.values_select)}
            count("params table rows", len(rows))
            for i, v in enumerate(values):
                want = e.table_row(v)
                if not same_row(rows.get(i), want, ex):
                    fail("params", f"{st.name} table row {i}: {short(str(py_value(v)))} came back as {rows.get(i)!r}")
    finally:
        e.execute("DROP TABLE v")


# 4. Nested queries, holes beside operators, and random templates


def check_nesting(e: Engine) -> None:
    d = e.dialect
    e.nesting_setup()
    try:
        for q, want in e.nesting_cases():
            for st in e.styles():
                count("nesting")
                try:
                    r = q.render(d, st.style)
                except Exception as err:  # noqa: BLE001
                    sql = q.render(d, ww.PlaceholderStyle.question).sql
                    marker = {ww.PlaceholderStyle.colon_named: ":", ww.PlaceholderStyle.at_named: "@"}.get(st.style)
                    if marker and marker in sql:
                        # Named styles refuse text holding their marker.
                        count("nesting refused by design")
                    else:
                        fail("nesting", f"{st.name}: rendering {sql!r} failed: {describe(err)}")
                    continue
                try:
                    got = st.run(r)
                    if not (len(got) == len(want) and all(same_row(g, w) for g, w in zip(got, want, strict=True))):
                        fail("nesting", f"{st.name}: {r.sql!r} gave {got!r}, not {want!r}")
                except Exception as err:  # noqa: BLE001
                    fail("nesting", f"{st.name}: {r.sql!r} failed: {describe(err)}")
    finally:
        e.nesting_teardown()


def check_random_templates(e: Engine, strings: list[str], seed: int, n: int) -> None:
    """Random SELECT lists mixing holes with quoted strings, quoted
    aliases, and comments holding hostile text. The builder's lexer and
    the engine must agree on every boundary, or a hole lands inside a
    literal or comment and the row comes back wrong."""
    d = e.dialect
    rng = random.Random(seed)
    ok = [s for s in strings if not e.rejects_string(s) and e.bindable(s) and len(s) < 200]
    ok_names = [s for s in ok if d.name_problem(s) is None]
    pre, post = e.hole_text()
    styles = e.styles()
    for _ in range(n):
        count("random templates")
        b = ww.QueryBuilder(d)
        b.append_safe("SELECT ")
        want = []
        for i in range(rng.randint(1, 8)):
            if i:
                b.append_safe(rng.choice([", ", ",", " ,\n"]))
            if rng.random() < 0.3:
                b.append_safe(e.random_comment(rng, rng.choice(ok)))
            s = rng.choice(ok)
            kind = rng.random()
            if kind < 0.4:
                b.append_safe(pre)
                b.append_string(s)
                b.append_safe(post)
                want.append(s)
            elif kind < 0.7 and e.literal_in_template(d.quote_string(s)):
                b.append_safe(d.quote_string(s))
                want.append(s)
            elif kind < 0.7:
                b.append_string(s)
                want.append(s)
            else:
                b.append_int64(i)
                want.append(i)
            if rng.random() < 0.4:
                b.append_safe(e.random_alias(rng, ok_names))
        try:
            q = b.build()
        except Exception:  # noqa: BLE001
            # Only an alias or comment the engine's syntax rules out,
            # such as an unclosed nested comment, or one the lexer
            # refuses by design, such as a quote in a DuckDB block
            # comment, fails the build here.
            count("random templates skipped")
            continue
        st = rng.choice(styles)
        try:
            r = q.render(d, st.style)
        except Exception:  # noqa: BLE001
            # Named styles fail if their marker is in the text.
            st = styles[0]
            r = q.render(d, st.style)
        try:
            got = st.run(r)
            if not (len(got) == 1 and list(got[0]) == want):
                fail("random", f"{st.name}: {r.sql!r} gave {got!r}, not {want!r}")
        except Exception as err:  # noqa: BLE001
            fail("random", f"{st.name}: {r.sql!r} failed: {describe(err)}")


# Running


def arguments(doc: str, server: tuple[str, str, str, int] | None = None) -> argparse.ArgumentParser:
    """Common options; server is (name, host variable, port variable,
    default port) for an engine reached over the network."""
    parser = argparse.ArgumentParser(description=doc.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=REPO / "temper.out" / "py",
                        help="Temper's Python output (default: temper.out/py)")
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--fuzz", type=int, default=3000, help="random strings to add")
    parser.add_argument("--templates", type=int, default=3000, help="random templates to run")
    parser.add_argument("--common", type=int, default=500, help="random common queries to run")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every failure")
    if server:
        name, host_var, port_var, port = server
        parser.add_argument("--require-server", action="store_true",
                            help=f"fail, rather than skip, if no {name} server is reachable (for CI)")
        parser.set_defaults(host=os.environ.get(host_var, "127.0.0.1"),
                            port=int(os.environ.get(port_var, str(port))))
    return parser


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def start(args, server_name: str | None = None) -> int | None:
    """Loads Wherewith and checks for the server. Returns an exit status
    to stop with, or None to go on."""
    if not (args.out / "wherewith" / "wherewith").is_dir():
        print(f"No Wherewith Python library in {args.out}; run `temper build -b py` first.")
        return 2
    if server_name and not reachable(args.host, args.port):
        message = f"No {server_name} server at {args.host}:{args.port}"
        if args.require_server:
            print(f"{message}.")
            return 1
        print(f"{message}; skipping. (CI runs these against a service container.)")
        return 0
    load_wherewith(args.out)
    return None


def run_all(e: Engine, args, label: str = "", strings: list[str] | None = None) -> None:
    """Runs every check on one engine setting."""
    strings = strings if strings is not None else hostile_strings(args.seed, args.fuzz)
    print(e.describe())
    e.limits()
    for name, run in [
        ("strings", lambda: check_strings(e, strings)),
        ("names", lambda: check_names(e, strings)),
        ("params", lambda: check_params(e, strings)),
        ("nesting", lambda: check_nesting(e)),
        ("random templates", lambda: check_random_templates(e, strings, args.seed, args.templates)),
        ("common corpus", lambda: check_common(e, args)),
    ]:
        t = time.perf_counter()
        before = len(failures)
        run()
        if args.verbose or len(failures) > before:
            print(f"  {label}{name}: {len(failures) - before} failures, {time.perf_counter() - t:.1f} s")


def check_common(e: Engine, args) -> None:
    import common_corpus  # noqa: PLC0415

    if e.corpus_name:
        common_corpus.check(e, args.seed, args.common)


def finish(args, started: float) -> int:
    for kind, n in counts.items():
        print(f"  {kind}: {n}")
    print(f"{len(failures)} failures in {time.perf_counter() - started:.1f} s")
    shown = failures if args.verbose else failures[:30]
    for f in shown:
        print(f"  {f}")
    if len(shown) < len(failures):
        print(f"  ... and {len(failures) - len(shown)} more (-v lists all)")
    return 1 if failures else 0
