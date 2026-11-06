# PostgreSQL

## Profile

`Dialect.postgres`, in the [core](core.temper.md), quotes names in
`"…"` and strings in `'…'`, doubling the quote inside.

PostgreSQL truncates names longer than 63 bytes, so two long names
could become the same one; Wherewith rejects them instead.

The profile assumes `standard_conforming_strings` is on, the default
since PostgreSQL 9.1, so backslashes in strings are plain characters.
Wherewith never writes `E'…'` strings. A NUL can't be written in a
string, since PostgreSQL's text can't hold one.

Queries for PostgreSQL are planned; see the [design](../docs/design.md).
