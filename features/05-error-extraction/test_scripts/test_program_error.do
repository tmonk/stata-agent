// Test 5: Program-defined error
capture program drop badprog
program define badprog
    error 111
end
badprog
display "_rc after program error = " _rc
