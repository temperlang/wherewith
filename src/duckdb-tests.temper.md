# DuckDB Tests

DuckDB quotes as PostgreSQL does, with no limit on names, and like
PostgreSQL can't take NUL in a string.

    test("duckdb quoting") {
      let d = Dialect.duckdb;
      assert(nam(d, "a\"b") == "\"a\"\"b\"");
      assert(nam(d, "a`b") == "\"a`b\"");
      assert(nam(d, "t${u(0x1F600)} ") == "\"t${u(0x1F600)} \"");
      let x64 = repeated("x", 64);
      assert(nam(d, x64) == "\"${x64}\"");
      assert(nam(d, "") == "(fails)");
      assert(str(d, "it's \\") == "'it''s \\'");
      assert(str(d, "a${u(0x0)}b") == "(fails)");
      assert(str(d, "a${u(0xA0)}b") == "'a${u(0xA0)}b'");
    }

    test("duckdb queries") {
      let col = Identifier.named("name") orelse panic();
      let q = duckdb"SELECT ${col}, tags[1:${2}], {'a': ${3}} FROM t WHERE x = ${"it's"}";
      assert(render(q, Dialect.duckdb, PlaceholderStyle.dollarNumbered) ==
        "SELECT \"name\", tags[1: $1], {'a': $2 } FROM t WHERE x = $3");
      assert(render(q, Dialect.duckdb, PlaceholderStyle.question) ==
        "SELECT \"name\", tags[1: ?], {'a': ? } FROM t WHERE x = ?");
      assert(paramText(q.params[2]) == "text:it's");
    }

Template mistakes, with DuckDB's quotes and comments: PostgreSQL's,
plus backtick names and the Unicode space pass.

    test("duckdb template mistakes") {
      let check(build: fn (QueryBuilder): Void): String { checkTemplate(Dialect.duckdb, build) }
      let inQuote = "hole inside a quote or comment";
      let unterminated = "template ends inside a quote or comment";
      let stray = "parameter in template text";
      let outOfStep = "quote or comment DuckDB's Unicode space pass misreads";
      let changed = "Unicode space DuckDB would change inside a quote";
      assert(check { b => b.appendSafe("SELECT 1"); } == "ok");
      assert(check { b => b.appendSafe("SELECT '"); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 1 -- c\r, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT /* /* */ "); b.appendInt(1); b.appendSafe(" */"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT /* /* */ */ "); b.appendInt(1); } == "ok");
      // E strings, and their continuation past a line break.
      assert(check { b => b.appendSafe("SELECT E'a\\' , "); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 'a\\', "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT E'a'\n'\\\\', "); b.appendInt(1); } == "ok");
      // Backtick names.
      assert(check { b => b.appendSafe("SELECT 1 AS `"); b.appendInt(1); b.appendSafe("`"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 1 AS `a``?`, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 AS `a"); } == unterminated);
      // Dollar quotes and placeholders.
      assert(check { b => b.appendSafe("SELECT $$ it's ? $$, $t$ $1 $t$, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT ?1"); } == stray);
      assert(check { b => b.appendSafe("SELECT $name"); } == stray);
      assert(check { b => b.appendSafe("SELECT a$b"); } == stray);
      assert(check { b => b.appendSafe("SELECT {'a': 1}, [1, 2][1:2], lambda x: x, 4 @ 2, 5 % 2"); } == "ok");
      // Quotes the Unicode space pass misreads, which put it out of
      // step: in a block comment, a backtick name, or an E string.
      assert(check { b => b.appendSafe("SELECT 1 /* it's */"); } == outOfStep);
      assert(check { b => b.appendSafe("SELECT 1 /* it''s \"a\" */, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 /* -- */"); } == outOfStep);
      assert(check { b => b.appendSafe("SELECT 1 /* a$b$ */"); } == outOfStep);
      assert(check { b => b.appendSafe("SELECT 1 /* $1$ */, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 AS `it's`"); } == outOfStep);
      assert(check { b => b.appendSafe("SELECT E'it\\'s'"); } == outOfStep);
      assert(check { b => b.appendSafe("SELECT E'a\\\\'"); } == "ok");
      assert(check { b => b.appendSafe("SELECT E'a'\n'\\'b'"); } == outOfStep);
      // The pass ends a dollar quote at a tag sharing the opening
      // tag's last `$`, and reads a closing tag's last `$` again.
      assert(check { b => b.appendSafe("SELECT $$$$"); } == outOfStep);
      assert(check { b => b.appendSafe("SELECT $a$$a$, $$x$$"); } == "ok");
      // Unicode spaces: whitespace in code, and kept in quotes the pass
      // knows, but changed in a backtick name.
      let nbsp = u(0xA0);
      let bom = u(0xFEFF);
      assert(check { b => b.appendSafe("SELECT${nbsp}1,${bom}'a${nbsp}', \"b${nbsp}\", $$c${nbsp}$$, "); b.appendInt(1); } ==
        "ok");
      assert(check { b => b.appendSafe("SELECT 1 /* a${nbsp} */ -- b${nbsp}\n, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 AS `a${nbsp}b`"); } == changed);
      assert(check { b => b.appendSafe("SELECT E'a\\'${nbsp}'"); } == changed);
      // After a Unicode space, `E'` starts an E string, and a line
      // break after one goes on into another string.
      assert(check { b => b.appendSafe("SELECT${nbsp}E'\\', "); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT E'a'${nbsp}\n'\\', "); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      // U+2028 isn't one of DuckDB's spaces, so it's part of a word.
      assert(check { b => b.appendSafe("SELECT x${u(0x2028)}E'\\', "); b.appendInt(1); } == "ok");
      // The pass's place carries across holes.
      assert(check { b => b.appendSafe("SELECT "); b.appendInt(1); b.appendSafe(" /* ' */"); } == outOfStep);
    }
