import os
import time
import hmac
import base64
import hashlib
import requests

from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

# Stato bot
bot_running = False

# Dashboard
@app.route('/')
def serve_dashboard():
    return send_from_directory('.', 'dashboard.html')


# Funzione per leggere il saldo reale da Bitget Futures
def get_real_balance():
    try:
        api_key = os.environ.get("BITGET_API_KEY")
        secret = os.environ.get("BITGET_API_SECRET")
        passphrase = os.environ.get("BITGET_API_PASSPHRASE")

        url = "https://api.bitget.com/api/v2/mix/account/accounts?productType=USDT-FUTURES"

        timestamp = str(int(time.time() * 1000))
        method = "GET"
        request_path = "/api/v2/mix/account/accounts?productType=USDT-FUTURES"
        body = ""

        message = timestamp + method + request_path + body

        signature = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode()

        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers)
        data = response.json()
        print("BITGET RAW RESPONSE:", data)

        if "data" in data and len(data["data"]) > 0:
            return float(data["data"][0]["usdtEquity"])
        else:
            return 0

    except Exception as e:
        print("BITGET ERROR:", str(e))
        return 0


# API stato bot
@app.route("/status")
def status():
    return jsonify({
        "status": "online" if bot_running else "offline",
        "balance": get_real_balance(),
        "profit_today": 0,
        "profit_total": 0
    })


# Avvio bot
@app.route("/start", methods=["POST"])
def start_bot():
    global bot_running
    bot_running = True
    return jsonify({"success": True})


# Stop bot
@app.route("/stop", methods=["POST"])
def stop_bot():
    global bot_running
    bot_running = False
    return jsonify({"success": True})


# Avvio server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    # === MARKET SCANNER STANDARD MODE ===

import threading
import time
import requests

scanner_active = False
monitored_pairs = []

def get_usdt_pairs():
    try:
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        response = requests.get(url)
        data = response.json()

        pairs = []
        for item in data.get("data", []):
            symbol = item.get("symbol", "")
            volume = float(item.get("quoteVolume", 0))

            if symbol.endswith("USDT") and volume > 1000000:
                pairs.append(symbol)

        pairs.sort()
        return pairs[:25]

    except Exception as e:
        print("SCANNER ERROR:", str(e))
        return []

def market_scanner_loop():
    global monitored_pairs, scanner_active

    scanner_active = True

    while True:
        try:
            monitored_pairs = get_usdt_pairs()
            print("Scanner active. Pairs:", monitored_pairs)
            time.sleep(30)

        except Exception as e:
            print("Scanner loop error:", str(e))
            time.sleep(30)

def start_scanner():
    thread = threading.Thread(target=market_scanner_loop)
    thread.daemon = True
    thread.start()

# avvia scanner automaticamente
start_scanner()
