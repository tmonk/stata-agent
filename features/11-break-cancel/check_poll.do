python:
import sfi
toolkit = sfi.SFIToolkit
# Check for poll-related methods
for attr in ['pollnow', 'pollstd', 'poll', 'checkBreak', 'processEvents']:
    obj = getattr(toolkit, attr, None)
    if obj:
        print(f"SFIToolkit.{attr} EXISTS: {obj}")
        if callable(obj):
            import inspect
            try:
                print(f"  signature: {inspect.signature(obj)}")
            except:
                print(f"  callable, no sig")
    else:
        print(f"SFIToolkit.{attr} NOT found")

# Also check the Data class
print("\n--- Checking sfi.Data ---")
for attr in dir(sfi.Data):
    if 'break' in attr.lower() or 'interrupt' in attr.lower():
        print(f"  Data.{attr}")

# Check Frame
print("\n--- Checking sfi.Frame ---")
for attr in dir(sfi.Frame):
    if 'break' in attr.lower() or 'interrupt' in attr.lower():
        print(f"  Frame.{attr}")
end
