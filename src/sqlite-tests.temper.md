# SQLite Tests

Values become parameters, never SQL text.

    test("values become parameters") {
      let name = "Robert'); DROP TABLE students; --";
      let q = sqlite"SELECT id FROM students WHERE name = ${name} AND age > ${7}";
      assert(q.sql == "SELECT id FROM students WHERE name = ? AND age > ?");
      assert(q.params.length == 2);
      assert(paramText(q.params[0]) == "text:${name}");
      assert(paramText(q.params[1]) == "int:7");
    }

Identifiers go in quoted, as SQL text.

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

A query in a hole goes in as SQL, with its parameters in place.

    test("queries nest") {
      let where = sqlite"WHERE a = ${1} AND b IS ${null}";
      let q = sqlite"SELECT * FROM t ${where} LIMIT ${10}";
      assert(q.sql == "SELECT * FROM t WHERE a = ? AND b IS ? LIMIT ?");
      assert(q.params.length == 3);
      assert(paramText(q.params[1]) == "null");
      assert(paramText(q.params[2]) == "int:10");
    }

Template mistakes are caught, whether they'd misplace a parameter or
leave a quote or comment open.

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
