import os
import time
import hmac
import base64
import hashlib
import requests
import json
import threading
import traceback

import pandas as pd
import numpy as np

from flask import Flask, jsonify, send_from_directory, request

# =========================
# CONFIG
# =========================

BASE_URL = "https://api.bitget.com"

API_KEY = os.environ.get("BITGET_API_KEY")
API_SECRET = os.environ.get("BITGET_API_SECRET")
PASSPHRASE = os.environ.get("BITGET_API_PASSPHRASE")

LEVERAGE = 5
capital_percent = {"value": 0.05}
last_trade_time = None
print("INITIAL CAPITAL PERCENT:", capital_percent["value"])
STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_PERCENT = 4.0
TRAILING_STOP_PERCENT = 1.5

# =========================
# APP
# =========================

app = Flask(__name__)

# Persistente
bot_running = {"state": True}
active_trades = {"count": 0}
MAX_ACTIVE_TRADES = 5

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

def get_open_positions_count():

    try:

        timestamp = str(int(time.time() * 1000))

        request_path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES"

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

        if data.get("code") != "00000":
            return 0

        positions = data.get("data", [])

        count = 0

        for pos in positions:

            size = float(pos.get("total", 0))

            if size > 0:
                count += 1

        return count

    except Exception as e:

        print("Positions count error:", e)

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

        print("REQUESTING SYMBOLS FROM BITGET...")

        url = BASE_URL + "/api/v2/mix/market/contracts?productType=USDT-FUTURES"

        response = requests.get(url)

        print("RESPONSE STATUS:", response.status_code)

        data = response.json()

        symbols = []

        if "data" in data:

            for item in data["data"]:

                symbol = item.get("symbol")

                if symbol and symbol.endswith("USDT"):

                    symbols.append(symbol)

        print("SYMBOLS FOUND:", len(symbols))

        return symbols

    except Exception as e:

        print("Symbols error:", e)

        return []


def get_symbol_precision(symbol):

    try:

        url = BASE_URL + "/api/v2/mix/market/contracts?productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        if "data" in data:

            for item in data["data"]:

                if item.get("symbol") == symbol:

                    price_precision = int(item.get("pricePlace", 2))
                    size_precision = int(item.get("volumePlace", 3))

                    print("PRECISION:", symbol, price_precision, size_precision)

                    return price_precision, size_precision

        return 2, 3

    except Exception as e:

        print("Precision error:", e)

        return 2, 3

# =========================
# OPEN POSITION
# =========================

def open_position(symbol, side, size, leverage):

    try:

        price = get_current_price(symbol)

        if price is None:
            print("Cannot get price")
            return

        price_precision, size_precision = get_symbol_precision(symbol)

        size_format = "{:." + str(size_precision) + "f}"
        price_format = "{:." + str(price_precision) + "f}"

        size = float(size_format.format(size))

        if side == "buy":
            stop_loss_price = price * (1 - STOP_LOSS_PERCENT / 100)
            take_profit_price = price * (1 + TAKE_PROFIT_PERCENT / 100)
            stop_side = "sell"

        else:
            stop_loss_price = price * (1 + STOP_LOSS_PERCENT / 100)
            take_profit_price = price * (1 - TAKE_PROFIT_PERCENT / 100)
            stop_side = "buy"

        stop_loss_price = float(price_format.format(stop_loss_price))
        take_profit_price = float(price_format.format(take_profit_price))

        print("OPENING POSITION:", symbol, side, size)
        print("SL:", stop_loss_price)
        print("TP:", take_profit_price)

        request_path = "/api/v2/mix/order/place-order"
        timestamp = str(int(time.time() * 1000))

        body = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "size": str(size),
            "side": side,
            "tradeSide": "open",
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

        response = requests.post(url, headers=headers, data=body_json)

        print("POSITION RESPONSE:", response.text)

        response_data = response.json()

        if response_data.get("code") != "00000":
            print("POSITION FAILED")
            return

        order_id = response_data["data"]["orderId"]

        # STOP LOSS
        set_stop_loss(symbol, stop_loss_price, stop_side, size)

        # TAKE PROFIT
        set_take_profit(symbol, take_profit_price, stop_side, size)

        print("TRADE OPENED:", symbol, side)

    except Exception as e:
        print("OPEN POSITION ERROR:", e)
        traceback.print_exc()

def set_stop_loss(symbol, stop_price, side, size):

    try:

        request_path = "/api/v2/mix/order/place-tpsl-order"
        timestamp = str(int(time.time() * 1000))

        body = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginCoin": "USDT",
            "planType": "loss_plan",
            "triggerPrice": str(stop_price),
            "executePrice": str(stop_price),
            "holdSide": side,
            "size": str(size)
            "triggerType": "mark_price"
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

        response = requests.post(url, headers=headers, data=body_json)

        print("STOP LOSS SET:", response.text)

    except Exception as e:
        print("STOP LOSS ERROR:", e)

def set_take_profit(symbol, tp_price, side, size):

    try:

        request_path = "/api/v2/mix/order/place-tpsl-order"
        timestamp = str(int(time.time() * 1000))

        body = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginCoin": "USDT",
            "planType": "profit_plan",
            "triggerPrice": str(tp_price),
            "executePrice": str(tp_price),
            "holdSide": side,
            "size": str(size)
            "triggerType": "mark_price"
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

        response = requests.post(url, headers=headers, data=body_json)

        print("TAKE PROFIT SET:", response.text)

    except Exception as e:
        print("TAKE PROFIT ERROR:", e)

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

    global last_trade_time

    try:

        symbols = get_market_symbols()

        print("Scanning symbols:", len(symbols), flush=True)

        trade_opened = False

        # protezione: attendi almeno 60 secondi tra un trade e l'altro
        current_time = time.time()

        if last_trade_time is not None:
            elapsed = current_time - last_trade_time
            if elapsed < 60:
                print("Waiting cooldown:", int(60 - elapsed), "seconds remaining", flush=True)
                return

        # ottieni numero posizioni reali aperte
        active_trades_count = get_open_positions_count()

        print("REAL ACTIVE POSITIONS:", active_trades_count, flush=True)

        if active_trades_count >= MAX_ACTIVE_TRADES:
            print("MAX ACTIVE TRADES REACHED", flush=True)
            return


        for symbol in symbols:

            if trade_opened:
                print("Trade already opened this scan", flush=True)
                return

            signal = get_signal(symbol)

            if signal is None:
                continue

            print("SIGNAL FOUND:", symbol, signal, flush=True)

            price = get_current_price(symbol)

            if price is None:
                continue

            balance = get_real_balance()

            if balance is None or balance <= 0:
                print("Invalid balance:", balance, flush=True)
                return

            capital_to_use = balance * capital_percent["value"]

            position_size = (capital_to_use * LEVERAGE) / price

            min_size = 0.01

            if position_size < min_size:
                print("Size too small, skipping:", symbol, flush=True)
                continue

            side = signal

            print("======= POSITION SIZE CALCULATION =======", flush=True)
            print("Symbol:", symbol, flush=True)
            print("Balance:", balance, flush=True)
            print("Capital %:", capital_percent["value"], flush=True)
            print("Capital used:", capital_to_use, flush=True)
            print("Leverage:", LEVERAGE, flush=True)
            print("Price:", price, flush=True)
            print("Position size:", position_size, flush=True)
            print("Side:", side, flush=True)
            print("========================================", flush=True)

            open_position(
                symbol,
                side,
                round(position_size, 3),
                LEVERAGE
            )

            print("TRADE OPENED:", symbol, side, flush=True)

            trade_opened = True

            last_trade_time = time.time()

            return

        print("No valid signals found", flush=True)

    except Exception as e:

        print("SCANNER ERROR:", str(e), flush=True)
        traceback.print_exc()

# =========================
# SCANNER LOOP
# =========================

def scanner_loop():

    print("SCANNER STARTED", flush=True)

    while True:

        try:

            print("BOT STATE:", bot_running["state"], flush=True)

            if bot_running["state"]:

                print("SCANNING MARKET NOW...", flush=True)

                scan_market()

                print("SCAN COMPLETE — waiting 60 seconds", flush=True)

                time.sleep(60)

            else:

                print("BOT OFF", flush=True)

                time.sleep(5)

        except Exception as e:

            import traceback

            print("SCANNER ERROR:", str(e), flush=True)

            traceback.print_exc()

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

    global capital_percent

    return jsonify({
        "status": "online" if bot_running["state"] else "offline",
        "balance": get_real_balance(),
        "capital_percent": capital_percent["value"],
        "leverage": LEVERAGE,
        "take_profit": TAKE_PROFIT_PERCENT,
        "stop_loss": STOP_LOSS_PERCENT
    })


@app.route("/set_capital_percent", methods=["POST"])
def set_capital_percent():

    global capital_percent

    try:
        data = request.json

        percent = float(data.get("percent", capital_percent["value"]))

        if percent <= 0 or percent > 1:
            return jsonify({"success": False})

        capital_percent["value"] = percent

        print("NEW CAPITAL PERCENT SAVED:", capital_percent["value"], flush=True)

        return jsonify({
            "success": True,
            "capital_percent": capital_percent["value"]
        })

    except Exception as e:

        print("ERROR SET CAPITAL:", e, flush=True)

        return jsonify({"success": False})

@app.route("/set_leverage", methods=["POST"])
def set_leverage():
    try:
        data = request.json
        value = float(data.get("value"))
        global LEVERAGE
        LEVERAGE = value
        print("NEW LEVERAGE:", value)
        return jsonify({"success": True})
    except Exception as e:
        print("ERROR:", e)
        return jsonify({"success": False})


@app.route("/set_stop_loss", methods=["POST"])
def set_stop_loss_percent():
    try:
        data = request.json
        value = float(data.get("value"))
        global STOP_LOSS_PERCENT
        STOP_LOSS_PERCENT = value
        print("NEW STOP LOSS:", value)
        return jsonify({"success": True})
    except Exception as e:
        print("ERROR:", e)
        return jsonify({"success": False})


@app.route("/set_take_profit", methods=["POST"])
def set_take_profit_percent():
    try:
        data = request.json
        value = float(data.get("value"))
        global TAKE_PROFIT_PERCENT
        TAKE_PROFIT_PERCENT = value
        print("NEW TAKE PROFIT:", value)
        return jsonify({"success": True})
    except Exception as e:
        print("ERROR:", e)
        return jsonify({"success": False})


# ============================
# HOME ROUTE
# ============================


# ============================
# START THREAD
# ============================

thread = threading.Thread(target=scanner_loop)
thread.daemon = True
thread.start()


# ============================
# RUN
# ============================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    print("STARTING PERFECTBOT SERVER ON PORT:", port)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
