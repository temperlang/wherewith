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
style. `targets` are the databases a common query was checked for, and
renders for; a database's query has just its own dialect. Queries come from a `QueryBuilder` or a tag, which check their
text; the constructor is private. It keeps its own copy of the parts
(free when they're already a `List`), so a caller that goes on
changing its list can't make the parts and `params` disagree.

A common query also keeps its syntax tree, privately, since rendering
writes from the tree: from a `QueryBuilder`, the tree its checks
parsed, so the template is parsed once; from `unchecked`, parsed from
its parts.

    export class Query {
      public dialect: Dialect;
      public parts: List<QueryPart>;
      public params: List<SqlValue>;
      public targets: List<Dialect>;
      private common: CommonQuery?;

      // `tree` is a common query's `CommonQuery`, typed as the exported
      // `TemplateCheck`, since some backends make this constructor public.
      private constructor(dialect: Dialect, parts: List<QueryPart>, targets: List<Dialect>, tree: TemplateCheck?) {
        let own = parts;
        let common = if (tree is CommonQuery) { tree } else { null };
        let params = new ListBuilder<SqlValue>();
        for (let part of own) {
          if (part is QueryParam) { params.add(part.value); }
        }
        this.dialect = dialect;
        this.parts = own;
        this.params = params.toList();
        this.targets = targets;
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
don't parse can't render. A common query's `targets` are those given,
or else every database.

Temper's private constructors still come out public in some backends
(a known limitation, for now), so there the constructor is
callable too, with the same danger; use `unchecked`, which says so.

      public static unchecked(dialect: Dialect, parts: Listed<QueryPart>, targets: List<Dialect>? = null): Query {
        let own = parts.toList();
        if (dialect.name != "common") { return new Query(dialect, own, [dialect], null); }
        new Query(dialect, own, targets ?? commonTargets(), parsedCommon(own))
      }

`checked` is how a common `QueryBuilder` hands over a template it has
checked, with the tree its checks parsed, so `build` doesn't parse it
again. Only a builder makes a `TemplateCheck`, and only one that passed
makes a query; anything else bubbles. Use a `QueryBuilder` or a tag.

      public static checked(check: TemplateCheck): Query throws Bubble {
        if (check is CommonCheck) {
          let common = check.common;
          if (check.problem == null && common != null) {
            return new Query(Dialect.common, check.parts, check.targets, common);
          }
        }
        bubble()
      }

### Rendering

`render` writes the SQL text for a dialect and a placeholder style.
Where a hole meets other text, it adds a space if they could otherwise
run together into one token, such as `5-` and `-1` into a comment, or
`a` and `$1` into one name: holes stay their own tokens. Only spaces,
line breaks, and the punctuation `(`, `)`, `[`, `]`, `,`, and `;`
(and `.` beside a quoted name) touch a hole directly.

A common query renders from its tree. For `Dialect.common`, that's
canonical common SQL: keywords in capitals, names bare where they can
be and quoted otherwise, and comments gone. For each database it was
checked for (its `targets`), it's that database's SQL, written as the
[rendering rules](common-rendering.temper.md) say, and then checked
with that database's own lexer, as its tag would check it, so a value
can't land in a quote or comment there.

Rendering bubbles if `renderProblem` finds a problem: a dialect other
than the query's, or than a common query's targets, or a named style
whose marker is in the text.

      public render(dialect: Dialect, style: PlaceholderStyle): RenderedQuery throws Bubble {
        let w = written(dialect, style);
        if (w.problem != null) { bubble() }
        let parts = w.parts;
        if (common == null) { return joined(parts, params, dialect, style); }
        let values = new ListBuilder<SqlValue>();
        for (let part of parts) {
          if (part is QueryParam) { values.add(part.value); }
        }
        joined(parts, values.toList(), dialect, style)
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
same lexer, which refuses text the two modes read differently. A
common query renders for `Dialect.common` and for its targets.

A named style's marker (`@` or `:`) can't be anywhere in the query's
text, even inside quotes, since a driver that looks for names could
misread it.

      public renderProblem(dialect: Dialect, style: PlaceholderStyle): String? {
        written(dialect, style).problem
      }

`renderedParts` gives the parts a query renders as for a dialect: for a
common query, its tree written for that database, with names in the
text; for others, its own parts. It bubbles as `render` does.

      public renderedParts(dialect: Dialect): List<QueryPart> throws Bubble {
        let w = written(dialect, PlaceholderStyle.question);
        if (w.problem != null) { bubble() }
        w.parts
      }

`written` gives the parts to render for a dialect, or the problem.

      private written(dialect: Dialect, style: PlaceholderStyle): WrittenQuery {
        var written = parts;
        let common = this.common;
        let database = if (dialect.name != "common") { common } else { null };
        if (database != null) {
          if (!hasDialect(targets, dialect)) {
            return new WrittenQuery(parts, "common query checked for ${dialectNames(targets)}, not ${dialect.name}");
          }
          let found = database.problem;
          if (found != null) { return new WrittenQuery(parts, "common query doesn't parse: ${found}"); }
          let rendered = database.renderedFor(dialect);
          let problem = rendered.problem ?? lexingProblem(dialect, rendered.parts);
          if (problem != null) { return new WrittenQuery(parts, problem); }
          written = rendered.parts;
        } else {
          if (!sameLexing(this.dialect, dialect)) {
            return new WrittenQuery(parts, "query checked for ${this.dialect.name}, not ${dialect.name}");
          }
          if (common != null) {
            let found = common.problem;
            if (found != null) { return new WrittenQuery(parts, "common query doesn't parse: ${found}"); }
            written = common.renderedFor(dialect).parts;
          }
        }
        let marker = style.marker;
        if (marker != 0) {
          for (var i = 0; i < written.length; i += 1) {
            let part = written[i];
            if (part is QueryText && hasCodePoint(part.text, marker)) {
              let shown = if (marker == char'@') { "@" } else { ":" };
              return new WrittenQuery(written, "text has ${shown}, which ${style.name} uses");
            }
          }
        }
        new WrittenQuery(written, null)
      }
    }

`TemplateCheck` is a builder's check of a whole template, or a common
query's tree, opaque outside Wherewith: see `Query.checked`.

    export sealed interface TemplateCheck {}

`CommonCheck` is a common template's: its parts and targets, then
either its tree, from the parse its checks ran on, or the first
problem.

    class CommonCheck(
      public parts: List<QueryPart>,
      public targets: List<Dialect>,
      public common: CommonQuery?,
      public problem: String?,
    ) extends TemplateCheck {}

`WrittenQuery` holds the parts a query renders as, or why it can't.

    class WrittenQuery(public parts: List<QueryPart>, public problem: String?) {}

`lexingProblem` checks a common query's parts, as written for a
database, with that database's lexer, as a `QueryBuilder` for it would.
It should never find one; if it does, rendering refuses rather than
send SQL the database could read differently.

    let lexingProblem(dialect: Dialect, parts: List<QueryPart>): String? {
      let b = new QueryBuilder(dialect);
      for (let part of parts) {
        when (part) {
          is QueryText -> b.appendSafe(part.text);
          is QueryParam -> b.appendValue(part.value);
          is QueryName -> b.appendIdentifier(part.name);
          else -> do {};
        }
      }
      let built: Query? = b.build() orelse null;
      if (built != null) { return null; }
      "common query rendered for ${dialect.name} fails its lexer: ${b.templateProblem ?? ""}"
    }

    let hasDialect(dialects: List<Dialect>, dialect: Dialect): Boolean {
      for (let d of dialects) {
        if (d.name == dialect.name) { return true; }
      }
      false
    }

    let dialectNames(dialects: List<Dialect>): String {
      dialects.join(", ", fn (d: Dialect): String { d.name })
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
  rules. A common query goes into a database's template rendered for
  that database, so it must be one of its targets: an escape hatch for
  SQL outside the common dialect.
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
outer query's targets. The query records its targets, and renders only
for them.

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
      // For the common dialect, the whole template's check, if done
      // since the template or targets last changed.
      private var check: CommonCheck?;

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
        this.check = null;
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
          for (let d of value) {
            if (d.name == "common") {
              fail("common isn't a target database");
              return;
            }
          }
          targetList = value;
          check = null;
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
        let common = this.common;
        if (common != null) {
          if (x.dialect.name != "common") {
            fail(lexer.locate("nested query checked for ${x.dialect.name}, not common"));
          }
          nest(common, x);
          return;
        }
        if (x.dialect.name == "common") {
          // Written for this dialect, and checked with its lexer.
          let rendered: List<QueryPart>? = x.renderedParts(dialect) orelse null;
          if (rendered == null) {
            fail(lexer.locate("nested common query: ${x.renderProblem(dialect, PlaceholderStyle.question) ?? ""}"));
          } else if (hole(holeQuery)) {
            for (let p of rendered) { parts.add(p); }
          }
          return;
        }
        if (!sameLexing(x.dialect, dialect)) {
          fail(lexer.locate("nested query checked for ${x.dialect.name}, not ${dialect.name}"));
        }
        if (hole(holeQuery)) {
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
        check = null;
        common.beginQuery();
        for (let p of x.parts) {
          when (p) {
            is QueryText -> do {
              let found = common.scan(p.text);
              if (found != null) { fail(found); }
            };
            is QueryParam -> do {
              let found = common.hole(holeValue);
              if (found != null) { fail(found); }
              holes.add(p);
            };
            is QueryName -> do {
              let found = common.hole(holeName);
              if (found != null) { fail(found); }
              holes.add(p);
            };
          }
          parts.add(p);
        }
        let found = common.endQuery();
        if (found != null) { fail(found); }
      }

      private added(part: QueryPart): Void {
        check = null;
        parts.add(part);
        if (common != null) { holes.add(part); }
      }

      public build(): Query throws Bubble {
        flush();
        if (lexer.inLineComment) {
          appendSafe("\n");
          flush();
        }
        if (templateProblem != null) { bubble() }
        // A common template's check is done, by `templateProblem`.
        let check = this.check;
        if (check != null) { return Query.checked(check); }
        Query.unchecked(dialect, parts, targetList)
      }

      public get accumulated(): Query { build() orelse panic() }

`templateProblem` says why `build` would refuse the template as it is
now, or is null if it wouldn't: a problem found as the template came
in, such as a hole in a quote; the template ending inside a quote or
block comment; and, for the common dialect, every problem the parser
and the checks find, such as `/` without a float operand. Reading it
doesn't change the builder, so more can be added after; a template
that's only half written reads as one that ends there. A common
template's parse and checks run once, when it or `build` first needs
them, and again only after more is added or the targets change; `build`
makes its query from that same parse.

      public get templateProblem(): String? {
        flush();
        if (problem != null) { return problem; }
        let common = this.common;
        if (common != null) {
          checkedCommon(common).problem
        } else if (lexer.inLineComment) {
          // `build` ends a line comment, so the template doesn't end
          // in one.
          null
        } else {
          lexer.endProblem()
        }
      }

      private checkedCommon(common: CommonLexer): CommonCheck {
        let done = check;
        if (done != null) { return done; }
        let made = commonCheck(common, parts.toList(), holes.toList(), targetList);
        check = made;
        made
      }

      private flush(): Void {
        if (!hasPending) { return; }
        let text = pending.toString();
        pending = new StringBuilder();
        hasPending = false;
        check = null;
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
