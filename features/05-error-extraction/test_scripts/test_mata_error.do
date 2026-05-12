// Test 2: Mata error - undefined variables
clear
mata: x = y + z
display "_rc after mata error = " _rc
