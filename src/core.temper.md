# Core

What every dialect shares: the `Dialect` class with its quoting rules,
names that are safe in every dialect, and the values queries bind as
parameters. [Queries](query.temper.md) hold text, values, and names
apart, and render for a dialect. Each database's own rules, query tag,
and template lexer are in its file:
[SQLite](sqlite.temper.md), [PostgreSQL](postgres.temper.md), and
[MySQL and MariaDB](mysql.temper.md).

## Dialects

A *Dialect* is a profile of one database's SQL text rules. Each starts
from the core the three databases share, and overrides only where its
database differs:

- **Names** (delimited identifiers) go in `"…"`, with `"` doubled.
  MySQL and MariaDB use `` `…` `` instead, with `` ` `` doubled, which
  works whether or not `ANSI_QUOTES` is on.
- **Strings** go in `'…'`, with `'` doubled. MySQL and MariaDB also
  read backslash escapes in strings, unless the server runs with
  `NO_BACKSLASH_ESCAPES`, so their profile escapes `\` as well.

The [design](../docs/design.md) has the details, with links to each
database's manual.

    export class Dialect {

`name` is a short name for the profile, for messages and tests.

      public name: String;

The quote around names, as a code point.

      private nameQuote: Int;

Whether the server may read backslash escapes in strings, so `\`, NUL,
and Ctrl-Z get escaped with a backslash. Strings are always quoted with
`'` doubled, never `\'`, so they end in the same place either way.

      private backslashEscapes: Boolean;

Limits on names, where the database truncates or rejects longer ones:
UTF-8 bytes and code points, or 0 for none.

      private maxNameBytes: Int;
      private maxNameCodePoints: Int;

Whether names may hold code points above U+FFFF, and may end in a
space.

      private nonBmpNames: Boolean;
      private trailingSpaceNames: Boolean;

      private constructor(
        name: String,
        nameQuote: Int,
        backslashEscapes: Boolean,
        maxNameBytes: Int,
        maxNameCodePoints: Int,
        nonBmpNames: Boolean,
        trailingSpaceNames: Boolean,
      ) {
        this.name = name;
        this.nameQuote = nameQuote;
        this.backslashEscapes = backslashEscapes;
        this.maxNameBytes = maxNameBytes;
        this.maxNameCodePoints = maxNameCodePoints;
        this.nonBmpNames = nonBmpNames;
        this.trailingSpaceNames = trailingSpaceNames;
      }

      public toString(): String { name }

### Profiles

The profiles are here, since only the class can call its private
constructor; each database's file explains its profile.

[SQLite](sqlite.temper.md): no backslash escapes and no limit on names.

      public static sqlite: Dialect = doPure {
        new Dialect("sqlite", char'"', false, 0, 0, true, true)
      };

[PostgreSQL](postgres.temper.md): names up to 63 bytes, and
`standard_conforming_strings` assumed on.

      public static postgres: Dialect = doPure {
        new Dialect("postgres", char'"', false, 63, 0, true, true)
      };

[MySQL and MariaDB](mysql.temper.md): names up to 64 characters, in
the Basic Multilingual Plane, with no trailing space. The default
profile works in every SQL mode.

      public static mysql: Dialect = doPure {
        new Dialect("mysql", char'`', true, 0, 64, false, false)
      };

Only for servers known to run with `NO_BACKSLASH_ESCAPES`. **It's
unsafe on a server without that mode.**

      public static mysqlNoBackslashEscapes: Dialect = doPure {
        new Dialect("mysqlNoBackslashEscapes", char'`', false, 0, 64, false, false)
      };

### Quoting names

`quoteName` quotes a name (an identifier: a table, a column, or other
object), or bubbles if `nameProblem` finds one. One name at a time:
`schema.table` is two names, each quoted.

      public quoteName(name: String): String throws Bubble {
        if (nameProblem(name) != null) { bubble() }
        let quote = String.fromCodePoint(nameQuote) orelse panic();
        "${quote}${replaceCodePoint(name, nameQuote, "${quote}${quote}")}${quote}"
      }

`nameProblem` says why a name can't be quoted for this dialect, or is
null if it can. Every dialect rejects an empty name, NUL, and lone
surrogates (only possible in languages whose strings are UTF-16).

      public nameProblem(name: String): String? {
        if (name.isEmpty) { return "empty name"; }
        var bytes = 0;
        var codePoints = 0;
        var last = 0;
        for (var i = String.begin; name.hasIndex(i); i = name.next(i)) {
          let c = name[i];
          if (c == 0) { return "NUL in name"; }
          if (c >= 0xD800 && c <= 0xDFFF) { return "lone surrogate in name"; }
          if (c > 0xFFFF && !nonBmpNames) { return "code point above U+FFFF in name"; }
          bytes += utf8Length(c);
          codePoints += 1;
          last = c;
        }
        if (maxNameBytes > 0 && bytes > maxNameBytes) {
          return "name longer than ${maxNameBytes.toString()} UTF-8 bytes";
        }
        if (maxNameCodePoints > 0 && codePoints > maxNameCodePoints) {
          return "name longer than ${maxNameCodePoints.toString()} characters";
        }
        if (last == char' ' && !trailingSpaceNames) { return "name ends in a space"; }
        null
      }

### Quoting strings

`quoteString` quotes text as a string literal, or bubbles if
`stringProblem` finds one. Prefer binding values as parameters; this is
for SQL that has to be text, such as a `DEFAULT` in DDL.

      public quoteString(value: String): String throws Bubble {
        if (stringProblem(value) != null) { bubble() }
        var sbOrNull: StringBuilder? = null;
        var upTo = String.begin;
        let end = value.end;
        for (var i = String.begin, next = i; i < end; i = next) {
          next = value.next(i);
          let c = value[i];
          let replacement: String? = if (c == char'\'') {
            "''"
          } else if (!backslashEscapes) {
            null
          } else if (c == char'\\') {
            "\\\\"
          } else if (c == 0) {
            "\\0"
          } else if (c == 0x1A) {
            "\\Z"
          } else {
            null
          };
          if (replacement != null) {
            let sbNow = sbOrNull;
            let sb = sbNow ?? new StringBuilder();
            sbOrNull = sb;
            sb.appendBetween(value, upTo, i);
            sb.append(replacement);
            upTo = next;
          }
        }
        let sb = sbOrNull;
        if (sb != null) {
          sb.appendBetween(value, upTo, end);
          "'${sb.toString()}'"
        } else {
          "'${value}'"
        }
      }

`stringProblem` says why text can't be a string literal for this
dialect, or is null if it can. A NUL can't be written in SQLite's or
PostgreSQL's strings (SQLite's parser ends the text there, and
PostgreSQL's text can't hold one), nor under `NO_BACKSLASH_ESCAPES`,
where nothing escapes it. Lone surrogates have no UTF-8 form.

      public stringProblem(value: String): String? {
        for (var i = String.begin; value.hasIndex(i); i = value.next(i)) {
          let c = value[i];
          if (c == 0 && !backslashEscapes) { return "NUL in string"; }
          if (c >= 0xD800 && c <= 0xDFFF) { return "lone surrogate in string"; }
        }
        null
      }
    }

## Names in every dialect

An *Identifier* is a name that's safe to quote in every dialect
Wherewith knows, so it can go in any query: not empty, at most 63 UTF-8
bytes and 64 characters, no NUL, nothing above U+FFFF, and no trailing
space. In a template, it's written quoted, as SQL text.

    export class Identifier {
      public name: String;

      private constructor(name: String) {
        this.name = name;
      }

      public toString(): String { name }

      public static named(name: String): Identifier throws Bubble {
        if (identifierProblem(name) != null) { bubble() }
        new Identifier(name)
      }
    }

`identifierProblem` gives the first problem any dialect finds, or null.

    export let identifierProblem(name: String): String? {
      Dialect.postgres.nameProblem(name) ?? Dialect.mysql.nameProblem(name)
    }

## Values

A *SqlValue* is a parameter's value, typed so each driver can bind it
with its own type.

    export sealed interface SqlValue {}

    export class SqlText(public value: String) extends SqlValue {}
    export class SqlInt(public value: Int64) extends SqlValue {}
    export class SqlFloat(public value: Float64) extends SqlValue {}
    export class SqlBool(public value: Boolean) extends SqlValue {}
    export class SqlNull() extends SqlValue {}

## Helpers

The number of bytes in code point `c`'s UTF-8 form.

    let utf8Length(c: Int): Int {
      if (c < 0x80) { 1 } else if (c < 0x800) { 2 } else if (c < 0x10000) { 3 } else { 4 }
    }

`replaceCodePoint` replaces each `target` in `s`, returning `s` itself
when there's none.

    let replaceCodePoint(s: String, target: Int, replacement: String): String {
      var sbOrNull: StringBuilder? = null;
      var upTo = String.begin;
      let end = s.end;
      for (var i = String.begin, next = i; i < end; i = next) {
        next = s.next(i);
        if (s[i] != target) { continue; }
        let sbNow = sbOrNull;
        let sb = sbNow ?? new StringBuilder();
        sbOrNull = sb;
        sb.appendBetween(s, upTo, i);
        sb.append(replacement);
        upTo = next;
      }
      let sb = sbOrNull;
      if (sb != null) {
        sb.appendBetween(s, upTo, end);
        sb.toString()
      } else {
        s
      }
    }
