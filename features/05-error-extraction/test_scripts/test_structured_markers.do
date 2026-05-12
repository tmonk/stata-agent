// Test structured marker injection
clear
sysuse auto, clear

display "=== Standard error with markers ==="
capture noisily regress y z_nonexistent
if _rc != 0 {
    display as error "[MCP-ERROR] rc=" _rc
    display as error "[MCP-MSG] variable not found"
}

display "=== Mata error with markers ==="
capture noisily mata: x = y + z
if _rc != 0 {
    display as error "[MCP-ERROR] rc=" _rc
    display as error "[MCP-MSG] Mata undefined variable"
}

display "=== Assertion with markers ==="
capture noisily assert 1==0
if _rc != 0 {
    display as error "[MCP-ERROR] rc=" _rc
    display as error "[MCP-MSG] assertion is false"
}

display "=== Program error with markers ==="
capture program drop badprog4
program define badprog4
    error 111
end
capture noisily badprog4
if _rc != 0 {
    display as error "[MCP-ERROR] rc=" _rc
    display as error "[MCP-MSG] program error 111"
}
