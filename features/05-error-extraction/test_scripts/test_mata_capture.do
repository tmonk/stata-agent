// Test Mata capture specifically
clear
display "=== Mata capture: st_local with undefined y ==="
capture mata: st_local("x", y)
display "_rc after capture mata = " _rc

display "=== Mata capture inside noisily ==="
capture noisily mata: st_local("x", y)
display "_rc after capture noisily mata = " _rc

display "=== Mata capture valid code ==="
capture mata: st_local("x", "hello")
display "_rc after valid mata = " _rc
display "local x = $x"
