// Test graph behavior with text vs SMCL logs
// Verifies that graph export is independent of log format

set more off
sysuse auto, clear

// --- Scatter plot ---
twoway (scatter price mpg), title("Price vs MPG") name(g1, replace)
graph export /tmp/test_graph1.png, replace width(1200)

// --- Regression diagnostics ---
regress price mpg weight
predict resid, residuals
histogram resid, title("Residual Distribution") name(g2, replace)
graph export /tmp/test_graph2.png, replace width(1200)

// --- Check graph directory ---
graph dir

display "Graph test complete."
