// Test explicit text log format with errors
clear
log using "test_text_log_explicit.log", replace text
sysuse auto, clear
regress y z_nonexistent
mata: x = y + z
assert 1==0
display as error "custom msg"
capture program drop badprog5
program define badprog5
    error 111
end
badprog5
log close
