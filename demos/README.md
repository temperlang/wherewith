# Demos

## Example

`example/` builds the same common query in each supported language,
checked once for every database, and renders it for SQLite, PostgreSQL,
MySQL and MariaDB, and DuckDB, each with a placeholder style its drivers
take; then a bare mixed-case name, refused, since PostgreSQL would fold
it. Every version prints the same text, `example/expected.txt`, so the
examples double as a cross-language test. The site shows them.

## Tour

`tour/` walks through Wherewith's whole public API in each supported
language, in nine steps: writing a query once, values bound and never
spliced, what's refused when a query is built and why, what each
database needs written differently, queries in queries, building
queries in code, placeholder styles, each database's own SQL, and
quoting by hand. Every version prints the same text,
`tour/expected.txt`, so the tours double as a cross-language test.
Only Temper has the `sql` tag, so the others build each common query
with a `QueryBuilder`, as the tag does. The Temper tour is a test,
`src/tour-tests.temper.md`, which checks it prints the same.

## Running them

First build the libraries from the repo's top, with
[Temper](https://temperlang.dev/):

    temper build -b cpp -b csharp -b java -b js -b lua -b py -b rust

Each example and tour uses the generated library in `temper.out/` by
relative path. Run one from its directory, with `example` or `tour` for
NAME:

| Language | In `example/…` or `tour/…` | Commands |
|---|---|---|
| C++ | `cpp` | `cmake -B build && cmake --build build && ./build/NAME` |
| C# | `csharp` | `dotnet run` |
| Java | `java` | `./gradlew run` |
| JavaScript | `js` | `npm ci && npm start` |
| Lua | `lua` | `lua -l paths NAME.lua` |
| Python | `py` | `uv run NAME.py` |
| Rust | `rust` | `cargo run` |

Or run them all and compare each with its `expected.txt`:

    uv run demos/run.py [LANGUAGE ...]

That also checks that the Temper tour's `tourOutput` is
`tour/expected.txt`, and prints what to paste there if not; `temper
test` runs the Temper tour itself. CI does the same for each backend,
after its tests.

### Snippets for the site

The lines between a comment `snippet: example` and a comment
`end snippet`, each alone on its line, are what the site shows for each
language; `site/build.py` collects them and fails if one is missing. The
site's Temper is the same kind of snippet, `snippet: temper`, in the
site's example test in `src/query-tests.temper.md`.

The tours mark each step the same way, `snippet: setup` and then one
name per step, such as `snippet: refused`, and the site shows each
step's code with its part of `tour/expected.txt`. A step can take more
than one block, such as a helper function and the code that calls it,
shown in order. Every tour, Temper's too, must have every step.

Java's Gradle build compiles the generated sources along with the
example, because the generated Maven projects expect a JDK 8 toolchain
and release signing. Python's example names Temper's runtime as a
dependency too, so it comes from `temper.out/`, not from older releases
on PyPI.
