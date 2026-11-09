# Query Tests

Rendering in every placeholder style, with names quoted per dialect.
Each dialect's template checks are tested in its own tests file.

## Test helpers

`render` writes a query, or `(fails)`; `qmarks` writes it for SQLite
with `?`.

    let render(q: Query, d: Dialect, style: PlaceholderStyle): String {
      do { q.render(d, style).sql } orelse "(fails)"
    }

    let qmarks(q: Query): String { render(q, Dialect.sqlite, PlaceholderStyle.question) }

`checkTemplate` builds a query for a dialect, and says `ok` or what's
wrong with it.

    let checkTemplate(d: Dialect, build: fn (QueryBuilder): Void): String {
      let b = new QueryBuilder(d);
      build(b);
      let built = do { b.build(); true } orelse false;
      if (built) { "ok" } else { b.templateProblem ?? "fails" }
    }

    let allStyles(): List<PlaceholderStyle> {
      [
        PlaceholderStyle.question, PlaceholderStyle.dollarNumbered, PlaceholderStyle.percentS,
        PlaceholderStyle.atNamed, PlaceholderStyle.colonNamed,
      ]
    }

Whether `s` has `part` anywhere in it.

    let contains(s: String, part: String): Boolean {
      for (var i = String.begin; s.hasIndex(i); i = s.next(i)) {
        if (hasAt(s, i, part)) { return true; }
      }
      part.isEmpty
    }

## Placeholder styles

    test("every placeholder style") {
      let inner = sqlite"b = ${2} OR c = ${3}";
      let q = sqlite"SELECT * FROM t WHERE a = ${1} AND (${inner}) LIMIT ${4}";
      assert(render(q, Dialect.sqlite, PlaceholderStyle.question) ==
        "SELECT * FROM t WHERE a = ? AND (b = ? OR c = ?) LIMIT ?");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.dollarNumbered) ==
        "SELECT * FROM t WHERE a = $1 AND (b = $2 OR c = $3) LIMIT $4");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.percentS) ==
        "SELECT * FROM t WHERE a = %s AND (b = %s OR c = %s) LIMIT %s");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.atNamed) ==
        "SELECT * FROM t WHERE a = @p1 AND (b = @p2 OR c = @p3) LIMIT @p4");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.colonNamed) ==
        "SELECT * FROM t WHERE a = :p1 AND (b = :p2 OR c = :p3) LIMIT :p4");
      assert(q.params.length == 4);
      for (var i = 0; i < 4; i += 1) {
        assert(paramText(q.params[i]) == "int:${(i + 1).toString()}");
      }
      let r = q.render(Dialect.sqlite, PlaceholderStyle.dollarNumbered) orelse panic();
      assert(r.params.length == 4);
      assert(PlaceholderStyle.dollarNumbered.placeholder(12) == "$12");
    }

Numbering runs across nested queries, however deep, in the order the
parameters appear.

    test("numbering across nested queries") {
      let deepest = postgres"${"c"}";
      let deeper = postgres"${"b"} || ${deepest}";
      let deep = postgres"${"a"} || ${deeper} || ${"d"}";
      let q = postgres"SELECT ${deep}, ${deep}";
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT $1 || $2 || $3 || $4, $5 || $6 || $7 || $8");
      let texts = new ListBuilder<String>();
      for (let p of q.params) { texts.add(paramText(p)); }
      assert(texts.join(" ", fn (s: String): String { s }) ==
        "text:a text:b text:c text:d text:a text:b text:c text:d");
    }

`%s` doubles each `%` in the text and in names, for Python's `%`
formatting; other styles leave `%` alone.

    test("percent doubling") {
      let col = Identifier.named("100%") orelse panic();
      let q = postgres"SELECT ${col} FROM t WHERE a LIKE 'x%' AND b % 2 = ${1} -- 50%";
      assert(render(q, Dialect.postgres, PlaceholderStyle.percentS) ==
        "SELECT \"100%%\" FROM t WHERE a LIKE 'x%%' AND b %% 2 = %s -- 50%%\n");
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT \"100%\" FROM t WHERE a LIKE 'x%' AND b % 2 = $1 -- 50%\n");
      let m = mysql"SELECT ${col} FROM t WHERE a = ${"%s"}";
      assert(render(m, Dialect.mysql, PlaceholderStyle.percentS) ==
        "SELECT `100%%` FROM t WHERE a = %s");
    }

Named styles fail when their marker is anywhere in the text, even in
quotes, where a driver looking for names could misread it.

    test("named styles and their markers") {
      let cast = postgres"SELECT ${1}::int";
      assert(render(cast, Dialect.postgres, PlaceholderStyle.atNamed) == "SELECT @p1 ::int");
      assert(render(cast, Dialect.postgres, PlaceholderStyle.colonNamed) == "(fails)");
      let user = mysql"SELECT @a + ${1}";
      assert(render(user, Dialect.mysql, PlaceholderStyle.atNamed) == "(fails)");
      assert(render(user, Dialect.mysql, PlaceholderStyle.question) == "SELECT @a + ?");
      let quoted = sqlite"SELECT '12:30', ${1}";
      assert(render(quoted, Dialect.sqlite, PlaceholderStyle.colonNamed) == "(fails)");
      assert(render(quoted, Dialect.sqlite, PlaceholderStyle.atNamed) == "SELECT '12:30', @p1");
    }

## Names

Names are quoted when rendered, for the query's dialect.

    test("names quoted per dialect") {
      let schema = Identifier.named("my schema") orelse panic();
      let table = Identifier.named("a\"b`c") orelse panic();
      let q = sqlite"SELECT * FROM ${schema}.${table} WHERE x = ${1}";
      assert(render(q, Dialect.sqlite, PlaceholderStyle.question) ==
        "SELECT * FROM \"my schema\".\"a\"\"b`c\" WHERE x = ?");
      let pg = postgres"SELECT * FROM ${schema}.${table} WHERE x = ${1}";
      assert(render(pg, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT * FROM \"my schema\".\"a\"\"b`c\" WHERE x = $1");
      let my = mysql"SELECT * FROM ${schema}.${table} WHERE x = ${1}";
      assert(render(my, Dialect.mysql, PlaceholderStyle.question) ==
        "SELECT * FROM `my schema`.`a\"b``c` WHERE x = ?");
      // Plain code makes the same query.
      let b = new QueryBuilder(Dialect.mysql);
      b.appendSafe("SELECT * FROM ");
      b.appendIdentifier(schema);
      b.appendSafe(".");
      b.appendIdentifier(table);
      b.appendSafe(" WHERE x = ");
      b.appendValue(new SqlInt(1.toInt64()));
      let built = b.build() orelse panic();
      assert(render(built, Dialect.mysql, PlaceholderStyle.question) ==
        render(my, Dialect.mysql, PlaceholderStyle.question));
    }

## Spacing around holes

Holes stay their own tokens: rendering adds a space wherever a hole
would otherwise run into the text beside it.

    test("holes stay separate tokens") {
      let a = Identifier.named("a") orelse panic();
      let q = postgres"SELECT x${1}0, ${a}${a}, -${-1}, ${2}'s', (${3}), [${4}]";
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT x $1 0, \"a\" \"a\", - $2, $3 's', ($4), [$5]");
      assert(render(q, Dialect.postgres, PlaceholderStyle.question) ==
        "SELECT x ? 0, \"a\" \"a\", - ?, ? 's', (?), [?]");
      let u = Identifier.named("u") orelse panic();
      let pg = postgres"SELECT U&${u}";
      assert(render(pg, Dialect.postgres, PlaceholderStyle.dollarNumbered) == "SELECT U& \"u\"");
    }

## Values

Values never appear in the SQL text, in any style or dialect, each
rendered for the dialects it's checked for.

    test("values never in the text") {
      let secret = "zq'\"`\\%?$1@p1:p1-- /*";
      let n = new SqlText(secret);
      let qs = [
        sqlite"SELECT ${secret}, ${n}",
        postgres"SELECT ${secret}, ${n}",
        mysql"SELECT ${secret}, ${n}",
        duckdb"SELECT ${secret}, ${n}",
      ];
      for (let q of qs) {
        assert(q.params.length == 2);
        for (let d of allDialects()) {
          for (let style of allStyles()) {
            let r: RenderedQuery? = q.render(d, style) orelse null;
            if (r != null) {
              assert(!contains(r.sql, "zq"));
              assert(r.params.length == 2);
              assert(paramText(r.params[0]) == "text:${secret}");
            } else {
              assert(q.renderProblem(d, style) != null);
              assert(d.name != q.dialect.name);
            }
          }
        }
      }
      assert(contains("abc", "bc"));
    }

## A query's dialect

A query remembers the dialect whose rules checked its text, and renders
only for that dialect, since the same text can read differently in
another. In PostgreSQL, `#` is an operator (bitwise XOR), but in MySQL
it starts a comment, which would hide the hole.

    test("a query renders only for its dialect") {
      let x = 1;
      let q = postgres"SELECT 1 # ${x}";
      assert(q.dialect.name == "postgres");
      assert(render(q, Dialect.postgres, PlaceholderStyle.question) == "SELECT 1 # ?");
      assert(render(q, Dialect.mysql, PlaceholderStyle.question) == "(fails)");
      assert(q.renderProblem(Dialect.mysql, PlaceholderStyle.question) == "query checked for postgres, not mysql");
      assert(q.renderProblem(Dialect.postgres, PlaceholderStyle.question) == null);
      assert(q.renderProblem(Dialect.postgres, PlaceholderStyle.colonNamed) == null);
      let mine = checkTemplate(Dialect.mysql) { b =>
        b.appendSafe("SELECT 1 # ");
        b.appendInt(x);
      };
      assert(mine == "hole inside a quote or comment");
      // PostgreSQL and DuckDB lex alike, but not quite, so they don't mix.
      assert(render(q, Dialect.duckdb, PlaceholderStyle.question) == "(fails)");
      assert(sqlite"SELECT 1".dialect.name == "sqlite");
      assert(mysql"SELECT 1".dialect.name == "mysql");
      assert(duckdb"SELECT 1".dialect.name == "duckdb");
      let named = sqlite"SELECT '12:30', ${x}";
      assert(named.renderProblem(Dialect.sqlite, PlaceholderStyle.colonNamed) == "text has :, which colonNamed uses");
      assert(named.renderProblem(Dialect.postgres, PlaceholderStyle.colonNamed) == "query checked for sqlite, not postgres");
    }

Both MySQL profiles check templates with the same lexer, which already
refuses text the two modes read differently, so a query for either
renders for both.

    test("the MySQL profiles share their queries") {
      let col = Identifier.named("a`b") orelse panic();
      let q = mysql"SELECT ${col}, 'it''s' FROM t WHERE a = ${1}";
      let want = "SELECT `a``b`, 'it''s' FROM t WHERE a = ?";
      assert(render(q, Dialect.mysql, PlaceholderStyle.question) == want);
      assert(render(q, Dialect.mysqlNoBackslashEscapes, PlaceholderStyle.question) == want);
      let b = new QueryBuilder(Dialect.mysqlNoBackslashEscapes);
      b.appendSafe("SELECT ");
      b.appendIdentifier(col);
      b.appendSafe(", 'it''s' FROM t WHERE a = ");
      b.appendInt(1);
      let nbe = b.build() orelse panic();
      assert(nbe.dialect.name == "mysqlNoBackslashEscapes");
      assert(render(nbe, Dialect.mysql, PlaceholderStyle.question) == want);
      assert(render(nbe, Dialect.mysqlNoBackslashEscapes, PlaceholderStyle.question) == want);
      assert(render(nbe, Dialect.sqlite, PlaceholderStyle.question) == "(fails)");
      // Text the two modes end in different places is refused for both.
      for (let d of [Dialect.mysql, Dialect.mysqlNoBackslashEscapes]) {
        let refused = checkTemplate(d) { b =>
          b.appendSafe("SELECT 'a\\', ");
          b.appendInt(1);
          b.appendSafe(" -- '");
        };
        assert(refused == "backslash before a quote or backslash in a string");
      }
    }

A nested query must be for a dialect the builder's checks cover, the
same rule as for rendering; tags panic, as for any template mistake.

    test("nested queries keep to one dialect") {
      let pg = postgres"1 # ${1}";
      let into = checkTemplate(Dialect.mysql) { b =>
        b.appendSafe("SELECT ");
        b.appendQuery(pg);
      };
      assert(into == "nested query checked for postgres, not mysql");
      let same = checkTemplate(Dialect.postgres) { b =>
        b.appendSafe("SELECT ");
        b.appendQuery(pg);
      };
      assert(same == "ok");
      let my = mysql"${1}";
      let shared = checkTemplate(Dialect.mysqlNoBackslashEscapes) { b =>
        b.appendSafe("SELECT ");
        b.appendQuery(my);
      };
      assert(shared == "ok");
      for (let d of allDialects()) {
        let q = valueQuery(d, "v");
        for (let outer of allDialects()) {
          let got = checkTemplate(outer) { b =>
            b.appendSafe("SELECT ");
            b.appendQuery(q);
          };
          let mysqls = hasAt(d.name, String.begin, "mysql") && hasAt(outer.name, String.begin, "mysql");
          assert((got == "ok") == (d.name == outer.name || mysqls));
        }
      }
    }

## Parts from holes

Tags and the builder never make a hole into a `QueryText`: values
become `QueryParam`s, names `QueryName`s, and a nested query keeps its
own parts. Only `Query.unchecked` can put arbitrary text in a query.

    let partKinds(q: Query): String {
      let kinds = new ListBuilder<String>();
      for (let p of q.parts) {
        kinds.add(when (p) {
          is QueryText -> if (contains(p.text, "zq")) { "LEAK" } else { "text" };
          is QueryParam -> "param";
          is QueryName -> "name";
          else -> "other";
        });
      }
      kinds.join(" ", fn (s: String): String { s })
    }

`valueQuery` is a query for a dialect that's just one value.

    let valueQuery(d: Dialect, value: String): Query {
      let b = new QueryBuilder(d);
      b.appendString(value);
      b.build() orelse panic()
    }

    test("holes never become text") {
      let evil = "zq' OR 1=1 --";
      let col = Identifier.named("zq") orelse panic();
      let inner = postgres"${evil}";
      let tagged = [
        sqlite"SELECT ${col} WHERE a = ${evil} AND b = ${new SqlText(evil)}",
        postgres"SELECT ${col} WHERE a = ${evil} AND b = ${new SqlText(evil)}",
        mysql"SELECT ${col} WHERE a = ${evil} AND b = ${new SqlText(evil)}",
        duckdb"SELECT ${col} WHERE a = ${evil} AND b = ${new SqlText(evil)}",
      ];
      for (let q of tagged) {
        assert(partKinds(q) == "text name text param text param");
      }
      assert(partKinds(postgres"SELECT ${inner}, ${evil}") == "text param text param");
      for (let d of allDialects()) {
        let b = new QueryBuilder(d);
        b.appendSafe("SELECT ");
        b.appendIdentifier(col);
        b.appendSafe(" WHERE a = ");
        b.appendString(evil);
        b.appendSafe(" AND b = ");
        b.appendValue(new SqlText(evil));
        b.appendSafe(", ");
        b.appendQuery(valueQuery(d, evil));
        assert(partKinds(b.build() orelse panic()) == "text name text param text param text param");
      }
      let text: QueryPart = new QueryText("SELECT 'zq'");
      let raw = Query.unchecked(Dialect.sqlite, [text]);
      assert(partKinds(raw) == "LEAK");
      assert(raw.params.isEmpty);
    }

`unchecked` takes any list of parts, even a `ListBuilder`, and keeps its
own copy, so changes the caller makes later leave the query's parts and
params as they were, and consistent.

    test("unchecked copies its parts") {
      let parts = new ListBuilder<QueryPart>();
      parts.add(new QueryText("SELECT "));
      parts.add(new QueryParam(new SqlInt(1.toInt64())));
      let q = Query.unchecked(Dialect.sqlite, parts);
      parts.add(new QueryText(", "));
      parts.add(new QueryParam(new SqlInt(2.toInt64())));
      parts.set(0, new QueryText("DELETE "));
      assert(q.parts.length == 2);
      assert(q.params.length == 1);
      assert(paramText(q.params[0]) == "int:1");
      assert(qmarks(q) == "SELECT ?");
      assert(q.dialect.name == "sqlite");
      let r = q.render(Dialect.sqlite, PlaceholderStyle.dollarNumbered) orelse panic();
      assert(r.sql == "SELECT $1");
      assert(r.params.length == 1);
    }

## The site's example

The site's opening example: one common query, checked for every
database, and what each database's driver gets. The lines between the
`snippet` comments go on the site, and the demos in `demos/example/`
build the same query from each language, printing what these asserts
check.

    test("the site's example") {
      // snippet: temper
      let word = "Launch";
      let q = sql"""
        "SELECT title, "dueDate" FROM tasks
        "WHERE title LIKE ${word} || '%' ESCAPE '!'
        "ORDER BY "dueDate" NULLS LAST
        "LIMIT ${20} OFFSET ${40}
      ;
      let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
      // end snippet
      assert(r.sql == "SELECT \"title\", \"dueDate\" FROM \"tasks\" WHERE \"title\" LIKE (CAST($1 AS TEXT) || '%') ESCAPE '!' ORDER BY \"dueDate\" LIMIT $2 OFFSET $3");
      assert(r.params.length == 3);
      assert(paramText(r.params[0]) == "text:${word}");
      assert(qmarks(q) == "SELECT \"title\", \"dueDate\" FROM \"tasks\" WHERE \"title\" LIKE (? || '%') ESCAPE '!' ORDER BY \"dueDate\" NULLS LAST LIMIT ? OFFSET ?");
      assert(render(q, Dialect.mysql, PlaceholderStyle.percentS) ==
        "SELECT `title`, `dueDate` FROM `tasks` WHERE `title` LIKE (CONCAT(%s, '%%')) ESCAPE '!' ORDER BY `dueDate` IS NULL, `dueDate` LIMIT %s OFFSET %s");
      assert(render(q, Dialect.duckdb, PlaceholderStyle.dollarNumbered) ==
        "SELECT \"title\", \"dueDate\" FROM \"tasks\" WHERE \"title\" LIKE ($1 || '%') ESCAPE '!' ORDER BY \"dueDate\" NULLS LAST LIMIT $2 OFFSET $3");
      let bare = new QueryBuilder(Dialect.common);
      bare.appendSafe("SELECT title, dueDate FROM tasks");
      assert(bare.templateProblem ==
        "bare name not lowercase; quote it to keep its case, at line 1, column 15: SELECT title, dueDate FROM tasks");
    }

## The site's dialect cards

The site's cards on where dialects differ. The lines between a
`card: NAME` comment and an `end card` comment go on the site: each
`let` is a value, and each `assert` a row, showing what one dialect
does with it. `site/build.py` reads only these shapes, and fails on
anything else.

`quotedString` and `quotedName` quote for a dialect, or say why they
can't.

    let quotedString(d: Dialect, s: String): String {
      d.quoteString(s) orelse "refused: ${d.stringProblem(s) ?? ""}"
    }

    let quotedName(d: Dialect, s: String): String {
      d.quoteName(s) orelse "refused: ${d.nameProblem(s) ?? ""}"
    }

`withHole` builds a template for a dialect, as its tag would: `before`,
then `value` in a hole, then `after`. It gives the SQL, with `$1` for
PostgreSQL and DuckDB and `?` otherwise, or says why it's refused. The
value is always the query's one parameter.

    let withHole(d: Dialect, before: String, value: String, after: String): String {
      let b = new QueryBuilder(d);
      b.appendSafe(before);
      b.appendString(value);
      b.appendSafe(after);
      let q: Query? = b.build() orelse null;
      if (q != null) {
        if (q.params.length != 1 || paramText(q.params[0]) != "text:${value}") { panic(); }
        let style = if (d.name == "postgres" || d.name == "duckdb") {
          PlaceholderStyle.dollarNumbered
        } else {
          PlaceholderStyle.question
        };
        render(q, d, style)
      } else {
        "refused: ${b.templateProblem ?? ""}"
      }
    }

MySQL and MariaDB read a backslash in a string as an escape, unless
`NO_BACKSLASH_ESCAPES` is on, so only the `mysql` profile doubles it.
A template's own strings can't hold a backslash before a quote or
backslash for MySQL, since the two modes end such a string in different
places.

    test("the site's card on backslashes") {
      // card: backslashes
      let path = "C:\\temp\\";
      assert(quotedString(Dialect.sqlite, path) == "'C:\\temp\\'");
      assert(quotedString(Dialect.postgres, path) == "'C:\\temp\\'");
      assert(quotedString(Dialect.duckdb, path) == "'C:\\temp\\'");
      assert(quotedString(Dialect.mysqlNoBackslashEscapes, path) == "'C:\\temp\\'");
      assert(quotedString(Dialect.mysql, path) == "'C:\\\\temp\\\\'");
      assert(withHole(Dialect.sqlite, "SELECT ", path, " = 'C:\\temp\\'") == "SELECT ? = 'C:\\temp\\'");
      assert(withHole(Dialect.mysql, "SELECT ", path, " = 'C:\\temp\\'") ==
        "refused: backslash before a quote or backslash in a string");
      // end card
      assert(withHole(Dialect.postgres, "SELECT ", path, " = 'C:\\temp\\'") == "SELECT $1 = 'C:\\temp\\'");
    }

PostgreSQL cuts names down to 63 bytes, so two long names that differ
only after that would name the same thing. MySQL and MariaDB reject
names over 64 characters, and names ending in whitespace. Each profile
refuses what its database would change or reject, and an `Identifier`,
which can go in any query, must suit every one.

    test("the site's card on names") {
      // card: names
      let long = "revenue_by_customer_segment_and_acquisition_channel_and_month_v1";
      let padded = "total ";
      assert(quotedName(Dialect.postgres, long) == "refused: name longer than 63 UTF-8 bytes");
      assert(quotedName(Dialect.mysql, padded) == "refused: name ends in whitespace");
      assert(quotedName(Dialect.mysqlNoBackslashEscapes, padded) == "refused: name ends in whitespace");
      assert(quotedName(Dialect.sqlite, padded) == "\"total \"");
      assert(quotedName(Dialect.postgres, padded) == "\"total \"");
      assert(quotedName(Dialect.duckdb, padded) == "\"total \"");
      // end card
      assert(quotedName(Dialect.mysql, long) == "`${long}`");
      assert(identifierProblem(long) == "name longer than 63 UTF-8 bytes");
      assert(identifierProblem(padded) == "name ends in whitespace");
    }

PostgreSQL and DuckDB nest block comments, and SQLite and MySQL don't,
so the same text can leave a hole in a comment for one and in code for
the other. Each dialect reads it its own way.

    test("the site's card on comments") {
      // card: comments
      let name = "Ann";
      assert(withHole(Dialect.sqlite, "SELECT 1 /* /* */, ", name, "") == "SELECT 1 /* /* */, ?");
      assert(withHole(Dialect.mysql, "SELECT 1 /* /* */, ", name, "") == "SELECT 1 /* /* */, ?");
      assert(withHole(Dialect.postgres, "SELECT 1 /* /* */, ", name, "") ==
        "refused: hole inside a quote or comment");
      assert(withHole(Dialect.duckdb, "SELECT 1 /* /* */, ", name, "") ==
        "refused: hole inside a quote or comment");
      // end card
      assert(withHole(Dialect.postgres, "SELECT 1 /* /* */ */, ", name, "") == "SELECT 1 /* /* */ */, $1");
      assert(withHole(Dialect.duckdb, "SELECT 1 /* /* */ */, ", name, "") == "SELECT 1 /* /* */ */, $1");
    }
