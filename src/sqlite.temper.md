# SQLite

## Profile

`Dialect.sqlite`, in the [core](core.temper.md), quotes names in `"…"`
and strings in `'…'`, doubling the quote inside. SQLite has no
backslash escapes and no limit on names. A NUL can't be written in a
string, since SQLite's parser ends the text there.

## Queries

The `sqlite` tag writes a query for SQLite with each value bound as a
parameter, never written into the SQL text:

```temper inert
let name = "Robert'); DROP TABLE students; --";
let q = sqlite"SELECT id FROM students WHERE name = ${name} AND age > ${7}";
q.sql; // SELECT id FROM students WHERE name = ? AND age > ?
```

Most SQLite drivers take `?` parameters in order: `sqlite3` in C and
C++, JDBC in Java, `node:sqlite` and `better-sqlite3` in JavaScript,
`lsqlite3` in Lua, `sqlite3` in Python, and `rusqlite` in Rust. C#'s
`Microsoft.Data.Sqlite` binds by name, so it will need named
placeholders. Those, and queries for PostgreSQL and MySQL with each
driver's placeholders, come later; see the [design](../docs/design.md).

Holes take values (as parameters), an `Identifier` (written quoted),
or another `SqliteQuery` (written as SQL, with its parameters in
place).

    export class SqliteQuery(public sql: String, public params: List<SqlValue>) {
      public toString(): String { sql }
    }

## SqliteBuilder

The tag's builder. Its template text is trusted SQL, but it's still
checked, so a mistake can't misplace parameters:

- A hole must be where an expression goes, not inside a string, a
  name, or a comment, where `?` would just be text.
- The text can't have its own parameters (`?`, `:a`, `@a`, or `$a`),
  which would shift every hole's place. That rules out `$` in bare
  names too, such as `a$b`, which SQLite allows; quote those.
- The text can't end inside a quote or a block comment.

A mistake panics when the tag is used. `build` reports it by bubbling
instead.

    export class SqliteBuilder {
      private sb: StringBuilder = new StringBuilder();
      private params: ListBuilder<SqlValue> = new ListBuilder<SqlValue>();
      private var state: Int = stateTop;
      private var problem: String? = null;
      private var endsWithSpace: Boolean = true;
      private var pendingSpace: Boolean = false;

      public appendSafe(fixed: String): Void {
        if (fixed.isEmpty) { return; }
        if (pendingSpace && !isSpace(fixed[String.begin])) { sb.append(" "); }
        pendingSpace = false;
        endsWithSpace = isSpace(fixed[fixed.prev(fixed.end)]);
        var i = String.begin;
        let end = fixed.end;
        while (i < end) {
          let c = fixed[i];
          let next = fixed.next(i);
          let following = if (next < end) { fixed[next] } else { -1 };
          when (state) {
            stateTop -> if (c == char'\'') {
              state = stateString;
            } else if (c == char'"') {
              state = stateDoubleQuoted;
            } else if (c == char'`') {
              state = stateBackQuoted;
            } else if (c == char'[') {
              state = stateBracketed;
            } else if (c == char'-' && following == char'-') {
              state = stateLineComment;
            } else if (c == char'/' && following == char'*') {
              state = stateBlockComment;
              i = next;
            } else if (c == char'?' || c == char':' || c == char'@' || c == char'$') {
              fail("parameter in template text");
            };
            stateString -> if (c == char'\'') { state = stateTop; };
            stateDoubleQuoted -> if (c == char'"') { state = stateTop; };
            stateBackQuoted -> if (c == char'`') { state = stateTop; };
            stateBracketed -> if (c == char']') { state = stateTop; };
            stateLineComment -> if (c == char'\n') { state = stateTop; };
            else -> if (c == char'*' && following == char'/') {
              state = stateTop;
              i = next;
            };
          }
          i = fixed.next(i);
        }
        sb.append(fixed);
      }

      @overload("append")
      public appendString(x: String?): Void {
        if (x == null) { param(new SqlNull()); } else { param(new SqlText(x)); }
      }
      @overload("append")
      public appendInt(x: Int): Void { param(new SqlInt(x.toInt64())); }
      @overload("append")
      public appendInt64(x: Int64): Void { param(new SqlInt(x)); }
      @overload("append")
      public appendFloat64(x: Float64): Void { param(new SqlFloat(x)); }
      @overload("append")
      public appendBoolean(x: Boolean): Void { param(new SqlBool(x)); }

      @overload("append")
      public appendIdentifier(x: Identifier): Void {
        if (hole()) {
          sb.append(Dialect.sqlite.quoteName(x.name) orelse panic());
          endsWithSpace = false;
        }
      }

      @overload("append")
      public appendQuery(x: SqliteQuery): Void {
        if (hole()) {
          // Spaces keep the query from joining the text around it into a
          // comment start, such as `-` before and `-1` after.
          if (!endsWithSpace) { sb.append(" "); }
          sb.append(x.sql);
          if (x.sql.isEmpty) {
            endsWithSpace = true;
          } else {
            endsWithSpace = isSpace(x.sql[x.sql.prev(x.sql.end)]);
            pendingSpace = !endsWithSpace;
          }
          for (let p of x.params) { params.add(p); }
        }
      }

      public build(): SqliteQuery throws Bubble {
        if (state != stateTop && state != stateLineComment) {
          fail("template ends inside a quote or comment");
        }
        if (problem != null) { bubble() }
        new SqliteQuery(sb.toString(), params.toList())
      }

      public get accumulated(): SqliteQuery { build() orelse panic() }

`templateProblem` says what's wrong with the template so far, or null.

      public get templateProblem(): String? { problem }

      private param(x: SqlValue): Void {
        if (hole()) {
          sb.append("?");
          endsWithSpace = false;
          params.add(x);
        }
      }

      private hole(): Boolean {
        if (state != stateTop) {
          fail("hole inside a quote or comment");
          false
        } else {
          true
        }
      }

      private fail(message: String): Void {
        if (problem == null) { problem = message; }
      }
    }

    export let sqlite = SqliteBuilder;

    let isSpace(c: Int): Boolean {
      c == char' ' || c == char'\t' || c == char'\n' || c == char'\r'
    }

    let stateTop = 0;
    let stateString = 1;
    let stateDoubleQuoted = 2;
    let stateBackQuoted = 3;
    let stateBracketed = 4;
    let stateLineComment = 5;
    let stateBlockComment = 6;
