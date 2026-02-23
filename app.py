from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

# Serve il dashboard HTML
@app.route('/dashboard.html')
def serve_dashboard():
    return send_from_directory('', 'dashboard.html')

# Stato bot
bot_running = False
balance = 5000
profit_today = 0
profit_total = 0

# API stato
@app.route("/")
def status():
    return jsonify({
        "status": "online" if bot_running else "offline",
        "balance": balance,
        "profit_today": profit_today,
        "profit_total": profit_total
    })

# Avvio bot
@app.route("/start", methods=["POST"])
def start_bot():
    global bot_running
    bot_running = True
    return jsonify({"message": "PerfectBot started"})

# Stop bot
@app.route("/stop", methods=["POST"])
def stop_bot():
    global bot_running
    bot_running = False
    return jsonify({"message": "PerfectBot stopped"})

# Avvio server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
