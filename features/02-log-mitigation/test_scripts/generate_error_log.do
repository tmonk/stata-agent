// Generate a log with an error at the end
set more off
sysuse auto, clear

describe
summarize

forvalues i = 1/100 {
    display "Iteration `i': normal processing continues..."
}

regress price mpg weight

// This will fail: variable does not exist
regress price nonexistent_variable_that_fails
