-- Wherewith's example, from Lua: the same query for each database.
--
-- The same example exists for each language Wherewith supports, and they all
-- print the same text. See demos/README.md for how to run them.

-- snippet: example
local wherewith = require("wherewith")
local Dialect, PlaceholderStyle = wherewith.Dialect, wherewith.PlaceholderStyle
local QueryBuilder = wherewith.QueryBuilder

local word = "Launch"

-- One query, in the common dialect, checked for every database.
local b = QueryBuilder(Dialect.common)
b:appendSafe('SELECT title, "dueDate" FROM tasks WHERE title LIKE ')
b:appendString(word)
b:appendSafe([[ || '%' ESCAPE '!' ORDER BY "dueDate" NULLS LAST LIMIT ]])
b:appendInt(20)
b:appendSafe(" OFFSET ")
b:appendInt(40)
local q = b:build()

-- Rendered for each database, with the placeholders its driver takes.
print("sqlite: " .. q:render(Dialect.sqlite, PlaceholderStyle.question).sql)
print("postgres: " .. q:render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql)
print("mysql: " .. q:render(Dialect.mysql, PlaceholderStyle.percentS).sql)
local r = q:render(Dialect.duckdb, PlaceholderStyle.dollarNumbered)
print("duckdb: " .. r.sql)
-- The values travel apart from the SQL, for the driver to bind.
print("params: " .. #r.params)

-- What databases would read differently is refused, with its place.
local bad = QueryBuilder(Dialect.common)
bad:appendSafe("SELECT title, dueDate FROM tasks")
print("refused: " .. bad.templateProblem) -- and bad:build() raises an error
-- end snippet
