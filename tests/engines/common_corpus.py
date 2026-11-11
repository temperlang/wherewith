"""The common dialect on real engines: one corpus of common queries,
rendered for each engine and run there, with the same expected rows
everywhere, but where the design documents a difference, which is
asserted to still differ.

Each runner's engine names itself (`corpus_name`: sqlite, postgres,
mariadb, mysql, or duckdb) and its column types; `roundtrip.run_all` calls
`check` for every engine setting. The fixture has `NULL`s, negative
numbers, mixed case, a trailing space, and non-ASCII text, and is
filled with a rendered common `INSERT`.

Cases built unchecked run what the checks refuse, and probes run SQL
written for the engines directly, for what the parser refuses, so each
refusal's reason stays true. A case or probe can name the claim in
docs/design.md it confirms, so a failure says which row to correct.

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
# Any rows at all: the engine takes the query, whatever it gives.
ACCEPTED = "accepted"
# For a raw probe: not run on that engine.
SKIP = "skip"


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
class Exact:
    """Expected rows whose floats must match to the bit, so a zero's
    sign counts."""

    rows: list


@dataclass
class Case:
    name: str
    pieces: tuple
    rows: object  # a list of tuples, ERROR, ACCEPTED, Raw, or Exact
    # Documented differences: engine name to what it gives instead.
    differs: dict = field(default_factory=dict)
    # Built with Query.unchecked, for what the checks refuse, to pin
    # why they refuse it.
    unchecked: bool = False
    # The claim in docs/design.md the case confirms, named in failures.
    claim: str = ""


def C(name, *pieces, rows, unchecked=False, claim="", **differs):  # noqa: N802
    return Case(name, pieces, rows, differs, unchecked, claim)


@dataclass
class Probe:
    """SQL written for the engines directly, run as it is, for what
    the common parser refuses, to pin why it refuses it. Written to
    read the same on every engine (no quoted names, no `%`)."""

    name: str
    sql: str
    rows: object  # a list of tuples, ERROR, ACCEPTED, or SKIP
    claim: str
    differs: dict = field(default_factory=dict)


def P(name, sql, *, rows, claim, **differs):  # noqa: N802
    return Probe(name, sql, rows, claim, differs)


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
      sqlite=[(2,)], mariadb=[(2,)], mysql=[(2,)]),
    C("collation", "SELECT id FROM people WHERE name = 'BOB'", rows=[], mariadb=[(2,)], mysql=[(2,)]),
    C("LOWER past ASCII", "SELECT lower(name) FROM people WHERE id = 4", rows=[("émile",)], sqlite=[("Émile",)]),
    C("float to integer", "SELECT CAST(ratio AS INTEGER) FROM people WHERE id = 1", rows=[(2,)], sqlite=[(1,)]),
    C("text that isn't a number", "SELECT CAST(nick AS INTEGER) FROM people WHERE id = 1", rows=ERROR,
      sqlite=[(0,)], mariadb=[(0,)], mysql=[(0,)]),
    C("division by zero", "SELECT ratio / (score + 0.0) FROM people WHERE id = 4", rows=[(None,)],
      postgres=ERROR, duckdb=[(math.inf,)]),
    C("comparison results", "SELECT 1 < 2, TRUE", rows=Raw(("bool", "bool")),
      sqlite=Raw(("int", "int")), mariadb=Raw(("int", "int")), mysql=Raw(("int", "int"))),
    C("decimal literals", "SELECT 1.5", rows=Raw(("Decimal",)), sqlite=Raw(("float",))),
    C("AVG of integers", "SELECT avg(score) FROM people", rows=Raw(("Decimal",)),
      sqlite=Raw(("float",)), duckdb=Raw(("float",))),
    C("SUM of integers", "SELECT sum(score) FROM people", rows=Raw(("Decimal",)),
      sqlite=Raw(("int",)), duckdb=Raw(("int",))),
    # MySQL types the negation of a negative constant integer as
    # DECIMAL (MariaDB that of a negative constant expression), and
    # PyMySQL fills in values as literals, so `- %s` with -1 would be
    # `- -1`. Rendering folds the negation of a constant instead, so
    # every engine gives an integer.
    C("negating a negative value", "SELECT -", H(-1), " AS n", rows=[(1,)]),
    C("negating a negative value, type", "SELECT -", H(-1), " AS n", rows=Raw(("int",)),
      claim="rendering table, `-x` of a negative constant"),
    C("negating a negative literal, type", "SELECT -(-1)", rows=Raw(("int",)),
      claim="rendering table, `-x` of a negative constant"),
    C("negating a negative constant expression, type", "SELECT -(1 - 2)", rows=Raw(("int",)),
      claim="rendering table, `-x` of a negative constant"),
    C("negating a negative constant expression of values, type", "SELECT -(", H(1), " - ", H(2), ") AS n",
      rows=Raw(("int",)), claim="rendering table, `-x` of a negative constant"),
    C("negating a column, type", "SELECT -score FROM people WHERE id = 2", rows=Raw(("int",)),
      claim="rendering table, `-x` of a negative constant (a column stays an integer)"),
    # SQLite negates 0.0 to 0.0 and DuckDB to -0.0; folding binds 0.0.
    C("negating a zero float value", "SELECT -", H(0.0), " AS n", rows=Exact([(0.0,)]),
      claim="rendering table, `-x` of a negative constant (a float zero)"),
    C("NULLIF of values", "SELECT nullif(", H(1), ", ", H(2), ") AS n", rows=[(1,)],
      claim="decided 8: values cast where their type is unknown (NULLIF)"),
    # Where nothing but values and literals types a value, PostgreSQL
    # reads one sent untyped as text ('10' < '9'), as a literal's type
    # (a 32-bit INTEGER for 1, so 2.5 or 3000000000 fails), or not at
    # all; rendering casts it to its own type. The PostgreSQL runner
    # runs these untyped too, and psycopg's typed binding sends small
    # integers as 16-bit SMALLINTs, so 30000 * 30000 would overflow.
    C("values compared with values", "SELECT ", H(10), " < ", H(9), " AS a, ", H(10), " = ", H(10), " AS b, ",
      H("b"), " > ", H("a"), " AS c", rows=[(0, 1, 1)],
      claim="decided 8: values cast where their type is unknown (comparisons)"),
    C("values compared with literals", "SELECT ", H(10), " > 9 AS a, ", H(2.5), " > 2 AS b, ", H(3000000000),
      " > 1 AS c", rows=[(1, 1, 1)],
      claim="decided 8: values cast where their type is unknown (beside literals)"),
    C("values in a list of values", "SELECT ", H(10), " IN (", H(9), ", ", H(10), ") AS a, ", H(1), " IN (",
      H(1.0), ") AS b, ", H(5), " IN (1, 5) AS c", rows=[(1, 1, 1)],
      claim="decided 8: values cast where their type is unknown (IN lists)"),
    C("values between values", "SELECT ", H(5), " BETWEEN ", H(4), " AND ", H(10), " AS a, ", H(2.5),
      " BETWEEN 2 AND 3 AS b", rows=[(1, 1)],
      claim="decided 8: values cast where their type is unknown (BETWEEN)"),
    C("arithmetic on values", "SELECT ", H(1), " + ", H(2), " AS a, ", H(2.5), " * 2 AS b, ", H(7), " % ", H(4),
      " AS c, ", H(30000), " * ", H(30000), " AS d", rows=[(3, 5.0, 3, 900000000)],
      claim="decided 8: values cast where their type is unknown (arithmetic)"),
    C("arithmetic on values, type", "SELECT ", H(1), " + ", H(2), " AS a", rows=Raw(("int",)),
      claim="decided 8: values cast where their type is unknown (arithmetic)"),
    C("a value beside a function's type", "SELECT length(name) + ", H(0.5), " FROM people WHERE id = 5",
      rows=[(4.5,)], claim="decided 8: values cast where their type is unknown (beside a 32-bit INTEGER)"),
    C("signs before values", "SELECT +", H(3), " AS a, +", H(-2.5), " AS b, -", H(NOTHING), " AS c",
      rows=[(3, -2.5, None)], claim="decided 8: values cast where their type is unknown (signs)"),
    C("a sign before a value, type", "SELECT +", H(3), " AS a", rows=Raw(("int",)),
      claim="decided 8: values cast where their type is unknown (signs)"),
    C("values in functions", "SELECT abs(", H(-3), ") AS a, min(", H(10), ") AS b, max(", H("x"), ") AS c, sum(",
      H(2), ") AS d, avg(", H(2.5), ") AS e, count(", H(1), ") AS f", rows=[(3, 10, "x", 2, 2.5, 1)],
      claim="decided 8: values cast where their type is unknown (ABS, MIN, MAX, SUM, AVG, and COUNT)"),
    C("values in functions, type", "SELECT abs(", H(-3), ") AS a, min(", H(10), ") AS b, max(", H(10), ") AS c",
      rows=Raw(("int", "int", "int")),
      claim="decided 8: values cast where their type is unknown (ABS, MIN, and MAX)"),
    C("a value and IS NULL", "SELECT ", H(NOTHING), " IS NULL AS a, ", H(1), " IS NOT NULL AS b", rows=[(1, 1)],
      claim="decided 8: values cast where their type is unknown (IS NULL)"),
    C("a value as a CASE subject", "SELECT CASE ", H(2), " WHEN 1 THEN 'one' WHEN ", H(2), " THEN 'two' END AS a",
      rows=[("two",)], claim="decided 8: values cast where their type is unknown (a CASE subject)"),
    C("values beside literals in COALESCE and NULLIF", "SELECT coalesce(", H(2.5), ", 0) AS a, nullif(",
      H(3000000000), ", 0) AS b", rows=[(2.5, 3000000000)],
      claim="decided 8: values cast where their type is unknown (beside literals)"),
    # PostgreSQL's SUBSTR takes only 32-bit integers, so rendering casts
    # a start or length that isn't one, such as a BIGINT column.
    C("SUBSTR from a column and values", "SELECT substr(name, id), substr(name, ", H(2), ", ", H(3),
      ") FROM people WHERE id = 1", rows=[("alice", "lic")],
      claim="rendering table, `SUBSTR(s, i, n)`: PostgreSQL's takes only 32-bit integers"),
    C("collation and accents", "SELECT id FROM people WHERE name = 'emile'", rows=[], mariadb=[(4,)],
      mysql=[(4,)], claim="rendering table, `'a' = 'A'`: MariaDB's and MySQL's default collations ignore"
                          " accents too"),
    # MySQL's utf8mb4_0900_ai_ci is NO PAD, unlike MariaDB's default.
    C("collation and trailing spaces", "SELECT id FROM people WHERE name = 'carol'", rows=[], mariadb=[(3,)],
      claim="rendering table, `'a' = 'A'`: MariaDB's default collation pads spaces, and MySQL's doesn't"),
    # Expression rules from the manuals, each refused (or allowed) by
    # the checks, run as the engines read them. Most are built
    # unchecked, since the checks refuse them.
    C("integer division", "SELECT 7 / 2", rows=[(3.5,)], sqlite=[(3,)], postgres=[(3,)], unchecked=True,
      claim="rendering table, `7 / 2`"),
    C("text and integers in ||", "SELECT 'a' || 1, 1 || 'a', name || id FROM people WHERE id = 1",
      rows=[("a1", "1a", "alice1")], claim="rendering table, `a || b`: integers beside text"),
    C("% with a float", "SELECT 5.5 % 2", rows=[(1.5,)], sqlite=[(1.0,)], unchecked=True,
      claim="expression checks: `%` with a float, which SQLite truncates"),
    # PostgreSQL has no % for DOUBLE PRECISION at all.
    C("% with a float column", "SELECT ratio % 1.0 FROM people WHERE id = 1", rows=[(0.5,)], sqlite=[(0.0,)],
      postgres=ERROR, unchecked=True, claim="expression checks: `%` with a float, which SQLite truncates"),
    # 7.5, -7.5, and 10.5: halves show how each rounds.
    C("float to integer, halves", "SELECT CAST(ratio * 5.0 AS INTEGER), CAST(ratio * -5.0 AS INTEGER),"
      " CAST(ratio * 7.0 AS INTEGER) FROM people WHERE id = 1", rows=[(8, -8, 10)], sqlite=[(7, -7, 10)],
      unchecked=True,
      claim="rendering table, `CAST(x AS INTEGER)`: SQLite truncates floats; the others round halves to even"),
    C("decimal to integer, halves", "SELECT CAST(2.5 AS INTEGER), CAST(-2.5 AS INTEGER)", rows=[(3, -3)],
      sqlite=[(2, -2)], unchecked=True,
      claim="rendering table, `CAST(x AS INTEGER)`: SQLite truncates decimals; the others round halves away"
            " from zero"),
    C("floats as text", "SELECT CAST(ratio AS TEXT), ratio || '', CAST(ratio / 3.0 AS TEXT) FROM people"
      " WHERE id = 4", rows=[("2", "2", "0.6666666666666666")], sqlite=[("2.0", "2.0", "0.666666666666667")],
      duckdb=[("2.0", "2.0", "0.6666666666666666")], unchecked=True,
      claim="expression checks: floats in `||` or cast to `TEXT` are written differently"),
    C("a boolean in ||", "SELECT name || flag FROM people WHERE id = 1", rows=[("alicetrue",)],
      sqlite=[("alice1",)], mariadb=[("alice1",)], mysql=[("alice1",)], unchecked=True,
      claim="expression rule letters: a boolean in `||` is 1 in SQLite and MySQL, true in the others"),
    # PostgreSQL casts a boolean only to INTEGER (32 bits) and text.
    C("a boolean cast to INTEGER", "SELECT CAST(flag AS INTEGER) FROM people WHERE id = 1", rows=[(1,)],
      postgres=ERROR, unchecked=True, claim="expression checks: casts of booleans"),
    C("a boolean cast to DOUBLE", "SELECT CAST(flag AS DOUBLE) FROM people WHERE id = 1", rows=[(1.0,)],
      postgres=ERROR, unchecked=True, claim="expression checks: casts of booleans"),
    C("a boolean cast to TEXT", "SELECT CAST(flag AS TEXT) FROM people WHERE id = 1", rows=[("true",)],
      sqlite=[("1",)], mariadb=[("1",)], mysql=[("1",)], unchecked=True,
      claim="expression checks: casts of booleans"),
    C("an escape before an ordinary character", "SELECT 'ab' LIKE 'a!b' ESCAPE '!', 'a!b' LIKE 'a!b' ESCAPE '!'",
      rows=[(1, 0)], unchecked=True,
      claim="expression checks: an escape not before %, _, or itself (matches the character)"),
    C("an escape at the end", "SELECT 'a!' LIKE 'a!' ESCAPE '!', 'a' LIKE 'a!' ESCAPE '!'", rows=ERROR,
      sqlite=[(0, 0)], mariadb=[(1, 0)], mysql=[(1, 0)], unchecked=True,
      claim="expression checks: an escape not before %, _, or itself (at the end)"),
    C("integer % by zero", "SELECT score % (id - 4) FROM people WHERE id = 4", rows=[(None,)], postgres=ERROR,
      duckdb=ERROR, claim="rendering table, `x / 0`: `%` by zero"),
    C("float % by zero", "SELECT ratio % (id - 4) FROM people WHERE id = 4", rows=[(None,)], postgres=ERROR,
      duckdb=[(math.nan,)], claim="rendering table, `x / 0`: `%` by zero"),
    C("integer / by zero", "SELECT (score + 1) / (id - 4), (score - 1) / (id - 4) FROM people WHERE id = 4",
      rows=[(None, None)], postgres=ERROR, duckdb=[(math.inf, -math.inf)], unchecked=True,
      claim="rendering table, `x / 0`"),
    C("text plus a number", "SELECT '1' + 1", rows=[(2,)], duckdb=ERROR, unchecked=True,
      claim="expression checks: text in arithmetic"),
    C("decimal text plus a number", "SELECT '1.5' + 1", rows=[(2.5,)], postgres=ERROR, duckdb=ERROR,
      unchecked=True, claim="expression checks: text in arithmetic"),
    C("a text column plus a number", "SELECT nick + 1 FROM people WHERE id = 1", rows=[(1,)], postgres=ERROR,
      duckdb=ERROR, unchecked=True, claim="expression checks: text in arithmetic"),
    C("a float plus text", "SELECT ratio + '1' FROM people WHERE id = 1", rows=[(2.5,)], unchecked=True,
      claim="expression checks: text in arithmetic (beside a float, read alike)"),
    # Statement rules from the manuals, the same way.
    C("LIMIT in an IN subquery", "SELECT id FROM people WHERE id IN (SELECT owner FROM pets ORDER BY owner"
      " LIMIT 1)", rows=[(1,)], mariadb=ERROR, mysql=ERROR, unchecked=True,
      claim="statement checks: `LIMIT` in an `IN` subquery, which MySQL refuses (error 1235)"),
    C("* before other items", "SELECT *, owner FROM pets ORDER BY 1, 2 LIMIT 1", rows=[(1, "cat", 1)],
      claim="statement checks: `*` before other items, which every engine takes"),
    C("* after other items", "SELECT owner, * FROM pets ORDER BY 1, 3 LIMIT 1", rows=[(1, 1, "cat")],
      mariadb=ERROR, mysql=ERROR, unchecked=True,
      claim="statement checks: `*` after other items, which MySQL refuses"),
    C("GROUP BY a column that's also an alias", "SELECT owner % 2 AS owner, count(*) AS n FROM pets"
      " GROUP BY owner ORDER BY 2, 1", rows=[(0, 1), (1, 1), (1, 2)], unchecked=True,
      claim="which of alias and column: GROUP BY reads the column"),
    C("HAVING a grouped column that's also an alias", "SELECT owner AS o, -owner AS owner FROM pets"
      " GROUP BY owner HAVING owner > 1 ORDER BY 1", rows=[(2, -2), (9, -9)], unchecked=True,
      claim="which of alias and column: HAVING reads a grouped column"),
    C("HAVING an ungrouped column that's also an alias", "SELECT owner AS o, count(*) AS kind FROM pets"
      " GROUP BY owner HAVING kind > 1 ORDER BY 1", rows=[(1, 2)], sqlite=[(1, 2), (2, 1), (9, 1)],
      postgres=ERROR, unchecked=True,
      claim="which of alias and column: HAVING reads an ungrouped column in SQLite, the alias in DuckDB and"
            " MySQL"),
    C("WHERE a column that's also an alias", "SELECT id, -score AS score FROM people WHERE score > 0 ORDER BY 1",
      rows=[(1, -10), (5, -7)], unchecked=True, claim="which of alias and column: WHERE reads the column"),
    C("ORDER BY an expression of a column that's also an alias", "SELECT id, -score AS score FROM people"
      " WHERE score IS NOT NULL ORDER BY score + 0", rows=[(2, 3), (4, 0), (5, -7), (1, -10)], unchecked=True,
      claim="which of alias and column: inside ORDER BY expressions, the column everywhere, MariaDB and MySQL"
            " too"),
    C("ORDER BY a string", "SELECT id FROM people ORDER BY 'a', id", rows=[(1,), (2,), (3,), (4,), (5,)],
      postgres=ERROR, duckdb=ERROR, unchecked=True, claim="statement checks: constants in ORDER BY"),
    # MySQL reads -1 as an expression, a constant it ignores, where
    # MariaDB's parser folds it into a literal, a place.
    C("ORDER BY a negative integer", "SELECT id FROM people ORDER BY -1, id", rows=ERROR,
      mysql=[(1,), (2,), (3,), (4,), (5,)], unchecked=True,
      claim="statement checks: constants in ORDER BY (a negative integer fails everywhere but MySQL, which"
            " ignores it)"),
    C("ORDER BY a decimal", "SELECT id FROM people ORDER BY 1.5, id", rows=[(1,), (2,), (3,), (4,), (5,)],
      postgres=ERROR, duckdb=ERROR, unchecked=True, claim="statement checks: constants in ORDER BY"),
    C("ORDER BY a place past the items", "SELECT id FROM people ORDER BY 2", rows=ERROR,
      claim="statement checks: constants in ORDER BY (a place past the items fails everywhere)"),
    C("GROUP BY a string", "SELECT count(*) FROM pets GROUP BY 'a'", rows=[(4,)], postgres=ERROR,
      unchecked=True, claim="statement checks: constants in GROUP BY"),
    # Which owner comes first is up to the engine where it's taken.
    C("SELECT DISTINCT ordered by a column not selected", "SELECT DISTINCT owner FROM pets ORDER BY kind",
      rows=ACCEPTED, postgres=ERROR, mysql=ERROR, unchecked=True,
      claim="statement checks: SELECT DISTINCT ordered by something not selected (MySQL error 3065)"),
    C("ON reading a table joined after it", "SELECT count(*) FROM people AS p JOIN pets AS q"
      " ON q.owner = r.owner JOIN pets AS r ON r.owner = p.id", rows=ERROR, sqlite=[(5,)], unchecked=True,
      claim="statement checks: ON reading a table joined after it"),
    # What the output-name checks refuse, built unchecked.
    C("ORDER BY an alias beside a column of its name", "SELECT id, score AS id FROM people ORDER BY id",
      rows=[(3, None), (2, -3), (4, 0), (5, 7), (1, 10)], unchecked=True, postgres=ERROR, mariadb=ERROR,
      mysql=ERROR),
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

# Statement rules for writes, run after WRITES are read back.
LATER = [
    C("UPDATE reading its own table", "UPDATE scratch SET v = 'u' WHERE id IN (SELECT id FROM scratch"
      " WHERE id > 1)", rows=ACCEPTED, mysql=ERROR, unchecked=True,
      claim="statement checks: a subquery reading the table an UPDATE changes (MariaDB takes it from 10.3;"
            " MySQL error 1093)"),
    C("DELETE reading its own table", "DELETE FROM scratch WHERE id IN (SELECT id FROM scratch WHERE id > 100)",
      rows=ACCEPTED, mysql=ERROR, unchecked=True,
      claim="statement checks: a subquery reading the table a DELETE changes (MariaDB takes it from 10.3;"
            " MySQL error 1093)"),
    C("INSERT VALUES reading its own table", "INSERT INTO scratch (id, v) VALUES ((SELECT count(*) FROM scratch),"
      " 'x')", rows=ACCEPTED, mysql=ERROR, unchecked=True,
      claim="statement checks: a subquery reading the table an INSERT ... VALUES changes (MariaDB takes it;"
            " MySQL error 1093)"),
    C("INSERT naming a column twice", "INSERT INTO scratch (id, id) VALUES (1, 2)", rows=ERROR,
      sqlite=ACCEPTED, unchecked=True, claim="statement checks: a column twice in INSERT"),
    C("SET naming a column twice", "UPDATE scratch SET v = 'a', v = 'b' WHERE id = 1", rows=ERROR,
      sqlite=ACCEPTED, mariadb=ACCEPTED, mysql=ACCEPTED, unchecked=True,
      claim="statement checks: a column twice in SET"),
    # Row 11 is (11, 'alice') from WRITES on every engine; only `v` may
    # differ, which this sets.
    C("SET reading a column set before it", "UPDATE scratch SET id = id + 1000, v = CAST(id AS TEXT)"
      " WHERE id = 11", rows=ACCEPTED, unchecked=True, claim="the check stage: the `UPDATE … SET` trap"),
    C("SET reading a column set before it, read back", "SELECT v FROM scratch WHERE id = 1011", rows=[("11",)],
      mariadb=[("1011",)], mysql=[("1011",)],
      claim="the check stage: the `UPDATE … SET` trap (MySQL and MariaDB assign left to right)"),
]

# What the common parser refuses, as each engine reads it.
PROBES = [
    P("WHERE without FROM", "SELECT 1 AS x WHERE 1 = 1", rows=[(1,)],
      claim="the parser: clauses after the items without FROM"),
    P("WHERE without FROM, false", "SELECT 1 AS x WHERE 1 = 0", rows=[],
      claim="the parser: clauses after the items without FROM"),
    P("ORDER BY without FROM", "SELECT 1 AS x ORDER BY x", rows=[(1,)],
      claim="the parser: clauses after the items without FROM"),
    P("LIMIT without FROM", "SELECT 1 AS x LIMIT 1", rows=[(1,)],
      claim="the parser: clauses after the items without FROM"),
    P("TRIM with a second argument", "SELECT trim('xyxaxy', 'xy')", rows=[("a",)], mariadb=ERROR, mysql=ERROR,
      claim="the parser: TRIM takes one argument (a set of characters to remove, but MySQL has no such form)"),
    P("TRIM ... FROM", "SELECT trim(BOTH 'xy' FROM 'xyxaxy')", rows=[("a",)], sqlite=ERROR,
      mariadb=[("xa",)], mysql=[("xa",)],
      claim="the parser: TRIM takes one argument (MySQL removes a whole string)"),
    # What constant arithmetic that overflows gives, which the checks
    # refuse: SQLite turns to a float, DuckDB widens a negation to a
    # 128-bit integer, MySQL and MariaDB to DECIMAL, and the rest fail.
    P("negating the smallest integer", "SELECT -(-9223372036854775807 - 1)", rows=ERROR,
      sqlite=[(9223372036854775808,)], duckdb=[(9223372036854775808,)], mariadb=[(9223372036854775808,)],
      mysql=[(9223372036854775808,)], claim="rendering table, `-x` of a negative constant: past 64 bits"),
    P("adding past the largest integer", "SELECT 9223372036854775807 + 1", rows=ERROR,
      sqlite=[(9223372036854775808,)], claim="rendering table, `-x` of a negative constant: past 64 bits"),
    P("|| beside arithmetic", "SELECT 1 + 2 || 'a'", rows=[("3a",)], sqlite=[(3,)], mariadb=[(1,)], mysql=[(1,)],
      claim="the parser: `||` beside arithmetic needs parentheses (SQLite binds `||` tighter)"),
    # MySQL drops the backslash of an unknown escape, \x, in a string,
    # but keeps it before _ and %. Under NO_BACKSLASH_ESCAPES, MariaDB
    # still reads `\` as LIKE's escape (MySQL's manual says MySQL
    # doesn't), so `\` there is refused for that profile even alone.
    P("LIKE without ESCAPE, with a backslash", "SELECT 'a_b' LIKE 'a\\_b', 'a\\xb' LIKE 'a\\_b'", rows=[(0, 1)],
      postgres=[(1, 0)], mariadb=[(1, 0)], mysql=[(1, 0)], mysql_nbe=[(0, 1)],
      claim="rendering table, `LIKE p`, no `ESCAPE`: `\\` escapes in PostgreSQL and MariaDB, under"
            " NO_BACKSLASH_ESCAPES too, and in MySQL but not under it"),
    # What the refusal asks for instead: an ESCAPE reads alike in every
    # mode, and a backslash in the pattern is then itself.
    P("LIKE with ESCAPE, with a backslash", "SELECT 'a\\b' LIKE 'a\\%' ESCAPE '!', 'a_b' LIKE 'a!_b' ESCAPE '!'",
      rows=[(1, 1)], mariadb=SKIP, mariadb_nbe=[(1, 1)], mysql=SKIP, mysql_nbe=[(1, 1)],
      claim="rendering table, `LIKE p`, no `ESCAPE`: with `ESCAPE`, `\\` is itself under NO_BACKSLASH_ESCAPES"),
    P("a subquery in FROM without an alias", "SELECT count(*) FROM (SELECT 1 AS x)", rows=[(1,)], mariadb=ERROR,
      mysql=ERROR,
      claim="rendering table, subquery in `FROM`: an alias is required in MySQL, and in PostgreSQL before 16"),
    P("the default collation", "SELECT collation(name) FROM people WHERE id = 1", rows=SKIP,
      mariadb=[("utf8mb4_uca1400_ai_ci",)], mysql=[("utf8mb4_0900_ai_ci",)],
      claim="rendering table, `'a' = 'A'`: MariaDB's and MySQL's default collations"),
    P("the locale", "SELECT datcollate FROM pg_database WHERE datname = current_database()", rows=SKIP,
      postgres=[("en_US.utf8",)], claim="rendering table, `UPPER`, `LOWER`: the image's locale"),
]


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
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        return a == b or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return type(a) is type(b) and a == b


def matches(got, want) -> bool:
    if isinstance(want, Raw):
        return isinstance(got, list) and len(got) == 1 and tuple(type(v).__name__ for v in got[0]) == want.types
    if isinstance(want, Exact):
        return isinstance(got, list) and len(got) == len(want.rows) and all(
            rt.same_row(g, w) for g, w in zip(got, want.rows, strict=True))
    if want == ACCEPTED:
        return got != ERROR
    if want == ERROR or got == ERROR:
        return got == want
    return len(got) == len(want) and all(
        len(g) == len(w) and all(same_value(x, y) for x, y in zip(g, w, strict=True))
        for g, w in zip(got, want, strict=True)
    )


def usable(e, q, style_index: int) -> bool:
    """Whether q renders in a style: named styles refuse text holding
    their marker, by design."""
    return q.render_problem(e.dialect, e.corpus_styles()[style_index].style) is None


def run(e, q, style_index: int = 0):
    """Renders q for the engine and runs it in its first style (or
    another), giving the rows, or ERROR if the engine refuses it."""
    st = e.corpus_styles()[style_index]
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
            rt.fail("corpus", f"inserting {row!r} failed: {q.render(e.dialect, e.corpus_styles()[0].style).sql!r}"
                    f" gave {got!r}")
    for row in PETS:
        run(e, common("INSERT INTO pets (owner, kind) VALUES (", H(row[0]), ", ", H(row[1]), ")"))


def teardown(e) -> None:
    for table in ("people", "pets", "scratch"):
        try:
            e.execute(f"DROP TABLE {table}")
        except Exception:  # noqa: BLE001, PERF203
            pass


def claimed(case) -> str:
    return f" [docs/design.md: {case.claim}]" if case.claim else ""


def setting(e) -> str:
    """The engine's name, and for MariaDB or MySQL under
    NO_BACKSLASH_ESCAPES, `mariadb_nbe` or `mysql_nbe`, where a case can
    differ again."""
    return e.corpus_name + ("_nbe" if getattr(e, "nbe", False) else "")


def expected(e, differs: dict, rows):
    return differs.get(setting(e), differs.get(e.corpus_name, rows))


def check_case(e, case: Case) -> None:
    name = e.corpus_name
    rt.count("corpus queries")
    want = expected(e, case.differs, case.rows)
    try:
        q = unchecked_common(*case.pieces) if case.unchecked else common(*case.pieces)
    except Exception as err:  # noqa: BLE001
        rt.fail("corpus", f"{case.name}: the common query doesn't build ({rt.describe(err)}){claimed(case)}")
        return
    for i in range(len(e.corpus_styles())):
        if not usable(e, q, i):
            rt.count("corpus styles refused by design")
            continue
        got = run(e, q, i)
        if not matches(got, want):
            sql = q.render(e.dialect, e.corpus_styles()[i].style).sql
            rt.fail("corpus", f"{case.name} ({e.corpus_styles()[i].name}): {sql!r} gave {got!r}, not {want!r}"
                    f"{claimed(case)}")
    if name in case.differs:
        if matches(run(e, q), case.rows):
            rt.fail("corpus", f"{case.name}: documented as different on {name}, but isn't{claimed(case)}")
        else:
            rt.count("corpus differences confirmed")


def check_probe(e, probe: Probe) -> None:
    """Runs SQL as written, without Wherewith."""
    want = expected(e, probe.differs, probe.rows)
    if want == SKIP:
        return
    rt.count("corpus probes")
    try:
        got = [tuple(row) for row in e.execute(probe.sql)]
    except Exception as err:  # noqa: BLE001
        got = Refused(err)
    if not matches(got, want):
        rt.fail("corpus probe", f"{probe.name}: {probe.sql!r} gave {got!r}, not {want!r}"
                f" [docs/design.md: {probe.claim}]")


def check(e, seed: int, n: int) -> None:
    """Runs the corpus, the writes, the probes, and n random queries on
    one engine setting."""
    teardown(e)
    setup(e)
    try:
        for case in CASES:
            check_case(e, case)
        for pieces in WRITES:
            rt.count("corpus writes")
            q = common(*pieces)
            got = run(e, q)
            if got == ERROR:
                rt.fail("corpus", f"{q.render(e.dialect, e.corpus_styles()[0].style).sql!r} gave {got!r}")
        got = run(e, common("SELECT id, v FROM scratch ORDER BY id"))
        if not matches(got, WRITTEN):
            rt.fail("corpus", f"after the writes, scratch has {got!r}, not {WRITTEN!r}")
        for case in LATER:
            check_case(e, case)
        for probe in PROBES:
            check_probe(e, probe)
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
        st = rng.randrange(len(e.corpus_styles()))
        if not usable(e, q, st):
            st = 0
        got = run(e, q, st)
        if not matches(got, want):
            sql = q.render(e.dialect, e.corpus_styles()[st].style).sql
            rt.fail("corpus random", f"{sql!r} gave {got!r}, not SQLite's {want!r}")
