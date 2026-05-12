clear all
set seed 12345
set obs 10000
generate y = rnormal(0,1)
generate x1 = rnormal(0,1)
generate x2 = rnormal(0,1)

timer on 1
forvalues i = 1/500 {
    quietly regress y x1 x2
    if mod(`i', 50) == 0 {
        display "PROGRESS: `i'/500"
    }
}
timer off 1
quietly timer list 1
display "DONE: `=r(t1)' seconds"
