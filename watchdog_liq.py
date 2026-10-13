"""Arranca recorder_liq.py si no esta corriendo (via PID). Para tarea cada 5 min."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(HERE, "recorder", "liq.pid")


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                         capture_output=True, text=True).stdout.lower()
    return "python" in out


if os.path.exists(PID_FILE):
    try:
        if alive(int(open(PID_FILE).read().strip())):
            sys.exit(0)
    except Exception:
        pass

pyw = sys.executable.replace("python.exe", "pythonw.exe")
if not os.path.exists(pyw):
    pyw = sys.executable
subprocess.Popen([pyw, os.path.join(HERE, "recorder_liq.py")],
                 creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP
print("recorder_liq lanzado")
