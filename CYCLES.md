# Reference cycles: a trial

A trial of Temper's proposed memory cycle checker, for discussion: what
would it report on Wherewith, and what would Wherewith change to pass?
The checker doesn't exist yet, so this branch pretends it does. Nothing
here needs to compile.

Backends without a garbage collector (C++, Rust) reference count
Temper's objects, and reference counting can't free a cycle. The
proposal makes cycles a compile-time error, with `forbids` clauses on
type parameters and type declarations (`class Cons<T forbids Cons<T>>`)
to say what a type may never lead back to. It builds on Temper issues
[#5](https://github.com/temperlang/temper/issues/5) ("does not
reference" bounds) and [#7](https://github.com/temperlang/temper/issues/7)
(`this` escaping a constructor).

## The rules, as read here

1. **A "may reference" graph over types.** An edge from `A` to `B` when
   an `A` can hold a `B`: a field, a `List` or `ListBuilder` element, a
   `Map` or `MapBuilder` key or value, or a variable captured by a
   stored closure. Edges count subtypes, so an interface reaches every
   implementation.
2. **Mutable edges** are `var` fields, builder elements, keys, and
   values, and captured `var`s. A field typed `Listed` or `Mapped` may
   hold a builder, so its elements count as mutable too.
3. **Every loop through a mutable edge is an error,** reported at that
   field. Loops of immutable edges are fine: an object can only point at
   older ones.
4. **Generic instantiations** are checked against `forbids` where they
   happen.
5. **Constructors:** `this` isn't used until every field is set (already
   the rule). Nothing here leaks `this` from a constructor later either.

Where the proposal and other sketches differ or are silent, this trial
takes the stricter, more literal reading:

- **`forbids` is transitive:** `T forbids X` means a `T` can't reach an
  `X` by any path, as the proposal's `Cons` example needs.
- **Open types reach anything.** `AnyValue`, and an interface with
  implementations the library can't see (exported and not `sealed`,
  including `@fun` interfaces), have an edge to every type. That counts
  on any path, not only for fields declared with that type: a mutable
  edge whose target can reach an open type can lead back.
- **Closed interfaces** are `sealed` ones and ones not exported, whose
  implementations are all in the library.
- **Stored closures** (a field or element of a function or `@fun`
  interface type) have edges to what they capture. Closures only passed
  as arguments add none.
- **std's types:** `ListBuilder`, `MapBuilder`, and similar hold mutable
  edges to their elements, and declare `forbids` on them (say,
  `ListBuilder<T forbids ListBuilder<T>>`). `List` and `Map` hold
  immutable ones. `StringBuilder` holds only text.
- **No write-once exemption:** a `var` set only before its object
  escapes still counts as mutable (#7's `late` isn't in the proposal).

## What it reports

Nothing. Types analyzed: 77 (73 in the library, 4 in its tests), with
no reports, so no `forbids` clauses, no restructures, and no cases the
rules can't express.

Why it's clean:

- **No generic types** of its own, so nothing needs a `forbids` clause
  to stay usable.
- **Exported interfaces are all `sealed`** (`SqlValue`, `QueryPart`,
  `TemplateCheck`), and `SqlLexer` isn't exported, so every interface is
  closed.
- **Trees are immutable:** expression and statement nodes take every
  field in the header, and point only down.
- **Builders hold leaves:** `QueryBuilder`'s `parts` and `holes` hold
  `QueryPart`s, the lexers' lists hold tokens and strings, and none of
  those reach back.
- **No stored closures:** every function value is passed to a call
  (`join`, the tests' `check { … }`) and dropped.

## Near misses

What would have been reported with small changes, for the discussion:

- **`QueryBuilder.check`** is a `var` cache of the template's check,
  which holds a `CommonQuery`, which holds the builder's `CommonLexer`.
  It passes because the check holds the lexer, not the builder. A check
  that kept its builder, to re-run lazily, would be a cycle.
- **The two parsers** recurse into each other by making a
  `StatementParser` per subquery rather than storing one in the
  `CommonParser`, as common-statements notes. Holding each other would
  need a `var` (a constructor can't pass `this` on before its fields are
  set), and so a report.
- **Nested queries:** `appendQuery` copies a query's parts into the
  builder rather than keeping the `Query`. Keeping it would still pass,
  since a `Query` can't reach a builder.
- **Exporting `SqlLexer`** for pluggable dialects wouldn't add a report:
  `QueryBuilder.lexer` is immutable, and its mutable edges don't reach
  the interface.

Not a cycle, but worth knowing: a `Query` from a common builder holds
that builder's `CommonLexer`, which goes on changing if the builder is
used after `build`. "Immutable" to the checker means its own fields,
not everything below them.

## Noise and real risks

No noise, and no real risks caught. Wherewith's style (immutable
records, sealed interfaces, builders that hold values and give back
copies) is the one the proposal says should just work, and here it
does.
