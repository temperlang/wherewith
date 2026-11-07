// Wherewith's example, from C++: one query, rendered for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
#include <iostream>
#include <string>

#include "wherewith/init.hpp"

using wherewith::Dialect;
using wherewith::Identifier;
using wherewith::PlaceholderStyle;
using wherewith::QueryBuilder;

int main() {
  std::string name = "Robert'); DROP TABLE students; --";
  auto b = QueryBuilder::make(Dialect::postgres());
  b->appendSafe("SELECT id FROM ");
  b->appendIdentifier(Identifier::named("students"));
  b->appendSafe(" WHERE name = ");
  b->appendString(name);
  auto q = b->build();

  // Each database's quoting, with the placeholders its driver takes.
  std::cout << "sqlite: " << q->render(Dialect::sqlite(), PlaceholderStyle::question())->sql << "\n";
  std::cout << "postgres: " << q->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql << "\n";
  std::cout << "mysql: " << q->render(Dialect::mysql(), PlaceholderStyle::percentS())->sql << "\n";
  auto r = q->render(Dialect::duckdb(), PlaceholderStyle::dollarNumbered());
  std::cout << "duckdb: " << r->sql << "\n";
  // The name travels apart from the SQL, for the driver to bind.
  std::cout << "params: " << r->params->size() << "\n";

  // A value inside quotes is refused, not guessed at.
  auto bad = QueryBuilder::make(Dialect::postgres());
  bad->appendSafe("SELECT id FROM students WHERE name = '");
  bad->appendString(name);
  bad->appendSafe("'");
  // And bad->build() throws temper::core::TemperBubble.
  std::cout << "refused: " << bad->get_templateProblem().value << "\n";
}
// end snippet
