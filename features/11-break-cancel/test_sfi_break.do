clear all
set obs 100
gen x = _n

python:
import sfi
print("sfi version:", sfi.__version__)
print("sfi.breakIn exists:", hasattr(sfi, 'breakIn'))
print("sfi.BreakError exists:", hasattr(sfi, 'BreakError'))
print("sfi.SFIToolkit exists:", hasattr(sfi, 'SFIToolkit'))

members = [m for m in dir(sfi) if not m.startswith('_')]
print("All sfi members:", sorted(members))

# Check for break function
break_fn = getattr(sfi, "breakIn", None)
if break_fn is None:
    break_fn = getattr(sfi, "break_in", None)
print("break_fn found:", break_fn is not None)
if break_fn is not None:
    print("break_fn callable:", callable(break_fn))

# Check for BreakError
print("BreakError:", sfi.BreakError)

# Check for SFIToolkit.pollnow/pollstd
toolkit = getattr(sfi, "SFIToolkit", None)
if toolkit:
    print("SFIToolkit.pollnow exists:", hasattr(toolkit, "pollnow"))
    print("SFIToolkit.pollstd exists:", hasattr(toolkit, "pollstd"))
end
