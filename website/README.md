# KVCache Upper Bound Oracle — Results Dashboard

A self-contained, offline web dashboard for visualising output files produced by
the **KVCache Upper Bound Oracle** tool.

## Opening the dashboard

No server or build step is required.  Just open `index.html` directly in your
browser:

```
# macOS
open website/index.html

# Linux
xdg-open website/index.html

# Windows
start website/index.html
```

Or drag the file into an already-open browser tab.

## Loading results

After the page loads you will see a **drag-and-drop zone**.  Drop one or more
output files from your run directory onto it, or click **Browse files** and
select them with the system file picker.

Recognised file names (any subset is fine):

| File | Section populated |
|------|-------------------|
| `metadata.json` | Run Metadata |
| `hit_summary.csv` | Hit Rate Summary (table + bar chart) |
| `heuristic_summary.csv` | Hit Rate Summary (heuristic estimates) |
| `tier_summary.csv` | Capacity Tier Comparison |
| `planning_strict_prefix.csv` | Planning Summary — Strict-Prefix column |
| `planning_lru.csv` | Planning Summary — LRU column |

Files can be dropped all at once or one at a time.  Each chip in the file list
turns green (✅) on success or red (❌) with an error message on failure.

## Notes

* The dashboard works entirely in the browser — no data leaves your machine.
* Chart.js is loaded from `https://cdn.jsdelivr.net/npm/chart.js` (CDN); an
  internet connection is required the first time, after which the browser cache
  is used.  If you need a fully offline setup, download
  `chart.umd.min.js` and replace the `<script src="...">` tag in `index.html`.
* Column sets in the CSVs are dynamic (some columns are optional).  The
  dashboard auto-detects which columns are present and shows only those.
