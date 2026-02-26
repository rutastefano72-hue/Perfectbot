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

STOP_LOSS_PERCENT = 2.0
TAKE_PROFIT_PERCENT = 4.0

MAX_ACTIVE_TRADES = 5

print("PerfectBot starting...")

# =========================
# APP
# =========================

app = Flask(__name__)

bot_running = {"state": False}
scanner_thread = None

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
# GET BALANCE
# =========================

def get_real_balance():

    try:

        timestamp = str(int(time.time() * 1000))

        request_path = "/api/v2/mix/account/accounts?productType=USDT-FUTURES"

        signature = generate_signature(timestamp,"GET",request_path)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
        }

        url = BASE_URL + request_path

        response = requests.get(url, headers=headers)

        data = response.json()

        if data.get("code") == "00000":

            return float(data["data"][0]["usdtEquity"])

        return 0

    except Exception as e:

        print("Balance error:", e)

        return 0


# =========================
# GET OPEN POSITIONS
# =========================

def get_open_positions():

    try:

        timestamp = str(int(time.time() * 1000))

        request_path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES"

        signature = generate_signature(timestamp,"GET",request_path)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
        }

        url = BASE_URL + request_path

        response = requests.get(url, headers=headers)

        data = response.json()

        trades = []

        if data.get("code") == "00000":

            for pos in data["data"]:

                size = float(pos.get("total", 0))

                if size > 0:

                    trades.append({

                        "symbol": pos.get("symbol"),
                        "side": pos.get("holdSide"),
                        "entry": pos.get("openPriceAvg"),
                        "pnl": pos.get("unrealizedPL")

                    })

        return trades

    except:

        return []


def get_open_positions_count():

    positions = get_open_positions()

    return len(positions)


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

    except:

        return None


# =========================
# SYMBOL PRECISION
# =========================

def get_symbol_precision(symbol):

    try:

        url = BASE_URL + "/api/v2/mix/market/contracts?productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        for item in data["data"]:

            if item["symbol"] == symbol:

                return int(item["pricePlace"]), int(item["volumePlace"])

        return 2,3

    except:

        return 2,3


# =========================
# OPEN POSITION REAL
# =========================

def open_position(symbol, side, size, leverage):

    # 🔒 BLOCCO DI SICUREZZA ASSOLUTO
    if not bot_running["state"]:
        print("BLOCKED: bot is OFF — position NOT opened", flush=True)
        return

    try:

        price = get_current_price(symbol)

        if price is None:
            return

        price_precision, size_precision = get_symbol_precision(symbol)

        size = round(size, size_precision)

        if side == "buy":

            stop_loss_price = round(price * (1 - STOP_LOSS_PERCENT/100), price_precision)

            take_profit_price = round(price * (1 + TAKE_PROFIT_PERCENT/100), price_precision)

        else:

            stop_loss_price = round(price * (1 + STOP_LOSS_PERCENT/100), price_precision)

            take_profit_price = round(price * (1 - TAKE_PROFIT_PERCENT/100), price_precision)

        request_path="/api/v2/mix/order/place-order"

        timestamp=str(int(time.time()*1000))

        body={

            "symbol":symbol,
            "productType":"USDT-FUTURES",
            "marginMode":"crossed",
            "marginCoin":"USDT",

            "size":str(size),

            "side":side,

            "tradeSide":"open",

            "orderType":"market",

            "presetStopLossPrice":str(stop_loss_price),
            "presetTakeProfitPrice":str(take_profit_price),

            "presetStopLossType":"mark_price",
            "presetTakeProfitType":"mark_price"
        }

        body_json=json.dumps(body)

        signature=generate_signature(timestamp,"POST",request_path,body_json)

        headers={

            "ACCESS-KEY":API_KEY,
            "ACCESS-SIGN":signature,
            "ACCESS-TIMESTAMP":timestamp,
            "ACCESS-PASSPHRASE":PASSPHRASE,
            "Content-Type":"application/json"

        }

        url=BASE_URL+request_path

        response=requests.post(url,headers=headers,data=body_json)

        print("POSITION RESPONSE:",response.text)

        print("TP SET:",take_profit_price)

        print("SL SET:",stop_loss_price)

    except Exception as e:

        traceback.print_exc()


# =========================
# SIGNAL
# =========================

def get_signal(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/candles?symbol={symbol}&granularity=5m&limit=200&productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        candles = data["data"]

        closes = np.array([float(c[4]) for c in candles])
        volumes = np.array([float(c[5]) for c in candles])

        price = closes[-1]

        # EMA
        ema20 = pd.Series(closes).ewm(span=20).mean().iloc[-1]
        ema50 = pd.Series(closes).ewm(span=50).mean().iloc[-1]
        ema200 = pd.Series(closes).ewm(span=200).mean().iloc[-1]

        # RSI
        delta = pd.Series(closes).diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.iloc[-1]

        # MACD
        ema12 = pd.Series(closes).ewm(span=12).mean()
        ema26 = pd.Series(closes).ewm(span=26).mean()

        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()

        macd_value = macd.iloc[-1]
        signal_value = signal.iloc[-1]

        # Volume
        volume_current = volumes[-1]
        volume_avg = volumes[-20:].mean()

        score_buy = 0
        score_sell = 0

        # Trend
        if ema50 > ema200:
            score_buy += 1
        if ema50 < ema200:
            score_sell += 1

        # RSI
        if 50 < rsi < 70:
            score_buy += 1
        if 30 < rsi < 50:
            score_sell += 1

        # MACD
        if macd_value > signal_value:
            score_buy += 1
        if macd_value < signal_value:
            score_sell += 1

        # Momentum
        if price > ema20:
            score_buy += 1
        if price < ema20:
            score_sell += 1

        # Volume confirmation
        if volume_current > volume_avg:
            score_buy += 1
            score_sell += 1

        print(f"{symbol} SCORE BUY: {score_buy} | SCORE SELL: {score_sell}", flush=True)

        if score_buy >= 4:
            print(f"{symbol} SIGNAL: BUY CONFIRMED", flush=True)
            return "buy"

        if score_sell >= 4:
            print(f"{symbol} SIGNAL: SELL CONFIRMED", flush=True)
            return "sell"

        return None

    except Exception as e:

        print("Signal error:", str(e), flush=True)

        return None


# =========================
# SCAN MARKET
# =========================

def scan_market():

    global last_trade_time

    try:

        if last_trade_time and time.time()-last_trade_time<60:

            return

        active=get_open_positions_count()

        if active>=MAX_ACTIVE_TRADES:

            return

        symbols=get_market_symbols()

        for symbol in symbols:

            open_symbols=[p["symbol"] for p in get_open_positions()]

            if symbol in open_symbols:

                continue

            signal=get_signal(symbol)

            if signal is None:

                continue

            balance=get_real_balance()

            capital=balance*capital_percent["value"]

            price=get_current_price(symbol)

            size=(capital*LEVERAGE)/price

            open_position(symbol,signal,size,LEVERAGE)

            last_trade_time=time.time()

            break

    except:

        traceback.print_exc()


# =========================
# GET SYMBOLS
# =========================

def get_market_symbols():

    try:

        url = BASE_URL + "/api/v2/mix/market/tickers?productType=USDT-FUTURES"

        response = requests.get(url)

        data = response.json()

        symbols_data = []

        if data.get("code") == "00000":

            for item in data["data"]:

                symbol = item.get("symbol")

                volume = float(item.get("baseVolume", 0))

                if symbol.endswith("USDT"):

                    symbols_data.append((symbol, volume))

        # Ordina per volume decrescente
        symbols_data.sort(key=lambda x: x[1], reverse=True)

        # Prendi solo le prime 25
        top_25 = [x[0] for x in symbols_data[:25]]

        print("TOP 25 SYMBOLS SELECTED:", top_25, flush=True)

        return top_25

    except Exception as e:

        print("Error selecting top symbols:", str(e), flush=True)

        return []


# =========================
# LOOP
# =========================

def scanner_loop():

    print("SCANNER STARTED", flush=True)

    while True:

        try:

            print("BOT STATE:", bot_running["state"], flush=True)

            if bot_running["state"] == True:

                print("SCANNING MARKET NOW...", flush=True)

                scan_market()

                print("SCAN COMPLETE — waiting 60 seconds", flush=True)

                time.sleep(60)

            else:

                print("BOT OFF — waiting 5 seconds", flush=True)

                time.sleep(5)

        except Exception as e:

            print("SCANNER LOOP ERROR:", str(e), flush=True)

            traceback.print_exc()

            time.sleep(10)


# =========================
# API
# =========================

@app.route("/status")
def status():

    return jsonify({

        "status":"online" if bot_running["state"] else "offline",

        "balance":get_real_balance(),

        "capital_percent":capital_percent["value"],

        "leverage":LEVERAGE,

        "take_profit":TAKE_PROFIT_PERCENT,

        "stop_loss":STOP_LOSS_PERCENT

    })


@app.route("/get_open_positions")
def api_positions():

    return jsonify(get_open_positions())


@app.route("/start",methods=["POST"])
def start():

    global scanner_thread

    bot_running["state"] = True

    if scanner_thread is None or not scanner_thread.is_alive():

        scanner_thread = threading.Thread(target=scanner_loop)
        scanner_thread.daemon = True
        scanner_thread.start()

        print("SCANNER THREAD STARTED FROM API", flush=True)

    return jsonify({"success":True})


@app.route("/stop",methods=["POST"])
def stop():

    bot_running["state"]=False

    return jsonify({"success":True})


# ============================
# RUN
# ============================


if __name__ == "__main__":

    print("PerfectBot starting...", flush=True)

    print("Scanner thread started at boot", flush=True)

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
