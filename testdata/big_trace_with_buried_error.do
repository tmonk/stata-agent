*===============================================================================
*  BURIED-ERROR DO-FILE
*  Demonstrates: set trace on + capture noisily + many post-error commands
*  =  the real error is NOT at the bottom of the log.
*
*  Run:  /Applications/StataNow/StataSE.app/Contents/MacOS/stata-se -b do big_trace_with_buried_error.do
*===============================================================================

clear all
set more off
set trace on

display "=== PREAMBLE ==="
forvalues i = 1/10 {
    quietly generate double g`i' = runiform()
    quietly summarize g`i'
    display "preamble `i'"
}
display "=== PREAMBLE END ==="


* ------------------------------------------------------------------
*  Program: error in iteration 2, lots of post-error output
* ------------------------------------------------------------------

capture program drop demo
program define demo
    version 18
    args n

    display _newline ">>> ITERATION `n' <<<"

    * Generate data
    quietly drop _all
    set obs 30
    generate double y = rnormal()
    generate double x = y * 0.7 + rnormal()
    summarize y x
    quietly regress y x

    * ===== THE BURIED ERROR (only in iteration 2) =====
    if `n' == 2 {
        display as error ">>> PRODUCING BURIED ERROR <<<"
        capture noisily confirm variable __nonexist_xyz__
        if _rc != 0 {
            display as error "Caught rc=`_rc', continuing..."
        }
    }

    * Post-error work (more trace = pushes error upward)
    forvalues j = 1/8 {
        quietly generate double r_`n'_`j' = runiform()
        quietly summarize r_`n'_`j'
        display "  post-error var `j' done"
    }
    quietly regress y x
    predict double yh`n'
    summarize yh`n'
    display "Iteration `n' complete"
end

* ------------------------------------------------------------------
*  Run 5 iterations
* ------------------------------------------------------------------

display _newline "=== RUNNING DEMO ==="
forvalues n = 1/5 {
    demo `n'
}

* ------------------------------------------------------------------
*  Postamble — push error further from the bottom
* ------------------------------------------------------------------

display _newline "=== POSTAMBLE ==="
forvalues b = 1/20 {
    quietly generate double p`b' = runiform()
    quietly summarize p`b'
    display "postamble `b': mean=" %7.4f r(mean)
}
display ""
display "=== FINISHED ==="
display "The error '__nonexist_xyz__ not found' is above this line."
