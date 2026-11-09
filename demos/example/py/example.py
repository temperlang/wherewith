"""Wherewith's example, from Python: the same query for each database.

The same example exists for each language Wherewith supports, and they all
print the same text. See demos/README.md for how to run them.
"""

# snippet: example
from wherewith import Dialect, PlaceholderStyle, QueryBuilder

word = "Launch"

# One query, in the common dialect, checked for every database.
b = QueryBuilder(Dialect.common)
b.append_safe('SELECT title, "dueDate" FROM tasks WHERE title LIKE ')
b.append_string(word)
b.append_safe(" || '%' ESCAPE '!' ORDER BY \"dueDate\" NULLS LAST LIMIT ")
b.append_int(20)
b.append_safe(" OFFSET ")
b.append_int(40)
q = b.build()

# Rendered for each database, with the placeholders its driver takes.
print("sqlite: " + q.render(Dialect.sqlite, PlaceholderStyle.question).sql)
print("postgres: " + q.render(Dialect.postgres, PlaceholderStyle.dollar_numbered).sql)
print("mysql: " + q.render(Dialect.mysql, PlaceholderStyle.percent_s).sql)
r = q.render(Dialect.duckdb, PlaceholderStyle.dollar_numbered)
print("duckdb: " + r.sql)
# The values travel apart from the SQL, for the driver to bind.
print("params: " + str(len(r.params)))

# What databases would read differently is refused, with its place.
bad = QueryBuilder(Dialect.common)
bad.append_safe("SELECT title, dueDate FROM tasks")
print("refused: " + bad.template_problem)  # and bad.build() raises
# end snippet
