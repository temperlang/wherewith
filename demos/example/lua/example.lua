-- Wherewith's example, from Lua: one query, rendered for each database.
--
-- The same example exists for each language Wherewith supports, and they all
-- print the same text. See demos/README.md for how to run them.

-- snippet: example
local wherewith = require("wherewith")
local Dialect, Identifier = wherewith.Dialect, wherewith.Identifier
local PlaceholderStyle, QueryBuilder = wherewith.PlaceholderStyle, wherewith.QueryBuilder

local name = "Robert'); DROP TABLE students; --"
local b = QueryBuilder(Dialect.postgres)
b:appendSafe("SELECT id FROM ")
b:appendIdentifier(Identifier.named("students"))
b:appendSafe(" WHERE name = ")
b:appendString(name)
local q = b:build()

-- Each database's quoting, with the placeholders its driver takes.
print("sqlite: " .. q:render(Dialect.sqlite, PlaceholderStyle.question).sql)
print("postgres: " .. q:render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql)
print("mysql: " .. q:render(Dialect.mysql, PlaceholderStyle.percentS).sql)
local r = q:render(Dialect.duckdb, PlaceholderStyle.dollarNumbered)
print("duckdb: " .. r.sql)
-- The name travels apart from the SQL, for the driver to bind.
print("params: " .. #r.params)

-- A value inside quotes is refused, not guessed at.
local bad = QueryBuilder(Dialect.postgres)
bad:appendSafe("SELECT id FROM students WHERE name = '")
bad:appendString(name)
bad:appendSafe("'")
print("refused: " .. bad.templateProblem) -- and bad:build() raises an error
-- end snippet
