// Wherewith's example, from Java: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
import wherewith.Dialect;
import wherewith.Identifier;
import wherewith.PlaceholderStyle;
import wherewith.QueryBuilder;
import wherewith.RenderedQuery;

public class Example {
    // The query for one database, checked with its rules, rendered for it.
    static RenderedQuery find(String name, Dialect dialect, PlaceholderStyle style) {
        QueryBuilder b = new QueryBuilder(dialect);
        b.appendSafe("SELECT id FROM ");
        b.appendIdentifier(Identifier.named("students"));
        b.appendSafe(" WHERE name = ");
        b.appendString(name);
        return b.build().render(dialect, style);
    }

    public static void main(String[] args) {
        String name = "Robert'); DROP TABLE students; --";

        // Each database's quoting, with the placeholders its driver takes.
        System.out.println("sqlite: " + find(name, Dialect.sqlite, PlaceholderStyle.question).getSql());
        System.out.println("postgres: " + find(name, Dialect.postgres, PlaceholderStyle.dollarNumbered).getSql());
        System.out.println("mysql: " + find(name, Dialect.mysql, PlaceholderStyle.percentS).getSql());
        RenderedQuery r = find(name, Dialect.duckdb, PlaceholderStyle.dollarNumbered);
        System.out.println("duckdb: " + r.getSql());
        // The name travels apart from the SQL, for the driver to bind.
        System.out.println("params: " + r.getParams().size());

        // A value inside quotes is refused, not guessed at.
        QueryBuilder bad = new QueryBuilder(Dialect.postgres);
        bad.appendSafe("SELECT id FROM students WHERE name = '");
        bad.appendString(name);
        bad.appendSafe("'");
        System.out.println("refused: " + bad.getTemplateProblem()); // and bad.build() throws
    }
}
// end snippet
