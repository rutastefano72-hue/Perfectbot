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
signal_memory = {}

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

def get_higher_timeframe_trend(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/candles?symbol={symbol}&granularity=1h&limit=200&productType=USDT-FUTURES"

        response = requests.get(url)
        data = response.json()

        if "data" not in data:
            return None

        candles = data["data"]

        closes = np.array([float(c[4]) for c in candles])

        ema50 = pd.Series(closes).ewm(span=50).mean().iloc[-1]
        ema200 = pd.Series(closes).ewm(span=200).mean().iloc[-1]

        if ema50 > ema200:
            return "buy"

        if ema50 < ema200:
            return "sell"

        return None

    except Exception as e:

        print("HTF error:", str(e), flush=True)
        return None

def detect_market_regime(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/candles?symbol={symbol}&granularity=15m&limit=200&productType=USDT-FUTURES"

        response = requests.get(url)
        data = response.json()

        if "data" not in data:
            return "NO_TRADE"

        candles = data["data"]

        closes = np.array([float(c[4]) for c in candles])
        highs = np.array([float(c[2]) for c in candles])
        lows = np.array([float(c[3]) for c in candles])

        ema50 = pd.Series(closes).ewm(span=50).mean()
        ema200 = pd.Series(closes).ewm(span=200).mean()

        # Calcolo slope EMA200
        if len(ema200) < 10:
            return "NO_TRADE"

        ema200_slope = ema200.iloc[-1] - ema200.iloc[-10]

        # Distanza tra EMA50 e EMA200
        ema_distance = abs(ema50.iloc[-1] - ema200.iloc[-1]) / closes[-1]

        # ATR semplificato
        tr1 = highs - lows
        tr2 = abs(highs - np.roll(closes, 1))
        tr3 = abs(lows - np.roll(closes, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        atr = pd.Series(tr).rolling(14).mean().iloc[-1] / closes[-1]

        # Forza trend (simile ADX)
        adx_strength = ema_distance * 100

        # Logica decisionale

        if atr < 0.003:
            return "NO_TRADE"

        if adx_strength > 0.5 and ema200_slope > 0:
            return "TREND_UP"

        if adx_strength > 0.5 and ema200_slope < 0:
            return "TREND_DOWN"

        if atr > 0.02:
            return "VOLATILE"

        return "RANGE"

    except Exception as e:

        print("Regime error:", str(e), flush=True)
        return "NO_TRADE"

def get_signal(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/candles?symbol={symbol}&granularity=5m&limit=200&productType=USDT-FUTURES"

        response = requests.get(url)
        data = response.json()

        if "data" not in data:
            return None

        candles = data["data"]

        closes = np.array([float(c[4]) for c in candles])

        ema50 = pd.Series(closes).ewm(span=50).mean()
        ema200 = pd.Series(closes).ewm(span=200).mean()

        price = closes[-1]

        score_buy = 0
        score_sell = 0

        # EMA Trend
        if ema50.iloc[-1] > ema200.iloc[-1]:
            score_buy += 1

        if ema50.iloc[-1] < ema200.iloc[-1]:
            score_sell += 1

        # Price vs EMA50
        if price > ema50.iloc[-1]:
            score_buy += 1

        if price < ema50.iloc[-1]:
            score_sell += 1

        # RSI
        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        avg_gain = pd.Series(gain).rolling(14).mean().iloc[-1]
        avg_loss = pd.Series(loss).rolling(14).mean().iloc[-1]

        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        if rsi > 55:
            score_buy += 1

        if rsi < 45:
            score_sell += 1

        print(f"{symbol} SCORE BUY: {score_buy} | SCORE SELL: {score_sell}", flush=True)

        # =============================
        # REGIME AI LAYER
        # =============================

        regime = detect_market_regime(symbol)

        print(f"{symbol} REGIME: {regime}", flush=True)

        if regime == "NO_TRADE":
            return None

        if regime == "RANGE":
            return None

        # =============================
        # HTF FILTER
        # =============================

        htf_trend = get_higher_timeframe_trend(symbol)

        if regime == "TREND_UP" and score_buy >= 4 and htf_trend == "buy":
            print(f"{symbol} SIGNAL: BUY CONFIRMED (AI TREND UP)", flush=True)
            return "buy"

        if regime == "TREND_DOWN" and score_sell >= 4 and htf_trend == "sell":
            print(f"{symbol} SIGNAL: SELL CONFIRMED (AI TREND DOWN)", flush=True)
            return "sell"

        print(f"{symbol} rejected by AI regime or HTF filter", flush=True)

        return None

    except Exception as e:

        print("Signal error:", str(e), flush=True)
        traceback.print_exc()
        return None


# =========================
# SCAN MARKET
# =========================

def scan_market():

    global last_trade_time
    global signal_memory

    try:

        # Evita troppi trade ravvicinati
        if last_trade_time and time.time() - last_trade_time < 60:
            return

        active = get_open_positions_count()

        if active >= MAX_ACTIVE_TRADES:
            return

        symbols = get_market_symbols()

        for symbol in symbols:

            open_symbols = [p["symbol"] for p in get_open_positions()]

            if symbol in open_symbols:
                continue

            signal = get_signal(symbol)

            # Nessun segnale → reset memoria
            if signal is None:
                if symbol in signal_memory:
                    del signal_memory[symbol]
                continue

            # Prima conferma
            if symbol not in signal_memory:
                signal_memory[symbol] = signal
                print(f"{symbol} first confirmation stored", flush=True)
                continue

            # Seconda conferma
            if signal_memory.get(symbol) == signal:
                print(f"{symbol} second confirmation — opening trade", flush=True)
            else:
                signal_memory[symbol] = signal
                continue

            # Apertura trade
            balance = get_real_balance()
            capital = balance * capital_percent["value"]

            price = get_current_price(symbol)
            if price is None:
                continue

            size = (capital * LEVERAGE) / price

            open_position(symbol, signal, size, LEVERAGE)

            last_trade_time = time.time()

            # Reset memoria dopo apertura
            if symbol in signal_memory:
                del signal_memory[symbol]

            break

    except Exception as e:
        print("SCAN MARKET ERROR:", str(e), flush=True)
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
