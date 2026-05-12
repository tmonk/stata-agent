capture program drop longrun
program define longrun
    forvalues i = 1/100000000 {
        local j = `i' + 1
        if mod(`i', 1000000) == 0 {
            noi di "i=`i'"
        }
    }
end

python:
import sfi, signal, os, time, threading

print(f"PID: {os.getpid()}", flush=True)

break_attempted = False

def interruptor():
    global break_attempted
    time.sleep(5)
    break_attempted = True
    print("\n*** Interruptor: trying to break... ***", flush=True)
    os.kill(os.getpid(), signal.SIGINT)
    time.sleep(1)
    print("Sending SIGTERM...", flush=True)
    os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(1)
    print("Done sending signals", flush=True)

t = threading.Thread(target=interruptor, daemon=True)
t.start()

print("Running longrun...", flush=True)
try:
    sfi.SFIToolkit.stata("longrun")
    print(f"Stata command completed. Break attempted: {break_attempted}", flush=True)
except KeyboardInterrupt:
    print("KeyboardInterrupt caught!", flush=True)
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}", flush=True)

print("Done", flush=True)
end
