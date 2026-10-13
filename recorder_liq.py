"""
Grabadora continua del stream de LIQUIDACIONES de Binance Futures (todas).
Anade una linea JSON por liquidacion a ./recorder/liq_YYYY-MM-DD.jsonl.
Se reconecta sola. Pensada para arrancarse via watchdog_liq.py.
"""
import json
import os
import time

import websocket

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorder")
os.makedirs(DIR, exist_ok=True)
PID_FILE = os.path.join(DIR, "liq.pid")
open(PID_FILE, "w").write(str(os.getpid()))


def on_message(ws, msg):
    try:
        data = json.loads(msg)
        o = data.get("o", {})
        day = time.strftime("%Y-%m-%d", time.gmtime())
        line = json.dumps({"ts": o.get("T"), "s": o.get("s"), "side": o.get("S"),
                           "q": o.get("q"), "p": o.get("ap"), "status": o.get("X")})
        with open(os.path.join(DIR, f"liq_{day}.jsonl"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


while True:
    try:
        ws = websocket.WebSocketApp(
            "wss://fstream.binance.com/ws/!forceOrder@arr",
            on_message=on_message)
        ws.run_forever(ping_interval=180, ping_timeout=10)
    except Exception:
        pass
    time.sleep(10)  # reconexion
