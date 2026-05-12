* while.do - Infinite while loop for SIGINT testing
clear all
set obs 1000
gen x = runiform()
gen y = x + rnormal()

di "Entering infinite loop at $S_DATE $S_TIME"
local i = 1
while 1 {
    quietly reg y x
    quietly reg y x c.x##c.x
    local i = `i' + 1
    if mod(`i', 10000) == 0 {
        di "Completed `i' iterations..."
    }
}
di "This should NOT be reached"
