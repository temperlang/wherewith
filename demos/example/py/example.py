"""Wherewith's example, from Python: one query, rendered for each database.

The same example exists for each language Wherewith supports, and they all
print the same text. See demos/README.md for how to run them.
"""

# snippet: example
from wherewith import Dialect, Identifier, PlaceholderStyle, QueryBuilder

name = "Robert'); DROP TABLE students; --"
b = QueryBuilder(Dialect.postgres)
b.append_safe("SELECT id FROM ")
b.append_identifier(Identifier.named("students"))
b.append_safe(" WHERE name = ")
b.append_string(name)
q = b.build()

# Each database's quoting, with the placeholders its driver takes.
print("sqlite: " + q.render(Dialect.sqlite, PlaceholderStyle.question).sql)
print("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
print("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percent_s).sql)
r = q.render(Dialect.duckdb, PlaceholderStyle.dollar_numbered)
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
