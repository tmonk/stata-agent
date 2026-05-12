// Test break error - we can't easily test Ctrl+Break, but test set break
set break
forvalues i = 1/1000000 {
    quietly gen x`i' = 1
}
