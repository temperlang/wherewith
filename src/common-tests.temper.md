# Common Dialect Tests

The `sql` tag, `Dialect.common`, and the common lexer: its tokens,
every rule it refuses, and where it says the problem is.

## Test helpers

`lexed` lexes text as a common template, without parsing it, and
checks its strings and names for every target, and says `ok` or what's
wrong with it; `at` writes a problem with its place.

    let lexed(text: String): String {
      let lexer = new CommonLexer();
      lexer.scan(text) ?? lexer.endProblem() ?? lexer.targetProblem(commonTargets()) ?? "ok"
    }

    let at(message: String, line: Int, column: Int, excerpt: String): String {
      "${message}, at line ${line.toString()}, column ${column.toString()}: ${excerpt}"
    }

`spaced` joins strings with spaces.

    let spaced(parts: Listed<String>): String { parts.join(" ", fn (s: String): String { s }) }

`tokensOf` lexes runs with a value hole between each two, and writes
each token as its kind, its text, and its line and column.

    let tokensOf(runs: List<String>): String {
      let lexer = new CommonLexer();
      for (var i = 0; i < runs.length; i += 1) {
        if (i > 0) {
          let found = lexer.hole(holeValue);
          if (found != null) { return found; }
        }
        let found = lexer.scan(runs[i]);
        if (found != null) { return found; }
      }
      let ended = lexer.endProblem();
      if (ended != null) { return ended; }
      let names = [
        "", "keyword", "word", "name", "quoted", "string", "integer", "decimal", "symbol",
        "valueHole", "nameHole", "queryHole",
      ];
      let out = new ListBuilder<String>();
      let tokens = lexer.tokens;
      for (var i = 0; i < tokens.length; i += 1) {
        let t = tokens[i];
        let text = new StringBuilder();
        if (t.run < 0) {
          text.append(holeMark);
        } else {
          text.appendBetween(lexer.runs[t.run], t.begin, t.end);
        }
        out.add("${names[t.kind]}:${text.toString()}@${t.line.toString()}:${t.column.toString()}");
      }
      spaced(out)
    }

## The profile

`Dialect.common` quotes as the shared core does, and takes exactly the
names `Identifier` takes.

    test("the common profile") {
      let d = Dialect.common;
      assert(d.name == "common");
      assert(nam(d, "a\"b") == "\"a\"\"b\"");
      assert(nam(d, "a`b") == "\"a`b\"");
      assert(str(d, "it's \\") == "'it''s \\'");
      assert(str(d, "a${u(0)}b") == "(fails)");
      let names = [
        "a", "Mixed Case", "", "a${u(0)}", "t ", "t${u(0x9)}", "#mysql50#t", "t${u(0x1F600)}",
        repeated("a", 63), repeated("a", 64), repeated(u(0xE9), 31), repeated(u(0xE9), 32),
      ];
      for (let s of names) {
        assert((d.nameProblem(s) == null) == (identifierProblem(s) == null));
      }
    }

## The tag

A common query keeps its values as parameters, and renders for
`Dialect.common` canonically, with names bare where they can be.
Rendering for each database comes next.

    test("the sql tag") {
      let users = Identifier.named("users") orelse panic();
      let name = "Robert'); DROP TABLE students; --";
      let q = sql"SELECT id FROM ${users} WHERE name = ${name} AND age > ${7}";
      assert(q.dialect.name == "common");
      assert(q.params.length == 2);
      assert(paramText(q.params[0]) == "text:${name}");
      assert(render(q, Dialect.common, PlaceholderStyle.question) ==
        "SELECT id FROM users WHERE name = ? AND age > ?");
      assert(render(q, Dialect.common, PlaceholderStyle.dollarNumbered) ==
        "SELECT id FROM users WHERE name = $1 AND age > $2");
      for (let d of allDialects()) {
        assert(render(q, d, PlaceholderStyle.question) == "(fails)");
        assert(q.renderProblem(d, PlaceholderStyle.question) ==
          "rendering a common query for ${d.name} isn't built yet");
      }
      let other = sqlite"SELECT 1";
      assert(other.renderProblem(Dialect.common, PlaceholderStyle.question) ==
        "query checked for sqlite, not common");
      assert(partKinds(q) == "text name text param text param");
    }

## Tokens

Each kind of token, with its line and column. Keywords are read in any
case; function names, type names, `first`, and `last` are words that
can also be names; comments and whitespace make no tokens.

    test("common tokens") {
      assert(tokensOf(["SELECT a, \"B\"\"c\", 'it''s', count, 12, 1.50\n  FROM t WHERE x <> -1 || ", " -- c\n"]) ==
        spaced([
          "keyword:SELECT@1:1 name:a@1:8 symbol:,@1:9 quoted:\"B\"\"c\"@1:11 symbol:,@1:17",
          "string:'it''s'@1:19 symbol:,@1:26 word:count@1:28 symbol:,@1:33 integer:12@1:35",
          "symbol:,@1:37 decimal:1.50@1:39 keyword:FROM@2:3 name:t@2:8 keyword:WHERE@2:10",
          "name:x@2:16 symbol:<>@2:18 symbol:-@2:21 integer:1@2:22 symbol:||@2:24 valueHole:${holeMark}@2:27",
        ]));
      assert(tokensOf(["select Text, FIRST /* x */ from\tt"]) ==
        "keyword:select@1:1 word:Text@1:8 symbol:,@1:12 word:FIRST@1:14 keyword:from@1:28 name:t@1:33");
      assert(tokensOf(["a!=b<=c>=d<e>f=g+h*i/j%k(l).m"]) ==
        spaced([
          "name:a@1:1 symbol:!=@1:2 name:b@1:4 symbol:<=@1:5 name:c@1:7 symbol:>=@1:8 name:d@1:10",
          "symbol:<@1:11 name:e@1:12 symbol:>@1:13 name:f@1:14 symbol:=@1:15 name:g@1:16 symbol:+@1:17",
          "name:h@1:18 symbol:*@1:19 name:i@1:20 symbol:/@1:21 name:j@1:22 symbol:%@1:23 name:k@1:24",
          "symbol:(@1:25 name:l@1:26 symbol:)@1:27 symbol:.@1:28 name:m@1:29",
        ]));
    }

## Refused characters and operators

Anything outside the subset is refused where it is, outside quotes and
comments.

    test("common refusals") {
      let refusals = [
        new Pair("?", "? outside quotes; put values in holes"),
        new Pair("$1", "$ outside quotes; put values in holes"),
        new Pair(":x", ": isn't common SQL"),
        new Pair("::", ": isn't common SQL"),
        new Pair("@x", "@ isn't common SQL"),
        new Pair(";", "; outside quotes; write one statement per query"),
        new Pair("#", "# isn't common SQL"),
        new Pair("`", "` outside quotes; quote names with double quotes"),
        new Pair("[", "[ isn't common SQL"),
        new Pair("{", "{ isn't common SQL"),
        new Pair("&", "& isn't common SQL"),
        new Pair("^", "^ isn't common SQL"),
        new Pair("~", "~ isn't common SQL"),
        new Pair("\\", "\\ isn't common SQL"),
        new Pair("==", "== isn't common SQL"),
        new Pair("<=>", "<=> isn't common SQL"),
        new Pair("=>", "=> isn't common SQL"),
        new Pair("<<", "<< isn't common SQL"),
        new Pair(">>", ">> isn't common SQL"),
        new Pair("->", "-> isn't common SQL"),
        new Pair("**", "** isn't common SQL"),
        new Pair("!", "! isn't common SQL"),
        new Pair("|", "| isn't common SQL"),
        new Pair(u(0xE9), "non-ASCII character outside quotes"),
        new Pair(u(0xA0), "non-ASCII character outside quotes"),
        new Pair(u(0x1F600), "non-ASCII character outside quotes"),
        new Pair(u(0xB), "control character outside quotes"),
        new Pair(u(0x7F), "control character outside quotes"),
        new Pair(u(0), "NUL in template text"),
      ];
      for (let r of refusals) {
        let text = "SELECT a ${r.key} b";
        assert(lexed(text) == at(r.value, 1, 10, text));
      }
      let operators = ["=", "<>", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/", "%", "||", "<-", "= -"];
      for (let op of operators) {
        assert(lexed("SELECT a ${op} b") == "ok");
      }
      assert(lexed("SELECT\ta\r\n,${u(0xC)}b") == "ok");
      assert(lexed("SELECT ?") == at("? outside quotes; put values in holes", 1, 8, "SELECT ?"));
    }

## Comments

Comments hold anything but NUL, never nest, and aren't MySQL's
executable comments or hints. A line comment ends at a line feed,
with no lone carriage return in it.

    test("common comments") {
      assert(lexed("SELECT 1 -- what? $1 @a ${u(0xE9)}\n, 2") == "ok");
      assert(lexed("SELECT 1 /* ? ; ` ${u(0x1F600)} -- */, 2") == "ok");
      assert(lexed("SELECT 1 -- a\r\n, 2") == "ok");
      assert(lexed("SELECT 1 -- a\r") == "ok");
      assert(lexed("SELECT 1 -- end") == "ok");
      assert(lexed("SELECT /* a /* b */ */ 1") ==
        at("/* inside a comment", 1, 13, "SELECT /* a /* b */ */ 1"));
      assert(lexed("SELECT /*! 1 */ 2") ==
        at("executable comment or optimizer hint", 1, 8, "SELECT /*! 1 */ 2"));
      assert(lexed("SELECT /*+ x */ 2") ==
        at("executable comment or optimizer hint", 1, 8, "SELECT /*+ x */ 2"));
      assert(lexed("SELECT 1 -- a\rb\n") == at("carriage return in a line comment", 1, 14, "SELECT 1 -- a"));
      assert(lexed("SELECT 1 -- ${u(0)}\n") == at("NUL in template text", 1, 13, "SELECT 1 -- ${u(0)}"));
      assert(lexed("SELECT /* abc") == at("comment not closed", 1, 8, "SELECT /* abc"));
      let inComment = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT 1 -- ");
        b.appendInt(1);
      };
      assert(inComment == at("hole inside a quote or comment", 1, 13, "SELECT 1 -- "));
      let inBlock = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT /* ");
        b.appendInt(1);
        b.appendSafe(" */");
      };
      assert(inBlock == at("hole inside a quote or comment", 1, 11, "SELECT /* "));
    }

## Strings

Strings double their quote, take no prefix, and must suit every
database: for MySQL's default profile, that means no backslash, which
it reads as an escape.

    test("common strings") {
      assert(lexed("SELECT 'it''s', '${u(0xE9)}${u(0x1F600)}', '-- /* ? $1', ''") == "ok");
      assert(lexed("SELECT 'C:\\temp'") ==
        at("backslash in a string for mysql; bind the value instead", 1, 8, "SELECT 'C:\\temp'"));
      assert(lexed("SELECT 'a${u(0)}'") == at("NUL in template text", 1, 10, "SELECT 'a${u(0)}'"));
      assert(lexed("SELECT 'abc") == at("string not closed", 1, 8, "SELECT 'abc"));
      assert(lexed("SELECT x'0A'") == at("prefixed string", 1, 8, "SELECT x'0A'"));
      assert(lexed("SELECT n'a'") == at("prefixed string", 1, 8, "SELECT n'a'"));
      assert(lexed("SELECT _utf8mb4'a'") == at("prefixed string", 1, 8, "SELECT _utf8mb4'a'"));
      assert(lexed("SELECT a 'b'") == "ok");
      let inQuote = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT 'a");
        b.appendInt(1);
        b.appendSafe("'");
      };
      assert(inQuote == at("hole inside a quote or comment", 1, 10, "SELECT 'a"));
    }

## Names

Bare names are lowercase, and every name must suit every database,
each refusal naming the first database that refuses it.

    test("common names") {
      assert(lexed("SELECT a_1, _b, \"Mixed Case\", \"a\"\"b\", \"${u(0xE9)}\" FROM t") == "ok");
      assert(lexed("select a FrOm t") == "ok");
      assert(lexed("SELECT count, text, first, last, max FROM t") == "ok");
      assert(lexed("SELECT Name FROM t") ==
        at("bare name not lowercase; quote it to keep its case", 1, 8, "SELECT Name FROM t"));
      assert(lexed("SELECT ${repeated("a", 63)}") == "ok");
      assert(lexed("SELECT ${repeated("a", 64)}") ==
        at("name longer than 63 UTF-8 bytes for postgres", 1, 8, "SELECT ${repeated("a", 20)}"));
      assert(lexed("SELECT \"\"") == at("empty name for sqlite", 1, 8, "SELECT \"\""));
      assert(lexed("SELECT \"a \"") == at("name ends in whitespace for mysql", 1, 8, "SELECT \"a \""));
      assert(lexed("SELECT \"#mysql50#a\"") ==
        at("name starts with #mysql50# for mysql", 1, 8, "SELECT \"#mysql50#a\""));
      assert(lexed("SELECT \"t${u(0x1F600)}\"") ==
        at("code point above U+FFFF in name for mysql", 1, 8, "SELECT \"t${u(0x1F600)}\""));
      let wide = repeated(u(0xE9), 32);
      assert(lexed("SELECT \"${wide}\"") ==
        at("name longer than 63 UTF-8 bytes for postgres", 1, 8, "SELECT \"${repeated(u(0xE9), 19)}"));
      assert(lexed("SELECT \"abc") == at("quoted name not closed", 1, 8, "SELECT \"abc"));
    }

## Numbers

Integers fit in 64 bits, and decimals have at most 18 digits, leading
zeros aside; nothing runs into a number.

    test("common numbers") {
      assert(lexed("SELECT 9223372036854775807, 0009223372036854775807, 9223372036854775799, 0, 007") == "ok");
      assert(lexed("SELECT 1.5, 0.000000000000000001, 12345678901234567.8, -1") == "ok");
      let tooBig = ["9223372036854775808", "9300000000000000000", "10000000000000000000"];
      for (let n of tooBig) {
        assert(lexed("SELECT ${n}") == at("integer beyond 64 bits; bind it as a value", 1, 8, "SELECT ${n}"));
      }
      assert(lexed("SELECT 123456789012345678.9") ==
        at("decimal with more than 18 digits", 1, 8, "SELECT 123456789012345678.9"));
      assert(lexed("SELECT 1.") == at("decimal point without digits after it", 1, 9, "SELECT 1."));
      assert(lexed("SELECT .5") == at("decimal without a digit before its point", 1, 8, "SELECT .5"));
      for (let n of ["1e5", "0x1F", "1_000", "1.5e3", "12abc"]) {
        assert(lexed("SELECT ${n}") == at("number runs into a word", 1, 8, "SELECT ${n}"));
      }
    }

## Holes

Holes count as `${…}` in positions. The grammar decides where each
kind goes: a nested query alone in parentheses, a name where a name
goes, and only a value after `LIMIT` or `OFFSET`.

    test("common holes") {
      let a = Identifier.named("a") orelse panic();
      let lines = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT a,\n  ");
        b.appendInt(1);
        b.appendSafe(" + ?");
      };
      assert(lines == at("? outside quotes; put values in holes", 2, 10, "  ${holeMark} + ?"));
      let dotted = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT ");
        b.appendIdentifier(a);
        b.appendSafe(".");
        b.appendIdentifier(a);
        b.appendSafe(" FROM ");
        b.appendIdentifier(a);
        b.appendSafe(" AS t LIMIT ");
        b.appendInt(1);
        b.appendSafe(" OFFSET ");
        b.appendInt(2);
      };
      assert(dotted == "ok");
      let afterDot = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT t.");
        b.appendInt(1);
      };
      assert(afterDot == at("value where a name goes", 1, 10, "SELECT t.${holeMark}"));
      let beforeDot = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT ");
        b.appendInt(1);
        b.appendSafe(".a");
      };
      assert(beforeDot == at("value where a name goes", 1, 8, "SELECT ${holeMark}.a"));
      // Each place a name goes, and the hole's column there.
      let places = [
        new Pair("SELECT a AS ", 13), new Pair("SELECT a FROM ", 15), new Pair("SELECT a FROM t JOIN ", 22),
        new Pair("INSERT INTO ", 13), new Pair("UPDATE ", 8), new Pair("UPDATE t SET ", 14),
        new Pair("DELETE FROM ", 13), new Pair("select a as ", 13),
      ];
      for (let w of places) {
        let got = checkTemplate(Dialect.common) { b =>
          b.appendSafe(w.key);
          b.appendString("t");
        };
        assert(got == placed("${w.key}${holeMark}", "value where a name goes", w.value)) { got }
      }
      let named = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT a FROM t LIMIT ");
        b.appendIdentifier(a);
      };
      assert(named == placed("SELECT a FROM t LIMIT ${holeMark}", "name where a value goes", 23));
    }

A nested common query goes in parentheses, alone, as a subquery, and
its parameters number with the rest. A database's query can't nest in
a common template, nor a common query in a database's template, for
now.

    test("common nesting") {
      let inner = sql"SELECT b FROM u WHERE c = ${2}";
      let q = sql"SELECT a FROM t WHERE a IN (${inner}) AND d = ${3}";
      assert(render(q, Dialect.common, PlaceholderStyle.dollarNumbered) ==
        "SELECT a FROM t WHERE a IN (SELECT b FROM u WHERE c = $1) AND d = $2");
      let bare = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT ");
        b.appendQuery(inner);
      };
      assert(bare == at("nested query needs its own parentheses", 1, 8, "SELECT ${holeMark}"));
      let followed = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT (");
        b.appendQuery(inner);
        b.appendSafe(" + 1)");
      };
      assert(followed == at("nested query needs its own parentheses", 1, 9, "SELECT (${holeMark} + 1)"));
      let open = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT (");
        b.appendQuery(inner);
      };
      assert(open == at("nested query needs its own parentheses", 1, 9, "SELECT (${holeMark}"));
      let pg = postgres"SELECT 1";
      let foreign = checkTemplate(Dialect.common) { b =>
        b.appendSafe("SELECT (");
        b.appendQuery(pg);
        b.appendSafe(")");
      };
      assert(foreign == at("nested query checked for postgres, not common", 1, 9, "SELECT ("));
      let into = checkTemplate(Dialect.postgres) { b =>
        b.appendSafe("SELECT (");
        b.appendQuery(inner);
        b.appendSafe(")");
      };
      assert(into == "nested query checked for common, not postgres");
    }
