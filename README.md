# Wherewith

Write a query once, in a common SQL dialect, and run it on SQLite,
PostgreSQL, MySQL or MariaDB, and DuckDB, the same in every language.
Wherewith checks that the query means the same on every database, and
renders it for each, with values always bound as parameters, so a value
never becomes SQL. Underneath are the pieces safe composition
frameworks, query builders, and admin tools need: quoting names and
strings the way each database really reads them, and templates for
each database.

**Status: beta**, until Temper's translations reach 1.0. The API may
change.

## Example

In Temper, and the same API in each supported language:

```temper
// One query, checked for every database when the sql tag runs.
let q = sql"SELECT name, coalesce(nick, name) AS shown FROM users
  WHERE id IN (${a}, ${b}) ORDER BY name NULLS LAST LIMIT ${10}";

// Rendered for each, with the placeholders its driver takes.
q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
// SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users"
//   WHERE "id" IN ($1, $2) ORDER BY "name" LIMIT $3
q.render(Dialect.mysql, PlaceholderStyle.question) orelse panic();
// SELECT `name`, COALESCE(`nick`, `name`) AS `shown` FROM `users`
//   WHERE `id` IN (?, ?) ORDER BY `name` IS NULL, `name` LIMIT ?

// What databases would read differently is refused, with its place.
sql"SELECT a / 2 FROM t"; // panics: / without a float operand

// Each database's own templates check its SQL with its rules, for
// what the common dialect doesn't cover.
let name = "Robert'); DROP TABLE students; --";
let p = postgres"SELECT id FROM students WHERE name = ${name}";
p.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
// SELECT id FROM students WHERE name = $1
mysql"SELECT * FROM t WHERE a = '${name}'"; // panics: a value inside quotes

// Names and strings are quoted as each database expects.
Dialect.mysql.quoteName("my `table`");        // `my ``table```
Dialect.mysql.quoteString("it's \\ fine");  // 'it''s \\ fine'
```

Anything that can't be written safely, such as a NUL in a PostgreSQL
string or a 64-byte PostgreSQL name, fails rather than being changed.
See the [design](docs/design.md) for the common dialect and how it
renders for each database, each dialect's rules, with links to the
manuals, which drivers take which placeholders, and what's planned.

## Languages

Made in Temper, Wherewith supports these languages, and its tests run
on each:

- C++
- C\#
- Java
- JavaScript
- Lua
- Python
- Rust

## Development

Written with Claude Code and Opus 5.5.

Run tests with [Temper](https://temperlang.dev/), on one backend while
working:

    temper test -b py

Or on all of them:

    temper test -b cpp -b csharp -b java -b js -b lua -b py -b rust

Round trips through real engines use the Python library, with
[uv](https://docs.astral.sh/uv/) and the drivers in `pyproject.toml`
(psycopg 3, PyMySQL, and DuckDB's own package; SQLite needs only
Python's standard library):

    temper build -b py
    uv run tests/engines/sqlite_roundtrip.py
    uv run tests/engines/duckdb_roundtrip.py
    uv run tests/engines/postgres_roundtrip.py
    uv run tests/engines/mariadb_roundtrip.py

SQLite and DuckDB are embedded, so those run anywhere. The PostgreSQL
and MariaDB runners skip unless a server is reachable,
at `127.0.0.1` on the usual port by default; each script's
documentation lists the variables that change that. Each also runs the
common dialect's shared corpus (`common_corpus.py`): the same queries,
rendered for that engine, giving the same rows, but where the design
documents a difference, and random ones checked against SQLite.

CI runs the tests on every backend for pull requests and pushes to
`main`, using Temper's nightly `dev` build, and the round trips with
Python 3.11: SQLite and DuckDB in the `py` job, and PostgreSQL and
MariaDB as service containers in the `engines` job. Source files in
`src/` are literate Markdown: `core.temper.md` has what every dialect
shares, `query.temper.md` the query and its builder,
and each database has its own file (`sqlite`, `postgres`, `mysql`, and
`duckdb`) with its tag and template lexer, with tests beside them in
`-tests` files.

The same common query, built from each language and rendered for each
database, is in [`demos/example/`](demos/README.md), and CI checks that
every one prints the same text.

### Site

[The site](site/) is one static page: a common query and what each
database's driver gets, where dialects differ, the same query in Temper
and in each language, why Wherewith, and each driver's placeholders.
Its code and SQL come from the example and the Temper tests, and its
table from the design notes, so it can't drift from them. Build and preview it:

    npm ci --prefix site
    uv run site/build.py
    python3 -m http.server --bind 127.0.0.1 -d site/build

## License

Apache-2.0 OR MIT, at your option, as Temper is; see [COPYRIGHT](COPYRIGHT). Third-party material, with its notices, is in [NOTICE](NOTICE).
