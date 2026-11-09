# Common Rendering Tests

Common queries rendered for each database: every construct, and every
row of the rendering table, golden for each; the casts PostgreSQL gets;
targets, and the checks they relax; the lexer each rendering passes;
and random statements rendered for every database.

## Test helpers

`ruled` builds a common query from text for targets, or null, and
`renderedEach` renders it for each database, with `?` for values, as
`name: sql` lines, or the problem.

    let ruled(targets: List<Dialect>, text: String): Query? {
      let b = new QueryBuilder(Dialect.common);
      b.targets = targets;
      b.appendSafe(text);
      b.build() orelse null
    }

    let checkedQuery(targets: List<Dialect>, text: String): Query {
      let b = new QueryBuilder(Dialect.common);
      b.targets = targets;
      b.appendSafe(text);
      b.build() orelse panic()
    }

`textPart` and `intPart` make parts, typed as parts for list literals.

    let textPart(text: String): QueryPart { new QueryText(text) }
    let intPart(n: Int): QueryPart { new QueryParam(new SqlInt(n.toInt64())) }

    let databases(): List<Dialect> { [Dialect.sqlite, Dialect.postgres, Dialect.mysql, Dialect.duckdb] }

`quotedAs` writes expected SQL for a dialect from text with names in
backticks, which are double quotes but for MySQL.

    let quotedAs(d: Dialect, expected: String): String {
      if (lexingName(d) == "mysql") { expected } else { replaceCodePoint(expected, char'`', "\"") }
    }

`renderMismatches` builds each case for every target, and checks its
rendering for SQLite, PostgreSQL, MySQL, and DuckDB, in that order
after the text (empty for the same as SQLite's), and that both MySQL
profiles render alike. It lists those that differ.

    let renderMismatches(cases: List<List<String>>): String {
      let out = new StringBuilder();
      let ds = databases();
      for (let c of cases) {
        let q = ruled(commonTargets(), c[0]);
        if (q == null) {
          out.append("${c[0]}: ${canon(c[0])} | ");
        } else {
          for (var i = 0; i < ds.length; i += 1) {
            let d = ds[i];
            let want = quotedAs(d, if (c[i + 1].isEmpty) { c[1] } else { c[i + 1] });
            let got = render(q, d, PlaceholderStyle.question);
            if (got != want) { out.append("${c[0]} for ${d.name}: ${got} | "); }
          }
          let other = render(q, Dialect.mysqlNoBackslashEscapes, PlaceholderStyle.question);
          if (other != render(q, Dialect.mysql, PlaceholderStyle.question)) {
            out.append("${c[0]} for mysqlNoBackslashEscapes: ${other} | ");
          }
        }
      }
      out.toString()
    }

## Constructs

Each construct, for each database: every name quoted, parentheses
around every operand that's an operator expression but for `AND` and
`OR`, and the same text where the databases agree.

    test("common rendering of each construct") {
      let found = renderMismatches([
        ["SELECT a, \"Mixed\", t.b FROM s.t", "SELECT `a`, `Mixed`, `t`.`b` FROM `s`.`t`", "", "", ""],
        ["SELECT x.a AS b FROM t x", "SELECT `x`.`a` AS `b` FROM `t` AS `x`", "", "", ""],
        ["SELECT DISTINCT * FROM t", "SELECT DISTINCT * FROM `t`", "", "", ""],
        ["SELECT t.* FROM t", "SELECT `t`.* FROM `t`", "", "", ""],
        ["SELECT 1, 1.50, 'it''s', NULL", "SELECT 1, 1.50, 'it''s', NULL", "", "", ""],
        ["SELECT TRUE, FALSE", "SELECT TRUE, FALSE", "", "", ""],
        [
          "SELECT (a + b) * c, a - -1, -(-a), a * b % 3 FROM t",
          "SELECT (`a` + `b`) * `c`, `a` - (-1), -(-`a`), (`a` * `b`) % 3 FROM `t`", "", "", "",
        ],
        [
          "SELECT a FROM t WHERE a = 1 OR b <> 2 AND NOT c != 3",
          "SELECT `a` FROM `t` WHERE `a` = 1 OR (`b` <> 2 AND NOT (`c` <> 3))", "", "", "",
        ],
        [
          "SELECT a FROM t WHERE (a OR b) AND c IS NOT NULL AND d + 1 IS NULL",
          "SELECT `a` FROM `t` WHERE (`a` OR `b`) AND `c` IS NOT NULL AND (`d` + 1) IS NULL", "", "", "",
        ],
        [
          "SELECT a FROM t WHERE a IN (1, 2 + 3) AND b NOT BETWEEN c - 1 AND 4",
          "SELECT `a` FROM `t` WHERE `a` IN (1, 2 + 3) AND `b` NOT BETWEEN (`c` - 1) AND 4", "", "", "",
        ],
        [
          "SELECT a FROM t WHERE a LIKE 'x!%' ESCAPE '!' AND b NOT LIKE 'ab%'",
          "SELECT `a` FROM `t` WHERE `a` LIKE 'x!%' ESCAPE '!' AND `b` NOT LIKE 'ab%'", "", "", "",
        ],
        [
          "SELECT a FROM t WHERE a IN (SELECT b FROM u) AND EXISTS (SELECT 1 FROM v WHERE v.a = t.a)",
          "SELECT `a` FROM `t` WHERE `a` IN (SELECT `b` FROM `u`) AND EXISTS (SELECT 1 FROM `v` WHERE `v`.`a` = `t`.`a`)",
          "", "", "",
        ],
        [
          "SELECT (SELECT max(b) FROM u) AS m FROM (SELECT b FROM t) x",
          "SELECT (SELECT MAX(`b`) FROM `u`) AS `m` FROM (SELECT `b` FROM `t`) AS `x`", "", "", "",
        ],
        [
          "SELECT CASE a WHEN 1 THEN 'one' ELSE 'other' END, CASE WHEN a > 1 THEN b END FROM t",
          "SELECT CASE `a` WHEN 1 THEN 'one' ELSE 'other' END, CASE WHEN `a` > 1 THEN `b` END FROM `t`", "", "", "",
        ],
        [
          "SELECT coalesce(a, b), nullif(a, 1), abs(a), lower(b), upper(b), trim(b), replace(b, 'x', 'y'), substr(b, 2, 3) FROM t",
          "SELECT COALESCE(`a`, `b`), NULLIF(`a`, 1), ABS(`a`), LOWER(`b`), UPPER(`b`), TRIM(`b`), REPLACE(`b`, 'x', 'y'), SUBSTR(`b`, 2, 3) FROM `t`",
          "", "", "",
        ],
        [
          "SELECT count(*), count(DISTINCT a), sum(a), avg(a), min(a), max(a) FROM t",
          "SELECT COUNT(*), COUNT(DISTINCT `a`), SUM(`a`), AVG(`a`), MIN(`a`), MAX(`a`) FROM `t`", "", "", "",
        ],
        [
          "SELECT a, count(*) FROM t GROUP BY a HAVING count(*) > 1",
          "SELECT `a`, COUNT(*) FROM `t` GROUP BY `a` HAVING COUNT(*) > 1", "", "", "",
        ],
        [
          "SELECT t.a FROM t INNER JOIN u ON t.id = u.id LEFT OUTER JOIN v ON v.id = u.id CROSS JOIN w",
          "SELECT `t`.`a` FROM `t` JOIN `u` ON `t`.`id` = `u`.`id` LEFT JOIN `v` ON `v`.`id` = `u`.`id` CROSS JOIN `w`",
          "", "", "",
        ],
        ["SELECT a / 2.0, 7.5 / a FROM t", "SELECT `a` / 2.0, 7.5 / `a` FROM `t`", "", "", ""],
        ["INSERT INTO t (a, b) VALUES (1, 'x'), (2, NULL)", "INSERT INTO `t` (`a`, `b`) VALUES (1, 'x'), (2, NULL)", "", "", ""],
        ["INSERT INTO s.t (a) SELECT b FROM u", "INSERT INTO `s`.`t` (`a`) SELECT `b` FROM `u`", "", "", ""],
        ["UPDATE t SET a = a + 1, b = 'x' WHERE c = 2", "UPDATE `t` SET `a` = `a` + 1, `b` = 'x' WHERE `c` = 2", "", "", ""],
        ["DELETE FROM s.t WHERE a = 1", "DELETE FROM `s`.`t` WHERE `a` = 1", "", "", ""],
      ]);
      assert(found == "") { found }
    }

## The rendering table

The rows where databases differ: `||`, `OFFSET` alone, `NULLS` (and
the unwritten order), casts, and `LENGTH`.

    test("common rendering where databases differ") {
      let found = renderMismatches([
        [
          "SELECT a || 'x' || b, 1 || 2 FROM t",
          "SELECT `a` || 'x' || `b`, 1 || 2 FROM `t`",
          "SELECT `a` || 'x' || `b`, CAST(1 AS TEXT) || 2 FROM `t`",
          "SELECT CONCAT(`a`, 'x', `b`), CONCAT(1, 2) FROM `t`",
          "",
        ],
        [
          "SELECT a || b, (a + 1) || 'x' FROM t",
          "SELECT `a` || `b`, (`a` + 1) || 'x' FROM `t`",
          "SELECT CAST(`a` AS TEXT) || `b`, (`a` + 1) || 'x' FROM `t`",
          "SELECT CONCAT(`a`, `b`), CONCAT(`a` + 1, 'x') FROM `t`",
          "",
        ],
        ["SELECT a FROM t LIMIT 5 OFFSET 2", "SELECT `a` FROM `t` LIMIT 5 OFFSET 2", "", "", ""],
        ["SELECT a FROM t LIMIT 5", "SELECT `a` FROM `t` LIMIT 5", "", "", ""],
        [
          "SELECT a FROM t OFFSET 2",
          "SELECT `a` FROM `t` LIMIT -1 OFFSET 2",
          "SELECT `a` FROM `t` OFFSET 2",
          "SELECT `a` FROM `t` LIMIT 18446744073709551615 OFFSET 2",
          "SELECT `a` FROM `t` OFFSET 2",
        ],
        [
          "SELECT a FROM t ORDER BY a, b DESC",
          "SELECT `a` FROM `t` ORDER BY `a`, `b` DESC",
          "SELECT `a` FROM `t` ORDER BY `a` NULLS FIRST, `b` DESC NULLS LAST",
          "",
          "SELECT `a` FROM `t` ORDER BY `a` NULLS FIRST, `b` DESC NULLS LAST",
        ],
        [
          "SELECT a FROM t ORDER BY a NULLS LAST, b DESC NULLS FIRST",
          "SELECT `a` FROM `t` ORDER BY `a` NULLS LAST, `b` DESC NULLS FIRST",
          "SELECT `a` FROM `t` ORDER BY `a`, `b` DESC",
          "SELECT `a` FROM `t` ORDER BY `a` IS NULL, `a`, `b` IS NULL DESC, `b` DESC",
          "SELECT `a` FROM `t` ORDER BY `a` NULLS LAST, `b` DESC NULLS FIRST",
        ],
        [
          "SELECT a + 1 AS n, b FROM t ORDER BY n NULLS LAST, 2 DESC NULLS FIRST, a - 1 NULLS LAST",
          "SELECT `a` + 1 AS `n`, `b` FROM `t` ORDER BY `n` NULLS LAST, 2 DESC NULLS FIRST, `a` - 1 NULLS LAST",
          "SELECT `a` + 1 AS `n`, `b` FROM `t` ORDER BY `n`, 2 DESC, `a` - 1",
          "SELECT `a` + 1 AS `n`, `b` FROM `t` ORDER BY (`a` + 1) IS NULL, `n`, `b` IS NULL DESC, 2 DESC, (`a` - 1) IS NULL, `a` - 1",
          "SELECT `a` + 1 AS `n`, `b` FROM `t` ORDER BY `n` NULLS LAST, 2 DESC NULLS FIRST, `a` - 1 NULLS LAST",
        ],
        [
          "SELECT CAST(a AS INTEGER), CAST(a AS DOUBLE), CAST(a AS TEXT) FROM t",
          "SELECT CAST(`a` AS INTEGER), CAST(`a` AS REAL), CAST(`a` AS TEXT) FROM `t`",
          "SELECT CAST(`a` AS BIGINT), CAST(`a` AS DOUBLE PRECISION), CAST(`a` AS TEXT) FROM `t`",
          "SELECT CAST(`a` AS SIGNED), CAST(`a` AS DOUBLE), CAST(`a` AS CHAR) FROM `t`",
          "SELECT CAST(`a` AS BIGINT), CAST(`a` AS DOUBLE), CAST(`a` AS VARCHAR) FROM `t`",
        ],
        [
          "SELECT length(a) FROM t",
          "SELECT LENGTH(`a`) FROM `t`",
          "",
          "SELECT CHAR_LENGTH(`a`) FROM `t`",
          "",
        ],
      ]);
      assert(found == "") { found }
      // MySQL can't sort by IS NULL of a * column's place.
      let star = checkedQuery(commonTargets(), "SELECT * FROM t ORDER BY 1 NULLS LAST");
      assert(render(star, Dialect.sqlite, PlaceholderStyle.question) == "SELECT * FROM \"t\" ORDER BY 1 NULLS LAST");
      assert(star.renderProblem(Dialect.mysql, PlaceholderStyle.question) ==
        "NULLS FIRST or LAST on the place of a * in ORDER BY, for mysql");
    }

## Values

Values stay parameters, numbered as rendered: MySQL's `IS NULL`
repeats the values of what it sorts by. PostgreSQL casts a value where
nothing else gives it a type: alone in the `SELECT` list, among `CASE`
results or `COALESCE` arguments that are all values, strings, or
`NULL`, and in `||`.

    test("common rendering of values") {
      let nothing: String? = null;
      let alone = sql"SELECT ${"x"} AS a, ${1} AS b, ${1.5} AS c, ${true} AS d, ${nothing} AS e";
      assert(render(alone, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT CAST($1 AS TEXT) AS \"a\", CAST($2 AS BIGINT) AS \"b\", CAST($3 AS DOUBLE PRECISION) AS \"c\", CAST($4 AS BOOLEAN) AS \"d\", CAST($5 AS TEXT) AS \"e\"");
      assert(render(alone, Dialect.duckdb, PlaceholderStyle.dollarNumbered) ==
        "SELECT $1 AS \"a\", $2 AS \"b\", $3 AS \"c\", $4 AS \"d\", $5 AS \"e\"");
      let grouped = sql"SELECT coalesce(${nothing}, ${2}) AS n, coalesce(a, ${3}) AS m, nullif(${"a"}, 'b') AS o, CASE WHEN a > 0 THEN ${4} ELSE NULL END AS p, CASE WHEN a > 0 THEN a ELSE ${5} END AS q FROM t";
      assert(render(grouped, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT COALESCE(CAST($1 AS BIGINT), CAST($2 AS BIGINT)) AS \"n\", COALESCE(\"a\", $3) AS \"m\", NULLIF(CAST($4 AS TEXT), 'b') AS \"o\", CASE WHEN \"a\" > 0 THEN CAST($5 AS BIGINT) ELSE NULL END AS \"p\", CASE WHEN \"a\" > 0 THEN \"a\" ELSE $6 END AS \"q\" FROM \"t\"");
      assert(render(grouped, Dialect.sqlite, PlaceholderStyle.question) ==
        "SELECT COALESCE(?, ?) AS \"n\", COALESCE(\"a\", ?) AS \"m\", NULLIF(?, 'b') AS \"o\", CASE WHEN \"a\" > 0 THEN ? ELSE NULL END AS \"p\", CASE WHEN \"a\" > 0 THEN \"a\" ELSE ? END AS \"q\" FROM \"t\"");
      let joined = sql"SELECT a || ${"x"} AS s, ${"y"} || ${"z"} AS u FROM t WHERE b = ${1}";
      assert(render(joined, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT \"a\" || CAST($1 AS TEXT) AS \"s\", CAST($2 AS TEXT) || CAST($3 AS TEXT) AS \"u\" FROM \"t\" WHERE \"b\" = $4");
      assert(render(joined, Dialect.mysql, PlaceholderStyle.percentS) ==
        "SELECT CONCAT(`a`, %s) AS `s`, CONCAT(%s, %s) AS `u` FROM `t` WHERE `b` = %s");
      let sorted = sql"SELECT a + ${1} AS n FROM t ORDER BY n NULLS LAST LIMIT ${2} OFFSET ${3}";
      let r = sorted.render(Dialect.mysql, PlaceholderStyle.question) orelse panic();
      assert(r.sql == "SELECT `a` + ? AS `n` FROM `t` ORDER BY (`a` + ?) IS NULL, `n` LIMIT ? OFFSET ?");
      assert(r.params.length == 4 && paramText(r.params[1]) == "int:1" && paramText(r.params[3]) == "int:3");
      assert(sorted.params.length == 3);
      let offset = sql"SELECT a FROM t OFFSET ${3}";
      assert(render(offset, Dialect.sqlite, PlaceholderStyle.colonNamed) == "SELECT \"a\" FROM \"t\" LIMIT -1 OFFSET :p1");
      // A minus before a negative value gets its space.
      assert(render(sql"SELECT -${-1} AS n", Dialect.mysql, PlaceholderStyle.percentS) == "SELECT - %s AS `n`");
      // Names from holes are quoted the database's way.
      let t = named("My Table");
      assert(render(sql"SELECT a FROM ${t}", Dialect.mysql, PlaceholderStyle.question) == "SELECT `a` FROM `My Table`");
    }

## Strings

Each profile quotes strings its own way: `mysqlNoBackslashEscapes`
writes a backslash plainly, which a query can hold only without the
default `mysql` profile among its targets.

    test("common rendering of strings") {
      let q = checkedQuery([Dialect.mysqlNoBackslashEscapes, Dialect.postgres], "SELECT 'C:\\temp' AS p");
      assert(render(q, Dialect.mysqlNoBackslashEscapes, PlaceholderStyle.question) == "SELECT 'C:\\temp' AS `p`");
      assert(render(q, Dialect.postgres, PlaceholderStyle.question) == "SELECT 'C:\\temp' AS \"p\"");
      assert(q.renderProblem(Dialect.mysql, PlaceholderStyle.question) ==
        "common query checked for mysqlNoBackslashEscapes, postgres, not mysql");
      // The MySQL lexer refuses a backslash before a closing quote,
      // which the two modes read differently, even in a rendering.
      let ending = checkedQuery([Dialect.mysqlNoBackslashEscapes], "SELECT 'a\\' AS p");
      assert(ending.renderProblem(Dialect.mysqlNoBackslashEscapes, PlaceholderStyle.question) ==
        "common query rendered for mysqlNoBackslashEscapes fails its lexer: backslash before a quote or backslash in a string");
    }

## Targets

A common query records its targets and renders only for them, and for
`Dialect.common`; `unchecked` takes targets too, every database by
default.

    test("common rendering only for targets") {
      let q = checkedQuery([Dialect.postgres, Dialect.sqlite], "SELECT a FROM t");
      assert(dialectNames(q.targets) == "postgres, sqlite");
      assert(render(q, Dialect.sqlite, PlaceholderStyle.question) == "SELECT \"a\" FROM \"t\"");
      assert(render(q, Dialect.common, PlaceholderStyle.question) == "SELECT a FROM t");
      for (let d of [Dialect.mysql, Dialect.mysqlNoBackslashEscapes, Dialect.duckdb]) {
        assert(q.renderProblem(d, PlaceholderStyle.question) == "common query checked for postgres, sqlite, not ${d.name}");
      }
      assert(dialectNames(sql"SELECT 1".targets) == dialectNames(commonTargets()));
      let parts = [textPart("SELECT a FROM t")];
      assert(Query.unchecked(Dialect.common, parts).targets.length == 5);
      let duck = Query.unchecked(Dialect.common, parts, [Dialect.duckdb]);
      assert(render(duck, Dialect.duckdb, PlaceholderStyle.question) == "SELECT \"a\" FROM \"t\"");
      assert(render(duck, Dialect.sqlite, PlaceholderStyle.question) == "(fails)");
      assert(dialectNames(sqlite"SELECT 1".targets) == "sqlite");
      // A name past PostgreSQL's limit renders where it was allowed,
      // and an unchecked query refuses it at render time.
      let long = "SELECT ${repeated("a", 64)} FROM t";
      let wide = checkedQuery([Dialect.sqlite], long);
      assert(render(wide, Dialect.sqlite, PlaceholderStyle.question) == "SELECT \"${repeated("a", 64)}\" FROM \"t\"");
      let loose = Query.unchecked(Dialect.common, [textPart(long)]);
      assert(loose.renderProblem(Dialect.postgres, PlaceholderStyle.question) == "name longer than 63 UTF-8 bytes for postgres");
    }

Narrower targets relax the checks there because databases differ, when
the targets left read the construct alike; the traps apply to every
target.

    test("narrower targets relax expression checks") {
      let relaxed = [
        new Pair("SELECT a / 2 FROM t", [Dialect.sqlite, Dialect.postgres]),
        new Pair("SELECT 'a' || TRUE", [Dialect.sqlite, Dialect.mysql]),
        new Pair("SELECT a FROM t WHERE a LIKE b", [Dialect.sqlite, Dialect.duckdb, Dialect.mysqlNoBackslashEscapes]),
        new Pair("SELECT a FROM t WHERE a LIKE 'a\\%'", [Dialect.sqlite, Dialect.duckdb, Dialect.mysqlNoBackslashEscapes]),
        new Pair("SELECT substr(a, 0) FROM t", [Dialect.sqlite, Dialect.duckdb]),
        new Pair("SELECT 'a' + 1", [Dialect.postgres]),
        new Pair("SELECT CAST(1.5 AS INTEGER)", [Dialect.mysql, Dialect.mysqlNoBackslashEscapes]),
        new Pair("SELECT a FROM t WHERE 1", [Dialect.sqlite]),
      ];
      for (let r of relaxed) {
        assert(ruled(r.value, r.key) != null) { r.key }
        assert(ruled(commonTargets(), r.key) == null) { r.key }
      }
      let still = [
        new Pair("SELECT a / 2 FROM t", [Dialect.sqlite, Dialect.duckdb]),
        new Pair("SELECT a FROM t WHERE a LIKE b", [Dialect.sqlite, Dialect.postgres]),
        new Pair("SELECT a FROM t WHERE a LIKE 'a\\%'", [Dialect.sqlite, Dialect.postgres]),
        new Pair("SELECT a FROM t WHERE a LIKE b", [Dialect.mysql, Dialect.mysqlNoBackslashEscapes]),
        new Pair("SELECT a FROM t WHERE a = NULL", [Dialect.postgres]),
        new Pair("SELECT a FROM t WHERE a LIKE 'a!' ESCAPE '!'", [Dialect.sqlite]),
        new Pair("SELECT sum(max(a)) FROM t", [Dialect.duckdb]),
      ];
      for (let r of still) {
        assert(ruled(r.value, r.key) == null) { r.key }
      }
      assert(canon("SELECT a FROM t WHERE a LIKE 'a\\%'") ==
        placed("SELECT a FROM t WHERE a LIKE 'a\\%'", "backslash in a string for mysql; bind the value instead", 30));
      assert(narrowed([Dialect.sqlite, Dialect.postgres], "SELECT a FROM t WHERE a LIKE 'a\\%'") ==
        placed("SELECT a FROM t WHERE a LIKE 'a\\%'", "\\ in a LIKE pattern without ESCAPE; databases differ", 30));
    }

## The lexer oracle

A rendering goes through its database's own lexer, which would catch a
value in a quote or comment.

    test("rendered SQL passes each database's lexer") {
      assert(lexingProblem(Dialect.sqlite, [textPart("SELECT a FROM t")]) == null);
      let open = [textPart("SELECT '"), intPart(1), textPart("'")];
      assert(lexingProblem(Dialect.postgres, open) ==
        "common query rendered for postgres fails its lexer: hole inside a quote or comment");
      let comment = [textPart("SELECT 1 # "), intPart(1)];
      assert(lexingProblem(Dialect.mysql, comment) ==
        "common query rendered for mysql fails its lexer: hole inside a quote or comment");
    }

## Round trip

Random statements, parsed without the checks, render for every
database, each passing that database's lexer, and render the same for
both MySQL profiles.

    test("common rendering round trip") {
      let r = new Rng();
      for (var i = 0; i < 60; i += 1) {
        let text = generatedStatement(r);
        let q = Query.unchecked(Dialect.common, [textPart(text)]);
        for (let d of databases()) {
          let problem = q.renderProblem(d, PlaceholderStyle.question);
          assert(problem == null) { "${text} for ${d.name}: ${problem ?? ""}" }
        }
        assert(render(q, Dialect.mysql, PlaceholderStyle.question) ==
          render(q, Dialect.mysqlNoBackslashEscapes, PlaceholderStyle.question)) { text }
      }
    }
