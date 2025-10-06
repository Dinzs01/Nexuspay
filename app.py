 # app.py
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import hashlib
import os
from functools import wraps
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "payup.db")

app = Flask(__name__)
app.secret_key = "change_this_secret_in_production"

CREDIT_PER_VIDEO = 0.01          # amount to credit per full watch (adjustable)
MIN_WITHDRAW = 5.0               # minimum payout

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        g._database = db
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def hashpw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for('login'))
        db = get_db()
        cur = db.execute("SELECT is_admin FROM users WHERE id = ?", (session["user_id"],))
        row = cur.fetchone()
        if not row or row["is_admin"] != 1:
            flash("Admin access required", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def index():
    return render_template("base.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    ref = request.args.get("ref")
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        referred_by = request.form.get("referred_by") or None

        if not username or not password:
            flash("Username and password required", "danger")
            return redirect(url_for("register"))

        password_hash = hashpw(password)
        referral_code = username + "_ref"  # simple referral code; change if needed

        db = get_db()
        try:
            db.execute("INSERT INTO users (username, email, password, referral_code, referred_by) VALUES (?, ?, ?, ?, ?)",
                       (username, email, password_hash, referral_code, referred_by or ref))
            db.commit()
            flash("Registered successfully. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists", "danger")
            return redirect(url_for("register"))
    else:
        return render_template("register.html", ref=ref)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        db = get_db()
        cur = db.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        if user and user["password"] == hashpw(password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Logged in", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    cur = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],))
    user = cur.fetchone()
    referral_link = request.url_root.rstrip("/") + url_for("register") + "?ref=" + user["referral_code"]
    return render_template("dashboard.html", user=user, referral_link=referral_link, min_withdraw=MIN_WITHDRAW)

@app.route("/watch/<video_id>")
@login_required
def watch(video_id):
    # shows the watch page containing video player and JS to report watch time
    return render_template("watch.html", video_id=video_id, credit=CREDIT_PER_VIDEO)

@app.route("/api/report_watch", methods=["POST"])
@login_required
def report_watch():
    """
    Client must POST JSON: { video_id: str, watched_seconds: int, video_duration: int }
    We perform a simple check: only credit if watched_seconds >= 0.8 * video_duration (80% watched)
    and we also check if this user hasn't already been credited for this video recently.
    """
    data = request.get_json()
    video_id = data.get("video_id")
    watched_seconds = int(data.get("watched_seconds", 0))
    video_duration = int(data.get("video_duration", 0))

    if not video_id or video_duration <= 0:
        return {"status": "error", "message": "invalid data"}, 400

    # anti-fraud: require >=80% watch
    if watched_seconds < 0.8 * video_duration:
        return {"status": "ignored", "message": "watch too short"}, 200

    db = get_db()
    user_id = session["user_id"]

    # check if already credited in last 1 hour for same video (simple duplicate protection)
    cur = db.execute("SELECT COUNT(*) as cnt FROM watched WHERE user_id = ? AND video_id = ? AND timestamp >= datetime('now', '-1 hour')", (user_id, video_id))
    row = cur.fetchone()
    if row and row["cnt"] > 0:
        return {"status": "ignored", "message": "already credited recently"}, 200

    # credit user
    db.execute("INSERT INTO watched (user_id, video_id, watched_seconds) VALUES (?, ?, ?)", (user_id, video_id, watched_seconds))
    db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (CREDIT_PER_VIDEO, user_id))
    db.commit()

    # referral bonus: if user was referred, give small percent to referrer (optional simple rule)
    cur = db.execute("SELECT referred_by FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    ref_code = row["referred_by"]
    if ref_code:
        # find referrer
        cur = db.execute("SELECT id FROM users WHERE referral_code = ?", (ref_code,))
        ref_row = cur.fetchone()
        if ref_row:
            ref_id = ref_row["id"]
            bonus = CREDIT_PER_VIDEO * 0.10  # 10% to referrer
            db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bonus, ref_id))
            db.commit()

    return {"status": "ok", "credited": CREDIT_PER_VIDEO}, 200

@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    db = get_db()
    if request.method == "POST":
        amount = float(request.form.get("amount", "0"))
        cur = db.execute("SELECT balance FROM users WHERE id = ?", (session["user_id"],))
        row = cur.fetchone()
        if not row:
            flash("User not found", "danger")
            return redirect(url_for("withdraw"))
        balance = row["balance"]
        if amount <= 0 or amount > balance:
            flash("Invalid amount", "danger")
            return redirect(url_for("withdraw"))
        if amount < MIN_WITHDRAW:
            flash(f"Minimum withdrawal is {MIN_WITHDRAW}", "danger")
            return redirect(url_for("withdraw"))
        # create withdrawal request (admin must approve)
        db.execute("INSERT INTO withdrawals (user_id, amount, status) VALUES (?, ?, ?)", (session["user_id"], amount, "pending"))
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, session["user_id"]))
        db.commit()
        flash("Withdrawal request created (pending admin approval)", "success")
        return redirect(url_for("dashboard"))
    else:
        cur = db.execute("SELECT balance FROM users WHERE id = ?", (session["user_id"],))
        row = cur.fetchone()
        balance = row["balance"] if row else 0.0
        return render_template("withdraw.html", balance=balance, min_withdraw=MIN_WITHDRAW)

# Admin functions
@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    users = db.execute("SELECT id, username, email, balance, referral_code, referred_by FROM users").fetchall()
    withdrawals = db.execute("SELECT w.*, u.username FROM withdrawals w LEFT JOIN users u ON w.user_id = u.id ORDER BY w.request_time DESC").fetchall()
    return render_template("admin.html", users=users, withdrawals=withdrawals)

@app.route("/admin/process_withdrawal/<int:w_id>", methods=["POST"])
@admin_required
def process_withdrawal(w_id):
    action = request.form.get("action")
    db = get_db()
    if action == "approve":
        db.execute("UPDATE withdrawals SET status = 'approved', processed_time = datetime('now') WHERE id = ?", (w_id,))
        db.commit()
        flash("Withdrawal approved (you must actually pay the user externally)", "success")
    else:
        # reject: refund user
        cur = db.execute("SELECT user_id, amount FROM withdrawals WHERE id = ?", (w_id,))
        row = cur.fetchone()
        if row:
            uid = row["user_id"]
            amt = row["amount"]
            db.execute("UPDATE withdrawals SET status = 'rejected', processed_time = datetime('now') WHERE id = ?", (w_id,))
            db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amt, uid))
            db.commit()
            flash("Withdrawal rejected and amount refunded", "info")
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(debug=True)
