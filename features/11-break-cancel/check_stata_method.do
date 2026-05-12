python:
import sfi
import inspect
print("SFIToolkit.stata signature:", inspect.signature(sfi.SFIToolkit.stata))
print("SFIToolkit.stata doc:")
print(sfi.SFIToolkit.stata.__doc__)
end
