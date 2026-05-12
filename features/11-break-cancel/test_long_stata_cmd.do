* Test: Long-running Stata command with SIGINT from Python
clear all
set obs 10000
gen x = runiform()
gen y = x + rnormal()
capture program drop myboot
program define myboot, rclass
    reg y x
    return scalar b = _b[x]
end
set seed 12345

python:
import signal, os
print(f"Python PID: {os.getpid()}", flush=True)

# Check current SIGINT handler
old_handler = signal.getsignal(signal.SIGINT)
print(f"SIGINT handler before: {old_handler}", flush=True)
print(f"SIG_IGN: {signal.SIG_IGN}", flush=True)
print(f"SIG_DFL: {signal.SIG_DFL}", flush=True)

# Set up SIGINT handler
caught = []
def handler(signum, frame):
    caught.append(signum)
    print(f"\n*** SIGINT CAUGHT during Stata command! ***", flush=True)

signal.signal(signal.SIGINT, handler)
print(f"SIGINT handler now: {signal.getsignal(signal.SIGINT)}", flush=True)
print("Starting long Stata command (enter Stata mode)...", flush=True)
end

* Now run a long Stata command - the bootstrap
bootstrap b=r(b), reps(5000) seed(12345): myboot

python:
print(f"\nStata command returned to Python. Signals caught: {caught}", flush=True)
if caught:
    print("SIGINT WAS CAUGHT during Stata command!", flush=True)
else:
    print("SIGINT was NOT caught during Stata command", flush=True)
end
