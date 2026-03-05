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
capital_percent = {"value": 0.10}
last_trade_time = None

STOP_LOSS_PERCENT = 0.8
TAKE_PROFIT_PERCENT = 0.4

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

        signature = generate_signature(timestamp, "GET", request_path)

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

                    symbol = pos.get("symbol")
                    side = pos.get("holdSide")
                    entry_price = float(pos.get("openPriceAvg", 0))
                    unrealized = float(pos.get("unrealizedPL", 0))

                    # Calcolo notional attuale
                    mark_price = float(pos.get("markPrice", 0))
                    notional = size * mark_price

                    # Fee round trip stimata (0.06% entrata + 0.06% uscita)
                    estimated_fees = notional * 0.0012

                    # PNL netto reale stimato
                    net_pnl = unrealized - estimated_fees

                    trades.append({

                        "symbol": symbol,
                        "side": side,
                        "entry": entry_price,
                        "pnl": unrealized,
                        "net_pnl": net_pnl

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

def set_leverage(symbol):

    try:

        request_path = "/api/v2/mix/account/set-leverage"

        for side in ["long", "short"]:

            timestamp = str(int(time.time()*1000))

            body = {
                "symbol": symbol,
                "productType": "USDT-FUTURES",
                "marginCoin": "USDT",
                "leverage": str(LEVERAGE),
                "holdSide": side
            }

            body_json = json.dumps(body)

            signature = generate_signature(timestamp, "POST", request_path, body_json)

            headers = {
                "ACCESS-KEY": API_KEY,
                "ACCESS-SIGN": signature,
                "ACCESS-TIMESTAMP": timestamp,
                "ACCESS-PASSPHRASE": PASSPHRASE,
                "Content-Type": "application/json"
            }

            url = BASE_URL + request_path
            response = requests.post(url, headers=headers, data=body_json)

            print(f"SET LEVERAGE {side.upper()}:", response.text, flush=True)

            time.sleep(0.2)

    except Exception as e:
        print("Leverage error:", str(e), flush=True)

def open_position(symbol, side, size, leverage):

    # 🔒 BLOCCO DI SICUREZZA ASSOLUTO
    if not bot_running["state"]:
        print("BLOCKED: bot is OFF — position NOT opened", flush=True)
        return

    try:

        price = get_current_price(symbol)

        if price is None:
            return

        set_leverage(symbol)

        price_precision, size_precision = get_symbol_precision(symbol)

        size = round(size, size_precision)

        # ==============================
        # CALCOLO TP / SL
        # ==============================

        if side == "buy":

            stop_loss_price = round(price * (1 - STOP_LOSS_PERCENT/100), price_precision)
            take_profit_price = round(price * (1 + TAKE_PROFIT_PERCENT/100), price_precision)

        else:

            stop_loss_price = round(price * (1 + STOP_LOSS_PERCENT/100), price_precision)
            take_profit_price = round(price * (1 - TAKE_PROFIT_PERCENT/100), price_precision)

        # ==============================
        # ORDINE APERTURA CON TP/SL
        # ==============================

        request_path = "/api/v2/mix/order/place-order"

        timestamp = str(int(time.time()*1000))

        body = {

            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": "crossed",
            "marginCoin": "USDT",

            "size": str(size),
            "side": side,
            "tradeSide": "open",
            "orderType": "market",

            "holdSide": "long" if side == "buy" else "short",

            "presetTakeProfitPrice": str(take_profit_price),
            "presetStopLossPrice": str(stop_loss_price),

            "presetTakeProfitType": "mark_price",
            "presetStopLossType": "mark_price"

        }

        body_json = json.dumps(body)

        signature = generate_signature(timestamp, "POST", request_path, body_json)

        headers = {

            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"

        }

        url = BASE_URL + request_path

        response = requests.post(url, headers=headers, data=body_json)

        print("ENTRY PRICE USED:", price, flush=True)

        print("ORDER RESPONSE:", response.text, flush=True)
        print("TP SET:", take_profit_price, flush=True)
        print("SL SET:", stop_loss_price, flush=True)

    except Exception as e:

        traceback.print_exc()

def place_conditional_order(symbol, side, size, trigger_price):

    request_path = "/api/v2/mix/order/place-plan-order"
    timestamp = str(int(time.time()*1000))

    body = {

        "symbol": symbol,
        "productType": "USDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "USDT",
        "planType": "normal_plan",
        "triggerPrice": str(trigger_price),
        "triggerType": "mark_price",
        "side": side,
        "tradeSide": "close",
        "orderType": "market",
        "size": str(size),
        "clientOid": str(int(time.time()*1000))

    }

    body_json = json.dumps(body)

    signature = generate_signature(timestamp, "POST", request_path, body_json)

    headers = {

        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"

    }

    url = BASE_URL + request_path

    response = requests.post(url, headers=headers, data=body_json)

    print("CONDITIONAL ORDER RESPONSE:", response.text, flush=True)


# =========================
# SIGNAL
# =========================

def get_higher_timeframe_trend(symbol):

    try:

        url = BASE_URL + f"/api/v2/mix/market/candles?symbol={symbol}&granularity=1h&limit=200&productType=USDT-FUTURES"

        response = requests.get(url)
        data = response.json()

        if not data or "data" not in data:
            return None

        candles = data.get("data")

        if not candles or not isinstance(candles, list):
            return None

        if len(candles) < 50:
            return None

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

        # slope più stabile (prima era -10)
        ema200_slope = ema200.iloc[-1] - ema200.iloc[-20]

        # distanza tra le medie
        ema_distance = abs(ema50.iloc[-1] - ema200.iloc[-1]) / closes[-1]

        # ATR semplificato
        tr1 = highs - lows
        tr2 = abs(highs - np.roll(closes, 1))
        tr3 = abs(lows - np.roll(closes, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        atr = pd.Series(tr).rolling(14).mean().iloc[-1] / closes[-1]

        # forza trend (simile ADX)
        adx_strength = ema_distance * 100

        # =========================
        # LOGICA REGIME
        # =========================

        # mercato troppo fermo
        if atr < 0.002:
            return "NO_TRADE"

        # trend forte
        if adx_strength > 0.3:

            if ema200_slope > 0:
                return "TREND_UP"

            if ema200_slope < 0:
                return "TREND_DOWN"

        # volatilità alta ma senza direzione
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

        # ===== PROTEZIONE API =====
        if "data" not in data or not data["data"]:
            print(f"{symbol} - No candle data", flush=True)
            return None

        candles = data["data"]

        if candles is None or len(candles) < 50:
            print(f"{symbol} - Invalid candle set", flush=True)
            return None

        closes = np.array([float(c[4]) for c in candles if c and len(c) > 4])

        if len(closes) < 50:
            print(f"{symbol} - Not enough close prices", flush=True)
            return None

        # ===== EMA =====
        ema50_series = pd.Series(closes).ewm(span=50).mean()
        ema200_series = pd.Series(closes).ewm(span=200).mean()

        ema50 = ema50_series.iloc[-1]
        ema200 = ema200_series.iloc[-1]

        price = closes[-1]
        previous_price = closes[-2]

        # ==== RSI (BONUS CONFIRMATION) ====
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

        print(f"{symbol} RSI: {rsi}", flush=True)

        # =============================
        # REGIME AI LAYER
        # =============================

        regime = detect_market_regime(symbol)
        print(f"{symbol} REGIME: {regime}", flush=True)

        if regime == "NO_TRADE" or regime == "RANGE":
            return None

        # =============================
        # HTF (BONUS)
        # =============================

        htf_trend = get_higher_timeframe_trend(symbol)
        print(f"{symbol} HTF: {htf_trend}", flush=True)

        # =====================================================
        # ===== PULLBACK ENTRY LOGIC =====
        # =====================================================

        # ---- LONG PULLBACK ----
        if regime == "TREND_UP" and ema50 > ema200:

            # prezzo era sotto o vicino EMA50 e ora chiude sopra
            if price > ema50 and price < ema50 * 1.003:

                if htf_trend == "buy":
                    print(f"{symbol} PULLBACK LONG (HTF aligned)", flush=True)
                else:
                    print(f"{symbol} PULLBACK LONG", flush=True)

                return "buy"

        # ---- SHORT PULLBACK ----
        if regime == "TREND_DOWN" and ema50 < ema200:

            # prezzo era sopra o vicino EMA50 e ora chiude sotto
            if price < ema50 and price > ema50 * 0.997:

                if htf_trend == "sell":
                    print(f"{symbol} PULLBACK SHORT (HTF aligned)", flush=True)
                else:
                    print(f"{symbol} PULLBACK SHORT", flush=True)

                return "sell"

        print(f"{symbol} rejected by pullback logic", flush=True)

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

        symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "AVAXUSDT",
            "LINKUSDT",
            "DOGEUSDT",
            "MATICUSDT",

            "ATOMUSDT",
            "INJUSDT",
            "APTUSDT",
            "ARBUSDT",
            "OPUSDT",
            "NEARUSDT",
            "FILUSDT",
            "SUIUSDT",
            "SEIUSDT",
            "ETCUSDT"
        ]

        print("FIXED SYMBOL LIST SELECTED:", symbols, flush=True)

        return symbols

    except Exception as e:
        print("Error selecting fixed symbols:", str(e), flush=True)
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

                print("SCAN COMPLETE — waiting 20 seconds", flush=True)

                time.sleep(20)

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

@app.route("/trade_history")
def trade_history():
    try:
        timestamp = str(int(time.time() * 1000))

        # 🔥 endpoint corretto V2
        request_path = "/api/v2/mix/order/orders-history?productType=usdt-futures&pageSize=5&pageNo=1"

        signature = generate_signature(timestamp, "GET", request_path)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
        }

        url = BASE_URL + request_path
        response = requests.get(url, headers=headers, timeout=10)

        # 👇 restituiamo la risposta grezza di Bitget
        return response.text

    except Exception as e:
        return str(e)


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
