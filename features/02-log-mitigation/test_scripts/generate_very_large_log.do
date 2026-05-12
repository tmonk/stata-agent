// Generate a very large log file (target ~5MB)
set more off

sysuse auto, clear
describe
summarize

forvalues i = 1/25000 {
    display "Iteration `i': This is a sample log line to simulate realistic Stata output with multiple tokens and variables."
    display "    make price mpg rep78 headroom trunk weight length turn displacement gear_ratio foreign"
    display "    Observations: 74, Variables: 12, Iteration count: `i'"
}

regress price mpg weight
