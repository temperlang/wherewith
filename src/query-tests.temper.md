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
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT * FROM t WHERE a = $1 AND (b = $2 OR c = $3) LIMIT $4");
      assert(render(q, Dialect.mysql, PlaceholderStyle.percentS) ==
        "SELECT * FROM t WHERE a = %s AND (b = %s OR c = %s) LIMIT %s");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.atNamed) ==
        "SELECT * FROM t WHERE a = @p1 AND (b = @p2 OR c = @p3) LIMIT @p4");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.colonNamed) ==
        "SELECT * FROM t WHERE a = :p1 AND (b = :p2 OR c = :p3) LIMIT :p4");
      assert(q.params.length == 4);
      for (var i = 0; i < 4; i += 1) {
        assert(paramText(q.params[i]) == "int:${(i + 1).toString()}");
      }
      let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
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

Names are quoted when rendered, so one query works for every dialect.

    test("names quoted per dialect") {
      let schema = Identifier.named("my schema") orelse panic();
      let table = Identifier.named("a\"b`c") orelse panic();
      let q = sqlite"SELECT * FROM ${schema}.${table} WHERE x = ${1}";
      assert(render(q, Dialect.sqlite, PlaceholderStyle.question) ==
        "SELECT * FROM \"my schema\".\"a\"\"b`c\" WHERE x = ?");
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT * FROM \"my schema\".\"a\"\"b`c\" WHERE x = $1");
      assert(render(q, Dialect.mysql, PlaceholderStyle.question) ==
        "SELECT * FROM `my schema`.`a\"b``c` WHERE x = ?");
      // Plain code makes the same query.
      let b = new QueryBuilder(Dialect.sqlite);
      b.appendSafe("SELECT * FROM ");
      b.appendIdentifier(schema);
      b.appendSafe(".");
      b.appendIdentifier(table);
      b.appendSafe(" WHERE x = ");
      b.appendValue(new SqlInt(1.toInt64()));
      let built = b.build() orelse panic();
      assert(render(built, Dialect.mysql, PlaceholderStyle.question) ==
        render(q, Dialect.mysql, PlaceholderStyle.question));
    }

## Spacing around holes

Holes stay their own tokens: rendering adds a space wherever a hole
would otherwise run into the text beside it.

    test("holes stay separate tokens") {
      let a = Identifier.named("a") orelse panic();
      let q = postgres"SELECT x${1}0, ${a}${a}, -${-1}, ${2}'s', (${3}), [${4}]";
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT x $1 0, \"a\" \"a\", - $2, $3 's', ($4), [$5]");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.question) ==
        "SELECT x ? 0, \"a\" \"a\", - ?, ? 's', (?), [?]");
      let u = Identifier.named("u") orelse panic();
      let pg = postgres"SELECT U&${u}";
      assert(render(pg, Dialect.postgres, PlaceholderStyle.dollarNumbered) == "SELECT U& \"u\"");
    }

## Values

Values never appear in the SQL text, in any style or dialect.

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
            let r = q.render(d, style) orelse panic();
            assert(!contains(r.sql, "zq"));
            assert(r.params.length == 2);
            assert(paramText(r.params[0]) == "text:${secret}");
          }
        }
      }
      assert(contains("abc", "bc"));
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
        b.appendQuery(inner);
        assert(partKinds(b.build() orelse panic()) == "text name text param text param text param");
      }
      let text: QueryPart = new QueryText("SELECT 'zq'");
      let raw = Query.unchecked([text]);
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
      let q = Query.unchecked(parts);
      parts.add(new QueryText(", "));
      parts.add(new QueryParam(new SqlInt(2.toInt64())));
      parts.set(0, new QueryText("DELETE "));
      assert(q.parts.length == 2);
      assert(q.params.length == 1);
      assert(paramText(q.params[0]) == "int:1");
      assert(qmarks(q) == "SELECT ?");
      let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
      assert(r.sql == "SELECT $1");
      assert(r.params.length == 1);
    }

## The site's example

The site's opening example: one template, rendered for each database.
The lines between the `snippet` comments go on the site, and the
demos in `demos/example/` build the same query from each language,
printing what these asserts check.

    test("the site's example") {
      // snippet: temper
      let name = "Robert'); DROP TABLE students; --";
      let students = Identifier.named("students") orelse panic();
      let q = postgres"SELECT id FROM ${students} WHERE name = ${name}";
      let r = q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered) orelse panic();
      // end snippet
      assert(r.sql == "SELECT id FROM \"students\" WHERE name = $1");
      assert(r.params.length == 1);
      assert(paramText(r.params[0]) == "text:${name}");
      assert(qmarks(q) == "SELECT id FROM \"students\" WHERE name = ?");
      assert(render(q, Dialect.mysql, PlaceholderStyle.percentS) == "SELECT id FROM `students` WHERE name = %s");
      assert(render(q, Dialect.duckdb, PlaceholderStyle.dollarNumbered) == "SELECT id FROM \"students\" WHERE name = $1");
      let quoted = checkTemplate(Dialect.postgres) { b =>
        b.appendSafe("SELECT id FROM students WHERE name = '");
        b.appendString(name);
        b.appendSafe("'");
      };
      assert(quoted == "hole inside a quote or comment");
    }
