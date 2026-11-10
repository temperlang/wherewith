# Tour outline

A draft for review: what Wherewith's tour would cover, in what order, and
what it would print. No code is written yet. The output lines below come
from running the built Python library, first at f3eea57 and again after
the library changes the tour needed (open questions 3, 4, and 5), so
they're what the library prints today, except where a line says
otherwise.

## The goal

A reader should come away knowing:

- **SQL is written once,** in a common dialect that's plain SQL, and
  Wherewith writes it the way each of SQLite, PostgreSQL, MySQL and
  MariaDB, and DuckDB needs it, from any of the seven languages.
- **It means the same everywhere, or it's refused** when the query is
  built, with the line, the column, and why. A query builder or ORM would
  send `a / 2` and get 3 from one database and 3.5 from another; Wherewith
  says so before anything runs.
- **Values never become SQL.** They go to the driver as parameters, in
  whichever placeholder style it takes. Names are quoted for each
  database. There's no way to splice a value into the text by mistake.
- **There's an escape hatch** for SQL the common dialect doesn't cover:
  each database's own template, checked with that database's rules, with
  common queries nesting inside.

The bar: a reader choosing between Wherewith and SQLAlchemy Core, Knex,
Kysely, jOOQ, or SQLGlot should see things none of them do, in every
language, with no setup.

## Steps

Each section prints a `## N. Title` heading, as the other tours do. The
Python sketches use `D` for `Dialect` and `P` for `PlaceholderStyle` only
to keep this outline short; the tour spells them out. SQL lines are
printed as `database: SQL`, in the site's order: SQLite, PostgreSQL,
MySQL, and DuckDB.

**Note:** the `sql` tag exists only in Temper. In the seven languages, a
common query is a `QueryBuilder(Dialect.common)`, with `append_safe` for
SQL text and `append_string`, `append_int`, `append_identifier`, and
`append_query` for holes. So the tour uses the builder from the first
section, and says in a comment that it's what Temper's `sql"…"` does.
(See the open question on a Temper tab.)

### 1. Write it once

The point: one query, as plain SQL with holes for values, written for
every database. Shows `render(Dialect.common, …)` too, the canonical
form, for logs.

API: `QueryBuilder(Dialect.common)`, `append_safe`, `append_int`, `build`,
`render`, `RenderedQuery.sql` and `.params`, and `SqlValue`'s `toString`.

```python
b = QueryBuilder(Dialect.common)
b.append_safe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (")
b.append_int(7); b.append_safe(", "); b.append_int(9)
b.append_safe(") ORDER BY name NULLS LAST LIMIT "); b.append_int(10)
q = b.build()
for name, dialect, style in databases:
    print(f"{name}: {q.render(dialect, style).sql}")
print("params: " + ", ".join(str(v) for v in q.render(Dialect.sqlite, PlaceholderStyle.question).params))
```

```
common: SELECT name, COALESCE(nick, name) AS shown FROM users WHERE id IN (?, ?) ORDER BY name NULLS LAST LIMIT ?
sqlite: SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users" WHERE "id" IN (?, ?) ORDER BY "name" NULLS LAST LIMIT ?
postgres: SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users" WHERE "id" IN ($1, $2) ORDER BY "name" LIMIT $3
mysql: SELECT `name`, COALESCE(`nick`, `name`) AS `shown` FROM `users` WHERE `id` IN (%s, %s) ORDER BY `name` IS NULL, `name` LIMIT %s
duckdb: SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users" WHERE "id" IN ($1, $2) ORDER BY "name" NULLS LAST LIMIT $3
params: 7, 9, 10
```

The last line prints each value with `toString`, which writes it as SQL
would, the same in every language.

A comment explains the one surprise plainly: PostgreSQL already puts
nulls last going up, so it needs no `NULLS LAST`, and MySQL has no
`NULLS`, so it sorts by `name IS NULL` first.

### 2. Values are bound, never spliced

The point: injection can't happen, because the value never enters the
text. Side by side with what string-building sends.

API: `append_string`, `params`, `Identifier.named`, `append_identifier`,
`template_problem`.

```python
name = "Robert'); DROP TABLE students; --"
print("by hand: " + f"SELECT id FROM students WHERE name = '{name}'")
b = QueryBuilder(Dialect.common)
b.append_safe("SELECT id FROM students WHERE name = "); b.append_string(name)
r = b.build().render(Dialect.sqlite, PlaceholderStyle.question)
# A name from outside is an Identifier, quoted, never a value or SQL.
table = Identifier.named('students"; DROP TABLE x; --')
# A hole inside quotes is refused: it would be text, not a value.
b.append_safe("… WHERE name = '"); b.append_string(name); b.append_safe("'")
```

```
by hand: SELECT id FROM students WHERE name = 'Robert'); DROP TABLE students; --'
wherewith: SELECT "id" FROM "students" WHERE "name" = ?
params: 'Robert''); DROP TABLE students; --'
a hostile name: SELECT * FROM "students""; DROP TABLE x; --"
in MySQL: SELECT * FROM `students"; DROP TABLE x; --`
a hole in quotes: hole inside a quote or comment, at line 1, column 39: dents WHERE name = '
```

### 3. Refused when it's built

The point, and the section to blow minds: each of these runs on every
database, and gives different results on some. Wherewith refuses them
when the query is built, with where and why. One line each, with a
plain comment on what goes wrong without it.

API: `template_problem`, which gives the problem `build` would raise
for, before `build` runs; and `append_string(None)`, a null value.

```python
def refused(sql):
    b = QueryBuilder(Dialect.common)
    b.append_safe(sql)
    print(f"{sql}: {b.template_problem or 'built'}")
# And a null value, refused at = as NULL is.
b = QueryBuilder(Dialect.common)
b.append_safe("SELECT a FROM t WHERE b = "); b.append_string(None)
print(f"SELECT a FROM t WHERE b = ${{null}}: {b.template_problem}")
```

```
SELECT a / 2 FROM t: / without a float operand; databases divide integers differently, at line 1, column 10: SELECT a / 2 FROM t
SELECT a FROM t WHERE b = NULL: = NULL is never true; use IS NULL, at line 1, column 25: CT a FROM t WHERE b = NULL
SELECT Name FROM t: bare name not lowercase; quote it to keep its case, at line 1, column 8: SELECT Name FROM t
SELECT a, count(*) AS n FROM t GROUP BY b: a is neither grouped nor aggregated; databases differ, at line 1, column 8: SELECT a, count(*) AS n FRO
SELECT 'a' || 1 + 2 AS x: arithmetic beside || needs parentheses; databases group them differently, at line 1, column 17: SELECT 'a' || 1 + 2 AS x
SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t: CASE mixes text and a number, at line 1, column 38: a > 1 THEN 'x' ELSE 0 END AS c FROM t
SELECT a FROM t WHERE id = ?: ? outside quotes; put values in holes, at line 1, column 28: a FROM t WHERE id = ?
SELECT a FROM t UNION SELECT b FROM u: UNION isn't in the common dialect yet, at line 1, column 17: SELECT a FROM t UNION SELECT b FROM 
SELECT 7 / 2.0 AS x: built
SELECT a FROM t WHERE b = ${null}: = with a null value is never true; use IS NULL, at line 1, column 25: CT a FROM t WHERE b = ${…}
```

The comments say what each would do: `7 / 2` is 3 in SQLite and
PostgreSQL but 3.5 in MySQL and DuckDB; `Name` is `name` to PostgreSQL
but `Name` to the others; SQLite returns any row's `a` for an ungrouped
column; SQLite reads `'a' || 1 + 2` as `('a' || 1) + 2`, PostgreSQL as
`'a' || (1 + 2)`. The `7 / 2.0` line shows the fix for the first. A
null value, whether written `${null}` or from a variable that's null,
is refused where `NULL` would be, since `b = NULL` matches no row on any
database. The `UNION` line trails a space, from the excerpt; pick
another or trim it.

### 4. What differs, handled

The point: what Wherewith writes differently for each database, so the
reader doesn't have to know. Four small queries, each printed for the
four databases.

API: as in section 1.

```
SELECT id || ':' || name AS tag FROM people
sqlite: SELECT "id" || ':' || "name" AS "tag" FROM "people"
postgres: SELECT "id" || ':' || "name" AS "tag" FROM "people"
mysql: SELECT CONCAT(`id`, ':', `name`) AS `tag` FROM `people`
duckdb: SELECT "id" || ':' || "name" AS "tag" FROM "people"
SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people
sqlite: SELECT CAST("score" AS INTEGER) AS "s", CAST("id" AS TEXT) AS "t", LENGTH("name") AS "n" FROM "people"
postgres: SELECT CAST("score" AS BIGINT) AS "s", CAST("id" AS TEXT) AS "t", LENGTH("name") AS "n" FROM "people"
mysql: SELECT CAST(`score` AS SIGNED) AS `s`, CAST(`id` AS CHAR) AS `t`, CHAR_LENGTH(`name`) AS `n` FROM `people`
duckdb: SELECT CAST("score" AS BIGINT) AS "s", CAST("id" AS VARCHAR) AS "t", LENGTH("name") AS "n" FROM "people"
SELECT name FROM people ORDER BY nick DESC OFFSET ${20}
… (OFFSET alone: LIMIT -1 for SQLite, LIMIT 18446744073709551615 for MySQL; NULLS LAST for PostgreSQL and DuckDB)
SELECT ${"hi"} AS greeting
sqlite: SELECT ? AS "greeting"
postgres: SELECT CAST($1 AS TEXT) AS "greeting"
mysql: SELECT %s AS `greeting`
duckdb: SELECT $1 AS "greeting"
```

The third block's lines are to be run (`DESC` and `OFFSET` were each run
alone). Comments: MySQL's `||` means `OR`; MySQL's `LENGTH` counts bytes;
PostgreSQL can't guess a lone parameter's type. Quoting and reserved
words are shown by every line, so no separate query for them.

### 5. Queries in queries

The point: a common query nests in another as a hole, its parameters
numbered with the outer query's, and it's checked again as part of the
whole, with problems placed at its hole.

API: `append_query`.

```python
big = QueryBuilder(Dialect.common)
big.append_safe("SELECT user_id FROM orders WHERE total > "); big.append_int(100)
b = QueryBuilder(Dialect.common)
b.append_safe("SELECT name FROM users WHERE id IN ("); b.append_query(big.build())
b.append_safe(") AND active = "); b.append_string("yes")
```

```
postgres: SELECT "name" FROM "users" WHERE "id" IN (SELECT "user_id" FROM "orders" WHERE "total" > $1) AND "active" = $2
mysql: SELECT `name` FROM `users` WHERE `id` IN (SELECT `user_id` FROM `orders` WHERE `total` > %s) AND `active` = %s
with LIMIT inside: LIMIT in an IN subquery; MySQL refuses it, at line 1, column 37:  users WHERE id IN (${…})
```

### 6. Building queries in code

The point: real queries vary at run time. A search function adds filters
only when given, takes a sort column from the caller as an `Identifier`,
and pages; every variant is still checked. Then `targets`: a query only
for PostgreSQL and SQLite relaxes the checks for the others, and renders
only for those.

API: `QueryBuilder`, `append_identifier`, `targets`, `render_problem`.

```python
def search(word=None, min_total=None, sort="created", page=0):
    b = QueryBuilder(Dialect.common)
    b.append_safe("SELECT id, title FROM orders")
    joiner = " WHERE "
    if word is not None:
        b.append_safe(joiner + "title LIKE "); b.append_string(word)
        b.append_safe(" || '%' ESCAPE '!'"); joiner = " AND "
    ...
```

```
SELECT "id", "title" FROM "orders" ORDER BY "created" NULLS FIRST LIMIT $1 OFFSET $2
SELECT "id", "title" FROM "orders" WHERE "title" LIKE (CAST($1 AS TEXT) || '%') ESCAPE '!' ORDER BY "created" NULLS FIRST LIMIT $2 OFFSET $3
SELECT "id", "title" FROM "orders" WHERE "total" >= $1 ORDER BY "Total" DESC NULLS LAST LIMIT $2 OFFSET $3
for postgres and sqlite: SELECT 'C:\temp' AS "p"
for mysql: common query checked for postgres, sqlite, not mysql
```

### 7. Placeholders for each driver

The point: the placeholder style depends on the driver, not the
database, so it's chosen at render time. `percentS` doubles `%`, and a
named style refuses text holding its marker.

API: `PlaceholderStyle.question`, `dollar_numbered`, `percent_s`,
`at_named`, `colon_named`, `render_problem`.

```
question: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = ?
dollarNumbered: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = $1
percentS: SELECT "name" FROM "users" WHERE "name" LIKE 'a%%' ESCAPE '!' AND "id" = %s
atNamed: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = @p1
colonNamed: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = :p1
colonNamed with 'a:b': text has :, which colonNamed uses
```

### 8. Each database's own SQL

The point: for what the common dialect doesn't cover yet (upserts,
`RETURNING`, JSON), a database's own template, checked with its rules: a
hole must be code, not inside a quote or comment, as that database reads
them. A common query nests in it, rendered for that database. Such a
query renders only for its own database.

API: `QueryBuilder(Dialect.postgres)`, `QueryBuilder(Dialect.mysql)`,
`append_query`, `render_problem`.

```
upsert: INSERT INTO tags (name) VALUES ($1) ON CONFLICT (name) DO NOTHING RETURNING id
for mysql: query checked for postgres, not mysql
nested: SELECT jsonb_agg(x) FROM (SELECT "user_id" FROM "orders" WHERE "total" > $1) AS s(x)
mysql, after #: hole inside a quote or comment
```

The last is `SELECT * FROM t WHERE a = 1 # ${x}`: `#` starts a comment in
MySQL only, so the value would vanish there.

### 9. Quoting by hand

The point: the pieces underneath, for tools that write SQL text
themselves, such as DDL defaults. Each fails rather than changing what
it can't write.

API: `Dialect.quote_name`, `quote_string`, `name_problem`,
`Identifier.named`.

```
mysql name: `my ``table```
mysql string: 'it''s \\ fine'
postgres string: 'it''s \ fine'
postgres, 64-byte name: name longer than 63 UTF-8 bytes
postgres, NUL in a string: refused
Identifier, 64 bytes: refused
```

That's about 76 lines of output, between Ordable's 33 and Hrefine's 143.

## How it differs from the example and the site

- `demos/example/` and the site hero use one query (tasks, `LIKE`,
  paging) and one refusal. The tour doesn't reuse that query; section 1
  uses the README's, and section 6 builds the paging dynamically
  instead.
- The site's three cards (backslashes, long names, nested comments)
  show quoting and lexing rules from tests. The tour touches backslashes
  only through `targets`, and long names only in section 9, in passing.
- The example stays the short "what it looks like"; the tour is "what it
  does", across the whole public API. `demos/README.md`'s line that a
  tour comes later is replaced.

## Per-language notes

- **No tag outside Temper.** Every language uses the builder, so SQL
  text comes in pieces. Lua's `[[…]]`, Rust's `r#"…"#`, and C#'s verbatim
  strings help with `"dueDate"`-style quoted names; C++ and Java escape
  them. The example already settles each language's form.
- **Errors.** `build`, `render`, `Identifier.named`, and the quoting
  methods throw: `RuntimeError` in Python, `RuntimeException` in Java,
  an exception in C# and JavaScript, `error` in Lua (caught with
  `pcall`), `TemperBubble` in C++, and `Err(temper_core::Error)` in
  Rust. None carries a message, so, as Hrefine's tour does with
  `check_url`, the tour prints `template_problem` or `render_problem`
  instead, and its comments name each language's exception, as
  Hrefine's do.
- **`template_problem` before `build`.** It gives every problem
  `build` would raise for, lexing, parsing, and the checks, without
  building (done: open question 3), so the tour's `refused` helper
  doesn't build, and needs no `try` in any language.
- **Nullable strings.** `template_problem` and `render_problem` are
  `String?`: `.value` or `has_value()` in C++, `Option` in Rust
  (`unwrap_or_default`), `nil` in Lua. `append_string` takes
  `Some(word)` in Rust.
- **Profiles are static:** `Dialect::common()` in C++ and Rust, plain
  fields elsewhere.
- **Printing parameters.** `SqlValue`'s `toString` writes each value
  as SQL would (`7`, `'it''s'`, `2.0`, `TRUE`, `NULL`), the same in
  every language (done: open question 4): `str(v)` in Python,
  `toString()` in C++ (`->toString()`), Java, and JavaScript,
  `ToString()` in C#, `v:toString()` in Lua, and `v.to_string()` in
  Rust (an `Arc<String>`).
- **Setting `targets`** takes a list: a Python list, `List.of` in Java,
  a `List` in C#, a JS array, a Temper list in Lua, and a `Vec` or the
  core's list type in Rust; the example doesn't cover it yet, so check
  each language when writing.
- **Words to avoid:** `full`, `first`, and `last` are keywords
  (`full_name` is fine), so the tour's aliases avoid them.

## CI and checking

As for the other libraries and Wherewith's example:

- `demos/tour/{cpp,csharp,java,js,lua,py,rust}` and
  `demos/tour/expected.txt`, built the same way as `demos/example/`.
- `demos/run.py` runs both the example and the tour, per language, and
  compares each with its `expected.txt`; the test workflow's
  "Example" step becomes "Example and tour", after each backend's tests.
- `site/build.py` reads each tour's source and `expected.txt`, and
  fails if a tour or its expected output is missing, as it does for the
  example.

## Open questions

1. **Write it now, or after the check stage (chunk 5)?** The site says
   the tour comes once the checks are complete. The API it uses
   (builder, render, targets, styles) is settled; chunk 5 changes
   messages and adds refusals, which touch only `expected.txt`.
   *Recommended: write it now, and refresh `expected.txt` per chunk.*
2. **A Temper tab?** The `sql` tag is Wherewith's headline, but no
   tour shows it, since the seven programs can't use it. *Recommended:
   add a Temper version as a test in `src/` (as the site's Temper
   snippet is), printing the same lines, shown as a Temper tab after
   the seven, with Python still the default.*
3. **`template_problem` before `build`.** *Done:* it gives every
   problem `build` would raise for, lexing, the template's end, and for
   a common builder the parser and the checks, without building. The
   parse and checks run once per state of the template, shared with
   `build`, and reading it changes nothing, so more can be added after.
4. **`toString` for `SqlValue`.** *Done:* each value as SQL writes it,
   the same in every language: `'Launch'` (with `'` doubled), `7`,
   `2.0`, `TRUE`, and `NULL`.
5. **A null value at `=`.** *Done:* a value hole holding null is
   refused wherever `NULL` written in the text is: comparisons, `IN`
   lists, and `WHEN` in a simple `CASE`, pointing to `IS NULL`. Section
   3 shows it.
6. **Run in your browser.** The other sites run the JS tour in the
   page; Wherewith's site ships no library. *Recommended: yes, as the
   others do (`tourrun.js`, checked in Node at build time); the library
   is pure Temper and small enough.*
7. **Real engines in the tour?** Running the SQL would need a driver per
   language, and identical output is the point. *Recommended: no; the
   tour stops at what the driver gets, and a closing comment points to
   the engine round trips.*
8. **Snippet markers.** Wherewith's site takes blocks between
   `snippet:` and `end snippet`; the other libraries mark single lines
   for a dev mode. *Recommended: blocks, matching Wherewith's example,
   until its site has a dev mode.*
