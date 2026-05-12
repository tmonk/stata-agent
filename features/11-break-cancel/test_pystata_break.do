python:
import sfi, signal, os, time, threading

print(f"PID: {os.getpid()}", flush=True)
print(f"Default SIGINT handler: {signal.getsignal(signal.SIGINT)}", flush=True)

# Check if there is any Python API in pystata for running Stata commands
# that supports break/cancel
# Try to find the actual pystata API
try:
    import pystata
    print(f"\npystata available: {pystata.__file__}", flush=True)
    for attr in dir(pystata):
        if not attr.startswith('_'):
            print(f"  pystata.{attr}", flush=True)
except ImportError:
    print("\npystata not available as separate module", flush=True)

# Check if stata module exists
try:
    import stata
    print(f"\nstata module available: {stata.__file__}", flush=True)
    for attr in dir(stata):
        if not attr.startswith('_'):
            obj = getattr(stata, attr)
            print(f"  stata.{attr} = {type(obj).__name__}", flush=True)
            if attr in ('break', 'interrupt', 'cancel'):
                print(f"    --> {obj}", flush=True)
except ImportError:
    print("\nstata module not available", flush=True)

# Check config
try:
    from pystata import config
    print(f"\nconfig available", flush=True)
except ImportError:
    print("\npystata.config not available", flush=True)
    
# Check stata_setup
try:
    import stata_setup
    print(f"\nstata_setup available", flush=True)
except ImportError:
    print("\nstata_setup not available", flush=True)
end
