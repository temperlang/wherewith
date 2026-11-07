# DuckDB

## Profile

`Dialect.duckdb`, in the [core](core.temper.md), quotes names in `"…"`
and strings in `'…'`, doubling the quote inside. Backslashes in plain
strings are plain characters, and DuckDB has no setting that changes
that. Names have no length limit. A NUL can't be written in a string:
DuckDB's text can hold one, but its C API reads SQL text only up to a
NUL.

DuckDB matches names without regard to ASCII case, even quoted ones,
so `"A"` and `"a"` are the same column, though it keeps the case it
was given. Wherewith quotes names exactly; it doesn't fold them or
check whether two would clash.

DuckDB turns some Unicode spaces into plain spaces before it parses,
everywhere but in what it takes for quotes and line comments (see the
lexer below). Quoted strings and names keep theirs where the text
around them is plain, as it is wherever Wherewith checks it. SQL put
together some other way, after a block comment, backtick name, or
`E'…'` string holding a quote, can lose them.

## Queries

The `duckdb` tag makes a [Query](query.temper.md), checking the
template with DuckDB's lexing rules:

```temper inert
let q = duckdb"SELECT tags[1:${2}] FROM t WHERE name = ${"it's"}";
let r = q.render(Dialect.duckdb, PlaceholderStyle.dollarNumbered) orelse panic();
r.sql; // SELECT tags[1: $1] FROM t WHERE name = $2
```

DuckDB's clients take `?` (`PlaceholderStyle.question`) and `$1`
(`PlaceholderStyle.dollarNumbered`), apart from JDBC, which takes only
`?`. DuckDB also takes `$name`, which no placeholder style writes.

    export class DuckdbTag {
      private b: QueryBuilder = new QueryBuilder(Dialect.duckdb);

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

    export let duckdb = DuckdbTag;

## Lexer

DuckDB's parser started from PostgreSQL's, and reads quotes, comments,
and parameters the same way, so `QueryBuilder` checks DuckDB's SQL with
the [PostgreSQL lexer](postgres.temper.md), set for DuckDB:

- Quotes: as for PostgreSQL, strings in `'…'`, `E'…'` strings with
  backslash escapes (going on past a line break into another `'…'`, as
  PostgreSQL's do), dollar quotes, and names in `"…"`; and also names
  in `` `…` ``, with `` ` `` doubled. `U&'…'` isn't a string prefix in
  DuckDB, but `U&` before a plain string lexes the same either way.
- Comments: `--` to the end of the line, which a line feed or a
  carriage return ends, and `/* */`, which nest.
- Placeholders: `?`, `?1`, `$1`, and `$name`, so `?` can't be in the
  text outside quotes and comments, and `$` only starts a dollar
  quote; names with `$` need quoting. `:` (in slices, struct literals,
  and lambdas) and `@` are fine.
- Unicode spaces: before parsing, DuckDB turns each of these into a
  plain space, wherever its own simpler pass doesn't take it for part
  of a quote or a line comment: U+00A0, U+2000 to U+200B, U+202F,
  U+205F, U+2060, U+3000, and U+FEFF. That pass knows `'…'`, `"…"`,
  dollar quotes, and line comments, but not block comments, backtick
  names, or backslash escapes, so a quote in those can put it out of
  step with the parser. So it's a mistake wherever the lexer is in code
  and the pass isn't, as after `/* it's */`, `` `it's` ``, or
  `E'it\'s'` (write `/* it is */`, `"it's"`, or `'it''s'`), and for a
  Unicode space inside a quote where the pass would change it, as in a
  backtick name. In code, these spaces are whitespace, so one before
  `E'` makes an `E` string.

These rules are from DuckDB 2.0's own behavior, through the round
trips in `tests/engines`; parser extensions and other dialects that
replace DuckDB's parser aren't covered.

### Unicode space pass

`DuckdbSpacePass` follows DuckDB's pass over the text, a run at a
time. It keeps its state from one run to the next, and its place,
`upTo`, within the run.

    class DuckdbSpacePass {
      private var state: Int = lexCode;
      private var tag: String = "";
      private var upTo: StringIndex = String.begin;

`start` begins a new run.

      public start(): Void { upTo = String.begin; }

      public get inCode(): Boolean { state == lexCode }

Whether the pass changes a Unicode space at `i`, once it has caught up
to it: only where it's in code, and not in a dollar quote's tag, which
it skips.

      public changes(i: StringIndex): Boolean {
        state == lexCode && upTo == i
      }

`catchUp` reads on to `target`. Unlike the parser, the pass looks for
a dollar quote's closing tag from the last `$` of its opening tag, and
reads a closing tag's last `$` again, as code, so `$$$$` starts a
second dollar quote.

      public catchUp(text: String, target: StringIndex): Void {
        let end = text.end;
        while (upTo < target) {
          let i = upTo;
          let c = text[i];
          let next = text.next(i);
          let following = if (next < end) { text[next] } else { -1 };
          var resume = next;
          when (state) {
            lexCode -> if (c == char'\'') {
              state = lexSingleQuoted;
            } else if (c == char'"') {
              state = lexDoubleQuoted;
            } else if (c == char'-' && following == char'-') {
              state = lexLineComment;
            } else if (c == char'$') {
              let tagEnd = dollarTagEnd(text, next);
              if (tagEnd != null) {
                let sb = new StringBuilder();
                sb.appendBetween(text, i, text.next(tagEnd));
                tag = sb.toString();
                state = lexDollarQuoted;
                resume = tagEnd;
              }
            };
            lexSingleQuoted -> if (c == char'\'') { state = lexCode; };
            lexDoubleQuoted -> if (c == char'"') { state = lexCode; };
            lexLineComment -> if (c == char'\n' || c == char'\r') { state = lexCode; };
            else -> if (c == char'$' && hasAt(text, i, tag)) {
              state = lexCode;
              // On to the tag's last `$`, which is read again.
              var j = i;
              for (var k = tag.next(String.begin); tag.hasIndex(k); k = tag.next(k)) {
                j = text.next(j);
              }
              resume = j;
            };
          }
          upTo = resume;
        }
      }
    }

The Unicode spaces DuckDB turns into plain ones.

    let isDuckdbUnicodeSpace(c: Int): Boolean {
      c == 0xA0 || (c >= 0x2000 && c <= 0x200B) || c == 0x202F || c == 0x205F ||
        c == 0x2060 || c == 0x3000 || c == 0xFEFF
    }

    let duckdbOutOfStep = "quote or comment DuckDB's Unicode space pass misreads";
