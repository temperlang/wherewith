//! Wherewith's example, from Rust: the same query for each database.
//!
//! The same example exists for each language Wherewith supports, and they all
//! print the same text. See demos/README.md for how to run them.

// snippet: example
use wherewith::{Dialect, PlaceholderStyle, QueryBuilder};

fn main() -> temper_core::Result<()> {
    let word = "Launch";

    // One query, in the common dialect, checked for every database.
    let b = QueryBuilder::new(Dialect::common());
    b.append_safe(r#"SELECT title, "dueDate" FROM tasks WHERE title LIKE "#);
    b.append_string(Some(word));
    b.append_safe(r#" || '%' ESCAPE '!' ORDER BY "dueDate" NULLS LAST LIMIT "#);
    b.append_int(20);
    b.append_safe(" OFFSET ");
    b.append_int(40);
    let q = b.build()?;

    // Rendered for each database, with the placeholders its driver takes.
    println!("sqlite: {}", q.render(Dialect::sqlite(), PlaceholderStyle::question())?.sql());
    println!("postgres: {}", q.render(Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql());
    println!("mysql: {}", q.render(Dialect::mysql(), PlaceholderStyle::percent_s())?.sql());
    let r = q.render(Dialect::duckdb(), PlaceholderStyle::dollar_numbered())?;
    println!("duckdb: {}", r.sql());
    // The values travel apart from the SQL, for the driver to bind.
    println!("params: {}", r.params().len());

    // What databases would read differently is refused, with its place.
    let bad = QueryBuilder::new(Dialect::common());
    bad.append_safe("SELECT title, dueDate FROM tasks");
    // And bad.build() gives an Err.
    println!("refused: {}", bad.template_problem().unwrap_or_default());
    Ok(())
}
// end snippet
