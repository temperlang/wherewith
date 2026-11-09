// Wherewith's example, from Java: the same query for each database.
//
// The same example exists for each language Wherewith supports, and they all
// print the same text. See demos/README.md for how to run them.

// snippet: example
import wherewith.Dialect;
import wherewith.PlaceholderStyle;
import wherewith.Query;
import wherewith.QueryBuilder;
import wherewith.RenderedQuery;

public class Example {
    public static void main(String[] args) {
        String word = "Launch";

        // One query, in the common dialect, checked for every database.
        QueryBuilder b = new QueryBuilder(Dialect.common);
        b.appendSafe("SELECT title, \"dueDate\" FROM tasks WHERE title LIKE ");
        b.appendString(word);
        b.appendSafe(" || '%' ESCAPE '!' ORDER BY \"dueDate\" NULLS LAST LIMIT ");
        b.appendInt(20);
        b.appendSafe(" OFFSET ");
        b.appendInt(40);
        Query q = b.build();

        // Rendered for each database, with the placeholders its driver takes.
        System.out.println("sqlite: " + q.render(Dialect.sqlite, PlaceholderStyle.question).getSql());
        System.out.println("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollarNumbered).getSql());
        System.out.println("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percentS).getSql());
        RenderedQuery r = q.render(Dialect.duckdb, PlaceholderStyle.dollarNumbered);
        System.out.println("duckdb: " + r.getSql());
        // The values travel apart from the SQL, for the driver to bind.
        System.out.println("params: " + r.getParams().size());

        // What databases would read differently is refused, with its place.
        QueryBuilder bad = new QueryBuilder(Dialect.common);
        bad.appendSafe("SELECT title, dueDate FROM tasks");
        System.out.println("refused: " + bad.getTemplateProblem()); // and bad.build() throws
    }
}
// end snippet
