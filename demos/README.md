# Demos

## Example

`example/` builds the same query in each supported language: a name bound
as a parameter and a table name quoted, for SQLite, PostgreSQL, MySQL and
MariaDB, and DuckDB, each checked with its database's rules and rendered
with a placeholder style its drivers take, then a value inside quotes,
refused. Every version prints the same text,
`example/expected.txt`, so the examples double as a cross-language test.
The site shows them.

A full tour of the API comes once the statement model lands.

First build the libraries from the repo's top, with
[Temper](https://temperlang.dev/):

    temper build -b cpp -b csharp -b java -b js -b lua -b py -b rust

Each example uses the generated library in `temper.out/` by relative
path. Run one from its directory:

| Language | In `example/…` | Commands |
|---|---|---|
| C++ | `cpp` | `cmake -B build && cmake --build build && ./build/example` |
| C# | `csharp` | `dotnet run` |
| Java | `java` | `./gradlew run` |
| JavaScript | `js` | `npm ci && npm start` |
| Lua | `lua` | `lua -l paths example.lua` |
| Python | `py` | `uv run example.py` |
| Rust | `rust` | `cargo run` |

Or run them all and compare each with `expected.txt`:

    uv run demos/run.py [LANGUAGE ...]

CI does the same for each backend, after its tests.

### Snippets for the site

The lines between a comment `snippet: example` and a comment
`end snippet`, each alone on its line, are what the site shows for each
language; `site/build.py` collects them and fails if one is missing. The
site's Temper is the same kind of snippet, `snippet: temper`, in the
site's example test in `src/query-tests.temper.md`.

Java's Gradle build compiles the generated sources along with the
example, because the generated Maven projects expect a JDK 8 toolchain
and release signing. Python's example names Temper's runtime as a
dependency too, so it comes from `temper.out/`, not from older releases
on PyPI.
