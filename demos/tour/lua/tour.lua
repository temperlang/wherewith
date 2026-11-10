-- A tour of Wherewith's whole public API, from Lua.
--
-- The same tour exists for each language Wherewith supports, and they all
-- print the same text. See demos/README.md for how to run them.

-- snippet: setup
local wherewith = require("wherewith")
local Dialect, Identifier = wherewith.Dialect, wherewith.Identifier
local PlaceholderStyle, QueryBuilder = wherewith.PlaceholderStyle, wherewith.QueryBuilder
local identifierProblem = wherewith.identifierProblem
-- Temper's runtime gives temper.null, not nil, for no value. It's a
-- table, so it's truthy; null_to_nil turns it into nil.
local null_to_nil = require("temper-core").null_to_nil

-- Each database, with a placeholder style its drivers take.
local databases = {
  { "sqlite", Dialect.sqlite, PlaceholderStyle.question },
  { "postgres", Dialect.postgres, PlaceholderStyle.dollarNumbered },
  { "mysql", Dialect.mysql, PlaceholderStyle.percentS },
  { "duckdb", Dialect.duckdb, PlaceholderStyle.dollarNumbered },
}

local function forEachDatabase(q)
  for _, db in ipairs(databases) do
    print(db[1] .. ": " .. q:render(db[2], db[3]).sql)
  end
end

-- Values as SQL would write them, joined.
local function shown(values)
  local out = {}
  for i, v in ipairs(values) do
    out[i] = v:toString()
  end
  return table.concat(out, ", ")
end

-- A common query is a QueryBuilder for Dialect.common: SQL text with
-- appendSafe, and values, names, and other queries in holes between. In
-- Temper, sql"…" builds the same.
local function common(text)
  local b = QueryBuilder(Dialect.common)
  b:appendSafe(text)
  return b
end
-- end snippet

local function section(title)
  print()
  print("## " .. title)
end

print("# Wherewith tour")

section("1. Write it once")

-- snippet: write-once
local b = QueryBuilder(Dialect.common)
b:appendSafe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (")
b:appendInt(7)
b:appendSafe(", ")
b:appendInt(9)
b:appendSafe(") ORDER BY name NULLS LAST LIMIT ")
b:appendInt(10)
local q = b:build() -- raises an error if the query is refused

-- Rendered for Dialect.common, it's the canonical form, for logs.
print("common: " .. q:render(Dialect.common, PlaceholderStyle.question).sql)
-- PostgreSQL already sorts nulls last going up, so it needs no NULLS LAST,
-- and MySQL has no NULLS, so it sorts by name IS NULL first.
forEachDatabase(q)
-- Values print as SQL would write them, for reading only.
print("params: " .. shown(q.params))
-- end snippet

section("2. Values are bound, never spliced")

-- snippet: bound
local name = "Robert'); DROP TABLE students; --"
-- Building SQL by hand puts the value in the text, where it ends the
-- string early and adds a statement of its own.
print("by hand: SELECT id FROM students WHERE name = '" .. name .. "'")
-- A hole sends the value apart from the SQL, for the driver to bind.
b = common("SELECT id FROM students WHERE name = ")
b:appendString(name)
local r = b:build():render(Dialect.sqlite, PlaceholderStyle.question)
print("wherewith: " .. r.sql)
print("params: " .. shown(r.params))

-- A name from outside is an Identifier, quoted for each database, never
-- a value or SQL.
b = common("SELECT * FROM ")
b:appendIdentifier(Identifier.named('students"; DROP TABLE x; --'))
q = b:build()
print("a hostile name: " .. q:render(Dialect.sqlite, PlaceholderStyle.question).sql)
print("in MySQL: " .. q:render(Dialect.mysql, PlaceholderStyle.percentS).sql)

-- A hole inside quotes is refused: it would be text, not a value.
b = common("SELECT id FROM students WHERE name = '")
b:appendString(name)
b:appendSafe("'")
print("a hole in quotes: " .. b.templateProblem)
-- end snippet

section("3. Refused when it's built")

-- snippet: refused
-- Each of these runs on every database, and gives different results on
-- some. templateProblem says why build would refuse it, and where.
local function refused(sql)
  print(sql .. ": " .. (null_to_nil(common(sql).templateProblem) or "built"))
end

-- 7 / 2 is 3 in SQLite and PostgreSQL, and 3.5 in MySQL and DuckDB.
refused("SELECT a / 2 FROM t")
-- b = NULL matches no row: NULL isn't equal to anything, even NULL.
refused("SELECT a FROM t WHERE b = NULL")
-- PostgreSQL reads Name as name; the others keep its case.
refused("SELECT Name FROM t")
-- SQLite gives any row's a; the others refuse the query.
refused("SELECT a, count(*) AS n FROM t GROUP BY b")
-- SQLite reads ('a' || 1) + 2, PostgreSQL 'a' || (1 + 2).
refused("SELECT 'a' || 1 + 2 AS x")
-- Some databases turn 0 into text, and others refuse it.
refused("SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t")
-- A placeholder in the text would shift every value's place.
refused("SELECT a FROM t WHERE id = ?")
-- What isn't in the common dialect yet is refused too.
refused("SELECT 1 AS a UNION SELECT 2")
-- The fix for the first: a float operand divides the same everywhere.
refused("SELECT 7 / 2.0 AS x")
-- A null value is refused where NULL would be.
b = common("SELECT a FROM t WHERE b = ")
b:appendString(nil)
print("SELECT a FROM t WHERE b = ${null}: " .. b.templateProblem)
-- end snippet

section("4. What differs, handled")

-- snippet: differs
-- MySQL's || means OR, so it's CONCAT there.
local text = "SELECT id || ':' || name AS tag FROM people"
print(text)
forEachDatabase(common(text):build())
-- Each database names its types differently, and MySQL's LENGTH counts
-- bytes, not characters.
text = "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people"
print(text)
forEachDatabase(common(text):build())
-- Where nulls sort differs, and so does OFFSET without LIMIT.
b = common("SELECT name FROM people ORDER BY nick DESC OFFSET ")
b:appendInt(20)
print("SELECT name FROM people ORDER BY nick DESC OFFSET ${20}")
forEachDatabase(b:build())
-- PostgreSQL can't guess a lone parameter's type, so it gets a cast.
b = common("SELECT ")
b:appendString("hi")
b:appendSafe(" AS greeting")
print('SELECT ${"hi"} AS greeting')
forEachDatabase(b:build())
-- end snippet

section("5. Queries in queries")

-- snippet: nested
local big = common("SELECT user_id FROM orders WHERE total > ")
big:appendInt(100)
b = common("SELECT name FROM users WHERE id IN (")
b:appendQuery(big:build())
b:appendSafe(") AND active = ")
b:appendString("yes")
q = b:build()
-- The inner query's parameters are numbered with the outer query's.
print("postgres: " .. q:render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql)
print("mysql: " .. q:render(Dialect.mysql, PlaceholderStyle.percentS).sql)
-- And it's checked again as part of the whole, with problems at its hole.
local inner = common("SELECT user_id FROM orders LIMIT ")
inner:appendInt(5)
b = common("SELECT name FROM people WHERE id IN (")
b:appendQuery(inner:build())
b:appendSafe(")")
print("with LIMIT inside: " .. b.templateProblem)
-- end snippet

section("6. Building queries in code")

-- snippet: dynamic
-- Filters only when given, a sort column from the caller, and a page.
-- Every variant is still checked when it's built.
local function search(options)
  local b = common("SELECT id, title FROM orders")
  local joiner = " WHERE "
  if options.word ~= nil then
    b:appendSafe(joiner .. "title LIKE ")
    b:appendString(options.word)
    b:appendSafe(" || '%' ESCAPE '!'")
    joiner = " AND "
  end
  if options.minTotal ~= nil then
    b:appendSafe(joiner .. "total >= ")
    b:appendInt(options.minTotal)
  end
  b:appendSafe(" ORDER BY ")
  b:appendIdentifier(options.sort or Identifier.named("created"))
  b:appendSafe(options.descending and " DESC LIMIT " or " LIMIT ")
  b:appendInt(20)
  b:appendSafe(" OFFSET ")
  b:appendInt((options.page or 0) * 20)
  return b:build():render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql
end

print(search({}))
print(search({ word = "Launch" }))
print(search({ minTotal = 100, sort = Identifier.named("Total"), descending = true, page = 2 }))

-- A query for fewer databases relaxes the checks for the others: MySQL
-- reads \ in a string as an escape, so it's refused only while MySQL is
-- a target. The query renders only for its targets.
b = QueryBuilder(Dialect.common)
b.targets = { Dialect.postgres, Dialect.sqlite }
b:appendSafe([[SELECT 'C:\temp' AS p]])
q = b:build()
print("for postgres and sqlite: " .. q:render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql)
print("for mysql: " .. q:renderProblem(Dialect.mysql, PlaceholderStyle.percentS))
-- end snippet

section("7. Placeholders for each driver")

-- snippet: placeholders
-- The placeholder style depends on the driver, not the database, so it's
-- chosen when rendering. percentS doubles %, for drivers that fill in
-- values with Python's % formatting.
b = common("SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ")
b:appendInt(1)
q = b:build()
local styles = {
  PlaceholderStyle.question,
  PlaceholderStyle.dollarNumbered,
  PlaceholderStyle.percentS,
  PlaceholderStyle.atNamed,
  PlaceholderStyle.colonNamed,
}
for _, style in ipairs(styles) do
  print(style:toString() .. ": " .. q:render(Dialect.sqlite, style).sql)
end
-- A named style refuses text holding its marker, which a driver could
-- misread as a name.
b = common("SELECT 'a:b' AS s FROM users WHERE id = ")
b:appendInt(1)
print("colonNamed with 'a:b': " .. b:build():renderProblem(Dialect.sqlite, PlaceholderStyle.colonNamed))
-- end snippet

section("8. Each database's own SQL")

-- snippet: own-sql
-- For SQL the common dialect doesn't cover yet, a database's own
-- template, checked with its rules. In Temper, postgres"…" builds it.
b = QueryBuilder(Dialect.postgres)
b:appendSafe("INSERT INTO tags (name) VALUES (")
b:appendString("sql")
b:appendSafe(") ON CONFLICT (name) DO NOTHING RETURNING id")
q = b:build()
print("upsert: " .. q:render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql)
-- It renders only for its own database.
print("for mysql: " .. q:renderProblem(Dialect.mysql, PlaceholderStyle.percentS))
-- A common query nests in it, rendered for that database.
b = QueryBuilder(Dialect.postgres)
b:appendSafe("SELECT jsonb_agg(x) FROM (")
b:appendQuery(big:build())
b:appendSafe(") AS s(x)")
print("nested: " .. b:build():render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql)
-- # starts a comment in MySQL only, so a value after it would vanish.
b = QueryBuilder(Dialect.mysql)
b:appendSafe("SELECT * FROM t WHERE a = 1 # ")
b:appendString("x")
print("mysql, after #: " .. b.templateProblem)
-- end snippet

section("9. Quoting by hand")

-- snippet: quoting
-- For tools that write SQL text themselves, such as DDL defaults. Each
-- raises an error rather than change what it can't write, which pcall
-- catches, and a ...Problem method says why.
print("mysql name: " .. Dialect.mysql:quoteName("my `table`"))
print("mysql string: " .. Dialect.mysql:quoteString([[it's \ fine]]))
print("postgres string: " .. Dialect.postgres:quoteString([[it's \ fine]]))
local longName = string.rep("n", 64)
print("postgres, 64-byte name: " .. Dialect.postgres:nameProblem(longName))
if pcall(Dialect.postgres.quoteString, Dialect.postgres, "a\0b") then
  print("postgres, NUL in a string: quoted")
else
  print("postgres, NUL in a string: refused, " .. Dialect.postgres:stringProblem("a\0b"))
end
if pcall(Identifier.named, longName) then
  print("Identifier, 64 bytes: named")
else
  print("Identifier, 64 bytes: refused, " .. identifierProblem(longName))
end
-- end snippet

-- The tour stops at what the driver gets. The repo's tests/engines run
-- these kinds of queries through SQLite, DuckDB, PostgreSQL, and MariaDB.
