# Wherewith Design

Wherewith writes SQL text safely for SQLite, PostgreSQL, and MySQL or
MariaDB, the same in every language Temper supports. It's small on
purpose: the pieces a safe-composition framework, a query builder, or
an admin tool needs underneath, done right per dialect.

## Goals

- **Quoting that's right per dialect:** names (identifiers) and string
  literals, including hostile input, with a clear failure where a value
  can't be written safely, never a guess.
- **Templates that bind values as parameters:** a tagged template's
  holes become parameters with typed values, so values never enter the
  SQL text. Names and nested queries are the only holes written as
  text.
- **Syntax whitelists:** types for the SQL a user may pick that can't
  be a parameter (a column type, a sort direction, a comparison, a
  function), each with a private constructor and a fixed list of
  allowed values.
- **The same behavior in C++, C#, Java, JavaScript, Lua, Python, and
  Rust**, in pure Temper, with no connected (native) code.

## Non-goals

- A SQL parser, a query builder, or an ORM. Template text is lexed only
  enough to find quotes, comments, and stray parameters.
- Translating SQL between dialects.
- Claims of conformance to the SQL standard. Wherewith follows what the
  three databases actually do, as their manuals describe and, later,
  as tests against the real engines show.
- Other databases, for now (SQL Server, Oracle, DuckDB, and others).

## Model: a shared core plus profiles

The three databases agree on a core, which Wherewith uses by default:

- Names are delimited with `"…"`, and `"` inside is doubled.
- Strings are delimited with `'…'`, and `'` inside is doubled.

A *Dialect* is a profile that overrides only where its database
differs. Wherewith always writes the one form that's safe in every
setting of its database, rather than the shortest form for one
setting.

| | SQLite | PostgreSQL | MySQL and MariaDB |
| --- | --- | --- | --- |
| Names | `"…"`, `""` | `"…"`, `""` | `` `…` ``, with `` ` `` doubled (works with or without `ANSI_QUOTES`) |
| Name limits | none | 63 bytes, longer truncated (rejected here) | 64 characters, no NUL, nothing above U+FFFF, no trailing space |
| Strings | `'…'`, `''` | `'…'`, `''` | `'…'`, `''` |
| Backslash in strings | plain | plain, with `standard_conforming_strings` on (the default since 9.1) | an escape, unless `NO_BACKSLASH_ESCAPES` |
| NUL in strings | ends the SQL text: rejected | not allowed in text: rejected | `\0` (rejected under `NO_BACKSLASH_ESCAPES`) |
| Other string forms | none | `E'…'`, `U&'…'`, `$$…$$` (never written) | `"…"` strings without `ANSI_QUOTES` (never written) |
| Comments | `--`, `/* */` | `--`, `/* */` (nested) | `-- ` (with a space), `#`, `/* */` |
| Parameters in SQL | `?`, `?1`, `:a`, `@a`, `$a` | `$1` (server side) | `?` (server side) |

Sources: SQLite's [keywords and quoting](https://www.sqlite.org/lang_keywords.html),
[expressions and parameters](https://www.sqlite.org/lang_expr.html),
and [quirks](https://www.sqlite.org/quirks.html); PostgreSQL's
[lexical structure](https://www.postgresql.org/docs/current/sql-syntax-lexical.html)
and [`standard_conforming_strings`](https://www.postgresql.org/docs/current/runtime-config-compatible.html);
MySQL's [string literals](https://dev.mysql.com/doc/refman/8.4/en/string-literals.html),
[identifiers](https://dev.mysql.com/doc/refman/8.4/en/identifiers.html),
[identifier length](https://dev.mysql.com/doc/refman/8.4/en/identifier-length.html),
[comments](https://dev.mysql.com/doc/refman/8.4/en/comments.html), and
[SQL modes](https://dev.mysql.com/doc/refman/8.4/en/sql-mode.html);
MariaDB's [string literals](https://mariadb.com/kb/en/string-literals/),
[identifier names](https://mariadb.com/kb/en/identifier-names/), and
[SQL modes](https://mariadb.com/kb/en/sql-mode/).

Notes on each:

- **SQLite** accepts a `"…"` that names no column as a string, for
  compatibility. A quoted name with a typo then reads as text instead
  of failing. Drivers can turn that off (`SQLITE_DBCONFIG_DQS_DML` and
  `SQLITE_DBCONFIG_DQS_DDL`), and adapters should.
- **PostgreSQL** with `standard_conforming_strings` off reads `\'` in
  a plain string as an escaped quote, which would make quoting unsafe.
  Wherewith assumes it's on, as it has been by default since 9.1.
- **MySQL and MariaDB:** the `mysql` profile doubles `'` and escapes
  `\`, NUL, and Ctrl-Z with a backslash. In the default mode that reads
  back exactly; under `NO_BACKSLASH_ESCAPES` the string still ends in
  the same place, and only reads back with extra backslashes. The
  `mysqlNoBackslashEscapes` profile reads back exactly there, but is
  unsafe without that mode, so it's only for servers known to use it.
  Both assume a `utf8mb4` connection character set; some older
  multi-byte sets (such as GBK) can hide a quote in a character's
  second byte.

Every profile rejects names that are empty or hold NUL, and strings and
names with lone surrogates (possible only where strings are UTF-16),
since they have no UTF-8 form.

## API

Done:

- `Dialect`, with profiles `Dialect.sqlite`, `Dialect.postgresql`,
  `Dialect.mysql`, and `Dialect.mysqlNoBackslashEscapes` (private
  constructor). Methods: `quoteName` and `quoteString`, which bubble on
  bad input, and `nameProblem` and `stringProblem`, which say why.
- `Identifier.named(name)`: a name that quotes safely in every dialect,
  for template holes.
- The `sqlite` tag: `sqlite"SELECT * FROM t WHERE a = ${x}"` gives a
  `SqliteQuery` with `sql` (`?` for each value) and `params`, a list of
  `SqlValue` (`SqlText`, `SqlInt`, `SqlFloat`, `SqlBool`, or
  `SqlNull`). Holes take values, an `Identifier` (written quoted), or
  another `SqliteQuery` (written as SQL, with its parameters). Template
  mistakes (a hole in quotes or a comment, `?` or `:a` in the text, or
  text ending in a quote) panic; `SqliteBuilder.build` bubbles instead.

Planned:

- `postgresql` and `mysql` tags, each with its own query type, so one
  dialect's query can't nest in another's.
- More value types: bytes, dates and times, and lists for `IN (…)`
  (one parameter each).
- Whitelists, each a class with a private constructor, a fixed list,
  and a `parse` that returns null for anything else: `SortDirection`,
  `NullsOrder`, `ComparisonOperator`, `ColumnType` per dialect,
  `ForeignKeyAction`, and `SqlFunction` (a short list of scalar
  functions). In a template they're written as SQL.

## Parameters per driver

The query keeps text and values apart; a driver adapter binds each
value with the driver's own type. Placeholder syntax depends on the
driver, not only the database:

| Language | SQLite | PostgreSQL | MySQL and MariaDB |
| --- | --- | --- | --- |
| C++ | `sqlite3`: `?` | `libpq`: `$1` | Connector/C: `?` |
| C# | `Microsoft.Data.Sqlite`: `$a`, `@a`, `:a` | Npgsql: `$1` or `@a` | MySqlConnector: `?` or `@a` |
| Java | JDBC: `?` | JDBC: `?` | JDBC: `?` |
| JavaScript | `node:sqlite`, `better-sqlite3`: `?` | `pg`: `$1` | `mysql2`: `?` |
| Lua | `lsqlite3`: `?` | LuaSQL: none (quoting only) | LuaSQL: none (quoting only) |
| Python | `sqlite3`: `?` | psycopg: `%s` (literal `%` doubled); asyncpg: `$1` | PyMySQL, mysqlclient: `%s`; MariaDB Connector: `?` |
| Rust | `rusqlite`: `?` | `tokio-postgres`, `sqlx`: `$1` | `mysql`, `sqlx`: `?` |

So a query will keep its text as parts between parameters, and render
them in a chosen style: `?`, `$1`, `%s` (doubling `%` in the text), or
named `@p1`. The SQLite slice writes `?` directly; C#'s
`Microsoft.Data.Sqlite` needs named parameters, so it will need a
named style. These are from the drivers' docs and need checking in the
differential tests. Where a driver has no parameters (LuaSQL), quoting
is the fallback, which is why `quoteString` exists.

## Testing

- **Unit tests in Temper**, next to the code, run on every backend:
  each profile's quoting with hostile input (quotes, backslashes, NUL,
  Ctrl-Z, line breaks, comment starts, characters above U+FFFF, lone
  surrogates where a language can make them, and very long text), name
  limits, and template mistakes.
- **Differential tests, later:** run each quoted string and name
  through real SQLite, PostgreSQL, and MariaDB (and MySQL), in each
  relevant SQL mode, and check it reads back exactly or fails as
  expected; check `NO_BACKSLASH_ESCAPES`, `ANSI_QUOTES`, and
  `standard_conforming_strings` both ways; and bind template parameters
  through each language's drivers above. Generated hostile strings
  (fuzzing) can feed the same checks.

## Open questions

1. **Tag names:** `sqlite`, `postgresql`, and `mysql`, or names that
   can't clash with other libraries' tags, such as `sqliteQuery`?
2. **NUL in SQLite strings:** reject (now), or write an expression
   such as `'a'||char(0)||'b'` where an expression is allowed?
3. **PostgreSQL with `standard_conforming_strings` off:** assume on
   (now), or also reject strings with backslashes, safe either way?
4. **Empty names:** rejected everywhere now, though SQLite accepts
   `""`. Keep that?
5. **MariaDB:** share the MySQL profiles (now), or get its own, for
   differences such as its `SQL_MODE=ORACLE`?
6. **Template mistakes:** panic when the tag is used (now), or make
   every template bubble, which Rust would see as a `Result`?
7. **Placeholder styles:** chosen when rendering (planned), or fixed
   per dialect?
8. **Whitelists:** which lists first, and how strict per dialect
   (`ColumnType` differs the most)?
