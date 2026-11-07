//! Wherewith's example, from Rust: the same query for each database.
//!
//! The same example exists for each language Wherewith supports, and they all
//! print the same text. See demos/README.md for how to run them.

// snippet: example
use wherewith::{Dialect, Identifier, PlaceholderStyle, QueryBuilder, RenderedQuery};

/// The query for one database, checked with its rules, rendered for it.
fn find(name: &str, dialect: Dialect, style: PlaceholderStyle) -> temper_core::Result<RenderedQuery> {
    let b = QueryBuilder::new(dialect.clone());
    b.append_safe("SELECT id FROM ");
    b.append_identifier(Identifier::named("students")?);
    b.append_safe(" WHERE name = ");
    b.append_string(Some(name));
    b.build()?.render(dialect, style)
}

fn main() -> temper_core::Result<()> {
    let name = "Robert'); DROP TABLE students; --";

    // Each database's quoting, with the placeholders its driver takes.
    println!("sqlite: {}", find(name, Dialect::sqlite(), PlaceholderStyle::question())?.sql());
    println!("postgres: {}", find(name, Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql());
    println!("mysql: {}", find(name, Dialect::mysql(), PlaceholderStyle::percent_s())?.sql());
    let r = find(name, Dialect::duckdb(), PlaceholderStyle::dollar_numbered())?;
    println!("duckdb: {}", r.sql());
    // The name travels apart from the SQL, for the driver to bind.
    println!("params: {}", r.params().len());

    // A value inside quotes is refused, not guessed at.
    let bad = QueryBuilder::new(Dialect::postgres());
    bad.append_safe("SELECT id FROM students WHERE name = '");
    bad.append_string(Some(name));
    bad.append_safe("'");
    // And bad.build() gives an Err.
    println!("refused: {}", bad.template_problem().unwrap_or_default());
    Ok(())
}
// end snippet
