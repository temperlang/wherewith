# Common Expression Tests

The expression parser, its checks, and the canonical printer: the
precedence table, every operator, every refusal with its message and
place, holes by kind, the depth limit, and a randomized round trip.

## Test helpers

`parseOnly` parses text as one expression, without the checks, and
prints it canonically, or with every operand's parentheses for
`explicit`; `checked` parses and checks it too. Each gives the problem
instead, if there is one.

    let parseOnly(text: String, explicit: Boolean): String {
      let lexer = new CommonLexer();
      let found = lexer.scan(text) ?? lexer.endProblem();
      if (found != null) { return found; }
      let parser = new CommonParser(lexer);
      let tree: CommonExpr? = parser.parseExpression() orelse null;
      if (tree != null) {
        new CommonPrinter(lexer, explicit).print(tree).runs[0]
      } else {
        parser.problem ?? "fails"
      }
    }

    let checked(text: String): String {
      let tag = new ExprTag();
      tag.appendSafe(text);
      tag.accumulated
    }

`placed` writes a problem at a column of one line of text, with the
excerpt the lexer gives: up to 20 code points on each side.

    let placed(text: String, message: String, column: Int): String {
      let first = if (column - 1 > 20) { column - 21 } else { 0 };
      let out = new StringBuilder();
      var k = 0;
      for (var i = String.begin; text.hasIndex(i); i = text.next(i)) {
        if (k >= first && k < column + 19) { out.appendCodePoint(text[i]) orelse panic(); }
        k += 1;
      }
      at(message, 1, column, out.toString())
    }

`expr` is a tag that parses and checks its template as an expression,
and gives it printed canonically, with `?` for each value and `{name}`
for each name, or the problem. A nested query goes in as its own
tokens, as the builder puts it.

    class ExprTag {
      private lexer: CommonLexer = new CommonLexer();
      private holes: ListBuilder<QueryPart> = new ListBuilder<QueryPart>();
      private shown: ListBuilder<String> = new ListBuilder<String>();
      private var problem: String? = null;

      public appendSafe(fixed: String): Void { note(lexer.scan(fixed)); }
      @overload("append")
      public appendString(x: String?): Void {
        if (x == null) { appendValue(new SqlNull()); } else { appendValue(new SqlText(x)); }
      }
      @overload("append")
      public appendInt(x: Int): Void { appendValue(new SqlInt(x.toInt64())); }
      @overload("append")
      public appendInt64(x: Int64): Void { appendValue(new SqlInt(x)); }
      @overload("append")
      public appendFloat64(x: Float64): Void { appendValue(new SqlFloat(x)); }
      @overload("append")
      public appendBoolean(x: Boolean): Void { appendValue(new SqlBool(x)); }
      @overload("append")
      public appendValue(x: SqlValue): Void { hole(new QueryParam(x)); }
      @overload("append")
      public appendIdentifier(x: Identifier): Void { hole(new QueryName(x)); }
      @overload("append")
      public appendQuery(x: Query): Void {
        inCode();
        lexer.beginQuery();
        for (let p of x.parts) {
          if (p is QueryText) { note(lexer.scan(p.text)); } else { hole(p); }
        }
        note(lexer.endQuery());
      }

      public get accumulated(): String {
        if (problem == null && lexer.inLineComment) { note(lexer.scan("\n")); }
        if (problem == null) { note(lexer.endProblem()); }
        let found = problem;
        if (found != null) { return found; }
        let parser = new CommonParser(lexer);
        let parsed: CommonExpr? = parser.parseExpression() orelse null;
        if (parsed != null) { printed(parsed) } else { parser.problem ?? "fails" }
      }

`printed` checks a tree and prints it, or gives the problem.

      private printed(tree: CommonExpr): String {
        let checker = new CommonChecker(lexer, holes.toList(), commonTargets());
        let kind = checker.check(tree) orelse -1;
        if (kind < 0) { return checker.problem ?? "fails"; }
        let printed = new CommonPrinter(lexer, false).print(tree);
        let out = new StringBuilder();
        for (var i = 0; i < printed.runs.length; i += 1) {
          if (i > 0) { out.append(shown[printed.holes[i - 1]]); }
          out.append(printed.runs[i]);
        }
        out.toString()
      }

      private hole(part: QueryPart): Void {
        inCode();
        if (part is QueryName) {
          note(lexer.hole(holeName));
          shown.add("{${part.name.name}}");
        } else {
          note(lexer.hole(holeValue));
          shown.add("?");
        }
        holes.add(part);
      }

      private inCode(): Void {
        if (problem == null && !lexer.inCode) { problem = lexer.locate("hole inside a quote or comment"); }
      }

      private note(found: String?): Void {
        if (problem == null) { problem = found; }
      }
    }

    let expr = ExprTag;

    let named(name: String): Identifier { Identifier.named(name) orelse panic() }

## Precedence

Each operator's place, shown with every operand that's an operator
expression in parentheses: `OR`, then `AND`, then `NOT`, then one
comparison or other predicate, then `||`, then `+` and `-`, then `*`,
`/`, and `%`, then a sign.

    test("common expression precedence") {
      let shapes = [
        new Pair("a OR b AND c", "a OR (b AND c)"),
        new Pair("a AND b OR c", "(a AND b) OR c"),
        new Pair("a OR b OR c AND d", "a OR b OR (c AND d)"),
        new Pair("NOT a AND b", "(NOT a) AND b"),
        new Pair("NOT a = b", "NOT (a = b)"),
        new Pair("NOT NOT a", "NOT (NOT a)"),
        new Pair("a = b AND c <> d", "(a = b) AND (c <> d)"),
        new Pair("a = b + c * d", "a = (b + (c * d))"),
        new Pair("a + b * c - d", "(a + (b * c)) - d"),
        new Pair("a - b - c", "(a - b) - c"),
        new Pair("a - (b - c)", "a - (b - c)"),
        new Pair("a * b / c % d", "((a * b) / c) % d"),
        new Pair("a / (b * c)", "a / (b * c)"),
        new Pair("-a * b", "(-a) * b"),
        new Pair("-(a * b)", "-(a * b)"),
        new Pair("- -a", "-(-a)"),
        new Pair("+a", "+a"),
        new Pair("a || b || c", "a || b || c"),
        new Pair("a || -b", "a || (-b)"),
        new Pair("(a + b) || c", "(a + b) || c"),
        new Pair("a = b || c", "a = (b || c)"),
        new Pair("a || b = c", "(a || b) = c"),
        new Pair("a IS NULL AND b IS NOT NULL", "(a IS NULL) AND (b IS NOT NULL)"),
        new Pair("a NOT IN (1, b + 1) OR c", "(a NOT IN (1, b + 1)) OR c"),
        new Pair("a BETWEEN b AND c AND d", "(a BETWEEN b AND c) AND d"),
        new Pair("a NOT BETWEEN b + 1 AND c || d", "a NOT BETWEEN (b + 1) AND (c || d)"),
        new Pair("a NOT LIKE b || '%' ESCAPE '!'", "a NOT LIKE (b || '%') ESCAPE '!'"),
        new Pair("(a OR b) AND c", "(a OR b) AND c"),
        new Pair("a OR (b OR c)", "a OR (b OR c)"),
        new Pair("(a = b) = c", "(a = b) = c"),
        new Pair("CASE WHEN a THEN b + 1 ELSE c END * 2", "CASE WHEN a THEN b + 1 ELSE c END * 2"),
        new Pair("abs(a + b) * -c", "ABS(a + b) * (-c)"),
      ];
      for (let s of shapes) {
        let got = parseOnly(s.key, true);
        assert(got == s.value) { "${s.key}: ${got}" }
      }
    }

## Canonical form

Keywords and functions in capitals, single spaces, names bare where
they can be, integers without leading zeros, and only the parentheses
the grammar needs. Comments and line breaks go.

    test("common expression canonical form") {
      let forms = [
        new Pair("a   +\n b", "a + b"),
        new Pair("a and not b or c is not null", "a AND NOT b OR c IS NOT NULL"),
        new Pair("((a))", "a"),
        new Pair("(a + b) * c", "(a + b) * c"),
        new Pair("a + (b * c)", "a + b * c"),
        new Pair("(a + b) + c", "a + b + c"),
        new Pair("a - (b + c)", "a - (b + c)"),
        new Pair("(a || b) || c", "(a || b) || c"),
        new Pair("NOT (a = b)", "NOT a = b"),
        new Pair("(NOT a) = b", "(NOT a) = b"),
        new Pair("- -a", "- -a"),
        new Pair("-(-1)", "- -1"),
        new Pair("\"Mixed\" = \"plain\"", "\"Mixed\" = plain"),
        new Pair("\"select\" = count", "\"select\" = \"count\""),
        new Pair("\"a\"\"b\" = \"9a\"", "\"a\"\"b\" = \"9a\""),
        new Pair("t.c = \"T\".\"c\"", "t.c = \"T\".c"),
        new Pair("007 + 00.50 + 0 + 0.0", "7 + 0.50 + 0 + 0.0"),
        new Pair("cast(a as text) || 'x''y'", "CAST(a AS TEXT) || 'x''y'"),
        new Pair("count(*) + count(distinct a) + coalesce(a, b, 1)", "COUNT(*) + COUNT(DISTINCT a) + COALESCE(a, b, 1)"),
        new Pair("case a when 1 then 'x' when 2 then 'y' else 'z' end", "CASE a WHEN 1 THEN 'x' WHEN 2 THEN 'y' ELSE 'z' END"),
        new Pair("case when a then b end", "CASE WHEN a THEN b END"),
        new Pair("a /* c */ = -- x\n b", "a = b"),
        new Pair("a <> b and c != d", "a <> b AND c <> d"),
        new Pair("a <= b and c >= d and e < f and g > h", "a <= b AND c >= d AND e < f AND g > h"),
        new Pair("null is null or true or false", "NULL IS NULL OR TRUE OR FALSE"),
        new Pair("a not in (1) and b in (2, 3)", "a NOT IN (1) AND b IN (2, 3)"),
        new Pair("a like 'x' escape '!'", "a LIKE 'x' ESCAPE '!'"),
        new Pair("sum(distinct a) + min(a) + max(a) + avg(a)", "SUM(DISTINCT a) + MIN(a) + MAX(a) + AVG(a)"),
        new Pair("length(a) + abs(b)", "LENGTH(a) + ABS(b)"),
        new Pair("upper(lower(trim(a))) || substr(a, 1, 2) || replace(a, 'x', 'y')", "UPPER(LOWER(TRIM(a))) || SUBSTR(a, 1, 2) || REPLACE(a, 'x', 'y')"),
        new Pair("nullif(a, 1)", "NULLIF(a, 1)"),
        new Pair("cast(a as Integer) + cast(b as DOUBLE)", "CAST(a AS INTEGER) + CAST(b AS DOUBLE)"),
        new Pair("first + last + text", "\"first\" + \"last\" + \"text\""),
      ];
      for (let f of forms) {
        let got = parseOnly(f.key, false);
        assert(got == f.value) { "${f.key}: ${got}" }
      }
    }

## Grammar refusals

What the grammar refuses, each with its message and place. Predicates
don't chain, `||` beside arithmetic needs parentheses, and functions
take set numbers of arguments.

    test("common expression grammar refusals") {
      let refusals = [
        new Pair("a = b = c", new Pair("comparisons don't chain; add parentheses", 7)),
        new Pair("a = b IS NULL", new Pair("comparisons don't chain; add parentheses", 7)),
        new Pair("a < b BETWEEN 1 AND 2", new Pair("comparisons don't chain; add parentheses", 7)),
        new Pair("a IS NULL IS NULL", new Pair("comparisons don't chain; add parentheses", 11)),
        new Pair("a LIKE 'x' NOT LIKE 'y'", new Pair("comparisons don't chain; add parentheses", 12)),
        new Pair("a IN (1) = b", new Pair("comparisons don't chain; add parentheses", 10)),
        new Pair("a || b + c", new Pair("arithmetic beside || needs parentheses; databases group them differently", 8)),
        new Pair("a * b || c", new Pair("arithmetic beside || needs parentheses; databases group them differently", 3)),
        new Pair("a + b || c", new Pair("arithmetic beside || needs parentheses; databases group them differently", 3)),
        new Pair("a || b || c * d", new Pair("arithmetic beside || needs parentheses; databases group them differently", 13)),
        new Pair("a IS TRUE", new Pair("expected NULL", 6)),
        new Pair("a IS NOT 1", new Pair("expected NULL", 10)),
        new Pair("a NOT b", new Pair("expected IN, BETWEEN, or LIKE after NOT", 7)),
        new Pair("a ILIKE b", new Pair("ILIKE isn't common SQL", 3)),
        new Pair("a = NOT b", new Pair("NOT here needs parentheses", 5)),
        new Pair("a +", new Pair("expected an expression", 4)),
        new Pair("", new Pair("expected an expression", 1)),
        new Pair("(a", new Pair("expected )", 3)),
        new Pair("a)", new Pair("unmatched )", 2)),
        new Pair("a b", new Pair("expected the end of the expression", 3)),
        new Pair("foo(a)", new Pair("unknown function foo", 1)),
        new Pair("\"Abs\"(a)", new Pair("unknown function \"Abs\"", 1)),
        new Pair("integer(a)", new Pair("unknown function integer", 1)),
        new Pair("abs(a, b)", new Pair("ABS takes 1 argument", 1)),
        new Pair("coalesce(a)", new Pair("COALESCE takes 2 or more arguments", 1)),
        new Pair("nullif(a, b, c)", new Pair("NULLIF takes 2 arguments", 1)),
        new Pair("substr(a)", new Pair("SUBSTR takes 2 or 3 arguments", 1)),
        new Pair("replace(a, b)", new Pair("REPLACE takes 3 arguments", 1)),
        new Pair("trim(a, 'x')", new Pair("TRIM takes 1 argument", 1)),
        new Pair("count()", new Pair("COUNT takes 1 argument", 1)),
        new Pair("count(distinct a, b)", new Pair("COUNT takes 1 argument", 1)),
        new Pair("lower(distinct a)", new Pair("DISTINCT outside an aggregate", 7)),
        new Pair("sum(*)", new Pair("expected an expression", 5)),
        new Pair("count(*", new Pair("expected )", 8)),
        new Pair("cast(a as varchar)", new Pair("expected INTEGER, DOUBLE, or TEXT", 11)),
        new Pair("cast(a, text)", new Pair("expected AS", 7)),
        new Pair("case when a then b", new Pair("expected END", 19)),
        new Pair("case a then b end", new Pair("expected WHEN", 8)),
        new Pair("case when a b end", new Pair("expected THEN", 13)),
        new Pair("a between 1 or 2", new Pair("expected AND", 13)),
        new Pair("a like b escape c", new Pair("expected a string after ESCAPE", 17)),
        new Pair("a in b", new Pair("expected (", 6)),
        new Pair("a in ()", new Pair("expected an expression", 7)),
        new Pair("a in (1,)", new Pair("expected an expression", 9)),
        new Pair("t.c.d", new Pair("name with more than two parts", 4)),
        new Pair("t.select", new Pair("expected a name", 3)),
        new Pair("t.", new Pair("expected a name", 3)),
        new Pair("Count = 1", new Pair("bare name not lowercase; quote it to keep its case", 1)),
        new Pair("select", new Pair("a subquery needs its own parentheses", 1)),
        new Pair("(a, b) = (1, 2)", new Pair("expected )", 3)),
        new Pair("exists a", new Pair("expected (", 8)),
      ];
      for (let r of refusals) {
        let got = parseOnly(r.key, false);
        let want = placed(r.key, r.value.key, r.value.value);
        assert(got == want) { "${r.key}: ${got}" }
      }
      assert(parseOnly("a = 1\n  AND b = c = d", false) ==
        at("comparisons don't chain; add parentheses", 2, 13, "  AND b = c = d"));
    }

## Checks

What the checks refuse, since the databases would read it differently,
each with its message and place.

    test("common expression check refusals") {
      let refusals = [
        new Pair("a / 2", new Pair("/ without a float operand; databases divide integers differently", 3)),
        new Pair("a / b", new Pair("/ without a float operand; databases divide integers differently", 3)),
        new Pair("a % 1.5", new Pair("% of a float; SQLite truncates it to an integer", 3)),
        new Pair("a / 0.0", new Pair("/ by zero; databases differ", 3)),
        new Pair("a / -0.0", new Pair("/ by zero; databases differ", 3)),
        new Pair("a % 0", new Pair("% by zero; databases differ", 3)),
        new Pair("a = NULL", new Pair("= NULL is never true; use IS NULL", 3)),
        new Pair("NULL <> a", new Pair("<> NULL is never true; use IS NOT NULL", 6)),
        new Pair("a != NULL", new Pair("!= NULL is never true; use IS NOT NULL", 3)),
        new Pair("a < NULL", new Pair("< NULL is never true", 3)),
        new Pair("a IN (1, NULL)", new Pair("NULL in an IN list never matches; use IS NULL", 10)),
        new Pair("CASE a WHEN NULL THEN 1 END", new Pair("WHEN NULL never matches; use WHEN x IS NULL", 13)),
        new Pair("a LIKE b", new Pair("LIKE without ESCAPE takes only a literal pattern", 8)),
        new Pair("a LIKE b ESCAPE ''", new Pair("ESCAPE takes one character", 17)),
        new Pair("a LIKE b ESCAPE '!!'", new Pair("ESCAPE takes one character", 17)),
        new Pair("a LIKE b ESCAPE '%'", new Pair("% can't be the escape character", 17)),
        new Pair("a LIKE b ESCAPE '_'", new Pair("_ can't be the escape character", 17)),
        new Pair("a LIKE b ESCAPE ''''", new Pair("' can't be the escape character", 17)),
        new Pair("a LIKE '!a' ESCAPE '!'", new Pair("escape character not before %, _, or itself", 8)),
        new Pair("a LIKE 'a!' ESCAPE '!'", new Pair("escape character not before %, _, or itself", 8)),
        new Pair("1 + 'a'", new Pair("text in arithmetic", 5)),
        new Pair("TRUE + 1", new Pair("a boolean in arithmetic", 1)),
        new Pair("-'a'", new Pair("text in arithmetic", 2)),
        new Pair("a AND 1", new Pair("a number where a condition goes", 7)),
        new Pair("NOT 'x'", new Pair("text where a condition goes", 5)),
        new Pair("CASE WHEN 1 THEN a END", new Pair("a number where a condition goes", 11)),
        new Pair("1 = 'a'", new Pair("comparing a number with text", 3)),
        new Pair("TRUE = 1", new Pair("comparing a boolean with a number", 6)),
        new Pair("1 BETWEEN a AND 'z'", new Pair("comparing a number with text", 17)),
        new Pair("1 IN (a, 'x')", new Pair("comparing a number with text", 10)),
        new Pair("CASE 1 WHEN 'a' THEN 2 END", new Pair("comparing a number with text", 13)),
        new Pair("NULLIF(1, 'a')", new Pair("comparing a number with text", 11)),
        new Pair("CASE WHEN a THEN 1 ELSE 'x' END", new Pair("CASE mixes a number and text", 25)),
        new Pair("COALESCE(a, 1, 'x')", new Pair("COALESCE mixes a number and text", 16)),
        new Pair("5 LIKE 'x'", new Pair("a number in LIKE", 1)),
        new Pair("'a' || TRUE", new Pair("a boolean in ||; databases write booleans differently", 8)),
        new Pair("'a' || 1.5", new Pair("a float in ||; databases write floats differently", 8)),
        new Pair("LOWER(1)", new Pair("a number in LOWER", 7)),
        new Pair("LENGTH(TRUE)", new Pair("a boolean in LENGTH", 8)),
        new Pair("REPLACE(a, 1, 'x')", new Pair("a number in REPLACE", 12)),
        new Pair("ABS('x')", new Pair("text in ABS", 5)),
        new Pair("MAX(a = b)", new Pair("a boolean in MAX", 7)),
        new Pair("SUM(TRUE)", new Pair("a boolean in SUM", 5)),
        new Pair("CAST(a = b AS INTEGER)", new Pair("CAST of a boolean; databases convert booleans differently", 1)),
        new Pair("CAST(1.5 AS INTEGER)", new Pair("CAST of a float to INTEGER; SQLite truncates, the others round", 1)),
        new Pair("CAST(1.5 AS TEXT)", new Pair("CAST of a float to TEXT; databases write floats differently", 1)),
        new Pair("CAST('1.5' AS INTEGER)", new Pair("CAST of a string that isn't a plain number", 1)),
        new Pair("CAST(' 1' AS INTEGER)", new Pair("CAST of a string that isn't a plain number", 1)),
        new Pair("CAST('1e5' AS DOUBLE)", new Pair("CAST of a string that isn't a plain number", 1)),
        new Pair("SUBSTR(a, 0)", new Pair("SUBSTR start below 1; databases differ", 11)),
        new Pair("SUBSTR(a, -1, 2)", new Pair("SUBSTR start below 1; databases differ", 11)),
        new Pair("SUBSTR(a, 1, -2)", new Pair("SUBSTR length below 0; databases differ", 14)),
        new Pair("SUBSTR(a, 1.5)", new Pair("a float in SUBSTR", 11)),
        new Pair("SUM(COUNT(a))", new Pair("aggregate inside an aggregate", 5)),
      ];
      for (let r of refusals) {
        let got = checked(r.key);
        let want = placed(r.key, r.value.key, r.value.value);
        assert(got == want) { "${r.key}: ${got}" }
      }
    }

What the checks accept: `/` with a float operand, literal `LIKE`
patterns, and kinds that every database reads alike.

    test("common expression check passes") {
      let passes = [
        new Pair("a / 2.0", "a / 2.0"),
        new Pair("a * 1.0 / b", "a * 1.0 / b"),
        new Pair("cast(a as double) / b", "CAST(a AS DOUBLE) / b"),
        new Pair("avg(a) / 2", "AVG(a) / 2"),
        new Pair("-(a * 1.5) / 2", "-(a * 1.5) / 2"),
        new Pair("sum(a * 1.0) / count(*)", "SUM(a * 1.0) / COUNT(*)"),
        new Pair("abs(-1.5) / 2", "ABS(-1.5) / 2"),
        new Pair("case when a then 1 else 2.5 end / 2", "CASE WHEN a THEN 1 ELSE 2.5 END / 2"),
        new Pair("a % 2", "a % 2"),
        new Pair("a LIKE 'x%'", "a LIKE 'x%'"),
        new Pair("a LIKE '100!%' ESCAPE '!'", "a LIKE '100!%' ESCAPE '!'"),
        new Pair("a LIKE 'a!!b!_' ESCAPE '!'", "a LIKE 'a!!b!_' ESCAPE '!'"),
        new Pair("a NOT LIKE b || '%' ESCAPE '!'", "a NOT LIKE b || '%' ESCAPE '!'"),
        new Pair("'a' || 1 || b || NULL", "'a' || 1 || b || NULL"),
        new Pair("a = TRUE AND b IS NULL", "a = TRUE AND b IS NULL"),
        new Pair("CAST('12' AS INTEGER) + CAST('-1.5' AS DOUBLE)", "CAST('12' AS INTEGER) + CAST('-1.5' AS DOUBLE)"),
        new Pair("CAST(1 AS TEXT) || 'x' = 'y' AND CAST(1.5 AS DOUBLE) + 1 > 2", "CAST(1 AS TEXT) || 'x' = 'y' AND CAST(1.5 AS DOUBLE) + 1 > 2"),
        new Pair("SUBSTR(a, 1) || SUBSTR(a, b, 0) || SUBSTR(a, 2, 3)", "SUBSTR(a, 1) || SUBSTR(a, b, 0) || SUBSTR(a, 2, 3)"),
        new Pair("SUM(a) + COUNT(b) + MAX(ABS(a))", "SUM(a) + COUNT(b) + MAX(ABS(a))"),
        new Pair("COUNT(DISTINCT a) > 1 AND MIN(a) || 'x' = 'y'", "COUNT(DISTINCT a) > 1 AND MIN(a) || 'x' = 'y'"),
        new Pair("COALESCE(a, NULL, 1) = NULLIF(a, 0)", "COALESCE(a, NULL, 1) = NULLIF(a, 0)"),
        new Pair("LENGTH(TRIM(LOWER(a))) < 3", "LENGTH(TRIM(LOWER(a))) < 3"),
        new Pair("REPLACE(UPPER(a), 'x', 'y') <> ''", "REPLACE(UPPER(a), 'x', 'y') <> ''"),
        new Pair("1 BETWEEN 0 AND 2.5 AND a IN (1, 2.5, b)", "1 BETWEEN 0 AND 2.5 AND a IN (1, 2.5, b)"),
        new Pair("CASE a WHEN 1 THEN 'x' ELSE NULL END", "CASE a WHEN 1 THEN 'x' ELSE NULL END"),
        new Pair("NOT a AND (b OR c = 1)", "NOT a AND (b OR c = 1)"),
      ];
      for (let p of passes) {
        let got = checked(p.key);
        assert(got == p.value) { "${p.key}: ${got}" }
      }
    }

## Holes

Values go wherever an expression does, names only in a column, and
nested queries only in their own parentheses, with `IN`, or after
`EXISTS`, where they go in as written. The checks see each value's
kind.

    test("common expression holes") {
      let t = named("t");
      let c = named("c");
      let f = named("f");
      let q = sql"SELECT 1";
      assert(expr"a + ${1} = ${2}" == "a + ? = ?");
      assert(expr"${t}.${c} = ${"x"} AND ${c} IS NULL" == "{t}.{c} = ? AND {c} IS NULL");
      assert(expr"t.${c} || ${1}" == "t.{c} || ?");
      assert(expr"a IN (${q}) AND EXISTS (${q}) AND (${q}) > 1" ==
        "a IN (SELECT 1) AND EXISTS (SELECT 1) AND (SELECT 1) > 1");
      assert(expr"a NOT IN ((${q}), ${1})" == "a NOT IN ((SELECT 1), ?)");
      assert(expr"${1} + ${t}.${c} * ${2}" == "? + {t}.{c} * ?");
      assert(expr"${t}.${c} / ${1.5}" == "{t}.{c} / ?");
      assert(expr"${t}.${c} / ${2}" ==
        at("/ without a float operand; databases divide integers differently", 1, 11, "${holeMark}.${holeMark} / ${holeMark}"));
      assert(expr"a % ${1.5}" == at("% of a float; SQLite truncates it to an integer", 1, 3, "a % ${holeMark}"));
      assert(expr"${"x"} + 1" == at("text in arithmetic", 1, 1, "${holeMark} + 1"));
      assert(expr"${true} AND a" == "? AND a");
      assert(expr"a || ${true}" == at("a boolean in ||; databases write booleans differently", 1, 6, "a || ${holeMark}"));
      assert(expr"a LIKE ${"x%"} ESCAPE '!'" == "a LIKE ? ESCAPE '!'");
      assert(expr"a LIKE ${"x%"}" ==
        at("LIKE without ESCAPE takes only a literal pattern", 1, 8, "a LIKE ${holeMark}"));
      assert(expr"${f}(a)" == at("unknown function ${holeMark}", 1, 1, "${holeMark}(a)"));
      assert(expr"CAST(a AS ${t})" == at("expected INTEGER, DOUBLE, or TEXT", 1, 11, "CAST(a AS ${holeMark})"));
      assert(expr"COUNT(${q})" == at("nested query needs its own parentheses", 1, 7, "COUNT(${holeMark})"));
      assert(expr"a LIKE ${"x"} ESCAPE ${"!"}" ==
        at("expected a string after ESCAPE", 1, 20, "a LIKE ${holeMark} ESCAPE ${holeMark}"));
      assert(expr"a IS ${1}" == at("expected NULL", 1, 6, "a IS ${holeMark}"));
      assert(expr"EXISTS (${1})" == at("expected SELECT or a nested query", 1, 9, "EXISTS (${holeMark})"));
      assert(expr"a = ${t}" == "a = {t}");
    }

A value hole holding null is refused wherever `NULL` written in the
text is: in a comparison, in an `IN` list, and after `WHEN` in a simple
`CASE`, which never match. Elsewhere it's fine.

    test("common expression null values") {
      let n: SqlValue = new SqlNull();
      let h = holeMark;
      assert(expr"a = ${n}" == at("= with a null value is never true; use IS NULL", 1, 3, "a = ${h}"));
      assert(expr"${n} <> a" == at("<> with a null value is never true; use IS NOT NULL", 1, 6, "${h} <> a"));
      assert(expr"a != ${n}" == at("!= with a null value is never true; use IS NOT NULL", 1, 3, "a != ${h}"));
      assert(expr"a < ${n}" == at("< with a null value is never true", 1, 3, "a < ${h}"));
      assert(expr"a IN (1, ${n})" == at("a null value in an IN list never matches; use IS NULL", 1, 10, "a IN (1, ${h})"));
      assert(expr"a NOT IN (${n})" == at("a null value in an IN list never matches; use IS NULL", 1, 11, "a NOT IN (${h})"));
      assert(expr"CASE a WHEN ${n} THEN 1 END" ==
        at("WHEN with a null value never matches; use WHEN x IS NULL", 1, 13, "CASE a WHEN ${h} THEN 1 END"));
      assert(expr"COALESCE(${n}, a) = 1" == "COALESCE(?, a) = 1");
      assert(expr"a IS NULL OR a = ${1}" == "a IS NULL OR a = ?");
      assert(expr"CASE WHEN a THEN ${n} ELSE 1 END" == "CASE WHEN a THEN ? ELSE 1 END");
      assert(expr"${n} IS NULL" == "? IS NULL");
      let nick: String? = null;
      assert(expr"a = ${nick}" == at("= with a null value is never true; use IS NULL", 1, 3, "a = ${h}"));
    }

## Constants

Arithmetic on constants is refused where its result overflows a 64-bit
integer or isn't a finite float, whether or not it's negated, at the
operator that overflows. Rendering's folding is in the
[rendering tests](common-rendering-tests.temper.md#constants).

    test("common expression constant overflow") {
      let h = holeMark;
      let min = -0x8000_0000_0000_0000_i64;
      let max = 0x7FFF_FFFF_FFFF_FFFF_i64;
      let over = "constant arithmetic overflows a 64-bit integer; databases differ";
      let infinite = "constant arithmetic gives infinity or NaN; databases differ";
      assert(expr"-${min}" == at(over, 1, 1, "-${h}"));
      assert(expr"a + -(${min})" == at(over, 1, 5, "a + -(${h})"));
      assert(expr"-(${max} + 1)" == at(over, 1, 8, "-(${h} + 1)"));
      assert(expr"${max} + 1" == at(over, 1, 6, "${h} + 1"));
      assert(expr"${min} - 1" == at(over, 1, 6, "${h} - 1"));
      assert(expr"${max} * -2" == at(over, 1, 6, "${h} * -2"));
      assert(expr"${min} * -1" == at(over, 1, 6, "${h} * -1"));
      assert(expr"abs(${min})" == at(over, 1, 1, "abs(${h})"));
      assert(expr"-CAST(${min} AS INTEGER)" == at(over, 1, 1, "-CAST(${h} AS INTEGE"));
      assert(expr"${1.0e308} * 10" == at(infinite, 1, 6, "${h} * 10"));
      assert(expr"-(${1.0e308} + ${1.0e308})" == at(infinite, 1, 8, "-(${h} + ${h})"));
      // Up to the limits, and anything with a column, pass.
      assert(expr"-${max}" == "-?");
      assert(expr"-(${min} + 1)" == "-(? + 1)");
      assert(expr"${min} % -1" == "? % -1");
      assert(expr"-(${min} % ${max})" == "-(? % ?)");
      assert(expr"a - ${min}" == "a - ?");
      assert(expr"-(a * ${max} * ${max})" == "-(a * ? * ?)");
      assert(expr"-(${1.0e308} - ${1.0e308})" == "-(? - ?)");
    }

## Depth

Nesting stops at 64 levels, counting parentheses, prefixes, and
operators, with a clear problem rather than a crash, however deep the
input goes.

    test("common expression depth") {
      // The sizes come from loops, since Temper would otherwise try to
      // run these deep parses while compiling.
      for (let n of [63, 64]) {
        let parens = "${repeated("(", n)}a${repeated(")", n)}";
        let nots = "${repeated("NOT ", n)}a";
        let signs = "${repeated("- ", n)}a";
        let sum = "a${repeated(" + a", n)}";
        if (n == 63) {
          assert(parseOnly(parens, false) == "a");
          assert(parseOnly(nots, false) == nots);
          assert(parseOnly(signs, false) == "${repeated("- ", n - 1)}-a");
          assert(parseOnly(sum, false) == sum);
        } else {
          assert(parseOnly(parens, false) == placed(parens, deepMessage, 65));
          assert(parseOnly(nots, false) == placed(nots, deepMessage, 257));
          assert(parseOnly(signs, false) == placed(signs, deepMessage, 129));
          assert(parseOnly(sum, false) == placed(sum, deepMessage, 255));
        }
      }
      // Chains and lists are flat, however long.
      for (let n of [300]) {
        let ors = "a${repeated(" OR a", n)}";
        assert(parseOnly(ors, false) == ors);
        let concat = "a${repeated(" || a", n)}";
        assert(parseOnly(concat, false) == concat);
        let list = "a IN (1${repeated(", 1", n)})";
        assert(parseOnly(list, false) == list);
      }
      for (let n of [10000]) {
        let hostile = repeated("(", n);
        assert(parseOnly(hostile, false) == placed(hostile, deepMessage, 65));
        let hostileNots = repeated("NOT ", n);
        assert(parseOnly(hostileNots, false) == placed(hostileNots, deepMessage, 257));
      }
    }

## Round trip

Random expressions, written with every operand in parentheses and
keywords in mixed case, print canonically to text that parses back to
the same tree.

    class Rng {
      private var state: Int = 2026;

      public next(n: Int): Int {
        state = (state * 1103 + 12345) % 65536;
        (state / 64) * n / 1024
      }
    }

    let pick(r: Rng, choices: List<String>): String { choices[r.next(choices.length)] }

    let leaves: List<String> = [
      "a", "t.b", "\"Q\"\"x\"", "count", "12", "007", "1.50", "'it''s'", "NULL", "TRUE", "false",
    ];

    let generated(r: Rng, depth: Int): String {
      if (depth == 0 || r.next(5) == 0) { return pick(r, leaves); }
      let a = "(${generated(r, depth - 1)})";
      let b = "(${generated(r, depth - 1)})";
      let c = "(${generated(r, depth - 1)})";
      when (r.next(16)) {
        0 -> "${a} ${pick(r, ["OR", "or", "AND", "And"])} ${b}";
        1 -> "NOT ${a}";
        2 -> "${a} ${pick(r, ["=", "<>", "!=", "<", "<=", ">", ">="])} ${b}";
        3 -> "${a} ${pick(r, ["+", "-", "*", "/", "%", "||"])} ${b}";
        4 -> "${pick(r, ["-", "+"])}${a}";
        5 -> "${a} IS ${pick(r, ["", "NOT "])}NULL";
        6 -> "${a} ${pick(r, ["", "NOT "])}IN (${b}, ${c})";
        7 -> "${a} ${pick(r, ["", "not "])}BETWEEN ${b} AND ${c}";
        8 -> "${a} ${pick(r, ["", "NOT "])}LIKE ${b} ESCAPE '!'";
        9 -> "CASE WHEN ${a} THEN ${b} ELSE ${c} END";
        10 -> "case ${a} when ${b} then ${c} end";
        11 -> "CAST(${a} AS ${pick(r, ["integer", "DOUBLE", "Text"])})";
        12 -> "coalesce(${a}, ${b}, ${c})";
        13 -> "SUBSTR(${a}, ${b})";
        14 -> "count(distinct ${a})";
        else -> "${a}${pick(r, [" ", "\n", " /* c */ ", "\t-- c\n"])}+${b}";
      }
    }

    test("common expression round trip") {
      let r = new Rng();
      for (var i = 0; i < 100; i += 1) {
        let text = generated(r, 4);
        let shape = parseOnly(text, true);
        let canonical = parseOnly(text, false);
        assert(parseOnly(canonical, false) == canonical) { "${text}: ${canonical}" }
        assert(parseOnly(canonical, true) == shape) { "${text}: ${shape}" }
      }
    }
