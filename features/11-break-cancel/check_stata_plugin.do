python:
import sys, inspect

# Find and inspect the stata_plugin module (built-in C module)
if 'stata_plugin' in sys.modules:
    sp = sys.modules['stata_plugin']
    print(f"stata_plugin type: {type(sp)}")
    sp_attrs = [a for a in dir(sp) if not a.startswith('_')]
    print(f"stata_plugin attributes ({len(sp_attrs)}):")
    for a in sorted(sp_attrs):
        obj = getattr(sp, a)
        try:
            if callable(obj):
                try:
                    sig = str(inspect.signature(obj))
                    print(f"  {a}{sig}")
                except:
                    print(f"  {a}()")
            else:
                print(f"  {a} = {obj}")
        except:
            print(f"  {a} = (error)")
else:
    print("stata_plugin not in sys.modules")

print("\nDone", flush=True)
end
