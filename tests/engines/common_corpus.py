"""The common dialect on real engines: one corpus of common queries,
rendered for each engine and run there, with the same expected rows
everywhere, but where the design documents a difference, which is
asserted to still differ.

Each runner's engine names itself (`corpus_name`: sqlite, postgres,
mariadb, or duckdb) and its column types; `roundtrip.run_all` calls
`check` for every engine setting. The fixture has `NULL`s, negative
numbers, mixed case, a trailing space, and non-ASCII text, and is
filled with a rendered common `INSERT`.

Results are normalized before comparing (booleans to integers, decimals
to floats, numbers compared by value), except in rows marked `Raw`,
which compare the Python type the driver gives back, to pin the
documented differences in result types. Random common queries are
checked against SQLite, through Python's own `sqlite3`, as the
reference.
"""

import math
import random
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal

import roundtrip as rt
from roundtrip import H

PEOPLE = [
    (1, "alice", "Al", 10, 1.5, True),
    (2, "Bob", None, -3, -0.25, False),
    (3, "carol ", "cc", None, None, None),
    (4, "Émile", "É", 0, 2.0, True),
    (5, "dave", None, 7, 0.5, False),
]
PETS = [(1, "cat"), (1, "dog"), (2, "cat"), (9, "fish")]

# What an engine gives instead of rows, when it refuses a query.
ERROR = "error"


class Refused(str):
    """ERROR, as an engine gave it: equal to ERROR, but carrying the
    error's type and the first line of its message, for failures."""

    def __new__(cls, err: BaseException):
        refused = super().__new__(cls, ERROR)
        refused.why = rt.describe(err)
        return refused

    def __repr__(self) -> str:
        return f"error ({self.why})"


@dataclass
class Raw:
    """Expected Python types of a row's values, as the driver gives
    them, unnormalized."""

    types: tuple[str, ...]


@dataclass
class Case:
    name: str
    pieces: tuple
    rows: object  # a list of tuples, ERROR, or Raw
    # Documented differences: engine name to what it gives instead.
    differs: dict = field(default_factory=dict)
    # Built with Query.unchecked, for what the checks refuse, to pin
    # why they refuse it.
    unchecked: bool = False


def C(name, *pieces, rows, unchecked=False, **differs):  # noqa: N802
    return Case(name, pieces, rows, differs, unchecked)


NOTHING = None

CASES = [
    # Names, values, and the clauses every database reads alike.
    C("where", "SELECT id, name FROM people WHERE score > ", H(0), " ORDER BY id",
      rows=[(1, "alice"), (5, "dave")]),
    C("limit and offset", "SELECT id FROM people ORDER BY id LIMIT 2 OFFSET 1", rows=[(2,), (3,)]),
    C("limit value", "SELECT id FROM people ORDER BY id LIMIT ", H(2), rows=[(1,), (2,)]),
    C("offset alone", "SELECT id FROM people ORDER BY id OFFSET ", H(3), rows=[(4,), (5,)]),
    # NULL order: smallest by default, and NULLS where written.
    C("nulls by default", "SELECT id FROM people ORDER BY score, id", rows=[(3,), (2,), (4,), (5,), (1,)]),
    C("nulls by default, descending", "SELECT id FROM people ORDER BY score DESC, id",
      rows=[(1,), (5,), (4,), (2,), (3,)]),
    C("nulls last", "SELECT id FROM people ORDER BY score NULLS LAST, id", rows=[(2,), (4,), (5,), (1,), (3,)]),
    C("nulls first, descending", "SELECT id FROM people ORDER BY score DESC NULLS FIRST, id",
      rows=[(3,), (1,), (5,), (4,), (2,)]),
    C("nulls last on an alias", "SELECT id, score + ", H(1), " AS s FROM people ORDER BY s NULLS LAST, id",
      rows=[(2, -2), (4, 1), (5, 8), (1, 11), (3, None)]),
    C("nulls first on a place", "SELECT score, id FROM people ORDER BY 1 DESC NULLS FIRST, 2",
      rows=[(None, 3), (10, 1), (7, 5), (0, 4), (-3, 2)]),
    # Concatenation: || or CONCAT, with PostgreSQL's casts.
    C("concatenation", "SELECT name || '/' || nick FROM people WHERE id IN (1, 2, 3) ORDER BY id",
      rows=[("alice/Al",), (None,), ("carol /cc",)]),
    C("concatenating numbers", "SELECT id || ':' || score, score || id FROM people WHERE id = 2",
      rows=[("2:-3", "-32")]),
    C("concatenating values", "SELECT ", H("a"), " || ", H("b"), " AS ab", rows=[("ab",)]),
    # Casts, functions, and operators.
    C("casts", "SELECT CAST(score AS TEXT), CAST('12' AS INTEGER), CAST('2.5' AS DOUBLE), CAST(id AS DOUBLE)"
      " FROM people WHERE id = 2", rows=[("-3", 12, 2.5, 2.0)]),
    C("length in characters", "SELECT length(name) FROM people WHERE id = 4", rows=[(5,)]),
    C("text functions", "SELECT upper(name), trim(name), replace(name, 'a', 'o'), substr(name, 2, 3),"
      " substr(name, 2) FROM people WHERE id = 3", rows=[("CAROL ", "carol", "corol ", "aro", "arol ")]),
    C("numbers", "SELECT (score + 1) * 2, score - -1, -score, abs(score), score % 4, score / 2.0, ratio * 2.0"
      " FROM people WHERE id = 2", rows=[(-4, -2, 3, 3, -3, -1.5, -0.5)]),
    C("like with escape", "SELECT id FROM people WHERE name LIKE ", H("%e"), " ESCAPE '!' ORDER BY id",
      rows=[(1,), (4,), (5,)]),
    C("like with escaped wildcard", "SELECT 'a%b' LIKE 'a!%b' ESCAPE '!', 'axb' LIKE 'a!%b' ESCAPE '!'",
      rows=[(1, 0)]),
    C("like a literal", "SELECT id FROM people WHERE name LIKE 'a%' ORDER BY id", rows=[(1,)]),
    C("booleans", "SELECT id, flag FROM people WHERE flag OR NOT flag ORDER BY id",
      rows=[(1, 1), (2, 0), (4, 1), (5, 0)]),
    C("true and false", "SELECT TRUE, FALSE, 1 < 2, 2 = 3", rows=[(1, 0, 1, 0)]),
    C("between and is null", "SELECT id FROM people WHERE score BETWEEN 0 AND 9 OR nick IS NULL ORDER BY id",
      rows=[(2,), (4,), (5,)]),
    C("not between", "SELECT id FROM people WHERE score NOT BETWEEN 0 AND 9 ORDER BY id", rows=[(1,), (2,)]),
    C("case", "SELECT id, CASE WHEN score > 5 THEN 'high' WHEN score < 0 THEN 'low' ELSE 'mid' END,"
      " CASE id WHEN 1 THEN 'one' END FROM people ORDER BY id",
      rows=[(1, "high", "one"), (2, "low", None), (3, "mid", None), (4, "mid", None), (5, "high", None)]),
    C("case of values", "SELECT CASE WHEN id = 1 THEN ", H("y"), " ELSE ", H("n"), " END FROM people"
      " WHERE id < 3 ORDER BY id", rows=[("y",), ("n",)]),
    C("coalesce and nullif", "SELECT coalesce(nick, name), nullif(score, 0) FROM people ORDER BY id",
      rows=[("Al", 10), ("Bob", -3), ("cc", None), ("É", None), ("dave", 7)]),
    C("coalesce of values", "SELECT coalesce(", H(NOTHING), ", ", H(2), ") AS n", rows=[(2,)]),
    C("values alone", "SELECT ", H("x"), " AS s, ", H(7), " AS i, ", H(2.5), " AS f, ", H(True), " AS b",
      rows=[("x", 7, 2.5, 1)]),
    # Aggregates, grouping, joins, and subqueries.
    C("aggregates", "SELECT count(*), count(nick), sum(score), min(score), max(score), avg(score) FROM people",
      rows=[(5, 3, 14, -3, 10, 3.5)]),
    C("grouping", "SELECT owner, count(*) AS n FROM pets GROUP BY owner HAVING count(*) > 0 ORDER BY owner",
      rows=[(1, 2), (2, 1), (9, 1)]),
    C("count distinct", "SELECT count(DISTINCT kind) FROM pets", rows=[(3,)]),
    C("join", "SELECT p.name, q.kind FROM people AS p JOIN pets AS q ON q.owner = p.id ORDER BY p.id, q.kind",
      rows=[("alice", "cat"), ("alice", "dog"), ("Bob", "cat")]),
    C("left join", "SELECT p.id, q.kind FROM people AS p LEFT JOIN pets AS q ON q.owner = p.id WHERE p.id > 1"
      " ORDER BY p.id, q.kind", rows=[(2, "cat"), (3, None), (4, None), (5, None)]),
    C("cross join", "SELECT count(*) FROM people CROSS JOIN pets", rows=[(20,)]),
    C("in a subquery", "SELECT id FROM people WHERE id IN (SELECT owner FROM pets) ORDER BY id", rows=[(1,), (2,)]),
    C("not in a subquery", "SELECT id FROM people WHERE id NOT IN (SELECT owner FROM pets) ORDER BY id",
      rows=[(3,), (4,), (5,)]),
    C("exists", "SELECT id FROM people WHERE EXISTS (SELECT 1 FROM pets WHERE pets.owner = people.id) ORDER BY id",
      rows=[(1,), (2,)]),
    C("scalar subquery", "SELECT (SELECT max(owner) FROM pets) AS m", rows=[(9,)]),
    C("subquery in FROM", "SELECT x.k, count(*) AS n FROM (SELECT kind AS k FROM pets) AS x GROUP BY x.k"
      " ORDER BY x.k", rows=[("cat", 2), ("dog", 1), ("fish", 1)]),
    C("distinct", "SELECT DISTINCT owner FROM pets ORDER BY owner", rows=[(1,), (2,), (9,)]),
    # A bare column in ORDER BY beside an item PostgreSQL names after it,
    # which rendering qualifies for PostgreSQL (the first two from CI's
    # random queries).
    C("ORDER BY a column beside its cast",
      "SELECT id || '-' || score, CAST(id AS DOUBLE), id, -score FROM people WHERE score BETWEEN -1 AND ", H(9),
      " OR score BETWEEN -1 AND ", H(0), " ORDER BY score DESC NULLS LAST, id",
      rows=[("5-7", 5.0, 5, -7), ("4-0", 4.0, 4, 0)]),
    C("ORDER BY a column beside its cast, after others",
      "SELECT nick, id, length(name), CAST(id AS DOUBLE) FROM people ORDER BY score + id, ratio DESC, id",
      rows=[("cc", 3, 6, 3.0), (None, 2, 3, 2.0), ("É", 4, 5, 4.0), ("Al", 1, 5, 1.0), (None, 5, 4, 5.0)]),
    C("ORDER BY a column cast to text", "SELECT CAST(score AS TEXT) FROM people WHERE score IS NOT NULL ORDER BY score",
      rows=[("-3",), ("0",), ("7",), ("10",)]),
    C("ORDER BY a column beside its cast, distinct",
      "SELECT DISTINCT id, CAST(id AS DOUBLE) FROM people WHERE id < 3 ORDER BY id DESC", rows=[(2, 2.0), (1, 1.0)]),
    C("ORDER BY a column beside its cast, grouped",
      "SELECT owner, CAST(owner AS TEXT), count(*) FROM pets GROUP BY owner ORDER BY owner DESC",
      rows=[(9, "9", 1), (2, "2", 1), (1, "1", 2)]),
    C("ORDER BY a column beside its cast, in FROM",
      "SELECT x.k, CAST(k AS TEXT) FROM (SELECT owner AS k FROM pets) AS x ORDER BY k DESC, 2",
      rows=[(9, "9"), (2, "2"), (1, "1"), (1, "1")]),
    # Documented differences, each asserted to still differ.
    C("LIKE's case", "SELECT id FROM people WHERE name LIKE 'b%' ORDER BY id", rows=[],
      sqlite=[(2,)], mariadb=[(2,)]),
    C("collation", "SELECT id FROM people WHERE name = 'BOB'", rows=[], mariadb=[(2,)]),
    C("LOWER past ASCII", "SELECT lower(name) FROM people WHERE id = 4", rows=[("émile",)], sqlite=[("Émile",)]),
    C("float to integer", "SELECT CAST(ratio AS INTEGER) FROM people WHERE id = 1", rows=[(2,)], sqlite=[(1,)]),
    C("text that isn't a number", "SELECT CAST(nick AS INTEGER) FROM people WHERE id = 1", rows=ERROR,
      sqlite=[(0,)], mariadb=[(0,)]),
    C("division by zero", "SELECT ratio / (score + 0.0) FROM people WHERE id = 4", rows=[(None,)],
      postgres=ERROR, duckdb=[(math.inf,)]),
    C("comparison results", "SELECT 1 < 2, TRUE", rows=Raw(("bool", "bool")),
      sqlite=Raw(("int", "int")), mariadb=Raw(("int", "int"))),
    C("decimal literals", "SELECT 1.5", rows=Raw(("Decimal",)), sqlite=Raw(("float",))),
    C("AVG of integers", "SELECT avg(score) FROM people", rows=Raw(("Decimal",)),
      sqlite=Raw(("float",)), duckdb=Raw(("float",))),
    C("SUM of integers", "SELECT sum(score) FROM people", rows=Raw(("Decimal",)),
      sqlite=Raw(("int",)), duckdb=Raw(("int",))),
    # What the output-name checks refuse, built unchecked.
    C("ORDER BY an alias beside a column of its name", "SELECT id, score AS id FROM people ORDER BY id",
      rows=[(3, None), (2, -3), (4, 0), (5, 7), (1, 10)], unchecked=True, postgres=ERROR, mariadb=ERROR),
    C("ORDER BY an expression's alias beside a column of its name", "SELECT id, score + 0 AS id FROM people ORDER BY id",
      rows=[(3, None), (2, -3), (4, 0), (5, 7), (1, 10)], unchecked=True, postgres=ERROR),
]

# Statements that change a table, run in order, then read back.
WRITES = [
    ("INSERT INTO scratch (id, v) VALUES (", H(1), ", ", H("a"), "), (2, 'b')"),
    ("UPDATE scratch SET v = v || '!' WHERE id = ", H(1)),
    ("DELETE FROM scratch WHERE id = 2",),
    ("INSERT INTO scratch (id, v) SELECT id + 10, name FROM people WHERE id = ", H(1)),
    ("UPDATE scratch SET v = ", H("z"), " WHERE id = 99"),
]
WRITTEN = [(1, "a!"), (11, "alice")]


def unchecked_common(*pieces):
    """A common query from text, without the checks."""
    ww = rt.ww
    return ww.Query.unchecked(ww.Dialect.common, [ww.QueryText(p) for p in pieces])


def common(*pieces, targets=None):
    """A common query from pieces, as the sql tag makes it."""
    ww = rt.ww
    b = ww.QueryBuilder(ww.Dialect.common)
    if targets is not None:
        b.targets = targets
    for p in pieces:
        if isinstance(p, str):
            b.append_safe(p)
        else:
            p.append(b)
    return b.build()


def norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def same_value(a, b) -> bool:
    a, b = norm(a), norm(b)
    numbers = (int, float)
    if isinstance(a, numbers) and isinstance(b, numbers):
        return a == b or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return type(a) is type(b) and a == b


def matches(got, want) -> bool:
    if isinstance(want, Raw):
        return isinstance(got, list) and len(got) == 1 and tuple(type(v).__name__ for v in got[0]) == want.types
    if want == ERROR or got == ERROR:
        return got == want
    return len(got) == len(want) and all(
        len(g) == len(w) and all(same_value(x, y) for x, y in zip(g, w, strict=True))
        for g, w in zip(got, want, strict=True)
    )


def usable(e, q, style_index: int) -> bool:
    """Whether q renders in a style: named styles refuse text holding
    their marker, by design."""
    return q.render_problem(e.dialect, e.styles()[style_index].style) is None


def run(e, q, style_index: int = 0):
    """Renders q for the engine and runs it in its first style (or
    another), giving the rows, or ERROR if the engine refuses it."""
    st = e.styles()[style_index]
    r = q.render(e.dialect, st.style)
    try:
        return [tuple(row) for row in st.run(r)]
    except Exception as err:  # noqa: BLE001
        return Refused(err)


def setup(e) -> None:
    types = e.corpus_types
    opts = e.corpus_options
    text = types["text"]
    e.execute(f"CREATE TABLE people (id {types['int']}, name {text}, nick {text}, score {types['int']},"
              f" ratio {types['float']}, flag {types['bool']}){opts}")
    e.execute(f"CREATE TABLE pets (owner {types['int']}, kind {text}){opts}")
    e.execute(f"CREATE TABLE scratch (id {types['int']}, v {text}){opts}")
    # Filled with rendered common INSERTs, values as parameters.
    for row in PEOPLE:
        q = common("INSERT INTO people (id, name, nick, score, ratio, flag) VALUES (",
                   H(row[0]), ", ", H(row[1]), ", ", H(row[2]), ", ", H(row[3]), ", ", H(row[4]), ", ",
                   H(row[5]), ")")
        got = run(e, q)
        if got == ERROR:
            rt.fail("corpus", f"inserting {row!r} failed: {q.render(e.dialect, e.styles()[0].style).sql!r}"
                    f" gave {got!r}")
    for row in PETS:
        run(e, common("INSERT INTO pets (owner, kind) VALUES (", H(row[0]), ", ", H(row[1]), ")"))


def teardown(e) -> None:
    for table in ("people", "pets", "scratch"):
        try:
            e.execute(f"DROP TABLE {table}")
        except Exception:  # noqa: BLE001, PERF203
            pass


def check(e, seed: int, n: int) -> None:
    """Runs the corpus, the writes, and n random queries on one engine
    setting."""
    name = e.corpus_name
    teardown(e)
    setup(e)
    try:
        for case in CASES:
            rt.count("corpus queries")
            want = case.differs.get(name, case.rows)
            try:
                q = unchecked_common(*case.pieces) if case.unchecked else common(*case.pieces)
            except Exception as err:  # noqa: BLE001
                rt.fail("corpus", f"{case.name}: the common query doesn't build ({rt.describe(err)})")
                continue
            for i in range(len(e.styles())):
                if not usable(e, q, i):
                    rt.count("corpus styles refused by design")
                    continue
                got = run(e, q, i)
                if not matches(got, want):
                    sql = q.render(e.dialect, e.styles()[i].style).sql
                    rt.fail("corpus", f"{case.name} ({e.styles()[i].name}): {sql!r} gave {got!r}, not {want!r}")
            if name in case.differs and matches(run(e, q), case.rows):
                rt.fail("corpus", f"{case.name}: documented as different on {name}, but isn't")
            if name in case.differs:
                rt.count("corpus differences confirmed")
        for pieces in WRITES:
            rt.count("corpus writes")
            q = common(*pieces)
            got = run(e, q)
            if got == ERROR:
                rt.fail("corpus", f"{q.render(e.dialect, e.styles()[0].style).sql!r} gave {got!r}")
        got = run(e, common("SELECT id, v FROM scratch ORDER BY id"))
        if not matches(got, WRITTEN):
            rt.fail("corpus", f"after the writes, scratch has {got!r}, not {WRITTEN!r}")
        check_random(e, seed, n)
    finally:
        teardown(e)


# Random queries, against SQLite as the reference. The pieces avoid
# what's documented to differ: text in ORDER BY (collation), LIKE (case),
# and LOWER and UPPER past ASCII.

ITEMS = [
    "id", "score", "nick", "name", "ratio", "score + id", "score * 2", "-score", "coalesce(nick, name)",
    "nullif(score, 0)", "CASE WHEN score > 0 THEN 'p' ELSE 'n' END", "name || '!'", "id || '-' || score",
    "abs(score)", "length(name)", "CAST(score AS TEXT)", "CAST(id AS DOUBLE)", "ratio * 2.0", "substr(name, 2)",
    "trim(name)", "upper(nick)", "flag", "score / 4.0", "coalesce(score, id) % 3",
    "(SELECT count(*) FROM pets WHERE pets.owner = people.id)",
]
SORTS = ["score", "score + id", "-score", "nullif(score, 0)", "ratio", "abs(score)", "flag"]
FILTERS = [
    "score > {v}", "nick IS NULL", "nick IS NOT NULL", "id IN (1, 3, {v})", "flag", "NOT flag",
    "score BETWEEN -1 AND {v}", "EXISTS (SELECT 1 FROM pets WHERE pets.owner = people.id)",
    "id IN (SELECT owner FROM pets)", "name = 'dave'", "ratio < 1.0", "coalesce(score, 0) <> {v}",
]


def random_query(rng: random.Random):
    pieces: list = ["SELECT "]
    count = rng.randint(1, 4)
    for i in range(count):
        if i:
            pieces.append(", ")
        if rng.random() < 0.15:
            pieces.append(H(rng.choice([1, -2, "v", 2.5])))
            pieces.append(f" AS h{i}")
        else:
            pieces.append(rng.choice(ITEMS))
    pieces.append(" FROM people")
    if rng.random() < 0.7:
        pieces.append(" WHERE ")
        for j in range(rng.randint(1, 3)):
            if j:
                pieces.append(rng.choice([" AND ", " OR "]))
            parts = rng.choice(FILTERS).split("{v}")
            for k, part in enumerate(parts):
                if k:
                    pieces.append(H(rng.randint(-3, 9)))
                pieces.append(part)
    pieces.append(" ORDER BY ")
    for _ in range(rng.randint(0, 2)):
        pieces.append(rng.choice(SORTS))
        pieces.append(rng.choice(["", " DESC", " NULLS FIRST", " NULLS LAST", " DESC NULLS FIRST", " DESC NULLS LAST"]))
        pieces.append(", ")
    pieces.append("id")
    if rng.random() < 0.3:
        pieces.append(" LIMIT ")
        pieces.append(H(rng.randint(0, 4)))
    if rng.random() < 0.3:
        pieces.append(" OFFSET ")
        pieces.append(H(rng.randint(0, 3)))
    return pieces


class Reference:
    """SQLite, through Python's sqlite3, with the same fixture."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE people (id INTEGER, name TEXT, nick TEXT, score INTEGER, ratio REAL,"
                          " flag BOOLEAN)")
        self.conn.execute("CREATE TABLE pets (owner INTEGER, kind TEXT)")
        self.conn.executemany("INSERT INTO people VALUES (?, ?, ?, ?, ?, ?)", PEOPLE)
        self.conn.executemany("INSERT INTO pets VALUES (?, ?)", PETS)

    def rows(self, q):
        r = q.render(rt.ww.Dialect.sqlite, rt.ww.PlaceholderStyle.question)
        return [tuple(row) for row in self.conn.execute(r.sql, [rt.py_value(p) for p in r.params])]


def check_random(e, seed: int, n: int) -> None:
    rng = random.Random(seed)
    ref = Reference()
    for _ in range(n):
        pieces = random_query(rng)
        try:
            q = common(*pieces)
        except Exception:  # noqa: BLE001
            # The checks refuse some mixes, such as a value compared
            # with text; that's their job, tested elsewhere.
            rt.count("corpus random refused")
            continue
        rt.count("corpus random")
        want = ref.rows(q)
        st = rng.randrange(len(e.styles()))
        if not usable(e, q, st):
            st = 0
        got = run(e, q, st)
        if not matches(got, want):
            sql = q.render(e.dialect, e.styles()[st].style).sql
            rt.fail("corpus random", f"{sql!r} gave {got!r}, not SQLite's {want!r}")
