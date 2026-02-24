import os
import time
import hmac
import base64
import hashlib
import requests
import json

import threading
import time

# ===== TRADING SETTINGS =====

LEVERAGE = 5

STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_PERCENT = 4.0
TRAILING_STOP_PERCENT = 1.5

CAPITAL_PERCENT_PER_TRADE = 0.10

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

        if data.get("code") == "00000":
            usdt_equity = float(data["data"][0]["usdtEquity"])
            return usdt_equity
        else:
            return 0

    except Exception as e:
        print("Balance error:", str(e))
        return 0

    except Exception as e:
        print("BITGET ERROR:", str(e))
        return 0

def get_current_price(symbol):

    try:

        url = f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={symbol}&productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        if data.get("code") == "00000":
            return float(data["data"][0]["lastPr"])

        return None

    except Exception as e:

        print("Price error:", str(e))
        return None


# API stato bot
@app.route("/status")
def status():
    return jsonify({
        "status": "online" if bot_running else "offline",
        "balance": get_real_balance(),
        "profit_today": 0,
        "profit_total": 0
    })

@app.route("/trades")
def get_trades():

    try:

        url = BASE_URL + "/api/v2/mix/position/all-position"

        timestamp = str(int(time.time() * 1000))

        params = "productType=USDT-FUTURES"

        sign = generate_signature(timestamp, "GET", "/api/v2/mix/position/all-position", params)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }

        response = requests.get(url + "?" + params, headers=headers)

        data = response.json()

        trades = []

        if "data" in data:

            for pos in data["data"]:

                size = float(pos["total"])

                if size > 0:

                    entry = float(pos["openPriceAvg"])

                    mark = float(pos["markPrice"])

                    pnl = (mark - entry) * size

                    trades.append({
                        "symbol": pos["symbol"],
                        "side": pos["holdSide"],
                        "entry": entry,
                        "size": size,
                        "pnl": pnl
                    })

        return jsonify(trades)

    except Exception as e:

        print("Trade fetch error:", e)

        return jsonify([])


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
    print("SCANNER LOOP STARTED")
    global monitored_pairs, scanner_active

    scanner_active = True

    while True:
        try:
            print("Fetching pairs...")
            monitored_pairs = get_usdt_pairs()
            print("Pairs found:", monitored_pairs)

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
    print("STARTING SCANNER THREAD...")
    thread = threading.Thread(target=market_scanner_loop)
    thread.daemon = True
    thread.start()
    print("SCANNER THREAD STARTED SUCCESSFULLY")
    return thread
    
    start_scanner()

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

def open_position(symbol, side, size, leverage):

    try:

        url = BASE_URL + "/api/v2/mix/order/place-order"

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

        sign = generate_signature(
            timestamp,
            "POST",
            "/api/v2/mix/order/place-order",
            body_json
        )

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }

        print("SENDING REAL ORDER:", body)

        response = requests.post(
            url,
            headers=headers,
            data=body_json
        )

        print("BITGET ORDER RESPONSE:", response.json())

    except Exception as e:
        print("Order error:", e)

print("BOOTING PERFECTBOT...")
start_scanner()
print("SCANNER THREAD STARTED")


flask_thread = threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=10000)
)

flask_thread.daemon = True
flask_thread.start()

while True:
    time.sleep(60)

@app.route("/trades")
def get_trades():

    try:

        url = "https://api.bitget.com/api/v2/mix/position/all-position"

        timestamp = str(int(time.time() * 1000))

        params = "productType=USDT-FUTURES"

        sign = generate_signature(timestamp, "GET", "/api/v2/mix/position/all-position", params)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }

        response = requests.get(url + "?" + params, headers=headers)

        data = response.json()

        trades = []

        if "data" in data and data["data"]:

            for pos in data["data"]:

                if float(pos["total"]) > 0:

                    trades.append({
                        "symbol": pos["symbol"],
                        "side": pos["holdSide"],
                        "entry": pos["openPriceAvg"],
                        "size": pos["total"],
                        "pnl": pos["unrealizedPL"]
                    })

        return jsonify(trades)

    except Exception as e:

        print("Trades error:", e)

        return jsonify([])

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

        print("Market scan error:", e)
        return []


def scan_market():

    symbols = get_market_symbols()
    price = get_price(symbol)

if price is None:
    continue

side = "buy"  # per ora test LONG

balance = get_real_balance()

capital_percent = 10
leverage = 5
tp_percent = 4
sl_percent = 2
trailing_percent = 1

amount_usdt = balance * (capital_percent / 100)

position_size = (amount_usdt * leverage) / price

tp_price = price * (1 + tp_percent / 100)
sl_price = price * (1 - sl_percent / 100)
trailing_price = price * (1 - trailing_percent / 100)

print("Side:", side.upper())
print("Entry:", price)
print("TP:", tp_price)
print("SL:", sl_price)
print("Trailing:", trailing_price)
print("Amount USDT:", amount_usdt)
print("Leverage:", leverage)

open_position(
    symbol=symbol,
    side=side,
    size=round(position_size, 3),
    leverage=leverage
)

break

def start_scanner():

    while True:

        if bot_running:

            scan_market()

        time.sleep(30)


scanner_thread = threading.Thread(target=start_scanner)
scanner_thread.daemon = True
scanner_thread.start()

