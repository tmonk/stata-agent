python:
import sfi, signal, os, time, threading, sys

print(f"PID: {os.getpid()}", flush=True)

# This will run a long Stata command via the sfi API
# We'll try to interrupt it from another thread

# Flag to check
break_attempted = False

def interruptor():
    """Thread that tries to interrupt the main thread after 3 seconds."""
    global break_attempted
    time.sleep(3)
    break_attempted = True
    print("\n*** Interruptor: trying to break... ***", flush=True)
    
    # Option 1: Send SIGINT to our own process
    print("Sending SIGINT...", flush=True)
    os.kill(os.getpid(), signal.SIGINT)
    time.sleep(1)
    
    # Option 2: Try thread.interrupt_main
    print("Calling interrupt_main...", flush=True)
    threading.interrupt_main()
    time.sleep(1)
    
    # Option 3: Use signal to raise
    print("Signals sent, waiting...", flush=True)

t = threading.Thread(target=interruptor, daemon=True)
t.start()

print("Running long Stata command via SFIToolkit.stata()...", flush=True)
try:
    # This should be long-running
    result = sfi.SFIToolkit.stata("""
        forvalues i = 1/10000000 {
            local j = `i' + 1
        }
    """)
    print(f"Stata command completed normally. Break attempted: {break_attempted}", flush=True)
except KeyboardInterrupt:
    print("KeyboardInterrupt caught!", flush=True)
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}", flush=True)

print("Done", flush=True)
end
