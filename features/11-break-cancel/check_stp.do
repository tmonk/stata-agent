python:
# Check what _stp module provides
try:
    import _stp
    print("_stp module found!")
    print(f"_stp location: {_stp.__file__}")
    stp_attrs = [a for a in dir(_stp) if not a.startswith('_')]
    print(f"_stp attributes ({len(stp_attrs)}):")
    for a in sorted(stp_attrs):
        obj = getattr(_stp, a)
        info = ""
        if callable(obj):
            import inspect
            try:
                sig = str(inspect.signature(obj))
                info = sig
            except:
                info = "(callable)"
        print(f"  _stp.{a} {info}")
except ImportError:
    print("_stp not available (C extension)")

# Also check how the current StataClient runs commands
# to understand the execution model better
import sfi
print("\n--- How does pystata run Stata commands? ---")
# The StataClient uses the 'stata' or 'pystata' module for running commands
# Let's see what's available for execution
exec_attrs = [a for a in dir(sfi) if 'run' in a.lower() or 'exec' in a.lower() or 'cmd' in a.lower()]
print(f"Execution-related sfi attributes: {exec_attrs}")

# Check SFIToolkit for any run method
toolkit = sfi.SFIToolkit
tk_attrs = [a for a in dir(toolkit) if not a.startswith('_')]
print(f"\nSFIToolkit methods:")
for a in sorted(tk_attrs):
    obj = getattr(toolkit, a)
    if callable(obj):
        print(f"  SFIToolkit.{a}()")
    else:
        print(f"  SFIToolkit.{a} = {obj}")
end
