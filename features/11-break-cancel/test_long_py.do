python:
import signal, os, time, threading

print(f"Python PID: {os.getpid()}", flush=True)

# Set up SIGINT handler
caught = []
def handler(signum, frame):
    caught.append(signum)
    print(f"\n*** SIGINT CAUGHT in Python! ***", flush=True)
    import sfi
    # Try to trigger a break via SFIToolkit
    try:
        sfi.SFIToolkit.pollnow()
        print("pollnow returned normally", flush=True)
    except sfi.BreakError as e:
        print(f"BreakError triggered: {e}", flush=True)
    except Exception as e:
        print(f"pollnow error: {e}", flush=True)

signal.signal(signal.SIGINT, handler)

# Now run a long Stata operation
print("Running long Stata command from Python...", flush=True)

# This Stata command will be long-running
from sfi import Data, Macro
# Simulate a long Stata operation
# We'll run an infinite loop in Stata via Data APIs
i = 0
try:
    while True:
        i += 1
        # Do some Stata work
        if i % 1000 == 0:
            print(f"  iteration {i}...", flush=True)
            if caught:
                print(f"  Break requested, exiting Python loop", flush=True)
                break
        time.sleep(0.001)
except Exception as e:
    print(f"Exception: {e}", flush=True)

print(f"Python loop ended after {i} iterations. Caught: {caught}", flush=True)
end
