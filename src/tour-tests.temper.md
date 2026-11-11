# Tour Tests

The tour, in Temper: the same steps as the programs in `demos/tour/`,
with the `sql` tag where they use a `QueryBuilder`. It collects each
line it would print, and checks them against `tourOutput`, below, which
`demos/run.py` checks is `demos/tour/expected.txt`, so the Temper prints
what every language prints. The site shows the lines between each
`snippet` comment and its `end snippet` as the tour's Temper tab.

## Setup

    // snippet: setup
    // Each database, with a placeholder style its drivers take.
    class Database(public name: String, public dialect: Dialect, public style: PlaceholderStyle) {}

    let tourDatabases: List<Database> = [
      new Database("sqlite", Dialect.sqlite, PlaceholderStyle.question),
      new Database("postgres", Dialect.postgres, PlaceholderStyle.dollarNumbered),
      new Database("mysql", Dialect.mysql, PlaceholderStyle.percentS),
      new Database("duckdb", Dialect.duckdb, PlaceholderStyle.dollarNumbered),
    ];

    // A query's SQL for a database, with that style's placeholders.
    let sqlFor(q: Query, d: Dialect, style: PlaceholderStyle): String {
      let r = q.render(d, style) orelse panic();
      r.sql
    }

    let forEachDatabase(out: ListBuilder<String>, q: Query): Void {
      for (let db of tourDatabases) {
        out.add("${db.name}: ${sqlFor(q, db.dialect, db.style)}");
      }
    }

    // Values as SQL would write them, joined.
    let joinedValues(values: List<SqlValue>): String {
      values.join(", ", fn (v: SqlValue): String { v.toString() })
    }

    // A common query built in code, as the other languages build it, for
    // what the sql tag would refuse, or would build in pieces.
    let common(text: String): QueryBuilder {
      let b = new QueryBuilder(Dialect.common);
      b.appendSafe(text);
      b
    }
    // end snippet

    let section(out: ListBuilder<String>, title: String): Void {
      out.add("");
      out.add("## ${title}");
    }

## Building a query in code

    // snippet: dynamic
    // Filters only when given, a sort column from the caller, and a page.
    // Every variant is still checked when it's built.
    let search(
      word: String?,
      minTotal: Int?,
      sort: Identifier,
      descending: Boolean,
      page: Int,
    ): String {
      let b = common("SELECT id, title FROM orders");
      var joiner = " WHERE ";
      if (word != null) {
        b.appendSafe("${joiner}title LIKE ");
        b.appendString(word);
        b.appendSafe(" || '%' ESCAPE '!'");
        joiner = " AND ";
      }
      if (minTotal != null) {
        b.appendSafe("${joiner}total >= ");
        b.appendInt(minTotal);
      }
      b.appendSafe(" ORDER BY ");
      b.appendIdentifier(sort);
      b.appendSafe(if (descending) { " DESC LIMIT " } else { " LIMIT " });
      b.appendInt(20);
      b.appendSafe(" OFFSET ");
      b.appendInt(page * 20);
      sqlFor(b.build() orelse panic(), Dialect.postgres, PlaceholderStyle.dollarNumbered)
    }
    // end snippet

`firstDifference` says where two texts first differ, by line.

    let firstDifference(got: String, want: String): String {
      let gotLines = got.split("\n");
      let wantLines = want.split("\n");
      for (var i = 0; i < gotLines.length || i < wantLines.length; i += 1) {
        let g = if (i < gotLines.length) { gotLines[i] } else { "(nothing)" };
        let w = if (i < wantLines.length) { wantLines[i] } else { "(nothing)" };
        if (g != w) { return "line ${(i + 1).toString()}: got ${g}, want ${w}"; }
      }
      "the same"
    }

## The tour

    test("the tour") {
      let out = new ListBuilder<String>();
      // say collects each line, for the check at the end.
      let say(line: String): Void { out.add(line); }
      say("# Wherewith tour");

      section(out, "1. Write it once");

      // snippet: write-once
      // One query, as plain SQL with holes for values. The sql tag checks
      // it for every database, and panics if it's refused.
      let q = sql"""
        "SELECT name, coalesce(nick, name) AS shown FROM users
        "WHERE id IN (${7}, ${9}) ORDER BY name NULLS LAST LIMIT ${10}
      ;
      // Rendered for Dialect.common, it's the canonical form, for logs.
      say("common: ${sqlFor(q, Dialect.common, PlaceholderStyle.question)}");
      // PostgreSQL already sorts nulls last going up, so it needs no NULLS
      // LAST, and MySQL has no NULLS, so it sorts by name IS NULL first.
      forEachDatabase(out, q);
      // Values print as SQL would write them, for reading only.
      say("params: ${joinedValues(q.params)}");
      // end snippet

      section(out, "2. Values are bound, never spliced");

      // snippet: bound
      let name = "Robert'); DROP TABLE students; --";
      // Building SQL by hand puts the value in the text, where it ends the
      // string early and adds a statement of its own.
      say("by hand: SELECT id FROM students WHERE name = '${name}'");
      // A hole sends the value apart from the SQL, for the driver to bind.
      let r = sql"SELECT id FROM students WHERE name = ${name}".render(
        Dialect.sqlite, PlaceholderStyle.question) orelse panic();
      say("wherewith: ${r.sql}");
      say("params: ${joinedValues(r.params)}");

      // A name from outside is an Identifier, quoted for each database,
      // never a value or SQL.
      let table = Identifier.named("students\"; DROP TABLE x; --") orelse panic();
      let named = sql"SELECT * FROM ${table}";
      say("a hostile name: ${sqlFor(named, Dialect.sqlite, PlaceholderStyle.question)}");
      say("in MySQL: ${sqlFor(named, Dialect.mysql, PlaceholderStyle.percentS)}");

      // A hole inside quotes is refused: it would be text, not a value.
      // The tag would panic, so this builds it in code.
      let quoted = common("SELECT id FROM students WHERE name = '");
      quoted.appendString(name);
      quoted.appendSafe("'");
      say("a hole in quotes: ${quoted.templateProblem ?? ""}");
      // end snippet

      section(out, "3. Refused when it's built");

      // snippet: refused
      // Each of these runs on every database, and gives different results
      // on some. templateProblem says why build would refuse it, and
      // where; the sql tag would panic with the same.
      let refused(text: String): Void {
        say("${text}: ${common(text).templateProblem ?? "built"}");
      }

      // 7 / 2 is 3 in SQLite and PostgreSQL, and 3.5 in MySQL and DuckDB.
      refused("SELECT a / 2 FROM t");
      // b = NULL matches no row: NULL isn't equal to anything, even NULL.
      refused("SELECT a FROM t WHERE b = NULL");
      // PostgreSQL reads Name as name; the others keep its case.
      refused("SELECT Name FROM t");
      // SQLite gives any row's a; the others refuse the query.
      refused("SELECT a, count(*) AS n FROM t GROUP BY b");
      // SQLite reads ('a' || 1) + 2, PostgreSQL 'a' || (1 + 2).
      refused("SELECT 'a' || 1 + 2 AS x");
      // Some databases turn 0 into text, and others refuse it.
      refused("SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t");
      // Databases name a + 1 differently (a+1, ?column?, or (a + 1)), so
      // an expression in a FROM subquery needs an alias.
      refused("SELECT * FROM (SELECT a + 1 FROM t) AS s");
      // A placeholder in the text would shift every value's place.
      refused("SELECT a FROM t WHERE id = ?");
      // What isn't in the common dialect yet is refused too.
      refused("SELECT 1 AS a UNION SELECT 2");
      // The fix for the first: a float operand divides the same everywhere.
      refused("SELECT 7 / 2.0 AS x");
      // A null value is refused where NULL would be.
      let withNull = common("SELECT a FROM t WHERE b = ");
      withNull.appendString(null);
      say("SELECT a FROM t WHERE b = \${null}: ${withNull.templateProblem ?? ""}");
      // end snippet

      section(out, "4. What differs, handled");

      // snippet: differs
      // MySQL's || means OR, so it's CONCAT there.
      say("SELECT id || ':' || name AS tag FROM people");
      forEachDatabase(out, sql"SELECT id || ':' || name AS tag FROM people");
      // Each database names its types differently, and MySQL's LENGTH
      // counts bytes, not characters.
      say("SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people");
      forEachDatabase(out, sql"SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people");
      // Where nulls sort differs, and so does OFFSET without LIMIT.
      say("SELECT name FROM people ORDER BY nick DESC OFFSET \${20}");
      forEachDatabase(out, sql"SELECT name FROM people ORDER BY nick DESC OFFSET ${20}");
      // PostgreSQL can't guess a lone parameter's type, so it gets a cast.
      say("SELECT \${\"hi\"} AS greeting");
      forEachDatabase(out, sql"SELECT ${"hi"} AS greeting");
      // end snippet

      section(out, "5. Queries in queries");

      // snippet: nested
      let big = sql"SELECT user_id FROM orders WHERE total > ${100}";
      let both = sql"SELECT name FROM users WHERE id IN (${big}) AND active = ${"yes"}";
      // The inner query's parameters are numbered with the outer query's.
      say("postgres: ${sqlFor(both, Dialect.postgres, PlaceholderStyle.dollarNumbered)}");
      say("mysql: ${sqlFor(both, Dialect.mysql, PlaceholderStyle.percentS)}");
      // And it's checked again as part of the whole, with problems at its
      // hole.
      let inner = sql"SELECT user_id FROM orders LIMIT ${5}";
      let outer = common("SELECT name FROM people WHERE id IN (");
      outer.appendQuery(inner);
      outer.appendSafe(")");
      say("with LIMIT inside: ${outer.templateProblem ?? ""}");
      // end snippet

      section(out, "6. Building queries in code");

      // snippet: dynamic
      let created = Identifier.named("created") orelse panic();
      say(search(null, null, created, false, 0));
      say(search("Launch", null, created, false, 0));
      say(search(null, 100, Identifier.named("total") orelse panic(), true, 2));

      // A query for fewer databases relaxes the checks for the others:
      // MySQL reads \ in a string as an escape, so it's refused only while
      // MySQL is a target. The query renders only for its targets.
      let few = new QueryBuilder(Dialect.common);
      few.targets = [Dialect.postgres, Dialect.sqlite];
      few.appendSafe("SELECT 'C:\\temp' AS p");
      let path = few.build() orelse panic();
      say("for postgres and sqlite: ${sqlFor(path, Dialect.postgres, PlaceholderStyle.dollarNumbered)}");
      say("for mysql: ${path.renderProblem(Dialect.mysql, PlaceholderStyle.percentS) ?? ""}");
      // end snippet

      section(out, "7. Placeholders for each driver");

      // snippet: placeholders
      // The placeholder style depends on the driver, not the database, so
      // it's chosen when rendering. percentS doubles %, for drivers that
      // fill in values with Python's % formatting.
      let like = sql"SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ${1}";
      let styles = [
        PlaceholderStyle.question,
        PlaceholderStyle.dollarNumbered,
        PlaceholderStyle.percentS,
        PlaceholderStyle.atNamed,
        PlaceholderStyle.colonNamed,
      ];
      for (let style of styles) {
        say("${style.toString()}: ${sqlFor(like, Dialect.sqlite, style)}");
      }
      // A named style refuses text holding its marker, which a driver
      // could misread as a name.
      let colon = sql"SELECT 'a:b' AS s FROM users WHERE id = ${1}";
      say("colonNamed with 'a:b': ${colon.renderProblem(Dialect.sqlite, PlaceholderStyle.colonNamed) ?? ""}");
      // end snippet

      section(out, "8. Each database's own SQL");

      // snippet: own-sql
      // For SQL the common dialect doesn't cover yet, a database's own
      // template, checked with its rules.
      let upsert = postgres"INSERT INTO tags (name) VALUES (${"sql"}) ON CONFLICT (name) DO NOTHING RETURNING id";
      say("upsert: ${sqlFor(upsert, Dialect.postgres, PlaceholderStyle.dollarNumbered)}");
      // It renders only for its own database.
      say("for mysql: ${upsert.renderProblem(Dialect.mysql, PlaceholderStyle.percentS) ?? ""}");
      // A common query nests in it, rendered for that database.
      let agg = postgres"SELECT jsonb_agg(x) FROM (${big}) AS s(x)";
      say("nested: ${sqlFor(agg, Dialect.postgres, PlaceholderStyle.dollarNumbered)}");
      // # starts a comment in MySQL only, so a value after it would vanish.
      // The mysql tag would panic, so this builds it in code.
      let hash = new QueryBuilder(Dialect.mysql);
      hash.appendSafe("SELECT * FROM t WHERE a = 1 # ");
      hash.appendString("x");
      say("mysql, after #: ${hash.templateProblem ?? ""}");
      // end snippet

      section(out, "9. Quoting by hand");

      // snippet: quoting
      // For tools that write SQL text themselves, such as DDL defaults.
      // Each bubbles rather than change what it can't write, and a
      // ...Problem method says why.
      say("mysql name: ${Dialect.mysql.quoteName("my `table`") orelse panic()}");
      say("mysql string: ${Dialect.mysql.quoteString("it's \\ fine") orelse panic()}");
      say("postgres string: ${Dialect.postgres.quoteString("it's \\ fine") orelse panic()}");
      let longName = new StringBuilder();
      for (var i = 0; i < 64; i += 1) { longName.append("n"); }
      let long = longName.toString();
      say("postgres, 64-byte name: ${Dialect.postgres.nameProblem(long) ?? ""}");
      let withNul = "a${String.fromCodePoint(0) orelse panic()}b";
      say("postgres, NUL in a string: ${
        do { Dialect.postgres.quoteString(withNul); "quoted" }
        orelse "refused, ${Dialect.postgres.stringProblem(withNul) ?? ""}"
      }");
      say("Identifier, 64 bytes: ${
        do { Identifier.named(long); "named" }
        orelse "refused, ${identifierProblem(long) ?? ""}"
      }");
      // end snippet

      // The tour stops at what the driver gets. The repo's tests/engines
      // run these kinds of queries through SQLite, DuckDB, PostgreSQL, and
      // MariaDB.
      // Each line ends in a line break, as printed.
      let got = "${out.toList().join("\n", fn (s: String): String { s })}\n";
      assert(got == tourOutput) { firstDifference(got, tourOutput) }
    }

## What it prints

The same as `demos/tour/expected.txt`.
`demos/run.py` checks that the two agree.

<!-- tour output: start -->

    let tourOutput = """
      "# Wherewith tour
      "
      "## 1. Write it once
      "common: SELECT name, COALESCE(nick, name) AS shown FROM users WHERE id IN (?, ?) ORDER BY name NULLS LAST LIMIT ?
      "sqlite: SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users" WHERE "id" IN (?, ?) ORDER BY "name" NULLS LAST LIMIT ?
      "postgres: SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users" WHERE "id" IN ($1, $2) ORDER BY "name" LIMIT $3
      "mysql: SELECT `name`, COALESCE(`nick`, `name`) AS `shown` FROM `users` WHERE `id` IN (%s, %s) ORDER BY `name` IS NULL, `name` LIMIT %s
      "duckdb: SELECT "name", COALESCE("nick", "name") AS "shown" FROM "users" WHERE "id" IN ($1, $2) ORDER BY "name" NULLS LAST LIMIT $3
      "params: 7, 9, 10
      "
      "## 2. Values are bound, never spliced
      "by hand: SELECT id FROM students WHERE name = 'Robert'); DROP TABLE students; --'
      "wherewith: SELECT "id" FROM "students" WHERE "name" = ?
      "params: 'Robert''); DROP TABLE students; --'
      "a hostile name: SELECT * FROM "students""; DROP TABLE x; --"
      "in MySQL: SELECT * FROM `students"; DROP TABLE x; --`
      "a hole in quotes: hole inside a quote or comment, at line 1, column 39: dents WHERE name = '
      "
      "## 3. Refused when it's built
      "SELECT a / 2 FROM t: / without a float operand; databases divide integers differently, at line 1, column 10: SELECT a / 2 FROM t
      "SELECT a FROM t WHERE b = NULL: = NULL is never true; use IS NULL, at line 1, column 25: CT a FROM t WHERE b = NULL
      "SELECT Name FROM t: bare name not lowercase; quote it to keep its case, at line 1, column 8: SELECT Name FROM t
      "SELECT a, count(*) AS n FROM t GROUP BY b: a is neither grouped nor aggregated; databases differ, at line 1, column 8: SELECT a, count(*) AS n FRO
      "SELECT 'a' || 1 + 2 AS x: arithmetic beside || needs parentheses; databases group them differently, at line 1, column 17: SELECT 'a' || 1 + 2 AS x
      "SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t: CASE mixes text and a number, at line 1, column 38: a > 1 THEN 'x' ELSE 0 END AS c FROM t
      "SELECT * FROM (SELECT a + 1 FROM t) AS s: an expression in a FROM subquery needs an alias; databases name it differently, at line 1, column 23: LECT * FROM (SELECT a + 1 FROM t) AS s
      "SELECT a FROM t WHERE id = ?: ? outside quotes; put values in holes, at line 1, column 28: a FROM t WHERE id = ?
      "SELECT 1 AS a UNION SELECT 2: UNION isn't in the common dialect yet, at line 1, column 15: SELECT 1 AS a UNION SELECT 2
      "SELECT 7 / 2.0 AS x: built
      "SELECT a FROM t WHERE b = \${null}: = with a null value is never true; use IS NULL, at line 1, column 25: CT a FROM t WHERE b = \${…}
      "
      "## 4. What differs, handled
      "SELECT id || ':' || name AS tag FROM people
      "sqlite: SELECT "id" || ':' || "name" AS "tag" FROM "people"
      "postgres: SELECT "id" || ':' || "name" AS "tag" FROM "people"
      "mysql: SELECT CONCAT(`id`, ':', `name`) AS `tag` FROM `people`
      "duckdb: SELECT "id" || ':' || "name" AS "tag" FROM "people"
      "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people
      "sqlite: SELECT CAST("score" AS INTEGER) AS "s", CAST("id" AS TEXT) AS "t", LENGTH("name") AS "n" FROM "people"
      "postgres: SELECT CAST("score" AS BIGINT) AS "s", CAST("id" AS TEXT) AS "t", LENGTH("name") AS "n" FROM "people"
      "mysql: SELECT CAST(`score` AS SIGNED) AS `s`, CAST(`id` AS CHAR) AS `t`, CHAR_LENGTH(`name`) AS `n` FROM `people`
      "duckdb: SELECT CAST("score" AS BIGINT) AS "s", CAST("id" AS VARCHAR) AS "t", LENGTH("name") AS "n" FROM "people"
      "SELECT name FROM people ORDER BY nick DESC OFFSET \${20}
      "sqlite: SELECT "name" FROM "people" ORDER BY "nick" DESC LIMIT -1 OFFSET ?
      "postgres: SELECT "name" FROM "people" ORDER BY "nick" DESC NULLS LAST OFFSET $1
      "mysql: SELECT `name` FROM `people` ORDER BY `nick` DESC LIMIT 18446744073709551615 OFFSET %s
      "duckdb: SELECT "name" FROM "people" ORDER BY "nick" DESC NULLS LAST OFFSET $1
      "SELECT \${"hi"} AS greeting
      "sqlite: SELECT ? AS "greeting"
      "postgres: SELECT CAST($1 AS TEXT) AS "greeting"
      "mysql: SELECT %s AS `greeting`
      "duckdb: SELECT $1 AS "greeting"
      "
      "## 5. Queries in queries
      "postgres: SELECT "name" FROM "users" WHERE "id" IN (SELECT "user_id" FROM "orders" WHERE "total" > $1) AND "active" = $2
      "mysql: SELECT `name` FROM `users` WHERE `id` IN (SELECT `user_id` FROM `orders` WHERE `total` > %s) AND `active` = %s
      "with LIMIT inside: LIMIT in an IN subquery; MySQL refuses it, at line 1, column 38: people WHERE id IN (\${…})
      "
      "## 6. Building queries in code
      "SELECT "id", "title" FROM "orders" ORDER BY "created" NULLS FIRST LIMIT $1 OFFSET $2
      "SELECT "id", "title" FROM "orders" WHERE "title" LIKE (CAST($1 AS TEXT) || '%') ESCAPE '!' ORDER BY "created" NULLS FIRST LIMIT $2 OFFSET $3
      "SELECT "id", "title" FROM "orders" WHERE "total" >= $1 ORDER BY "total" DESC NULLS LAST LIMIT $2 OFFSET $3
      "for postgres and sqlite: SELECT 'C:\\temp' AS "p"
      "for mysql: common query checked for postgres, sqlite, not mysql
      "
      "## 7. Placeholders for each driver
      "question: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = ?
      "dollarNumbered: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = $1
      "percentS: SELECT "name" FROM "users" WHERE "name" LIKE 'a%%' ESCAPE '!' AND "id" = %s
      "atNamed: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = @p1
      "colonNamed: SELECT "name" FROM "users" WHERE "name" LIKE 'a%' ESCAPE '!' AND "id" = :p1
      "colonNamed with 'a:b': text has :, which colonNamed uses
      "
      "## 8. Each database's own SQL
      "upsert: INSERT INTO tags (name) VALUES ($1) ON CONFLICT (name) DO NOTHING RETURNING id
      "for mysql: query checked for postgres, not mysql
      "nested: SELECT jsonb_agg(x) FROM (SELECT "user_id" FROM "orders" WHERE "total" > $1) AS s(x)
      "mysql, after #: hole inside a quote or comment
      "
      "## 9. Quoting by hand
      "mysql name: `my ``table```
      "mysql string: 'it''s \\\\ fine'
      "postgres string: 'it''s \\ fine'
      "postgres, 64-byte name: name longer than 63 UTF-8 bytes
      "postgres, NUL in a string: refused, NUL in string
      "Identifier, 64 bytes: refused, name longer than 63 UTF-8 bytes
    ;

<!-- tour output: end -->
