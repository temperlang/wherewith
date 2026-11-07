// Wherewith's example, from C#: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
using System;
using Wherewith;

var name = "Robert'); DROP TABLE students; --";

// The query for one database, checked with its rules, rendered for it.
RenderedQuery Find(Dialect dialect, PlaceholderStyle style)
{
    var b = new QueryBuilder(dialect);
    b.AppendSafe("SELECT id FROM ");
    b.AppendIdentifier(Identifier.Named("students"));
    b.AppendSafe(" WHERE name = ");
    b.AppendString(name);
    return b.Build().Render(dialect, style);
}

// Each database's quoting, with the placeholders its driver takes.
Console.WriteLine("sqlite: " + Find(Dialect.Sqlite, PlaceholderStyle.Question).Sql);
Console.WriteLine("postgres: " + Find(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql);
Console.WriteLine("mysql: " + Find(Dialect.Mysql, PlaceholderStyle.PercentS).Sql);
var r = Find(Dialect.Duckdb, PlaceholderStyle.DollarNumbered);
Console.WriteLine("duckdb: " + r.Sql);
// The name travels apart from the SQL, for the driver to bind.
Console.WriteLine("params: " + r.Params.Count);

// A value inside quotes is refused, not guessed at.
var bad = new QueryBuilder(Dialect.Postgres);
bad.AppendSafe("SELECT id FROM students WHERE name = '");
bad.AppendString(name);
bad.AppendSafe("'");
Console.WriteLine("refused: " + bad.TemplateProblem); // and bad.Build() throws
// end snippet
