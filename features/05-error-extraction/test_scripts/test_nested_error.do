// Test nested program errors
capture program drop outer
capture program drop inner
program define inner
    error 198
end
program define outer
    inner
end
outer
display "_rc after nested = " _rc
