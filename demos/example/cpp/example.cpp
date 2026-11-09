// Wherewith's example, from C++: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
#include <iostream>
#include <string>

#include "wherewith/init.hpp"

using wherewith::Dialect;
using wherewith::PlaceholderStyle;
using wherewith::QueryBuilder;

int main() {
  std::string word = "Launch";

  // One query, in the common dialect, checked for every database.
  auto b = QueryBuilder::make(Dialect::common());
  b->appendSafe("SELECT title, \"dueDate\" FROM tasks WHERE title LIKE ");
  b->appendString(word);
  b->appendSafe(" || '%' ESCAPE '!' ORDER BY \"dueDate\" NULLS LAST LIMIT ");
  b->appendInt(20);
  b->appendSafe(" OFFSET ");
  b->appendInt(40);
  auto q = b->build();

  // Rendered for each database, with the placeholders its driver takes.
  std::cout << "sqlite: " << q->render(Dialect::sqlite(), PlaceholderStyle::question())->sql << "\n";
  std::cout << "postgres: " << q->render(Dialect::postgres(), PlaceholderStyle::dollarNumbered())->sql << "\n";
  std::cout << "mysql: " << q->render(Dialect::mysql(), PlaceholderStyle::percentS())->sql << "\n";
  auto r = q->render(Dialect::duckdb(), PlaceholderStyle::dollarNumbered());
  std::cout << "duckdb: " << r->sql << "\n";
  // The values travel apart from the SQL, for the driver to bind.
  std::cout << "params: " << r->params->size() << "\n";

  // What databases would read differently is refused, with its place.
  auto bad = QueryBuilder::make(Dialect::common());
  bad->appendSafe("SELECT title, dueDate FROM tasks");
  // And bad->build() throws temper::core::TemperBubble.
  std::cout << "refused: " << bad->get_templateProblem().value << "\n";
}
// end snippet
