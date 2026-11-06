# PostgreSQL

## Profile

`Dialect.postgres`, in the [core](core.temper.md), quotes names in
`"…"` and strings in `'…'`, doubling the quote inside.

PostgreSQL truncates names longer than 63 bytes, so two long names
could become the same one; Wherewith rejects them instead.

The profile assumes `standard_conforming_strings` is on, the default
since PostgreSQL 9.1, so backslashes in strings are plain characters.
Wherewith never writes `E'…'` strings. A NUL can't be written in a
string, since PostgreSQL's text can't hold one.

## Queries

The `postgres` tag makes a [Query](query.temper.md), checking the
template with PostgreSQL's lexing rules:

```temper inert
let q = postgres"SELECT id FROM t WHERE tags::text LIKE ${"a%"}";
let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
r.sql; // SELECT id FROM t WHERE tags::text LIKE $1
```

Drivers differ: libpq, `pg`, asyncpg, `tokio-postgres`, and `sqlx` take
`$1` (`PlaceholderStyle.dollarNumbered`), psycopg takes `%s`
(`PlaceholderStyle.percentS`), and JDBC takes `?`
(`PlaceholderStyle.question`).

    export class PostgresTag {
      private b: QueryBuilder = new QueryBuilder(Dialect.postgres);

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

    export let postgres = PostgresTag;

## Lexer

What `QueryBuilder` checks for PostgreSQL:

- Quotes: strings in `'…'`, names in `"…"`, and dollar quotes,
  `$$…$$` or `$tag$…$tag$`. An `E'…'` string also reads backslash
  escapes, so `\'` doesn't end it.
- Comments: `--` to the end of the line, and `/* */`, which nest.
- Placeholders: `$1` on the server, and `?` for JDBC. So `?` can't be
  in the text outside quotes and comments (write JSON operators such
  as `?` and `?|` as functions, `jsonb_exists` and
  `jsonb_exists_any`), and `$` only starts a dollar quote, so names
  with `$` need quoting. Casts (`::`) and operators with `@` are fine.

The lexer keeps its state from one run of text to the next.

    class PostgresLexer extends SqlLexer {
      private var state: Int = lexCode;
      private var depth: Int = 0;
      private var tag: String = "";

      public get inCode(): Boolean { state == lexCode }
      public get inLineComment(): Boolean { state == lexLineComment }

      public scan(text: String): String? {
        var problem: String? = null;
        var i = String.begin;
        let end = text.end;
        // The two code points before `c` in this run, or -1.
        var before = -1;
        var beforeThat = -1;
        while (i < end) {
          let start = i;
          let c = text[i];
          let next = text.next(i);
          let following = if (next < end) { text[next] } else { -1 };
          when (state) {
            lexCode -> if (c == char'\'') {
              let escapes = (before == char'E' || before == char'e') && !isWordChar(beforeThat);
              state = if (escapes) { lexEscapeString } else { lexSingleQuoted };
            } else if (c == char'"') {
              state = lexDoubleQuoted;
            } else if (c == char'-' && following == char'-') {
              state = lexLineComment;
            } else if (c == char'/' && following == char'*') {
              state = lexBlockComment;
              depth = 1;
              i = next;
            } else if (c == char'$') {
              let tagEnd = if (isWordChar(before)) { null } else { dollarTagEnd(text, next) };
              if (tagEnd == null) {
                problem = problem ?? stray;
              } else {
                let sb = new StringBuilder();
                sb.appendBetween(text, i, text.next(tagEnd));
                tag = sb.toString();
                state = lexDollarQuoted;
                i = tagEnd;
              }
            } else if (c == char'?') {
              problem = problem ?? stray;
            };
            lexSingleQuoted -> if (c == char'\'') { state = lexCode; };
            lexEscapeString -> if (c == char'\'') {
              state = lexCode;
            } else if (c == char'\\' && next < end) {
              i = next;
            };
            lexDoubleQuoted -> if (c == char'"') { state = lexCode; };
            lexLineComment -> if (c == char'\n') { state = lexCode; };
            lexDollarQuoted -> if (c == char'$' && hasAt(text, i, tag)) {
              state = lexCode;
              // Skip to the tag's last `$`.
              var j = i;
              for (var k = text.next(String.begin); tag.hasIndex(k); k = tag.next(k)) {
                j = text.next(j);
              }
              i = j;
            };
            else -> if (c == char'/' && following == char'*') {
              depth += 1;
              i = next;
            } else if (c == char'*' && following == char'/') {
              depth -= 1;
              if (depth == 0) { state = lexCode; }
              i = next;
            };
          }
          beforeThat = if (i == start) { before } else { c };
          before = text[i];
          i = text.next(i);
        }
        problem
      }
    }

`dollarTagEnd` finds the `$` that ends a dollar quote's opening tag,
which starts at `i`, just after its first `$`. A tag is empty, or a
name's letters, digits, and `_`, not starting with a digit. It's null
if there's no such tag in this run.

    let dollarTagEnd(text: String, i: StringIndex): StringIndex? {
      let end = text.end;
      var j = i;
      while (j < end) {
        let c = text[j];
        if (c == char'$') { return j; }
        let ok = (c >= char'a' && c <= char'z') || (c >= char'A' && c <= char'Z') ||
          c == char'_' || c >= 0x80 || (c >= char'0' && c <= char'9' && j != i);
        if (!ok) { return null; }
        j = text.next(j);
      }
      null
    }
