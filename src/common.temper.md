# The Common Dialect

The common dialect is SQL written once for every database Wherewith
knows: a strict subset that each one reads the same way. The
[design](../docs/design.md#the-common-dialect) has the whole plan.
Built so far: the `sql` tag, `Dialect.common`, the lexer, which reads
a template into tokens and refuses anything outside the subset, with
the line and column of the problem, and the parser for
[expressions](common-expressions.temper.md) and
[statements](common-statements.temper.md), with the checks they show.
The rest of the check stage, and rendering for each database, come
next.

## Profile

`Dialect.common`, in the [core](core.temper.md), quotes as the shared
core does (names in `"…"` and strings in `'…'`, each doubling its
quote) and takes only names `Identifier` takes, which every database
accepts.

## Queries

The `sql` tag makes a [Query](query.temper.md) whose dialect is
`Dialect.common`, lexing, parsing, and checking the template when it
runs, and panicking on a problem:

```temper inert
let users = Identifier.named("Users") orelse panic();
let q = sql"select name from ${users} where id = ${42}";
q.dialect; // Dialect.common
q.render(Dialect.common, PlaceholderStyle.question).sql;
// SELECT name FROM "Users" WHERE id = ?
```

For now a common query renders only for `Dialect.common`, as canonical
common SQL written from its tree: keywords in capitals, names bare
where they can be, comments gone, and values as placeholders. For any
other dialect, `render` bubbles with `renderProblem` saying that isn't
built yet.

    export class SqlTag {
      private b: QueryBuilder = new QueryBuilder(Dialect.common);

      public appendSafe(fixed: String): Void { b.appendSafe(fixed); }
      @overload("append")
      public appendString(x: String?): Void { b.appendString(x); }
      @overload("append")
      public appendInt(x: Int): Void { b.appendInt(x); }
      @overload("append")
      public appendInt64(x: Int64): Void { b.appendInt64(x); }
      @overload("append")
      public appendFloat64(x: Float64): Void { b.appendFloat64(x); }
      @overload("append")
      public appendBoolean(x: Boolean): Void { b.appendBoolean(x); }
      @overload("append")
      public appendValue(x: SqlValue): Void { b.appendValue(x); }
      @overload("append")
      public appendIdentifier(x: Identifier): Void { b.appendIdentifier(x); }
      @overload("append")
      public appendQuery(x: Query): Void { b.appendQuery(x); }

      public get accumulated(): Query { b.accumulated }
    }

    export let sql = SqlTag;

## Lexer

What `QueryBuilder` checks for the common dialect. Unlike the
databases' lexers, which only find quotes, comments, and stray
parameters, it reads the whole template into tokens, for the parser,
and refuses everything outside the subset:

- **Whitespace:** space, tab, line feed, form feed, and carriage
  return. Not vertical tab, which SQLite refuses.
- **Comments:** `--` to a line feed, with no lone carriage return in
  it (PostgreSQL and DuckDB end the comment there), and `/* */`, with
  no `/*` inside (PostgreSQL and DuckDB nest them, SQLite and MySQL
  don't), and not MySQL's `/*!` or `/*+`. Comments may hold anything
  but NUL, since they never reach the rendered SQL.
- **Strings:** `'…'`, with `'` doubled and no backslash escapes, and no
  prefix (`E'…'`, `X'…'`, `N'…'`, or MySQL's `_utf8mb4'…'`). Each must
  be a string every target takes (each one's `stringProblem`), and,
  when MySQL's default profile is one, hold no `\`, which MySQL reads
  as an escape in its default mode only: bind such text as a value.
- **Quoted names:** `"…"`, with `"` doubled, each a name every target
  takes (each one's `nameProblem`). For every profile, that's not
  empty, at most 63 UTF-8 bytes and 64 characters, nothing above
  U+FFFF, no trailing whitespace, and no `#mysql50#` prefix.
- **Words:** `[A-Za-z_][A-Za-z0-9_]*`. Keywords are read without regard
  to case. Any other word is a bare name, which must be lowercase,
  since PostgreSQL folds names to lowercase while the others keep their
  case; Wherewith never folds a name itself. Quote a name to keep its
  case. Function and type names, `FIRST`, and `LAST` aren't reserved,
  so written lowercase they can be names too.
- **Numbers:** integers (`12`) up to 9223372036854775807, the largest
  64-bit integer, and decimals (`1.5`) of at most 18 digits, with no
  exponents, signs (a `-` is an operator), or other forms such as
  `0x1F` or `1_000`, and nothing running into them. The smallest
  64-bit integer can only be bound as a value.
- **Operators:** `(`, `)`, `,`, `.`, `+`, `-`, `*`, `/`, `%`, `||`,
  `=`, `<>`, `!=`, `<`, `<=`, `>`, and `>=`.
- Anything else outside quotes and comments is refused: `?`, `$`, `:`,
  `@`, `;`, `#`, backticks, brackets, other operators such as `::`,
  `==`, or `->`, other control characters, non-ASCII characters, and
  NUL anywhere.

Holes are tokens of their kind: a value or a name (an `Identifier`).
A nested query's own tokens go in, between a start and an end token,
so the parser sees the whole statement and the checks see into it; the
grammar decides where each kind may go. The tokens inside a nested
query take the place of its hole, for problems.

Whether strings and names suit each target database is checked once
the template is whole, since a builder's
[targets](query.temper.md#querybuilder) can change until then
(`targetProblem`).

A problem gives its place in the template written with each hole as
`${…}`: the line and column (counting code points from 1), and a short
excerpt of that line.

Tokens point into the text, rather than copying it: each holds its
run (the text between two holes), and string indexes into it.

    class CommonToken(
      public kind: Int,
      // The text run it's in, or -1 for a hole or a nested query's ends.
      public run: Int,
      public begin: StringIndex,
      public end: StringIndex,
      public line: Int,
      public column: Int,
      // Code points before it in the template, with holes as `${…}`.
      public offset: Int,
      // A keyword's, word's, or bare name's text, lowercase, or else "".
      public word: String,
    ) {}

Token kinds.

    let tokenKeyword = 1;
    // A word that's a keyword in some places and a name in others.
    let tokenWord = 2;
    let tokenName = 3;
    let tokenQuotedName = 4;
    let tokenString = 5;
    let tokenInteger = 6;
    let tokenDecimal = 7;
    let tokenSymbol = 8;
    let tokenValueHole = 9;
    let tokenNameHole = 10;
    let tokenQueryStart = 11;
    let tokenQueryEnd = 12;

The words with a meaning, lowercase: the subset's keywords, and words
saved for constructs planned later, which are reserved; and function
names, type names, `first`, and `last`, which aren't.

    let commonWords: Map<String, Int> = new Map([
      new Pair("all", tokenKeyword), new Pair("and", tokenKeyword),
      new Pair("as", tokenKeyword), new Pair("asc", tokenKeyword),
      new Pair("between", tokenKeyword), new Pair("by", tokenKeyword),
      new Pair("case", tokenKeyword), new Pair("cast", tokenKeyword),
      new Pair("cross", tokenKeyword), new Pair("delete", tokenKeyword),
      new Pair("desc", tokenKeyword), new Pair("distinct", tokenKeyword),
      new Pair("else", tokenKeyword), new Pair("end", tokenKeyword),
      new Pair("escape", tokenKeyword), new Pair("except", tokenKeyword),
      new Pair("exists", tokenKeyword), new Pair("false", tokenKeyword),
      new Pair("from", tokenKeyword), new Pair("full", tokenKeyword),
      new Pair("group", tokenKeyword), new Pair("having", tokenKeyword),
      new Pair("ilike", tokenKeyword), new Pair("in", tokenKeyword),
      new Pair("inner", tokenKeyword), new Pair("insert", tokenKeyword),
      new Pair("intersect", tokenKeyword), new Pair("into", tokenKeyword),
      new Pair("is", tokenKeyword), new Pair("join", tokenKeyword),
      new Pair("left", tokenKeyword), new Pair("like", tokenKeyword),
      new Pair("limit", tokenKeyword), new Pair("natural", tokenKeyword),
      new Pair("not", tokenKeyword), new Pair("null", tokenKeyword),
      new Pair("nulls", tokenKeyword), new Pair("offset", tokenKeyword),
      new Pair("on", tokenKeyword), new Pair("or", tokenKeyword),
      new Pair("order", tokenKeyword), new Pair("outer", tokenKeyword),
      new Pair("returning", tokenKeyword), new Pair("right", tokenKeyword),
      new Pair("select", tokenKeyword), new Pair("set", tokenKeyword),
      new Pair("then", tokenKeyword), new Pair("true", tokenKeyword),
      new Pair("union", tokenKeyword), new Pair("update", tokenKeyword),
      new Pair("using", tokenKeyword), new Pair("values", tokenKeyword),
      new Pair("when", tokenKeyword), new Pair("where", tokenKeyword),
      new Pair("window", tokenKeyword), new Pair("with", tokenKeyword),
      new Pair("abs", tokenWord), new Pair("avg", tokenWord),
      new Pair("coalesce", tokenWord), new Pair("count", tokenWord),
      new Pair("double", tokenWord), new Pair("first", tokenWord),
      new Pair("integer", tokenWord), new Pair("last", tokenWord),
      new Pair("length", tokenWord), new Pair("lower", tokenWord),
      new Pair("max", tokenWord), new Pair("min", tokenWord),
      new Pair("nullif", tokenWord), new Pair("replace", tokenWord),
      new Pair("substr", tokenWord), new Pair("sum", tokenWord),
      new Pair("text", tokenWord), new Pair("trim", tokenWord),
      new Pair("upper", tokenWord),
    ]);

How a hole shows in problem excerpts.

    let holeMark = "\${…}";

The lexer reads a run at a time, as the builder gives them, and keeps
every run, since its tokens point into them.

    class CommonLexer extends SqlLexer {
      public tokens: ListBuilder<CommonToken> = new ListBuilder<CommonToken>();
      public runs: ListBuilder<String> = new ListBuilder<String>();
      // The runs and holes in order, for excerpts.
      private pieces: ListBuilder<String> = new ListBuilder<String>();
      private var state: Int = lexCode;
      // Where the next code point is, as shown in problems; inside a
      // nested query, where its hole is.
      private var line: Int = 1;
      private var column: Int = 1;
      private var offset: Int = 0;
      // Where the quote or comment still open started.
      private var openLine: Int = 0;
      private var openColumn: Int = 0;
      private var openOffset: Int = 0;
      // Code points read, nested queries' too, and where the last token
      // ended among them.
      private var read: Int = 0;
      private var lastEnd: Int = -1;
      // How many nested queries the lexer is in.
      private var nested: Int = 0;
      // The first problem in this run or hole.
      private var problem: String? = null;

      public get inCode(): Boolean { state == lexCode }
      public get inLineComment(): Boolean { state == lexLineComment }

      public scan(text: String): String? {
        problem = null;
        runs.add(text);
        if (nested == 0) { pieces.add(text); }
        let run = runs.length - 1;
        let end = text.end;
        var i = String.begin;
        // A quote or comment goes on from the last run only after a
        // hole was refused there, or in the line break that `build`
        // adds after a line comment.
        if (state == lexLineComment) {
          state = lexCode;
          i = lineComment(text, i);
        } else if (state == lexBlockComment) {
          i = blockCommentBody(text, i);
        } else if (state != lexCode) {
          i = skipQuote(text, i);
        }
        while (i < end) {
          let c = text[i];
          let next = text.next(i);
          let following = if (next < end) { text[next] } else { -1 };
          if (c == char' ' || c == char'\n' || c == char'\t' || c == char'\r' || c == 0x0C) {
            i = step(text, i);
          } else if (c == char'-' && following == char'-') {
            i = lineComment(text, step(text, step(text, i)));
          } else if (c == char'/' && following == char'*') {
            i = blockComment(text, i);
          } else if (c == char'\'' || c == char'"') {
            i = quoted(text, run, i);
          } else if (c >= char'0' && c <= char'9') {
            i = number(text, run, i);
          } else if (isLetter(c) || c == char'_') {
            i = word(text, run, i);
          } else {
            i = symbol(text, run, i);
          }
        }
        problem
      }

A value or name hole, from the [builder](query.temper.md). It's a
token, written `${…}` for positions.

      public hole(kind: Int): String? {
        problem = null;
        let tokenKind = if (kind == holeName) { tokenNameHole } else { tokenValueHole };
        let token = new CommonToken(tokenKind, -1, String.begin, String.begin, line, column, offset, "");
        read += 4;
        add(token, read);
        if (nested == 0) {
          pieces.add(holeMark);
          column += 4;
          offset += 4;
        }
        problem
      }

A nested query: `beginQuery`, then its parts, as text and holes, then
`endQuery`, which refuses a query that ends inside a quote or comment.

      public beginQuery(): Void {
        problem = null;
        add(new CommonToken(tokenQueryStart, -1, String.begin, String.begin, line, column, offset, ""), read);
        if (nested == 0) { pieces.add(holeMark); }
        nested += 1;
      }

      public endQuery(): String? {
        problem = null;
        if (state != lexCode) {
          report("nested query ends inside a quote or comment", line, column, offset);
          state = lexCode;
        }
        add(new CommonToken(tokenQueryEnd, -1, String.begin, String.begin, line, column, offset, ""), read);
        nested -= 1;
        if (nested == 0) {
          column += 4;
          offset += 4;
        }
        problem
      }

      public locate(message: String): String {
        located(message, line, column, offset)
      }

      public endProblem(): String? {
        problem = null;
        let open = if (state == lexSingleQuoted) {
          "string not closed"
        } else if (state == lexDoubleQuoted) {
          "quoted name not closed"
        } else if (state == lexBlockComment) {
          "comment not closed"
        } else {
          null
        };
        if (open != null) { report(open, openLine, openColumn, openOffset); }
        problem
      }

`step` moves past the code point at `i`, keeping the position, and
refuses NUL, wherever it is.

      private step(text: String, i: StringIndex): StringIndex {
        let c = text[i];
        if (c == 0) { report("NUL in template text", line, column, offset); }
        read += 1;
        if (nested == 0) {
          if (c == char'\n') {
            line += 1;
            column = 1;
          } else {
            column += 1;
          }
          offset += 1;
        }
        text.next(i)
      }

A line comment, from just after its `--`, up to its line feed.

      private lineComment(text: String, start: StringIndex): StringIndex {
        let end = text.end;
        var i = start;
        while (i < end && text[i] != char'\n') {
          let next = text.next(i);
          if (text[i] == char'\r' && next < end && text[next] != char'\n') {
            report("carriage return in a line comment", line, column, offset);
          }
          i = step(text, i);
        }
        if (i >= end) { state = lexLineComment; }
        i
      }

A block comment, from its `/*`.

      private blockComment(text: String, start: StringIndex): StringIndex {
        openLine = line;
        openColumn = column;
        openOffset = offset;
        var i = step(text, step(text, start));
        if (i < text.end && (text[i] == char'!' || text[i] == char'+')) {
          report("executable comment or optimizer hint", openLine, openColumn, openOffset);
        }
        state = lexBlockComment;
        blockCommentBody(text, i)
      }

      private blockCommentBody(text: String, start: StringIndex): StringIndex {
        let end = text.end;
        var i = start;
        while (i < end) {
          let next = text.next(i);
          let following = if (next < end) { text[next] } else { -1 };
          if (text[i] == char'*' && following == char'/') {
            state = lexCode;
            return step(text, step(text, i));
          }
          if (text[i] == char'/' && following == char'*') {
            report("/* inside a comment", line, column, offset);
          }
          i = step(text, i);
        }
        i
      }

A string or quoted name, from its opening quote.

      private quoted(text: String, run: Int, start: StringIndex): StringIndex {
        let quote = text[start];
        let isString = quote == char'\'';
        let startLine = line;
        let startColumn = column;
        let startOffset = offset;
        let last = lastToken();
        if (last != null) {
          let wordy = last.kind == tokenKeyword || last.kind == tokenWord || last.kind == tokenName;
          if (isString && lastEnd == read && wordy) {
            report("prefixed string", last.line, last.column, last.offset);
          }
        }
        let end = text.end;
        var i = step(text, start);
        while (i < end) {
          if (text[i] == quote) {
            let next = text.next(i);
            if (next < end && text[next] == quote) {
              i = step(text, step(text, i));
              continue;
            }
            i = step(text, i);
            add(
              new CommonToken(
                if (isString) { tokenString } else { tokenQuotedName },
                run, start, i, startLine, startColumn, startOffset, "",
              ),
              read,
            );
            return i;
          }
          i = step(text, i);
        }
        openLine = startLine;
        openColumn = startColumn;
        openOffset = startOffset;
        state = if (isString) { lexSingleQuoted } else { lexDoubleQuoted };
        i
      }

`targetProblem` gives the first string or name, in the order written,
that some target database can't take, or null. A target that reads
backslash escapes (MySQL's default profile) refuses a string with `\`,
since `NO_BACKSLASH_ESCAPES` reads it differently.

      public targetProblem(targets: List<Dialect>): String? {
        for (var i = 0; i < tokens.length; i += 1) {
          let t = tokens[i];
          let kind = t.kind;
          let found = if (kind == tokenString) {
            stringTargetProblem(stringValue(t), targets)
          } else if (kind == tokenQuotedName || kind == tokenName) {
            nameTargetProblem(nameValue(t), targets)
          } else {
            null
          };
          if (found != null) { return located(found, t.line, t.column, t.offset); }
        }
        null
      }

What's wrong with a string or name for some target, or null.

      // Index loops, since Temper can't yet return from a for-of loop
      // in a method.
      private stringTargetProblem(value: String, targets: List<Dialect>): String? {
        for (var t = 0; t < targets.length; t += 1) {
          let d = targets[t];
          let found = d.stringProblem(value);
          if (found != null) { return "${found} for ${d.name}"; }
          if (d.name == "mysql" && hasCodePoint(value, char'\\')) {
            return "backslash in a string for mysql; bind the value instead";
          }
        }
        null
      }

      private nameTargetProblem(name: String, targets: List<Dialect>): String? {
        for (var t = 0; t < targets.length; t += 1) {
          let d = targets[t];
          let found = d.nameProblem(name);
          if (found != null) { return "${found} for ${d.name}"; }
        }
        null
      }

The rest of a quote whose hole was refused, or that ends the template.

      private skipQuote(text: String, start: StringIndex): StringIndex {
        let quote = if (state == lexSingleQuoted) { char'\'' } else { char'"' };
        let end = text.end;
        var i = start;
        while (i < end) {
          let c = text[i];
          i = step(text, i);
          if (c == quote) {
            if (i < end && text[i] == quote) {
              i = step(text, i);
            } else {
              state = lexCode;
              return i;
            }
          }
        }
        i
      }

A number: an integer up to the largest 64-bit integer, or a decimal
of at most 18 digits, leading zeros aside.

      private number(text: String, run: Int, start: StringIndex): StringIndex {
        let startLine = line;
        let startColumn = column;
        let startOffset = offset;
        let end = text.end;
        let largest = "9223372036854775807";
        var l = String.begin;
        // Whether the digits so far are less than (-1), equal to (0),
        // or more than (1) the largest's first digits.
        var order = 0;
        var digits = 0;
        var i = start;
        while (i < end && isDigit(text[i])) {
          let c = text[i];
          if (digits > 0 || c != char'0') {
            digits += 1;
            if (largest.hasIndex(l)) {
              if (order == 0) {
                let d = largest[l];
                order = if (c > d) { 1 } else if (c < d) { -1 } else { 0 };
              }
              l = largest.next(l);
            }
          }
          i = step(text, i);
        }
        var kind = tokenInteger;
        if (i < end && text[i] == char'.') {
          let next = text.next(i);
          if (next < end && isDigit(text[next])) {
            kind = tokenDecimal;
            i = step(text, i);
            while (i < end && isDigit(text[i])) {
              digits += 1;
              i = step(text, i);
            }
          } else {
            report("decimal point without digits after it", line, column, offset);
          }
        }
        if (i < end && (isLetter(text[i]) || text[i] == char'_')) {
          report("number runs into a word", startLine, startColumn, startOffset);
        }
        if (kind == tokenInteger && (digits > 19 || (digits == 19 && order > 0))) {
          report("integer beyond 64 bits; bind it as a value", startLine, startColumn, startOffset);
        } else if (kind == tokenDecimal && digits > 18) {
          report("decimal with more than 18 digits", startLine, startColumn, startOffset);
        }
        add(new CommonToken(kind, run, start, i, startLine, startColumn, startOffset, ""), read);
        i
      }

A keyword, or a bare name, which must be lowercase.

      private word(text: String, run: Int, start: StringIndex): StringIndex {
        let startLine = line;
        let startColumn = column;
        let startOffset = offset;
        let end = text.end;
        var upper = false;
        var i = start;
        while (i < end && (isLetter(text[i]) || isDigit(text[i]) || text[i] == char'_')) {
          if (text[i] <= char'Z' && text[i] >= char'A') { upper = true; }
          i = step(text, i);
        }
        let key = new StringBuilder();
        if (upper) {
          for (var j = start; j < i; j = text.next(j)) {
            key.appendCodePoint(lowercased(text[j])) orelse panic();
          }
        } else {
          key.appendBetween(text, start, i);
        }
        let name = key.toString();
        var kind = commonWords.getOr(name, tokenName);
        if (kind == tokenName && upper) {
          report("bare name not lowercase; quote it to keep its case", startLine, startColumn, startOffset);
        }
        add(new CommonToken(kind, run, start, i, startLine, startColumn, startOffset, name), read);
        i
      }

An operator, or a refused character.

      private symbol(text: String, run: Int, start: StringIndex): StringIndex {
        let startLine = line;
        let startColumn = column;
        let startOffset = offset;
        let end = text.end;
        let c = text[start];
        let next = text.next(start);
        let following = if (next < end) { text[next] } else { -1 };
        // How many code points the operator has.
        var size = 1;
        // An operator that isn't common SQL, or else a message.
        var refused: String? = null;
        var message: String? = null;
        if (c == char'<') {
          if (following == char'=') {
            let after = text.next(next);
            if (after < end && text[after] == char'>') { refused = "<=>"; } else { size = 2; }
          } else if (following == char'>') {
            size = 2;
          } else if (following == char'<') {
            refused = "<<";
          }
        } else if (c == char'>') {
          if (following == char'=') { size = 2; } else if (following == char'>') { refused = ">>"; }
        } else if (c == char'=') {
          if (following == char'=') { refused = "=="; } else if (following == char'>') { refused = "=>"; }
        } else if (c == char'!') {
          if (following == char'=') { size = 2; } else { refused = "!"; }
        } else if (c == char'|') {
          if (following == char'|') { size = 2; } else { refused = "|"; }
        } else if (c == char'-') {
          if (following == char'>') { refused = "->"; }
        } else if (c == char'*') {
          if (following == char'*') { refused = "**"; }
        } else if (c == char'.') {
          if (isDigit(following)) {
            report("decimal without a digit before its point", startLine, startColumn, startOffset);
          }
        } else if (c == char'?' || c == char'$') {
          message = "${shown(c)} outside quotes; put values in holes";
        } else if (c == char';') {
          message = "; outside quotes; write one statement per query";
        } else if (c == char'`') {
          message = "` outside quotes; quote names with double quotes";
        } else if (c >= 0x80) {
          message = "non-ASCII character outside quotes";
        } else if (c == 0) {
          // `step` refuses it.
          message = "";
        } else if (c < 0x20 || c == 0x7F) {
          message = "control character outside quotes";
        } else if (!isOperator(c)) {
          refused = shown(c);
        }
        let op = refused;
        let whole = if (op != null) { "${op} isn't common SQL" } else { message };
        if (whole != null) {
          if (!whole.isEmpty) { report(whole, startLine, startColumn, startOffset); }
          return step(text, start);
        }
        var i = step(text, start);
        if (size == 2) { i = step(text, i); }
        add(new CommonToken(tokenSymbol, run, start, i, startLine, startColumn, startOffset, ""), read);
        i
      }

`add` adds a token ending at `after`, counting code points read.

      private add(token: CommonToken, after: Int): Void {
        tokens.add(token);
        lastEnd = after;
      }

      private lastToken(): CommonToken? {
        if (tokens.isEmpty) { null } else { tokens[tokens.length - 1] }
      }

`tokenText` is a token's text as written, or `${…}` for a hole.

      public tokenText(t: CommonToken): String {
        if (t.run < 0) { holeMark } else { runs[t.run].slice(t.begin, t.end) }
      }

`nameValue` is the name a bare or quoted name's token is, and
`stringValue` the text a string's token is, each with its doubled
quotes made single.

      public nameValue(t: CommonToken): String {
        if (t.kind == tokenQuotedName) { unquoted(t) } else { t.word }
      }

      public stringValue(t: CommonToken): String { unquoted(t) }

      private unquoted(t: CommonToken): String {
        let text = runs[t.run];
        let quote = text[t.begin];
        let last = text.prev(t.end);
        let value = new StringBuilder();
        var i = text.next(t.begin);
        var from = i;
        while (i < last) {
          if (text[i] == quote) {
            let next = text.next(i);
            value.appendBetween(text, from, next);
            i = text.next(next);
            from = i;
          } else {
            i = text.next(i);
          }
        }
        value.appendBetween(text, from, last);
        value.toString()
      }

`report` keeps the first problem, placed at a line, column, and
offset.

      private report(message: String, atLine: Int, atColumn: Int, at: Int): Void {
        if (problem == null) { problem = located(message, atLine, atColumn, at); }
      }

`located` adds the place to a message: the line and column, and up to
20 code points of the line on each side, from the template so far.

      public located(message: String, atLine: Int, atColumn: Int, at: Int): String {
        let all = new StringBuilder();
        for (var p = 0; p < pieces.length; p += 1) { all.append(pieces[p]); }
        let shown = all.toString();
        let before = if (atColumn - 1 < 20) { atColumn - 1 } else { 20 };
        var i = String.begin;
        var k = 0;
        while (k < at - before && shown.hasIndex(i)) {
          i = shown.next(i);
          k += 1;
        }
        let from = i;
        while (shown.hasIndex(i) && k < at + 20) {
          let c = shown[i];
          if (k >= at && (c == char'\n' || c == char'\r')) { break; }
          i = shown.next(i);
          k += 1;
        }
        let excerpt = new StringBuilder();
        excerpt.appendBetween(shown, from, i);
        "${message}, at line ${atLine.toString()}, column ${atColumn.toString()}: ${excerpt.toString()}"
      }
    }

## Helpers

    let isDigit(c: Int): Boolean { c >= char'0' && c <= char'9' }

    let isLetter(c: Int): Boolean {
      (c >= char'a' && c <= char'z') || (c >= char'A' && c <= char'Z')
    }

    let isOperator(c: Int): Boolean {
      c == char'(' || c == char')' || c == char',' || c == char'.' || c == char'+' ||
        c == char'-' || c == char'*' || c == char'/' || c == char'%' || c == char'=' ||
        c == char'<' || c == char'>'
    }

`lowercased` folds an ASCII capital, leaving other code points alone.

    let lowercased(c: Int): Int {
      if (c >= char'A' && c <= char'Z') { c + 32 } else { c }
    }

`shown` writes an ASCII code point as a string.

    let shown(c: Int): String { String.fromCodePoint(c) orelse "?" }
