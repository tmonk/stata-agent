// Test do-file for Text-First Native Logs verification
// Produces mixed output: display, regression, tables, and an intentional error

set more off
set linesize 80

// Load sample data
sysuse auto, clear

// --- Display output ---
display "=== Text-First Log Test ==="
display "Date: " c(current_date)
display "Version: " c(version)

// --- Descriptive statistics ---
describe
summarize price mpg weight length

// --- Regression output ---
regress price mpg weight

// --- Tabulation ---
tabulate foreign rep78

// --- Loop output ---
forvalues i = 1/10 {
    display "Processing iteration `i'..."
}

// --- Intentional error ---
// This will fail and produce an error message
display "About to trigger an error..."
regress price nonexistent_var_12345

// --- End ---
display "End of test do-file"
