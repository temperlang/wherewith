# PostgreSQL Tests

    test("postgres queries") {
      let col = Identifier.named("name") orelse panic();
      let q = postgres"SELECT ${col}::text FROM t WHERE a @> ${"{1}"} AND b = ${true}";
      assert(render(q, Dialect.postgres, PlaceholderStyle.dollarNumbered) ==
        "SELECT \"name\" ::text FROM t WHERE a @> $1 AND b = $2");
      assert(paramText(q.params[1]) == "bool:true");
    }

Template mistakes, with PostgreSQL's quotes and comments: `E'…'`
strings with backslash escapes, dollar quotes, and nested block
comments.

    test("postgres template mistakes") {
      let check(build: fn (QueryBuilder): Void): String { checkTemplate(Dialect.postgres, build) }
      let inQuote = "hole inside a quote or comment";
      let unterminated = "template ends inside a quote or comment";
      assert(check { b => b.appendSafe("SELECT 1"); } == "ok");
      assert(check { b => b.appendSafe("SELECT '"); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT \"a"); b.appendInt(1); b.appendSafe("\""); } == inQuote);
      assert(check { b => b.appendSafe("SELECT 1 -- "); b.appendInt(1); } == inQuote);
      // A carriage return ends a line comment, as a line feed does.
      assert(check { b => b.appendSafe("SELECT 1 -- c\r, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 1 -- c\r'"); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      // Block comments nest.
      assert(check { b => b.appendSafe("SELECT /* /* */ "); b.appendInt(1); b.appendSafe(" */"); } ==
        inQuote);
      assert(check { b => b.appendSafe("SELECT /* /* */ */ "); b.appendInt(1); } == "ok");
      // Plain strings don't read backslash escapes; E strings do.
      assert(check { b => b.appendSafe("SELECT 'a\\' , "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT E'a\\' , "); b.appendInt(1); b.appendSafe("'"); } ==
        inQuote);
      assert(check { b => b.appendSafe("SELECT e'a\\'', "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT name'a\\' , "); b.appendInt(1); } == "ok");
      // An E string goes on past a doubled quote, and past whitespace
      // and line comments with a line break, but not past a hole.
      assert(check { b => b.appendSafe("SELECT E'a''\\' , "); b.appendInt(1); b.appendSafe("'"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT E'a'\n '\\' , "); b.appendInt(1); b.appendSafe("'"); } ==
        inQuote);
      assert(check { b => b.appendSafe("SELECT E'a' -- c\r\n'\\' , "); b.appendInt(1); b.appendSafe("'"); } ==
        inQuote);
      assert(check { b => b.appendSafe("SELECT E'a' '\\', "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT 'a'\n'\\', "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT E'a'\n"); b.appendInt(1); b.appendSafe("\n'\\', "); b.appendInt(2); } ==
        "ok");
      // Dollar quotes.
      assert(check { b => b.appendSafe("SELECT $$ it's ? $$, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT $fn$ $$ ' $fn$, "); b.appendInt(1); } == "ok");
      assert(check { b => b.appendSafe("SELECT $fn$ "); b.appendInt(1); b.appendSafe(" $fn$"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT $a$ $b$ "); b.appendInt(1); b.appendSafe(" $a$"); } == inQuote);
      assert(check { b => b.appendSafe("SELECT $$ x"); } == unterminated);
      assert(check { b => b.appendSafe("SELECT E'x"); } == unterminated);
      assert(check { b => b.appendSafe("SELECT /* /* */"); } == unterminated);
      // Stray placeholders.
      assert(check { b => b.appendSafe("SELECT $1"); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT a$b"); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT $"); b.appendInt(1); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT a ? b"); } == "parameter in template text");
      assert(check { b => b.appendSafe("SELECT '?', \"?\", $q$?$q$ -- ?"); } == "ok");
      // Casts, operators, and `%` are fine.
      assert(check { b => b.appendSafe("SELECT a::int, b @> c, d % 2, e[1:2]"); } == "ok");
    }
