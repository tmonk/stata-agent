---
name: stata-graph
description: List, export, and review Stata graphs from the current session.
---

1. Call `stata graph list` to see all graphs in memory, with the active graph marked.

2. If an argument (graph name) was provided:
   - Call `stata graph export --name <graph_name> --format png` and display the exported file path.

3. If no argument was provided and graphs exist:
   - Call `stata graph export-all --format png` to export all graphs.
   - Display all exported file paths for the user to inspect.

4. If no graphs are in memory, tell the user to create a graph first (e.g., `stata run "histogram price"` or `stata run "scatter price mpg"`).

After export, review the graph(s): check titles, axis labels, legends, and whether the plot matches expectations. Report any issues.

## CLI Reference

| Command | Description |
|---|---|
| `stata graph list [--session NAME]` | List graphs in memory, active graph marked |
| `stata graph export --name NAME --format png\|pdf\|svg [--out /path]` | Export a named graph |
| `stata graph export-all --format png\|pdf [--outdir ./figures]` | Export all graphs |

- Unnamed graphs appear as `"Graph"` in the list.
- `export-all` renames unnamed graphs to `_unnamedN`.
- Name graphs explicitly in Stata: `twoway scatter price mpg, name(myfig)`
