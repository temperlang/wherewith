//! A tour of Wherewith's whole public API, from Rust.
//!
//! The same tour exists for each language Wherewith supports, and they all
//! print the same text. See demos/README.md for how to run them.

// snippet: setup
use wherewith::{identifier_problem, Dialect, Identifier, PlaceholderStyle, Query, QueryBuilder, SqlValue, SqlValueTrait};

// Each database, with a placeholder style its drivers take.
fn databases() -> Vec<(&'static str, Dialect, PlaceholderStyle)> {
    vec![
        ("sqlite", Dialect::sqlite(), PlaceholderStyle::question()),
        ("postgres", Dialect::postgres(), PlaceholderStyle::dollar_numbered()),
        ("mysql", Dialect::mysql(), PlaceholderStyle::percent_s()),
        ("duckdb", Dialect::duckdb(), PlaceholderStyle::dollar_numbered()),
    ]
}

fn for_each_database(q: &Query) -> temper_core::Result<()> {
    for (name, dialect, style) in databases() {
        println!("{name}: {}", q.render(dialect, style)?.sql());
    }
    Ok(())
}

// Values as SQL would write them, joined.
fn shown(values: &[SqlValue]) -> String {
    values.iter().map(|v| v.to_string().to_string()).collect::<Vec<_>>().join(", ")
}

// A common query is a QueryBuilder for Dialect::common(): SQL text with
// append_safe, and values, names, and other queries in holes between. In
// Temper, sql"…" builds the same.
fn common(text: &str) -> QueryBuilder {
    let b = QueryBuilder::new(Dialect::common());
    b.append_safe(text);
    b
}

// A problem, or nothing, as text.
fn problem(found: Option<std::sync::Arc<String>>) -> String {
    found.map(|s| s.to_string()).unwrap_or_default()
}
// end snippet

fn section(title: &str) {
    println!();
    println!("## {title}");
}

fn main() -> temper_core::Result<()> {
    println!("# Wherewith tour");

    section("1. Write it once");

    // snippet: write-once
    let b = QueryBuilder::new(Dialect::common());
    b.append_safe("SELECT name, coalesce(nick, name) AS shown FROM users WHERE id IN (");
    b.append_int(7);
    b.append_safe(", ");
    b.append_int(9);
    b.append_safe(") ORDER BY name NULLS LAST LIMIT ");
    b.append_int(10);
    let q = b.build()?; // an Err if the query is refused

    // Rendered for Dialect::common(), it's the canonical form, for logs.
    println!("common: {}", q.render(Dialect::common(), PlaceholderStyle::question())?.sql());
    // PostgreSQL already sorts nulls last going up, so it needs no NULLS
    // LAST, and MySQL has no NULLS, so it sorts by name IS NULL first.
    for_each_database(&q)?;
    // Values print as SQL would write them, for reading only.
    println!("params: {}", shown(&q.params()));
    // end snippet

    section("2. Values are bound, never spliced");

    // snippet: bound
    let name = "Robert'); DROP TABLE students; --";
    // Building SQL by hand puts the value in the text, where it ends the
    // string early and adds a statement of its own.
    println!("by hand: SELECT id FROM students WHERE name = '{name}'");
    // A hole sends the value apart from the SQL, for the driver to bind.
    let b = common("SELECT id FROM students WHERE name = ");
    b.append_string(Some(name));
    let r = b.build()?.render(Dialect::sqlite(), PlaceholderStyle::question())?;
    println!("wherewith: {}", r.sql());
    println!("params: {}", shown(&r.params()));

    // A name from outside is an Identifier, quoted for each database, never
    // a value or SQL.
    let b = common("SELECT * FROM ");
    b.append_identifier(Identifier::named(r#"students"; DROP TABLE x; --"#)?);
    let q = b.build()?;
    println!("a hostile name: {}", q.render(Dialect::sqlite(), PlaceholderStyle::question())?.sql());
    println!("in MySQL: {}", q.render(Dialect::mysql(), PlaceholderStyle::percent_s())?.sql());

    // A hole inside quotes is refused: it would be text, not a value.
    let b = common("SELECT id FROM students WHERE name = '");
    b.append_string(Some(name));
    b.append_safe("'");
    println!("a hole in quotes: {}", problem(b.template_problem()));
    // end snippet

    section("3. Refused when it's built");

    // snippet: refused
    // Each of these runs on every database, and gives different results on
    // some. template_problem says why build would refuse it, and where.
    let refused = |sql: &str| {
        let found = common(sql).template_problem();
        println!("{sql}: {}", found.map(|s| s.to_string()).unwrap_or("built".into()));
    };

    // 7 / 2 is 3 in SQLite and PostgreSQL, and 3.5 in MySQL and DuckDB.
    refused("SELECT a / 2 FROM t");
    // b = NULL matches no row: NULL isn't equal to anything, even NULL.
    refused("SELECT a FROM t WHERE b = NULL");
    // PostgreSQL reads Name as name; the others keep its case.
    refused("SELECT Name FROM t");
    // SQLite gives any row's a; the others refuse the query.
    refused("SELECT a, count(*) AS n FROM t GROUP BY b");
    // SQLite reads ('a' || 1) + 2, PostgreSQL 'a' || (1 + 2).
    refused("SELECT 'a' || 1 + 2 AS x");
    // Some databases turn 0 into text, and others refuse it.
    refused("SELECT CASE WHEN a > 1 THEN 'x' ELSE 0 END AS c FROM t");
    // A placeholder in the text would shift every value's place.
    refused("SELECT a FROM t WHERE id = ?");
    // What isn't in the common dialect yet is refused too.
    refused("SELECT 1 AS a UNION SELECT 2");
    // The fix for the first: a float operand divides the same everywhere.
    refused("SELECT 7 / 2.0 AS x");
    // A null value is refused where NULL would be.
    let b = common("SELECT a FROM t WHERE b = ");
    b.append_string(None::<&str>);
    println!("SELECT a FROM t WHERE b = ${{null}}: {}", problem(b.template_problem()));
    // end snippet

    section("4. What differs, handled");

    // snippet: differs
    // MySQL's || means OR, so it's CONCAT there.
    let text = "SELECT id || ':' || name AS tag FROM people";
    println!("{text}");
    for_each_database(&common(text).build()?)?;
    // Each database names its types differently, and MySQL's LENGTH counts
    // bytes, not characters.
    let text = "SELECT CAST(score AS INTEGER) AS s, CAST(id AS TEXT) AS t, LENGTH(name) AS n FROM people";
    println!("{text}");
    for_each_database(&common(text).build()?)?;
    // Where nulls sort differs, and so does OFFSET without LIMIT.
    let b = common("SELECT name FROM people ORDER BY nick DESC OFFSET ");
    b.append_int(20);
    println!("SELECT name FROM people ORDER BY nick DESC OFFSET ${{20}}");
    for_each_database(&b.build()?)?;
    // PostgreSQL can't guess a lone parameter's type, so it gets a cast.
    let b = common("SELECT ");
    b.append_string(Some("hi"));
    b.append_safe(" AS greeting");
    println!(r#"SELECT ${{"hi"}} AS greeting"#);
    for_each_database(&b.build()?)?;
    // end snippet

    section("5. Queries in queries");

    // snippet: nested
    let big = common("SELECT user_id FROM orders WHERE total > ");
    big.append_int(100);
    let b = common("SELECT name FROM users WHERE id IN (");
    b.append_query(big.build()?);
    b.append_safe(") AND active = ");
    b.append_string(Some("yes"));
    let q = b.build()?;
    // The inner query's parameters are numbered with the outer query's.
    println!("postgres: {}", q.render(Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql());
    println!("mysql: {}", q.render(Dialect::mysql(), PlaceholderStyle::percent_s())?.sql());
    // And it's checked again as part of the whole, with problems at its hole.
    let inner = common("SELECT user_id FROM orders LIMIT ");
    inner.append_int(5);
    let b = common("SELECT name FROM people WHERE id IN (");
    b.append_query(inner.build()?);
    b.append_safe(")");
    println!("with LIMIT inside: {}", problem(b.template_problem()));
    // end snippet

    section("6. Building queries in code");

    // snippet: dynamic
    // Filters only when given, a sort column from the caller, and a page.
    // Every variant is still checked when it's built.
    fn search(
        word: Option<&str>,
        min_total: Option<i32>,
        sort: Identifier,
        descending: bool,
        page: i32,
    ) -> temper_core::Result<String> {
        let b = common("SELECT id, title FROM orders");
        let mut joiner = " WHERE ";
        if let Some(word) = word {
            b.append_safe(format!("{joiner}title LIKE "));
            b.append_string(Some(word));
            b.append_safe(" || '%' ESCAPE '!'");
            joiner = " AND ";
        }
        if let Some(min_total) = min_total {
            b.append_safe(format!("{joiner}total >= "));
            b.append_int(min_total);
        }
        b.append_safe(" ORDER BY ");
        b.append_identifier(sort);
        b.append_safe(if descending { " DESC LIMIT " } else { " LIMIT " });
        b.append_int(20);
        b.append_safe(" OFFSET ");
        b.append_int(page * 20);
        Ok(b.build()?.render(Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql().to_string())
    }

    let created = Identifier::named("created")?;
    println!("{}", search(None, None, created.clone(), false, 0)?);
    println!("{}", search(Some("Launch"), None, created, false, 0)?);
    println!("{}", search(None, Some(100), Identifier::named("Total")?, true, 2)?);

    // A query for fewer databases relaxes the checks for the others: MySQL
    // reads \ in a string as an escape, so it's refused only while MySQL is
    // a target. The query renders only for its targets.
    let b = QueryBuilder::new(Dialect::common());
    b.set_targets(vec![Dialect::postgres(), Dialect::sqlite()]);
    b.append_safe(r"SELECT 'C:\temp' AS p");
    let q = b.build()?;
    println!("for postgres and sqlite: {}", q.render(Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql());
    println!("for mysql: {}", problem(q.render_problem(Dialect::mysql(), PlaceholderStyle::percent_s())));
    // end snippet

    section("7. Placeholders for each driver");

    // snippet: placeholders
    // The placeholder style depends on the driver, not the database, so it's
    // chosen when rendering. percent_s doubles %, for drivers that fill in
    // values with Python's % formatting.
    let b = common("SELECT name FROM users WHERE name LIKE 'a%' ESCAPE '!' AND id = ");
    b.append_int(1);
    let q = b.build()?;
    let styles = [
        PlaceholderStyle::question(),
        PlaceholderStyle::dollar_numbered(),
        PlaceholderStyle::percent_s(),
        PlaceholderStyle::at_named(),
        PlaceholderStyle::colon_named(),
    ];
    for style in styles {
        println!("{}: {}", style.to_string(), q.render(Dialect::sqlite(), style.clone())?.sql());
    }
    // A named style refuses text holding its marker, which a driver could
    // misread as a name.
    let b = common("SELECT 'a:b' AS s FROM users WHERE id = ");
    b.append_int(1);
    let found = b.build()?.render_problem(Dialect::sqlite(), PlaceholderStyle::colon_named());
    println!("colonNamed with 'a:b': {}", problem(found));
    // end snippet

    section("8. Each database's own SQL");

    // snippet: own-sql
    // For SQL the common dialect doesn't cover yet, a database's own
    // template, checked with its rules. In Temper, postgres"…" builds it.
    let b = QueryBuilder::new(Dialect::postgres());
    b.append_safe("INSERT INTO tags (name) VALUES (");
    b.append_string(Some("sql"));
    b.append_safe(") ON CONFLICT (name) DO NOTHING RETURNING id");
    let q = b.build()?;
    println!("upsert: {}", q.render(Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql());
    // It renders only for its own database.
    println!("for mysql: {}", problem(q.render_problem(Dialect::mysql(), PlaceholderStyle::percent_s())));
    // A common query nests in it, rendered for that database.
    let b = QueryBuilder::new(Dialect::postgres());
    b.append_safe("SELECT jsonb_agg(x) FROM (");
    b.append_query(big.build()?);
    b.append_safe(") AS s(x)");
    println!("nested: {}", b.build()?.render(Dialect::postgres(), PlaceholderStyle::dollar_numbered())?.sql());
    // # starts a comment in MySQL only, so a value after it would vanish.
    let b = QueryBuilder::new(Dialect::mysql());
    b.append_safe("SELECT * FROM t WHERE a = 1 # ");
    b.append_string(Some("x"));
    println!("mysql, after #: {}", problem(b.template_problem()));
    // end snippet

    section("9. Quoting by hand");

    // snippet: quoting
    // For tools that write SQL text themselves, such as DDL defaults. Each
    // gives an Err rather than change what it can't write, and a _problem
    // method says why.
    println!("mysql name: {}", Dialect::mysql().quote_name("my `table`")?);
    println!("mysql string: {}", Dialect::mysql().quote_string(r"it's \ fine")?);
    println!("postgres string: {}", Dialect::postgres().quote_string(r"it's \ fine")?);
    let long_name = "n".repeat(64);
    println!("postgres, 64-byte name: {}", problem(Dialect::postgres().name_problem(long_name.as_str())));
    match Dialect::postgres().quote_string("a\0b") {
        Ok(_) => println!("postgres, NUL in a string: quoted"),
        Err(_) => println!("postgres, NUL in a string: refused, {}", problem(Dialect::postgres().string_problem("a\0b"))),
    }
    match Identifier::named(long_name.as_str()) {
        Ok(_) => println!("Identifier, 64 bytes: named"),
        Err(_) => println!("Identifier, 64 bytes: refused, {}", problem(identifier_problem(long_name.as_str()))),
    }
    // end snippet

    // The tour stops at what the driver gets. The repo's tests/engines run
    // these kinds of queries through SQLite, DuckDB, PostgreSQL, and
    // MariaDB.
    Ok(())
}
