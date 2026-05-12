python:
import signal, os, time, threading

caught = []

def handler(signum, frame):
    caught.append(signum)
    print(f"Python caught SIGINT (signal {signum})", flush=True)

# Set up signal handler
signal.signal(signal.SIGINT, handler)

print(f"Python PID: {os.getpid()}", flush=True)
print(f"Parent PID: {os.getppid()}", flush=True)

# Send self SIGINT from timer
def self_sig():
    time.sleep(1)
    print("Sending SIGINT to self...", flush=True)
    os.kill(os.getpid(), signal.SIGINT)

t = threading.Thread(target=self_sig, daemon=True)
t.start()

# Block for a bit
for i in range(10):
    time.sleep(0.3)
    if caught:
        print(f"Break detected! Exiting at iteration {i}", flush=True)
        break
else:
    print("No break detected", flush=True)

print(f"Caught signals: {caught}", flush=True)
end
