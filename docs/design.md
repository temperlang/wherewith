# Wherewith Design

Wherewith writes SQL text safely for SQLite, PostgreSQL, MySQL or
MariaDB, and DuckDB, the same in every language Temper supports. It's small on
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
  databases actually do, as their manuals describe and, later,
  as tests against the real engines show.
- Other databases, for now. SQL Server is planned next, then Oracle
  and Db2.

## Model: a shared core plus profiles

The databases agree on a core, which Wherewith uses by default:

- Names are delimited with `"…"`, and `"` inside is doubled.
- Strings are delimited with `'…'`, and `'` inside is doubled.

A *Dialect* is a profile that overrides only where its database
differs. Wherewith always writes the one form that's safe in every
setting of its database, rather than the shortest form for one
setting.

| | SQLite | PostgreSQL | MySQL and MariaDB | DuckDB |
| --- | --- | --- | --- | --- |
| Names | `"…"`, `""` | `"…"`, `""` | `` `…` ``, with `` ` `` doubled (works with or without `ANSI_QUOTES`) | `"…"`, `""` (also `` `…` ``) |
| Name limits | none | 63 bytes, longer truncated (rejected here) | 64 characters, no NUL, nothing above U+FFFF, no trailing whitespace, no `#mysql50#` prefix | none, but matched without regard to ASCII case |
| Strings | `'…'`, `''` | `'…'`, `''` | `'…'`, `''` | `'…'`, `''` |
| Backslash in strings | plain | plain, with `standard_conforming_strings` on (the default since 9.1) | an escape, unless `NO_BACKSLASH_ESCAPES` | plain, with no setting |
| NUL in strings | ends the SQL text: rejected | not allowed in text: rejected | `\0` (rejected under `NO_BACKSLASH_ESCAPES`) | ends SQL text in the C API: rejected |
| Other string forms | none | `E'…'`, `U&'…'`, `$$…$$` (never written) | `"…"` strings without `ANSI_QUOTES` (never written) | `E'…'`, `$$…$$` (never written) |
| Comments | `--` (to `\n`), `/* */` | `--` (to `\n` or `\r`), `/* */` (nested) | `-- ` (with a space or control character), `#` (both to `\n`), `/* */` | `--` (to `\n` or `\r`), `/* */` (nested) |
| Parameters in SQL | `?`, `?1`, `:a`, `@a`, `$a` | `$1` (server side) | `?` (server side) | `?`, `?1`, `$1`, `$a` |

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
[SQL modes](https://mariadb.com/kb/en/sql-mode/); DuckDB's
[keywords and identifiers](https://duckdb.org/docs/current/sql/dialect/keywords_and_identifiers),
[literal types](https://duckdb.org/docs/current/sql/data_types/literal_types),
[SQL introduction](https://duckdb.org/docs/current/sql/introduction)
(comments), and [prepared statements](https://duckdb.org/docs/current/sql/query_syntax/prepared_statements).
DuckDB's manual doesn't say whether block comments nest, where a line
comment ends, which names `?1` and `$a` are, or how its Unicode spaces
work (below), so those come from DuckDB 2.0's own behavior, which its
round trip checks.

Notes on each:

- **SQLite** accepts a `"…"` that names no column as a string, for
  compatibility. A quoted name with a typo then reads as text instead
  of failing. Drivers can turn that off (`SQLITE_DBCONFIG_DQS_DML` and
  `SQLITE_DBCONFIG_DQS_DDL`), and adapters should. SQLite also
  reserves table, index, view, and trigger names starting with
  `sqlite_`, in any case and however they're quoted; columns may use
  them.
- **PostgreSQL** with `standard_conforming_strings` off reads `\'` in
  a plain string as an escaped quote, which would make quoting unsafe.
  Wherewith assumes it's on, as it has been by default since 9.1, and
  doesn't also reject backslashes; adapters can check it with `SHOW
  standard_conforming_strings`.
- **MySQL and MariaDB:** the `mysql` profile doubles `'` and escapes
  `\`, NUL, and Ctrl-Z with a backslash. In the default mode that reads
  back exactly; under `NO_BACKSLASH_ESCAPES` the string still ends in
  the same place, and only reads back with extra backslashes. The
  `mysqlNoBackslashEscapes` profile reads back exactly there, but is
  unsafe without that mode, so it's only for servers known to use it.
  Both assume a `utf8mb4` connection character set; some older
  multi-byte sets (such as GBK) can hide a quote in a character's
  second byte.
- **DuckDB** lexes as PostgreSQL does, with `standard_conforming_strings`
  always on, plus backtick names. Its text can hold NUL, but its C API
  ends SQL text there, so the profile rejects it. It matches names
  without regard to ASCII case, even quoted, so `"A"` and `"a"` clash.
  Before parsing, it turns 18 Unicode spaces (U+00A0, U+2000 to U+200B,
  U+202F, U+205F, U+2060, U+3000, and U+FEFF) into plain spaces, in a
  simpler pass that skips `'…'`, `"…"`, dollar quotes, and line
  comments, but reads block comments, backtick names, and `E'…'`
  escapes as code. A quote there puts the pass out of step, and from
  then on it changes spaces inside later strings and names, and leaves
  them alone in code, where they're whitespace to the parser (changing
  whether `E'` starts an escape string, say). The `duckdb` lexer
  follows the pass and refuses templates that put it out of step, and
  Unicode spaces it would change inside a quote; `quoteString` and
  `quoteName` output is safe wherever the pass is in step. Parser
  extensions that replace DuckDB's parser aren't covered.

Every profile rejects names that are empty or hold NUL, and strings and
names with lone surrogates (possible only where strings are UTF-16),
since they have no UTF-8 form.

## API

Done:

- `Dialect`, with profiles `Dialect.sqlite`, `Dialect.postgres`,
  `Dialect.mysql`, `Dialect.mysqlNoBackslashEscapes`, and
  `Dialect.duckdb` (private constructor). Methods: `quoteName` and `quoteString`, which bubble on
  bad input, and `nameProblem` and `stringProblem`, which say why.
- `Identifier.named(name)`: a name that quotes safely in every dialect,
  for template holes.
- `Query`: a query for one dialect, as a list of parts: `QueryText`
  (SQL text), `QueryParam` (a `SqlValue`: `SqlText`, `SqlInt`,
  `SqlFloat`, `SqlBool`, or `SqlNull`), and `QueryName` (an
  `Identifier`). A nested query's parts go in place, so parameters
  number straight through. `dialect` is the dialect whose lexing rules
  checked its text, and `params` lists the values in order. Its
  constructor is private: queries come from a `QueryBuilder` or a tag,
  which check their text, or from `Query.unchecked(dialect, parts)`,
  which skips every check and is named so it's plainly unsafe for
  untrusted text.
  It takes any list of parts, even a `ListBuilder`, and keeps its own
  copy, so later changes to the caller's list can't make the parts
  and `params` disagree.
  Temper's private constructors are still public in some backends, a
  known limitation, so `new Query(dialect, parts)` may be callable
  there, with the same danger.
- `Query.render(dialect, style)` gives a `RenderedQuery`, with `sql`
  and `params`: names quoted for the dialect, and each parameter
  written in a `PlaceholderStyle`, chosen at render time: `question`
  (`?`), `dollarNumbered` (`$1`), `percentS` (`%s`, doubling every `%`
  in the text and names), `atNamed` (`@p1`), or `colonNamed` (`:p1`).
  It bubbles for a dialect other than the query's, since the same text
  can read differently there, and for a named style whose marker is
  anywhere in the text; `renderProblem` says why. The two MySQL
  profiles share their queries, since they check templates with the
  same lexer, which refuses text the two modes read differently.
  `render` keeps its dialect argument for a portable dialect, later,
  whose queries could render for several databases. Where a hole meets
  text it could merge with (`5-` and `-1`, `a` and `$1`, or two quoted
  names), rendering adds a space.
- `QueryBuilder(dialect)`: makes a query from plain code, checking its
  text with that dialect's lexing rules: `appendSafe` for trusted SQL
  text, `append` overloads for values, `SqlValue`, `Identifier`, and
  `Query` (of the same dialect, as for rendering), and `build`, which
  bubbles on a mistake, with `templateProblem` saying why.
- The `sqlite`, `postgres`, `mysql`, and `duckdb` tags (`SqliteTag`,
  `PostgresTag`, `MysqlTag`, and `DuckdbTag`): `postgres"SELECT * FROM
  t WHERE a = ${x}"` gives a `Query`, built with that dialect's checks.
  Template mistakes panic: a hole in a quote or comment (including
  PostgreSQL's and DuckDB's dollar quotes and MySQL's `#` comments),
  placeholder-like text (`?` everywhere, `$` outside PostgreSQL's and
  DuckDB's dollar quotes, and SQLite's `:a` and `@a`), text ending in a
  quote or block comment, a MySQL backslash before a quote or backslash
  in a string (read differently under `NO_BACKSLASH_ESCAPES`), a
  nested query of another dialect, MySQL
  executable comments, quotes in MySQL optimizer hints (`/*+ … */`),
  text that puts DuckDB's Unicode space pass out of step, and NUL
  anywhere in the text. Each dialect's file lists its rules.

Later, after a design pass:

- A small statement model: `SELECT`, `INSERT`, `UPDATE`, and `DELETE`,
  with `WHERE`, `ORDER BY`, and `LIMIT`.

Also planned:

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
driver, not only the database, so the style is chosen when rendering:

| Language | SQLite | PostgreSQL | MySQL and MariaDB | DuckDB |
| --- | --- | --- | --- | --- |
| C++ | `sqlite3`: `?` | `libpq`: `$1` | Connector/C: `?` | DuckDB's C and C++ APIs: `?` or `$1` |
| C# | `Microsoft.Data.Sqlite`: `@p1` or `:p1` (no `?`) | Npgsql: `$1` (recommended), or `@p1` | MySqlConnector: `?` or `@p1` | DuckDB.NET: `?` or `$1` |
| Java | JDBC: `?` | JDBC: `?` | JDBC: `?` | JDBC: `?` |
| JavaScript | `node:sqlite`, `better-sqlite3`: `?` | `pg`: `$1` | `mysql2`: `?` | `@duckdb/node-api`: `?` or `$1` |
| Lua | `lsqlite3`: `?` | LuaSQL: none, quoting only | LuaSQL: none, quoting only | none common, quoting only |
| Python | `sqlite3`: `?` | psycopg 3: `%s`, or `$1` with its `RawCursor`; asyncpg: `$1` | PyMySQL, mysqlclient: `%s`; MariaDB Connector: `?` | `duckdb`: `?` or `$1` |
| Rust | `rusqlite`: `?` | `tokio-postgres`, `sqlx`: `$1` | `mysql`, `sqlx`: `?` | `duckdb`: `?` or `$1` |

Checked against each driver's docs or source (2026-11):
`Microsoft.Data.Sqlite`'s [parameters](https://learn.microsoft.com/en-us/dotnet/standard/data/sqlite/parameters)
and [`SqliteParameter.Bind`](https://github.com/dotnet/efcore/blob/main/src/Microsoft.Data.Sqlite.Core/SqliteParameter.cs);
Npgsql's [basic usage](https://www.npgsql.org/doc/basic-usage.html)
and [SQL parser](https://github.com/npgsql/npgsql/blob/main/src/Npgsql/SqlQueryParser.cs);
MySqlConnector's [SQL parser](https://github.com/mysql-net/MySqlConnector/blob/master/src/MySqlConnector/Core/SqlParser.cs);
`mysql2`'s [prepared statements](https://sidorares.github.io/node-mysql2/docs/documentation/prepared-statements);
`lsqlite3`'s [`bind_values`](https://github.com/LuaDist/lsqlite3/blob/master/lsqlite3.c)
(an older copy of the source; [its site](http://lua.sqlite.org/) was
unreachable); LuaSQL's [manual](https://lunarmodules.github.io/luasql/manual.html);
psycopg's [query conversion](https://github.com/psycopg/psycopg/blob/master/psycopg/psycopg/_queries.py);
PyMySQL's [cursors](https://github.com/PyMySQL/PyMySQL/blob/main/pymysql/cursors.py);
mysqlclient's [cursors](https://github.com/PyMySQL/mysqlclient/blob/main/src/MySQLdb/cursors.py);
MariaDB Connector/Python's [module](https://mariadb.com/docs/connectors/mariadb-connector-python/api/module);
and DuckDB's [prepared statements](https://duckdb.org/docs/current/sql/query_syntax/prepared_statements)
and [Python DB API](https://duckdb.org/docs/current/clients/python/dbapi).
The rest are from memory of the drivers' docs, and the differential
tests should confirm every one. Details:

- `%s` drivers (psycopg 3, PyMySQL, and mysqlclient) skip `%`
  formatting when the parameters are `None`, leaving `%%` as it is, but
  apply it to an empty list, turning `%%` into `%`. So an adapter must
  always pass a list, even an empty one. psycopg 3 turns `%s` into `$1`
  for the server (except its `ClientCursor`); PyMySQL and mysqlclient
  fill in values on the client, so `-%s` with `-1` would be `--1`, a
  comment, and rendering's spaces around holes prevent that.
- `Microsoft.Data.Sqlite` binds only by name (`@`, `:`, or `$`), and
  an unnamed `?` is an error, so use `atNamed` or `colonNamed`.
- Npgsql sends `$1` text unchanged when its parameters have no names.
  With named ones, it rewrites `@name` and `:name` to `$1` by scanning
  the text (skipping quotes, comments, and dollar quotes, and leaving
  names it doesn't know), so `atNamed` works too; a query with `@`
  in its text fails `atNamed`, though, so use `dollarNumbered`.
- MySqlConnector reads `?` by position, or `@name` and `?name` by name,
  skipping quotes and comments; MySQL's own `@a` variables then need
  its `AllowUserVariables` option, and fail `atNamed` here.
- `mysql2` reads `?`, and with `query` (not `execute`) also `??` for a
  name, filled in on the client; the lexers reject `?` in template
  text, so a query never has `??`.
- `lsqlite3`'s `bind_values` binds `?` by position.
- Python's `sqlite3` takes `?` with a sequence, and any named form
  with a dict keyed by the name without its first character: `:p1`
  and `@p1` as `p1`, and `$1` (a name to SQLite) as `1`. The round-trip
  tests check all four. It binds `bool` as an integer, and SQLite
  stores a NaN as `NULL`.
- MariaDB Connector/Python's style is `?` (`qmark`), and it also takes
  `%s`, but not both in one query.
- DuckDB's manual lists `?`, `$1`, and `$name`, and says JDBC takes
  only `?`. Python's `duckdb` takes `?` and `$1` with a list, and any
  `$` name with a dict keyed by the name without its `$`, so `$1` as
  `1`; the round trip checks all three. DuckDB also reads `?1` as a
  numbered parameter.
- SQL Server's (`@p1`) and Oracle's (`:p1`) styles are already here,
  for when those dialects come.
- Where a driver has no parameters (LuaSQL), quoting is the fallback,
  which is why `quoteString` exists.

## Prior art and test oracles

Other libraries already handle SQL per dialect. Wherewith uses them as
checklists of rules and cases, and, in tests, as oracles: comparing
our quoting with theirs on many inputs. Each needs the user's approval
before tests use it as a package.

- [SQLGlot](https://github.com/tobymao/sqlglot) (Python): a parser and
  transpiler for about 30 dialects.
- [SQLAlchemy](https://www.sqlalchemy.org/) (Python): its dialect
  system, with each database's quoting and reserved words.
- [sqlparser-rs](https://github.com/apache/datafusion-sqlparser-rs)
  (Rust): a parser with a `Dialect` trait, used by Apache DataFusion.
- [jOOQ](https://www.jooq.org/) (Java): `SQLDialect`, covering many
  databases. Some dialects need a paid license, so borrow carefully.
- [Knex](https://knexjs.org/) and [Kysely](https://kysely.dev/)
  (JavaScript and TypeScript): query builders with per-dialect clients.
- [Diesel](https://diesel.rs/) and
  [SeaQuery](https://github.com/SeaQL/sea-query) (Rust): query
  builders with per-database backends.
- Quoting-only libraries: psycopg's
  [`sql.Identifier`](https://www.psycopg.org/psycopg3/docs/api/sql.html),
  [pg-format](https://github.com/datalanche/node-pg-format), and
  [sqlstring](https://github.com/mysqljs/sqlstring).

Most are MIT or Apache licensed, so small borrowings, with credit in
`NOTICE`, are fine. SQLite's source is in the public domain, and its
tokenizer and keyword list are the authoritative spec for the SQLite
profile.

The shared core stays the strict common form: Wherewith never relies
on SQLite's leniency, such as `"text"` read as a string or `[names]`
in brackets. SQLite is the first real engine for the differential
tests below.

## Testing

- **Unit tests in Temper**, next to the code, run on every backend:
  each profile's quoting with hostile input (quotes, backslashes, NUL,
  Ctrl-Z, line breaks, comment starts, characters above U+FFFF, lone
  surrogates where a language can make them, and very long text), name
  limits, and template mistakes.
- **Round trips through real engines:** `tests/engines/` runs the
  Python library against real databases, with hostile input: the unit
  tests' cases, every ASCII control character, quotes of many kinds,
  combining marks, very long text, and seeded random fuzz.
  `roundtrip.py` has the inputs and checks they share; each engine's
  runner says how to reach it and what it gives back.
  - **SQLite (done):** `sqlite_roundtrip.py`, with Python's standard
    `sqlite3`. Quoted strings read back exactly from `SELECT`; quoted
    names make a table and column that read back exactly from
    `sqlite_schema` and `pragma_table_info`, and work in an insert and
    a select; values bound in every style the driver takes (`?`,
    `:p1`, `@p1`, and `$1`) come back equal with the type SQLite
    stores; nested queries and holes beside operators give the
    expected rows; and random templates mixing holes with quoted
    strings, aliases, and comments check that the builder's lexer and
    the engine agree on every boundary. Inputs Wherewith rejects (NUL
    and lone surrogates in strings, and empty names) must be rejected.
    With Python 3.12 or later it turns off SQLite's `"…"` strings
    (DQS), so a misquoted name fails instead of reading as text. CI
    runs it in the `py` job.
  - **PostgreSQL and MariaDB (in CI):** `postgres_roundtrip.py` with
    psycopg 3 and `mariadb_roundtrip.py` with PyMySQL, run by CI's
    `engines` job against service containers (PostgreSQL 18 and
    MariaDB 11.8). They make the same checks, reading names back from
    `information_schema` (and `pg_catalog` for PostgreSQL). PostgreSQL
    binds with `%s` through psycopg's server-side and client-side
    cursors, and with `$1` through its `RawCursor`, which sends the
    SQL unchanged; it checks that `standard_conforming_strings` is on
    and records it, and expects names over 63 bytes and NUL anywhere
    in text to be rejected. MariaDB binds with `%s`, filled in by
    PyMySQL on the client, and runs everything in four SQL modes: the
    default, `NO_BACKSLASH_ESCAPES`, `ANSI_QUOTES`, and both, with the
    matching profile; in the modes without backslash escapes it also
    checks that the default `mysql` profile's strings still end where
    Wherewith ends them, reading back with their escapes as text. It
    expects names over 64 characters, above U+FFFF, ending in
    whitespace, or starting with `#mysql50#` to be rejected, and its DOUBLE has no NaN, infinities, or
    subnormals, so those aren't bound. Each runner records the
    server's own limits (truncated names, and how it treats NUL and
    long names). Without a server, they skip; CI passes
    `--require-server`.
  - **DuckDB (done):** `duckdb_roundtrip.py`, with the `duckdb`
    package, embedded and in memory, so it runs anywhere; CI runs it in
    the `py` job. It makes the same checks, reading names back from
    `information_schema` and `duckdb_tables()` and `duckdb_columns()`,
    and binds with `?` and `$1` by position and `$1` by name. It also
    checks that the Unicode spaces DuckDB changes are the 18 the lexer
    knows, and, for random text in a block comment, which DuckDB's
    parser skips but its Unicode space pass reads, that the lexer finds
    the pass out of step exactly when DuckDB's is. It records DuckDB's
    limits: no truncation of long names, names matched without regard
    to case, and NUL taken in names and literals (which Wherewith
    rejects anyway). It uses two threads and a 1 GB memory limit, since
    DuckDB's default of a thread per core reserves much memory.
  - **MySQL itself, later:** a MySQL service container, with the
    MariaDB runner's checks.
  - Later, binding parameters through each language's drivers above.

## Open questions

Each has a recommendation, but stays open until decided.

1. **Tag names:** `sqlite`, `postgres`, `mysql`, and `duckdb`, or
   names that can't clash with other libraries' tags, such as
   `sqliteQuery`? Recommended: the plain names.
2. **NUL in SQLite strings:** reject (now), or write an expression
   such as `'a'||char(0)||'b'` where an expression is allowed?
   Recommended: keep rejecting; bind such values as parameters.
3. **Empty names:** rejected everywhere now, though SQLite accepts
   `""`. Keep that? Recommended: keep rejecting them everywhere.
4. **MariaDB:** share the MySQL profiles (now), or get its own, for
   differences such as its `SQL_MODE=ORACLE`? Recommended: share them
   until a real difference matters.
5. **Template mistakes:** panic when the tag is used (now), or make
   every template bubble, which Rust would see as a `Result`?
   Recommended: templates panic, and the builder bubbles.
6. **Whitelists:** which lists first, and how strict per dialect
   (`ColumnType` differs the most)? Recommended: start with SQLite's
   column types, defaults, foreign-key actions, functions, and
   operators.

## Decided

- **Placeholder styles** are chosen at render time, not fixed per
  dialect, since they depend on the driver.
- **Raw queries:** `Query`'s constructor is private, and
  `Query.unchecked(dialect, parts)` is the plainly named way to skip
  the checks.
- **A query keeps its dialect** and renders only for it (or the other
  MySQL profile), since text checked by one dialect's lexer can read
  differently in another: `postgres"SELECT 1 # ${x}"` is fine in
  PostgreSQL, where `#` is an operator, but rendered for MySQL its
  parameter would land in a `#` comment.
- **Named styles** fail if their marker is anywhere in the text, even
  in quotes or comments, rather than lexing to find only real
  placeholders: conservative, and the same for every driver.
- **MySQL backslashes:** templates keep rejecting a backslash before a
  quote or backslash in a string, since `NO_BACKSLASH_ESCAPES` reads it
  differently.
- **PostgreSQL** is assumed to have `standard_conforming_strings` on,
  as documented above, with no extra rejection of backslashes.
- **Spacing:** the space rendering adds beside a hole, as in `- ?`, is
  fine, even where it isn't needed.
- **More databases:** DuckDB (done), then SQL Server, Oracle, and Db2.
