clear all
set obs 1000
gen x = runiform()

python:
import sfi
import time

print("Testing SFIToolkit.pollnow...")
toolkit = sfi.SFIToolkit

# pollnow should raise BreakError if a break is pending
print("Calling pollnow...")
try:
    toolkit.pollnow()
    print("pollnow returned normally (no break pending)")
except sfi.BreakError as e:
    print("BreakError caught from pollnow:", e)
except Exception as e:
    print("Other error from pollnow:", type(e).__name__, e)
end
