* long.do - Long-running Stata script for break/cancel testing
clear all
set obs 100000
gen x = runiform()
gen y = x + rnormal()

* Run a long bootstrap (5000 reps) that will take a while
capture program drop myreg
program define myreg, rclass
    reg y x
    return scalar b = _b[x]
end

set seed 12345
di "Starting bootstrap at $S_DATE $S_TIME..."
bootstrap b=r(b), reps(5000) seed(12345): myreg
di "Bootstrap finished at $S_DATE $S_TIME"
