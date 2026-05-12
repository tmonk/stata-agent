// Test SMCL log format with errors
clear
log using "test_smcl_mode.smcl", replace smcl
sysuse auto, clear
regress y z_nonexistent
mata: x = y + z
assert 1==0
display as error "custom msg"
capture program drop badprog3
program define badprog3
    error 111
end
badprog3
log close
