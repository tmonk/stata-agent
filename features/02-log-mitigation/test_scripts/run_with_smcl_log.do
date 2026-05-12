// Wrapper to run with SMCL log
set more off
log using "large_log_smcl_proper.smcl", smcl replace

do generate_very_large_log.do

log close
