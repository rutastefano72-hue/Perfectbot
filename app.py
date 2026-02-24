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

            for symbol in monitored_pairs:
                signal = get_signal(symbol)

                if signal == "LONG":
                    print(f"Opening LONG on {symbol}")
                    open_position(symbol, "buy")

                elif signal == "SHORT":
                    print(f"Opening SHORT on {symbol}")
                    open_position(symbol, "sell")

            time.sleep(30)

        except Exception as e:
            print("Scanner loop error:", str(e))
            time.sleep(30)

def start_scanner():
    thread = threading.Thread(target=market_scanner_loop)
    thread.daemon = True
    thread.start()

import pandas as pd
import numpy as np
import requests

def get_signal(symbol):
    try:
        url = f"https://api.bitget.com/api/v2/mix/market/candles?symbol={symbol}&granularity=5m&limit=200&productType=USDT-FUTURES"
        response = requests.get(url)
        data = response.json()

        if "data" not in data:
            return None

        candles = data["data"]
        closes = np.array([float(c[4]) for c in candles])

        ema50 = pd.Series(closes).ewm(span=50).mean().iloc[-1]
        ema200 = pd.Series(closes).ewm(span=200).mean().iloc[-1]

        delta = np.diff(closes)
        gain = np.maximum(delta, 0)
        loss = -np.minimum(delta, 0)

        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])

        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi = 100 - (100 / (1 + rs))

        price = closes[-1]

        if price > ema50 and ema50 > ema200 and rsi < 70:
            return "LONG"

        if price < ema50 and ema50 < ema200 and rsi > 30:
            return "SHORT"

        return None

    except Exception as e:
        print("Signal error:", e)
        return None

def open_position(symbol, side):
    try:
        # usa la funzione corretta che già hai
        balance = get_real_balance()

        amount_usdt = balance * 0.10

        print(f"REAL ORDER READY: {side.upper()} {symbol} with {amount_usdt} USDT")

        # qui inseriremo tra poco l'ordine reale Bitget

    except Exception as e:
        print("REAL TRADE ERROR:", str(e))

if __name__ == "__main__":
    start_scanner()
    app.run(host="0.0.0.0", port=10000)

