// Generate a large log file with 5000 display lines
set more off

// Use a dataset to make output realistic
sysuse auto, clear

describe
summarize

forvalues i = 1/5000 {
    display "Iteration `i': This is a sample log line to simulate realistic Stata output."
    display "    Variables: make price mpg rep78 headroom trunk weight length turn displacement gear_ratio foreign"
    display "    Summary statistics for iteration `i' are computed and displayed here."
}

regress price mpg weight
