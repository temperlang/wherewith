# Rendering Common Queries

A [common query](common.temper.md) renders for each database it was
checked for (its `targets`) from its syntax tree, through the
[printers](common-expressions.temper.md#printing), which ask the table
here for the pieces that differ. Rendering for `Dialect.common` writes
canonical common SQL instead.

```temper inert
let q = sql"SELECT name, coalesce(nick, name) AS shown FROM users
  WHERE id IN (${a}, ${b}) ORDER BY name NULLS LAST LIMIT ${10}";
q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql;
// SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users"
//   WHERE "id" IN ($1, $2) ORDER BY "name" LIMIT $3
q.render(Dialect.mysql, PlaceholderStyle.question).sql;
// SELECT `name`, COALESCE(`nick`, `name`) AS `shown` FROM `users`
//   WHERE `id` IN (?, ?) ORDER BY `name` IS NULL, `name` LIMIT ?
```

The same for every database:

- **Names** are always quoted, with the profile's `quoteName`, so no
  database's reserved words matter, and strings are quoted with its
  `quoteString`.
- **Parentheses** go around every operand that's an operator
  expression, but for the operands of `AND` and `OR`, since precedence
  differs: SQLite reads `'a' || 1 + 2` as `('a' || 1) + 2`, PostgreSQL
  and DuckDB as `'a' || (1 + 2)`, and MySQL's `NOT` binds tighter with
  `HIGH_NOT_PRECEDENCE`. A minus before a negative number is then
  `- (-1)`, never a comment.
- **Keywords** are written as in canonical common SQL, with `AS` before
  every alias, and `<>` for `!=`.

Where they differ (the [design](../docs/design.md#rendering-per-dialect)
has the whole table, with what's only documented):

| Common | SQLite | PostgreSQL | MySQL and MariaDB | DuckDB |
| --- | --- | --- | --- | --- |
| `a \|\| b` | `a \|\| b` | `a \|\| b`, with casts | `CONCAT(a, b)` | `a \|\| b` |
| `OFFSET m` alone | `LIMIT -1 OFFSET m` | `OFFSET m` | `LIMIT 18446744073709551615 OFFSET m` | `OFFSET m` |
| `NULLS FIRST` or `LAST` | where it differs from smallest | where it differs from largest | `x IS NULL, x` where it differs from smallest | always |
| `CAST(x AS INTEGER)` | `INTEGER` | `BIGINT` | `SIGNED` | `BIGINT` |
| `CAST(x AS DOUBLE)` | `REAL` | `DOUBLE PRECISION` | `DOUBLE` | `DOUBLE` |
| `CAST(x AS TEXT)` | `TEXT` | `TEXT` | `CHAR` | `VARCHAR` |
| `LENGTH(s)` | `LENGTH` | `LENGTH` | `CHAR_LENGTH` | `LENGTH` |
| `SUBSTR(s, i, n)` | `SUBSTR` | `SUBSTR`, `i` and `n` cast to `INTEGER` | `SUBSTR` | `SUBSTR` |

`NULL` order follows the [decided rule](../docs/design.md#decided):
without `NULLS`, nulls sort as the smallest values, as in SQLite and
MySQL. PostgreSQL sorts them as the largest, so it gets `NULLS FIRST`
going up; DuckDB's order depends on its `default_null_order` setting,
so it always gets `NULLS`. MySQL has no `NULLS`, so where its order
differs, the item goes after `x IS NULL` (or `x IS NULL DESC`), which
repeats `x` and its values; for a place (`ORDER BY 2`) or an alias,
`x` is the item it stands for.

PostgreSQL reads a column alone in `ORDER BY` as a `SELECT` item it
names after the column, if there is one, such as `CAST(c AS TEXT)`, so
rendering writes the column with its table there, `t.c`, as the
[output names](common-statements.temper.md#output-names) say.

PostgreSQL types a parameter from what's around it (with drivers that
send values untyped, such as `pg`): as text beside only values and
strings (`'10' < '9'`), as a literal's type beside one (a 32-bit
`INTEGER` for `1`), or not at all, failing. So a value gets a cast to
its own type wherever nothing but values and literals is beside it:
alone as a `SELECT` item, and in comparisons, arithmetic, `IN` lists,
`BETWEEN`, `CASE`, `COALESCE`, and `NULLIF`; and always after a sign,
before `IS NULL`, as a simple `CASE`'s subject, and in `ABS`, `MIN`,
`MAX`, `SUM`, `AVG`, and `COUNT`. A column beside it, or an expression
of its type, types it instead, so it stays bare, except a float value
beside a column, which an integer column would read as a `BIGINT`. Its `||` takes text
on one side, so each value there is cast to `TEXT`, and so is the
first operand when neither of the first two is text (`1 || 2` is
`'12'` everywhere). Its `SUBSTR` takes only 32-bit integers, so a
start or length that isn't one, such as a `BIGINT` column, is cast to
`INTEGER`.

A float value of zero binds as `0.0`, since SQLite stores `-0.0` as
`0.0` and DuckDB keeps its sign.

After writing, a database's SQL goes through that database's own
lexer, as a `QueryBuilder` for it would check it, so a value can't land
in a quote or comment; rendering refuses if it ever finds a problem.

## The table

Each database's pieces. Both MySQL profiles write the same, but for
strings, which each quotes its own way.

    class CommonTarget(
      public dialect: Dialect,
      // CAST's type names for INTEGER, DOUBLE, and TEXT, after "".
      public castNames: List<String>,
      public lengthName: String,
      // Whether `||` is written as CONCAT(…).
      public concatCall: Boolean,
      // Whether values get casts where their type is unknown.
      public castsUnknown: Boolean,
      public nulls: Int,
      // The LIMIT for OFFSET alone, or "" for none.
      public noLimit: String,
    ) {}

Where each database puts nulls without `NULLS`: as the smallest values
(and it takes `NULLS`), as the largest, depending on a setting (so
`NULLS` is always written), or as the smallest without taking `NULLS`.

    let nullsSmallest = 0;
    let nullsLargest = 1;
    let nullsWritten = 2;
    let nullsEmulated = 3;

    let commonTarget(dialect: Dialect): CommonTarget {
      let lexing = lexingName(dialect);
      if (lexing == "sqlite") {
        new CommonTarget(dialect, ["", "INTEGER", "REAL", "TEXT"], "LENGTH", false, false, nullsSmallest, "-1")
      } else if (lexing == "postgres") {
        new CommonTarget(dialect, ["", "BIGINT", "DOUBLE PRECISION", "TEXT"], "LENGTH", false, true, nullsLargest, "")
      } else if (lexing == "mysql") {
        new CommonTarget(
          dialect, ["", "SIGNED", "DOUBLE", "CHAR"], "CHAR_LENGTH", true, false, nullsEmulated,
          "18446744073709551615",
        )
      } else {
        new CommonTarget(dialect, ["", "BIGINT", "DOUBLE", "VARCHAR"], "LENGTH", false, false, nullsWritten, "")
      }
    }
