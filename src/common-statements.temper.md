# Common Statements

Statements in [the common dialect](common.temper.md): `SELECT`,
`INSERT`, `UPDATE`, and `DELETE`, parsed from the common lexer's tokens
into a tree, with [expressions](common-expressions.temper.md) for their
columns, conditions, and values; the checks a whole statement shows;
and a printer that writes the tree back as canonical common SQL. The
`sql` tag and `QueryBuilder` run all of it when a template is made.

The grammar, with keywords in any case:

```ebnf
statement = select | insert | update | delete | QUERY
select    = "SELECT" ["DISTINCT"] item {"," item}
            ["FROM" source {join}] ["WHERE" expr]
            ["GROUP" "BY" expr {"," expr} ["HAVING" expr]]
            ["ORDER" "BY" order {"," order}] ["LIMIT" count] ["OFFSET" count]
item      = "*" | name "." "*" | expr [["AS"] name]
source    = table [["AS"] name] | subquery ["AS"] name
table     = name ["." name]
join      = ["INNER" | "LEFT" ["OUTER"]] "JOIN" source "ON" expr
          | "CROSS" "JOIN" source
order     = expr ["ASC" | "DESC"] ["NULLS" ("FIRST" | "LAST")]
count     = INTEGER | VALUE_HOLE
insert    = "INSERT" "INTO" table "(" name {"," name} ")"
            ("VALUES" row {"," row} | select | QUERY)
row       = "(" expr {"," expr} ")"
update    = "UPDATE" table "SET" name "=" expr {"," name "=" expr} ["WHERE" expr]
delete    = "DELETE" "FROM" table ["WHERE" expr]
subquery  = "(" (select | QUERY) ")"
```

`QUERY` is a nested query's hole, `${q}`, whose statement goes there
as if written in place; in a subquery and after `INSERT`, it must be a
`SELECT`. Where the databases differ, the parser refuses:

- **`HAVING` without `GROUP BY`**, which SQLite took only from 3.39.
- **Clauses without `FROM`:** `*`, `WHERE`, `GROUP BY`, `ORDER BY`,
  `LIMIT`, and `OFFSET` all need it, since MySQL and MariaDB versions
  differ on which they take without one.
- **Comma joins** (`FROM a, b`), which MySQL groups differently beside
  `JOIN`; write `CROSS JOIN`.
- **A subquery in `FROM` without an alias**, which MySQL and
  PostgreSQL before 16 refuse.
- **`INSERT … (SELECT …)`** in parentheses, which SQLite refuses, and a
  `VALUES` row whose length isn't the column list's.
- **`SET t.c = …`**, which PostgreSQL reads as a field of a column.

`ASC` and `NULLS` follow the [decided rule](../docs/design.md#decided):
without `NULLS`, nulls sort as the smallest values, first going up and
last going down, so `NULLS FIRST` after `ASC` changes nothing, and the
printer leaves it out.

## The tree

Every statement keeps a token for problems, its first, and its depth,
as expressions do.

    sealed interface CommonStatement {
      public get at(): CommonToken;
      public get depth(): Int;
    }

`SELECT`. An item with no expression is `*`, or `t.*` with a table.

    class SelectStatement(
      public at: CommonToken,
      public depth: Int,
      public distinct: Boolean,
      public items: List<SelectItem>,
      public source: CommonSource?,
      public joins: List<CommonJoin>,
      public filter: CommonExpr?,
      public groups: List<CommonExpr>,
      public having: CommonExpr?,
      public orders: List<OrderItem>,
      public limit: CommonExpr?,
      public offset: CommonExpr?,
    ) extends CommonStatement {}

    class SelectItem(
      public at: CommonToken,
      public expr: CommonExpr?,
      public table: CommonName?,
      public alias: CommonName?,
    ) {}

`nullsFirst` is where nulls go, whether written or by the rule.

    class OrderItem(public expr: CommonExpr, public descending: Boolean, public nullsFirst: Boolean) {}

Sources and joins. A table may have a schema, and a subquery always
has an alias.

    sealed interface CommonSource {
      public get at(): CommonToken;
      public get alias(): CommonName?;
    }

    class TableName(public schema: CommonName?, public name: CommonName) {}

    class TableSource(public at: CommonToken, public table: TableName, public alias: CommonName?) extends CommonSource {}

    class QuerySource(public at: CommonToken, public query: SubqueryExpr, public alias: CommonName?) extends CommonSource {}

    class CommonJoin(public at: CommonToken, public kind: Int, public source: CommonSource, public condition: CommonExpr?) {}

    let joinInner = 1;
    let joinLeft = 2;
    let joinCross = 3;

`INSERT`, with rows of values or a query; `UPDATE`, with each column's
new value; and `DELETE`.

    class InsertStatement(
      public at: CommonToken,
      public depth: Int,
      public table: TableName,
      public columns: List<CommonName>,
      public rows: List<List<CommonExpr>>,
      public query: SelectStatement?,
    ) extends CommonStatement {}

    class UpdateStatement(
      public at: CommonToken,
      public depth: Int,
      public table: TableName,
      public columns: List<CommonName>,
      public values: List<CommonExpr>,
      public filter: CommonExpr?,
    ) extends CommonStatement {}

    class DeleteStatement(
      public at: CommonToken,
      public depth: Int,
      public table: TableName,
      public filter: CommonExpr?,
    ) extends CommonStatement {}

## The parser

The statement grammar, over the [expression parser](common-expressions.temper.md)'s
tokens and helpers. The expression parser makes one of these for each
subquery, so the two recurse into each other without either holding
the other.

    class StatementParser(private p: CommonParser) {

`whole` reads the whole template as one statement.

      public whole(): CommonStatement throws Bubble {
        let s = statement();
        let t = p.peek();
        if (t != null) {
          if (p.isSymbol(t, char')')) { p.report("unmatched )", t); }
          unexpected(t, "expected the end of the statement");
          bubble()
        }
        s
      }

      private statement(): CommonStatement throws Bubble {
        let t = p.need("expected a statement");
        if (t.kind == tokenQueryStart) { return nested(); }
        if (p.isKeyword(t, "select")) { return select(); }
        if (p.isKeyword(t, "insert")) { return insert(); }
        if (p.isKeyword(t, "update")) { return update(); }
        if (p.isKeyword(t, "delete")) { return deleteFrom(); }
        unexpected(t, "expected SELECT, INSERT, UPDATE, or DELETE");
        bubble()
      }

A nested query's statement, between its start and end tokens. In a
subquery, or after `INSERT`, it must be a `SELECT`.

      private nested(): CommonStatement throws Bubble {
        let start = p.advance();
        let s = statement();
        ends(start);
        s
      }

      public nestedSelect(): SelectStatement throws Bubble {
        let start = p.advance();
        if (!p.isKeyword(p.peek(), "select")) {
          p.report("nested query isn't a SELECT", start);
          bubble()
        }
        let s = select();
        ends(start);
        s
      }

      private ends(start: CommonToken): Void throws Bubble {
        let end = p.peek();
        if (end == null || end.kind != tokenQueryEnd) {
          p.report("nested query doesn't parse alone", start);
          bubble()
        }
        p.advance();
      }

### SELECT

      public select(): SelectStatement throws Bubble {
        let at = p.advance();
        let distinct = p.isKeyword(p.peek(), "distinct");
        if (distinct) { p.advance(); }
        let items = new ListBuilder<SelectItem>();
        var depth = 0;
        while (true) {
          let item = selectItem();
          items.add(item);
          depth = larger(depth, exprDepth(item.expr));
          if (!p.isSymbol(p.peek(), char',')) { break; }
          p.advance();
        }
        var source: CommonSource? = null;
        let joins = new ListBuilder<CommonJoin>();
        if (p.isKeyword(p.peek(), "from")) {
          p.advance();
          let first = fromSource();
          source = first;
          depth = larger(depth, sourceDepth(first));
          var more = true;
          while (more) {
            let join = joined();
            if (join != null) {
              joins.add(join);
              depth = larger(depth, larger(sourceDepth(join.source), exprDepth(join.condition)));
            } else {
              more = false;
            }
          }
          let comma = p.peek();
          if (p.isSymbol(comma, char',')) {
            p.report("comma joins aren't common SQL; use CROSS JOIN", comma);
            bubble()
          }
        } else {
          for (var i = 0; i < items.length; i += 1) {
            let item = items[i];
            if (item.expr == null) {
              p.report("* without FROM", item.at);
              bubble()
            }
          }
        }
        let hasFrom = source != null;
        var filter: CommonExpr? = null;
        if (clause("where", "WHERE", hasFrom)) {
          let e = p.expression();
          filter = e;
          depth = larger(depth, e.depth);
        }
        let groups = new ListBuilder<CommonExpr>();
        var having: CommonExpr? = null;
        if (clause("group", "GROUP BY", hasFrom)) {
          expectKeyword("by");
          while (true) {
            let e = p.expression();
            groups.add(e);
            depth = larger(depth, e.depth);
            if (!p.isSymbol(p.peek(), char',')) { break; }
            p.advance();
          }
          if (p.isKeyword(p.peek(), "having")) {
            p.advance();
            let e = p.expression();
            having = e;
            depth = larger(depth, e.depth);
          }
        } else if (p.isKeyword(p.peek(), "having")) {
          p.report("HAVING without GROUP BY isn't common SQL", p.peek());
          bubble()
        }
        let orders = new ListBuilder<OrderItem>();
        if (clause("order", "ORDER BY", hasFrom)) {
          expectKeyword("by");
          while (true) {
            let o = orderItem();
            orders.add(o);
            depth = larger(depth, o.expr.depth);
            if (!p.isSymbol(p.peek(), char',')) { break; }
            p.advance();
          }
        }
        var limit: CommonExpr? = null;
        if (clause("limit", "LIMIT", hasFrom)) { limit = count("LIMIT"); }
        var offset: CommonExpr? = null;
        if (clause("offset", "OFFSET", hasFrom)) { offset = count("OFFSET"); }
        new SelectStatement(
          at, depth + 1, distinct, items.toList(), source, joins.toList(), filter, groups.toList(),
          having, orders.toList(), limit, offset,
        )
      }

`clause` takes a clause's first keyword if it's next, refusing it
without `FROM`.

      private clause(word: String, shown: String, hasFrom: Boolean): Boolean throws Bubble {
        let t = p.peek();
        if (!p.isKeyword(t, word)) { return false; }
        if (!hasFrom) {
          p.report("${shown} without FROM isn't common SQL", t);
          bubble()
        }
        p.advance();
        true
      }

      private selectItem(): SelectItem throws Bubble {
        let t = p.need("expected an expression");
        if (p.isSymbol(t, char'*')) {
          p.advance();
          return new SelectItem(t, null, null, null);
        }
        if (nameish(t) && p.isSymbol(p.peekAt(1), char'.') && p.isSymbol(p.peekAt(2), char'*')) {
          let table = p.name();
          p.advance();
          p.advance();
          return new SelectItem(t, null, table, null);
        }
        let e = p.expression();
        var alias: CommonName? = null;
        if (p.isKeyword(p.peek(), "as")) {
          p.advance();
          alias = p.name();
        } else if (nameish(p.peek())) {
          alias = p.name();
        }
        new SelectItem(t, e, null, alias)
      }

A table or a subquery, with its alias.

      private fromSource(): CommonSource throws Bubble {
        let t = p.need("expected a table");
        if (p.isSymbol(t, char'(')) {
          p.advance();
          if (!p.startsQuery(p.peek())) {
            p.report("expected SELECT or a nested query", p.peek());
            bubble()
          }
          let query = p.subquery();
          let alias = sourceAlias();
          if (alias == null) {
            p.report("a subquery in FROM needs an alias", t);
            bubble()
          }
          return new QuerySource(t, query, alias);
        }
        let table = tableName();
        new TableSource(t, table, sourceAlias())
      }

      private sourceAlias(): CommonName? throws Bubble {
        if (p.isKeyword(p.peek(), "as")) {
          p.advance();
          return p.name();
        }
        if (nameish(p.peek())) { p.name() } else { null }
      }

      private tableName(): TableName throws Bubble {
        let first = p.name();
        if (!p.isSymbol(p.peek(), char'.')) { return new TableName(null, first); }
        p.advance();
        let second = p.name();
        let dot = p.peek();
        if (p.isSymbol(dot, char'.')) {
          p.report("name with more than two parts", dot);
          bubble()
        }
        new TableName(first, second)
      }

A join, if one is next.

      private joined(): CommonJoin? throws Bubble {
        let t = p.peek();
        if (t != null) { joinedAt(t) } else { null }
      }

      private joinedAt(t: CommonToken): CommonJoin? throws Bubble {
        let word = if (t.kind == tokenKeyword) { t.word } else { "" };
        var kind = joinInner;
        if (word == "inner") {
          p.advance();
        } else if (word == "left") {
          p.advance();
          if (p.isKeyword(p.peek(), "outer")) { p.advance(); }
          kind = joinLeft;
        } else if (word == "cross") {
          p.advance();
          kind = joinCross;
        } else if (word != "join") {
          if (laterMessage(t) != null) {
            unexpected(t, "");
            bubble()
          }
          return null;
        }
        expectKeyword("join");
        let source = fromSource();
        var condition: CommonExpr? = null;
        if (kind == joinCross) {
          let on = p.peek();
          if (p.isKeyword(on, "on")) {
            p.report("CROSS JOIN takes no ON", on);
            bubble()
          }
        } else {
          expectKeyword("on");
          condition = p.expression();
        }
        new CommonJoin(t, kind, source, condition)
      }

      private orderItem(): OrderItem throws Bubble {
        let e = p.expression();
        let t = p.peek();
        var descending = false;
        if (p.isKeyword(t, "asc")) {
          p.advance();
        } else if (p.isKeyword(t, "desc")) {
          p.advance();
          descending = true;
        }
        var nullsFirst = !descending;
        if (p.isKeyword(p.peek(), "nulls")) {
          p.advance();
          let w = p.peek();
          // Nested, since Temper doesn't narrow through `&&` into a branch.
          var word = "";
          if (w != null) {
            if (w.kind == tokenWord) { word = w.word; }
          }
          if (word == "first") {
            nullsFirst = true;
          } else if (word == "last") {
            nullsFirst = false;
          } else {
            p.report("expected FIRST or LAST", w);
            bubble()
          }
          p.advance();
        }
        new OrderItem(e, descending, nullsFirst)
      }

`count` reads a `LIMIT` or `OFFSET` count: an integer, or a value.

      private count(clause: String): CommonExpr throws Bubble {
        let t = p.need("${clause} takes an integer or a value");
        if (t.kind == tokenInteger) {
          p.advance();
          return new LiteralExpr(t, 1, literalInteger);
        }
        if (t.kind == tokenValueHole) {
          p.advance();
          return new ValueExpr(t, 1, p.holes - 1);
        }
        let message = if (t.kind == tokenNameHole) {
          "name where a value goes"
        } else {
          "${clause} takes an integer or a value"
        };
        p.report(message, t);
        bubble()
      }

### INSERT, UPDATE, and DELETE

      private insert(): CommonStatement throws Bubble {
        let at = p.advance();
        expectKeyword("into");
        let table = tableName();
        p.expectSymbol(char'(');
        let columns = new ListBuilder<CommonName>();
        while (true) {
          columns.add(p.name());
          if (!p.isSymbol(p.peek(), char',')) { break; }
          p.advance();
        }
        p.expectSymbol(char')');
        let t = p.peek();
        let rows = new ListBuilder<List<CommonExpr>>();
        var query: SelectStatement? = null;
        var depth = 0;
        if (p.isKeyword(t, "values")) {
          p.advance();
          while (true) {
            let open = p.peek();
            p.expectSymbol(char'(');
            let row = new ListBuilder<CommonExpr>();
            while (true) {
              let e = p.expression();
              row.add(e);
              depth = larger(depth, e.depth);
              if (!p.isSymbol(p.peek(), char',')) { break; }
              p.advance();
            }
            p.expectSymbol(char')');
            if (row.length != columns.length) {
              p.report("VALUES row has ${counted(row.length, "value")} for ${counted(columns.length, "column")}", open);
              bubble()
            }
            rows.add(row.toList());
            if (!p.isSymbol(p.peek(), char',')) { break; }
            p.advance();
          }
        } else if (p.isKeyword(t, "select") || (t != null && t.kind == tokenQueryStart)) {
          let q = if (p.isKeyword(t, "select")) { select() } else { nestedSelect() };
          query = q;
          depth = q.depth;
        } else if (p.isSymbol(t, char'(') && p.startsQuery(p.peekAt(1))) {
          p.report("a query after INSERT goes without parentheses", t);
          bubble()
        } else {
          unexpected(t, "expected VALUES or SELECT");
          bubble()
        }
        new InsertStatement(at, depth + 1, table, columns.toList(), rows.toList(), query)
      }

      private update(): CommonStatement throws Bubble {
        let at = p.advance();
        let table = tableName();
        expectKeyword("set");
        let columns = new ListBuilder<CommonName>();
        let values = new ListBuilder<CommonExpr>();
        var depth = 0;
        while (true) {
          columns.add(p.name());
          let dot = p.peek();
          if (p.isSymbol(dot, char'.')) {
            p.report("SET takes a column without its table", dot);
            bubble()
          }
          p.expectSymbol(char'=');
          let e = p.expression();
          values.add(e);
          depth = larger(depth, e.depth);
          if (!p.isSymbol(p.peek(), char',')) { break; }
          p.advance();
        }
        let filter = where();
        new UpdateStatement(at, larger(depth, exprDepth(filter)) + 1, table, columns.toList(), values.toList(), filter)
      }

      private deleteFrom(): CommonStatement throws Bubble {
        let at = p.advance();
        expectKeyword("from");
        let table = tableName();
        let filter = where();
        new DeleteStatement(at, exprDepth(filter) + 1, table, filter)
      }

      private where(): CommonExpr? throws Bubble {
        if (!p.isKeyword(p.peek(), "where")) { return null; }
        p.advance();
        p.expression()
      }

### Helpers

      private expectKeyword(word: String): Void throws Bubble {
        let t = p.peek();
        if (!p.isKeyword(t, word)) {
          unexpected(t, "expected ${upperWord(word)}");
          bubble()
        }
        p.advance();
      }

`unexpected` reports a token where it doesn't go, saying so plainly
for words saved for constructs planned later.

      private unexpected(t: CommonToken?, message: String): Void {
        p.report(laterMessage(t) ?? message, t);
      }

      private laterMessage(t: CommonToken?): String? {
        var word = "";
        if (t != null) {
          if (t.kind == tokenKeyword) { word = t.word; }
        }
        if (word == "right" || word == "full" || word == "natural") {
          "${upperWord(word)} JOIN isn't in the common dialect yet"
        } else if (word == "using") {
          "USING isn't in the common dialect yet; use ON"
        } else if (
          word == "union" || word == "intersect" || word == "except" || word == "with" ||
            word == "returning" || word == "window"
        ) {
          "${upperWord(word)} isn't in the common dialect yet"
        } else {
          null
        }
      }

      private nameish(t: CommonToken?): Boolean {
        let kind = if (t != null) { t.kind } else { 0 };
        kind == tokenName || kind == tokenQuotedName || kind == tokenWord || kind == tokenNameHole
      }

      private exprDepth(e: CommonExpr?): Int { if (e != null) { e.depth } else { 0 } }

      private sourceDepth(s: CommonSource): Int {
        if (s is QuerySource) { s.query.depth } else { 1 }
      }

      private larger(a: Int, b: Int): Int { if (a > b) { a } else { b } }
    }

`integerValue` is an integer literal's value, up to 100000, which no
column count reaches.

    let integerValue(lexer: CommonLexer, t: CommonToken): Int {
      let text = lexer.runs[t.run];
      var n = 0;
      for (var i = t.begin; i < t.end; i = text.next(i)) {
        if (n > 100000) { return 100000; }
        n = n * 10 + (text[i] - char'0');
      }
      n
    }

`counted` writes a count with a noun, plural or not.

    let counted(n: Int, noun: String): String {
      if (n == 1) { "1 ${noun}" } else { "${n.toString()} ${noun}s" }
    }

`upperWord` writes an ASCII word in capitals.

    let upperWord(word: String): String {
      let out = new StringBuilder();
      for (var i = String.begin; word.hasIndex(i); i = word.next(i)) {
        let c = word[i];
        out.appendCodePoint(if (c >= char'a' && c <= char'z') { c - 32 } else { c }) orelse panic();
      }
      out.toString()
    }

## Checks

What a statement shows about whether it means the same on every
target, on top of each expression's [checks](common-expressions.temper.md#checks).
For every target:

- **Conditions:** `WHERE`, `HAVING`, and `ON` take a condition, not a
  number or text.
- **`LIMIT` and `OFFSET`** take a non-negative integer; SQLite reads a
  negative one as none, and the others refuse it.
- **Constants in `GROUP BY` and `ORDER BY`**, other than an integer
  for a column's place, which PostgreSQL refuses and the others ignore.
- **Grouping:** in a query with `GROUP BY` or an aggregate, a column
  outside an aggregate must be one it groups by, since SQLite (and
  MySQL without `ONLY_FULL_GROUP_BY`) takes any row's value, and the
  others refuse it; `*` too.
- **Aliases:** a `SELECT` alias that names something other than the
  column of its own name, used in `WHERE`, `ON`, `GROUP BY`, `HAVING`,
  or inside an `ORDER BY` expression, since some databases read it as
  the alias and others as a column; alone in `ORDER BY`, every
  database reads it as the alias, if its case matches, but for the
  [output names](#output-names) below.
- **`SELECT DISTINCT … ORDER BY`** something not selected, which SQLite
  takes and the others refuse.
- **Names twice:** a table or alias twice in `FROM`, a column twice in
  an `INSERT` or `SET`, and an `ON` that reads a table joined after it,
  which SQLite takes and the others refuse.

Names match without regard to ASCII case, since MySQL matches column
names and aliases that way.

For MySQL and MariaDB (either profile):

- **`UPDATE … SET`** that reads a column set earlier in the same
  `SET`, since MySQL assigns left to right, where the others read the
  old values.
- **A subquery that reads the table** an `INSERT … VALUES`, `UPDATE`,
  or `DELETE` changes, which MySQL refuses.
- **`LIMIT` in an `IN` subquery**, and **`*` beside other items**,
  which MySQL refuses.
- **`ORDER BY` an alias** that a plain column has, `SELECT a, b AS a
  … ORDER BY a`, which MySQL refuses as ambiguous.

For PostgreSQL, a name alone in `ORDER BY` that it would read
differently, by its [output names](#output-names): an alias that
another item is named too, and a column, where an item is named after
it, in a query whose column it can't qualify.

The checker walks a statement once, through the expression checker,
which holds the holes and targets.

    class StatementChecker(private c: CommonChecker) {

      public statement(s: CommonStatement): Void throws Bubble {
        when (s) {
          is SelectStatement -> do { select(s); };
          is InsertStatement -> insert(s);
          is UpdateStatement -> update(s);
          is DeleteStatement -> deleteFrom(s);
        }
      }

`subquery` checks a subquery in an expression, as its own scope for
aggregates, and gives its kind: its one column's, or unknown. A
subquery in `FROM` is its own scope too, but can't read the columns of
the query it's in. `inSubquery` adds what `IN` refuses.

      public subquery(s: SelectStatement): Int throws Bubble {
        c.subqueries += 1;
        let kind = scoped(s);
        c.subqueries -= 1;
        kind
      }

      private scoped(s: SelectStatement): Int throws Bubble {
        let saved = c.aggregates;
        c.aggregates = 0;
        let kind = select(s);
        c.aggregates = saved;
        kind
      }

      public inSubquery(s: SelectStatement): Void throws Bubble {
        let limit = s.limit;
        if (limit != null) {
          if (mysql()) { c.fail("LIMIT in an IN subquery; MySQL refuses it", limit.at); }
        }
      }

### SELECT

      private select(s: SelectStatement): Int throws Bubble {
        let items = s.items;
        var kind = kindUnknown;
        for (let item of items) {
          let e = item.expr;
          if (e != null) {
            let k = c.check(e);
            if (items.length == 1) { kind = k; }
          } else if (item.table == null && items.length > 1 && mysql()) {
            c.fail("* beside other items; MySQL refuses it; write t.*", item.at);
          }
        }
        sources(s);
        let filter = s.filter;
        if (filter != null) { c.condition(c.check(filter), filter); }
        let groups = s.groups;
        for (let g of groups) {
          c.check(g);
          constant(g, "GROUP BY");
        }
        let having = s.having;
        if (having != null) { c.condition(c.check(having), having); }
        let orders = s.orders;
        for (let o of orders) {
          c.check(o.expr);
          constant(o.expr, "ORDER BY");
        }
        count(s.limit, "LIMIT");
        count(s.offset, "OFFSET");
        aliases(s);
        grouping(s);
        distinctOrder(s);
        kind
      }

The sources, each named once, and the joins' conditions, each reading
only tables joined before it.

      private sources(s: SelectStatement): Void throws Bubble {
        let names = new ListBuilder<String>();
        let first = s.source;
        if (first != null) { source(first, names); }
        let joins = s.joins;
        for (let join of joins) { source(join.source, names); }
        for (var i = 0; i < joins.length; i += 1) {
          let condition = joins[i].condition;
          if (condition != null) {
            c.condition(c.check(condition), condition);
            joinedLater(condition, names, i + 2);
          }
        }
      }

      private source(s: CommonSource, names: ListBuilder<String>): Void throws Bubble {
        var named = s.alias;
        when (s) {
          is QuerySource -> scoped(s.query.query);
          is TableSource -> named = named ?? s.table.name;
        }
        let n = named;
        if (n != null) {
          let name = folded(c.nameText(n));
          for (var i = 0; i < names.length; i += 1) {
            if (names[i] == name) {
              c.fail("${canonicalName(c.nameText(n))} is in FROM twice; give one an alias", n.token);
            }
          }
          names.add(name);
        }
      }

      private joinedLater(e: CommonExpr, names: ListBuilder<String>, from: Int): Void throws Bubble {
        if (e is ColumnExpr) {
          let table = e.table;
          if (table != null) {
            let name = folded(c.nameText(table));
            for (var i = from; i < names.length; i += 1) {
              if (names[i] == name) {
                c.fail("ON reads ${canonicalName(c.nameText(table))}, joined after it; databases differ", e.at);
              }
            }
          }
          return;
        }
        let children = exprChildren(e);
        for (let child of children) { joinedLater(child, names, from); }
      }

A constant item in `GROUP BY` or `ORDER BY`, but an integer, which is
a column's place.

      private constant(e: CommonExpr, clause: String): Void throws Bubble {
        if (e is LiteralExpr && e.literal == literalInteger) { return; }
        if (isConstant(e)) { c.fail("a constant in ${clause}; databases read it differently", e.at); }
      }

      private isConstant(e: CommonExpr): Boolean {
        if (e is ColumnExpr || e is SubqueryExpr) { return false; }
        if (e is CallExpr && CallExpr.isAggregate(e.callee)) { return false; }
        let children = exprChildren(e);
        for (let child of children) {
          if (!isConstant(child)) { return false; }
        }
        true
      }

      private count(e: CommonExpr?, clause: String): Void throws Bubble {
        if (e == null) { return; }
        if (e is ValueExpr) {
          let value = c.holeValue(e.hole);
          let message = if (value is SqlInt) {
            if (value.value < 0.toInt64()) { "${clause} below 0; databases differ" } else { "" }
          } else if (value is SqlText || value is SqlFloat || value is SqlBool) {
            "${c.described(c.valueKind(e.hole))} in ${clause}"
          } else {
            "NULL in ${clause}"
          };
          if (!message.isEmpty) { c.fail(message, e.at); }
        }
      }

Aliases, outside `ORDER BY` or inside its expressions, where an alias
that names something other than its own column could be read as
either.

      private aliases(s: SelectStatement): Void throws Bubble {
        let items = s.items;
        // Each alias that names something else, folded.
        let others = new ListBuilder<String>();
        for (let item of items) {
          let alias = item.alias;
          if (alias != null) {
            let text = c.nameText(alias);
            if (columnName(item.expr) != text) { others.add(folded(text)); }
          }
        }
        let filter = s.filter;
        if (filter != null) { aliasRefs(filter, others); }
        let joins = s.joins;
        for (let join of joins) {
          let condition = join.condition;
          if (condition != null) { aliasRefs(condition, others); }
        }
        let groups = s.groups;
        for (let g of groups) { aliasRefs(g, others); }
        let having = s.having;
        if (having != null) { aliasRefs(having, others); }
        let orders = s.orders;
        for (let o of orders) {
          let e = o.expr;
          if (isBareColumn(e)) {
            orderAlias(s, e);
            if (e is ColumnExpr) { outputNames(s, e); }
          } else {
            aliasRefs(e, others);
          }
        }
      }

      private aliasRefs(e: CommonExpr, others: ListBuilder<String>): Void throws Bubble {
        if (others.isEmpty) { return; }
        if (e is ColumnExpr) {
          if (e.table == null) {
            let name = folded(c.nameText(e.column));
            for (var i = 0; i < others.length; i += 1) {
              if (others[i] == name) {
                c.fail("${columnText(e)} is also a SELECT alias; databases differ on which it means", e.at);
              }
            }
          }
          return;
        }
        if (e is SubqueryExpr) { return; }
        let children = exprChildren(e);
        for (let child of children) { aliasRefs(child, others); }
      }

`columnName` is a column's name, without its table, or else "".

      private columnName(e: CommonExpr?): String {
        if (e is ColumnExpr) { c.nameText(e.column) } else { "" }
      }

      private isBareColumn(e: CommonExpr): Boolean {
        if (e is ColumnExpr) { e.table == null } else { false }
      }

A bare name in `ORDER BY` is an alias if one matches it exactly; one
that matches only without regard to case, or matches two, is refused.

      private orderAlias(s: SelectStatement, e: CommonExpr): Void throws Bubble {
        let text = columnName(e);
        let name = folded(text);
        var exact = 0;
        var loose = 0;
        let items = s.items;
        for (let item of items) {
          let alias = item.alias;
          if (alias != null) {
            let a = c.nameText(alias);
            if (a == text) { exact += 1; }
            if (folded(a) == name) { loose += 1; }
          }
        }
        if (loose > 1) {
          c.fail("${canonicalName(text)} matches more than one SELECT alias", e.at);
        } else if (loose == 1 && exact == 0) {
          c.fail("${canonicalName(text)} matches a SELECT alias only without regard to case; databases differ", e.at);
        }
      }

A bare name in `ORDER BY` that a database would read as another item,
by its [output names](#output-names). Rendering qualifies a column for
PostgreSQL where it can: in a query with one source and no outer
query, whose columns a bare name could be.

      private outputNames(s: SelectStatement, e: ColumnExpr): Void throws Bubble {
        let names = new OutputNames(c.lexer, c.holes);
        let name = canonicalName(c.nameText(e.column));
        if (postgres()) {
          let clash = names.postgresClash(s, e);
          if (clash == clashAlias) {
            c.fail("ORDER BY ${name} is ambiguous for postgres, which names another SELECT item ${name} too; rename the alias", e.at);
          } else if (clash == clashColumn && !canQualify(s)) {
            c.fail("ORDER BY ${name} would mean a SELECT item for postgres, which names one ${name}; write the column's table", e.at);
          }
        }
        if (mysql() && names.mysqlClash(s, e)) {
          c.fail("ORDER BY ${name} is ambiguous for mysql, which names another SELECT item ${name} too; rename the alias", e.at);
        }
      }

      private canQualify(s: SelectStatement): Boolean {
        c.subqueries == 0 && s.source != null && s.joins.isEmpty
      }

      private isOrderAlias(s: SelectStatement, e: CommonExpr): Boolean {
        if (isBareColumn(e)) {
          let text = columnName(e);
          let items = s.items;
          for (let item of items) {
            let alias = item.alias;
            if (alias != null && c.nameText(alias) == text) { return true; }
          }
        }
        false
      }

Grouping: in a query that groups or aggregates, every column outside
an aggregate must be grouped by. A `GROUP BY` position stands for its
item.

      private grouping(s: SelectStatement): Void throws Bubble {
        let items = s.items;
        let orders = s.orders;
        let written = s.groups;
        let groups = new ListBuilder<CommonExpr>();
        for (let g of written) {
          let place = position(g);
          let item = if (place >= 1 && place <= items.length) { items[place - 1].expr } else { null };
          groups.add(item ?? g);
        }
        var grouped = !groups.isEmpty || s.having != null;
        for (var i = 0; i < items.length; i += 1) {
          let e = items[i].expr;
          if (e != null && hasAggregate(e)) { grouped = true; }
        }
        for (let o of orders) {
          if (hasAggregate(o.expr)) { grouped = true; }
        }
        if (!grouped) { return; }
        let keys = new ListBuilder<String>();
        for (var i = 0; i < groups.length; i += 1) { keys.add(key(groups[i])); }
        for (var i = 0; i < items.length; i += 1) {
          let e = items[i].expr;
          if (e == null) {
            c.fail("* in a grouped query; databases differ", items[i].at);
          } else {
            ungrouped(e, keys, groups);
          }
        }
        let having = s.having;
        if (having != null) { ungrouped(having, keys, groups); }
        for (let o of orders) {
          let e = o.expr;
          if (position(e) < 0 && !isOrderAlias(s, e)) { ungrouped(e, keys, groups); }
        }
      }

`position` is an integer literal's value, as a column's place, or -1.

      private position(e: CommonExpr): Int {
        if (e is LiteralExpr && e.literal == literalInteger) { integerValue(c.lexer, e.at) } else { -1 }
      }

      private ungrouped(e: CommonExpr, keys: ListBuilder<String>, groups: ListBuilder<CommonExpr>): Void throws Bubble {
        if (e is SubqueryExpr) { return; }
        if (e is CallExpr && CallExpr.isAggregate(e.callee)) { return; }
        if (!keys.isEmpty) {
          let k = key(e);
          for (var i = 0; i < keys.length; i += 1) {
            if (keys[i] == k) { return; }
          }
        }
        if (e is ColumnExpr) {
          if (!groupedColumn(e, groups)) {
            c.fail("${columnText(e)} is neither grouped nor aggregated; databases differ", e.at);
          }
          return;
        }
        let children = exprChildren(e);
        for (let child of children) { ungrouped(child, keys, groups); }
      }

A column is grouped by if `GROUP BY` names the same column, with the
same table or with a table on only one side.

      private groupedColumn(e: ColumnExpr, groups: ListBuilder<CommonExpr>): Boolean {
        let column = c.nameText(e.column);
        let table = e.table;
        for (var i = 0; i < groups.length; i += 1) {
          let g = groups[i];
          if (g is ColumnExpr) {
            if (c.nameText(g.column) == column && sameTable(table, g.table)) { return true; }
          }
        }
        false
      }

      private sameTable(a: CommonName?, b: CommonName?): Boolean {
        if (a != null) {
          if (b != null) { return c.nameText(a) == c.nameText(b); }
        }
        true
      }

      private hasAggregate(e: CommonExpr): Boolean {
        if (e is SubqueryExpr) { return false; }
        if (e is CallExpr && CallExpr.isAggregate(e.callee)) { return true; }
        let children = exprChildren(e);
        for (let child of children) {
          if (hasAggregate(child)) { return true; }
        }
        false
      }

With `DISTINCT`, each `ORDER BY` item is a column's place, an alias,
an item itself, or a column when the items have `*`.

      private distinctOrder(s: SelectStatement): Void throws Bubble {
        let orders = s.orders;
        if (!s.distinct || orders.isEmpty) { return; }
        let items = s.items;
        let keys = new ListBuilder<String>();
        var star = false;
        for (let item of items) {
          let e = item.expr;
          if (e != null) { keys.add(key(e)); } else { star = true; }
        }
        for (let o of orders) {
          let e = o.expr;
          var listed = (e is LiteralExpr && e.literal == literalInteger) || isOrderAlias(s, e) ||
            (star && e is ColumnExpr);
          if (!listed) {
            let k = key(e);
            for (var j = 0; j < keys.length; j += 1) {
              if (keys[j] == k) { listed = true; }
            }
          }
          if (!listed) {
            c.fail("ORDER BY item not in the SELECT DISTINCT list; databases differ", e.at);
          }
        }
      }

### INSERT, UPDATE, and DELETE

      private insert(s: InsertStatement): Void throws Bubble {
        twice(s.columns, "listed");
        let rows = s.rows;
        for (let row of rows) {
          for (var j = 0; j < row.length; j += 1) {
            c.check(row[j]);
            if (mysql()) { reads(row[j], s.table, "INSERT"); }
          }
        }
        let query = s.query;
        if (query != null) { select(query); }
      }

      private update(s: UpdateStatement): Void throws Bubble {
        twice(s.columns, "set");
        let columns = s.columns;
        let values = s.values;
        for (let value of values) { c.check(value); }
        let filter = s.filter;
        if (filter != null) { c.condition(c.check(filter), filter); }
        if (!mysql()) { return; }
        let set = new ListBuilder<String>();
        let table = folded(c.nameText(s.table.name));
        for (var i = 0; i < values.length; i += 1) {
          setEarlier(values[i], set, table);
          set.add(folded(c.nameText(columns[i])));
          reads(values[i], s.table, "UPDATE");
        }
        if (filter != null) { reads(filter, s.table, "UPDATE"); }
      }

      private deleteFrom(s: DeleteStatement): Void throws Bubble {
        let filter = s.filter;
        if (filter != null) {
          c.condition(c.check(filter), filter);
          if (mysql()) { reads(filter, s.table, "DELETE"); }
        }
      }

      private twice(columns: List<CommonName>, verb: String): Void throws Bubble {
        for (var i = 0; i < columns.length; i += 1) {
          let name = folded(c.nameText(columns[i]));
          for (var j = 0; j < i; j += 1) {
            if (folded(c.nameText(columns[j])) == name) {
              c.fail("column ${canonicalName(c.nameText(columns[i]))} ${verb} twice", columns[i].token);
            }
          }
        }
      }

`setEarlier` refuses a column, in an `UPDATE`'s new value, that the
same `SET` assigned before it, looking into subqueries too: a column
there with no table, or the updated table's, may be that column.

      private setEarlier(e: CommonExpr, set: ListBuilder<String>, table: String): Void throws Bubble {
        if (set.isEmpty) { return; }
        if (e is ColumnExpr) {
          let qualifier = e.table;
          if (qualifier == null || folded(c.nameText(qualifier)) == table) {
            let name = folded(c.nameText(e.column));
            for (var i = 0; i < set.length; i += 1) {
              if (set[i] == name) {
                c.fail("${columnText(e)} was set earlier in this SET; MySQL assigns left to right", e.at);
              }
            }
          }
          return;
        }
        let children = deepChildren(e);
        for (let child of children) { setEarlier(child, set, table); }
      }

`reads` refuses a subquery in `e` that reads `table`, however deep.

      private reads(e: CommonExpr, table: TableName, verb: String): Void throws Bubble {
        if (e is SubqueryExpr) {
          let name = folded(c.nameText(table.name));
          let query = e.query;
          let sources = new ListBuilder<CommonSource>();
          let first = query.source;
          if (first != null) { sources.add(first); }
          for (let join of query.joins) { sources.add(join.source); }
          for (var i = 0; i < sources.length; i += 1) {
            let source = sources[i];
            if (source is TableSource) {
              let read = source.table.name;
              if (folded(c.nameText(read)) == name) {
                c.fail(
                  "a subquery reads ${canonicalName(c.nameText(table.name))}, which this ${verb} changes; MySQL refuses it",
                  read.token,
                );
              }
            }
          }
        }
        let children = deepChildren(e);
        for (let child of children) { reads(child, table, verb); }
      }

### Helpers

      private mysql(): Boolean { targets("mysql") }

      private postgres(): Boolean { targets("postgres") }

      private targets(lexing: String): Boolean {
        let targets = c.targets;
        for (let d of targets) {
          if (lexingName(d) == lexing) { return true; }
        }
        false
      }

`key` is an expression's canonical text, to find the same expression
written twice: a name hole as its name, and each value hole as itself
alone, since its value could differ.

      private key(e: CommonExpr): String {
        let printed = new CommonPrinter(c.lexer, true).print(e);
        let out = new StringBuilder();
        let runs = printed.runs;
        for (var i = 0; i < runs.length; i += 1) {
          out.append(runs[i]);
          if (i < printed.holes.length) {
            let hole = printed.holes[i];
            let part = c.holes[hole];
            if (part is QueryName) {
              out.append(canonicalName(part.name.name));
            } else {
              out.append("\${${hole.toString()}}");
            }
          }
        }
        out.toString()
      }

      private columnText(e: ColumnExpr): String {
        let table = e.table;
        let column = canonicalName(c.nameText(e.column));
        if (table != null) { "${canonicalName(c.nameText(table))}.${column}" } else { column }
      }
    }

`exprChildren` lists an expression's operands, but not what's inside
a subquery; `deepChildren` adds each subquery's expressions, and its
sources' subqueries.

    let exprChildren(e: CommonExpr): List<CommonExpr> {
      let out = new ListBuilder<CommonExpr>();
      when (e) {
        is ExistsExpr -> out.add(e.query);
        is UnaryExpr -> out.add(e.operand);
        is BinaryExpr -> do {
          out.add(e.left);
          out.add(e.right);
        };
        is ChainExpr -> do {
          for (let operand of e.operands) { out.add(operand); }
        };
        is IsNullExpr -> out.add(e.operand);
        is InListExpr -> do {
          out.add(e.operand);
          for (let item of e.items) { out.add(item); }
        };
        is InQueryExpr -> do {
          out.add(e.operand);
          out.add(e.query);
        };
        is BetweenExpr -> do {
          out.add(e.operand);
          out.add(e.low);
          out.add(e.high);
        };
        is LikeExpr -> do {
          out.add(e.operand);
          out.add(e.pattern);
        };
        is CaseExpr -> do {
          let subject = e.subject;
          if (subject != null) { out.add(subject); }
          let thens = e.thens;
          var i = 0;
          for (let w of e.whens) {
            out.add(w);
            out.add(thens[i]);
            i += 1;
          }
          let otherwise = e.otherwise;
          if (otherwise != null) { out.add(otherwise); }
        };
        is CastExpr -> out.add(e.operand);
        is CallExpr -> do {
          for (let arg of e.args) { out.add(arg); }
        };
      }
      out.toList()
    }

    let deepChildren(e: CommonExpr): List<CommonExpr> {
      if (e is SubqueryExpr) { subqueryChildren(e.query) } else { exprChildren(e) }
    }

    let subqueryChildren(s: SelectStatement): List<CommonExpr> {
      let out = new ListBuilder<CommonExpr>();
      for (let item of s.items) {
        let x = item.expr;
        if (x != null) { out.add(x); }
      }
      let sources = new ListBuilder<CommonSource>();
      let first = s.source;
      if (first != null) { sources.add(first); }
      for (let join of s.joins) {
        sources.add(join.source);
        let condition = join.condition;
        if (condition != null) { out.add(condition); }
      }
      for (var i = 0; i < sources.length; i += 1) {
        let source = sources[i];
        if (source is QuerySource) { out.add(source.query); }
      }
      let filter = s.filter;
      if (filter != null) { out.add(filter); }
      for (let g of s.groups) { out.add(g); }
      let having = s.having;
      if (having != null) { out.add(having); }
      for (let o of s.orders) { out.add(o.expr); }
      out.toList()
    }

`folded` lowercases a name's ASCII letters, to compare names as MySQL
does.

    let folded(name: String): String {
      let out = new StringBuilder();
      for (var i = String.begin; name.hasIndex(i); i = name.next(i)) {
        out.appendCodePoint(lowercased(name[i])) orelse panic();
      }
      out.toString()
    }

## Output names

Every `SELECT` item has an output name, and a name alone in `ORDER BY`
can mean one, but the databases name items differently. SQLite and
DuckDB match only an alias there, and otherwise read a column, so they
read it as the common dialect does. PostgreSQL matches an unaliased
item too, by the name it gives it, which can be a column's:

- a column, `t.c`, is named `c`;
- a function call is named after the function, as PostgreSQL writes
  it: `length`, `count`, `coalesce`, and `btrim` for `TRIM`;
- a cast takes its operand's name, if that's a column's, a
  function's, or a subquery's, and else its type's (`int8`, `float8`,
  or `text`), as does a value alone, which rendering casts;
- `CASE` takes its `ELSE` result's name, the same way, or else `case`;
- `EXISTS` is named `exists`, and a subquery after its one item;
- `TRUE` and `FALSE` are taken as `bool`, as older PostgreSQL
  versions name them, which wrote them as casts;
- anything else, such as an operator, is `?column?`.

So `SELECT id, CAST(id AS DOUBLE) … ORDER BY id` has two items named
`id`, which PostgreSQL refuses as ambiguous, and `SELECT CAST(score AS
TEXT) … ORDER BY score` sorts by text there. Rendering for PostgreSQL
writes such a column with its source's name, `people.id`, which always
means the column. Items that are the same column don't count, since
PostgreSQL takes those as one.

Where the common dialect reads an alias, another item of that name
makes PostgreSQL refuse it as ambiguous: `SELECT id, score AS id …
ORDER BY id`. MySQL matches items by name too, without regard to
case, but names an unaliased expression after its text, so only plain
columns clash there: it refuses the same query, but takes `score + 0
AS id` beside `id`, as the alias. The checks refuse both.

A `*` brings columns this can't see. PostgreSQL and MySQL refuse an
alias that one of them has, as with `SELECT t.*, score AS id`, but
the star's own columns are no trouble, since a qualified name means
the same column.

`OutputNames` works these out for the checks and the printer, from
the lexer's text and the holes' names and values.

    let clashNone = 0;
    let clashColumn = 1;
    let clashAlias = 2;

    class OutputNames(private lexer: CommonLexer, private holes: List<QueryPart>) {
      // The name `figure` found last.
      private var figured: String = "";

`postgresClash` says how PostgreSQL would read a bare name alone in
`ORDER BY` differently: `clashColumn` for a column, where it would read
an item named after it, and `clashAlias` for an alias, where another
item has its name; `clashNone` if it reads it as the common dialect
does.

      public postgresClash(s: SelectStatement, e: ColumnExpr): Int {
        if (e.table != null) { return clashNone; }
        let name = nameText(e.column);
        let aliased = aliasedItem(s, name, false);
        let items = s.items;
        for (let item of items) {
          let x = item.expr;
          if (item.alias == null) {
            if (x != null) {
              let output = postgresName(x);
              if (output == name || output.isEmpty) {
                if (aliased != null) {
                  if (!sameColumn(aliased.expr, x)) { return clashAlias; }
                } else if (!(x is ColumnExpr)) {
                  return clashColumn;
                }
              }
            }
          }
        }
        clashNone
      }

`mysqlClash` says whether MySQL would refuse a bare name alone in
`ORDER BY` as ambiguous: an alias of a column, beside another column of
that name.

      public mysqlClash(s: SelectStatement, e: ColumnExpr): Boolean {
        if (e.table != null) { return false; }
        let name = folded(nameText(e.column));
        let aliased = aliasedItem(s, name, true);
        let column = if (aliased != null) { aliased.expr } else { null };
        if (!(column is ColumnExpr)) { return false; }
        let items = s.items;
        for (let item of items) {
          let x = item.expr;
          if (item.alias == null) {
            if (x is ColumnExpr) {
              if (folded(nameText(x.column)) == name && !sameColumn(column, x)) { return true; }
            }
          }
        }
        false
      }

`aliasedItem` is the item with an alias `name`, folded or not, if any.

      private aliasedItem(s: SelectStatement, name: String, fold: Boolean): SelectItem? {
        let items = s.items;
        for (let item of items) {
          let alias = item.alias;
          if (alias != null) {
            let text = nameText(alias);
            if ((if (fold) { folded(text) } else { text }) == name) { return item; }
          }
        }
        null
      }

Two columns are the same if their names are, with the same table or a
table on only one side.

      private sameColumn(a: CommonExpr?, b: CommonExpr): Boolean {
        if (a is ColumnExpr) {
          if (b is ColumnExpr) {
            if (nameText(a.column) != nameText(b.column)) { return false; }
            let x = a.table;
            let y = b.table;
            if (x != null) {
              if (y != null) { return nameText(x) == nameText(y); }
            }
            return true;
          }
        }
        false
      }

`postgresName` is an unaliased item's name in PostgreSQL, or "" when
it can't be known, for a subquery whose first item is a `*`.

      public postgresName(e: CommonExpr): String {
        if (e is ValueExpr) { return postgresTypeNames[valueCast(e.hole)]; }
        figured = "?column?";
        figure(e);
        figured
      }

`figure` follows PostgreSQL's `FigureColname`: it sets `figured` and
gives how strong the name is, 2 for a column's, a function's, or a
subquery's, 1 for a type's or `case`, and 0, leaving `figured` alone,
for none. A cast or `CASE` takes the name inside it only if that's
strong.

      private figure(e: CommonExpr): Int {
        when (e) {
          is ColumnExpr -> do {
            figured = nameText(e.column);
            2
          };
          is CallExpr -> do {
            figured = postgresFunctionNames[e.callee];
            2
          };
          is CastExpr -> do {
            let strength = figure(e.operand);
            if (strength <= 1) {
              figured = postgresTypeNames[e.target];
              1
            } else {
              strength
            }
          };
          is CaseExpr -> do {
            let otherwise = e.otherwise;
            let strength = if (otherwise != null) { figure(otherwise) } else { 0 };
            if (strength <= 1) {
              figured = "case";
              1
            } else {
              strength
            }
          };
          is SubqueryExpr -> do {
            let first = e.query.items[0];
            let alias = first.alias;
            let x = first.expr;
            figured = if (alias != null) {
              nameText(alias)
            } else if (x != null) {
              new OutputNames(lexer, holes).postgresName(x)
            } else {
              ""
            };
            2
          };
          is ExistsExpr -> do {
            figured = "exists";
            2
          };
          is LiteralExpr -> if (e.literal == literalTrue || e.literal == literalFalse) {
            figured = "bool";
            1
          } else {
            0
          };
          else -> 0;
        }
      }

`valueCast` is the cast a value alone gets, as rendering writes it:
to its type, or `TEXT` for `NULL`.

      private valueCast(hole: Int): Int {
        let part = if (hole >= 0 && hole < holes.length) { holes[hole] } else { null };
        let value = if (part is QueryParam) { part.value } else { null };
        when (value) {
          is SqlInt -> castInteger;
          is SqlFloat -> castDouble;
          is SqlBool -> castBoolean;
          else -> castText;
        }
      }

      public nameText(n: CommonName): String {
        if (n.hole >= 0 && n.hole < holes.length) {
          let part = holes[n.hole];
          if (part is QueryName) { return part.name.name; }
        }
        lexer.nameValue(n.token)
      }
    }

PostgreSQL's names for the common functions, as it writes them in
lowercase, and for the types rendering casts to, by the cast numbers,
with `bool` after them for a value's boolean.

    let postgresFunctionNames: List<String> = [
      "", "abs", "avg", "coalesce", "count", "length", "lower", "max", "min", "nullif", "replace",
      "substr", "sum", "btrim", "upper",
    ];

    let castBoolean = 4;

    let postgresTypeNames: List<String> = ["", "int8", "float8", "text", "bool"];

## Printing

The statement printer writes through an expression
[printer](common-expressions.temper.md#printing), canonically:
keywords in capitals, `JOIN` and `LEFT JOIN` for the joins, `AS` before
every alias, no `ASC`, and `NULLS` only where the rule doesn't already
put them. For a target database, it writes `NULLS` and `OFFSET` as
[rendering](common-rendering.temper.md) says.

    class StatementPrinter(private p: CommonPrinter) {

      public statement(s: CommonStatement): Void {
        when (s) {
          is SelectStatement -> select(s);
          is InsertStatement -> insert(s);
          is UpdateStatement -> update(s);
          is DeleteStatement -> deleteFrom(s);
        }
      }

      public select(s: SelectStatement): Void {
        p.text(if (s.distinct) { "SELECT DISTINCT " } else { "SELECT " });
        var first = true;
        for (let item of s.items) {
          if (!first) { p.text(", "); }
          first = false;
          let e = item.expr;
          if (e != null) {
            p.item(e);
            alias(item.alias);
          } else {
            let table = item.table;
            if (table != null) {
              p.name(table);
              p.text(".");
            }
            p.text("*");
          }
        }
        let source = s.source;
        if (source != null) {
          p.text(" FROM ");
          fromSource(source);
        }
        for (let join of s.joins) {
          let kind = join.kind;
          p.text(if (kind == joinLeft) { " LEFT JOIN " } else if (kind == joinCross) { " CROSS JOIN " } else { " JOIN " });
          fromSource(join.source);
          let condition = join.condition;
          if (condition != null) {
            p.text(" ON ");
            p.write(condition, 0);
          }
        }
        clause(" WHERE ", s.filter);
        if (!s.groups.isEmpty) {
          p.text(" GROUP BY ");
          list(s.groups);
        }
        clause(" HAVING ", s.having);
        if (!s.orders.isEmpty) {
          p.text(" ORDER BY ");
          var firstOrder = true;
          for (let o of s.orders) {
            if (!firstOrder) { p.text(", "); }
            firstOrder = false;
            order(s, o);
          }
        }
        let t = p.target;
        if (t != null) {
          if (s.limit == null && s.offset != null && !t.noLimit.isEmpty) { p.text(" LIMIT ${t.noLimit}"); }
        }
        clause(" LIMIT ", s.limit);
        clause(" OFFSET ", s.offset);
      }

An `ORDER BY` item, with `NULLS` written where the database's own
order differs from the rule's, and on MySQL, which has no `NULLS`,
`x IS NULL` before it instead, where its order differs.

      private order(s: SelectStatement, o: OrderItem): Void {
        let t = p.target;
        let nulls = if (t != null) { t.nulls } else { nullsSmallest };
        let differs = if (nulls == nullsLargest) {
          o.nullsFirst != o.descending
        } else if (nulls == nullsWritten) {
          true
        } else {
          o.nullsFirst == o.descending
        };
        if (differs && nulls == nullsEmulated) {
          let key = nullsKey(s, o.expr);
          if (key != null) {
            p.write(key, levelConcat);
            p.text(if (o.descending) { " IS NULL DESC, " } else { " IS NULL, " });
          } else {
            p.fail("NULLS FIRST or LAST on the place of a * in ORDER BY, for mysql");
          }
        }
        let qualifier = postgresQualifier(s, o.expr);
        if (qualifier != null) {
          p.name(qualifier);
          p.text(".");
        }
        p.write(o.expr, 0);
        if (o.descending) { p.text(" DESC"); }
        if (differs && nulls != nullsEmulated) {
          p.text(if (o.nullsFirst) { " NULLS FIRST" } else { " NULLS LAST" });
        }
      }

`postgresQualifier` is the table or alias to write before a bare
column in `ORDER BY` for PostgreSQL, where it would otherwise read an
item named after the column, or null. The checks refuse such a column
where the query's only source can't be the table.

      private postgresQualifier(s: SelectStatement, e: CommonExpr): CommonName? {
        let t = p.target;
        if (t == null || lexingName(t.dialect) != "postgres") { return null; }
        if (!(e is ColumnExpr) || p.subqueries > 0 || !s.joins.isEmpty) { return null; }
        if (e is ColumnExpr) {
          if (new OutputNames(p.lexer, p.values).postgresClash(s, e) != clashColumn) { return null; }
        }
        let source = s.source;
        if (source is TableSource) {
          source.alias ?? source.table.name
        } else if (source != null) {
          source.alias
        } else {
          null
        }
      }

`nullsKey` is what an `ORDER BY` item sorts by, for `IS NULL`: the
`SELECT` item that a place (`ORDER BY 2`) or an alias stands for, or
else the item itself; null for the place of a `*`.

      private nullsKey(s: SelectStatement, e: CommonExpr): CommonExpr? {
        let items = s.items;
        if (e is LiteralExpr && e.literal == literalInteger) {
          let place = integerValue(p.lexer, e.at);
          // Past the items, it's for the database to refuse.
          return if (place >= 1 && place <= items.length) { items[place - 1].expr } else { e };
        }
        if (e is ColumnExpr) {
          if (e.table == null) {
            let name = p.nameText(e.column);
            for (let item of items) {
              let alias = item.alias;
              if (alias != null) {
                if (p.nameText(alias) == name) { return item.expr; }
              }
            }
          }
        }
        e
      }

      private insert(s: InsertStatement): Void {
        p.text("INSERT INTO ");
        tableName(s.table);
        p.text(" (");
        names(s.columns);
        p.text(")");
        let query = s.query;
        if (query != null) {
          p.text(" ");
          select(query);
          return;
        }
        p.text(" VALUES ");
        var first = true;
        for (let row of s.rows) {
          if (!first) { p.text(", "); }
          first = false;
          p.text("(");
          list(row);
          p.text(")");
        }
      }

      private update(s: UpdateStatement): Void {
        p.text("UPDATE ");
        tableName(s.table);
        p.text(" SET ");
        let values = s.values;
        var i = 0;
        for (let column of s.columns) {
          if (i > 0) { p.text(", "); }
          p.name(column);
          p.text(" = ");
          p.write(values[i], 0);
          i += 1;
        }
        clause(" WHERE ", s.filter);
      }

      private deleteFrom(s: DeleteStatement): Void {
        p.text("DELETE FROM ");
        tableName(s.table);
        clause(" WHERE ", s.filter);
      }

      private fromSource(s: CommonSource): Void {
        when (s) {
          is TableSource -> tableName(s.table);
          // Not through `p.write`, since it's no subquery in an
          // expression: its names can't be an outer query's columns.
          is QuerySource -> do {
            p.text("(");
            select(s.query.query);
            p.text(")");
          };
        }
        alias(s.alias);
      }

      private tableName(t: TableName): Void {
        let schema = t.schema;
        if (schema != null) {
          p.name(schema);
          p.text(".");
        }
        p.name(t.name);
      }

      private alias(a: CommonName?): Void {
        if (a != null) {
          p.text(" AS ");
          p.name(a);
        }
      }

      private clause(keyword: String, e: CommonExpr?): Void {
        if (e != null) {
          p.text(keyword);
          p.write(e, 0);
        }
      }

      private list(items: List<CommonExpr>): Void {
        var first = true;
        for (let e of items) {
          if (!first) { p.text(", "); }
          first = false;
          p.write(e, 0);
        }
      }

      private names(items: List<CommonName>): Void {
        var first = true;
        for (let n of items) {
          if (!first) { p.text(", "); }
          first = false;
          p.name(n);
        }
      }
    }

## Queries

What the [builder](query.temper.md) and `Query` use. `commonTargets`
are the default targets: every profile.

    let commonTargets(): List<Dialect> {
      [Dialect.sqlite, Dialect.postgres, Dialect.mysql, Dialect.mysqlNoBackslashEscapes, Dialect.duckdb]
    }

`commonCheck` checks a whole template, already lexed, for its
targets: its end, its strings and names, then its grammar, then the
checks. It gives the first problem, or else the tree, for the query
the builder makes, with its own copy of the lexer's text.

    let commonCheck(
      lexer: CommonLexer,
      parts: List<QueryPart>,
      holes: List<QueryPart>,
      targets: List<Dialect>,
    ): CommonCheck {
      var problem = lexer.endProblem() ?? lexer.targetProblem(targets);
      var common: CommonQuery? = null;
      if (problem == null) {
        let parser = new CommonParser(lexer);
        let tree: CommonStatement? = parser.parseStatement() orelse null;
        if (tree != null) {
          let checker = new CommonChecker(lexer, holes, targets);
          let checked = do {
            new StatementChecker(checker).statement(tree);
            true
          } orelse false;
          if (checked) {
            common = new CommonQuery(lexer.frozen(), tree, holes, null);
          } else {
            problem = checker.problem ?? "fails";
          }
        } else {
          problem = parser.problem ?? "fails";
        }
      }
      new CommonCheck(parts, targets, common, problem)
    }

A common `Query` keeps a `CommonQuery`: its tree, or the problem that
stopped its parse, and its holes. It's a `TemplateCheck`, an exported
type, so `Query`'s constructor can take one.

    class CommonQuery(
      public lexer: CommonLexer,
      public statement: CommonStatement?,
      public holes: List<QueryPart>,
      public problem: String?,
    ) extends TemplateCheck {

`renderedFor` writes the tree for a dialect, in parts: text, with each
name hole's name written in it, and each value as a `QueryParam`. For
`Dialect.common` it's canonical common SQL; for a database, its SQL,
with the problem, if any, that kept it from being written.

      public renderedFor(dialect: Dialect): WrittenQuery {
        let out = new ListBuilder<QueryPart>();
        let s = statement;
        if (s == null) { return new WrittenQuery(out.toList(), problem ?? "fails"); }
        let common = dialect.name == "common";
        let printer = new CommonPrinter(lexer, !common);
        if (!common) { printer.target = commonTarget(dialect); }
        printer.values = holes;
        // `?? panic()`, since Temper doesn't narrow after an early return.
        let printed = printer.printStatement(s ?? panic());
        var text = new StringBuilder();
        let runs = printed.runs;
        for (var i = 0; i < runs.length; i += 1) {
          text.append(runs[i]);
          if (i < printed.holes.length) {
            let part = holes[printed.holes[i]];
            if (part is QueryName) {
              let name = part.name.name;
              text.append(if (common) { canonicalName(name) } else { dialect.quoteName(name) orelse panic() });
            } else {
              out.add(new QueryText(text.toString()));
              text = new StringBuilder();
              out.add(part);
            }
          }
        }
        out.add(new QueryText(text.toString()));
        new WrittenQuery(out.toList(), printer.problem)
      }
    }

`parsedCommon` parses a common query's parts, without the checks.

    let parsedCommon(parts: List<QueryPart>): CommonQuery {
      let lexer = new CommonLexer();
      let holes = new ListBuilder<QueryPart>();
      var problem: String? = null;
      for (let part of parts) {
        var found: String? = null;
        if (part is QueryText) {
          found = lexer.scan(part.text);
        } else if (!lexer.inCode) {
          found = lexer.locate("hole inside a quote or comment");
        } else if (part is QueryParam) {
          holes.add(part);
          found = lexer.hole(holeValue);
        } else if (part is QueryName) {
          holes.add(part);
          found = lexer.hole(holeName);
        }
        if (problem == null) { problem = found; }
      }
      if (lexer.inLineComment) { lexer.scan("\n"); }
      if (problem == null) { problem = lexer.endProblem(); }
      var tree: CommonStatement? = null;
      if (problem == null) {
        let parser = new CommonParser(lexer);
        let parsed: CommonStatement? = parser.parseStatement() orelse null;
        tree = parsed;
        if (parsed == null) { problem = parser.problem ?? "fails"; }
      }
      new CommonQuery(lexer, tree, holes.toList(), problem)
    }
