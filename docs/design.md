# Wherewith Design

Wherewith lets you write a query once, in a common SQL dialect, and
run it on SQLite, PostgreSQL, MySQL or MariaDB, and DuckDB, the same in
every language Temper supports. It parses the common dialect, checks
that a query means the same on every database it targets, and renders
it for each, with values always bound as parameters. Underneath are
the pieces a safe-composition framework, a query builder, or an admin
tool needs: quoting and templates for each database, done right.

The common dialect is [designed below](#the-common-dialect), and
usable end to end: its tag, lexer, expressions, statements, and
rendering for each database are done, checked on the real engines, and
the rest of the checks are next. Quoting and per-database templates are
done.

## Goals

- **Write once, run on every database:** a common dialect, starting
  with a useful subset of SQL, parsed and rendered for each database,
  with a check stage that refuses what wouldn't mean the same
  everywhere.
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

- Translating one database's SQL into another's, say PostgreSQL's into
  MySQL's. Translation goes one way: from the common dialect to each
  database.
- All of SQL. The common dialect grows from a useful subset, and the
  per-database tags cover the rest; their text is lexed only enough to
  find quotes, comments, and stray parameters, never parsed.
- An ORM, or knowledge of the schema. Wherewith never sees tables or
  column types, so it checks only what a query's text and values show.
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
  `SqlFloat`, `SqlBool`, or `SqlNull`, whose `toString` writes it as
  SQL would, the same in every language: `'it''s'`, `7`, `2.0`,
  `TRUE`, `NULL`), and `QueryName` (an
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
  known limitation, so the constructor may be callable there, with
  the same danger. `targets` lists the databases
  a common query was checked for and renders for (just its dialect for
  a database's query); `unchecked` takes them too, every database by
  default.
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
  A [common query](#the-common-dialect) renders for each of its
  targets, and for `Dialect.common` as canonical common SQL;
  `renderedParts(dialect)` gives the parts it renders as, for code
  that builds on them. Where a hole meets
  text it could merge with (`5-` and `-1`, `a` and `$1`, or two quoted
  names), rendering adds a space.
- `QueryBuilder(dialect)`: makes a query from plain code, checking its
  text with that dialect's lexing rules: `appendSafe` for trusted SQL
  text, `append` overloads for values, `SqlValue`, `Identifier`, and
  `Query` (of the same dialect, as for rendering, or a common query,
  rendered for the builder's database), and `build`, which
  bubbles on a mistake, with `templateProblem` saying why.
  `templateProblem` gives the problem `build` would bubble for
  without building: lexing, the template's end, and, for the common
  dialect, the parser and the checks. Reading it changes nothing, so a
  half-written template can be finished; a common template's parse and
  checks run once per state of the template, shared with `build`.
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
- The common dialect, so far: `Dialect.common`, a profile that quotes
  as the shared core does and takes only names `Identifier` takes; and
  the `sql` tag (`SqlTag`), whose queries have that dialect. The tag
  and `QueryBuilder` lex, parse, and check the whole statement (below),
  refusing anything outside the subset or read differently by a target
  database, with the line, column, and an excerpt. A builder can
  narrow its `targets`, which the query records. Common queries nest in
  common templates where a subquery goes, and in a database's template
  rendered for it, and render for each target database, as
  [below](#rendering-per-dialect).

Next: the rest of the [common dialect](#the-common-dialect)'s check
stage.

Also planned:

- More value types: bytes, dates and times, and lists for `IN (…)`
  (one parameter each).
- Whitelists, each a class with a private constructor, a fixed list,
  and a `parse` that returns null for anything else: `SortDirection`,
  `NullsOrder`, `ComparisonOperator`, `ColumnType` per dialect,
  `ForeignKeyAction`, and `SqlFunction` (a short list of scalar
  functions). In a template they're written as SQL.

## The common dialect

Status: designed (2026-11-07), with its open questions decided
(2026-11-09, under [Decided](#decided)). Built: chunks 1 to 4 of the
[plan](#plan): the lexer and tag, expressions, statements, and
rendering for each database.

One query, written once, rendered for each database:

```temper inert
let q = sql"SELECT name, coalesce(nick, name) AS shown FROM users
  WHERE id IN (${a}, ${b}) ORDER BY name NULLS LAST LIMIT ${10}";
q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered);
// SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users"
//   WHERE "id" IN ($1, $2) ORDER BY "name" LIMIT $3
q.render(Dialect.mysql, PlaceholderStyle.question);
// SELECT `name`, COALESCE(`nick`, `name`) AS `shown` FROM `users`
//   WHERE `id` IN (?, ?) ORDER BY `name` IS NULL, `name` LIMIT ?
```

A template goes through four stages: the lexer and parser make a
syntax tree when the tag runs; the check stage refuses anything that
wouldn't mean the same on every target; and `render` writes the tree
for one database. The rules:

- **Same meaning or refused.** Where databases differ, Wherewith
  emulates the difference only when the emulation is exact and cheap,
  refuses what the check can see, and documents what only the data
  decides (collations, column types), with an engine test pinning
  each documented difference so this page stays true.
- **Values are always parameters**, and names are always quoted on
  output, so no target's reserved words matter.
- **One way only:** common to each database. Text checked by one
  database's tag is never parsed or translated.

### The first subset

Statements, one per query, with no `;`:

- `SELECT [DISTINCT]` columns (`*`, `t.*`, expressions with `AS`
  aliases), `FROM` a table or a subquery with an alias, joined by
  `[INNER] JOIN` or `LEFT [OUTER] JOIN` with `ON` (`USING` later), or
  `CROSS JOIN`; `WHERE`, `GROUP BY` and `HAVING`, `ORDER BY` with
  `ASC`, `DESC`, and `NULLS FIRST` or `NULLS LAST`, and `LIMIT` and
  `OFFSET`.
- `INSERT INTO t (columns) VALUES (…), (…)` or `… SELECT …`, always
  with a column list.
- `UPDATE t SET c = e, … [WHERE …]` and `DELETE FROM t [WHERE …]`.

Expressions: literals (integers, decimals, strings, `TRUE`, `FALSE`,
and `NULL`), columns (`c` or `t.c`), parameters, comparisons (`=`,
`<>` or `!=`, `<`, `<=`, `>`, `>=`), `AND`, `OR`, `NOT`, arithmetic
(`+`, `-`, `*`, `/`, `%`), `||` concatenation, `IS [NOT] NULL`,
`[NOT] IN` (a list or a subquery), `[NOT] BETWEEN`, `[NOT] LIKE` with
`ESCAPE`, `EXISTS`, scalar subqueries, `CASE` (both forms), and
`CAST` to `INTEGER` (64-bit), `DOUBLE`, or `TEXT`. Functions:
`COALESCE`, `NULLIF`, `ABS`, `LOWER`, `UPPER`, `LENGTH`, `SUBSTR`,
`TRIM`, `REPLACE`, and the aggregates `COUNT(*)`, `COUNT([DISTINCT]
x)`, `SUM`, `AVG`, `MIN`, and `MAX`.

Deliberately later, each needing its own design:

| Construct | Why later |
| --- | --- |
| Upsert | `ON CONFLICT` (SQLite, PostgreSQL, DuckDB) and MySQL's `ON DUPLICATE KEY UPDATE` pick the conflicting key differently; MySQL can't name one. |
| `RETURNING` | Missing in MySQL; MariaDB has it for `INSERT` and `DELETE` only. Needs a refusal story per target. |
| Window functions | MySQL 8.0 and MariaDB 10.2 or later only, and frame defaults and function lists differ. |
| CTEs (`WITH`) | Recursion and materialization differ, and MySQL needs 8.0. Small once subqueries are solid. |
| DDL | Column types differ the most; needs the `ColumnType` whitelists first. |
| Dates and times | Types, time zones, and functions differ almost everywhere; needs the planned date values first. |
| `UNION`, `INTERSECT`, `EXCEPT` | SQLite takes no parenthesized members; MySQL has `INTERSECT` and `EXCEPT` only from 8.0.31. |
| `RIGHT` and `FULL JOIN` | SQLite only from 3.39; MySQL has no `FULL JOIN`. |
| `IS [NOT] DISTINCT FROM` | Easy (`IS` in SQLite, `<=>` in MySQL); next after the subset. |
| Lists bound to `IN ${list}`, bytes, JSON, regular expressions, `ILIKE` | Need new value types, or differ widely. |

### The tag and the API

The `sql` tag gives a `Query` whose `dialect` is
`Dialect.common`, a new profile that quotes as the shared core does
and allows only names `Identifier` allows. Unlike other queries, a
common query renders for every profile:

- **Parts and tree.** `parts` keeps the template as written, and the
  query also holds its syntax tree, privately. A builder's query keeps
  the tree its checks parsed, handed over through `Query.checked` and
  an opaque `TemplateCheck`, since the builder can't call `Query`'s
  private constructor, so a template is parsed once.
  `Query.unchecked(Dialect.common, parts)` parses its parts, since
  rendering needs the tree.
- **Rendering.** `render(dialect, style)` checks the query for that
  dialect, writes the tree as parts for it, and then renders those as
  any query (spacing, `%` doubling, and the named-marker check), so
  placeholder styles work unchanged. `render(Dialect.common, style)`
  writes canonical common SQL, for logs and tests. `renderProblem`
  gives the check's message.
- **Targets.** A builder checks for every profile by default, or
  fewer, set with `targets`. The query records them, and renders only
  for them; rendering for another database bubbles.
- **Builder.** `new QueryBuilder(Dialect.common)` takes the same
  `appendSafe` and `append` calls, and `build` parses and checks,
  bubbling with `templateProblem`, which gives the same problem before
  `build` runs; the tag panics, as other tags do.
- **Holes by kind.** A value (`String`, `Int`, `SqlValue`, …) goes
  only where the grammar takes an expression or a `LIMIT` count; an
  `Identifier` only where it takes a name (a table, a column, an
  alias, or one part of `${schema}.${table}`); and a common `Query`,
  which must be a `SELECT`, only where it takes a subquery, as in
  `IN (${q})`, `EXISTS (${q})`, `FROM (${q}) AS t`, or after
  `INSERT INTO t (a)`. Anything else is a template mistake: a `String`
  can never become a name.
- **Nesting.** A common query nested in a common template goes in as
  its own tokens, so the outer query's checks see into it and check it
  again for the outer query's targets; problems there are placed at
  its hole. A common query nested in a database's template
  (`postgres"… ${q}"`) is rendered for that database and goes in as
  parts: an escape hatch for features outside the subset. A database's
  query can't nest in a common template, since it has no tree.

### The parser

Pure Temper, with no regular expressions: a lexer reads each text run
into tokens, with holes as tokens of their kind, and a
recursive-descent parser builds the tree. The grammar, roughly
(keywords are case-insensitive):

```
statement = select | insert | update | delete | QUERY_HOLE
select    = "SELECT" ["DISTINCT"] item {"," item} ["FROM" source {join}]
            ["WHERE" expr] ["GROUP" "BY" exprs ["HAVING" expr]]
            ["ORDER" "BY" order {"," order}] ["LIMIT" count] ["OFFSET" count]
item      = "*" | name "." "*" | expr [["AS"] name]
source    = qname [["AS"] name] | subquery ["AS"] name
join      = ["INNER" | "LEFT" ["OUTER"]] "JOIN" source "ON" expr
          | "CROSS" "JOIN" source
order     = expr ["ASC" | "DESC"] ["NULLS" ("FIRST" | "LAST")]
count     = INTEGER | VALUE_HOLE
insert    = "INSERT" "INTO" qname "(" names ")"
            ("VALUES" row {"," row} | select | QUERY_HOLE)
update    = "UPDATE" qname "SET" name "=" expr {"," name "=" expr} ["WHERE" expr]
delete    = "DELETE" "FROM" qname ["WHERE" expr]

expr      = and {"OR" and}
and       = not {"AND" not}
not       = "NOT" not | predicate
predicate = concat [cmp concat | "IS" ["NOT"] "NULL"
            | ["NOT"] "IN" (subquery | "(" exprs ")")
            | ["NOT"] "BETWEEN" concat "AND" concat
            | ["NOT"] "LIKE" concat ["ESCAPE" STRING]]
concat    = sum {"||" sum}
sum       = product {("+" | "-") product}
product   = unary {("*" | "/" | "%") unary}
unary     = ("-" | "+") unary | primary
primary   = literal | VALUE_HOLE | column | "(" expr ")" | subquery
          | "EXISTS" subquery | case | cast | call
subquery  = "(" (select | QUERY_HOLE) ")"
cast      = "CAST" "(" expr "AS" ("INTEGER" | "DOUBLE" | "TEXT") ")"
case      = "CASE" [expr] ("WHEN" expr "THEN" expr)+ ["ELSE" expr] "END"
call      = "COUNT" "(" "*" ")" | FUNCTION "(" ["DISTINCT"] [exprs] ")"
column    = name ["." name]
qname     = name ["." name]
name      = BARE | QUOTED | NAME_HOLE
```

Expressions (built; `src/common-expressions.temper.md` has the
details) parse to a tree of plain classes, with holes kept as their
place among the template's holes. Where the databases read the same
text differently, the parser refuses it: predicates don't chain
(`a = b IS NULL` too), `||` beside arithmetic needs parentheses,
names have at most two parts (DuckDB can read a third as a field),
`TRIM` takes one argument (the others take a set of characters to
remove as a second, and MySQL none: its `TRIM(r FROM s)` removes a
whole string), `DISTINCT` goes only in aggregates, and
a nested query goes only in its own parentheses. A printer writes the
tree back as canonical common SQL, with only the parentheses needed.

Statements (built; `src/common-statements.temper.md`) parse to the
same kind of tree, with subqueries written in place or as holes. The
parser refuses `HAVING` without `GROUP BY` (SQLite before 3.39), every
clause after the items without `FROM` (MySQL and MariaDB versions
differ), comma joins (MySQL groups them differently beside `JOIN`), a
subquery in `FROM` without an alias, a parenthesized query after
`INSERT` (SQLite), `VALUES` rows of the wrong length, and `SET t.c`
(PostgreSQL reads a field). Aliases may skip `AS`, since rendering
always writes it. Words for later constructs (`UNION`, `WITH`,
`RIGHT JOIN`, `USING`, …) say so.

Lexing rules (built; `src/common.temper.md` has the details): ASCII
whitespace (not vertical tab, which SQLite refuses); `--` comments to
a line feed, with no lone carriage return in them (PostgreSQL and
DuckDB end them there), and `/* */` comments, with `/*` refused inside
one (PostgreSQL and DuckDB nest them, SQLite and MySQL don't), and no
`/*!` or `/*+`; comments may hold anything but NUL, since they never
reach the output. Bare names `[A-Za-z_][A-Za-z0-9_]*` that aren't
keywords; keywords in any case, where function names, type names,
`FIRST`, and `LAST` aren't reserved, and a few words for planned
constructs are (`UNION`, `WITH`, `RETURNING`, and the like). Quoted
names `"…"` and strings `'…'`, with the quote doubled, no backslash
escapes, and no prefix (`E'…'`, `X'…'`, `_utf8mb4'…'`); integers and
decimals (`12`, `1.5`, no exponents, and nothing running into them);
and the operators above. Anything else outside quotes and comments,
such as `?`, `$`, `:`, `@`, `;`, backticks, `[`, `::`, `==`, or
non-ASCII characters, is refused, and NUL anywhere. Comparisons don't
chain (`a = b = c` is refused), since targets parse chains
differently or not at all.

Errors say what was expected and where: a line and column in the
template written with each hole as `${…}`, and a short excerpt, as in
`? outside quotes; put values in holes, at line 2, column 10:   ${…} + ?`.

Speed and the backends:

- **Linear and allocation-light.** Tokens hold a run number and
  string indexes rather than copied text; keywords are looked up in
  one `Map` built once; the tree is plain classes under sealed
  interfaces, which every backend translates directly (classes in
  C++, C#, Java, JavaScript, Python, and Rust; tables in Lua).
- **A depth limit** (say 64 nested parentheses or subqueries) keeps
  recursion safe on every backend, including Python's recursion limit
  and threads with small stacks, and refuses hostile input instead of
  crashing.
- **Parsing per query.** A tag runs every time its line runs, so each
  query is parsed afresh: a few microseconds in compiled backends and
  tens in Python or Lua for a typical query, to be measured. Caching
  per template needs a per-call-site constant, which Temper doesn't
  have, or a shared global map, which needs locking Temper can't yet
  express portably. So the first version doesn't cache, but the tree
  takes its holes from a separate list, so a cache would only need to
  keep immutable trees, if measurements call for one.

### The check stage

After parsing, the check walks the tree once for each target, and
gives the first problem with its position:

- **Names:** every name and alias passes each target's `nameProblem`
  (63 bytes for PostgreSQL; 64 characters, nothing above U+FFFF, no
  trailing whitespace, and no `#mysql50#` for MySQL; no NUL anywhere).
  Bare names must be lowercase, since PostgreSQL folds them while the
  others don't; every name renders quoted. (Built in the lexer, with
  the string and number checks below.)
- **Strings:** every string literal passes each target's
  `stringProblem` (no NUL except under MySQL's backslash escapes; no
  lone surrogates).
- **Numbers:** integer literals fit a signed 64-bit integer (beyond
  it, SQLite turns to a float and DuckDB fails); decimals have at most
  18 digits, which DuckDB's `DECIMAL` keeps exactly.
- **Constructs:** each one the target's renderer supports, in the
  forms it supports: `LIMIT` inside an `IN` subquery is refused for
  MySQL, which rejects it, say.
- **Known traps,** where the text or values show them: `x = NULL`,
  or `x = ${v}` with a null `v` (always unknown; use `IS NULL`), `/`
  without a known float operand, `LIKE` without `ESCAPE` on a pattern
  that isn't a plain literal, `CASE` branches mixing literal kinds
  (PostgreSQL and DuckDB refuse them, SQLite and MySQL convert), a
  `SUBSTR` start below 1, and an `UPDATE` that reads a column it set
  earlier in the same `SET`, since MySQL assigns left to right.

Built so far, for expressions: `= NULL` and `NULL` in `IN` lists, and
null values in their place (every value is known when the query is
built, so a null one is the same trap as `NULL` in the text),
`/` without a float operand (a float value, a decimal, `AVG`, a
`CAST` to `DOUBLE`, or arithmetic on one), `%` with a float (SQLite
truncates it), `/` or `%` by a literal zero, `LIKE` without `ESCAPE`
on anything but a literal, `ESCAPE` other than one character (not `'`,
`%`, or `_`), `SUBSTR` with a literal start below 1 or a negative
length, aggregates inside aggregates, and kinds the text or values
show that databases convert differently: text or booleans in
arithmetic, numbers or text as conditions, comparing different kinds,
`CASE` and `COALESCE` mixing kinds, booleans or floats in `||`, and
casts of booleans, of floats to `INTEGER` or `TEXT`, and of strings
that aren't plain numbers to `INTEGER` or `DOUBLE`.

Built for statements: conditions in `WHERE`, `HAVING`, and `ON`;
`LIMIT` and `OFFSET` values that aren't non-negative integers;
constants in `GROUP BY` and `ORDER BY` other than a column's place;
columns neither grouped nor aggregated in a grouped query (SQLite
takes any row's); `SELECT` aliases where databases could read a
column instead (outside `ORDER BY`, inside its expressions, or
matching only without regard to case); `SELECT DISTINCT` ordered by
something not selected; a table twice in `FROM`; a column twice in
`INSERT` or `SET`; and `ON` reading a table joined after it. For MySQL
targets also: the `UPDATE … SET` trap, a subquery reading the table an
`UPDATE`, `DELETE`, or `INSERT … VALUES` changes, `LIMIT` in an `IN`
subquery, and `*` beside other items. Each rests on MySQL's own
behavior, which [engine checks](#engine-checks) names the case for.

Which of alias and column a name means: in `HAVING`, for a column not
grouped, databases differ, and inside `ORDER BY` expressions MySQL's
manual says MySQL reads the alias, where the others, MariaDB included
(checked in CI), read the column; in `WHERE`, `ON`, and `GROUP BY`
they all read the column, but a reader could take it either way. So
an alias that names something else is refused in all of these, for
every target. Alone in `ORDER BY`,
every database matches a `SELECT` item's output name first, but they
name items differently (2026-11-10, from CI's random queries):

- **SQLite and DuckDB** match only aliases, and otherwise read a
  column, as the common dialect does (checked locally, `*` included).
- **PostgreSQL** matches unaliased items too, by the name its
  `FigureColname` gives them: a column's name, a function's (`btrim`
  for `TRIM`), a cast's operand's if that has one and else its type's
  (`int8`, `float8`, `text`), `CASE`'s `ELSE` result's or `case`,
  `exists`, a subquery's item's, and `?column?` for the rest. Two
  matches that aren't the same column are an error ("ORDER BY "id" is
  ambiguous"), and one that isn't the column silently sorts by the
  item: `SELECT CAST(score AS TEXT) … ORDER BY score` sorts text.
  Rendering for PostgreSQL writes such a column qualified, `people.id`,
  which always means the input column, as everywhere else; that also
  holds with `DISTINCT`, since the qualified column matches its item,
  and with `GROUP BY`, which PostgreSQL resolves against columns first.
  It can only qualify in a query with one source and no outer query:
  with joins it can't tell the table, and inside an expression the
  name could be an outer query's column, so the checks refuse those,
  asking for the table. An alias that another item is named too is
  ambiguous there, and refused: `SELECT id, score AS id … ORDER BY id`.
- **MySQL and MariaDB** match unaliased items too, without regard to
  case, but name an expression after its text, so only plain columns
  clash: an alias of a column beside another column of that name is
  ambiguous there, and refused, but `score + 0 AS id` beside `id` reads
  as the alias. Two columns that are the same column don't clash on
  either.
- **`*`** brings columns the checks can't see. A star column with an
  alias's name makes that alias ambiguous on PostgreSQL and MySQL (an
  error, not a different result), and isn't refused, since the schema
  decides. A qualified column matches the star's own, so qualifying
  still works.
- **UNION** isn't in the grammar yet; when it is, its `ORDER BY` can
  only name output columns, so this needs another look.

The corpus pins both CI queries and the qualified cases, and runs the
refused alias queries unchecked to confirm PostgreSQL and MariaDB
refuse them.

Narrower targets relax the checks for the dialects left out: the
lexer's string and name checks, the MySQL statement checks, and the
expression checks there because databases differ, when the targets
left read the construct alike (each check has a letter per profile;
`src/common-expressions.temper.md` lists them). The traps (`NULL` that
never matches, `ESCAPE` misused, aggregates in aggregates) apply to
every target, and so, for now, do the other statement checks.
The default set is every profile now; a new database (SQL Server,
say) joins it only in a major version, so an upgrade can't make
working queries fail.

A profile can also stand for databases that disagree among
themselves. Under `NO_BACKSLASH_ESCAPES`, MySQL's manual says `LIKE`
has no escape character without `ESCAPE`, but MariaDB 11.8 still reads
`\` as one (checked in CI), and both use the `mysqlNoBackslashEscapes`
profile. So `LIKE` without `ESCAPE` on a value or a pattern with `\` is
refused for that profile even when it's the only target (its letter is
`?`, which always counts as differing), and the fix is the one every
target already reads alike: an explicit `ESCAPE '!'`. Rendering an
`ESCAPE` for that profile instead would have to write `'\'`, which
opens a string on a server without the mode, the profile's one
danger, and would still leave `\` reading differently from SQLite and
DuckDB, so a query kept portable is the simpler rule. A pattern
without `\` reads alike everywhere and stays allowed.

### Rendering per dialect

Built (`src/common-rendering.temper.md`). One renderer walks the tree,
asking a small private table per target for the pieces that differ. It
writes parentheses around every operand that is itself an operator
expression (outside `AND` and `OR` chains), since precedence differs:
SQLite reads `'a' || 1 + 2` as `('a' || 1) + 2`, PostgreSQL and DuckDB
as `'a' || (1 + 2)`, and MySQL's `NOT` binds tighter with
`HIGH_NOT_PRECEDENCE`. That also means it never writes `--` from a
minus before a negative number. Both MySQL profiles render the same,
except for string literals, each quoted by its own profile. Each
rendering then goes through that database's own lexer, as its tag
would check it, so a value can't land in a quote or comment.

| Common | SQLite | PostgreSQL | MySQL and MariaDB | DuckDB | Approach |
| --- | --- | --- | --- | --- | --- |
| `name` (bare) | `"name"` | `"name"` | `` `name` `` | `"name"` | Bare names lowercase, all quoted |
| `TRUE`, `FALSE` | `TRUE`, `FALSE` (1 and 0, from 3.23) | same | same (1 and 0) | same | Same text; results differ, documented |
| `a \|\| b` | `a \|\| b` | `a \|\| b`, values cast to `TEXT`, and `a` too if neither is text | `CONCAT(a, b)` | `a \|\| b` | Emulate: MySQL's `\|\|` is `OR` without `PIPES_AS_CONCAT`, and PostgreSQL has no `\|\|` for two numbers; `CONCAT` gives `NULL` on any `NULL`, as `\|\|` does |
| `LIMIT n OFFSET m` | same | same | same | same | Same |
| `ORDER BY c` beside an item PostgreSQL names `c`, such as `CAST(c AS TEXT)` | `c` | `t.c` | `c` | `c` | Qualify for PostgreSQL, which would read the item; refuse where the table isn't known |
| `OFFSET m` alone | `LIMIT -1 OFFSET m` | `OFFSET m` | `LIMIT 18446744073709551615 OFFSET m` | `OFFSET m` (refuses `LIMIT -1`) | Emulate, as each manual says |
| Default `NULL` order | smallest | largest | smallest | last, both directions, unless `default_null_order` says otherwise | Common: smallest |
| `x NULLS LAST` (`ASC`) | `x NULLS LAST` (from 3.30) | `x` | `x IS NULL, x` | `x NULLS LAST` | `NULLS` where the default differs, and always for DuckDB, whose default is a setting; MySQL, which lacks it, sorts by `x IS NULL` first, repeating `x` and its values (for a place or an alias, its item) |
| `CAST(x AS INTEGER)` | `INTEGER` | `BIGINT` | `SIGNED` | `BIGINT` | Type names map; floats and decimals to integer truncate in SQLite and round in the others (a float's halves to even, a decimal's away from zero), and text reads as its leading number in SQLite and MySQL (`'12abc'` is 12, `'Al'` is 0) but fails in the others: documented |
| `CAST(x AS DOUBLE)` | `REAL` | `DOUBLE PRECISION` | `DOUBLE` (MySQL 8.0.17) | `DOUBLE` | Map |
| `CAST(x AS TEXT)` | `TEXT` | `TEXT` | `CHAR` | `VARCHAR` | Map |
| `LIKE p ESCAPE '!'` | same | same | same | same | Same; refuse `\` and `'` as the escape (MySQL's backslash mode) |
| `LIKE p`, no `ESCAPE` | no escape | `\` escapes | `\` escapes; under `NO_BACKSLASH_ESCAPES`, MariaDB's still does, and MySQL's manual says MySQL's doesn't | no escape | Allow only a literal pattern without `\`, and for `mysqlNoBackslashEscapes` even alone |
| `LIKE` case | ASCII-insensitive | sensitive | per collation, usually insensitive | sensitive | Document |
| `7 / 2` | 3 | 3 | 3.5000 | 3.5 | Refuse without a known float operand; integer division later as a function |
| `x / 0` | `NULL` | error | `NULL` (error in strict-mode writes) | `inf` (`nan` for `0 / 0`); `%` fails on integers and gives `nan` on floats | Document |
| `LENGTH(s)` | `length` | `length` | `CHAR_LENGTH` (`LENGTH` counts bytes) | `length` | Map |
| `UPPER`, `LOWER` | ASCII only (without ICU) | full | full | full | Document |
| `'a' = 'A'`, trailing spaces | binary | per collation, usually binary | per collation: default ones ignore case, and `PAD SPACE` ones trailing spaces; MariaDB 11.8's default, `utf8mb4_uca1400_ai_ci`, ignores accents too, and MySQL 8.4's, `utf8mb4_0900_ai_ci`, accents but not trailing spaces (`NO PAD`) | binary | Document; collation is data |
| Comparison results | 1 and 0 | `true` and `false` | 1 and 0 | `true` and `false` | Document; adapters may convert |
| `1.5` | a float | exact `numeric` | exact `DECIMAL` | exact `DECIMAL` | Document |
| `AVG` of integers | float | `numeric` | `DECIMAL` | `DOUBLE` | Document |
| `SUM` of integers | integer | `numeric` | `DECIMAL` | `HUGEINT` (128 bits) | Document |
| A `$1` with no context | n/a | sent untyped, read as text (from 10; before, it fails) | n/a | n/a | Cast to the value's type alone in a `SELECT` list, and among `CASE` results or `COALESCE` or `NULLIF` arguments when nothing else there has a type |
| Subquery in `FROM` | alias optional | required before 16 | required | optional | Grammar requires an alias |

Sources (to recheck, since the container's firewall blocked the
manuals when this was written): SQLite's [`SELECT`](https://www.sqlite.org/lang_select.html),
[expressions](https://www.sqlite.org/lang_expr.html), and
[datatypes](https://www.sqlite.org/datatype3.html); PostgreSQL's
[lexical structure](https://www.postgresql.org/docs/current/sql-syntax-lexical.html)
(name folding, numeric constants, and precedence),
[pattern matching](https://www.postgresql.org/docs/current/functions-matching.html),
[sorting](https://www.postgresql.org/docs/current/queries-order.html),
[`LIMIT`](https://www.postgresql.org/docs/current/queries-limit.html),
and [math functions](https://www.postgresql.org/docs/current/functions-math.html);
MySQL's [`SELECT`](https://dev.mysql.com/doc/refman/8.4/en/select.html),
[`UPDATE`](https://dev.mysql.com/doc/refman/8.4/en/update.html),
[`LIKE`](https://dev.mysql.com/doc/refman/8.4/en/string-comparison-functions.html),
[casts](https://dev.mysql.com/doc/refman/8.4/en/cast-functions.html),
[arithmetic](https://dev.mysql.com/doc/refman/8.4/en/arithmetic-functions.html),
[sorting](https://dev.mysql.com/doc/refman/8.4/en/sorting-rows.html),
[name case](https://dev.mysql.com/doc/refman/8.4/en/identifier-case-sensitivity.html),
and [SQL modes](https://dev.mysql.com/doc/refman/8.4/en/sql-mode.html);
MariaDB's [`CAST`](https://mariadb.com/kb/en/cast/) and
[SQL modes](https://mariadb.com/kb/en/sql-mode/); and DuckDB's
[`ORDER BY`](https://duckdb.org/docs/current/sql/query_syntax/orderby),
[pattern matching](https://duckdb.org/docs/current/sql/functions/pattern_matching),
[numeric functions](https://duckdb.org/docs/current/sql/functions/numeric),
and [casting](https://duckdb.org/docs/current/sql/expressions/cast).
The engine corpus (`tests/engines/common_corpus.py`, under
[Testing](#testing)) pins the rows: it runs on SQLite 3.45.1 and
DuckDB 2.0.0 locally and in CI's `py` job, and on PostgreSQL 18,
MariaDB 11.8, and MySQL 8.4 in its `engines` job; [engine checks](#engine-checks) has
each row's status. Checked on SQLite and DuckDB (2026-11-09):

- **Confirmed:** `OFFSET` alone (and DuckDB refuses `LIMIT -1`), the
  default `NULL` orders (DuckDB's last in both directions), `NULLS
  FIRST` and `LAST`, the cast type names, `||` on numbers (`1 || 2` is
  `'12'` in both), `LIKE`'s case, `7 / 2`, `x / 0` (and `%` by zero
  failing in DuckDB), float to integer (SQLite truncates, DuckDB
  rounds, its halves as [engine checks](#engine-checks) says),
  `LOWER` past ASCII, comparison results, `1.5`'s type, and `AVG`'s.
- **Corrected:** SQLite reads text cast to `INTEGER` as its leading
  number (`'12abc'` is 12), not 0; DuckDB's `NULL` order is a setting,
  so rendering always writes `NULLS` for it; DuckDB's `SUM` of integers
  is a 128-bit `HUGEINT`; and `SUBSTR` with a start below 1 or a
  negative length reads the same in SQLite and DuckDB, so that check
  applies only beside PostgreSQL or MySQL.

Empty strings and `NULL` are distinct on all four; Oracle, later,
differs. Prior art compiles one tree per dialect the same way (SQLGlot,
SQLAlchemy, Knex, and jOOQ, whose commercial dialects make it a source
of ideas only); Wherewith copies none of their code or tables.

### Engine checks

Each rule above that came from the manuals is a case in the engine
corpus (`tests/engines/common_corpus.py`): a common query; one built
unchecked, for what the checks refuse; or, for what the parser
refuses, SQL run on the engine as written. Each case names its claim
here, so a failing run says which row to fix. SQLite 3.45.1 and DuckDB
2.0.0 run locally and in CI's `py` job, and PostgreSQL 18, MariaDB
11.8.9, and MySQL 8.4 in its `engines` job, MariaDB and MySQL in four
SQL modes, through the same runner with each engine's own expected
rows. CI's first run (2026-11-10) confirmed every PostgreSQL row, and
every MariaDB row but four, corrected below: `ORDER BY` expressions, a
negative integer in `ORDER BY`, `INSERT … VALUES` reading its own
table, and `LIKE`'s `\` under `NO_BACKSLASH_ESCAPES`. MySQL 8.4 joined
after that run, so its column gives what the manual and the claims
expect, pending CI, with the case that checks each MySQL-only claim;
its default SQL mode adds `ONLY_FULL_GROUP_BY` to MariaDB's. MariaDB
10.6 isn't in CI, so claims about it stay unconfirmed.

Rendering, from the [table](#rendering-per-dialect):

| Row | SQLite and DuckDB | PostgreSQL and MariaDB | MySQL 8.4 |
| --- | --- | --- | --- |
| `\|\|`: casts, `CONCAT`, and integers beside text (`'a' \|\| 1` is `'a1'`) | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| `TRUE` and `FALSE`, `LIMIT` and `OFFSET`, and `OFFSET` alone (`LIMIT 18446744073709551615`) | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| `NULL` order, and `NULLS` (`x IS NULL, x` for MySQL) | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| `ORDER BY c`, qualified for PostgreSQL | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| `CAST` type names, and text that isn't a number | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB (`'Al'` is 0) |
| `CAST` of a float or decimal to `INTEGER` | Corrected: DuckDB rounds a float's halves to even (`7.5` is 8, `10.5` is 10) and a decimal's away from zero; SQLite truncates both | Confirmed: the same as DuckDB | Pending CI (MySQL 8.4): as MariaDB ("float to integer, halves" and "decimal to integer, halves") |
| `LENGTH` (`CHAR_LENGTH`), and `UPPER` and `LOWER` past ASCII | Confirmed | Confirmed, with PostgreSQL's locale `en_US.utf8`, as in its image | Pending CI (MySQL 8.4): as MariaDB |
| `LIKE` with `ESCAPE`, and `LIKE`'s case | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB, case-insensitive |
| `LIKE` without `ESCAPE`, with a `\` | Confirmed | Confirmed for PostgreSQL; corrected for MariaDB, whose `\` escapes in every mode, under `NO_BACKSLASH_ESCAPES` too; the check now refuses it for that profile even alone | Pending CI (MySQL 8.4): `\` escapes by default and, as the manual says, not at all under `NO_BACKSLASH_ESCAPES` (the probe's `mysql_nbe` rows), unlike MariaDB; that disagreement under one profile is why it's refused there even alone |
| `7 / 2` | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| `x / 0` | Corrected: DuckDB's `/` gives `inf` (`nan` for `0 / 0`) on integers too, and `%` fails only on integers, giving `nan` on floats | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| `'a' = 'A'`, trailing spaces | Confirmed | Confirmed, with MariaDB's default collation (`utf8mb4_uca1400_ai_ci`) ignoring accents and trailing spaces | Pending CI (MySQL 8.4): the default collation, `utf8mb4_0900_ai_ci`, ignores case and accents but, being `NO PAD`, not trailing spaces, unlike MariaDB's |
| Comparison results, `1.5`, `AVG`, and `SUM` | Confirmed | Confirmed | Pending CI (MySQL 8.4): as MariaDB |
| A `$1` with no context | n/a | Corrected and confirmed: sent untyped, PostgreSQL reads it as text, so a number comes back as text; the casts give values their types, alone and in `COALESCE`, `CASE`, `NULLIF`, and `\|\|` | n/a |
| Subquery in `FROM` | Confirmed: no alias needed | Confirmed: MariaDB needs one; PostgreSQL 18 doesn't | Pending CI (MySQL 8.4): an alias is required (error 1248) |

Expression rules, from the [parser](#the-parser) and the
[checks](#the-check-stage):

| Rule | SQLite and DuckDB | PostgreSQL and MariaDB | MySQL 8.4 |
| --- | --- | --- | --- |
| `\|\|` beside arithmetic | Confirmed: SQLite reads `1 + 2 \|\| 'a'` as `1 + (2 \|\| 'a')`, which is 3, and DuckDB as `'3a'` | Confirmed (MariaDB's `\|\|` is `OR`) | Pending CI (MySQL 8.4): as MariaDB (`\|\|` is a deprecated `OR`) |
| `TRIM`'s second argument | Confirmed: a set of characters; SQLite has no `TRIM(r FROM s)`, and DuckDB reads `r` there as a set too | Corrected and confirmed: PostgreSQL takes a set, and MariaDB no second argument, but `TRIM(r FROM s)`, removing a whole string, as MySQL's manual says MySQL does | Pending CI (MySQL 8.4): no second argument, and `TRIM(r FROM s)` removes a whole string |
| `%` with a float | Confirmed: SQLite truncates (`5.5 % 2` is 1.0) | Confirmed (PostgreSQL has no `%` for `DOUBLE PRECISION`) | Pending CI (MySQL 8.4): as MariaDB |
| Floats in `\|\|` or cast to `TEXT` | Confirmed: both write `2.0`, and SQLite 15 digits | Confirmed: `2` | Pending CI (MySQL 8.4): as MariaDB |
| Booleans in `\|\|` and casts | Confirmed: `1` in SQLite, `true` in DuckDB | Confirmed: `true` in PostgreSQL, which casts a boolean only to text and 32-bit integers, and `1` in MariaDB | Pending CI (MySQL 8.4): as MariaDB |
| `ESCAPE` before an ordinary character | Confirmed alike: it matches the character (refused anyway, as a likely mistake) | Confirmed: alike | Pending CI (MySQL 8.4): alike |
| `ESCAPE` at the end of a pattern | Confirmed: SQLite matches nothing, DuckDB fails | Confirmed: PostgreSQL fails, MariaDB reads it as itself | Pending CI (MySQL 8.4): as MariaDB |
| Text in arithmetic | Confirmed: SQLite converts (`'1' + 1` is 2, `'Al' + 1` is 1); DuckDB refuses, but reads a string beside a `DOUBLE` as one | Confirmed: PostgreSQL types a string literal from the other operand (`'1' + 1` is 2, `'1.5' + 1` fails) and refuses text columns; MariaDB converts | Pending CI (MySQL 8.4): as MariaDB |

Statement rules, from the [parser](#the-parser) and the
[checks](#the-check-stage):

| Rule | SQLite and DuckDB | PostgreSQL and MariaDB | MySQL 8.4 |
| --- | --- | --- | --- |
| Clauses without `FROM` (`WHERE`, `ORDER BY`, `LIMIT`) | Confirmed: taken | Confirmed: taken by PostgreSQL and MariaDB 11.8; MariaDB 10.6 unconfirmed | Pending CI (MySQL 8.4): taken |
| A subquery reading the table an `UPDATE` or `DELETE` changes | Confirmed: taken | Confirmed: taken by PostgreSQL and MariaDB (from 10.3) | Pending CI (MySQL 8.4): error 1093 ("UPDATE reading its own table" and "DELETE reading its own table"), which the check for both MySQL profiles rests on |
| The same in `INSERT … VALUES` | Confirmed: taken | Corrected: taken by MariaDB too, and PostgreSQL | Pending CI (MySQL 8.4): error 1093 ("INSERT VALUES reading its own table"), which alone justifies the check |
| `LIMIT` in an `IN` subquery | Confirmed: taken | Confirmed: PostgreSQL takes it, MariaDB refuses it | Pending CI (MySQL 8.4): error 1235 ("LIMIT in an IN subquery"), which the check rests on, with MariaDB |
| `*` beside other items | Confirmed: taken | Confirmed: PostgreSQL takes both, MariaDB `*, a` but not `a, *` | Pending CI (MySQL 8.4): `*, a` taken and `a, *` refused ("* before other items" and "* after other items"), as in MariaDB; if so, the check could refuse only the second |
| Alias or column, in `WHERE` and `GROUP BY`, and in `HAVING` for a grouped column | Confirmed: the column | Confirmed: the column | Pending CI (MySQL 8.4): the column |
| The same in `HAVING`, for a column not grouped | Confirmed they differ: SQLite reads the column, DuckDB the alias | Confirmed: PostgreSQL fails, MariaDB reads the alias | Pending CI (MySQL 8.4): the alias |
| The same inside `ORDER BY` expressions | Confirmed: the column | Confirmed for PostgreSQL, the column; corrected for MariaDB, the column too | Pending CI (MySQL 8.4): the alias, as the manual says ("ORDER BY an expression of a column that's also an alias"), the only engine to read it; the alias checks refuse it everywhere anyway |
| Constants in `ORDER BY` and `GROUP BY` | Confirmed: SQLite skips `'a'` and `1.5` but reads `-1` as a place, failing; DuckDB refuses `'a'` and `1.5`, and reads `-1` as a place too; both group everything by `'a'` | Confirmed for PostgreSQL, which refuses all three and `GROUP BY 'a'`; corrected for MariaDB, which skips `'a'` and `1.5` but refuses `-1` ("Unknown column '-1'"), so `-1` fails everywhere | Pending CI (MySQL 8.4): as MariaDB |
| `SELECT DISTINCT` ordered by a column not selected | Confirmed: taken, in different orders | Confirmed: PostgreSQL refuses it, MariaDB takes it | Pending CI (MySQL 8.4): error 3065 ("SELECT DISTINCT ordered by a column not selected") |
| `ON` reading a table joined after it | Confirmed: SQLite takes it, DuckDB fails | Confirmed: both fail | Pending CI (MySQL 8.4): fails |
| A column twice in `INSERT` or `SET` | Confirmed: SQLite takes both, DuckDB refuses both | Confirmed: PostgreSQL refuses both; MariaDB refuses `INSERT` and assigns `SET` left to right | Pending CI (MySQL 8.4): as MariaDB |
| A `SET` reading a column set before it | Confirmed: the old value | Pending CI: the old value in PostgreSQL, and the new in MariaDB, left to right ("SET reading a column set before it, read back") | Pending CI (MySQL 8.4): the new, which the `UPDATE … SET` trap rests on |

### Testing

- **Unit tests in Temper**, on every backend: each construct's
  canonical form and its rendering for each profile; every template
  mistake and check refusal, with its position; and each rendering
  passing that database's own `QueryBuilder` lexer, a cheap oracle
  that the output reads as one statement with holes in code.
- **The same query on every engine:** a corpus of common queries runs
  in `tests/engines/` against a fixture table with `NULL`s, negative
  numbers, mixed case, trailing spaces, and non-ASCII text, on SQLite
  and DuckDB in the `py` job and PostgreSQL, MariaDB, and MySQL 8.4 in
  the `engines` job. Results
  are normalized (booleans to integers, decimals to floats) and must
  match across engines; documented differences are asserted to still
  differ, so the table above can't go stale. Built: the corpus in
  `common_corpus.py`, which each runner runs, with random queries
  rendered for the engine and checked against SQLite, and the
  [engine checks](#engine-checks): cases built unchecked and SQL run
  as written, for what the checks and the parser refuse.
- **Fuzzing,** seeded in CI and longer locally: a grammar-based
  generator makes random subset queries that must parse, print back
  canonically to the same tree, render for each target, be accepted
  by each engine, and give matching results; and mutations of valid
  templates (dropped, swapped, or inserted tokens and characters) must
  parse or fail with a position, never crash or hang.

### Plan

Each chunk is one commit, tested on every backend:

1. **Lexer and tag** (done, 2026-11-09): `Dialect.common`, the `sql`
   tag, tokens, holes by kind, and errors with positions. Common
   queries render only for `Dialect.common`, as written, until
   chunk 4.
2. **Expressions** (done, 2026-11-09): the tree, the expression
   parser, the canonical printer, the depth limit, and the checks an
   expression alone can show.
3. **Statements** (done, 2026-11-09): `SELECT`, `INSERT`, `UPDATE`,
   and `DELETE`, subqueries in place or as holes, nesting, builder
   targets, and the checks a statement shows. The tag parses and
   checks at construction, and common queries render canonically.
4. **Rendering** (done, 2026-11-09): every profile, with the table
   above, the per-database lexer oracle, recorded targets that relax
   the expression checks, and the engine corpus, checked on SQLite and
   DuckDB.
5. **Check stage** (medium, ~500): every rule above, at construction
   and at render.
6. **Engines** (medium): the rest of the rules from manuals confirmed
   on PostgreSQL and MariaDB in CI, a MySQL service, and the statement
   rules' corpus. Cases written and confirmed on SQLite, DuckDB,
   PostgreSQL 18, and MariaDB 11.8 (2026-11-10), with four MariaDB
   rows corrected; a MySQL 8.4 service added, its rows pending CI. See
   [engine checks](#engine-checks).
7. **Fuzzing** (small to medium): the generator and mutations.
8. **Docs** (done, 2026-11-09): the README, the site, and the demos
   lead with the common dialect.
9. **Tour** (done, 2026-11-10): `demos/tour/` in every language, and
   in Temper as a test, all printing the same, on the site with each
   step's code and output. See [the tour](#the-tour-2026-11-10).

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
  - **The common corpus (done):** each runner, in each setting, also
    runs `common_corpus.py`: common queries rendered for its engine,
    on a fixture filled by a rendered `INSERT`, giving the same rows
    everywhere but where the [rendering table](#rendering-per-dialect)
    documents a difference, which must still differ; writes read back;
    and random queries, checked against SQLite.
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

### The common dialect (2026-11-09)

The general rule: the more compatible the better. Prefer choices that
accept the most SQL that means the same on every target, and stay
closest to standard SQL.

1. **Tag name:** `sql`, short and the obvious default; imports are
   explicit, so a clash is local.
2. **`NULL` order** when `ORDER BY` doesn't say: smallest first, as
   SQLite and MySQL do, so only PostgreSQL and DuckDB get an explicit
   `NULLS` when rendering.
3. **Bare names:** lowercase only, and always quoted on output; never
   folded silently, which would hide mismatches with MySQL's
   case-sensitive table names.
4. **Division:** `/` is refused unless an operand is known to be a
   float (a float value, a decimal literal, or a `CAST` to `DOUBLE`);
   integer division comes later as a function.
5. **`LIKE` without `ESCAPE`:** only for literal patterns with no `\`.
6. **`\` in string literals:** refused for the default `mysql` profile,
   with a hint to bind the value; `mysqlNoBackslashEscapes` takes them.
   The lexer refuses them when `mysql` is a target, as it is by
   default.
7. **Expression fragments** (`sql"active AND age > ${n}"`): yes, right
   after statements.
8. **PostgreSQL parameter types:** casts only where a parameter's type
   is unknown (the select list, `COALESCE`, `CASE` results, and `||`),
   checked by the engine tests.
9. **`UPDATE` and `DELETE` without `WHERE`:** allowed, as SQL does;
   maybe an opt-in check later.
10. **Collation:** MySQL's case-insensitive comparisons are documented,
    not forced; the collation is the schema's choice, and forcing one
    defeats indexes.
11. **Minimum versions:** SQLite 3.30, the oldest PostgreSQL the
    project still supports, MySQL 8.0.17, MariaDB 10.6, and DuckDB
    1.0, each tested on current releases. MySQL 8.0 and MariaDB 10.6
    are past their end of life, but staying compatible costs little.
12. **Rendering before the renderer:** until the renderer landed (chunk
    4), a common query rendered only for `Dialect.common`, rather than
    passing text through where it happened to be exact.
13. **Rendering only for targets:** a common query records the targets
    it was checked for, and renders only for them; narrower targets
    relax the checks for constructs those targets read alike.

### The tour (2026-11-10)

The tour walks through the whole public API in nine steps, each
printing a `## N. Title` heading and what it shows: writing a query
once, values bound and never spliced, what's refused when a query is
built, what each database needs written differently, queries in
queries, building queries in code (with `targets`), placeholder
styles, each database's own SQL, and quoting by hand. A reader
choosing between Wherewith and a query builder, an ORM, or SQLGlot
should see what none of them do: a query that would give different
results on different databases is refused before it runs, with the
line, the column, and why.

1. **One program per language,** in `demos/tour/`, built and run with
   each language's own tools, printing exactly `demos/tour/expected.txt`
   (85 lines). `demos/run.py` runs the tour after the example, and CI
   runs it after each backend's tests.
2. **Temper too,** as a test (`src/tour-tests.temper.md`), since only
   Temper has the `sql` tag: the other languages build each common
   query with a `QueryBuilder`, as the tag does. The test collects the
   lines it would print and checks them against its `tourOutput`, on
   every backend, and `demos/run.py` checks that `tourOutput` is
   `expected.txt`. The site shows it after the seven languages, with
   Python still the default.
3. **Problems as text:** none of the exceptions carries a message, so
   the tour prints `templateProblem` and `renderProblem`, which say
   why without building or rendering, and catches an exception only
   in the last step, to show each language's form of it.
4. **Snippet blocks:** each step is a block between `snippet: NAME` and
   `end snippet`, as in the example; a step may take more than one
   block, such as a helper and the code that calls it, and the site
   shows them in order. Every program must have every step.
5. **Run in your browser,** as on the other libraries' sites: the page
   loads the JS library only when asked, and the site's build runs the
   JS tour the same way in Node, failing unless it prints
   `expected.txt`.
6. **No real engines:** the tour stops at what the driver gets, so its
   output is the same everywhere; the engine round trips run such
   queries for real.
7. **Refreshing:** later chunks change messages and add refusals,
   which touch only `expected.txt` and the Temper's `tourOutput`
   (`demos/run.py` prints what to paste there).
