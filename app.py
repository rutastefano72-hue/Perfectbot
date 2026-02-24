import os
import time
import hmac
import base64
import hashlib
import requests
import json
import threading

import pandas as pd
import numpy as np

from flask import Flask, jsonify, send_from_directory

# =========================
# CONFIG
# =========================

BASE_URL = "https://api.bitget.com"

API_KEY = os.environ.get("BITGET_API_KEY")
API_SECRET = os.environ.get("BITGET_API_SECRET")
PASSPHRASE = os.environ.get("BITGET_API_PASSPHRASE")

LEVERAGE = 5
CAPITAL_PERCENT_PER_TRADE = 0.10
STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_PERCENT = 4.0
TRAILING_STOP_PERCENT = 1.5

# =========================
# APP
# =========================

app = Flask(__name__)

# Persistente
bot_running = {"state": False}

# =========================
# DASHBOARD
# =========================

@app.route("/")
def dashboard():
    return send_from_directory(".", "dashboard.html")

# =========================
# SIGNATURE
# =========================

def generate_signature(timestamp, method, request_path, body=""):

    message = str(timestamp) + method + request_path + body

    mac = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    )

    return base64.b64encode(mac.digest()).decode()

# =========================
# BALANCE
# =========================

def get_real_balance():

    try:

        timestamp = str(int(time.time() * 1000))

        request_path = "/api/v2/mix/account/accounts?productType=USDT-FUTURES"

        signature = generate_signature(
            timestamp,
            "GET",
            request_path
        )

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }

        url = BASE_URL + request_path

        response = requests.get(url, headers=headers)

        data = response.json()

        if data.get("code") == "00000":

            balance = float(data["data"][0]["usdtEquity"])

            return balance

        return 0

    except Exception as e:

        print("Balance error:", e)

        return 0

# =========================
# PRICE
# =========================

def get_current_price(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/ticker?symbol={symbol}&productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        if data.get("code") == "00000":

            return float(data["data"][0]["lastPr"])

        return None

    except Exception as e:

        print("Price error:", e)

        return None

# =========================
# MARKET SYMBOLS
# =========================

def get_market_symbols():

    try:

        url = BASE_URL + "/api/v2/mix/market/contracts?productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        symbols = []

        if "data" in data:

            for item in data["data"]:

                symbol = item["symbol"]

                if symbol.endswith("USDT"):

                    symbols.append(symbol)

        return symbols

    except Exception as e:

        print("Symbols error:", e)

        return []

# =========================
# OPEN POSITION
# =========================

def open_position(symbol, side, size, leverage):

    try:

        request_path = "/api/v2/mix/order/place-order"

        timestamp = str(int(time.time() * 1000))

        body = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "size": str(size),
            "side": side,
            "orderType": "market",
            "force": "gtc"
        }

        body_json = json.dumps(body)

        signature = generate_signature(
            timestamp,
            "POST",
            request_path,
            body_json
        )

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }

        url = BASE_URL + request_path

        print("OPENING POSITION:", symbol, side, size)

        response = requests.post(
            url,
            headers=headers,
            data=body_json
        )

        print("ORDER RESPONSE:", response.json())

    except Exception as e:

        print("Order error:", e)

# =========================
# SIGNAL
# =========================

def get_signal(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/candles?symbol={symbol}&granularity=5m&limit=200&productType=USDT-FUTURES"

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
            return "buy"

        if price < ema50 and ema50 < ema200 and rsi > 30:
            return "sell"

        return None

    except Exception as e:

        print("Signal error:", e)
        return None

# =========================
# SCAN MARKET
# =========================

def scan_market():

    symbols = get_market_symbols()

    print("Scanning symbols:", len(symbols))

    for symbol in symbols[:5]:

        signal = get_signal(symbol)

        if signal is None:
            continue

        price = get_current_price(symbol)

        if price is None:
            continue

        balance = get_real_balance()

        amount_usdt = balance * CAPITAL_PERCENT_PER_TRADE

        position_size = (amount_usdt * LEVERAGE) / price

        side = signal

        print("Opening:", symbol, side, position_size)

        open_position(
            symbol,
            side,
            round(position_size, 3),
            LEVERAGE
        )

        break

# =========================
# SCANNER LOOP
# =========================

def scanner_loop():

    print("SCANNER STARTED")

    while True:

        try:

            print("BOT STATE:", bot_running["state"])

            if bot_running["state"]:

                print("SCANNING MARKET NOW...")
                scan_market()

            else:

                print("BOT OFF")

        except Exception as e:

            print("SCANNER ERROR:", e)

        time.sleep(10)

# =========================
# API CONTROL
# =========================

@app.route("/start", methods=["POST"])
def start_bot():

    bot_running["state"] = True

    print("BOT STARTED")

    return jsonify({"success": True})

@app.route("/stop", methods=["POST"])
def stop_bot():

    bot_running["state"] = False

    print("BOT STOPPED")

    return jsonify({"success": True})

@app.route("/status")
def status():

    return jsonify({
        "status": "online" if bot_running["state"] else "offline",
        "balance": get_real_balance()
    })

# =========================
# START THREAD
# =========================

thread = threading.Thread(target=scanner_loop)
thread.daemon = True
thread.start()

# =========================
# RUN
# =========================

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=10000)
