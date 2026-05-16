# Lineage Checklist

Track:

- source datasets,
- merge keys and merge types,
- sample restrictions,
- generated variables,
- saved intermediates,
- outputs that depend on each stage.

Flag any step that is hard to reproduce from committed code and named inputs.

Use `stata inspect describe` to verify dataset state at each pipeline stage and `stata log errors` to detect warnings from merge or append operations.
