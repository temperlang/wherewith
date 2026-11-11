"""A tour of Wherewith's whole public API, from Python.

The same tour exists for each language Wherewith supports, and they all
print the same text. See demos/README.md for how to run them.
"""

# snippet: setup
from wherewith import Dialect, Identifier, PlaceholderStyle, QueryBuilder, identifier_problem

# Each database, with a placeholder style its drivers take.
databases = [
    ("sqlite", Dialect.sqlite, PlaceholderStyle.question),
    ("postgres", Dialect.postgres, PlaceholderStyle.dollar_numbered),
    ("mysql", Dialect.mysql, PlaceholderStyle.percent_s),
    ("duckdb", Dialect.duckdb, PlaceholderStyle.dollar_numbered),
]


def for_each_database(q):
    for name, dialect, style in databases:
        print(f"{name}: {q.render(dialect, style).sql}")


# A common query is a QueryBuilder for Dialect.common: SQL text with
# append_safe, and values, names, and other queries in holes between. In
# Temper, sql"…" builds the same.
def common(text):
    b = QueryBuilder(Dialect.common)
    b.append_safe(text)
    return b
# end snippet


def section(title):
    print()
    print(f"## {title}")


print("# Wherewith tour")

section("1. Write it once")

# snippet: write-once
b = QueryBuilder(Dialect.common)
b.append_safe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (")
b.append_int(7)
b.append_safe(", ")
b.append_int(9)
b.append_safe(") ORDER BY name NULLS LAST LIMIT ")
b.append_int(10)
q = b.build()  # raises RuntimeError if the query is refused

# Rendered for Dialect.common, it's the canonical form, for logs.
print("common: " + q.render(Dialect.common, PlaceholderStyle.question).sql)
# PostgreSQL already sorts nulls last going up, so it needs no NULLS LAST,
# and MySQL has no NULLS, so it sorts by name IS NULL first.
for_each_database(q)
# Values print as SQL would write them, for reading only.
print("params: " + ", ".join(str(v) for v in q.params))
# end snippet

section("2. Values are bound, never spliced")

# snippet: bound
name = "Robert'); DROP TABLE students; --"
# Building SQL by hand puts the value in the text, where it ends the
# string early and adds a statement of its own.
print("by hand: SELECT id FROM students WHERE name = '" + name + "'")
# A hole sends the value apart from the SQL, for the driver to bind.
b = common("SELECT id FROM students WHERE name = ")
b.append_string(name)
r = b.build().render(Dialect.sqlite, PlaceholderStyle.question)
print("wherewith: " + r.sql)
print("params: " + ", ".join(str(v) for v in r.params))

# A name from outside is an Identifier, quoted for each database, never
# a value or SQL.
b = common("SELECT * FROM ")
b.append_identifier(Identifier.named('students"; DROP TABLE x; --'))
q = b.build()
print("a hostile name: " + q.render(Dialect.sqlite, PlaceholderStyle.question).sql)
print("in MySQL: " + q.render(Dialect.mysql, PlaceholderStyle.percent_s).sql)

# A hole inside quotes is refused: it would be text, not a value.
b = common("SELECT id FROM students WHERE name = '")
b.append_string(name)
b.append_safe("'")
print("a hole in quotes: " + b.template_problem)
# end snippet

section("3. Refused when it's built")

# snippet: refused
# Each of these runs on every database, and gives different results on
# some. template_problem says why build would refuse it, and where.
def refused(sql):
    print(f"{sql}: {common(sql).template_problem or 'built'}")


# 7 / 2 is 3 in SQLite and PostgreSQL, and 3.5 in MySQL and DuckDB.
refused("SELECT a / 2 FROM t")
# b = NULL matches no row: NULL isn't equal to anything, even NULL.
refused("SELECT a FROM t WHERE b = NULL")
# PostgreSQL reads Name as name; the others keep its case.
refused("SELECT Name FROM t")
# SQLite gives any row's a; the others refuse the query.
refused("SELECT a, count(*) AS n FROM t GROUP BY b")
# SQLite reads ('a' || 1) + 2, PostgreSQL 'a' || (1 + 2).
refused("SELECT 'a' || 1 + 2 AS x")
# Some databases turn 0 into text, and others refuse it.
refused("SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t")
# Databases name a + 1 differently (a+1, ?column?, or (a + 1)), so
# an expression in a FROM subquery needs an alias.
refused("SELECT * FROM (SELECT a + 1 FROM t) AS s")
# A placeholder in the text would shift every value's place.
refused("SELECT a FROM t WHERE id = ?")
# What isn't in the common dialect yet is refused too.
refused("SELECT 1 AS a UNION SELECT 2")
# The fix for the first: a float operand divides the same everywhere.
refused("SELECT 7 / 2.0 AS x")
# A null value is refused where NULL would be.
b = common("SELECT a FROM t WHERE b = ")
b.append_string(None)
print("SELECT a FROM t WHERE b = ${null}: " + b.template_problem)
# end snippet

section("4. What differs, handled")

# snippet: differs
# MySQL's || means OR, so it's CONCAT there.
text = "SELECT id || ':' || name AS tag FROM people"
print(text)
for_each_database(common(text).build())
# Each database names its types differently, and MySQL's LENGTH counts
# bytes, not characters.
text = "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people"
print(text)
for_each_database(common(text).build())
# Where nulls sort differs, and so does OFFSET without LIMIT.
b = common("SELECT name FROM people ORDER BY nick DESC OFFSET ")
b.append_int(20)
print("SELECT name FROM people ORDER BY nick DESC OFFSET ${20}")
for_each_database(b.build())
# PostgreSQL can't guess a lone parameter's type, so it gets a cast.
b = common("SELECT ")
b.append_string("hi")
b.append_safe(" AS greeting")
print('SELECT ${"hi"} AS greeting')
for_each_database(b.build())
# end snippet

section("5. Queries in queries")

# snippet: nested
big = common("SELECT user_id FROM orders WHERE total > ")
big.append_int(100)
b = common("SELECT name FROM users WHERE id IN (")
b.append_query(big.build())
b.append_safe(") AND active = ")
b.append_string("yes")
q = b.build()
# The inner query's parameters are numbered with the outer query's.
print("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
print("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percent_s).sql)
# And it's checked again as part of the whole, with problems at its hole.
inner = common("SELECT user_id FROM orders LIMIT ")
inner.append_int(5)
b = common("SELECT name FROM people WHERE id IN (")
b.append_query(inner.build())
b.append_safe(")")
print("with LIMIT inside: " + b.template_problem)
# end snippet

section("6. Building queries in code")

# snippet: dynamic
# Filters only when given, a sort column from the caller, and a page.
# Every variant is still checked when it's built.
def search(word=None, min_total=None, sort=Identifier.named("created"), descending=False, page=0):
    b = common("SELECT id, title FROM orders")
    joiner = " WHERE "
    if word is not None:
        b.append_safe(joiner + "title LIKE ")
        b.append_string(word)
        b.append_safe(" || '%' ESCAPE '!'")
        joiner = " AND "
    if min_total is not None:
        b.append_safe(joiner + "total >= ")
        b.append_int(min_total)
    b.append_safe(" ORDER BY ")
    b.append_identifier(sort)
    b.append_safe(" DESC LIMIT " if descending else " LIMIT ")
    b.append_int(20)
    b.append_safe(" OFFSET ")
    b.append_int(page * 20)
    return b.build().render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql


print(search())
print(search(word="Launch"))
print(search(min_total=100, sort=Identifier.named("total"), descending=True, page=2))

# A query for fewer databases relaxes the checks for the others: MySQL
# reads \ in a string as an escape, so it's refused only while MySQL is
# a target. The query renders only for its targets.
b = QueryBuilder(Dialect.common)
b.targets = [Dialect.postgres, Dialect.sqlite]
b.append_safe("SELECT 'C:\\temp' AS p")
q = b.build()
print("for postgres and sqlite: " + q.render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
print("for mysql: " + q.render_problem(Dialect.mysql, PlaceholderStyle.percent_s))
# end snippet

section("7. Placeholders for each driver")

# snippet: placeholders
# The placeholder style depends on the driver, not the database, so it's
# chosen when rendering. percent_s doubles %, for drivers that fill in
# values with Python's % formatting.
b = common("SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ")
b.append_int(1)
q = b.build()
styles = [
    PlaceholderStyle.question,
    PlaceholderStyle.dollar_numbered,
    PlaceholderStyle.percent_s,
    PlaceholderStyle.at_named,
    PlaceholderStyle.colon_named,
]
for style in styles:
    print(f"{style}: {q.render(Dialect.sqlite, style).sql}")
# A named style refuses text holding its marker, which a driver could
# misread as a name.
b = common("SELECT 'a:b' AS s FROM users WHERE id = ")
b.append_int(1)
print("colonNamed with 'a:b': " + b.build().render_problem(Dialect.sqlite, PlaceholderStyle.colon_named))
# end snippet

section("8. Each database's own SQL")

# snippet: own-sql
# For SQL the common dialect doesn't cover yet, a database's own
# template, checked with its rules. In Temper, postgres"…" builds it.
b = QueryBuilder(Dialect.postgres)
b.append_safe("INSERT INTO tags (name) VALUES (")
b.append_string("sql")
b.append_safe(") ON CONFLICT (name) DO NOTHING RETURNING id")
q = b.build()
print("upsert: " + q.render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
# It renders only for its own database.
print("for mysql: " + q.render_problem(Dialect.mysql, PlaceholderStyle.percent_s))
# A common query nests in it, rendered for that database.
b = QueryBuilder(Dialect.postgres)
b.append_safe("SELECT jsonb_agg(x) FROM (")
b.append_query(big.build())
b.append_safe(") AS s(x)")
print("nested: " + b.build().render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
# # starts a comment in MySQL only, so a value after it would vanish.
b = QueryBuilder(Dialect.mysql)
b.append_safe("SELECT * FROM t WHERE a = 1 # ")
b.append_string("x")
print("mysql, after #: " + b.template_problem)
# end snippet

section("9. Quoting by hand")

# snippet: quoting
# For tools that write SQL text themselves, such as DDL defaults. Each
# raises RuntimeError rather than change what it can't write, and a
# _problem function says why.
print("mysql name: " + Dialect.mysql.quote_name("my `table`"))
print("mysql string: " + Dialect.mysql.quote_string("it's \\ fine"))
print("postgres string: " + Dialect.postgres.quote_string("it's \\ fine"))
long_name = "n" * 64
print("postgres, 64-byte name: " + Dialect.postgres.name_problem(long_name))
try:
    Dialect.postgres.quote_string("a\0b")
    print("postgres, NUL in a string: quoted")
except RuntimeError:
    print("postgres, NUL in a string: refused, " + Dialect.postgres.string_problem("a\0b"))
try:
    Identifier.named(long_name)
    print("Identifier, 64 bytes: named")
except RuntimeError:
    print("Identifier, 64 bytes: refused, " + identifier_problem(long_name))
# end snippet

# The tour stops at what the driver gets. The repo's tests/engines run
# these kinds of queries through SQLite, DuckDB, PostgreSQL, and MariaDB.
