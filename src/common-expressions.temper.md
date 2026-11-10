# Common Expressions

Expressions in [the common dialect](common.temper.md): a parser that
reads the common lexer's tokens into a syntax tree, the checks an
expression alone can show, and a printer that writes the tree back as
canonical common SQL. [Statements](common-statements.temper.md) use
these for their columns, conditions, and values, and expressions hold
statements in turn, as subqueries; [rendering](common-rendering.temper.md)
for each database writes from the same tree.

The grammar, with keywords in any case:

```ebnf
expr      = or
or        = and {"OR" and}
and       = not {"AND" not}
not       = "NOT" not | predicate
predicate = concat [cmp concat | "IS" ["NOT"] "NULL"
            | ["NOT"] "IN" (subquery | "(" expr {"," expr} ")")
            | ["NOT"] "BETWEEN" concat "AND" concat
            | ["NOT"] "LIKE" concat ["ESCAPE" STRING]]
concat    = sum {"||" sum}
sum       = product {("+" | "-") product}
product   = unary {("*" | "/" | "%") unary}
unary     = ("-" | "+") unary | primary
primary   = INTEGER | DECIMAL | STRING | "NULL" | "TRUE" | "FALSE"
          | VALUE_HOLE | column | "(" expr ")" | subquery
          | "EXISTS" subquery | case | cast | call
subquery  = "(" (select | QUERY) ")"
case      = "CASE" [expr] ("WHEN" expr "THEN" expr)+ ["ELSE" expr] "END"
cast      = "CAST" "(" expr "AS" ("INTEGER" | "DOUBLE" | "TEXT") ")"
call      = "COUNT" "(" "*" ")" | FUNCTION "(" ["DISTINCT"] [expr {"," expr}] ")"
column    = name ["." name]
name      = BARE | QUOTED | NAME_HOLE
cmp       = "=" | "<>" | "!=" | "<" | "<=" | ">" | ">="
```

Where the databases read the same text differently, the parser
refuses it rather than pick one reading:

- **No chains:** a comparison, `IS`, `IN`, `BETWEEN`, or `LIKE` can't
  be the operand of another without parentheses (`a = b = c`, or
  `a = b IS NULL`), since the databases group them differently or
  refuse them.
- **`||` beside arithmetic** needs parentheses: SQLite reads
  `'a' || 1 + 2` as `('a' || 1) + 2`, PostgreSQL and DuckDB as
  `'a' || (1 + 2)`.
- **Names** have at most two parts (`t.c`), since DuckDB can read a
  third as a field, and a word used as a name must be lowercase, as a
  bare name must.
- **Functions:** `ABS`, `AVG`, `COALESCE` (2 or more arguments),
  `COUNT`, `LENGTH`, `LOWER`, `MAX`, `MIN`, `NULLIF`, `REPLACE`,
  `SUBSTR` (2 or 3), `SUM`, `TRIM` (1, since MySQL's second argument is
  a string to remove and the others' a set of characters), and
  `UPPER`. `DISTINCT` goes only in an aggregate (`AVG`, `COUNT`,
  `MAX`, `MIN`, and `SUM`), and `*` only in `COUNT(*)`.
- **Holes by kind:** a value goes wherever an expression does; a name
  only in a column (`${t}.${c}`); and a nested query, which must be a
  `SELECT`, only as `(${q})`, in `IN (${q})`, or after `EXISTS`, as a
  `SELECT` written in place may.
- **Depth:** nesting stops at 64 levels, counting parentheses,
  prefixes, and operators, so recursion is safe on every backend.

Problems give the line and column, as the lexer's do.

## The tree

Every node keeps a token, for problems: its operator or keyword, or
its first token. `depth` counts the levels under it, itself included.
Holes keep their place among the template's holes, so the tree doesn't
hold the values themselves.

    sealed interface CommonExpr {
      public get at(): CommonToken;
      public get depth(): Int;
    }

A literal: an integer, a decimal, a string, `NULL`, `TRUE`, or `FALSE`.

    class LiteralExpr(public at: CommonToken, public depth: Int, public literal: Int) extends CommonExpr {}

    let literalInteger = 1;
    let literalDecimal = 2;
    let literalString = 3;
    let literalNull = 4;
    let literalTrue = 5;
    let literalFalse = 6;

A value hole, and a column, `c` or `t.c`, each part a name or a name
hole.

    class ValueExpr(public at: CommonToken, public depth: Int, public hole: Int) extends CommonExpr {}

    class CommonName(public token: CommonToken, public hole: Int) {}

    class ColumnExpr(
      public at: CommonToken,
      public depth: Int,
      public table: CommonName?,
      public column: CommonName,
    ) extends CommonExpr {}

A subquery, `(SELECT …)` or `(${q})`, which `EXISTS` and `IN` take
too. A nested query's tokens are in the template's, so its tree is
here as if written in place.

    class SubqueryExpr(public at: CommonToken, public depth: Int, public query: SelectStatement) extends CommonExpr {}

    class ExistsExpr(public at: CommonToken, public depth: Int, public query: SubqueryExpr) extends CommonExpr {}

Operators: `NOT` and the signs take one operand; arithmetic and
comparisons two; and `AND`, `OR`, and `||` a chain.

    class UnaryExpr(public at: CommonToken, public depth: Int, public op: Int, public operand: CommonExpr) extends CommonExpr {}

    class BinaryExpr(
      public at: CommonToken,
      public depth: Int,
      public op: Int,
      public left: CommonExpr,
      public right: CommonExpr,
    ) extends CommonExpr {}

    class ChainExpr(public at: CommonToken, public depth: Int, public op: Int, public operands: List<CommonExpr>) extends CommonExpr {}

    let opOr = 1;
    let opAnd = 2;
    let opNot = 3;
    let opEq = 4;
    let opNe = 5;
    let opLt = 6;
    let opLe = 7;
    let opGt = 8;
    let opGe = 9;
    let opConcat = 10;
    let opAdd = 11;
    let opSub = 12;
    let opMul = 13;
    let opDiv = 14;
    let opMod = 15;
    let opNeg = 16;
    let opPos = 17;

    let opTexts: List<String> = [
      "", "OR", "AND", "NOT", "=", "<>", "<", "<=", ">", ">=", "||", "+", "-", "*", "/", "%", "-", "+",
    ];

The predicates.

    class IsNullExpr(public at: CommonToken, public depth: Int, public operand: CommonExpr, public negated: Boolean) extends CommonExpr {}

    class InListExpr(
      public at: CommonToken,
      public depth: Int,
      public operand: CommonExpr,
      public negated: Boolean,
      public items: List<CommonExpr>,
    ) extends CommonExpr {}

    class InQueryExpr(
      public at: CommonToken,
      public depth: Int,
      public operand: CommonExpr,
      public negated: Boolean,
      public query: SubqueryExpr,
    ) extends CommonExpr {}

    class BetweenExpr(
      public at: CommonToken,
      public depth: Int,
      public operand: CommonExpr,
      public negated: Boolean,
      public low: CommonExpr,
      public high: CommonExpr,
    ) extends CommonExpr {}

    class LikeExpr(
      public at: CommonToken,
      public depth: Int,
      public operand: CommonExpr,
      public negated: Boolean,
      public pattern: CommonExpr,
      // The ESCAPE string, if any.
      public escape: CommonToken?,
    ) extends CommonExpr {}

`CASE`, with a subject in its simple form, and `CAST`.

    class CaseExpr(
      public at: CommonToken,
      public depth: Int,
      public subject: CommonExpr?,
      public whens: List<CommonExpr>,
      public thens: List<CommonExpr>,
      public otherwise: CommonExpr?,
    ) extends CommonExpr {}

    class CastExpr(public at: CommonToken, public depth: Int, public operand: CommonExpr, public target: Int) extends CommonExpr {}

    let castInteger = 1;
    let castDouble = 2;
    let castText = 3;

    let castNames: List<String> = ["", "INTEGER", "DOUBLE", "TEXT"];

A function call. `COUNT(*)` is `COUNT` with no arguments.

    class CallExpr(
      public at: CommonToken,
      public depth: Int,
      public callee: Int,
      public distinct: Boolean,
      public args: List<CommonExpr>,
    ) extends CommonExpr {
      public static isAggregate(callee: Int): Boolean {
        callee == fnAvg || callee == fnCount || callee == fnMax || callee == fnMin || callee == fnSum
      }
    }

    let fnAbs = 1;
    let fnAvg = 2;
    let fnCoalesce = 3;
    let fnCount = 4;
    let fnLength = 5;
    let fnLower = 6;
    let fnMax = 7;
    let fnMin = 8;
    let fnNullif = 9;
    let fnReplace = 10;
    let fnSubstr = 11;
    let fnSum = 12;
    let fnTrim = 13;
    let fnUpper = 14;

    let functionNames: List<String> = [
      "", "ABS", "AVG", "COALESCE", "COUNT", "LENGTH", "LOWER", "MAX", "MIN", "NULLIF", "REPLACE",
      "SUBSTR", "SUM", "TRIM", "UPPER",
    ];

    let commonFunctions: Map<String, Int> = new Map([
      new Pair("abs", fnAbs), new Pair("avg", fnAvg), new Pair("coalesce", fnCoalesce),
      new Pair("count", fnCount), new Pair("length", fnLength), new Pair("lower", fnLower),
      new Pair("max", fnMax), new Pair("min", fnMin), new Pair("nullif", fnNullif),
      new Pair("replace", fnReplace), new Pair("substr", fnSubstr), new Pair("sum", fnSum),
      new Pair("trim", fnTrim), new Pair("upper", fnUpper),
    ]);

How deep an expression may nest.

    let maxDepth = 64;
    let deepMessage = "expression nested more than 64 deep";

## The parser

A recursive-descent parser over a lexer's tokens, once the lexer has
read the whole template without a problem. It bubbles on the first
problem, which `problem` then gives, placed as the lexer places its
own. Its token helpers are public for the
[statement parser](common-statements.temper.md), which works on the
same tokens.

    class CommonParser(public lexer: CommonLexer) {
      private var pos: Int = 0;
      // Value and name holes taken so far.
      public var holes: Int = 0;
      public var nesting: Int = 0;
      // The arithmetic operator outside parentheses in the operand just
      // read, if any, since `||` beside one needs parentheses.
      private var bareAt: CommonToken? = null;
      public var problem: String? = null;

`parseExpression` reads the whole template as one expression.

      public parseExpression(): CommonExpr throws Bubble {
        let e = expression();
        let t = peek();
        if (t != null) {
          if (isSymbol(t, char')')) { report("unmatched )", t); }
          report("expected the end of the expression", t);
          bubble()
        }
        e
      }

`parseStatement` reads the whole template as one statement.

      public parseStatement(): CommonStatement throws Bubble {
        new StatementParser(this).whole()
      }

      public expression(): CommonExpr throws Bubble {
        enter();
        let e = disjunction();
        nesting -= 1;
        e
      }

      private disjunction(): CommonExpr throws Bubble {
        let first = conjunction();
        if (!isKeyword(peek(), "or")) { return first; }
        let at = advance();
        let operands = new ListBuilder<CommonExpr>();
        operands.add(first);
        var depth = first.depth;
        while (true) {
          let next = conjunction();
          operands.add(next);
          depth = larger(depth, next.depth);
          if (!isKeyword(peek(), "or")) { break; }
          advance();
        }
        deep(new ChainExpr(at, depth + 1, opOr, operands.toList()))
      }

      private conjunction(): CommonExpr throws Bubble {
        let first = negation();
        if (!isKeyword(peek(), "and")) { return first; }
        let at = advance();
        let operands = new ListBuilder<CommonExpr>();
        operands.add(first);
        var depth = first.depth;
        while (true) {
          let next = negation();
          operands.add(next);
          depth = larger(depth, next.depth);
          if (!isKeyword(peek(), "and")) { break; }
          advance();
        }
        deep(new ChainExpr(at, depth + 1, opAnd, operands.toList()))
      }

      private negation(): CommonExpr throws Bubble {
        if (!isKeyword(peek(), "not")) { return predicate(); }
        let at = advance();
        enter();
        let operand = negation();
        nesting -= 1;
        deep(new UnaryExpr(at, operand.depth + 1, opNot, operand))
      }

A predicate: at most one comparison, `IS`, `IN`, `BETWEEN`, or `LIKE`.

      private predicate(): CommonExpr throws Bubble {
        let left = concatenation();
        if (peek() == null) { return left; }
        let t = lexer.tokens[pos];
        let op = comparison(t);
        var e = left;
        if (op >= opEq && op <= opGe) {
          advance();
          let right = concatenation();
          e = new BinaryExpr(t, larger(left.depth, right.depth) + 1, op, left, right);
        } else if (isKeyword(t, "is")) {
          advance();
          let negated = isKeyword(peek(), "not");
          if (negated) { advance(); }
          if (!isKeyword(peek(), "null")) { report("expected NULL", peek()); bubble() }
          advance();
          e = new IsNullExpr(t, left.depth + 1, left, negated);
        } else {
          let negated = isKeyword(t, "not");
          if (negated) {
            if (!negatable(peekAt(1))) { report("expected IN, BETWEEN, or LIKE after NOT", peekAt(1)); bubble() }
            advance();
          }
          let word = peek();
          if (isKeyword(word, "in")) {
            advance();
            e = inPredicate(t, left, negated);
          } else if (isKeyword(word, "between")) {
            advance();
            let low = concatenation();
            if (!isKeyword(peek(), "and")) { report("expected AND", peek()); bubble() }
            advance();
            let high = concatenation();
            let depth = larger(left.depth, larger(low.depth, high.depth)) + 1;
            e = new BetweenExpr(t, depth, left, negated, low, high);
          } else if (isKeyword(word, "like")) {
            advance();
            let pattern = concatenation();
            var escape: CommonToken? = null;
            if (isKeyword(peek(), "escape")) {
              advance();
              let s = peek();
              if (s == null || s.kind != tokenString) { report("expected a string after ESCAPE", s); bubble() }
              escape = advance();
            }
            e = new LikeExpr(t, larger(left.depth, pattern.depth) + 1, left, negated, pattern, escape);
          } else if (isKeyword(word, "ilike")) {
            report("ILIKE isn't common SQL", word);
            bubble()
          } else {
            return left;
          }
        }
        let after = peek();
        if (startsPredicate(after)) { report("comparisons don't chain; add parentheses", after); bubble() }
        deep(e)
      }

`IN`, after the keyword: a nested query, or a list.

      private inPredicate(at: CommonToken, left: CommonExpr, negated: Boolean): CommonExpr throws Bubble {
        expectSymbol(char'(');
        if (startsQuery(peek())) {
          let query = subquery();
          return new InQueryExpr(at, larger(left.depth, query.depth) + 1, left, negated, query);
        }
        let items = new ListBuilder<CommonExpr>();
        var depth = left.depth;
        while (true) {
          let item = expression();
          items.add(item);
          depth = larger(depth, item.depth);
          if (!isSymbol(peek(), char',')) { break; }
          advance();
        }
        expectSymbol(char')');
        new InListExpr(at, depth + 1, left, negated, items.toList())
      }

`||` chains, refusing an arithmetic operand outside parentheses.

      private concatenation(): CommonExpr throws Bubble {
        let first = sum();
        if (comparison(peek()) != opConcat) { return first; }
        let at = advance();
        tightBeside();
        let operands = new ListBuilder<CommonExpr>();
        operands.add(first);
        var depth = first.depth;
        while (true) {
          let next = sum();
          tightBeside();
          operands.add(next);
          depth = larger(depth, next.depth);
          if (comparison(peek()) != opConcat) { break; }
          advance();
        }
        deep(new ChainExpr(at, depth + 1, opConcat, operands.toList()))
      }

      private tightBeside(): Void throws Bubble {
        let bare = bareAt;
        if (bare != null) {
          report("arithmetic beside || needs parentheses; databases group them differently", bare);
          bubble()
        }
      }

      private sum(): CommonExpr throws Bubble {
        var e = product();
        var bare = bareAt;
        while (true) {
          let op = comparison(peek());
          if (op != opAdd && op != opSub) { break; }
          let t = advance();
          let right = product();
          e = deep(new BinaryExpr(t, larger(e.depth, right.depth) + 1, op, e, right));
          bare = t;
        }
        bareAt = bare;
        e
      }

      private product(): CommonExpr throws Bubble {
        var e = unary();
        var bare: CommonToken? = null;
        while (true) {
          let op = comparison(peek());
          if (op != opMul && op != opDiv && op != opMod) { break; }
          let t = advance();
          let right = unary();
          e = deep(new BinaryExpr(t, larger(e.depth, right.depth) + 1, op, e, right));
          bare = t;
        }
        bareAt = bare;
        e
      }

      private unary(): CommonExpr throws Bubble {
        let op = comparison(peek());
        if (op != opSub && op != opAdd) { return primary(); }
        let t = advance();
        enter();
        let operand = unary();
        nesting -= 1;
        deep(new UnaryExpr(t, operand.depth + 1, if (op == opSub) { opNeg } else { opPos }, operand))
      }

      private primary(): CommonExpr throws Bubble {
        let t = need("expected an expression");
        let kind = t.kind;
        if (kind == tokenInteger || kind == tokenDecimal || kind == tokenString) {
          advance();
          let literal = if (kind == tokenInteger) {
            literalInteger
          } else if (kind == tokenDecimal) {
            literalDecimal
          } else {
            literalString
          };
          return new LiteralExpr(t, 1, literal);
        }
        if (kind == tokenValueHole) {
          if (isSymbol(peekAt(1), char'.')) { report("value where a name goes", t); bubble() }
          advance();
          return new ValueExpr(t, 1, holes - 1);
        }
        if (kind == tokenName || kind == tokenQuotedName || kind == tokenWord || kind == tokenNameHole) {
          if (isSymbol(peekAt(1), char'(')) { return call(); }
          return column();
        }
        if (kind == tokenQueryStart) {
          report("nested query needs its own parentheses", t);
          bubble()
        }
        if (isSymbol(t, char'(')) {
          advance();
          if (startsQuery(peek())) { return subquery(); }
          let e = expression();
          expectSymbol(char')');
          return e;
        }
        let word = t.word;
        if (kind == tokenKeyword) {
          if (word == "null" || word == "true" || word == "false") {
            advance();
            let literal = if (word == "null") {
              literalNull
            } else if (word == "true") {
              literalTrue
            } else {
              literalFalse
            };
            return new LiteralExpr(t, 1, literal);
          }
          if (word == "case") { return caseExpr(); }
          if (word == "cast") { return castExpr(); }
          if (word == "exists") {
            advance();
            expectSymbol(char'(');
            let inner = peek();
            if (!startsQuery(inner)) { report("expected SELECT or a nested query", inner); bubble() }
            let query = subquery();
            return deep(new ExistsExpr(t, query.depth + 1, query));
          }
          if (word == "not") {
            report("NOT here needs parentheses", t);
            bubble()
          }
          if (word == "select") {
            report("a subquery needs its own parentheses", t);
            bubble()
          }
        }
        report("expected an expression", t);
        bubble()
      }

A subquery, just after its `(`: a `SELECT`, or a nested query, which
must be one, alone in the parentheses.

      public subquery(): SubqueryExpr throws Bubble {
        let t = need("expected SELECT or a nested query");
        enter();
        let statements = new StatementParser(this);
        let query = if (t.kind == tokenQueryStart) { statements.nestedSelect() } else { statements.select() };
        nesting -= 1;
        let close = peek();
        if (!isSymbol(close, char')')) {
          if (t.kind == tokenQueryStart) {
            report("nested query needs its own parentheses", t);
          } else {
            report("expected )", close);
          }
          bubble()
        }
        advance();
        let e = new SubqueryExpr(t, query.depth + 1, query);
        if (e.depth > maxDepth) { report(deepMessage, t); bubble() }
        e
      }

      public startsQuery(t: CommonToken?): Boolean {
        t != null && (t.kind == tokenQueryStart || isKeyword(t, "select"))
      }

      private column(): CommonExpr throws Bubble {
        let first = name();
        if (!isSymbol(peek(), char'.')) { return new ColumnExpr(first.token, 1, null, first); }
        advance();
        let second = name();
        let dot = peek();
        if (isSymbol(dot, char'.')) { report("name with more than two parts", dot); bubble() }
        new ColumnExpr(first.token, 1, first, second)
      }

      public name(): CommonName throws Bubble {
        let t = need("expected a name");
        let kind = t.kind;
        if (kind != tokenName && kind != tokenQuotedName && kind != tokenWord && kind != tokenNameHole) {
          let message = if (kind == tokenValueHole) {
            "value where a name goes"
          } else if (kind == tokenQueryStart) {
            "nested query where a name goes"
          } else {
            "expected a name"
          };
          report(message, t);
          bubble()
        }
        if (kind == tokenWord && lexer.tokenText(t) != t.word) {
          report("bare name not lowercase; quote it to keep its case", t);
          bubble()
        }
        advance();
        new CommonName(t, if (kind == tokenNameHole) { holes - 1 } else { -1 })
      }

      private call(): CommonExpr throws Bubble {
        let t = advance();
        let callee = if (t.kind == tokenWord) { commonFunctions.getOr(t.word, 0) } else { 0 };
        if (callee == 0) {
          report("unknown function ${lexer.tokenText(t)}", t);
          bubble()
        }
        advance();
        let args = new ListBuilder<CommonExpr>();
        if (callee == fnCount && isSymbol(peek(), char'*')) {
          advance();
          expectSymbol(char')');
          return new CallExpr(t, 1, callee, false, args.toList());
        }
        let d = peek();
        let distinct = isKeyword(d, "distinct");
        if (distinct) {
          if (!CallExpr.isAggregate(callee)) { report("DISTINCT outside an aggregate", d); bubble() }
          advance();
        }
        var depth = 0;
        if (!isSymbol(peek(), char')')) {
          while (true) {
            let arg = expression();
            args.add(arg);
            depth = larger(depth, arg.depth);
            if (!isSymbol(peek(), char',')) { break; }
            advance();
          }
        }
        expectSymbol(char')');
        let most = mostArgs(callee);
        if (args.length < fewestArgs(callee) || (most >= 0 && args.length > most)) {
          report("${functionNames[callee]} takes ${arityText(callee)}", t);
          bubble()
        }
        deep(new CallExpr(t, depth + 1, callee, distinct, args.toList()))
      }

      private caseExpr(): CommonExpr throws Bubble {
        let t = advance();
        var depth = 0;
        var subject: CommonExpr? = null;
        if (!isKeyword(peek(), "when")) {
          let s = expression();
          subject = s;
          depth = s.depth;
        }
        if (!isKeyword(peek(), "when")) { report("expected WHEN", peek()); bubble() }
        let whens = new ListBuilder<CommonExpr>();
        let thens = new ListBuilder<CommonExpr>();
        while (isKeyword(peek(), "when")) {
          advance();
          let w = expression();
          if (!isKeyword(peek(), "then")) { report("expected THEN", peek()); bubble() }
          advance();
          let r = expression();
          whens.add(w);
          thens.add(r);
          depth = larger(depth, larger(w.depth, r.depth));
        }
        var otherwise: CommonExpr? = null;
        if (isKeyword(peek(), "else")) {
          advance();
          let o = expression();
          otherwise = o;
          depth = larger(depth, o.depth);
        }
        if (!isKeyword(peek(), "end")) { report("expected END", peek()); bubble() }
        advance();
        deep(new CaseExpr(t, depth + 1, subject, whens.toList(), thens.toList(), otherwise))
      }

      private castExpr(): CommonExpr throws Bubble {
        let t = advance();
        expectSymbol(char'(');
        let operand = expression();
        if (!isKeyword(peek(), "as")) { report("expected AS", peek()); bubble() }
        advance();
        let named = peek();
        var target = 0;
        if (named != null) {
          let w = if (named.kind == tokenWord) { named.word } else { "" };
          target = if (w == "integer") {
            castInteger
          } else if (w == "double") {
            castDouble
          } else if (w == "text") {
            castText
          } else {
            0
          };
        }
        if (target == 0) { report("expected INTEGER, DOUBLE, or TEXT", named); bubble() }
        advance();
        expectSymbol(char')');
        deep(new CastExpr(t, operand.depth + 1, operand, target))
      }

### Tokens

      public peek(): CommonToken? { peekAt(0) }

`need` gives the next token, or bubbles with a message at the end.

      public need(message: String): CommonToken throws Bubble {
        let t = peek();
        if (t != null) { return t; }
        report(message, null);
        bubble()
      }

      public peekAt(ahead: Int): CommonToken? {
        let tokens = lexer.tokens;
        if (pos + ahead < tokens.length) { tokens[pos + ahead] } else { null }
      }

      public advance(): CommonToken {
        let t = lexer.tokens[pos];
        pos += 1;
        if (t.kind == tokenValueHole || t.kind == tokenNameHole) { holes += 1; }
        t
      }

      public isKeyword(t: CommonToken?, word: String): Boolean {
        t != null && t.kind == tokenKeyword && t.word == word
      }

      public isSymbol(t: CommonToken?, c: Int): Boolean {
        t != null && t.kind == tokenSymbol && lexer.runs[t.run][t.begin] == c
      }

`comparison` gives the operator a symbol is, comparisons and
arithmetic both, or 0.

      private comparison(t: CommonToken?): Int {
        if (t != null) {
          if (t.kind == tokenSymbol) { return operatorOf(t); }
        }
        0
      }

      private operatorOf(t: CommonToken): Int {
        let text = lexer.runs[t.run];
        let c = text[t.begin];
        let next = text.next(t.begin);
        if (next < t.end) {
          let d = text[next];
          return if (c == char'<' && d == char'=') {
            opLe
          } else if (c == char'<' || c == char'!') {
            opNe
          } else if (c == char'>') {
            opGe
          } else {
            opConcat
          };
        }
        if (c == char'=') {
          opEq
        } else if (c == char'<') {
          opLt
        } else if (c == char'>') {
          opGt
        } else if (c == char'+') {
          opAdd
        } else if (c == char'-') {
          opSub
        } else if (c == char'*') {
          opMul
        } else if (c == char'/') {
          opDiv
        } else if (c == char'%') {
          opMod
        } else {
          0
        }
      }

Whether a token starts a predicate, which can't follow another.

      private startsPredicate(t: CommonToken?): Boolean {
        let op = comparison(t);
        (op >= opEq && op <= opGe) || isKeyword(t, "is") || negatable(t) ||
          (isKeyword(t, "not") && negatable(peekAt(1)))
      }

      private negatable(t: CommonToken?): Boolean {
        isKeyword(t, "in") || isKeyword(t, "between") || isKeyword(t, "like")
      }

      public expectSymbol(c: Int): Void throws Bubble {
        let t = peek();
        if (!isSymbol(t, c)) {
          report("expected ${shown(c)}", t);
          bubble()
        }
        advance();
      }

### Depth and problems

      public enter(): Void throws Bubble {
        nesting += 1;
        if (nesting > maxDepth) {
          report(deepMessage, peek());
          bubble()
        }
      }

      private deep(e: CommonExpr): CommonExpr throws Bubble {
        if (e.depth > maxDepth) {
          report(deepMessage, e.at);
          bubble()
        }
        e
      }

`report` places a problem at a token, or at the end for none.

      public report(message: String, t: CommonToken?): Void {
        if (problem != null) { return; }
        problem = if (t != null) {
          lexer.located(message, t.line, t.column, t.offset)
        } else {
          lexer.locate(message)
        };
      }

      private larger(a: Int, b: Int): Int { if (a > b) { a } else { b } }

How many arguments each function takes, and how a problem says so.

      private fewestArgs(callee: Int): Int {
        if (callee == fnCoalesce || callee == fnNullif || callee == fnSubstr) {
          2
        } else if (callee == fnReplace) {
          3
        } else {
          1
        }
      }

      private mostArgs(callee: Int): Int {
        if (callee == fnCoalesce) {
          -1
        } else if (callee == fnNullif) {
          2
        } else if (callee == fnReplace || callee == fnSubstr) {
          3
        } else {
          1
        }
      }

      private arityText(callee: Int): String {
        if (callee == fnCoalesce) {
          "2 or more arguments"
        } else if (callee == fnNullif) {
          "2 arguments"
        } else if (callee == fnSubstr) {
          "2 or 3 arguments"
        } else if (callee == fnReplace) {
          "3 arguments"
        } else {
          "1 argument"
        }
      }
    }

## Checks

What an expression shows about whether it means the same on every
database, given the values in its holes. Subqueries are checked as
[statements](common-statements.temper.md) are. Kinds are what the text
and values show: a literal's, a value's, or an operator's result, and
unknown for columns and nested queries. The checker refuses:

- **Kinds that databases convert differently:** text or a boolean in
  arithmetic, a number or text where a condition goes, comparing a
  number, text, or boolean with another of those, `CASE` results or
  `COALESCE` arguments of different kinds, a number in `LIKE` or a text
  function, text in `ABS`, `AVG`, or `SUM`, and a boolean in `||` or
  in any function but `COALESCE`, `COUNT`, and `NULLIF`.
  PostgreSQL and DuckDB refuse most of these, while SQLite and MySQL
  convert.
- **Division:** `/` without a float operand (a float value, a decimal,
  `AVG`, or a `CAST` to `DOUBLE`, or arithmetic on one), since SQLite
  and PostgreSQL divide integers to an integer; `%` with a float,
  which SQLite truncates; and `/` or `%` by a literal zero, which
  gives `NULL`, an error, or infinity.
- **Floats written as text:** a float in `||` or cast to `TEXT`, which
  the databases write differently (`1.0` or `1`, say), and a float cast
  to `INTEGER`, which SQLite truncates and the others round.
- **Casts:** of a boolean, and of a string that isn't a plain number to
  `INTEGER` or `DOUBLE`.
- **`NULL`:** a comparison with `NULL`, `NULL` in an `IN` list, or
  `WHEN NULL` in a simple `CASE`, which are never true; use `IS NULL`.
  A value hole holding null counts the same as `NULL` written in the
  text, since every value is known when the query is built:
  `a = ${null}` is refused, while `COALESCE(${null}, a)` is fine.
- **`LIKE`:** without `ESCAPE`, only a literal pattern, since
  PostgreSQL and MySQL read `\` in it as an escape and SQLite and
  DuckDB don't; with it, one character other than `'`, `%`, or `_`,
  and in a literal pattern, only before `%`, `_`, or itself.
- **`SUBSTR`** with a literal start below 1 or a negative length, and a
  float for either.
- **An aggregate inside an aggregate.**

Narrower [targets](query.temper.md#querybuilder) relax the checks that
are there because databases differ, when the targets left all read the
construct alike; the traps (`NULL` that never matches, `ESCAPE`
misused, and aggregates in aggregates) apply to every target. Each
rule gives a letter per profile, in the order `sqlite`, `postgres`,
`mysql`, `mysqlNoBackslashEscapes`, and `duckdb`; profiles with the
same letter read it alike, and the check applies only to targets with
different letters. Kinds that databases convert differently differ
everywhere, but for the two MySQL profiles; the rest:

| Rule | Letters | Why |
| --- | --- | --- |
| `/` without a float | `aabbc` | SQLite and PostgreSQL divide integers to an integer |
| A boolean in `\|\|` | `abaab` | `1` in SQLite and MySQL, `true` in the others |
| `LIKE` without `ESCAPE`, on a value or a `\` | `abbaa` | `\` escapes in PostgreSQL and MySQL, but not under `NO_BACKSLASH_ESCAPES` |
| `SUBSTR` start below 1 or length below 0 | `abcca` | SQLite and DuckDB agree |

    let ruleKinds = "abccd";
    let ruleDivision = "aabbc";
    let ruleBooleanText = "abaab";
    let ruleLikeEscape = "abbaa";
    let ruleSubstr = "abcca";

The kinds:

    let kindUnknown = 0;
    let kindNull = 1;
    let kindBoolean = 2;
    let kindInteger = 3;
    let kindFloat = 4;
    let kindText = 5;

The checker takes the template's holes, as a `QueryParam` or a
`QueryName` each, and the target databases, which the statement checks
need.

    class CommonChecker(
      public lexer: CommonLexer,
      public holes: List<QueryPart>,
      public targets: List<Dialect>,
    ) {
      // Aggregates around the expression being checked.
      public var aggregates: Int = 0;
      public var problem: String? = null;

`check` gives an expression's kind, or bubbles with `problem`.

      public check(e: CommonExpr): Int throws Bubble {
        when (e) {
          is LiteralExpr -> do {
            let literal = e.literal;
            if (literal == literalInteger) {
              kindInteger
            } else if (literal == literalDecimal) {
              kindFloat
            } else if (literal == literalString) {
              kindText
            } else if (literal == literalNull) {
              kindNull
            } else {
              kindBoolean
            }
          };
          is ValueExpr -> valueKind(e.hole);
          is SubqueryExpr -> new StatementChecker(this).subquery(e.query);
          is ExistsExpr -> do {
            check(e.query);
            kindBoolean
          };
          is UnaryExpr -> do {
            let k = check(e.operand);
            if (e.op == opNot) {
              condition(k, e.operand);
              kindBoolean
            } else {
              arithmetic(k, e.operand);
              if (k == kindInteger || k == kindFloat) { k } else { kindUnknown }
            }
          };
          is BinaryExpr -> binary(e);
          is ChainExpr -> chain(e);
          is IsNullExpr -> do {
            check(e.operand);
            kindBoolean
          };
          is InListExpr -> do {
            let k = check(e.operand);
            let items = e.items;
            for (let item of items) {
              if (isLiteral(item, literalNull)) { fail("NULL in an IN list never matches; use IS NULL", item.at); }
              if (isNullValue(item)) { fail("a null value in an IN list never matches; use IS NULL", item.at); }
              compare(k, check(item), item.at);
            }
            kindBoolean
          };
          is InQueryExpr -> do {
            let k = check(e.operand);
            let query = e.query;
            compare(k, check(query), query.at);
            new StatementChecker(this).inSubquery(query.query);
            kindBoolean
          };
          is BetweenExpr -> do {
            let k = check(e.operand);
            compare(k, check(e.low), e.low.at);
            compare(k, check(e.high), e.high.at);
            kindBoolean
          };
          is LikeExpr -> like(e);
          is CaseExpr -> caseKind(e);
          is CastExpr -> cast(e);
          is CallExpr -> call(e);
          else -> kindUnknown;
        }
      }

      public valueKind(hole: Int): Int {
        let value = holeValue(hole);
        when (value) {
          is SqlText -> kindText;
          is SqlInt -> kindInteger;
          is SqlFloat -> kindFloat;
          is SqlBool -> kindBoolean;
          else -> kindUnknown;
        }
      }

`holeValue` is a value hole's value, and `nameText` a name's text,
written or from its hole.

      public holeValue(hole: Int): SqlValue? {
        if (hole < 0 || hole >= holes.length) { return null; }
        let part = holes[hole];
        if (part is QueryParam) { part.value } else { null }
      }

      public nameText(n: CommonName): String {
        if (n.hole >= 0 && n.hole < holes.length) {
          let part = holes[n.hole];
          if (part is QueryName) { return part.name.name; }
        }
        lexer.nameValue(n.token)
      }

Comparisons and arithmetic.

      private binary(e: BinaryExpr): Int throws Bubble {
        let op = e.op;
        let left = check(e.left);
        let right = check(e.right);
        if (op >= opEq && op <= opGe) {
          if (isLiteral(e.left, literalNull) || isLiteral(e.right, literalNull)) {
            let shown = lexer.tokenText(e.at);
            let hint = if (op == opEq) { "; use IS NULL" } else if (op == opNe) { "; use IS NOT NULL" } else { "" };
            fail("${shown} NULL is never true${hint}", e.at);
          }
          if (isNullValue(e.left) || isNullValue(e.right)) {
            let shown = lexer.tokenText(e.at);
            let hint = if (op == opEq) { "; use IS NULL" } else if (op == opNe) { "; use IS NOT NULL" } else { "" };
            fail("${shown} with a null value is never true${hint}", e.at);
          }
          compare(left, right, e.at);
          return kindBoolean;
        }
        arithmetic(left, e.left);
        arithmetic(right, e.right);
        let float = left == kindFloat || right == kindFloat;
        if (op == opDiv || op == opMod) {
          if (op == opDiv && !float && varies(ruleDivision)) {
            fail("/ without a float operand; databases divide integers differently", e.at);
          }
          if (op == opMod && float && varies(ruleKinds)) { fail("% of a float; SQLite truncates it to an integer", e.at); }
          if (literalSign(e.right) == 0 && varies(ruleKinds)) { fail("${opTexts[op]} by zero; databases differ", e.at); }
        }
        if (op == opDiv || float) {
          kindFloat
        } else if (left == kindInteger && right == kindInteger) {
          kindInteger
        } else {
          kindUnknown
        }
      }

`AND`, `OR`, and `||`.

      private chain(e: ChainExpr): Int throws Bubble {
        let operands = e.operands;
        for (let operand of operands) {
          let k = check(operand);
          if (e.op != opConcat) {
            condition(k, operand);
          } else if (k == kindBoolean && varies(ruleBooleanText)) {
            fail("a boolean in ||; databases write booleans differently", operand.at);
          } else if (k == kindFloat && varies(ruleKinds)) {
            fail("a float in ||; databases write floats differently", operand.at);
          }
        }
        if (e.op == opConcat) { kindText } else { kindBoolean }
      }

      private like(e: LikeExpr): Int throws Bubble {
        textual(check(e.operand), e.operand, "LIKE");
        textual(check(e.pattern), e.pattern, "LIKE");
        let pattern = e.pattern;
        let escape = e.escape;
        let literal: String? = if (pattern is LiteralExpr && pattern.literal == literalString) {
          lexer.stringValue(pattern.at)
        } else {
          null
        };
        if (escape != null) {
          escaped(escape, literal, pattern);
        } else if (varies(ruleLikeEscape)) {
          if (literal == null) {
            fail("LIKE without ESCAPE takes only a literal pattern", pattern.at);
          } else if (hasCodePoint(literal, char'\\')) {
            fail("\\ in a LIKE pattern without ESCAPE; databases differ", pattern.at);
          }
        }
        kindBoolean
      }

`escaped` checks an `ESCAPE` string, and a literal pattern's escapes.

      private escaped(escape: CommonToken, literal: String?, pattern: CommonExpr): Void throws Bubble {
        let esc = lexer.stringValue(escape);
        let c = if (esc.isEmpty) { -1 } else { esc[String.begin] };
        if (c < 0 || esc.next(String.begin) < esc.end) { fail("ESCAPE takes one character", escape); }
        if (c == char'\'' || c == char'%' || c == char'_') {
          fail("${shown(c)} can't be the escape character", escape);
        }
        if (literal != null) {
          var i = String.begin;
          while (literal.hasIndex(i)) {
            if (literal[i] == c) {
              let next = literal.next(i);
              let d = if (literal.hasIndex(next)) { literal[next] } else { -1 };
              if (d != char'%' && d != char'_' && d != c) {
                fail("escape character not before %, _, or itself", pattern.at);
              }
              i = next;
            }
            i = literal.next(i);
          }
        }
      }

      private caseKind(e: CaseExpr): Int throws Bubble {
        let subject = e.subject;
        let subjectKind = if (subject != null) { check(subject) } else { kindUnknown };
        let whens = e.whens;
        let thens = e.thens;
        let kinds = new ListBuilder<Int>();
        let results = new ListBuilder<CommonExpr>();
        for (var i = 0; i < whens.length; i += 1) {
          let w = whens[i];
          if (subject != null) {
            if (isLiteral(w, literalNull)) { fail("WHEN NULL never matches; use WHEN x IS NULL", w.at); }
            if (isNullValue(w)) { fail("WHEN with a null value never matches; use WHEN x IS NULL", w.at); }
            compare(subjectKind, check(w), w.at);
          } else {
            condition(check(w), w);
          }
          kinds.add(check(thens[i]));
          results.add(thens[i]);
        }
        let otherwise = e.otherwise;
        if (otherwise != null) {
          kinds.add(check(otherwise));
          results.add(otherwise);
        }
        mixed(kinds, results, "CASE")
      }

      private cast(e: CastExpr): Int throws Bubble {
        let k = check(e.operand);
        let target = e.target;
        let differ = varies(ruleKinds);
        if (k == kindBoolean && differ) { fail("CAST of a boolean; databases convert booleans differently", e.at); }
        if (k == kindFloat && target == castInteger && differ) {
          fail("CAST of a float to INTEGER; SQLite truncates, the others round", e.at);
        }
        if (k == kindFloat && target == castText && differ) {
          fail("CAST of a float to TEXT; databases write floats differently", e.at);
        }
        let operand = e.operand;
        if (operand is LiteralExpr && operand.literal == literalString && target != castText && differ) {
          if (!plainNumber(lexer.stringValue(operand.at), target == castDouble)) {
            fail("CAST of a string that isn't a plain number", e.at);
          }
        }
        if (target == castInteger) { kindInteger } else if (target == castDouble) { kindFloat } else { kindText }
      }

      private call(e: CallExpr): Int throws Bubble {
        let callee = e.callee;
        let args = e.args;
        let name = functionNames[callee];
        let aggregate = CallExpr.isAggregate(callee);
        if (aggregate) {
          if (aggregates > 0) { fail("aggregate inside an aggregate", e.at); }
          aggregates += 1;
        }
        let kinds = new ListBuilder<Int>();
        let exprs = new ListBuilder<CommonExpr>();
        for (let arg of args) {
          kinds.add(check(arg));
          exprs.add(arg);
        }
        if (aggregate) { aggregates -= 1; }
        if (callee == fnCount) { return kindInteger; }
        if (callee == fnCoalesce) { return mixed(kinds, exprs, name); }
        let first = kinds[0];
        if (callee == fnNullif) {
          compare(first, kinds[1], args[1].at);
          return known(first);
        }
        if (callee == fnMin || callee == fnMax) {
          if (first == kindBoolean && varies(ruleKinds)) { fail("a boolean in ${name}", args[0].at); }
          return known(first);
        }
        if (callee == fnAbs || callee == fnAvg || callee == fnSum) {
          numeric(first, args[0], name);
          return if (callee == fnAvg || first == kindFloat) {
            kindFloat
          } else if (callee == fnAbs && first == kindInteger) {
            kindInteger
          } else {
            kindUnknown
          };
        }
        textual(first, args[0], name);
        if (callee == fnReplace) {
          textual(kinds[1], args[1], name);
          textual(kinds[2], args[2], name);
        }
        if (callee == fnSubstr) {
          for (var i = 1; i < args.length; i += 1) {
            let k = kinds[i];
            if (k != kindInteger && k != kindUnknown && k != kindNull && varies(ruleKinds)) {
              fail("${described(k)} in SUBSTR", args[i].at);
            }
          }
          if (literalSign(args[1]) <= 0 && varies(ruleSubstr)) { fail("SUBSTR start below 1; databases differ", args[1].at); }
          if (args.length > 2 && literalSign(args[2]) < 0 && varies(ruleSubstr)) {
            fail("SUBSTR length below 0; databases differ", args[2].at);
          }
        }
        if (callee == fnLength) { kindInteger } else { kindText }
      }

### Kinds

      public condition(k: Int, e: CommonExpr): Void throws Bubble {
        if ((k == kindInteger || k == kindFloat || k == kindText) && varies(ruleKinds)) {
          fail("${described(k)} where a condition goes", e.at);
        }
      }

      private arithmetic(k: Int, e: CommonExpr): Void throws Bubble {
        if ((k == kindBoolean || k == kindText) && varies(ruleKinds)) { fail("${described(k)} in arithmetic", e.at); }
      }

      private numeric(k: Int, e: CommonExpr, name: String): Void throws Bubble {
        if ((k == kindBoolean || k == kindText) && varies(ruleKinds)) { fail("${described(k)} in ${name}", e.at); }
      }

      private textual(k: Int, e: CommonExpr, name: String): Void throws Bubble {
        if ((k == kindBoolean || k == kindInteger || k == kindFloat) && varies(ruleKinds)) {
          fail("${described(k)} in ${name}", e.at);
        }
      }

      private compare(a: Int, b: Int, at: CommonToken): Void throws Bubble {
        let x = family(a);
        let y = family(b);
        if (x != 0 && y != 0 && x != y && varies(ruleKinds)) { fail("comparing ${described(a)} with ${described(b)}", at); }
      }

`mixed` is the kind of results that may be any of several, as `CASE`
and `COALESCE` give, refusing kinds that differ.

      private mixed(kinds: ListBuilder<Int>, exprs: ListBuilder<CommonExpr>, name: String): Int throws Bubble {
        var first = kindNull;
        var result = kindNull;
        for (var i = 0; i < kinds.length; i += 1) {
          let k = kinds[i];
          let f = family(k);
          if (f != 0) {
            let g = family(first);
            if (g == 0) {
              first = k;
            } else if (g != f && varies(ruleKinds)) {
              fail("${name} mixes ${described(first)} and ${described(k)}", exprs[i].at);
            }
          }
          result = if (result == kindNull) {
            k
          } else if (k == kindNull || k == result) {
            result
          } else if (f == 1 && family(result) == 1) {
            kindFloat
          } else {
            kindUnknown
          };
        }
        result
      }

      public fail(message: String, at: CommonToken): Void throws Bubble {
        problem = lexer.located(message, at.line, at.column, at.offset);
        bubble()
      }

`varies` says whether the targets read something differently, by its
rule's letters.

      public varies(rule: String): Boolean {
        var seen = -1;
        for (let d of targets) {
          let letter = ruleLetter(rule, d);
          if (seen < 0) {
            seen = letter;
          } else if (letter != seen) {
            return true;
          }
        }
        false
      }

A kind's family, where integers and floats are both numbers, or 0 for
unknown and `NULL`.

      private family(k: Int): Int {
        if (k == kindInteger || k == kindFloat) {
          1
        } else if (k == kindText) {
          2
        } else if (k == kindBoolean) {
          3
        } else {
          0
        }
      }

      private known(k: Int): Int { if (k == kindNull) { kindUnknown } else { k } }

      public described(k: Int): String {
        if (k == kindText) {
          "text"
        } else if (k == kindBoolean) {
          "a boolean"
        } else if (k == kindFloat) {
          "a float"
        } else {
          "a number"
        }
      }

      private isLiteral(e: CommonExpr, literal: Int): Boolean {
        e is LiteralExpr && e.literal == literal
      }

`isNullValue` is whether an expression is a hole holding a null value.

      private isNullValue(e: CommonExpr): Boolean {
        e is ValueExpr && holeValue(e.hole) is SqlNull
      }

`literalSign` is a literal number's sign, with its `-` or `+`: -1, 0,
or 1, or 2 for anything else.

      private literalSign(e: CommonExpr): Int {
        when (e) {
          is UnaryExpr -> do {
            if (e.op == opNot) { return 2; }
            let sign = literalSign(e.operand);
            if (sign == 2 || e.op == opPos) { sign } else { -sign }
          };
          is LiteralExpr -> do {
            if (e.literal != literalInteger && e.literal != literalDecimal) { return 2; }
            let t = e.at;
            let text = lexer.runs[t.run];
            var sign = 0;
            for (var i = t.begin; i < t.end; i = text.next(i)) {
              let c = text[i];
              if (c >= char'1' && c <= char'9') { sign = 1; }
            }
            sign
          };
          else -> 2;
        }
      }

Whether a string is a plain number: an optional `-`, then digits, and
for a `DOUBLE`, maybe a point and more digits; at most 18 digits for an
`INTEGER`.

      private plainNumber(s: String, decimal: Boolean): Boolean {
        var i = String.begin;
        if (s.hasIndex(i) && s[i] == char'-') { i = s.next(i); }
        var digits = 0;
        var point = false;
        var after = 0;
        while (s.hasIndex(i)) {
          let c = s[i];
          if (isDigit(c)) {
            if (point) { after += 1; } else { digits += 1; }
          } else if (c == char'.' && decimal && !point) {
            point = true;
          } else {
            return false;
          }
          i = s.next(i);
        }
        digits > 0 && (!point || after > 0) && (decimal || digits <= 18)
      }
    }

## Printing

The printer writes a tree as canonical common SQL: keywords and
functions in capitals, names bare where they can be and quoted
otherwise, integers without leading zeros, and only the parentheses
the grammar needs. With `explicit`, it puts every operand that's an
operator expression in parentheses, which shows the tree's shape.
Holes stay holes: the result is a template, its runs of text between
them. The [statement printer](common-statements.temper.md) writes
through it.

With a `target`, it writes for that database instead, as
[rendering](common-rendering.temper.md) says: explicit parentheses
(but none around the operands of `AND` and `OR`), every name quoted,
and the target's own pieces where databases differ. `values` are the
template's holes, for their types, and `problem` says what it couldn't
write, such as a name the target refuses in a query made unchecked.

    class CommonTemplate(public runs: List<String>, public holes: List<Int>) {}

    class CommonPrinter(public lexer: CommonLexer, public explicit: Boolean) {
      private runs: ListBuilder<String> = new ListBuilder<String>();
      private holes: ListBuilder<Int> = new ListBuilder<Int>();
      private var out: StringBuilder = new StringBuilder();
      public var target: CommonTarget? = null;
      public var values: List<QueryPart> = new ListBuilder<QueryPart>().toList();
      public var problem: String? = null;

      public print(e: CommonExpr): CommonTemplate {
        write(e, 0);
        finish()
      }

      public printStatement(s: CommonStatement): CommonTemplate {
        new StatementPrinter(this).statement(s);
        finish()
      }

      private finish(): CommonTemplate {
        runs.add(out.toString());
        out = new StringBuilder();
        new CommonTemplate(runs.toList(), holes.toList())
      }

      public text(s: String): Void { out.append(s); }

      public fail(message: String): Void {
        if (problem == null) { problem = message; }
      }

`write` writes an expression where the grammar needs at least `level`,
in parentheses if it has less.

      public write(e: CommonExpr, level: Int): Void {
        let own = levelOf(e);
        let paren = own < level || (explicit && level > 1 && own < levelPrimary);
        if (paren) { out.append("("); }
        node(e);
        if (paren) { out.append(")"); }
      }

      private node(e: CommonExpr): Void {
        when (e) {
          is LiteralExpr -> literal(e);
          is ValueExpr -> hole(e.hole);
          is ColumnExpr -> do {
            let table = e.table;
            if (table != null) {
              name(table);
              out.append(".");
            }
            name(e.column);
          };
          is SubqueryExpr -> do {
            out.append("(");
            new StatementPrinter(this).select(e.query);
            out.append(")");
          };
          is ExistsExpr -> do {
            out.append("EXISTS ");
            node(e.query);
          };
          is UnaryExpr -> do {
            let op = e.op;
            if (op == opNot) {
              out.append("NOT ");
              write(e.operand, levelNot);
            } else {
              out.append(opTexts[op]);
              // A space keeps `- -x` from starting a comment.
              let operand = e.operand;
              if (operand is UnaryExpr && operand.op != opNot && !explicit) { out.append(" "); }
              write(operand, levelUnary);
            }
          };
          is BinaryExpr -> do {
            let level = levelOf(e);
            let comparing = level == levelPredicate;
            write(e.left, if (comparing) { levelConcat } else { level });
            out.append(" ${opTexts[e.op]} ");
            write(e.right, if (comparing) { levelConcat } else { level + 1 });
          };
          is ChainExpr -> do {
            let t = target;
            let concatFor = if (e.op == opConcat) { t } else { null };
            if (concatFor != null) {
              concat(e, concatFor);
            } else {
              let level = if (e.op == opConcat) { levelUnary } else { levelOf(e) + 1 };
              let joiner = " ${opTexts[e.op]} ";
              var first = true;
              for (let operand of e.operands) {
                if (!first) { out.append(joiner); }
                first = false;
                if (t != null) { loose(operand); } else { write(operand, level); }
              }
            }
          };
          is IsNullExpr -> do {
            write(e.operand, levelConcat);
            out.append(if (e.negated) { " IS NOT NULL" } else { " IS NULL" });
          };
          is InListExpr -> do {
            write(e.operand, levelConcat);
            out.append(if (e.negated) { " NOT IN (" } else { " IN (" });
            list(e.items);
            out.append(")");
          };
          is InQueryExpr -> do {
            write(e.operand, levelConcat);
            out.append(if (e.negated) { " NOT IN " } else { " IN " });
            node(e.query);
          };
          is BetweenExpr -> do {
            write(e.operand, levelConcat);
            out.append(if (e.negated) { " NOT BETWEEN " } else { " BETWEEN " });
            write(e.low, levelConcat);
            out.append(" AND ");
            write(e.high, levelConcat);
          };
          is LikeExpr -> do {
            write(e.operand, levelConcat);
            out.append(if (e.negated) { " NOT LIKE " } else { " LIKE " });
            write(e.pattern, levelConcat);
            let escape = e.escape;
            if (escape != null) { out.append(" ESCAPE ${lexer.tokenText(escape)}"); }
          };
          is CaseExpr -> caseExpr(e);
          is CastExpr -> do {
            out.append("CAST(");
            write(e.operand, 0);
            let t = target;
            let names = if (t != null) { t.castNames } else { castNames };
            out.append(" AS ${names[e.target]})");
          };
          is CallExpr -> do {
            let callee = e.callee;
            let t = target;
            var called = functionNames[callee];
            if (t != null) {
              if (callee == fnLength) { called = t.lengthName; }
            }
            out.append("${called}(");
            if (e.distinct) { out.append("DISTINCT "); }
            if (e.args.isEmpty) {
              out.append("*");
            } else if (callee == fnCoalesce || callee == fnNullif) {
              group(e.args);
            } else {
              list(e.args);
            }
            out.append(")");
          };
        }
      }

An operand of `AND` or `OR`, for a target: in parentheses only if it's
another `AND` or `OR`.

      private loose(e: CommonExpr): Void {
        let paren = levelOf(e) <= levelAnd;
        if (paren) { out.append("("); }
        node(e);
        if (paren) { out.append(")"); }
      }

`||`, for a target: `CONCAT(…)` where `||` isn't concatenation, and
for PostgreSQL, each value cast to `TEXT`, and the first operand too if
neither of the first two is text, since PostgreSQL has no `||` for two
numbers.

      private concat(e: ChainExpr, t: CommonTarget): Void {
        let operands = e.operands;
        if (t.concatCall) {
          out.append("CONCAT(");
          list(operands);
          out.append(")");
          return;
        }
        let castFirst = t.castsUnknown && !textual(operands[0]) && !textual(operands[1]);
        for (var i = 0; i < operands.length; i += 1) {
          if (i > 0) { out.append(" || "); }
          let operand = operands[i];
          let hole = if (t.castsUnknown) { valueHole(operand) } else { -1 };
          if (hole >= 0) {
            castValue(hole, "TEXT");
          } else if (i == 0 && castFirst) {
            out.append("CAST(");
            write(operand, 0);
            out.append(" AS TEXT)");
          } else {
            write(operand, levelUnary);
          }
        }
      }

Whether an expression is text, as PostgreSQL sees it: a string, a
value cast to text, a text function, a cast to `TEXT`, or `||`.

      private textual(e: CommonExpr): Boolean {
        when (e) {
          is LiteralExpr -> e.literal == literalString;
          is CallExpr -> do {
            let callee = e.callee;
            callee == fnLower || callee == fnUpper || callee == fnTrim || callee == fnReplace || callee == fnSubstr
          };
          is CastExpr -> e.target == castText;
          is ChainExpr -> e.op == opConcat;
          else -> e is ValueExpr;
        }
      }

`item` writes a `SELECT` item: for PostgreSQL, a value alone is cast to
its type, which nothing else there gives it.

      public item(e: CommonExpr): Void {
        let t = target;
        let hole = if (t != null && t.castsUnknown) { valueHole(e) } else { -1 };
        if (hole >= 0) {
          castValue(hole, valueType(hole) ?? "TEXT");
        } else {
          write(e, 0);
        }
      }

`valueHole` is a value's hole, or -1 for anything else.

      private valueHole(e: CommonExpr): Int {
        if (e is ValueExpr) { e.hole } else { -1 }
      }

`group` writes `CASE` results, or `COALESCE` or `NULLIF` arguments, for
PostgreSQL casting each value to the group's type when nothing else in
the group has a type: when the rest are values, strings, and `NULL`.

      private group(items: List<CommonExpr>): Void {
        let type = groupType(items);
        var first = true;
        for (let item of items) {
          if (!first) { out.append(", "); }
          first = false;
          groupItem(item, type);
        }
      }

      private groupItem(e: CommonExpr, type: String): Void {
        let hole = if (type.isEmpty) { -1 } else { valueHole(e) };
        if (hole >= 0) { castValue(hole, type); } else { write(e, 0); }
      }

      private groupType(items: List<CommonExpr>): String {
        let t = target;
        if (t == null || !t.castsUnknown) { return ""; }
        var type = "";
        for (let e of items) {
          if (e is ValueExpr) {
            let own = valueType(e.hole);
            if (own != null) {
              if (type.isEmpty) { type = own; }
            }
          } else if (e is LiteralExpr && e.literal == literalString) {
            if (type.isEmpty) { type = "TEXT"; }
          } else if (!(e is LiteralExpr && e.literal == literalNull)) {
            return "";
          }
        }
        if (type.isEmpty) { "TEXT" } else { type }
      }

`valueType` is the PostgreSQL type for a value's hole, or null for
`NULL`.

      private valueType(hole: Int): String? {
        if (hole < 0 || hole >= values.length) { return null; }
        let part = values[hole];
        let value = if (part is QueryParam) { part.value } else { null };
        when (value) {
          is SqlText -> "TEXT";
          is SqlInt -> "BIGINT";
          is SqlFloat -> "DOUBLE PRECISION";
          is SqlBool -> "BOOLEAN";
          else -> null;
        }
      }

      public castValue(index: Int, type: String): Void {
        out.append("CAST(");
        hole(index);
        out.append(" AS ${type})");
      }

      private caseExpr(e: CaseExpr): Void {
        out.append("CASE");
        let subject = e.subject;
        if (subject != null) {
          out.append(" ");
          write(subject, 0);
        }
        let thens = e.thens;
        let otherwise = e.otherwise;
        let results = new ListBuilder<CommonExpr>();
        for (let r of thens) { results.add(r); }
        if (otherwise != null) { results.add(otherwise); }
        let type = groupType(results.toList());
        var i = 0;
        for (let w of e.whens) {
          out.append(" WHEN ");
          write(w, 0);
          out.append(" THEN ");
          groupItem(thens[i], type);
          i += 1;
        }
        if (otherwise != null) {
          out.append(" ELSE ");
          groupItem(otherwise, type);
        }
        out.append(" END");
      }

      private list(items: List<CommonExpr>): Void {
        var first = true;
        for (let item of items) {
          if (!first) { out.append(", "); }
          first = false;
          write(item, 0);
        }
      }

      private literal(e: LiteralExpr): Void {
        let literal = e.literal;
        if (literal == literalNull) {
          out.append("NULL");
        } else if (literal == literalTrue) {
          out.append("TRUE");
        } else if (literal == literalFalse) {
          out.append("FALSE");
        } else if (literal == literalString) {
          let t = target;
          if (t != null) {
            let value = lexer.stringValue(e.at);
            out.append(t.dialect.quoteString(value) orelse "");
            if (problem == null) {
              let found = t.dialect.stringProblem(value);
              if (found != null) { problem = "${found} for ${t.dialect.name}"; }
            }
          } else {
            out.append(lexer.tokenText(e.at));
          }
        } else {
          // Without leading zeros, but with a digit before any point.
          let t = e.at;
          let text = lexer.runs[t.run];
          var i = t.begin;
          while (text[i] == char'0') {
            let next = text.next(i);
            if (next >= t.end || !isDigit(text[next])) { break; }
            i = next;
          }
          out.appendBetween(text, i, t.end);
        }
      }

      public name(n: CommonName): Void {
        if (n.hole >= 0) {
          hole(n.hole);
          return;
        }
        let value = lexer.nameValue(n.token);
        let t = target;
        if (t != null) {
          out.append(t.dialect.quoteName(value) orelse "");
          if (problem == null) {
            let found = t.dialect.nameProblem(value);
            if (found != null) { problem = "${found} for ${t.dialect.name}"; }
          }
        } else {
          out.append(canonicalName(value));
        }
      }

`nameText` is a name's text, written or from its hole.

      public nameText(n: CommonName): String {
        if (n.hole >= 0 && n.hole < values.length) {
          let part = values[n.hole];
          if (part is QueryName) { return part.name.name; }
        }
        lexer.nameValue(n.token)
      }

      public hole(index: Int): Void {
        runs.add(out.toString());
        out = new StringBuilder();
        holes.add(index);
      }

Precedence: how tightly each kind of expression binds.

      private levelOf(e: CommonExpr): Int {
        if (e is ChainExpr) {
          if (e.op == opOr) { levelOr } else if (e.op == opAnd) { levelAnd } else { levelConcat }
        } else if (e is UnaryExpr) {
          if (e.op == opNot) { levelNot } else { levelUnary }
        } else if (e is BinaryExpr) {
          let op = e.op;
          if (op <= opGe) {
            levelPredicate
          } else if (op == opAdd || op == opSub) {
            levelSum
          } else {
            levelProduct
          }
        } else if (
          e is IsNullExpr || e is InListExpr || e is InQueryExpr || e is BetweenExpr || e is LikeExpr
        ) {
          levelPredicate
        } else {
          levelPrimary
        }
      }

    }

`canonicalName` writes a name bare if it can be, lowercase and not a
word with a meaning, or else quoted.

    let canonicalName(value: String): String {
      if (isPlainName(value)) { value } else { "\"${replaceCodePoint(value, char'"', "\"\"")}\"" }
    }

    let isPlainName(value: String): Boolean {
      if (value.isEmpty || isDigit(value[String.begin])) { return false; }
      for (var i = String.begin; value.hasIndex(i); i = value.next(i)) {
        let c = value[i];
        if (!((c >= char'a' && c <= char'z') || isDigit(c) || c == char'_')) { return false; }
      }
      !commonWords.has(value)
    }

`ruleLetter` is a profile's letter in a check's rule.

    let ruleLetter(rule: String, dialect: Dialect): Int {
      let name = dialect.name;
      let place = if (name == "sqlite") {
        0
      } else if (name == "postgres") {
        1
      } else if (name == "mysql") {
        2
      } else if (name == "mysqlNoBackslashEscapes") {
        3
      } else {
        4
      };
      var i = String.begin;
      for (var k = 0; k < place && rule.hasIndex(i); k += 1) { i = rule.next(i); }
      if (rule.hasIndex(i)) { rule[i] } else { 0 }
    }

Precedence levels, from loosest to tightest.

    let levelOr = 1;
    let levelAnd = 2;
    let levelNot = 3;
    let levelPredicate = 4;
    let levelConcat = 5;
    let levelSum = 6;
    let levelProduct = 7;
    let levelUnary = 8;
    let levelPrimary = 9;
