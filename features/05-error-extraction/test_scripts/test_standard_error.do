// Test 1: Standard error - variable not found
clear
sysuse auto, clear
regress y z_nonexistent
display "_rc after standard error = " _rc
