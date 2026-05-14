# stata-graph

Manage Stata graphs in memory.

## Commands

- `stata graph list [--session NAME]` — List graphs in memory
- `stata graph export --name NAME --format pdf|png|svg [--out /path]` — Export a graph
- `stata graph export-all --format pdf|png [--outdir ./figures]` — Export all graphs

## Best Practices

1. Name graphs explicitly in Stata: `twoway scatter price mpg, name(myfig)`
2. After graph-generating code, run `stata graph list` to see what was created.
3. Export with `stata graph export --name myfig --format svg --out figs/myfig.svg`.

## Notes

- Unnamed graphs appear as `"Graph"` in the list.
- `export-all` renames unnamed graphs to `_unnamedN`.
