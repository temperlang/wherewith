// A tour of Wherewith's whole public API, from C++.
//
// The same tour exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: setup
#include <iostream>
#include <memory>
#include <string>
#include <tuple>
#include <vector>

#include "wherewith/init.hpp"

using temper::core::NullableParam;
using temper::core::Str;
using temper::core::TemperBubble;
using wherewith::Dialect;
using wherewith::Identifier;
using wherewith::identifierProblem;
using wherewith::PlaceholderStyle;
using wherewith::Query;
using wherewith::QueryBuilder;
using wherewith::SqlValue;

// Each database, with a placeholder style its drivers take.
std::vector<std::tuple<std::string, std::shared_ptr<Dialect>, std::shared_ptr<PlaceholderStyle>>> databases() {
  return {
      std::make_tuple("sqlite", Dialect::sqlite(), PlaceholderStyle::question()),
      std::make_tuple("postgres", Dialect::postgres(), PlaceholderStyle::dollarNumbered()),
      std::make_tuple("mysql", Dialect::mysql(), PlaceholderStyle::percentS()),
      std::make_tuple("duckdb", Dialect::duckdb(), PlaceholderStyle::dollarNumbered()),
  };
}

void forEachDatabase(std::shared_ptr<Query> const &q) {
  for (auto const &db : databases()) {
    std::cout << std::get<0>(db) << ": " << q->render(std::get<1>(db), std::get<2>(db))->sql << "\n";
  }
}

// Values as SQL would write them, joined.
std::string shown(std::vector<std::shared_ptr<SqlValue>> const &values) {
  std::string out;
  for (size_t i = 0; i < values.size(); i++) {
    out += (i ? ", " : "") + std::string(values[i]->toString());
  }
  return out;
}

// templateProblem and renderProblem are nullable: has_value says whether
// there's a problem, and value is its text.
std::string problem(NullableParam<Str> const &found) { return found.has_value ? std::string(found.value) : ""; }

// A common query is a QueryBuilder for Dialect::common(): SQL text with
// appendSafe, and values, names, and other queries in holes between. In
// Temper, sql"…" builds the same.
std::shared_ptr<QueryBuilder> common(std::string const &text) {
  auto b = QueryBuilder::make(Dialect::common());
  b->appendSafe(text);
  return b;
}
// end snippet

void section(std::string const &title) { std::cout << "\n## " << title << "\n"; }

// snippet: refused
// Each of these runs on every database, and gives different results on
// some. get_templateProblem says why build would refuse it, and where.
void refused(std::string const &sql) {
  auto found = common(sql)->get_templateProblem();
  std::cout << sql << ": " << (found.has_value ? std::string(found.value) : "built") << "\n";
}
// end snippet

// snippet: dynamic
// Filters only when given (an empty word, or a negative total, means
// none), a sort column from the caller, and a page. Every variant is
// still checked when it's built.
std::string search(std::string const &word, int minTotal, std::shared_ptr<Identifier> const &sort, bool descending,
                   int page) {
  auto b = common("SELECT id, title FROM orders");
  std::string joiner = " WHERE ";
  if (!word.empty()) {
    b->appendSafe(joiner + "title LIKE ");
    b->appendString(word);
    b->appendSafe(" || '%' ESCAPE '!'");
    joiner = " AND ";
  }
  if (minTotal >= 0) {
    b->appendSafe(joiner + "total >= ");
    b->appendInt(minTotal);
  }
  b->appendSafe(" ORDER BY ");
  b->appendIdentifier(sort);
  b->appendSafe(descending ? " DESC LIMIT " : " LIMIT ");
  b->appendInt(20);
  b->appendSafe(" OFFSET ");
  b->appendInt(page * 20);
  return b->build()->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql;
}
// end snippet

int main() {
  std::cout << "# Wherewith tour\n";

  section("1. Write it once");

  // snippet: write-once
  auto b = QueryBuilder::make(Dialect::common());
  b->appendSafe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (");
  b->appendInt(7);
  b->appendSafe(", ");
  b->appendInt(9);
  b->appendSafe(") ORDER BY name NULLS LAST LIMIT ");
  b->appendInt(10);
  auto q = b->build();  // throws TemperBubble if the query is refused

  // Rendered for Dialect::common(), it's the canonical form, for logs.
  std::cout << "common: " << q->render(Dialect::common(), PlaceholderStyle::question())->sql << "\n";
  // PostgreSQL already sorts nulls last going up, so it needs no NULLS LAST,
  // and MySQL has no NULLS, so it sorts by name IS NULL first.
  forEachDatabase(q);
  // Values print as SQL would write them, for reading only.
  std::cout << "params: " << shown(*q->params) << "\n";
  // end snippet

  section("2. Values are bound, never spliced");

  // snippet: bound
  std::string name = "Robert'); DROP TABLE students; --";
  // Building SQL by hand puts the value in the text, where it ends the
  // string early and adds a statement of its own.
  std::cout << "by hand: SELECT id FROM students WHERE name = '" << name << "'\n";
  // A hole sends the value apart from the SQL, for the driver to bind.
  b = common("SELECT id FROM students WHERE name = ");
  b->appendString(name);
  auto r = b->build()->render(Dialect::sqlite(), PlaceholderStyle::question());
  std::cout << "wherewith: " << r->sql << "\n";
  std::cout << "params: " << shown(*r->params) << "\n";

  // A name from outside is an Identifier, quoted for each database, never
  // a value or SQL.
  b = common("SELECT * FROM ");
  b->appendIdentifier(Identifier::named("students\"; DROP TABLE x; --"));
  q = b->build();
  std::cout << "a hostile name: " << q->render(Dialect::sqlite(), PlaceholderStyle::question())->sql << "\n";
  std::cout << "in MySQL: " << q->render(Dialect::mysql(), PlaceholderStyle::percentS())->sql << "\n";

  // A hole inside quotes is refused: it would be text, not a value.
  b = common("SELECT id FROM students WHERE name = '");
  b->appendString(name);
  b->appendSafe("'");
  std::cout << "a hole in quotes: " << problem(b->get_templateProblem()) << "\n";
  // end snippet

  section("3. Refused when it's built");

  // snippet: refused
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
  // Databases name a + 1 differently (a+1, ?column?, or (a + 1)), so
  // an expression in a FROM subquery needs an alias.
  refused("SELECT * FROM (SELECT a + 1 FROM t) AS s");
  // A placeholder in the text would shift every value's place.
  refused("SELECT a FROM t WHERE id = ?");
  // What isn't in the common dialect yet is refused too.
  refused("SELECT 1 AS a UNION SELECT 2");
  // The fix for the first: a float operand divides the same everywhere.
  refused("SELECT 7 / 2.0 AS x");
  // A null value is refused where NULL would be.
  b = common("SELECT a FROM t WHERE b = ");
  b->appendString(nullptr);
  std::cout << "SELECT a FROM t WHERE b = ${null}: " << problem(b->get_templateProblem()) << "\n";
  // end snippet

  section("4. What differs, handled");

  // snippet: differs
  // MySQL's || means OR, so it's CONCAT there.
  std::string text = "SELECT id || ':' || name AS tag FROM people";
  std::cout << text << "\n";
  forEachDatabase(common(text)->build());
  // Each database names its types differently, and MySQL's LENGTH counts
  // bytes, not characters.
  text = "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people";
  std::cout << text << "\n";
  forEachDatabase(common(text)->build());
  // Where nulls sort differs, and so does OFFSET without LIMIT.
  b = common("SELECT name FROM people ORDER BY nick DESC OFFSET ");
  b->appendInt(20);
  std::cout << "SELECT name FROM people ORDER BY nick DESC OFFSET ${20}\n";
  forEachDatabase(b->build());
  // PostgreSQL can't guess a lone parameter's type, so it gets a cast.
  b = common("SELECT ");
  b->appendString("hi");
  b->appendSafe(" AS greeting");
  std::cout << "SELECT ${\"hi\"} AS greeting\n";
  forEachDatabase(b->build());
  // end snippet

  section("5. Queries in queries");

  // snippet: nested
  auto big = common("SELECT user_id FROM orders WHERE total > ");
  big->appendInt(100);
  b = common("SELECT name FROM users WHERE id IN (");
  b->appendQuery(big->build());
  b->appendSafe(") AND active = ");
  b->appendString("yes");
  q = b->build();
  // The inner query's parameters are numbered with the outer query's.
  std::cout << "postgres: " << q->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql << "\n";
  std::cout << "mysql: " << q->render(Dialect::mysql(), PlaceholderStyle::percentS())->sql << "\n";
  // And it's checked again as part of the whole, with problems at its hole.
  auto inner = common("SELECT user_id FROM orders LIMIT ");
  inner->appendInt(5);
  b = common("SELECT name FROM people WHERE id IN (");
  b->appendQuery(inner->build());
  b->appendSafe(")");
  std::cout << "with LIMIT inside: " << problem(b->get_templateProblem()) << "\n";
  // end snippet

  section("6. Building queries in code");

  // snippet: dynamic
  auto created = Identifier::named("created");
  std::cout << search("", -1, created, false, 0) << "\n";
  std::cout << search("Launch", -1, created, false, 0) << "\n";
  std::cout << search("", 100, Identifier::named("total"), true, 2) << "\n";

  // A query for fewer databases relaxes the checks for the others: MySQL
  // reads \ in a string as an escape, so it's refused only while MySQL is
  // a target. The query renders only for its targets.
  b = QueryBuilder::make(Dialect::common());
  b->set_targets(std::make_shared<std::vector<std::shared_ptr<Dialect>>>(
      std::vector<std::shared_ptr<Dialect>>{Dialect::postgres(), Dialect::sqlite()}));
  b->appendSafe("SELECT 'C:\\temp' AS p");
  q = b->build();
  std::cout << "for postgres and sqlite: " << q->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql
            << "\n";
  std::cout << "for mysql: " << problem(q->renderProblem(Dialect::mysql(), PlaceholderStyle::percentS())) << "\n";
  // end snippet

  section("7. Placeholders for each driver");

  // snippet: placeholders
  // The placeholder style depends on the driver, not the database, so it's
  // chosen when rendering. percentS doubles %, for drivers that fill in
  // values with Python's % formatting.
  b = common("SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ");
  b->appendInt(1);
  q = b->build();
  std::vector<std::shared_ptr<PlaceholderStyle>> styles = {
      PlaceholderStyle::question(),
      PlaceholderStyle::dollarNumbered(),
      PlaceholderStyle::percentS(),
      PlaceholderStyle::atNamed(),
      PlaceholderStyle::colonNamed(),
  };
  for (auto const &style : styles) {
    std::cout << style->toString() << ": " << q->render(Dialect::sqlite(), style)->sql << "\n";
  }
  // A named style refuses text holding its marker, which a driver could
  // misread as a name.
  b = common("SELECT 'a:b' AS s FROM users WHERE id = ");
  b->appendInt(1);
  auto found = b->build()->renderProblem(Dialect::sqlite(), PlaceholderStyle::colonNamed());
  std::cout << "colonNamed with 'a:b': " << problem(found) << "\n";
  // end snippet

  section("8. Each database's own SQL");

  // snippet: own-sql
  // For SQL the common dialect doesn't cover yet, a database's own
  // template, checked with its rules. In Temper, postgres"…" builds it.
  b = QueryBuilder::make(Dialect::postgres());
  b->appendSafe("INSERT INTO tags (name) VALUES (");
  b->appendString("sql");
  b->appendSafe(") ON CONFLICT (name) DO NOTHING RETURNING id");
  q = b->build();
  std::cout << "upsert: " << q->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql << "\n";
  // It renders only for its own database.
  std::cout << "for mysql: " << problem(q->renderProblem(Dialect::mysql(), PlaceholderStyle::percentS())) << "\n";
  // A common query nests in it, rendered for that database.
  b = QueryBuilder::make(Dialect::postgres());
  b->appendSafe("SELECT jsonb_agg(x) FROM (");
  b->appendQuery(big->build());
  b->appendSafe(") AS s(x)");
  std::cout << "nested: " << b->build()->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql << "\n";
  // # starts a comment in MySQL only, so a value after it would vanish.
  b = QueryBuilder::make(Dialect::mysql());
  b->appendSafe("SELECT * FROM t WHERE a = 1 # ");
  b->appendString("x");
  std::cout << "mysql, after #: " << problem(b->get_templateProblem()) << "\n";
  // end snippet

  section("9. Quoting by hand");

  // snippet: quoting
  // For tools that write SQL text themselves, such as DDL defaults. Each
  // throws TemperBubble rather than change what it can't write, and a
  // ...Problem method says why.
  std::cout << "mysql name: " << Dialect::mysql()->quoteName("my `table`") << "\n";
  std::cout << "mysql string: " << Dialect::mysql()->quoteString("it's \\ fine") << "\n";
  std::cout << "postgres string: " << Dialect::postgres()->quoteString("it's \\ fine") << "\n";
  std::string longName(64, 'n');
  std::cout << "postgres, 64-byte name: " << problem(Dialect::postgres()->nameProblem(longName)) << "\n";
  std::string withNul("a\0b", 3);
  try {
    Dialect::postgres()->quoteString(withNul);
    std::cout << "postgres, NUL in a string: quoted\n";
  } catch (TemperBubble const &) {
    std::cout << "postgres, NUL in a string: refused, " << problem(Dialect::postgres()->stringProblem(withNul)) << "\n";
  }
  try {
    Identifier::named(longName);
    std::cout << "Identifier, 64 bytes: named\n";
  } catch (TemperBubble const &) {
    std::cout << "Identifier, 64 bytes: refused, " << problem(identifierProblem(longName)) << "\n";
  }
  // end snippet

  // The tour stops at what the driver gets. The repo's tests/engines run
  // these kinds of queries through SQLite, DuckDB, PostgreSQL, and MariaDB.
}
