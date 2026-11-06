# Wherewith

Writes SQL safely for SQLite, PostgreSQL, and MySQL or MariaDB, the
same in every language: quoting names and strings the way each database
really reads them, and templates that bind values as parameters, so a
value never becomes SQL. It's designed to sit underneath safe
composition frameworks, query builders, and admin tools.

**Status: beta**, until Temper's translations reach 1.0. The API may
change.

## Example

In Temper, and the same API in each supported language:

```temper
// Values are bound as parameters, never written into the SQL.
let name = "Robert'); DROP TABLE students; --";
let q = postgres"SELECT id FROM students WHERE name = ${name}";
q.params; // [SqlText(name)]

// The placeholder style depends on the driver, so it's chosen when
// rendering: ?, $1, %s, @p1, or :p1.
let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
r.sql;    // SELECT id FROM students WHERE name = $1, or = %s for psycopg

// Templates for SQLite, PostgreSQL, and MySQL each check the SQL text
// with that database's rules, and plain code can use a QueryBuilder.
mysql"SELECT * FROM t WHERE a = '${name}'"; // panics: a value inside quotes

// Names are quoted as each database expects.
Dialect.postgres.quoteName("my \"table\"");   // "my ""table"""
Dialect.mysql.quoteName("my `table`");        // `my ``table```

// Where SQL has to be text, strings are quoted per dialect too.
Dialect.sqlite.quoteString("it's \\ fine"); // 'it''s \ fine'
Dialect.mysql.quoteString("it's \\ fine");  // 'it''s \\ fine'
```

Anything that can't be written safely, such as a NUL in a PostgreSQL
string or a 64-byte PostgreSQL name, fails rather than being changed.
See the [design](docs/design.md) for each dialect's rules, with links to
the manuals, which drivers take which placeholders, and what's planned,
such as whitelists for syntax users may pick, like column types.

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

CI runs the tests on every backend for pull requests and pushes to
`main`, using Temper's nightly `dev` build. Source files in `src/` are
literate Markdown: `core.temper.md` has what every dialect shares,
`query.temper.md` the dialect-neutral query and its builder, and each
database has its own file (`sqlite`, `postgres`, and `mysql`) with its
tag and template lexer, with tests beside them in `-tests` files.

## License

Apache-2.0 OR MIT, at your option, as Temper is; see [COPYRIGHT](COPYRIGHT). Third-party material, with its notices, is in [NOTICE](NOTICE).
