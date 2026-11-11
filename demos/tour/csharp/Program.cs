// A tour of Wherewith's whole public API, from C#.
//
// The same tour exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: setup
using System;
using System.Collections.Generic;
using System.Linq;
using Wherewith;
using static Wherewith.WherewithGlobal;

// Each database, with a placeholder style its drivers take.
var databases = new (string Name, Dialect Dialect, PlaceholderStyle Style)[]
{
    ("sqlite", Dialect.Sqlite, PlaceholderStyle.Question),
    ("postgres", Dialect.Postgres, PlaceholderStyle.DollarNumbered),
    ("mysql", Dialect.Mysql, PlaceholderStyle.PercentS),
    ("duckdb", Dialect.Duckdb, PlaceholderStyle.DollarNumbered),
};

void ForEachDatabase(Query q)
{
    foreach (var db in databases)
    {
        Console.WriteLine($"{db.Name}: {q.Render(db.Dialect, db.Style).Sql}");
    }
}

// Values as SQL would write them, joined.
string Shown(IEnumerable<ISqlValue> values) => string.Join(", ", values.Select(v => v.ToString()));

// A common query is a QueryBuilder for Dialect.Common: SQL text with
// AppendSafe, and values, names, and other queries in holes between. In
// Temper, sql"…" builds the same.
QueryBuilder Common(string text)
{
    var b = new QueryBuilder(Dialect.Common);
    b.AppendSafe(text);
    return b;
}
// end snippet

void Section(string title)
{
    Console.WriteLine();
    Console.WriteLine($"## {title}");
}

Console.WriteLine("# Wherewith tour");

Section("1. Write it once");

// snippet: write-once
var b = new QueryBuilder(Dialect.Common);
b.AppendSafe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (");
b.AppendInt(7);
b.AppendSafe(", ");
b.AppendInt(9);
b.AppendSafe(") ORDER BY name NULLS LAST LIMIT ");
b.AppendInt(10);
var q = b.Build(); // throws an Exception if the query is refused

// Rendered for Dialect.Common, it's the canonical form, for logs.
Console.WriteLine("common: " + q.Render(Dialect.Common, PlaceholderStyle.Question).Sql);
// PostgreSQL already sorts nulls last going up, so it needs no NULLS LAST,
// and MySQL has no NULLS, so it sorts by name IS NULL first.
ForEachDatabase(q);
// Values print as SQL would write them, for reading only.
Console.WriteLine("params: " + Shown(q.Params));
// end snippet

Section("2. Values are bound, never spliced");

// snippet: bound
var name = "Robert'); DROP TABLE students; --";
// Building SQL by hand puts the value in the text, where it ends the
// string early and adds a statement of its own.
Console.WriteLine("by hand: SELECT id FROM students WHERE name = '" + name + "'");
// A hole sends the value apart from the SQL, for the driver to bind.
b = Common("SELECT id FROM students WHERE name = ");
b.AppendString(name);
var r = b.Build().Render(Dialect.Sqlite, PlaceholderStyle.Question);
Console.WriteLine("wherewith: " + r.Sql);
Console.WriteLine("params: " + Shown(r.Params));

// A name from outside is an Identifier, quoted for each database, never
// a value or SQL.
b = Common("SELECT * FROM ");
b.AppendIdentifier(Identifier.Named(@"students""; DROP TABLE x; --"));
q = b.Build();
Console.WriteLine("a hostile name: " + q.Render(Dialect.Sqlite, PlaceholderStyle.Question).Sql);
Console.WriteLine("in MySQL: " + q.Render(Dialect.Mysql, PlaceholderStyle.PercentS).Sql);

// A hole inside quotes is refused: it would be text, not a value.
b = Common("SELECT id FROM students WHERE name = '");
b.AppendString(name);
b.AppendSafe("'");
Console.WriteLine("a hole in quotes: " + b.TemplateProblem);
// end snippet

Section("3. Refused when it's built");

// snippet: refused
// Each of these runs on every database, and gives different results on
// some. TemplateProblem says why Build would refuse it, and where.
void Refused(string sql) => Console.WriteLine($"{sql}: {Common(sql).TemplateProblem ?? "built"}");

// 7 / 2 is 3 in SQLite and PostgreSQL, and 3.5 in MySQL and DuckDB.
Refused("SELECT a / 2 FROM t");
// b = NULL matches no row: NULL isn't equal to anything, even NULL.
Refused("SELECT a FROM t WHERE b = NULL");
// PostgreSQL reads Name as name; the others keep its case.
Refused("SELECT Name FROM t");
// SQLite gives any row's a; the others refuse the query.
Refused("SELECT a, count(*) AS n FROM t GROUP BY b");
// SQLite reads ('a' || 1) + 2, PostgreSQL 'a' || (1 + 2).
Refused("SELECT 'a' || 1 + 2 AS x");
// Some databases turn 0 into text, and others refuse it.
Refused("SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t");
// Databases name a + 1 differently (a+1, ?column?, or (a + 1)), so
// an expression in a FROM subquery needs an alias.
Refused("SELECT * FROM (SELECT a + 1 FROM t) AS s");
// A placeholder in the text would shift every value's place.
Refused("SELECT a FROM t WHERE id = ?");
// What isn't in the common dialect yet is refused too.
Refused("SELECT 1 AS a UNION SELECT 2");
// The fix for the first: a float operand divides the same everywhere.
Refused("SELECT 7 / 2.0 AS x");
// A null value is refused where NULL would be.
b = Common("SELECT a FROM t WHERE b = ");
b.AppendString(null);
Console.WriteLine("SELECT a FROM t WHERE b = ${null}: " + b.TemplateProblem);
// end snippet

Section("4. What differs, handled");

// snippet: differs
// MySQL's || means OR, so it's CONCAT there.
var text = "SELECT id || ':' || name AS tag FROM people";
Console.WriteLine(text);
ForEachDatabase(Common(text).Build());
// Each database names its types differently, and MySQL's LENGTH counts
// bytes, not characters.
text = "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people";
Console.WriteLine(text);
ForEachDatabase(Common(text).Build());
// Where nulls sort differs, and so does OFFSET without LIMIT.
b = Common("SELECT name FROM people ORDER BY nick DESC OFFSET ");
b.AppendInt(20);
Console.WriteLine("SELECT name FROM people ORDER BY nick DESC OFFSET ${20}");
ForEachDatabase(b.Build());
// PostgreSQL can't guess a lone parameter's type, so it gets a cast.
b = Common("SELECT ");
b.AppendString("hi");
b.AppendSafe(" AS greeting");
Console.WriteLine(@"SELECT ${""hi""} AS greeting");
ForEachDatabase(b.Build());
// end snippet

Section("5. Queries in queries");

// snippet: nested
var big = Common("SELECT user_id FROM orders WHERE total > ");
big.AppendInt(100);
b = Common("SELECT name FROM users WHERE id IN (");
b.AppendQuery(big.Build());
b.AppendSafe(") AND active = ");
b.AppendString("yes");
q = b.Build();
// The inner query's parameters are numbered with the outer query's.
Console.WriteLine("postgres: " + q.Render(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql);
Console.WriteLine("mysql: " + q.Render(Dialect.Mysql, PlaceholderStyle.PercentS).Sql);
// And it's checked again as part of the whole, with problems at its hole.
var inner = Common("SELECT user_id FROM orders LIMIT ");
inner.AppendInt(5);
b = Common("SELECT name FROM people WHERE id IN (");
b.AppendQuery(inner.Build());
b.AppendSafe(")");
Console.WriteLine("with LIMIT inside: " + b.TemplateProblem);
// end snippet

Section("6. Building queries in code");

// snippet: dynamic
// Filters only when given, a sort column from the caller, and a page.
// Every variant is still checked when it's built.
string Search(string? word = null, int? minTotal = null, Identifier? sort = null, bool descending = false, int page = 0)
{
    var b = Common("SELECT id, title FROM orders");
    var joiner = " WHERE ";
    if (word != null)
    {
        b.AppendSafe(joiner + "title LIKE ");
        b.AppendString(word);
        b.AppendSafe(" || '%' ESCAPE '!'");
        joiner = " AND ";
    }
    if (minTotal != null)
    {
        b.AppendSafe(joiner + "total >= ");
        b.AppendInt(minTotal.Value);
    }
    b.AppendSafe(" ORDER BY ");
    b.AppendIdentifier(sort ?? Identifier.Named("created"));
    b.AppendSafe(descending ? " DESC LIMIT " : " LIMIT ");
    b.AppendInt(20);
    b.AppendSafe(" OFFSET ");
    b.AppendInt(page * 20);
    return b.Build().Render(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql;
}

Console.WriteLine(Search());
Console.WriteLine(Search(word: "Launch"));
Console.WriteLine(Search(minTotal: 100, sort: Identifier.Named("total"), descending: true, page: 2));

// A query for fewer databases relaxes the checks for the others: MySQL
// reads \ in a string as an escape, so it's refused only while MySQL is
// a target. The query renders only for its targets.
b = new QueryBuilder(Dialect.Common);
b.Targets = new List<Dialect> { Dialect.Postgres, Dialect.Sqlite };
b.AppendSafe(@"SELECT 'C:\temp' AS p");
q = b.Build();
Console.WriteLine("for postgres and sqlite: " + q.Render(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql);
Console.WriteLine("for mysql: " + q.RenderProblem(Dialect.Mysql, PlaceholderStyle.PercentS));
// end snippet

Section("7. Placeholders for each driver");

// snippet: placeholders
// The placeholder style depends on the driver, not the database, so it's
// chosen when rendering. PercentS doubles %, for drivers that fill in
// values with Python's % formatting.
b = Common("SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ");
b.AppendInt(1);
q = b.Build();
var styles = new[]
{
    PlaceholderStyle.Question,
    PlaceholderStyle.DollarNumbered,
    PlaceholderStyle.PercentS,
    PlaceholderStyle.AtNamed,
    PlaceholderStyle.ColonNamed,
};
foreach (var style in styles)
{
    Console.WriteLine($"{style}: {q.Render(Dialect.Sqlite, style).Sql}");
}
// A named style refuses text holding its marker, which a driver could
// misread as a name.
b = Common("SELECT 'a:b' AS s FROM users WHERE id = ");
b.AppendInt(1);
Console.WriteLine("colonNamed with 'a:b': " + b.Build().RenderProblem(Dialect.Sqlite, PlaceholderStyle.ColonNamed));
// end snippet

Section("8. Each database's own SQL");

// snippet: own-sql
// For SQL the common dialect doesn't cover yet, a database's own
// template, checked with its rules. In Temper, postgres"…" builds it.
b = new QueryBuilder(Dialect.Postgres);
b.AppendSafe("INSERT INTO tags (name) VALUES (");
b.AppendString("sql");
b.AppendSafe(") ON CONFLICT (name) DO NOTHING RETURNING id");
q = b.Build();
Console.WriteLine("upsert: " + q.Render(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql);
// It renders only for its own database.
Console.WriteLine("for mysql: " + q.RenderProblem(Dialect.Mysql, PlaceholderStyle.PercentS));
// A common query nests in it, rendered for that database.
b = new QueryBuilder(Dialect.Postgres);
b.AppendSafe("SELECT jsonb_agg(x) FROM (");
b.AppendQuery(big.Build());
b.AppendSafe(") AS s(x)");
Console.WriteLine("nested: " + b.Build().Render(Dialect.Postgres, PlaceholderStyle.DollarNumbered).Sql);
// # starts a comment in MySQL only, so a value after it would vanish.
b = new QueryBuilder(Dialect.Mysql);
b.AppendSafe("SELECT * FROM t WHERE a = 1 # ");
b.AppendString("x");
Console.WriteLine("mysql, after #: " + b.TemplateProblem);
// end snippet

Section("9. Quoting by hand");

// snippet: quoting
// For tools that write SQL text themselves, such as DDL defaults. Each
// throws an Exception rather than change what it can't write, and a
// ...Problem method says why.
Console.WriteLine("mysql name: " + Dialect.Mysql.QuoteName("my `table`"));
Console.WriteLine("mysql string: " + Dialect.Mysql.QuoteString(@"it's \ fine"));
Console.WriteLine("postgres string: " + Dialect.Postgres.QuoteString(@"it's \ fine"));
var longName = new string('n', 64);
Console.WriteLine("postgres, 64-byte name: " + Dialect.Postgres.NameProblem(longName));
try
{
    Dialect.Postgres.QuoteString("a\0b");
    Console.WriteLine("postgres, NUL in a string: quoted");
}
catch (Exception)
{
    Console.WriteLine("postgres, NUL in a string: refused, " + Dialect.Postgres.StringProblem("a\0b"));
}
try
{
    Identifier.Named(longName);
    Console.WriteLine("Identifier, 64 bytes: named");
}
catch (Exception)
{
    Console.WriteLine("Identifier, 64 bytes: refused, " + IdentifierProblem(longName));
}
// end snippet

// The tour stops at what the driver gets. The repo's tests/engines run
// these kinds of queries through SQLite, DuckDB, PostgreSQL, and MariaDB.
