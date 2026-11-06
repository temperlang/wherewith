# MySQL and MariaDB

## Profiles

`Dialect.mysql` and `Dialect.mysqlNoBackslashEscapes`, in the
[core](core.temper.md), quote names in `` `…` `` with `` ` `` doubled,
which works whether or not `ANSI_QUOTES` is on, and strings in `'…'`
with `'` doubled. MariaDB shares these profiles.

MySQL and MariaDB limit most names to 64 characters, within the Basic
Multilingual Plane, and not ending in a space.

The default profile, `Dialect.mysql`, works in every SQL mode: strings
escape `\`, NUL, and Ctrl-Z with a backslash, which reads back exactly
in the default mode, and only reads back with extra backslashes under
`NO_BACKSLASH_ESCAPES`, never unsafely.

For servers known to run with `NO_BACKSLASH_ESCAPES`,
`Dialect.mysqlNoBackslashEscapes` leaves backslashes alone, so they
read back exactly. **It's unsafe on a server without that mode**, where
a value ending in `\` would escape the closing quote. With nothing to
escape it, a NUL can't be written in its strings.

Queries for MySQL and MariaDB are planned; see the
[design](../docs/design.md).
