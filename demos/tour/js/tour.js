// A tour of Wherewith's whole public API, from JavaScript.
//
// The same tour exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: setup
import { Dialect, Identifier, PlaceholderStyle, QueryBuilder, identifierProblem } from "wherewith";

// Each database, with a placeholder style its drivers take.
const databases = [
  ["sqlite", Dialect.sqlite, PlaceholderStyle.question],
  ["postgres", Dialect.postgres, PlaceholderStyle.dollarNumbered],
  ["mysql", Dialect.mysql, PlaceholderStyle.percentS],
  ["duckdb", Dialect.duckdb, PlaceholderStyle.dollarNumbered],
];

function forEachDatabase(q) {
  for (const [name, dialect, style] of databases) {
    console.log(`${name}: ${q.render(dialect, style).sql}`);
  }
}

// A common query is a QueryBuilder for Dialect.common: SQL text with
// appendSafe, and values, names, and other queries in holes between. In
// Temper, sql"…" builds the same.
function common(text) {
  const b = new QueryBuilder(Dialect.common);
  b.appendSafe(text);
  return b;
}
// end snippet

function section(title) {
  console.log();
  console.log(`## ${title}`);
}

console.log("# Wherewith tour");

section("1. Write it once");

// snippet: write-once
let b = new QueryBuilder(Dialect.common);
b.appendSafe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (");
b.appendInt(7);
b.appendSafe(", ");
b.appendInt(9);
b.appendSafe(") ORDER BY name NULLS LAST LIMIT ");
b.appendInt(10);
let q = b.build(); // throws if the query is refused

// Rendered for Dialect.common, it's the canonical form, for logs.
console.log("common: " + q.render(Dialect.common, PlaceholderStyle.question).sql);
// PostgreSQL already sorts nulls last going up, so it needs no NULLS LAST,
// and MySQL has no NULLS, so it sorts by name IS NULL first.
forEachDatabase(q);
// Values print as SQL would write them, for reading only.
console.log("params: " + q.params.map((v) => v.toString()).join(", "));
// end snippet

section("2. Values are bound, never spliced");

// snippet: bound
const name = "Robert'); DROP TABLE students; --";
// Building SQL by hand puts the value in the text, where it ends the
// string early and adds a statement of its own.
console.log("by hand: SELECT id FROM students WHERE name = '" + name + "'");
// A hole sends the value apart from the SQL, for the driver to bind.
b = common("SELECT id FROM students WHERE name = ");
b.appendString(name);
const r = b.build().render(Dialect.sqlite, PlaceholderStyle.question);
console.log("wherewith: " + r.sql);
console.log("params: " + r.params.map((v) => v.toString()).join(", "));

// A name from outside is an Identifier, quoted for each database, never
// a value or SQL.
b = common("SELECT * FROM ");
b.appendIdentifier(Identifier.named('students"; DROP TABLE x; --'));
q = b.build();
console.log("a hostile name: " + q.render(Dialect.sqlite, PlaceholderStyle.question).sql);
console.log("in MySQL: " + q.render(Dialect.mysql, PlaceholderStyle.percentS).sql);

// A hole inside quotes is refused: it would be text, not a value.
b = common("SELECT id FROM students WHERE name = '");
b.appendString(name);
b.appendSafe("'");
console.log("a hole in quotes: " + b.templateProblem);
// end snippet

section("3. Refused when it's built");

// snippet: refused
// Each of these runs on every database, and gives different results on
// some. templateProblem says why build would refuse it, and where.
function refused(sql) {
  console.log(`${sql}: ${common(sql).templateProblem ?? "built"}`);
}

// 7 / 2 is 3 in SQLite and PostgreSQL, and 3.5 in MySQL and DuckDB.
refused("SELECT a / 2 FROM t");
// b = NULL matches no row: NULL isn't equal to anything, even NULL.
refused("SELECT a FROM t WHERE b = NULL");
// PostgreSQL reads Name as name; the others keep its case.
refused("SELECT Name FROM t");
// SQLite gives any row's a; the others refuse the query.
refused("SELECT a, count(*) AS n FROM t GROUP BY b");
// SQLite reads ('a' || 1) + 2, PostgreSQL 'a' || (1 + 2).
refused("SELECT 'a' || 1 + 2 AS x");
// Some databases turn 0 into text, and others refuse it.
refused("SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t");
// A placeholder in the text would shift every value's place.
refused("SELECT a FROM t WHERE id = ?");
// What isn't in the common dialect yet is refused too.
refused("SELECT 1 AS a UNION SELECT 2");
// The fix for the first: a float operand divides the same everywhere.
refused("SELECT 7 / 2.0 AS x");
// A null value is refused where NULL would be.
b = common("SELECT a FROM t WHERE b = ");
b.appendString(null);
console.log("SELECT a FROM t WHERE b = ${null}: " + b.templateProblem);
// end snippet

section("4. What differs, handled");

// snippet: differs
// MySQL's || means OR, so it's CONCAT there.
let text = "SELECT id || ':' || name AS tag FROM people";
console.log(text);
forEachDatabase(common(text).build());
// Each database names its types differently, and MySQL's LENGTH counts
// bytes, not characters.
text = "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people";
console.log(text);
forEachDatabase(common(text).build());
// Where nulls sort differs, and so does OFFSET without LIMIT.
b = common("SELECT name FROM people ORDER BY nick DESC OFFSET ");
b.appendInt(20);
console.log("SELECT name FROM people ORDER BY nick DESC OFFSET ${20}");
forEachDatabase(b.build());
// PostgreSQL can't guess a lone parameter's type, so it gets a cast.
b = common("SELECT ");
b.appendString("hi");
b.appendSafe(" AS greeting");
console.log('SELECT ${"hi"} AS greeting');
forEachDatabase(b.build());
// end snippet

section("5. Queries in queries");

// snippet: nested
const big = common("SELECT user_id FROM orders WHERE total > ");
big.appendInt(100);
b = common("SELECT name FROM users WHERE id IN (");
b.appendQuery(big.build());
b.appendSafe(") AND active = ");
b.appendString("yes");
q = b.build();
// The inner query's parameters are numbered with the outer query's.
console.log("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
console.log("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percentS).sql);
// And it's checked again as part of the whole, with problems at its hole.
const inner = common("SELECT user_id FROM orders LIMIT ");
inner.appendInt(5);
b = common("SELECT name FROM people WHERE id IN (");
b.appendQuery(inner.build());
b.appendSafe(")");
console.log("with LIMIT inside: " + b.templateProblem);
// end snippet

section("6. Building queries in code");

// snippet: dynamic
// Filters only when given, a sort column from the caller, and a page.
// Every variant is still checked when it's built.
function search({ word = null, minTotal = null, sort = Identifier.named("created"), descending = false, page = 0 } = {}) {
  const b = common("SELECT id, title FROM orders");
  let joiner = " WHERE ";
  if (word !== null) {
    b.appendSafe(joiner + "title LIKE ");
    b.appendString(word);
    b.appendSafe(" || '%' ESCAPE '!'");
    joiner = " AND ";
  }
  if (minTotal !== null) {
    b.appendSafe(joiner + "total >= ");
    b.appendInt(minTotal);
  }
  b.appendSafe(" ORDER BY ");
  b.appendIdentifier(sort);
  b.appendSafe(descending ? " DESC LIMIT " : " LIMIT ");
  b.appendInt(20);
  b.appendSafe(" OFFSET ");
  b.appendInt(page * 20);
  return b.build().render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql;
}

console.log(search());
console.log(search({ word: "Launch" }));
console.log(search({ minTotal: 100, sort: Identifier.named("Total"), descending: true, page: 2 }));

// A query for fewer databases relaxes the checks for the others: MySQL
// reads \ in a string as an escape, so it's refused only while MySQL is
// a target. The query renders only for its targets.
b = new QueryBuilder(Dialect.common);
b.targets = [Dialect.postgres, Dialect.sqlite];
b.appendSafe("SELECT 'C:\\temp' AS p");
q = b.build();
console.log("for postgres and sqlite: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
console.log("for mysql: " + q.renderProblem(Dialect.mysql, PlaceholderStyle.percentS));
// end snippet

section("7. Placeholders for each driver");

// snippet: placeholders
// The placeholder style depends on the driver, not the database, so it's
// chosen when rendering. percentS doubles %, for drivers that fill in
// values with Python's % formatting.
b = common("SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ");
b.appendInt(1);
q = b.build();
const styles = [
  PlaceholderStyle.question,
  PlaceholderStyle.dollarNumbered,
  PlaceholderStyle.percentS,
  PlaceholderStyle.atNamed,
  PlaceholderStyle.colonNamed,
];
for (const style of styles) {
  console.log(`${style}: ${q.render(Dialect.sqlite, style).sql}`);
}
// A named style refuses text holding its marker, which a driver could
// misread as a name.
b = common("SELECT 'a:b' AS s FROM users WHERE id = ");
b.appendInt(1);
console.log("colonNamed with 'a:b': " + b.build().renderProblem(Dialect.sqlite, PlaceholderStyle.colonNamed));
// end snippet

section("8. Each database's own SQL");

// snippet: own-sql
// For SQL the common dialect doesn't cover yet, a database's own
// template, checked with its rules. In Temper, postgres"…" builds it.
b = new QueryBuilder(Dialect.postgres);
b.appendSafe("INSERT INTO tags (name) VALUES (");
b.appendString("sql");
b.appendSafe(") ON CONFLICT (name) DO NOTHING RETURNING id");
q = b.build();
console.log("upsert: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
// It renders only for its own database.
console.log("for mysql: " + q.renderProblem(Dialect.mysql, PlaceholderStyle.percentS));
// A common query nests in it, rendered for that database.
b = new QueryBuilder(Dialect.postgres);
b.appendSafe("SELECT jsonb_agg(x) FROM (");
b.appendQuery(big.build());
b.appendSafe(") AS s(x)");
console.log("nested: " + b.build().render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
// # starts a comment in MySQL only, so a value after it would vanish.
b = new QueryBuilder(Dialect.mysql);
b.appendSafe("SELECT * FROM t WHERE a = 1 # ");
b.appendString("x");
console.log("mysql, after #: " + b.templateProblem);
// end snippet

section("9. Quoting by hand");

// snippet: quoting
// For tools that write SQL text themselves, such as DDL defaults. Each
// throws rather than change what it can't write, and a ...Problem method
// says why.
console.log("mysql name: " + Dialect.mysql.quoteName("my `table`"));
console.log("mysql string: " + Dialect.mysql.quoteString("it's \\ fine"));
console.log("postgres string: " + Dialect.postgres.quoteString("it's \\ fine"));
const longName = "n".repeat(64);
console.log("postgres, 64-byte name: " + Dialect.postgres.nameProblem(longName));
try {
  Dialect.postgres.quoteString("a\0b");
  console.log("postgres, NUL in a string: quoted");
} catch {
  console.log("postgres, NUL in a string: refused, " + Dialect.postgres.stringProblem("a\0b"));
}
try {
  Identifier.named(longName);
  console.log("Identifier, 64 bytes: named");
} catch {
  console.log("Identifier, 64 bytes: refused, " + identifierProblem(longName));
}
// end snippet

// The tour stops at what the driver gets. The repo's tests/engines run
// these kinds of queries through SQLite, DuckDB, PostgreSQL, and MariaDB.
