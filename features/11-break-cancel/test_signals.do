clear all
set obs 5000
gen x = runiform()
gen y = x + rnormal()

local i = 1
while 1 {
    quietly reg y x
    quietly reg y x c.x##c.x
    local i = `i' + 1
    if mod(`i', 50000) == 0 {
        di "Completed `i' iterations..."
    }
}
