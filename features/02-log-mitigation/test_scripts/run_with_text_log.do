// Wrapper to run with text log
set more off
log using "large_log_text.txt", text replace

do generate_very_large_log.do

log close
