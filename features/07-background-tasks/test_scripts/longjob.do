clear all
set seed 12345
set obs 20000
generate y = rnormal(0,1)
generate x1 = rnormal(0,1)
generate x2 = rnormal(0,1)
generate x3 = rnormal(0,1)
generate x4 = rnormal(0,1)

timer on 1
forvalues i = 1/10000 {
    quietly regress y x1 x2 x3 x4
    if mod(`i', 1000) == 0 {
        display "PROGRESS: `i'/10000"
    }
}
timer off 1
quietly timer list 1
display "DONE: `=r(t1)' seconds"
