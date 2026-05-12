capture program drop longrun
program define longrun
    forvalues i = 1/100000000 {
        local j = `i' + 1
        if mod(`i', 1000000) == 0 {
            noi di "i=`i'"
        }
    }
end

python:
import sfi, os
print(f"Starting longrun from Python... PID={os.getpid()}", flush=True)
try:
    sfi.SFIToolkit.stata("longrun")
    print("longrun completed normally", flush=True)
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}", flush=True)
print("Python done", flush=True)
end
