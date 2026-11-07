// Wherewith's example, from Java: one query, rendered for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
import wherewith.Dialect;
import wherewith.Identifier;
import wherewith.PlaceholderStyle;
import wherewith.Query;
import wherewith.QueryBuilder;
import wherewith.RenderedQuery;

public class Example {
    public static void main(String[] args) {
        String name = "Robert'); DROP TABLE students; --";
        QueryBuilder b = new QueryBuilder(Dialect.postgres);
        b.appendSafe("SELECT id FROM ");
        b.appendIdentifier(Identifier.named("students"));
        b.appendSafe(" WHERE name = ");
        b.appendString(name);
        Query q = b.build();

        // Each database's quoting, with the placeholders its driver takes.
        System.out.println("sqlite: " + q.render(Dialect.sqlite, PlaceholderStyle.question).getSql());
        System.out.println("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).getSql());
        System.out.println("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percentS).getSql());
        RenderedQuery r = q.render(Dialect.duckdb, PlaceholderStyle.dollarNumbered);
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
