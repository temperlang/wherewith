# SQLite

## Profile

`Dialect.sqlite`, in the [core](core.temper.md), quotes names in `"…"`
and strings in `'…'`, doubling the quote inside. SQLite has no
backslash escapes and no limit on names. A NUL can't be written in a
string, since SQLite's parser ends the text there.

## Queries

The `sqlite` tag makes a [Query](query.temper.md) with each value bound
as a parameter, never written into the SQL text, checking the template
with SQLite's lexing rules:

```temper inert
let name = "Robert'); DROP TABLE students; --";
let q = sqlite"SELECT id FROM students WHERE name = ${name} AND age > ${7}";
let r = q.render(Dialect.sqlite, PlaceholderStyle.question) orelse panic();
r.sql; // SELECT id FROM students WHERE name = ? AND age > ?
```

Most SQLite drivers take `?` parameters in order: `sqlite3` in C and
C++, JDBC in Java, `node:sqlite` and `better-sqlite3` in JavaScript,
`lsqlite3` in Lua, `sqlite3` in Python, and `rusqlite` in Rust. C#'s
`Microsoft.Data.Sqlite` binds by name, so it takes
`PlaceholderStyle.atNamed`.

Holes take values (as parameters), an `Identifier` (quoted when
rendered), or another `Query` (in place, with its parameters).

    export class SqliteTag {
      private b: QueryBuilder = new QueryBuilder(Dialect.sqlite);

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

    export let sqlite = SqliteTag;

## Lexer

What `QueryBuilder` checks for SQLite:

- Quotes: strings in `'…'`, and names in `"…"`, `` `…` ``, or `[…]`.
- Comments: `--` to the end of the line, and `/* */`, not nested.
- Placeholders: `?`, `:a`, `@a`, and `$a`, so `?`, `:`, `@`, and `$`
  can't be in the text outside quotes and comments. That rules out `$`
  in bare names too, such as `a$b`, which SQLite allows; quote those.

The lexer keeps its state from one run of text to the next.

    class SqliteLexer extends SqlLexer {
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
            } else if (c == char'[') {
              state = lexBracketed;
            } else if (c == char'-' && following == char'-') {
              state = lexLineComment;
            } else if (c == char'/' && following == char'*') {
              state = lexBlockComment;
              i = next;
            } else if (c == char'?' || c == char':' || c == char'@' || c == char'$') {
              problem = problem ?? stray;
            };
            lexSingleQuoted -> if (c == char'\'') { state = lexCode; };
            lexDoubleQuoted -> if (c == char'"') { state = lexCode; };
            lexBackQuoted -> if (c == char'`') { state = lexCode; };
            lexBracketed -> if (c == char']') { state = lexCode; };
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
