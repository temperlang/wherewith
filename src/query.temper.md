# Queries

A *Query* is SQL with its values kept apart: text, parameters, and
names, in order. Tags (`sqlite`, `postgres`, `mysql`, `duckdb`, and
`sql` for [the common dialect](common.temper.md)) and plain code both
make queries with a `QueryBuilder`, which checks
the text with one database's lexing rules, and the query remembers that
[Dialect](core.temper.md). Rendering it quotes its names for the
dialect, and writes its parameters in a *PlaceholderStyle*, the way the
driver expects.

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

`dialect` is the dialect whose lexing rules checked the text, and
`params` lists the values in order, the same for every placeholder
style. Queries come from a `QueryBuilder` or a tag, which check their
text; the constructor is private. It keeps its own copy of the parts
(free when they're already a `List`), so a caller that goes on
changing its list can't make the parts and `params` disagree.

A common query also keeps its syntax tree, privately, parsed from its
parts when it's made, since rendering writes from the tree.

    export class Query {
      public dialect: Dialect;
      public parts: List<QueryPart>;
      public params: List<SqlValue>;
      private common: CommonQuery?;

      private constructor(dialect: Dialect, parts: Listed<QueryPart>) {
        let own = parts.toList();
        let params = new ListBuilder<SqlValue>();
        // An index loop, since Temper's C++ backend drops the lambda's
        // declaration for a for-of loop in a constructor.
        for (var i = 0; i < own.length; i += 1) {
          let part = own[i];
          if (part is QueryParam) { params.add(part.value); }
        }
        let common = if (dialect.name == "common") { parsedCommon(own) } else { null };
        this.dialect = dialect;
        this.parts = own;
        this.params = params.toList();
        this.common = common;
      }

`unchecked` makes a query for a dialect straight from its parts,
skipping every check: each `QueryText` is written into the SQL as it
is, so it must never hold untrusted text, and must read as the caller
means in that dialect. It's for code that checks its own text, such
as another builder that already lexes SQL. Use a `QueryBuilder` or a
tag otherwise. It takes any list of parts, even a `ListBuilder` still
being added to, and the query keeps its own copy. For the common
dialect it parses the parts, without the checks; a query whose parts
don't parse can't render.

Temper's private constructors still come out public in some backends
(a known limitation, for now), so there `new Query(dialect, parts)` is
callable too, with the same danger; use `unchecked`, which says so.

      public static unchecked(dialect: Dialect, parts: Listed<QueryPart>): Query {
        new Query(dialect, parts)
      }

### Rendering

`render` writes the SQL text for a dialect and a placeholder style.
Where a hole meets other text, it adds a space if they could otherwise
run together into one token, such as `5-` and `-1` into a comment, or
`a` and `$1` into one name: holes stay their own tokens. Only spaces,
line breaks, and the punctuation `(`, `)`, `[`, `]`, `,`, and `;`
(and `.` beside a quoted name) touch a hole directly.

A common query renders as canonical common SQL, written from its tree:
keywords in capitals, names bare where they can be and quoted
otherwise, and comments gone.

Rendering bubbles if `renderProblem` finds a problem: a dialect other
than the query's, or a named style whose marker is in the text.

      public render(dialect: Dialect, style: PlaceholderStyle): RenderedQuery throws Bubble {
        if (renderProblem(dialect, style) != null) { bubble() }
        let common = this.common;
        if (common != null) {
          let written = common.rendered();
          let values = new ListBuilder<SqlValue>();
          for (let part of written) {
            if (part is QueryParam) { values.add(part.value); }
          }
          return joined(written, values.toList(), dialect, style);
        }
        joined(parts, params, dialect, style)
      }

      private joined(
        parts: List<QueryPart>,
        params: List<SqlValue>,
        dialect: Dialect,
        style: PlaceholderStyle,
      ): RenderedQuery {
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

`renderProblem` says why the query can't be rendered for a dialect and
style, or is null if it can.

The dialect must be one the query's checks cover, since text can read
differently in another: in `postgres"SELECT 1 # ${x}"`, `#` is an
operator to PostgreSQL, but starts a comment in MySQL, hiding the
parameter. A query for `mysql` renders for `mysqlNoBackslashEscapes`
too, and the other way around, since both check templates with the
same lexer, which refuses text the two modes read differently.

A common query renders, for now, only for `Dialect.common`; rendering
it for each database is next.

A named style's marker (`@` or `:`) can't be anywhere in the query's
text, even inside quotes, since a driver that looks for names could
misread it.

      public renderProblem(dialect: Dialect, style: PlaceholderStyle): String? {
        if (this.dialect.name == "common" && dialect.name != "common") {
          return "rendering a common query for ${dialect.name} isn't built yet";
        }
        if (!sameLexing(this.dialect, dialect)) {
          return "query checked for ${this.dialect.name}, not ${dialect.name}";
        }
        var written = parts;
        let common = this.common;
        if (common != null) {
          let found = common.problem;
          if (found != null) { return "common query doesn't parse: ${found}"; }
          written = common.rendered();
        }
        let marker = style.marker;
        if (marker != 0) {
          for (var i = 0; i < written.length; i += 1) {
            let part = written[i];
            if (part is QueryText && hasCodePoint(part.text, marker)) {
              let shown = if (marker == char'@') { "@" } else { ":" };
              return "text has ${shown}, which ${style.name} uses";
            }
          }
        }
        null
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
reads them: libpq, `pg`, asyncpg, `tokio-postgres`, and `sqlx`. DuckDB
reads them too.

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
- The text can't hold NUL. PostgreSQL, SQLite, and DuckDB's C API
  stop reading SQL text there, and MySQL and MariaDB end a line
  comment there.
- A nested query must be for a dialect the builder's checks cover, as
  for rendering, since its text was checked with its own dialect's
  rules.
- The text can't end inside a quote or a block comment. If it ends in
  a line comment, a line break ends that, so text after a nested query
  stays code.

Text passed to `appendSafe` is trusted SQL; consecutive calls join up
before they're checked. A mistake makes `build` bubble, with
`templateProblem` saying why (and, for the common dialect, where); for
a tag, it panics.

For the common dialect, `build` also parses the whole template and
checks it for each target database: every profile by default, or
fewer, set with `targets` any time before `build`. A nested common
query's own text is lexed, parsed, and checked again, as part of the
template, so the checks see into it, and it needs to suit only the
outer query's targets.

```temper inert
let b = new QueryBuilder(Dialect.mysql);
b.appendSafe("SELECT * FROM ");
b.appendIdentifier(Identifier.named("orders") orelse panic());
b.appendSafe(" WHERE id = ");
b.appendInt(42);
let q = b.build() orelse panic();
```

    export class QueryBuilder {
      private dialect: Dialect;
      private lexer: SqlLexer;
      // The same lexer, for the common dialect, or else null.
      private common: CommonLexer?;
      private parts: ListBuilder<QueryPart>;
      // For the common dialect, the parts that are value and name
      // holes, in order, nested queries' too.
      private holes: ListBuilder<QueryPart>;
      private var targetList: List<Dialect>;
      private var pending: StringBuilder;
      private var hasPending: Boolean;
      private var problem: String?;

      public constructor(dialect: Dialect) {
        let lexer = newLexer(dialect);
        this.dialect = dialect;
        this.lexer = lexer;
        this.common = if (lexer is CommonLexer) { lexer } else { null };
        this.parts = new ListBuilder<QueryPart>();
        this.holes = new ListBuilder<QueryPart>();
        this.targetList = commonTargets();
        this.pending = new StringBuilder();
        this.hasPending = false;
        this.problem = null;
      }

`targets` are the databases a common query must mean the same on. Set
fewer to relax the checks for the ones left out: `\` in strings, say,
which MySQL's default profile reads as an escape, is fine for
`[Dialect.postgres, Dialect.sqlite]`. Only common builders take them.

      public get targets(): List<Dialect> { targetList }

      public set targets(value: List<Dialect>): Void {
        if (common == null) {
          fail("targets are only for common queries");
        } else if (value.isEmpty) {
          fail("no target databases");
        } else {
          for (var i = 0; i < value.length; i += 1) {
            if (value[i].name == "common") {
              fail("common isn't a target database");
              return;
            }
          }
          targetList = value;
        }
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
        if (hole(holeValue)) { added(new QueryParam(x)); }
      }

      @overload("append")
      public appendIdentifier(x: Identifier): Void {
        if (hole(holeName)) { added(new QueryName(x)); }
      }

      @overload("append")
      public appendQuery(x: Query): Void {
        flush();
        if (!sameLexing(x.dialect, dialect)) {
          fail(lexer.locate("nested query checked for ${x.dialect.name}, not ${dialect.name}"));
        }
        let common = this.common;
        if (common != null) {
          nest(common, x);
        } else if (hole(holeQuery)) {
          for (let p of x.parts) { parts.add(p); }
        }
      }

A nested common query's parts go through the lexer too, between its
start and end.

      private nest(common: CommonLexer, x: Query): Void {
        if (!common.inCode) {
          fail(common.locate("hole inside a quote or comment"));
          return;
        }
        if (x.dialect.name != "common") { return; }
        common.beginQuery();
        for (let p of x.parts) {
          if (p is QueryText) {
            let found = common.scan(p.text);
            if (found != null) { fail(found); }
          } else if (p is QueryParam) {
            let found = common.hole(holeValue);
            if (found != null) { fail(found); }
            holes.add(p);
          } else if (p is QueryName) {
            let found = common.hole(holeName);
            if (found != null) { fail(found); }
            holes.add(p);
          }
          parts.add(p);
        }
        let found = common.endQuery();
        if (found != null) { fail(found); }
      }

      private added(part: QueryPart): Void {
        parts.add(part);
        if (common != null) { holes.add(part); }
      }

      public build(): Query throws Bubble {
        flush();
        if (lexer.inLineComment) {
          appendSafe("\n");
          flush();
        }
        let ended = lexer.endProblem();
        if (ended != null) { fail(ended); }
        let common = this.common;
        if (common != null) {
          if (problem == null) {
            let found = commonProblem(common, holes.toList(), targetList);
            if (found != null) { fail(found); }
          }
        }
        if (problem != null) { bubble() }
        Query.unchecked(dialect, parts)
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
        if (hasCodePoint(text, 0)) { fail("NUL in template text"); }
        parts.add(new QueryText(text));
      }

      private hole(kind: Int): Boolean {
        flush();
        if (lexer.inCode) {
          let found = lexer.hole(kind);
          if (found != null) { fail(found); }
          true
        } else {
          fail(lexer.locate("hole inside a quote or comment"));
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

That a hole of a kind comes next, where code goes, so the text on
either side of it can't join into one token. It gives a problem with
the hole, if the lexer sees one.

      public hole(kind: Int): String?;

`locate` adds where the lexer is to a problem the builder finds, for
lexers that track positions.

      public locate(message: String): String { message }

The problem, if any, with the template ending here.

      public endProblem(): String? {
        if (inCode) { null } else { "template ends inside a quote or comment" }
      }
    }

Hole kinds: a value, a name, or a nested query.

    let holeValue = 0;
    let holeName = 1;
    let holeQuery = 2;

    let newLexer(dialect: Dialect): SqlLexer {
      let lexing = lexingName(dialect);
      if (lexing == "sqlite") {
        new SqliteLexer()
      } else if (lexing == "postgres") {
        new PostgresLexer(false)
      } else if (lexing == "duckdb") {
        new PostgresLexer(true)
      } else if (lexing == "common") {
        new CommonLexer()
      } else {
        new MysqlLexer()
      }
    }

`lexingName` names the rules a dialect's templates are checked with:
its own name, but `mysql` for both MySQL profiles, which share a
lexer. A query renders, or nests, only where these agree.

    let lexingName(dialect: Dialect): String {
      if (dialect.name == "mysqlNoBackslashEscapes") { "mysql" } else { dialect.name }
    }

    let sameLexing(a: Dialect, b: Dialect): Boolean {
      lexingName(a) == lexingName(b)
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
