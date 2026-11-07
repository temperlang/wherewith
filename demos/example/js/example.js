// Wherewith's example, from JavaScript: one query, rendered for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
import { Dialect, Identifier, PlaceholderStyle, QueryBuilder } from "wherewith";

const name = "Robert'); DROP TABLE students; --";
const b = new QueryBuilder(Dialect.postgres);
b.appendSafe("SELECT id FROM ");
b.appendIdentifier(Identifier.named("students"));
b.appendSafe(" WHERE name = ");
b.appendString(name);
const q = b.build();

// Each database's quoting, with the placeholders its driver takes.
console.log("sqlite: " + q.render(Dialect.sqlite, PlaceholderStyle.question).sql);
console.log("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
console.log("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percentS).sql);
const r = q.render(Dialect.duckdb, PlaceholderStyle.dollarNumbered);
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
