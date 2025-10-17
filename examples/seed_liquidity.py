import json, uuid
from websocket import create_connection

URL = "ws://localhost:8000/ws"
SYMBOL = "BTC-USDT"
N_ORDERS = 200          # number of resting sell orders
PRICE = 50000
QTY = 0.05              # each 0.05 => total 10.0 liquidity

client_id = f"seed-{uuid.uuid4().hex[:6]}"
ws = create_connection(f"{URL}/{client_id}")
ws.recv()  # connection message

# (optional) subscribe to keep flow similar
ws.send(json.dumps({"type":"subscribe","symbols":[SYMBOL],"trades":True,"market_data":True}))
try:
    ws.recv(); ws.recv()
except Exception:
    pass

for _ in range(N_ORDERS):
    ws.send(json.dumps({
        "type":"order",
        "symbol":SYMBOL,
        "side":"sell",
        "order_type":"limit",
        "price": PRICE,
        "quantity": QTY
    }))
    # read order_response (ignore content)
    while True:
        resp = json.loads(ws.recv())
        if resp.get("type") == "order_response":
            break

print(f"Seeded {N_ORDERS} sell limit orders at {PRICE}.")
ws.close()
