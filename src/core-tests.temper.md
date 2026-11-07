# Core Tests

Quoting tests for every profile, most with hostile input: quotes and
backslashes that try to end a string or name early, NUL, newlines,
comment starts, characters above U+FFFF, lone surrogates, and very
long text. Tests for one database's rules are in its own tests file.

## Test helpers

    let allDialects(): List<Dialect> {
      [Dialect.sqlite, Dialect.postgres, Dialect.mysql, Dialect.mysqlNoBackslashEscapes, Dialect.duckdb]
    }

    let str(d: Dialect, s: String): String { d.quoteString(s) orelse "(fails)" }
    let nam(d: Dialect, s: String): String { d.quoteName(s) orelse "(fails)" }

`u` writes a code point as a string. (Tests avoid `\u{…}` escapes,
which Temper misreads before a later `${…}` in the same block.)

    let u(c: Int): String { String.fromCodePoint(c) orelse panic() }

    let repeated(s: String, n: Int): String {
      let sb = new StringBuilder();
      for (var i = 0; i < n; i += 1) { sb.append(s); }
      sb.toString()
    }

`paramText` describes a parameter, for tests.

    let paramText(p: SqlValue): String {
      when (p) {
        is SqlText -> "text:${p.value}";
        is SqlInt -> "int:${p.value.toString()}";
        is SqlFloat -> "float:${p.value.toString()}";
        is SqlBool -> "bool:${p.value.toString()}";
        else -> "null";
      }
    }

## Strings

    test("strings double single quotes in every dialect") {
      for (let d of allDialects()) {
        assert(str(d, "") == "''");
        assert(str(d, "plain") == "'plain'");
        assert(str(d, "it's") == "'it''s'");
        assert(str(d, "'") == "''''");
        assert(str(d, "x'; DROP TABLE t; --") == "'x''; DROP TABLE t; --'");
      }
    }

Other characters need no escaping inside quotes: double quotes, back
quotes, comment starts, line breaks, and characters above U+FFFF.

    test("other characters stay as they are") {
      let inputs = [
        "\"", "`", "-- x", "/* x */", "# x", "a\nb", "a\r\nb", "\t", "$$", "?", "%s", ":x",
        u(0x1F600), "e${u(0x301)}", u(0xFEFF), u(0x2028), u(0xFFFF), u(0x10FFFF),
      ];
      for (let d of allDialects()) {
        for (let s of inputs) {
          assert(str(d, s) == "'${s}'");
        }
      }
    }

    test("very long strings") {
      // Built in a loop here, not with `repeated`, which Temper would
      // try to run while compiling.
      let input = new StringBuilder();
      let forSqlite = new StringBuilder();
      let forMysql = new StringBuilder();
      for (var i = 0; i < 50000; i += 1) {
        input.append("a'\\");
        forSqlite.append("a''\\");
        forMysql.append("a''\\\\");
      }
      let long = input.toString();
      assert(str(Dialect.sqlite, long) == "'${forSqlite.toString()}'");
      assert(str(Dialect.mysql, long) == "'${forMysql.toString()}'");
      assert(str(Dialect.postgres, long) == "'${forSqlite.toString()}'");
      assert(str(Dialect.duckdb, long) == "'${forSqlite.toString()}'");
    }

Lone surrogates exist only where strings are UTF-16 (C#, Java, and
JavaScript), or where Python's strings allow them. Elsewhere Temper
won't build such a string, so the test checks only what it can.

    test("lone surrogates in strings and names") {
      let sb = new StringBuilder();
      sb.append("a");
      let lone: String? = do {
        sb.appendCodePoint(0xD800);
        sb.toString()
      } orelse null;
      if (lone != null) {
        for (let d of allDialects()) {
          assert(str(d, lone) == "(fails)");
          assert(nam(d, lone) == "(fails)");
        }
      }
      assert(true);
    }

## Names

    test("names double their quote") {
      assert(nam(Dialect.sqlite, "t") == "\"t\"");
      assert(nam(Dialect.postgres, "a\"b") == "\"a\"\"b\"");
      assert(nam(Dialect.sqlite, "\"") == "\"\"\"\"");
      assert(nam(Dialect.sqlite, "a`b") == "\"a`b\"");
      assert(nam(Dialect.mysql, "t") == "`t`");
      assert(nam(Dialect.mysql, "a`b") == "`a``b`");
      assert(nam(Dialect.mysql, "a\"b") == "`a\"b`");
      assert(nam(Dialect.mysqlNoBackslashEscapes, "`") == "````");
      assert(nam(Dialect.sqlite, "x\"; DROP TABLE t; --") == "\"x\"\"; DROP TABLE t; --\"");
      assert(nam(Dialect.mysql, "x`; DROP TABLE t; --") == "`x``; DROP TABLE t; --`");
    }

A name is one name, so a dot stays inside the quotes. Backslashes are
plain in every dialect's names.

    test("dots and backslashes in names") {
      for (let d of allDialects()) {
        assert(nam(d, "a.b") == (if (d.name == "mysql" || d.name == "mysqlNoBackslashEscapes") { "`a.b`" } else { "\"a.b\"" }));
      }
      assert(nam(Dialect.mysql, "a\\") == "`a\\`");
      assert(nam(Dialect.sqlite, "a\\") == "\"a\\\"");
      assert(nam(Dialect.sqlite, "a\nb") == "\"a\nb\"");
    }

    test("names every dialect rejects") {
      for (let d of allDialects()) {
        assert(nam(d, "") == "(fails)");
        assert(nam(d, "a${u(0x0)}b") == "(fails)");
      }
      assert(Dialect.sqlite.nameProblem("") == "empty name");
      assert(Dialect.mysql.nameProblem(u(0x0)) == "NUL in name");
    }

PostgreSQL counts UTF-8 bytes, up to 63; MySQL counts characters, up to
64; SQLite has no limit.

    test("name lengths") {
      let a63 = repeated("a", 63);
      assert(nam(Dialect.postgres, a63) == "\"${a63}\"");
      assert(nam(Dialect.postgres, "${a63}a") == "(fails)");
      assert(Dialect.postgres.nameProblem("${a63}a") == "name longer than 63 UTF-8 bytes");
      // é is 2 bytes in UTF-8.
      assert(nam(Dialect.postgres, repeated(u(0xE9), 31)) != "(fails)");
      assert(nam(Dialect.postgres, repeated(u(0xE9), 32)) == "(fails)");
      assert(nam(Dialect.mysql, repeated(u(0xE9), 64)) != "(fails)");
      assert(nam(Dialect.mysql, repeated(u(0xE9), 65)) == "(fails)");
      assert(Dialect.mysql.nameProblem(repeated("a", 65)) == "name longer than 64 characters");
      let input = new StringBuilder();
      let quoted = new StringBuilder();
      for (var i = 0; i < 10000; i += 1) {
        input.append("n\"");
        quoted.append("n\"\"");
      }
      assert(nam(Dialect.sqlite, input.toString()) == "\"${quoted.toString()}\"");
      assert(nam(Dialect.postgres, input.toString()) == "(fails)");
    }
