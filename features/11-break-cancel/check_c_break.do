python:
import sfi
import types

# Check ALL modules available in Stata's Python for break-related functions
import sys
print("Checking all modules for 'break':")
break_related = []
for mod_name, mod in sys.modules.items():
    if mod is None:
        continue
    try:
        for attr in dir(mod):
            if 'break' in attr.lower() and not attr.startswith('_'):
                break_related.append((mod_name, attr))
    except:
        pass

for mod, attr in sorted(break_related):
    print(f"  {mod}.{attr}")

# Also check if there's a way to set the break flag via the C extension
# Look at the _stp module if it's available
print("\n--- Checking for _stp in sys.modules ---")
for name in sys.modules:
    if '_stp' in name or 'st' in name.lower():
        print(f"  Found: {name}")

# Try to find any C extension with st_break
print("\n--- Trying to find break in native modules ---")
import ctypes
try:
    # Look for the Stata library
    libst = ctypes.CDLL(None)  # RTLD_GLOBAL
    print("Global symbols loaded")
except:
    print("Can't load global symbols")

# Try to use SFIToolkit to break by raising BreakError
# This might trigger Stata's break mechanism
print("\n--- Testing SFIToolkit.error(1) ---")
try:
    sfi.SFIToolkit.error(1)
    print("error(1) returned normally")
except Exception as e:
    print(f"error(1) raised: {e}")

print("\nDone", flush=True)
end
