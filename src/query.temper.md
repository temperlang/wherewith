# Queries

A *Query* is SQL with its values kept apart: text, parameters, and
names, in order. It doesn't belong to one database or one driver.
Rendering it takes a [Dialect](core.temper.md), which quotes its names,
and a *PlaceholderStyle*, which writes its parameters the way the
driver expects. Tags (`sqlite`, `postgres`, and `mysql`) and plain code
both make queries with a `QueryBuilder`, which checks the text with
one database's lexing rules.

```temper inert
let table = Identifier.named("students") orelse panic();
let name = "Robert'); DROP TABLE students; --";
let q = postgres"SELECT id FROM ${table} WHERE name = ${name}";
let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
r.sql;    // SELECT id FROM "students" WHERE name = $1
r.params; // [SqlText(name)]
```

## Parts

A query is a list of parts. `QueryText` is SQL text, written as it is;
`QueryParam` is a value, written as a placeholder; and `QueryName` is a
name, quoted for the dialect when rendered. A nested query's parts go
in place, so its parameters are numbered with the rest.

    export sealed interface QueryPart {}

    export class QueryText(public text: String) extends QueryPart {}
    export class QueryParam(public value: SqlValue) extends QueryPart {}
    export class QueryName(public name: Identifier) extends QueryPart {}

## Query

`params` lists the values in order, the same for every placeholder
style. Queries come from a `QueryBuilder` or a tag, which check their
text; the constructor is private.

    export class Query {
      public parts: List<QueryPart>;
      public params: List<SqlValue>;

      private constructor(parts: List<QueryPart>) {
        let params = new ListBuilder<SqlValue>();
        // An index loop, since Temper's C++ backend drops the lambda's
        // declaration for a for-of loop in a constructor.
        for (var i = 0; i < parts.length; i += 1) {
          let part = parts[i];
          if (part is QueryParam) { params.add(part.value); }
        }
        this.parts = parts;
        this.params = params.toList();
      }

`unchecked` makes a query straight from its parts, skipping every
check: each `QueryText` is written into the SQL as it is, so it must
never hold untrusted text. It's for code that checks its own text, such
as another builder that already lexes SQL. Use a `QueryBuilder` or a
tag otherwise.

Temper's private constructors still come out public in some backends
(a known limitation, for now), so there `new Query(parts)` is callable
too, with the same danger; use `unchecked`, which says so.

      public static unchecked(parts: List<QueryPart>): Query {
        new Query(parts)
      }

### Rendering

`render` writes the SQL text for a dialect and a placeholder style.
Where a hole meets other text, it adds a space if they could otherwise
run together into one token, such as `5-` and `-1` into a comment, or
`a` and `$1` into one name: holes stay their own tokens. Only spaces,
line breaks, and the punctuation `(`, `)`, `[`, `]`, `,`, and `;`
(and `.` beside a quoted name) touch a hole directly.

Rendering bubbles only for a named style whose marker (`@` or `:`) is
anywhere in the query's text, even inside quotes, since a driver that
looks for names could misread it.

      public render(dialect: Dialect, style: PlaceholderStyle): RenderedQuery throws Bubble {
        let marker = style.marker;
        var clash = false;
        if (marker != 0) {
          for (let part of parts) {
            if (part is QueryText && hasCodePoint(part.text, marker)) { clash = true; }
          }
        }
        if (clash) { bubble() }
        let sb = new StringBuilder();
        var last = -1;
        var count = 0;
        for (let part of parts) {
          let s = when (part) {
            is QueryText -> style.text(part.text);
            is QueryParam -> do {
              count += 1;
              style.placeholder(count)
            };
            is QueryName -> style.text(dialect.quoteName(part.name.name) orelse panic());
            else -> "";
          };
          if (!s.isEmpty) {
            if (last >= 0 && needsSpace(last, s[String.begin])) { sb.append(" "); }
            sb.append(s);
            last = s[s.prev(s.end)];
          }
        }
        new RenderedQuery(sb.toString(), params)
      }
    }

`RenderedQuery` is what a driver takes: the SQL text and the values to
bind, in placeholder order.

    export class RenderedQuery(public sql: String, public params: List<SqlValue>) {
      public toString(): String { sql }
    }

## Placeholder styles

The placeholder style depends on the driver, not only the database, so
it's chosen when rendering. The [design](../docs/design.md) lists the
drivers for each.

    export class PlaceholderStyle {
      public name: String;
      private kind: Int;

      private constructor(name: String, kind: Int) {
        this.name = name;
        this.kind = kind;
      }

      public toString(): String { name }

`question` writes `?` for each parameter: SQLite's drivers, JDBC, and
most MySQL and MariaDB drivers.

      public static question: PlaceholderStyle = doPure { new PlaceholderStyle("question", 0) };

`dollarNumbered` writes `$1`, `$2`, and so on, as PostgreSQL's server
reads them: libpq, `pg`, asyncpg, `tokio-postgres`, and `sqlx`.

      public static dollarNumbered: PlaceholderStyle = doPure { new PlaceholderStyle("dollarNumbered", 1) };

`percentS` writes `%s` and doubles each `%` in the text and names, for
drivers that fill in parameters with Python's `%` formatting: psycopg,
PyMySQL, and mysqlclient. Adapters must pass the parameter list even
when it's empty, so the driver turns `%%` back into `%`.

      public static percentS: PlaceholderStyle = doPure { new PlaceholderStyle("percentS", 2) };

`atNamed` writes `@p1`, `@p2`, and so on, and `colonNamed` writes
`:p1`, `:p2`, and so on, for drivers that bind by name, such as C#'s
`Microsoft.Data.Sqlite`. Bind each value as `p` and its number, from 1.

      public static atNamed: PlaceholderStyle = doPure { new PlaceholderStyle("atNamed", 3) };
      public static colonNamed: PlaceholderStyle = doPure { new PlaceholderStyle("colonNamed", 4) };

`placeholder` writes the placeholder for parameter `n`, counting from 1.

      public placeholder(n: Int): String {
        when (kind) {
          0 -> "?";
          1 -> "$${n.toString()}";
          2 -> "%s";
          3 -> "@p${n.toString()}";
          else -> ":p${n.toString()}";
        }
      }

`text` writes SQL text or a quoted name for this style.

      public text(s: String): String {
        if (kind == 2) { replaceCodePoint(s, char'%', "%%") } else { s }
      }

`marker` is the code point that starts a named placeholder, or 0.

      public get marker(): Int {
        if (kind == 3) { char'@' } else if (kind == 4) { char':' } else { 0 }
      }
    }

## QueryBuilder

A `QueryBuilder` makes a query, for the tags or for plain code. It
checks text with the lexing rules of the dialect it's made for, so a
mistake can't misplace a parameter:

- A hole (a value, a name, or a nested query) must be where SQL code
  goes, not inside a string, a quoted name, or a comment.
- The text can't have its own placeholders, such as `?` or `$1`, which
  would shift every parameter's place. Each dialect's file says what
  counts.
- The text can't end inside a quote or a block comment. If it ends in
  a line comment, a line break ends that, so text after a nested query
  stays code.

Text passed to `appendSafe` is trusted SQL; consecutive calls join up
before they're checked. A mistake makes `build` bubble, with
`templateProblem` saying why; for a tag, it panics.

```temper inert
let b = new QueryBuilder(Dialect.mysql);
b.appendSafe("SELECT * FROM ");
b.appendIdentifier(Identifier.named("orders") orelse panic());
b.appendSafe(" WHERE id = ");
b.appendInt(42);
let q = b.build() orelse panic();
```

    export class QueryBuilder {
      private lexer: SqlLexer;
      private parts: ListBuilder<QueryPart>;
      private var pending: StringBuilder;
      private var hasPending: Boolean;
      private var problem: String?;

      public constructor(dialect: Dialect) {
        this.lexer = newLexer(dialect);
        this.parts = new ListBuilder<QueryPart>();
        this.pending = new StringBuilder();
        this.hasPending = false;
        this.problem = null;
      }

      public appendSafe(fixed: String): Void {
        if (fixed.isEmpty) { return; }
        pending.append(fixed);
        hasPending = true;
      }

      @overload("append")
      public appendString(x: String?): Void {
        if (x == null) { appendValue(new SqlNull()); } else { appendValue(new SqlText(x)); }
      }
      @overload("append")
      public appendInt(x: Int): Void { appendValue(new SqlInt(x.toInt64())); }
      @overload("append")
      public appendInt64(x: Int64): Void { appendValue(new SqlInt(x)); }
      @overload("append")
      public appendFloat64(x: Float64): Void { appendValue(new SqlFloat(x)); }
      @overload("append")
      public appendBoolean(x: Boolean): Void { appendValue(new SqlBool(x)); }

      @overload("append")
      public appendValue(x: SqlValue): Void {
        if (hole()) { parts.add(new QueryParam(x)); }
      }

      @overload("append")
      public appendIdentifier(x: Identifier): Void {
        if (hole()) { parts.add(new QueryName(x)); }
      }

      @overload("append")
      public appendQuery(x: Query): Void {
        if (hole()) {
          for (let p of x.parts) { parts.add(p); }
        }
      }

      public build(): Query throws Bubble {
        flush();
        if (lexer.inLineComment) {
          appendSafe("\n");
          flush();
        }
        if (!lexer.inCode) { fail("template ends inside a quote or comment"); }
        if (problem != null) { bubble() }
        Query.unchecked(parts.toList())
      }

      public get accumulated(): Query { build() orelse panic() }

`templateProblem` says what's wrong with the query so far, or null.

      public get templateProblem(): String? {
        flush();
        problem
      }

      private flush(): Void {
        if (!hasPending) { return; }
        let text = pending.toString();
        pending = new StringBuilder();
        hasPending = false;
        let found = lexer.scan(text);
        if (found != null) { fail(found); }
        parts.add(new QueryText(text));
      }

      private hole(): Boolean {
        flush();
        if (lexer.inCode) {
          true
        } else {
          fail("hole inside a quote or comment");
          false
        }
      }

      private fail(message: String): Void {
        if (problem == null) { problem = message; }
      }
    }

## Lexers

Each dialect's file has its lexer, which reads text a run at a time
(the text between two holes), carrying its state from one run to the
next, and gives the first problem it finds.

    interface SqlLexer {
      public scan(text: String): String?;

Whether the text so far ends where code goes, so a hole can go there.

      public get inCode(): Boolean;

Whether it ends in a line comment.

      public get inLineComment(): Boolean;
    }

    let newLexer(dialect: Dialect): SqlLexer {
      if (dialect.name == "sqlite") {
        new SqliteLexer()
      } else if (dialect.name == "postgres") {
        new PostgresLexer()
      } else {
        new MysqlLexer()
      }
    }

States the lexers share.

    let lexCode = 0;
    let lexSingleQuoted = 1;
    let lexDoubleQuoted = 2;
    let lexBackQuoted = 3;
    let lexBracketed = 4;
    let lexLineComment = 5;
    let lexBlockComment = 6;
    let lexDollarQuoted = 7;
    let lexEscapeString = 8;

`stray` is the problem for placeholder-like text.

    let stray = "parameter in template text";

## Helpers

    let isSpace(c: Int): Boolean {
      c == char' ' || c == char'\t' || c == char'\n' || c == char'\r'
    }

A *word* character can be part of a bare name or a number. `$` counts,
since PostgreSQL and MySQL allow it in names.

    let isWordChar(c: Int): Boolean {
      (c >= char'a' && c <= char'z') || (c >= char'A' && c <= char'Z') ||
        (c >= char'0' && c <= char'9') || c == char'_' || c == char'$' || c >= 0x80
    }

Whether a space must go between `last`, the end of one part, and
`first`, the start of the next.

    let needsSpace(last: Int, first: Int): Boolean {
      if (last <= 0x20 || first <= 0x20) { return false; }
      if (isPunctuation(last) || isPunctuation(first)) { return false; }
      let quoted = last == char'"' || last == char'`' || first == char'"' || first == char'`';
      !(quoted && (last == char'.' || first == char'.'))
    }

    let isPunctuation(c: Int): Boolean {
      c == char'(' || c == char')' || c == char'[' || c == char']' || c == char',' || c == char';'
    }

    let hasCodePoint(s: String, target: Int): Boolean {
      for (var i = String.begin; s.hasIndex(i); i = s.next(i)) {
        if (s[i] == target) { return true; }
      }
      false
    }

Whether `s` has `prefix` starting at `i`.

    let hasAt(s: String, i: StringIndex, prefix: String): Boolean {
      var j = i;
      for (var k = String.begin; prefix.hasIndex(k); k = prefix.next(k)) {
        if (!s.hasIndex(j) || s[j] != prefix[k]) { return false; }
        j = s.next(j);
      }
      true
    }
