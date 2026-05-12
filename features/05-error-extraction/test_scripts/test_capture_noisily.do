// Test capture noisily wrappers around each error type
clear
sysuse auto, clear

display "=== Standard error with capture noisily ==="
capture noisily regress y z_nonexistent
display "_rc = " _rc

display "=== Mata error with capture ==="
capture noisily mata: x = y + z
display "_rc = " _rc

display "=== Assertion with capture noisily ==="
capture noisily assert 1==0
display "_rc = " _rc

display "=== Custom error with capture noisily ==="
capture noisily display as error "custom msg"
display "_rc = " _rc

display "=== Program error with capture noisily ==="
capture program drop badprog2
program define badprog2
    error 111
end
capture noisily badprog2
display "_rc = " _rc
