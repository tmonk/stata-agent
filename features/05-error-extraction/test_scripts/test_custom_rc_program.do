// Test program that displays as error but does NOT call error command
capture program drop warnprog
program define warnprog
    display as error "This is a warning, not a fatal error"
end
warnprog
display "_rc after warning program = " _rc

capture noisily warnprog
display "_rc after capture noisily warning = " _rc
