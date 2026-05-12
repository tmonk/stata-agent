python:
import sfi
import inspect

print("=== SFI SFIToolkit methods ===")
toolkit = sfi.SFIToolkit
for name in dir(toolkit):
    if not name.startswith('_'):
        obj = getattr(toolkit, name)
        if callable(obj):
            try:
                sig = str(inspect.signature(obj))
            except:
                sig = "(no signature)"
            print(f"  {name}{sig}")
        else:
            print(f"  {name} = {obj}")

print("\n=== sfi.BreakError ===")
print(f"  MRO: {sfi.BreakError.__mro__}")
print(f"  Bases: {sfi.BreakError.__bases__}")

print("\n=== Checking for any break/cancel mechanism ===")
# Check all sfi classes for break-related methods
for name in ['Data', 'Macro', 'Mata', 'Frame', 'SFIToolkit']:
    cls = getattr(sfi, name, None)
    if cls:
        for attr in dir(cls):
            if 'break' in attr.lower() or 'cancel' in attr.lower() or 'interrupt' in attr.lower():
                print(f"  sfi.{name}.{attr}")

print("\n=== Can SFIToolkit set a break? ===")
# Try calling pollstd (which is documented to check for breaks from Stata std engine)
print("Checking pollstd...")
try:
    toolkit.pollstd()
    print("  pollstd returned normally")
except sfi.BreakError as e:
    print(f"  pollstd raised BreakError: {e}")
except Exception as e:
    print(f"  pollstd error: {e}")

print("\n=== Testing SFIToolkit.setBreak() or similar ===")
for possible_name in ['break', 'interrupt', 'cancel', 'signalBreak', 'requestBreak', 
                       'setBreak', 'doBreak', 'breakIn', 'break_in']:
    method = getattr(toolkit, possible_name, None)
    if method:
        print(f"  toolkit.{possible_name} exists: {method}")
    else:
        print(f"  toolkit.{possible_name} NOT found")

# Also check sfi module level
for possible_name in ['breakIn', 'break_in', 'interrupt', 'cancel']:
    obj = getattr(sfi, possible_name, None)
    if obj:
        print(f"  sfi.{possible_name} exists: {obj}")
    else:
        print(f"  sfi.{possible_name} NOT found")
end
