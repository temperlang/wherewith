// Wherewith's example, from JavaScript: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
import { Dialect, Identifier, PlaceholderStyle, QueryBuilder } from "wherewith";

const name = "Robert'); DROP TABLE students; --";

// The query for one database, checked with its rules, rendered for it.
function find(dialect, style) {
  const b = new QueryBuilder(dialect);
  b.appendSafe("SELECT id FROM ");
  b.appendIdentifier(Identifier.named("students"));
  b.appendSafe(" WHERE name = ");
  b.appendString(name);
  return b.build().render(dialect, style);
}

// Each database's quoting, with the placeholders its driver takes.
console.log("sqlite: " + find(Dialect.sqlite, PlaceholderStyle.question).sql);
console.log("postgres: " + find(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
console.log("mysql: " + find(Dialect.mysql, PlaceholderStyle.percentS).sql);
const r = find(Dialect.duckdb, PlaceholderStyle.dollarNumbered);
console.log("duckdb: " + r.sql);
// The name travels apart from the SQL, for the driver to bind.
console.log("params: " + r.params.length);

// A value inside quotes is refused, not guessed at.
const bad = new QueryBuilder(Dialect.postgres);
bad.appendSafe("SELECT id FROM students WHERE name = '");
bad.appendString(name);
bad.appendSafe("'");
console.log("refused: " + bad.templateProblem); // and bad.build() throws
// end snippet
