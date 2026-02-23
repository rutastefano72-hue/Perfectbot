import os
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

@app.route('/')
def serve_dashboard():
    return send_from_directory('.', 'dashboard.html')

bot_running = False
import requests

def get_real_balance():
    try:
        api_key = os.environ.get("BITGET_API_KEY")
        secret = os.environ.get("BITGET_API_SECRET")
        passphrase = os.environ.get("BITGET_API_PASSPHRASE")

        url = "https://api.bitget.com/api/mix/v1/account/accounts?productType=UMCBL"

        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-PASSPHRASE": passphrase,
        }

        response = requests.get(url, headers=headers)
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            return float(data["data"][0]["available"])
        else:
            return 0

    except Exception as e:
        return 0

balance = get_real_balance()
profit_today = 0
profit_total = 0

@app.route("/status")
def status():
    return jsonify({
        "status": "online" if bot_running else "offline",
        "balance": balance,
        "profit_today": profit_today,
        "profit_total": profit_total
    })

@app.route("/start", methods=["POST"])
def start_bot():
    global bot_running
    bot_running = True
    return jsonify({"message": "PerfectBot started"})

@app.route("/stop", methods=["POST"])
def stop_bot():
    global bot_running
    bot_running = False
    return jsonify({"message": "PerfectBot stopped"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
