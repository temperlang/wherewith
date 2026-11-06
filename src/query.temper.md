# Queries

The `sqlite` tag writes a query for SQLite with each value bound as a
parameter, never written into the SQL text:

    test("values become parameters") {
      let name = "Robert'); DROP TABLE students; --";
      let q = sqlite"SELECT id FROM students WHERE name = ${name} AND age > ${7}";
      assert(q.sql == "SELECT id FROM students WHERE name = ? AND age > ?");
      assert(q.params.length == 2);
      assert(paramText(q.params[0]) == "text:${name}");
      assert(paramText(q.params[1]) == "int:7");
    }

Most SQLite drivers take `?` parameters in order: `sqlite3` in C and
C++, JDBC in Java, `node:sqlite` and `better-sqlite3` in JavaScript,
`lsqlite3` in Lua, `sqlite3` in Python, and `rusqlite` in Rust. C#'s
`Microsoft.Data.Sqlite` binds by name, so it will need named
placeholders. Those, and PostgreSQL and MySQL tags with each driver's
placeholders, come later; see the [design](../docs/design.md).

## Values

A *SqlValue* is a parameter's value, typed so each driver can bind it
with its own type.

    export sealed interface SqlValue {}

    export class SqlText(public value: String) extends SqlValue {}
    export class SqlInt(public value: Int64) extends SqlValue {}
    export class SqlFloat(public value: Float64) extends SqlValue {}
    export class SqlBool(public value: Boolean) extends SqlValue {}
    export class SqlNull() extends SqlValue {}

## Names

An *Identifier* is a name that's safe to quote in every dialect
Wherewith knows, so it can go in any query: not empty, at most 63 UTF-8
bytes and 64 characters, no NUL, nothing above U+FFFF, and no trailing
space. In a template, it's written quoted, as SQL text.

    export class Identifier {
      public name: String;

      private constructor(name: String) {
        this.name = name;
      }

      public toString(): String { name }

      public static named(name: String): Identifier throws Bubble {
        if (identifierProblem(name) != null) { bubble() }
        new Identifier(name)
      }
    }

`identifierProblem` gives the first problem any dialect finds, or null.

    export let identifierProblem(name: String): String? {
      Dialect.postgresql.nameProblem(name) ?? Dialect.mysql.nameProblem(name)
    }

<!-- -->

    test("identifiers go in quoted") {
      let col = Identifier.named("weird \"col\"") orelse panic();
      let q = sqlite"SELECT ${col} FROM t WHERE ${col} = ${"x"}";
      assert(q.sql == "SELECT \"weird \"\"col\"\"\" FROM t WHERE \"weird \"\"col\"\"\" = ?");
      assert(q.params.length == 1);
      let bad = ["", "a${u(0x0)}", "t ", "t${u(0x1F600)}", repeated("x", 65)];
      for (let s of bad) {
        assert(identifierProblem(s) != null);
      }
    }

## SqliteQuery

    export class SqliteQuery(public sql: String, public params: List<SqlValue>) {
      public toString(): String { sql }
    }

A query in a hole goes in as SQL, with its parameters in place.

    test("queries nest") {
      let where = sqlite"WHERE a = ${1} AND b IS ${null}";
      let q = sqlite"SELECT * FROM t ${where} LIMIT ${10}";
      assert(q.sql == "SELECT * FROM t WHERE a = ? AND b IS ? LIMIT ?");
      assert(q.params.length == 3);
      assert(paramText(q.params[1]) == "null");
      assert(paramText(q.params[2]) == "int:10");
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

<!-- -->

    test("template mistakes") {
      let check(build: fn (SqliteBuilder): Void): String {
        let b = new SqliteBuilder();
        build(b);
        do { b.build(); "ok" } orelse (b.templateProblem ?? "fails")
      }
      assert(check { b => b.appendSafe("SELECT 1"); } == "ok");
      assert(check { b => b.appendSafe("SELECT '"); b.appendString("x"); b.appendSafe("'"); } ==
        "hole inside a quote or comment");
      assert(check { b => b.appendSafe("SELECT \"a"); b.appendInt(1); b.appendSafe("\""); } ==
        "hole inside a quote or comment");
      assert(check { b => b.appendSafe("SELECT 1 -- "); b.appendInt(1); } ==
        "hole inside a quote or comment");
      assert(check { b => b.appendSafe("SELECT /* "); b.appendInt(1); b.appendSafe(" */"); } ==
        "hole inside a quote or comment");
      assert(check { b => b.appendSafe("SELECT ? , "); b.appendInt(1); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT :a"); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT 'it''s'"); } == "ok");
      assert(check { b => b.appendSafe("SELECT 'a ? :b'"); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 -- what?\n, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT [a]"); b.appendSafe(" , /* ? */ 1"); } == "ok");
      assert(check { b => b.appendSafe("SELECT 'a"); } == "template ends inside a quote or comment");
    }

Hostile values are only ever parameters.

    test("hostile values") {
      let values = ["'", "\\", u(0x0), "a\nb", "?", "-- x", "/*", u(0x1F600), "\"; DROP TABLE t; --"];
      for (let v of values) {
        let q = sqlite"SELECT ${v}, -${-1}";
        assert(q.sql == "SELECT ?, -?");
        assert(paramText(q.params[0]) == "text:${v}");
        assert(paramText(q.params[1]) == "int:-1");
      }
      let neg = sqlite"-1";
      assert(sqlite"SELECT 5-${neg}".sql == "SELECT 5- -1");
      assert(sqlite"SELECT ${neg}-1".sql == "SELECT -1 -1");
      assert(sqlite"SELECT 1-${sqlite""}-1".sql == "SELECT 1- -1");
    }

`paramText` describes a parameter, for tests.

    let paramText(p: SqlValue): String {
      when (p) {
        is SqlText -> "text:${p.value}";
        is SqlInt -> "int:${p.value.toString()}";
        is SqlFloat -> "float:${p.value.toString()}";
        is SqlBool -> "bool:${p.value.toString()}";
        else -> "null";
      }
    }
