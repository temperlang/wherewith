# MySQL and MariaDB Tests

Only the default MySQL profile escapes backslashes. Elsewhere they're
plain characters, so a trailing `\` can't escape the closing quote.

    test("backslashes per dialect") {
      let input = "\\'; DROP TABLE t; -- \\";
      assert(str(Dialect.sqlite, input) == "'\\''; DROP TABLE t; -- \\'");
      assert(str(Dialect.postgres, input) == "'\\''; DROP TABLE t; -- \\'");
      assert(str(Dialect.mysqlNoBackslashEscapes, input) == "'\\''; DROP TABLE t; -- \\'");
      assert(str(Dialect.mysql, input) == "'\\\\''; DROP TABLE t; -- \\\\'");
      assert(str(Dialect.mysql, "\\") == "'\\\\'");
      assert(str(Dialect.mysql, "a${u(0x1A)}b") == "'a\\Zb'");
      assert(str(Dialect.sqlite, "a${u(0x1A)}b") == "'a${u(0x1A)}b'");
    }

A NUL can only be written where backslash escapes are read.

    test("NUL in strings") {
      assert(str(Dialect.sqlite, "a${u(0x0)}b") == "(fails)");
      assert(str(Dialect.postgres, "a${u(0x0)}b") == "(fails)");
      assert(str(Dialect.mysqlNoBackslashEscapes, "a${u(0x0)}b") == "(fails)");
      assert(str(Dialect.mysql, "a${u(0x0)}b") == "'a\\0b'");
      assert(Dialect.sqlite.stringProblem(u(0x0)) == "NUL in string");
      assert(Dialect.mysql.stringProblem(u(0x0)) == null);
    }

MySQL and MariaDB reject names above U+FFFF and names ending in any
whitespace, and MariaDB reads table names starting with `#mysql50#` as
file names.

    test("MySQL-only name rules") {
      assert(nam(Dialect.mysql, "t${u(0x1F600)}") == "(fails)");
      assert(nam(Dialect.sqlite, "t${u(0x1F600)}") == "\"t${u(0x1F600)}\"");
      assert(nam(Dialect.postgres, "t${u(0x1F600)}") == "\"t${u(0x1F600)}\"");
      assert(nam(Dialect.mysql, "t ") == "(fails)");
      assert(nam(Dialect.mysql, " t") == "` t`");
      assert(nam(Dialect.sqlite, "t ") == "\"t \"");
      assert(Dialect.mysql.nameProblem("t ") == "name ends in whitespace");
      for (let c of [0x09, 0x0A, 0x0B, 0x0C, 0x0D]) {
        assert(nam(Dialect.mysql, "t${u(c)}") == "(fails)");
        assert(nam(Dialect.mysqlNoBackslashEscapes, "t${u(c)}") == "(fails)");
        assert(nam(Dialect.postgres, "t${u(c)}") == "\"t${u(c)}\"");
        assert(identifierProblem("t${u(c)}") == "name ends in whitespace");
      }
      // A name of only whitespace ends in it too.
      assert(Dialect.mysql.nameProblem(" ${u(0x09)}${u(0x0A)}") == "name ends in whitespace");
      assert(nam(Dialect.mysql, "${u(0x0D)} t") == "`${u(0x0D)} t`");
      assert(nam(Dialect.mysql, "t${u(0x85)}") == "`t${u(0x85)}`");
      assert(nam(Dialect.mysql, "t${u(0xA0)}") == "`t${u(0xA0)}`");
      assert(Dialect.mysql.nameProblem("#mysql50#t") == "name starts with #mysql50#");
      assert(nam(Dialect.mysql, "#mysql50") == "`#mysql50`");
      assert(nam(Dialect.mysql, "t#mysql50#") == "`t#mysql50#`");
      assert(nam(Dialect.sqlite, "#mysql50#t") == "\"#mysql50#t\"");
    }

## Queries

    test("mysql queries") {
      let col = Identifier.named("name") orelse panic();
      let q = mysql"SELECT ${col} FROM t WHERE a = ${1.5} AND b IS ${null} # done";
      assert(render(q, Dialect.mysql, PlaceholderStyle.question) ==
        "SELECT `name` FROM t WHERE a = ? AND b IS ? # done\n");
      assert(paramText(q.params[0]) == "float:1.5");
      assert(paramText(q.params[1]) == "null");
    }

Template mistakes, with MySQL's quotes and comments: backslashes that
end a string in one SQL mode but not another, `#` and `-- ` comments,
and executable comments.

    test("mysql template mistakes") {
      let check(build: fn (QueryBuilder): Void): String { checkTemplate(Dialect.mysql, build) }
      let inQuote = "hole inside a quote or comment";
      let backslash = "backslash before a quote or backslash in a string";
      assert(check { b => b.appendSafe("SELECT 1"); } == "ok");
      assert(check { b => b.appendSafe("SELECT '"); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT \""); b.appendInt(1); b.appendSafe("\""); } == inQuote);
      assert(check { b => b.appendSafe("SELECT `"); b.appendInt(1); b.appendSafe("`"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 1 # "); b.appendInt(1); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 1 -- "); b.appendInt(1); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 1 --\t"); b.appendInt(1); } == inQuote);
      assert(check { b => b.appendSafe("SELECT /* "); b.appendInt(1); b.appendSafe(" */"); } == inQuote);
      // `--` without a space is minus minus, unless a hole follows.
      assert(check { b => b.appendSafe("SELECT 5--1, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 5--"); b.appendInt(1); } == inQuote);
      // DEL is a control character too, but a line feed alone ends a
      // comment.
      assert(check { b => b.appendSafe("SELECT 5--${u(0x7F)}, "); b.appendInt(1); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 5--${u(0x80)}, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 # c\r, "); b.appendInt(1); } == inQuote);
      // Block comments don't nest.
      assert(check { b => b.appendSafe("SELECT /* /* */ "); b.appendInt(1); } == "ok");
      // Backslashes.
      assert(check { b => b.appendSafe("SELECT 'a\\' , "); b.appendInt(1); b.appendSafe("'"); } == backslash);
      assert(check { b => b.appendSafe("SELECT 'a\\\\'"); } == backslash);
      assert(check { b => b.appendSafe("SELECT \"a\\\"\""); } == backslash);
      assert(check { b => b.appendSafe("SELECT 'a\\nb\\\"', \"\\'\", `\\`, "); b.appendInt(1); } == "ok");
      // Executable comments.
      assert(check { b => b.appendSafe("SELECT /*! 1 */"); } == "executable comment in template text");
      assert(check { b => b.appendSafe("SELECT /*M! 1 */"); } == "executable comment in template text");
      assert(check { b => b.appendSafe("SELECT /*+ hint */ 1"); } == "ok");
      // A hint's own scanner reads quoted names, which can hold `*/`.
      let hintQuote = "quote in an optimizer hint";
      assert(check { b => b.appendSafe("SELECT /*+ QB_NAME(`*/ "); b.appendInt(1); b.appendSafe("`) */"); } ==
        hintQuote);
      assert(check { b => b.appendSafe("SELECT /*+ SET_VAR(a='b') */ 1"); } == hintQuote);
      assert(check { b => b.appendSafe("SELECT /*+ x \"y\" */ 1"); } == hintQuote);
      assert(check { b => b.appendSafe("SELECT /* x `y` */ 1"); } == "ok");
      // NUL ends a line comment, so it can't be in template text.
      assert(check { b => b.appendSafe("SELECT 1 # ${u(0)}\n, "); b.appendInt(1); } == "NUL in template text");
      assert(check { b => b.appendSafe("SELECT '${u(0)}'"); } == "NUL in template text");
      // Stray placeholders.
      assert(check { b => b.appendSafe("SELECT ?"); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT a$b"); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT '?', \"$1\", `?` # ?"); } == "ok");
      // User variables, `:=`, and `%` are fine.
      assert(check { b => b.appendSafe("SELECT @a := 1, 5 % 2"); } == "ok");
      // Unterminated.
      assert(check { b => b.appendSafe("SELECT 'a"); } == "template ends inside a quote or comment");
      assert(check { b => b.appendSafe("SELECT `a"); } == "template ends inside a quote or comment");
    }
