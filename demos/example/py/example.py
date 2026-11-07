"""Wherewith's example, from Python: the same query for each database.

The same example exists for each language Wherewith supports, and they all
print the same text. See demos/README.md for how to run them.
"""

# snippet: example
from wherewith import Dialect, Identifier, PlaceholderStyle, QueryBuilder

name = "Robert'); DROP TABLE students; --"


def find(dialect, style):
    """The query for one database, checked with its rules, rendered for it."""
    b = QueryBuilder(dialect)
    b.append_safe("SELECT id FROM ")
    b.append_identifier(Identifier.named("students"))
    b.append_safe(" WHERE name = ")
    b.append_string(name)
    return b.build().render(dialect, style)


# Each database's quoting, with the placeholders its driver takes.
print("sqlite: " + find(Dialect.sqlite, PlaceholderStyle.question).sql)
print("postgres: " + find(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
print("mysql: " + find(Dialect.mysql, PlaceholderStyle.percent_s).sql)
r = find(Dialect.duckdb, PlaceholderStyle.dollar_numbered)
print("duckdb: " + r.sql)
# The name travels apart from the SQL, for the driver to bind.
print("params: " + str(len(r.params)))

# A value inside quotes is refused, not guessed at.
bad = QueryBuilder(Dialect.postgres)
bad.append_safe("SELECT id FROM students WHERE name = '")
bad.append_string(name)
bad.append_safe("'")
print("refused: " + bad.template_problem)  # and bad.build() raises
# end snippet
