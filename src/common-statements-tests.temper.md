# Common Statement Tests

Statements of every form, every refusal with its message and place,
narrowed targets, holes by kind, the `sql` tag end to end, and a
randomized round trip.

## Test helpers

`canon` builds a common query from text, for every target or for
`targets`, and gives it rendered canonically with `?` for each value,
or the problem.

    let canon(text: String): String { narrowed(commonTargets(), text) }

    let narrowed(targets: List<Dialect>, text: String): String {
      let b = new QueryBuilder(Dialect.common);
      b.targets = targets;
      b.appendSafe(text);
      built(b)
    }

    let built(b: QueryBuilder): String {
      let q: Query? = b.build() orelse null;
      if (q != null) { render(q, Dialect.common, PlaceholderStyle.question) } else { b.templateProblem ?? "fails" }
    }

`stmt` is a tag that does the same with holes.

    class StmtTag {
      private b: QueryBuilder = new QueryBuilder(Dialect.common);

      public appendSafe(fixed: String): Void { b.appendSafe(fixed); }
      @overload("append")
      public appendString(x: String?): Void { b.appendString(x); }
      @overload("append")
      public appendInt(x: Int): Void { b.appendInt(x); }
      @overload("append")
      public appendFloat64(x: Float64): Void { b.appendFloat64(x); }
      @overload("append")
      public appendBoolean(x: Boolean): Void { b.appendBoolean(x); }
      @overload("append")
      public appendIdentifier(x: Identifier): Void { b.appendIdentifier(x); }
      @overload("append")
      public appendQuery(x: Query): Void { b.appendQuery(x); }

      // Written out rather than calling `built`, since Temper's C#
      // backend doesn't qualify a test-only function called from a
      // test-only class.
      public get accumulated(): String {
        let q: Query? = b.build() orelse null;
        if (q != null) {
          do { q.render(Dialect.common, PlaceholderStyle.question).sql } orelse "(fails)"
        } else {
          b.templateProblem ?? "fails"
        }
      }
    }

    let stmt = StmtTag;

`parsed` parses text as a statement, without the checks, and prints it
canonically, or with every operand's parentheses for `explicit`.

    let parsed(text: String, explicit: Boolean): String {
      let lexer = new CommonLexer();
      let found = lexer.scan(text) ?? lexer.endProblem();
      if (found != null) { return found; }
      let parser = new CommonParser(lexer);
      let tree: CommonStatement? = parser.parseStatement() orelse null;
      if (tree != null) {
        new CommonPrinter(lexer, explicit).printStatement(tree).runs[0]
      } else {
        parser.problem ?? "fails"
      }
    }

`mismatches` checks each text's problem, at a column of its one line,
and lists those that differ.

    let mismatches(cases: List<Pair<String, Pair<String, Int> > >, targets: List<Dialect>): String {
      let out = new StringBuilder();
      for (let r of cases) {
        let got = narrowed(targets, r.key);
        if (got != placed(r.key, r.value.key, r.value.value)) { out.append("${r.key}: ${got} | "); }
      }
      out.toString()
    }

    let notMysql(): List<Dialect> { [Dialect.sqlite, Dialect.postgres, Dialect.duckdb] }

## Forms

Each statement form, read in any case, and written canonically:
keywords in capitals, `AS` before every alias, `JOIN` and `LEFT JOIN`,
no `ASC`, and `NULLS` only where nulls wouldn't already go there.

    test("common statement forms") {
      let forms = [
        new Pair("SELECT * FROM t", "SELECT * FROM t"),
        new Pair("select distinct a from t", "SELECT DISTINCT a FROM t"),
        new Pair("SELECT a b, c AS \"D\", t.* FROM s.t", "SELECT a AS b, c AS \"D\", t.* FROM s.t"),
        new Pair("SELECT x.a FROM t x", "SELECT x.a FROM t AS x"),
        new Pair(
          "SELECT t.a FROM t INNER JOIN u ON t.id = u.id LEFT OUTER JOIN v ON v.id = u.id CROSS JOIN w",
          "SELECT t.a FROM t JOIN u ON t.id = u.id LEFT JOIN v ON v.id = u.id CROSS JOIN w",
        ),
        new Pair("select a from t join u on true left join v on false", "SELECT a FROM t JOIN u ON TRUE LEFT JOIN v ON FALSE"),
        new Pair("SELECT a FROM t WHERE a > 1 AND b IS NULL", "SELECT a FROM t WHERE a > 1 AND b IS NULL"),
        new Pair(
          "SELECT a, count(*) FROM t GROUP BY a HAVING count(*) > 1",
          "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
        ),
        new Pair(
          "SELECT a FROM t ORDER BY a ASC, b DESC, c NULLS FIRST, d NULLS LAST, e DESC NULLS FIRST, f DESC NULLS LAST",
          "SELECT a FROM t ORDER BY a, b DESC, c, d NULLS LAST, e DESC NULLS FIRST, f DESC",
        ),
        new Pair("SELECT a FROM t LIMIT 10 OFFSET 007", "SELECT a FROM t LIMIT 10 OFFSET 7"),
        new Pair("SELECT a FROM t OFFSET 5", "SELECT a FROM t OFFSET 5"),
        new Pair("SELECT 1", "SELECT 1"),
        new Pair("select 1.5 * 2 as three, 'x' || 'y'", "SELECT 1.5 * 2 AS three, 'x' || 'y'"),
        new Pair("SELECT a FROM (SELECT a FROM t) x", "SELECT a FROM (SELECT a FROM t) AS x"),
        new Pair(
          "SELECT a FROM t WHERE a IN (SELECT b FROM u) AND EXISTS (select 1 from v where v.a = t.a)",
          "SELECT a FROM t WHERE a IN (SELECT b FROM u) AND EXISTS (SELECT 1 FROM v WHERE v.a = t.a)",
        ),
        new Pair("SELECT (SELECT max(b) FROM u) AS m FROM t", "SELECT (SELECT MAX(b) FROM u) AS m FROM t"),
        new Pair("insert into t (a, b) values (1, 'x'), (2, NULL)", "INSERT INTO t (a, b) VALUES (1, 'x'), (2, NULL)"),
        new Pair("INSERT INTO s.t (a) SELECT b FROM u WHERE c = 1", "INSERT INTO s.t (a) SELECT b FROM u WHERE c = 1"),
        new Pair("update t set a = 1, b = 'x' where c = 2", "UPDATE t SET a = 1, b = 'x' WHERE c = 2"),
        new Pair("UPDATE s.t SET a = a + 1", "UPDATE s.t SET a = a + 1"),
        new Pair("delete from t where a = 1", "DELETE FROM t WHERE a = 1"),
        new Pair("DELETE FROM t", "DELETE FROM t"),
        new Pair("SELECT a /* c */ FROM -- x\n t", "SELECT a FROM t"),
        new Pair("SELECT \"Order\".\"Select\" FROM \"Order\"", "SELECT \"Order\".\"Select\" FROM \"Order\""),
        new Pair("SELECT count AS text FROM first", "SELECT \"count\" AS \"text\" FROM \"first\""),
        new Pair("SELECT a FROM t -- end", "SELECT a FROM t"),
      ];
      for (let f of forms) {
        let got = canon(f.key);
        assert(got == f.value) { "${f.key}: ${got}" }
      }
    }

## Grammar refusals

What the grammar refuses, each with its message and place, for every
target.

    test("common statement grammar refusals") {
      let found = mismatches([
        new Pair("", new Pair("expected a statement", 1)),
        new Pair("a = 1", new Pair("expected SELECT, INSERT, UPDATE, or DELETE", 1)),
        new Pair("WITH x AS (SELECT 1) SELECT 1", new Pair("WITH isn't in the common dialect yet", 1)),
        new Pair("SELECT 1 UNION SELECT 2", new Pair("UNION isn't in the common dialect yet", 10)),
        new Pair("SELECT a FROM t RIGHT JOIN u ON a = b", new Pair("RIGHT JOIN isn't in the common dialect yet", 17)),
        new Pair("SELECT a FROM t FULL JOIN u ON a = b", new Pair("FULL JOIN isn't in the common dialect yet", 17)),
        new Pair("SELECT a FROM t NATURAL JOIN u", new Pair("NATURAL JOIN isn't in the common dialect yet", 17)),
        new Pair("SELECT a FROM t JOIN u USING (a)", new Pair("USING isn't in the common dialect yet; use ON", 24)),
        new Pair("SELECT a FROM t JOIN u", new Pair("expected ON", 23)),
        new Pair("SELECT a FROM t LEFT u ON TRUE", new Pair("expected JOIN", 22)),
        new Pair("SELECT a FROM t CROSS JOIN u ON a = b", new Pair("CROSS JOIN takes no ON", 30)),
        new Pair("SELECT a FROM t, u", new Pair("comma joins aren't common SQL; use CROSS JOIN", 16)),
        new Pair("SELECT *", new Pair("* without FROM", 8)),
        new Pair("SELECT 1 WHERE TRUE", new Pair("WHERE without FROM isn't common SQL", 10)),
        new Pair("SELECT 1 GROUP BY 1", new Pair("GROUP BY without FROM isn't common SQL", 10)),
        new Pair("SELECT 1 ORDER BY 1", new Pair("ORDER BY without FROM isn't common SQL", 10)),
        new Pair("SELECT 1 LIMIT 1", new Pair("LIMIT without FROM isn't common SQL", 10)),
        new Pair("SELECT 1 OFFSET 1", new Pair("OFFSET without FROM isn't common SQL", 10)),
        new Pair("SELECT a FROM t HAVING a > 1", new Pair("HAVING without GROUP BY isn't common SQL", 17)),
        new Pair("SELECT a FROM t GROUP a", new Pair("expected BY", 23)),
        new Pair("SELECT a FROM t ORDER a", new Pair("expected BY", 23)),
        new Pair("SELECT a FROM t GROUP BY a WHERE b", new Pair("expected the end of the statement", 28)),
        new Pair("SELECT a FROM t LIMIT -1", new Pair("LIMIT takes an integer or a value", 23)),
        new Pair("SELECT a FROM t LIMIT a", new Pair("LIMIT takes an integer or a value", 23)),
        new Pair("SELECT a FROM t OFFSET 1.5", new Pair("OFFSET takes an integer or a value", 24)),
        new Pair("SELECT a FROM t LIMIT", new Pair("LIMIT takes an integer or a value", 22)),
        new Pair("SELECT a FROM t LIMIT 1 LIMIT 2", new Pair("expected the end of the statement", 25)),
        new Pair("SELECT a FROM t ORDER BY a NULLS", new Pair("expected FIRST or LAST", 33)),
        new Pair("SELECT a FROM t ORDER BY a NULLS middle", new Pair("expected FIRST or LAST", 34)),
        new Pair("SELECT a FROM (SELECT a FROM t)", new Pair("a subquery in FROM needs an alias", 15)),
        new Pair("SELECT a FROM (a)", new Pair("expected SELECT or a nested query", 16)),
        new Pair("SELECT a FROM t.u.v", new Pair("name with more than two parts", 18)),
        new Pair("SELECT a FROM t WHERE", new Pair("expected an expression", 22)),
        new Pair("SELECT a FROM t)", new Pair("unmatched )", 16)),
        new Pair("SELECT a, FROM t", new Pair("expected an expression", 11)),
        new Pair("SELECT a AS FROM t", new Pair("expected a name", 13)),
        new Pair("SELECT a FROM t WHERE a IN (SELECT b FROM u", new Pair("expected )", 44)),
        new Pair("SELECT a FROM t WHERE b = SELECT 1", new Pair("a subquery needs its own parentheses", 27)),
        new Pair("SELECT a FROM t WHERE EXISTS (a)", new Pair("expected SELECT or a nested query", 31)),
        new Pair("INSERT t (a) VALUES (1)", new Pair("expected INTO", 8)),
        new Pair("INSERT INTO t VALUES (1)", new Pair("expected (", 15)),
        new Pair("INSERT INTO t (a, b) VALUES (1)", new Pair("VALUES row has 1 value for 2 columns", 29)),
        new Pair("INSERT INTO t (a) VALUES (1, 2)", new Pair("VALUES row has 2 values for 1 column", 26)),
        new Pair("INSERT INTO t (a) VALUES (1), (2, 3)", new Pair("VALUES row has 2 values for 1 column", 31)),
        new Pair("INSERT INTO t (a) (SELECT b FROM u)", new Pair("a query after INSERT goes without parentheses", 19)),
        new Pair("INSERT INTO t (a) default values", new Pair("expected VALUES or SELECT", 19)),
        new Pair("INSERT INTO t (a) VALUES (1) RETURNING a", new Pair("RETURNING isn't in the common dialect yet", 30)),
        new Pair("INSERT INTO t (t.a) VALUES (1)", new Pair("expected )", 17)),
        new Pair("UPDATE t a = 1", new Pair("expected SET", 10)),
        new Pair("UPDATE t SET t.a = 1", new Pair("SET takes a column without its table", 15)),
        new Pair("UPDATE t SET a = 1 b = 2", new Pair("expected the end of the statement", 20)),
        new Pair("UPDATE t SET a 1", new Pair("expected =", 16)),
        new Pair("DELETE t WHERE a = 1", new Pair("expected FROM", 8)),
        new Pair("DELETE FROM t WHERE", new Pair("expected an expression", 20)),
      ], commonTargets());
      assert(found == "") { found }
      assert(canon("SELECT a\nFROM t\nWHERE a IN (1,)") ==
        at("expected an expression", 3, 15, "WHERE a IN (1,)"));
    }

## Check refusals

What the checks refuse for every target, since the databases would
read it differently, or some would refuse it.

    test("common statement check refusals") {
      let found = mismatches([
        new Pair("SELECT a FROM t WHERE 1", new Pair("a number where a condition goes", 23)),
        new Pair("SELECT a FROM t JOIN u ON 'x'", new Pair("text where a condition goes", 27)),
        new Pair("SELECT a FROM t GROUP BY a HAVING 1", new Pair("a number where a condition goes", 35)),
        new Pair("DELETE FROM t WHERE 'x'", new Pair("text where a condition goes", 21)),
        new Pair("UPDATE t SET a = 1 WHERE 2", new Pair("a number where a condition goes", 26)),
        new Pair("SELECT a / 2 FROM t", new Pair("/ without a float operand; databases divide integers differently", 10)),
        new Pair("UPDATE t SET a = b = NULL", new Pair("= NULL is never true; use IS NULL", 20)),
        new Pair("SELECT a FROM t ORDER BY 'a'", new Pair("a constant in ORDER BY; databases read it differently", 26)),
        new Pair("SELECT a FROM t GROUP BY NULL", new Pair("a constant in GROUP BY; databases read it differently", 26)),
        new Pair("SELECT a FROM t ORDER BY 1 + 1", new Pair("a constant in ORDER BY; databases read it differently", 28)),
        new Pair("SELECT a, b FROM t GROUP BY a", new Pair("b is neither grouped nor aggregated; databases differ", 11)),
        new Pair("SELECT a, count(*) FROM t", new Pair("a is neither grouped nor aggregated; databases differ", 8)),
        new Pair("SELECT * FROM t GROUP BY a", new Pair("* in a grouped query; databases differ", 8)),
        new Pair("SELECT a FROM t GROUP BY a HAVING b > 1", new Pair("b is neither grouped nor aggregated; databases differ", 35)),
        new Pair("SELECT a FROM t GROUP BY a ORDER BY b", new Pair("b is neither grouped nor aggregated; databases differ", 37)),
        new Pair("SELECT u.a FROM t GROUP BY t.a", new Pair("u.a is neither grouped nor aggregated; databases differ", 8)),
        new Pair("SELECT a + 1 FROM t GROUP BY a + 2", new Pair("a is neither grouped nor aggregated; databases differ", 8)),
        new Pair("SELECT a, b FROM t GROUP BY 1", new Pair("b is neither grouped nor aggregated; databases differ", 11)),
        new Pair("SELECT b AS a FROM t WHERE a > 1", new Pair("a is also a SELECT alias; databases differ on which it means", 28)),
        new Pair("SELECT b AS a FROM t GROUP BY a", new Pair("a is also a SELECT alias; databases differ on which it means", 31)),
        new Pair("SELECT b + 1 AS c FROM t JOIN u ON c = 1", new Pair("c is also a SELECT alias; databases differ on which it means", 36)),
        new Pair("SELECT b AS x FROM t ORDER BY x + 1", new Pair("x is also a SELECT alias; databases differ on which it means", 31)),
        new Pair(
          "SELECT b AS \"A\" FROM t ORDER BY a",
          new Pair("a matches a SELECT alias only without regard to case; databases differ", 33),
        ),
        new Pair("SELECT b AS x, c AS x FROM t ORDER BY x", new Pair("x matches more than one SELECT alias", 39)),
        new Pair(
          "SELECT DISTINCT a FROM t ORDER BY b",
          new Pair("ORDER BY item not in the SELECT DISTINCT list; databases differ", 35),
        ),
        new Pair("SELECT a FROM t JOIN t ON t.a = 1", new Pair("t is in FROM twice; give one an alias", 22)),
        new Pair("SELECT a FROM t AS x JOIN u AS \"X\" ON TRUE", new Pair("\"X\" is in FROM twice; give one an alias", 32)),
        new Pair("SELECT a FROM s.t JOIN r.t ON TRUE", new Pair("t is in FROM twice; give one an alias", 26)),
        new Pair("SELECT a FROM t JOIN u ON v.a = t.a JOIN v ON TRUE", new Pair("ON reads v, joined after it; databases differ", 27)),
        new Pair("INSERT INTO t (a, b, \"A\") VALUES (1, 2, 3)", new Pair("column \"A\" listed twice", 22)),
        new Pair("UPDATE t SET a = 1, a = 2", new Pair("column a set twice", 21)),
        new Pair("SELECT (SELECT a FROM u) FROM t WHERE (SELECT 1 / 2 FROM u) > 0", new Pair("/ without a float operand; databases divide integers differently", 49)),
        new Pair("SELECT a FROM t WHERE 1 IN (SELECT 'x' FROM u) AND b = 1", new Pair("comparing a number with text", 29)),
      ], commonTargets());
      assert(found == "") { found }
    }

What the checks accept: grouped columns however written, aliases where
every database reads them alike, and `DISTINCT` with the items in
`ORDER BY`.

    test("common statement check passes") {
      let passes = [
        "SELECT a, count(*) FROM t GROUP BY a",
        "SELECT a + 1, b, count(*) FROM t GROUP BY 1, 2 ORDER BY 2",
        "SELECT t.a, sum(b) FROM t GROUP BY a ORDER BY t.a, 2 DESC",
        "SELECT a + 1 AS n, max(b) FROM t GROUP BY a + 1 HAVING min(b) > 0 ORDER BY n",
        "SELECT count(*) FROM t",
        "SELECT count(*) + 1 AS n FROM t HAVING count(*) > 1",
        "SELECT 1 AS one, a FROM t GROUP BY a",
        "SELECT a AS a FROM t WHERE a > 1 GROUP BY a ORDER BY a",
        "SELECT t.b AS b FROM t WHERE b > 1",
        "SELECT b AS x FROM t ORDER BY x DESC, b",
        "SELECT DISTINCT a, b + 1 AS c FROM t ORDER BY a, b + 1, c, 2",
        "SELECT DISTINCT * FROM t ORDER BY a",
        "SELECT a FROM t AS x JOIN t AS y ON x.a = y.a",
        "SELECT a FROM t JOIN u ON t.a = u.a JOIN v ON v.a = t.a AND v.b = u.b",
        "SELECT a FROM t WHERE a IN (SELECT a FROM u GROUP BY a HAVING count(*) > 1)",
        "SELECT (SELECT count(*) FROM u WHERE u.a = t.a) AS n FROM t",
        "SELECT a, (SELECT max(b) FROM u) AS m FROM t GROUP BY a",
        "SELECT sum(a) FROM t WHERE EXISTS (SELECT b FROM u WHERE u.b = 1)",
        "INSERT INTO t (a, b) SELECT a, b FROM t",
        "UPDATE t SET a = b, b = 2",
        "UPDATE t SET a = 1, b = (SELECT max(u.a) FROM u)",
      ];
      for (let text of passes) {
        let got = canon(text);
        assert(got == parsed(text, false)) { "${text}: ${got}" }
      }
    }

## Output names

A bare name alone in `ORDER BY` that PostgreSQL or MySQL would read
as another item, by the names they give items: an alias beside an
item PostgreSQL names the same, or, for MySQL, beside a column of that
name; and, for PostgreSQL, a column where an item is named after it,
in a query with joins or inside an expression, where rendering can't
qualify it.

    test("common output names in ORDER BY") {
      let both = [
        new Pair("SELECT a, b AS a FROM t ORDER BY a", new Pair(pgAmbiguous("a"), 34)),
        new Pair("SELECT b AS a, t.a FROM t ORDER BY a DESC", new Pair(pgAmbiguous("a"), 36)),
      ];
      let pgOnly = [
        new Pair("SELECT CAST(a AS TEXT), b + 0 AS a FROM t ORDER BY a", new Pair(pgAmbiguous("a"), 52)),
        new Pair("SELECT length(b), c AS length FROM t ORDER BY length", new Pair(pgAmbiguous("\"length\""), 47)),
        new Pair(
          "SELECT t.a, CAST(t.a AS TEXT) FROM t JOIN u ON t.a = u.a ORDER BY a",
          new Pair(pgItem("a"), 67),
        ),
        new Pair(
          "SELECT a FROM t WHERE EXISTS (SELECT b, CAST(b AS TEXT) FROM u ORDER BY b)",
          new Pair(pgItem("b"), 73),
        ),
      ];
      let all = new ListBuilder<Pair<String, Pair<String, Int> > >();
      for (let r of both) { all.add(r); }
      for (let r of pgOnly) { all.add(r); }
      let mysqlBoth = [
        new Pair("SELECT a, b AS a FROM t ORDER BY a", new Pair(mysqlAmbiguous("a"), 34)),
        new Pair("SELECT b AS a, t.a FROM t ORDER BY a DESC", new Pair(mysqlAmbiguous("a"), 36)),
      ];
      let found = "${mismatches(all.toList(), commonTargets())}${mismatches(all.toList(), [Dialect.postgres])}${
        mismatches(mysqlBoth, [Dialect.mysql])}";
      assert(found == "") { found }
      for (let r of pgOnly) {
        assert(narrowed(notPostgres(), r.key) == parsed(r.key, false)) { r.key }
      }
      for (let r of both) {
        assert(narrowed([Dialect.sqlite, Dialect.duckdb], r.key) == parsed(r.key, false)) { r.key }
      }
      // A qualified name, an alias of its own column, the same column
      // twice, and a column no item is named after are fine.
      let passes = [
        "SELECT t.a, CAST(t.a AS TEXT) FROM t JOIN u ON t.a = u.a ORDER BY t.a",
        "SELECT a AS a, a, t.a FROM t ORDER BY a",
        "SELECT b AS a, c + 1 AS a2 FROM t ORDER BY a",
        "SELECT a FROM t WHERE EXISTS (SELECT b, CAST(c AS TEXT) FROM u ORDER BY b)",
        "SELECT a, CAST(a AS TEXT) FROM t ORDER BY a",
      ];
      for (let text of passes) {
        let got = canon(text);
        assert(got == parsed(text, false)) { "${text}: ${got}" }
      }
    }

    let pgAmbiguous(name: String): String {
      "ORDER BY ${name} is ambiguous for postgres, which names another SELECT item ${name} too; rename the alias"
    }

    let mysqlAmbiguous(name: String): String {
      "ORDER BY ${name} is ambiguous for mysql, which names another SELECT item ${name} too; rename the alias"
    }

    let pgItem(name: String): String {
      "ORDER BY ${name} would mean a SELECT item for postgres, which names one ${name}; write the column's table"
    }

    let notPostgres(): List<Dialect> { [Dialect.sqlite, Dialect.mysql, Dialect.duckdb] }

## Targets

The checks for MySQL and MariaDB apply only when a MySQL profile is a
target. Leave both out, and they pass.

    test("common statement checks for mysql") {
      let mysqlOnly = [
        new Pair("UPDATE t SET a = b, b = a", new Pair("a was set earlier in this SET; MySQL assigns left to right", 25)),
        new Pair("UPDATE t SET a = 1, b = t.a + 1", new Pair("t.a was set earlier in this SET; MySQL assigns left to right", 25)),
        new Pair("UPDATE t SET \"A\" = 1, b = a", new Pair("a was set earlier in this SET; MySQL assigns left to right", 27)),
        new Pair(
          "UPDATE t SET a = 1, b = (SELECT max(a) FROM u)",
          new Pair("a was set earlier in this SET; MySQL assigns left to right", 37),
        ),
        new Pair(
          "DELETE FROM t WHERE a IN (SELECT a FROM t WHERE b = 1)",
          new Pair("a subquery reads t, which this DELETE changes; MySQL refuses it", 41),
        ),
        new Pair(
          "UPDATE t SET a = (SELECT max(a) FROM t)",
          new Pair("a subquery reads t, which this UPDATE changes; MySQL refuses it", 38),
        ),
        new Pair(
          "UPDATE t SET a = 1 WHERE EXISTS (SELECT 1 FROM u JOIN (SELECT b FROM t) AS v ON TRUE)",
          new Pair("a subquery reads t, which this UPDATE changes; MySQL refuses it", 70),
        ),
        new Pair(
          "INSERT INTO t (a) VALUES ((SELECT max(a) FROM t))",
          new Pair("a subquery reads t, which this INSERT changes; MySQL refuses it", 47),
        ),
        new Pair(
          "SELECT a FROM t WHERE a IN (SELECT b FROM u LIMIT 1)",
          new Pair("LIMIT in an IN subquery; MySQL refuses it", 51),
        ),
        new Pair("SELECT *, a FROM t", new Pair("* beside other items; MySQL refuses it; write t.*", 8)),
      ];
      let found = "${mismatches(mysqlOnly, commonTargets())}${mismatches(mysqlOnly, [Dialect.mysqlNoBackslashEscapes])}";
      assert(found == "") { found }
      for (let r of mysqlOnly) {
        assert(narrowed(notMysql(), r.key) == parsed(r.key, false)) { r.key }
      }
      assert(canon("SELECT a FROM t WHERE EXISTS (SELECT b FROM u LIMIT 1)") ==
        "SELECT a FROM t WHERE EXISTS (SELECT b FROM u LIMIT 1)");
      assert(canon("SELECT t.*, a FROM t") == "SELECT t.*, a FROM t");
    }

A builder's targets also decide which strings and names its lexer
takes: `\` only without MySQL's default profile, and names past
PostgreSQL's 63 bytes only without PostgreSQL.

    test("common targets") {
      let slash = "SELECT 'C:\\temp' AS p";
      let slashed = "backslash in a string for mysql; bind the value instead";
      assert(canon(slash) == at(slashed, 1, 8, slash));
      assert(narrowed([Dialect.mysql], slash) == at(slashed, 1, 8, slash));
      assert(narrowed([Dialect.postgres, Dialect.sqlite], slash) == slash);
      assert(narrowed([Dialect.mysqlNoBackslashEscapes], slash) == slash);
      let long = "SELECT ${repeated("a", 64)} FROM t";
      assert(canon(long) == at("name longer than 63 UTF-8 bytes for postgres", 1, 8, "SELECT ${repeated("a", 20)}"));
      assert(narrowed([Dialect.sqlite, Dialect.duckdb], long) == long);
      assert(narrowed([Dialect.sqlite, Dialect.mysql], "SELECT ${repeated("a", 65)} FROM t") ==
        at("name longer than 64 characters for mysql", 1, 8, "SELECT ${repeated("a", 20)}"));
      let b = new QueryBuilder(Dialect.common);
      assert(b.targets.length == 5);
      b.targets = [Dialect.duckdb];
      assert(b.targets.length == 1 && b.targets[0].name == "duckdb");
      let none = new QueryBuilder(Dialect.common);
      none.targets = [];
      none.appendSafe("SELECT 1");
      assert(built(none) == "no target databases");
      let common = new QueryBuilder(Dialect.common);
      common.targets = [Dialect.sqlite, Dialect.common];
      common.appendSafe("SELECT 1");
      assert(built(common) == "common isn't a target database");
      let pg = new QueryBuilder(Dialect.postgres);
      pg.targets = [Dialect.postgres];
      pg.appendSafe("SELECT 1");
      assert(checkTemplateProblem(pg) == "targets are only for common queries");
    }

    let checkTemplateProblem(b: QueryBuilder): String {
      let ok = do { b.build(); true } orelse false;
      if (ok) { "ok" } else { b.templateProblem ?? "fails" }
    }

## Holes

Values go where an expression or a count goes, names where a name
goes, and nested queries where a subquery goes, or a whole statement,
or the query after `INSERT`. A nested query's tokens go in as written,
so the checks see into it, and problems they find there are placed at
its hole.

    test("common statement holes") {
      let t = named("t");
      let s = named("S");
      let a = named("a");
      let b = named("Bee");
      let x = named("x");
      let nothing: String? = null;
      assert(stmt"SELECT ${a} AS ${x}, ${x}.* FROM ${s}.${t} AS ${x} JOIN u ON ${x}.${a} = u.${b}" ==
        "SELECT a AS x, x.* FROM \"S\".t AS x JOIN u ON x.a = u.\"Bee\"");
      assert(stmt"INSERT INTO ${t} (${a}, ${b}) VALUES (${1}, ${"x"}), (${2}, ${nothing})" ==
        "INSERT INTO t (a, \"Bee\") VALUES (?, ?), (?, ?)");
      assert(stmt"UPDATE ${s}.${t} SET ${a} = ${1} WHERE ${b} = ${2}" == "UPDATE \"S\".t SET a = ? WHERE \"Bee\" = ?");
      assert(stmt"DELETE FROM ${t} WHERE ${a} = ${1}" == "DELETE FROM t WHERE a = ?");
      assert(stmt"SELECT a FROM t LIMIT ${10} OFFSET ${0}" == "SELECT a FROM t LIMIT ? OFFSET ?");
      let limit = "SELECT a FROM t LIMIT ${holeMark}";
      assert(stmt"SELECT a FROM t LIMIT ${-1}" == placed(limit, "LIMIT below 0; databases differ", 23));
      assert(stmt"SELECT a FROM t LIMIT ${"5"}" == placed(limit, "text in LIMIT", 23));
      assert(stmt"SELECT a FROM t LIMIT ${1.5}" == placed(limit, "a float in LIMIT", 23));
      assert(stmt"SELECT a FROM t LIMIT ${true}" == placed(limit, "a boolean in LIMIT", 23));
      assert(stmt"SELECT a FROM t OFFSET ${nothing}" == placed("SELECT a FROM t OFFSET ${holeMark}", "NULL in OFFSET", 24));
      assert(stmt"SELECT a FROM t ORDER BY ${1}" ==
        placed("SELECT a FROM t ORDER BY ${holeMark}", "a constant in ORDER BY; databases read it differently", 26));
      assert(stmt"INSERT INTO t (${a}, a) VALUES (1, 2)" ==
        placed("INSERT INTO t (${holeMark}, a) VALUES (1, 2)", "column a listed twice", 22));
      assert(stmt"UPDATE t SET ${a} = b, b = a" ==
        placed("UPDATE t SET ${holeMark} = b, b = a", "a was set earlier in this SET; MySQL assigns left to right", 28));
      assert(stmt"SELECT ${t}.* FROM t JOIN ${t} ON TRUE" ==
        placed("SELECT ${holeMark}.* FROM t JOIN ${holeMark} ON TRUE", "t is in FROM twice; give one an alias", 27));
    }

    test("common nested queries") {
      let inner = sql"SELECT b FROM u WHERE c = ${2}";
      let del = sql"DELETE FROM u WHERE c = ${3}";
      assert(stmt"INSERT INTO t (a) ${inner}" == "INSERT INTO t (a) SELECT b FROM u WHERE c = ?");
      assert(stmt"SELECT a FROM (${inner}) AS x WHERE a IN (${inner}) AND EXISTS (${inner})" ==
        "SELECT a FROM (SELECT b FROM u WHERE c = ?) AS x WHERE a IN (SELECT b FROM u WHERE c = ?) AND EXISTS (SELECT b FROM u WHERE c = ?)");
      assert(stmt"${del}" == "DELETE FROM u WHERE c = ?");
      let q = sql"SELECT a FROM t WHERE a = ${1} AND b IN (${inner}) AND d = ${4}";
      assert(render(q, Dialect.common, PlaceholderStyle.dollarNumbered) ==
        "SELECT a FROM t WHERE a = $1 AND b IN (SELECT b FROM u WHERE c = $2) AND d = $3");
      assert(q.params.length == 3 && paramText(q.params[1]) == "int:2");
      let mark = "SELECT a FROM t WHERE a IN (${holeMark})";
      assert(stmt"SELECT a FROM t WHERE a IN (${del})" == placed(mark, "nested query isn't a SELECT", 29));
      assert(stmt"INSERT INTO t (a) ${del}" == at("nested query isn't a SELECT", 1, 19, "INSERT INTO t (a) ${holeMark}"));
      assert(stmt"INSERT INTO t (a) (${inner})" ==
        at("a query after INSERT goes without parentheses", 1, 19, "INSERT INTO t (a) (${holeMark})"));
      assert(stmt"SELECT a FROM t WHERE a IN (${inner}, 1)" ==
        placed("SELECT a FROM t WHERE a IN (${holeMark}, 1)", "nested query needs its own parentheses", 29));
      assert(stmt"SELECT a FROM t WHERE a IN (${inner} WHERE b)" ==
        placed("SELECT a FROM t WHERE a IN (${holeMark} WHERE b)", "nested query needs its own parentheses", 29));
      // Problems inside a nested query are placed at its hole.
      let limited = sql"SELECT b FROM u LIMIT 1";
      assert(stmt"SELECT a FROM t WHERE a IN (${limited}) AND b = 1" ==
        placed("SELECT a FROM t WHERE a IN (${holeMark}) AND b = 1", "LIMIT in an IN subquery; MySQL refuses it", 29));
      let pgOnly = new QueryBuilder(Dialect.common);
      pgOnly.targets = [Dialect.postgres];
      pgOnly.appendSafe("SELECT 'C:\\temp' AS p FROM u");
      let slashed = pgOnly.build() orelse panic();
      assert(stmt"SELECT a FROM t WHERE a IN (${slashed})" ==
        placed(mark, "backslash in a string for mysql; bind the value instead", 29));
      let pgOuter = new QueryBuilder(Dialect.common);
      pgOuter.targets = [Dialect.postgres, Dialect.sqlite];
      pgOuter.appendSafe("SELECT a FROM t WHERE a IN (");
      pgOuter.appendQuery(slashed);
      pgOuter.appendSafe(")");
      assert(built(pgOuter) == "SELECT a FROM t WHERE a IN (SELECT 'C:\\temp' AS p FROM u)");
      assert(stmt"SELECT a FROM ${inner}" ==
        at("nested query where a name goes", 1, 15, "SELECT a FROM ${holeMark}"));
      let spillingText: QueryPart = new QueryText("SELECT a FROM t) AND (1");
      let spilling = [spillingText];
      let spills = Query.unchecked(Dialect.common, spilling);
      assert(stmt"SELECT a FROM t WHERE a IN (${spills})" == placed(mark, "nested query doesn't parse alone", 29));
      let openText: QueryPart = new QueryText("SELECT 'x");
      let open = [openText];
      let unparsed = Query.unchecked(Dialect.common, open);
      assert(stmt"SELECT a FROM t WHERE a IN (${unparsed})" ==
        at("nested query ends inside a quote or comment", 1, 29, " FROM t WHERE a IN (${holeMark}"));
    }

## The tag

The `sql` tag parses and checks a template when it runs, keeps its
values as parameters, and renders canonically for `Dialect.common`.
`Query.unchecked` parses common parts too, without the checks, and a
query whose parts don't parse can't render.

    test("the sql tag end to end") {
      let users = named("Users");
      let id = 42;
      let q = sql"select name, nick as shown from ${users} /* who */ where id = ${id} and name like 'a%' order by name nulls last limit ${10}";
      assert(q.dialect.name == "common");
      assert(q.params.length == 2);
      assert(paramText(q.params[0]) == "int:42");
      assert(partKinds(q) == "text name text param text param");
      assert(render(q, Dialect.common, PlaceholderStyle.question) ==
        "SELECT name, nick AS shown FROM \"Users\" WHERE id = ? AND name LIKE 'a%' ORDER BY name NULLS LAST LIMIT ?");
      assert(render(q, Dialect.common, PlaceholderStyle.percentS) ==
        "SELECT name, nick AS shown FROM \"Users\" WHERE id = %s AND name LIKE 'a%%' ORDER BY name NULLS LAST LIMIT %s");
      let r = q.render(Dialect.common, PlaceholderStyle.atNamed) orelse panic();
      assert(r.sql == "SELECT name, nick AS shown FROM \"Users\" WHERE id = @p1 AND name LIKE 'a%' ORDER BY name NULLS LAST LIMIT @p2");
      assert(r.params.length == 2 && paramText(r.params[1]) == "int:10");
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT \"name\", \"nick\" AS \"shown\" FROM \"Users\" WHERE \"id\" = $1 AND \"name\" LIKE 'a%' ORDER BY \"name\" LIMIT $2");
      // Named styles look at the text written, which has no comments.
      let timed = sql"SELECT a FROM t /* at 12:30 */ WHERE b = ${1}";
      assert(render(timed, Dialect.common, PlaceholderStyle.colonNamed) == "SELECT a FROM t WHERE b = :p1");
      let quoted = sql"SELECT a FROM t WHERE b = '12:30'";
      assert(quoted.renderProblem(Dialect.common, PlaceholderStyle.colonNamed) == "text has :, which colonNamed uses");
      // A minus before a value gets a space, so -1 can't make a comment.
      assert(render(sql"SELECT -${-1} AS n", Dialect.common, PlaceholderStyle.percentS) == "SELECT - %s AS n");
      let parts = [new QueryText("delete from t where a = "), new QueryParam(new SqlInt(1.toInt64()))];
      let unchecked = Query.unchecked(Dialect.common, parts);
      assert(render(unchecked, Dialect.common, PlaceholderStyle.question) == "DELETE FROM t WHERE a = ?");
      let cutText: QueryPart = new QueryText("SELECT a FROM");
      let cut = [cutText];
      let bad = Query.unchecked(Dialect.common, cut);
      assert(render(bad, Dialect.common, PlaceholderStyle.question) == "(fails)");
      assert(bad.renderProblem(Dialect.common, PlaceholderStyle.question) ==
        "common query doesn't parse: expected a table, at line 1, column 14: SELECT a FROM");
    }

## Depth

Subqueries count toward the depth limit, so deep nesting gives a
problem, not a crash.

    test("common statement depth") {
      for (let n of [20, 1000]) {
        let text = "SELECT ${repeated("(SELECT ", n)}1${repeated(")", n)}";
        let got = canon(text);
        if (n == 20) {
          assert(got == text) { got }
        } else {
          assert(hasAt(got, String.begin, deepMessage)) { got }
        }
      }
    }

## Round trip

Random statements, written with every operand in parentheses and
keywords in mixed case, print canonically to text that parses back to
the same tree.

    let generatedSelect(r: Rng, depth: Int): String {
      let e = "(${generated(r, 2)})";
      let items = new ListBuilder<String>();
      let n = 1 + r.next(3);
      for (var i = 0; i < n; i += 1) {
        // Assignments, since Temper rejects a call in one branch of an
        // `if` or `when` whose value a `let` takes here.
        let k = r.next(5);
        var item = e;
        if (k == 0) {
          item = "t.*";
        } else if (k == 1) {
          item = "${e} AS x";
        } else if (k == 2) {
          item = "(${generated(r, 2)}) y";
        } else if (k == 3) {
          item = "\"Q\"";
        }
        items.add(item);
      }
      let out = new StringBuilder();
      out.append(pick(r, ["SELECT ", "select distinct ", "Select "]));
      out.append(items.join(", ", fn (s: String): String { s }));
      out.append(" FROM ");
      if (depth > 0 && r.next(3) == 0) {
        out.append("(${generatedSelect(r, depth - 1)}) ${pick(r, ["AS q", "q"])}");
      } else {
        out.append(pick(r, ["t", "s.t AS u", "\"T\" v"]));
      }
      let joins = r.next(3);
      for (var i = 0; i < joins; i += 1) {
        out.append(pick(r, [
          " JOIN u ON ${e}", " left outer join v ON ${e}", " CROSS JOIN w", " inner join x on ${e}", " LEFT JOIN y ON ${e}",
        ]));
      }
      if (r.next(2) == 0) {
        let sub = if (depth > 0 && r.next(2) == 0) { "a IN (${generatedSelect(r, depth - 1)}) AND " } else { "" };
        out.append(" WHERE ${sub}${e}");
      }
      if (r.next(3) == 0) {
        out.append(" GROUP BY ${e}, b");
        if (r.next(2) == 0) { out.append(" HAVING ${e}"); }
      }
      if (r.next(2) == 0) {
        out.append(" ORDER BY ${e}${pick(r, ["", " ASC", " desc", " NULLS FIRST", " nulls last", " DESC NULLS FIRST"])}, 1");
      }
      if (r.next(3) == 0) { out.append(" LIMIT 5"); }
      if (r.next(3) == 0) { out.append(" OFFSET 010"); }
      out.toString()
    }

    let generatedStatement(r: Rng): String {
      let e = "(${generated(r, 2)})";
      when (r.next(4)) {
        0 -> generatedSelect(r, 2);
        1 -> if (r.next(2) == 0) {
          "INSERT INTO t (a, \"B\") VALUES (${e}, ${e}), (1, NULL)"
        } else {
          "insert into s.t (a) ${generatedSelect(r, 1)}"
        };
        2 -> "UPDATE t SET a = ${e}, \"B\" = ${e}${pick(r, ["", " WHERE a = 1"])}";
        else -> "delete from t${pick(r, ["", " where ${e}"])}";
      }
    }

    test("common statement round trip") {
      let r = new Rng();
      for (var i = 0; i < 60; i += 1) {
        let text = generatedStatement(r);
        let shape = parsed(text, true);
        let canonical = parsed(text, false);
        assert(parsed(canonical, false) == canonical) { "${text}: ${canonical}" }
        assert(parsed(canonical, true) == shape) { "${text}: ${shape}" }
      }
    }
