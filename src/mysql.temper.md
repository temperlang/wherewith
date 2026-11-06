# MySQL and MariaDB

## Profiles

`Dialect.mysql` and `Dialect.mysqlNoBackslashEscapes`, in the
[core](core.temper.md), quote names in `` `…` `` with `` ` `` doubled,
which works whether or not `ANSI_QUOTES` is on, and strings in `'…'`
with `'` doubled. MariaDB shares these profiles.

MySQL and MariaDB limit most names to 64 characters, within the Basic
Multilingual Plane, and not ending in a space.

The default profile, `Dialect.mysql`, works in every SQL mode: strings
escape `\`, NUL, and Ctrl-Z with a backslash, which reads back exactly
in the default mode, and only reads back with extra backslashes under
`NO_BACKSLASH_ESCAPES`, never unsafely.

For servers known to run with `NO_BACKSLASH_ESCAPES`,
`Dialect.mysqlNoBackslashEscapes` leaves backslashes alone, so they
read back exactly. **It's unsafe on a server without that mode**, where
a value ending in `\` would escape the closing quote. With nothing to
escape it, a NUL can't be written in its strings.

## Queries

The `mysql` tag makes a [Query](query.temper.md), checking the template
with MySQL's lexing rules, the same for MariaDB:

```temper inert
let q = mysql"SELECT id FROM t WHERE a = ${1}";
let r = q.render(Dialect.mysql, PlaceholderStyle.question) orelse panic();
r.sql; // SELECT id FROM t WHERE a = ?
```

Most drivers take `?` (`PlaceholderStyle.question`): Connector/C,
JDBC, MySqlConnector, `mysql2`, MariaDB Connector/Python, and Rust's
`mysql` and `sqlx`. PyMySQL and mysqlclient take `%s`
(`PlaceholderStyle.percentS`).

    export class MysqlTag {
      private b: QueryBuilder = new QueryBuilder(Dialect.mysql);

      public appendSafe(fixed: String): Void { b.appendSafe(fixed); }
      @overload("append")
      public appendString(x: String?): Void { b.appendString(x); }
      @overload("append")
      public appendInt(x: Int): Void { b.appendInt(x); }
      @overload("append")
      public appendInt64(x: Int64): Void { b.appendInt64(x); }
      @overload("append")
      public appendFloat64(x: Float64): Void { b.appendFloat64(x); }
      @overload("append")
      public appendBoolean(x: Boolean): Void { b.appendBoolean(x); }
      @overload("append")
      public appendValue(x: SqlValue): Void { b.appendValue(x); }
      @overload("append")
      public appendIdentifier(x: Identifier): Void { b.appendIdentifier(x); }
      @overload("append")
      public appendQuery(x: Query): Void { b.appendQuery(x); }

      public get accumulated(): Query { b.accumulated }
    }

    export let mysql = MysqlTag;

## Lexer

What `QueryBuilder` checks for MySQL and MariaDB, in every SQL mode:

- Quotes: strings in `'…'`, `"…"` as a string or, with `ANSI_QUOTES`,
  a name, and names in `` `…` ``.
- Backslashes: in strings they escape the next character, unless the
  server runs with `NO_BACKSLASH_ESCAPES`. Where the string ends only
  differs when a backslash comes before its quote or another
  backslash, so those are mistakes; bind such text as a parameter.
- Comments: `#` and `-- ` to the end of the line, and `/* */`, not
  nested. `--` is only a comment before a space or control character,
  so `5--1` is `5 - -1`; but `--` just before a hole is a mistake,
  since rendering adds a space there. Executable comments (`/*!` and
  MariaDB's `/*M!`) run their text as SQL, so they're mistakes too.
- Placeholders: `?`, so `?` can't be in the text outside quotes and
  comments, and neither can `$`, so `$1` can't look like one; names
  with `$` need quoting. User variables (`@a`) and `:=` are fine.

The lexer keeps its state from one run of text to the next.

    class MysqlLexer extends SqlLexer {
      private var state: Int = lexCode;

      public get inCode(): Boolean { state == lexCode }
      public get inLineComment(): Boolean { state == lexLineComment }

      public scan(text: String): String? {
        var problem: String? = null;
        var i = String.begin;
        let end = text.end;
        while (i < end) {
          let c = text[i];
          let next = text.next(i);
          let following = if (next < end) { text[next] } else { -1 };
          when (state) {
            lexCode -> if (c == char'\'') {
              state = lexSingleQuoted;
            } else if (c == char'"') {
              state = lexDoubleQuoted;
            } else if (c == char'`') {
              state = lexBackQuoted;
            } else if (c == char'#') {
              state = lexLineComment;
            } else if (c == char'-' && following == char'-') {
              let after = text.next(next);
              if (after >= end || text[after] <= 0x20) {
                state = lexLineComment;
              }
              i = next;
            } else if (c == char'/' && following == char'*') {
              let after = text.next(next);
              if (after < end && (text[after] == char'!' || hasAt(text, after, "M!"))) {
                problem = problem ?? "executable comment in template text";
              }
              state = lexBlockComment;
              i = next;
            } else if (c == char'?' || c == char'$') {
              problem = problem ?? stray;
            };
            lexSingleQuoted -> if (c == char'\'') {
              state = lexCode;
            } else if (c == char'\\' && (following == char'\'' || following == char'\\')) {
              problem = problem ?? backslashProblem;
            };
            lexDoubleQuoted -> if (c == char'"') {
              state = lexCode;
            } else if (c == char'\\' && (following == char'"' || following == char'\\')) {
              problem = problem ?? backslashProblem;
            };
            lexBackQuoted -> if (c == char'`') { state = lexCode; };
            lexLineComment -> if (c == char'\n') { state = lexCode; };
            else -> if (c == char'*' && following == char'/') {
              state = lexCode;
              i = next;
            };
          }
          i = text.next(i);
        }
        problem
      }
    }

    let backslashProblem = "backslash before a quote or backslash in a string";
