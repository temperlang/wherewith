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

MySQL and MariaDB reject names above U+FFFF and names ending in a
space.

    test("MySQL-only name rules") {
      assert(nam(Dialect.mysql, "t${u(0x1F600)}") == "(fails)");
      assert(nam(Dialect.sqlite, "t${u(0x1F600)}") == "\"t${u(0x1F600)}\"");
      assert(nam(Dialect.postgres, "t${u(0x1F600)}") == "\"t${u(0x1F600)}\"");
      assert(nam(Dialect.mysql, "t ") == "(fails)");
      assert(nam(Dialect.mysql, " t") == "` t`");
      assert(nam(Dialect.sqlite, "t ") == "\"t \"");
      assert(Dialect.mysql.nameProblem("t ") == "name ends in a space");
    }
