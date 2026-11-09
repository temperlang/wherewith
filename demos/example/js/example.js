// Wherewith's example, from JavaScript: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
import { Dialect, PlaceholderStyle, QueryBuilder } from "wherewith";

const word = "Launch";

// One query, in the common dialect, checked for every database.
const b = new QueryBuilder(Dialect.common);
b.appendSafe('SELECT title, "dueDate" FROM tasks WHERE title LIKE ');
b.appendString(word);
b.appendSafe(` || '%' ESCAPE '!' ORDER BY "dueDate" NULLS LAST LIMIT `);
b.appendInt(20);
b.appendSafe(" OFFSET ");
b.appendInt(40);
const q = b.build();

// Rendered for each database, with the placeholders its driver takes.
console.log("sqlite: " + q.render(Dialect.sqlite, PlaceholderStyle.question).sql);
console.log("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).sql);
console.log("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percentS).sql);
const r = q.render(Dialect.duckdb, PlaceholderStyle.dollarNumbered);
console.log("duckdb: " + r.sql);
// The values travel apart from the SQL, for the driver to bind.
console.log("params: " + r.params.length);

// What databases would read differently is refused, with its place.
const bad = new QueryBuilder(Dialect.common);
bad.appendSafe("SELECT title, dueDate FROM tasks");
console.log("refused: " + bad.templateProblem); // and bad.build() throws
// end snippet
