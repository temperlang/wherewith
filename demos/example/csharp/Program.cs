// Wherewith's example, from C#: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
using System;
using Wherewith;

var word = "Launch";

// One query, in the common dialect, checked for every database.
var b = new QueryBuilder(Dialect.Common);
b.AppendSafe("SELECT title, \"dueDate\" FROM tasks WHERE title LIKE ");
b.AppendString(word);
b.AppendSafe(" || '%' ESCAPE '!' ORDER BY \"dueDate\" NULLS LAST LIMIT ");
b.AppendInt(20);
b.AppendSafe(" OFFSET ");
b.AppendInt(40);
var q = b.Build();

// Rendered for each database, with the placeholders its driver takes.
Console.WriteLine("sqlite: " + q.Render(Dialect.Sqlite, PlaceholderStyle.Question).Sql);
Console.WriteLine("postgres: " + q.Render(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql);
Console.WriteLine("mysql: " + q.Render(Dialect.Mysql, PlaceholderStyle.PercentS).Sql);
var r = q.Render(Dialect.Duckdb, PlaceholderStyle.DollarNumbered);
Console.WriteLine("duckdb: " + r.Sql);
// The values travel apart from the SQL, for the driver to bind.
Console.WriteLine("params: " + r.Params.Count);

// What databases would read differently is refused, with its place.
var bad = new QueryBuilder(Dialect.Common);
bad.AppendSafe("SELECT title, dueDate FROM tasks");
Console.WriteLine("refused: " + bad.TemplateProblem); // and bad.Build() throws
// end snippet
