# ADR Format

ADRs live in `docs/adr/` and use sequential numbering: `0001-slug.md`, `0002-slug.md`, and so on, unless the repository defines a more specific convention.

Create the ADR directory lazily, only when the first ADR is explicitly needed and accepted by the user.

## Template

```md
# {Short title of the decision}

{1-3 sentences: what is the context, what was decided, and why.}
```

An ADR can be a single paragraph. Its value is recording that a decision was made and why, not filling out sections.

## Optional sections

Include these only when they add genuine value. Most ADRs do not need them.

- **Status** frontmatter (`proposed | accepted | deprecated | superseded by ADR-NNNN`): use when decisions may be revisited.
- **Considered Options**: use only when rejected alternatives are worth remembering.
- **Consequences**: use only when non-obvious downstream effects should be called out.

## Numbering

Scan the applicable ADR directory for the highest existing number and increment it by one.

## Qualification test

Offer an ADR only when the decision is hard to reverse, surprising without context, and the result of a real trade-off.

Qualifying examples include:

- Architectural shape, such as monorepo structure or event-sourced writes.
- Integration patterns between bounded contexts.
- Technology choices with meaningful lock-in.
- Ownership, boundary, and scope decisions.
- Deliberate deviations from an obvious or established path.
- Constraints that are not visible in code.
- Rejected alternatives whose rejection is non-obvious and likely to be revisited.
