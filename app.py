"""Smart Agriculture Waste Collection and Management System - Flask API."""
import os, sqlite3
from functools import wraps
from flask import Flask, g, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Vercel's filesystem is read-only except /tmp (data resets on cold start).
# For permanent data on Vercel, switch to a hosted DB such as Postgres.
DB_PATH = "/tmp/agri.db" if ON_VERCEL else os.path.join(BASE, "agri.db")

app = Flask(__name__, static_folder=os.path.join(BASE, "public"), static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=ON_VERCEL,
)

STATUSES = ("pending", "accepted", "scheduled", "collected", "recycled", "rejected")
MESSAGES = {
    "accepted": "Your collection request #{id} was accepted.",
    "scheduled": "Request #{id} is scheduled for {date}.",
    "collected": "Request #{id} has been collected. Please rate the service.",
    "recycled": "Your waste from request #{id} has been recycled.",
    "rejected": "Request #{id} could not be accepted.",
}

# ---------- database helpers ----------
def db():
    if not os.path.exists(DB_PATH):
        init_db()   # new serverless instance: its /tmp is empty
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def query(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    rows = [dict(r) for r in rows]
    return (rows[0] if rows else None) if one else rows

def execute(sql, args=()):
    cur = db().execute(sql, args)
    db().commit()
    return cur.lastrowid

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(open(os.path.join(BASE, "schema.sql")).read())
    if not con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        demo = [("Demo Farmer", "farmer@demo.com", "farmer"),
                ("Demo Collector", "worker@demo.com", "worker"),
                ("Demo Admin", "admin@demo.com", "admin")]
        for n, e, r in demo:
            con.execute("INSERT INTO users(name,email,password_hash,role) VALUES (?,?,?,?)",
                        (n, e, generate_password_hash("demo123"), r))
        # a few sample records so the dashboard is not empty
        for cat, kg, st, addr, lat, lng in [
            (2, 450, "collected", "Plot 12, Daund", 18.4637, 74.5833),
            (1, 800, "recycled", "Village Road, Pune", 18.5204, 73.8567),
            (4, 120, "scheduled", "Orchard Lane, Baramati", 18.1514, 74.5815),
            (3, 300, "pending", "Mill Road, Shirur", 18.8290, 74.3757)]:
            rid = con.execute("INSERT INTO waste_reports(farmer_id,category_id,quantity_kg) VALUES (1,?,?)", (cat, kg)).lastrowid
            con.execute("""INSERT INTO collection_requests(report_id,farmer_id,worker_id,address,latitude,longitude,status)
                           VALUES (?,1,?,?,?,?,?)""", (rid, 2 if st != "pending" else None, addr, lat, lng, st))
        con.execute("INSERT INTO notifications(user_id,message) VALUES (1,'Welcome! This is a demo account.')")
        con.commit()
    con.close()

init_db()

# ---------- auth helpers ----------
def current_user():
    uid = session.get("uid")
    return query("SELECT id,name,email,phone,role FROM users WHERE id=?", (uid,), one=True) if uid else None

def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u: return jsonify(error="Please log in."), 401
            if roles and u["role"] not in roles: return jsonify(error="Not allowed."), 403
            g.user = u
            return fn(*a, **kw)
        return wrapper
    return deco

def notify(user_id, message):
    execute("INSERT INTO notifications(user_id,message) VALUES (?,?)", (user_id, message))

# ---------- 1. auth ----------
@app.post("/api/register")
def register():
    d = request.get_json(force=True)
    name, email, pw = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), d.get("password") or ""
    role = d.get("role", "farmer")
    if role not in ("farmer", "worker"): return jsonify(error="Invalid role."), 400   # admins can't self-register
    if not name or "@" not in email or len(pw) < 6:
        return jsonify(error="Enter a name, valid email and a password of 6+ characters."), 400
    if query("SELECT 1 FROM users WHERE email=?", (email,), one=True):
        return jsonify(error="That email is already registered."), 409
    uid = execute("INSERT INTO users(name,email,phone,password_hash,role) VALUES (?,?,?,?,?)",
                  (name, email, d.get("phone"), generate_password_hash(pw), role))
    session["uid"] = uid
    return jsonify(user=current_user()), 201

@app.post("/api/login")
def login():
    d = request.get_json(force=True)
    u = query("SELECT * FROM users WHERE email=?", ((d.get("email") or "").strip().lower(),), one=True)
    if not u or not check_password_hash(u["password_hash"], d.get("password") or ""):
        return jsonify(error="Wrong email or password."), 401
    session.clear(); session["uid"] = u["id"]
    return jsonify(user=current_user())

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify(ok=True)

@app.get("/api/me")
def me():
    return jsonify(user=current_user())

# ---------- 3 & 7. categories + recycling info ----------
@app.get("/api/categories")
@login_required()
def categories():
    return jsonify(query("SELECT * FROM categories ORDER BY name"))

# ---------- 2, 4, 5. report waste + request collection ----------
REQ_SELECT = """SELECT r.id, r.status, r.address, r.latitude, r.longitude, r.scheduled_date, r.created_at,
       w.quantity_kg, w.notes, c.name AS category, c.recycling_method,
       f.name AS farmer, wk.name AS worker,
       (SELECT 1 FROM feedback fb WHERE fb.request_id=r.id) AS has_feedback
  FROM collection_requests r
  JOIN waste_reports w ON w.id=r.report_id
  JOIN categories c ON c.id=w.category_id
  JOIN users f ON f.id=r.farmer_id
  LEFT JOIN users wk ON wk.id=r.worker_id """

@app.post("/api/requests")
@login_required("farmer")
def add_request():
    d = request.get_json(force=True)
    try:
        cat, qty = int(d["category_id"]), float(d["quantity_kg"])
    except (KeyError, ValueError, TypeError):
        return jsonify(error="Choose a waste type and enter the quantity."), 400
    address = (d.get("address") or "").strip()
    if qty <= 0 or not address: return jsonify(error="Quantity and location are required."), 400
    if not query("SELECT 1 FROM categories WHERE id=?", (cat,), one=True):
        return jsonify(error="Unknown waste type."), 400
    rid = execute("INSERT INTO waste_reports(farmer_id,category_id,quantity_kg,notes) VALUES (?,?,?,?)",
                  (g.user["id"], cat, qty, d.get("notes")))
    req_id = execute("""INSERT INTO collection_requests(report_id,farmer_id,address,latitude,longitude)
                        VALUES (?,?,?,?,?)""", (rid, g.user["id"], address, d.get("latitude"), d.get("longitude")))
    for w in query("SELECT id FROM users WHERE role='worker'"):
        notify(w["id"], f"New collection request #{req_id} at {address}.")
    notify(g.user["id"], f"Request #{req_id} submitted. We'll notify you when it's accepted.")
    return jsonify(id=req_id), 201

@app.get("/api/requests")
@login_required()
def list_requests():
    u = g.user
    if u["role"] == "farmer":
        rows = query(REQ_SELECT + "WHERE r.farmer_id=? ORDER BY r.id DESC", (u["id"],))
    elif u["role"] == "worker":   # open requests + the worker's own jobs
        rows = query(REQ_SELECT + "WHERE r.status='pending' OR r.worker_id=? ORDER BY r.id DESC", (u["id"],))
    else:
        rows = query(REQ_SELECT + "ORDER BY r.id DESC")
    return jsonify(rows)

# ---------- 6. collection management ----------
@app.patch("/api/requests/<int:rid>")
@login_required("worker", "admin")
def update_request(rid):
    d = request.get_json(force=True)
    status = d.get("status")
    r = query("SELECT * FROM collection_requests WHERE id=?", (rid,), one=True)
    if not r: return jsonify(error="Request not found."), 404
    if status not in STATUSES: return jsonify(error="Invalid status."), 400
    if status == "scheduled" and not d.get("scheduled_date"):
        return jsonify(error="Pick a pickup date."), 400
    worker_id = r["worker_id"] or (g.user["id"] if g.user["role"] == "worker" else None)
    if g.user["role"] == "worker" and r["worker_id"] not in (None, g.user["id"]):
        return jsonify(error="Another worker owns this request."), 403
    execute("""UPDATE collection_requests SET status=?, worker_id=?, scheduled_date=COALESCE(?,scheduled_date),
               updated_at=CURRENT_TIMESTAMP WHERE id=?""", (status, worker_id, d.get("scheduled_date"), rid))
    if status in MESSAGES:
        notify(r["farmer_id"], MESSAGES[status].format(id=rid, date=d.get("scheduled_date")))
    return jsonify(ok=True)

# ---------- 9. notifications ----------
@app.get("/api/notifications")
@login_required()
def notifications():
    return jsonify(query("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50", (g.user["id"],)))

@app.post("/api/notifications/read")
@login_required()
def read_notifications():
    execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],))
    return jsonify(ok=True)

# ---------- 8. dashboard ----------
@app.get("/api/dashboard")
@login_required()
def dashboard():
    u = g.user
    scope, args = ("", ())
    if u["role"] == "farmer": scope, args = "WHERE r.farmer_id=?", (u["id"],)
    elif u["role"] == "worker": scope, args = "WHERE (r.worker_id=? OR r.status='pending')", (u["id"],)
    row = query(f"""SELECT
        COALESCE(SUM(w.quantity_kg),0) AS reported,
        COALESCE(SUM(CASE WHEN r.status IN ('collected','recycled') THEN w.quantity_kg END),0) AS collected,
        COALESCE(SUM(CASE WHEN r.status='recycled' THEN w.quantity_kg END),0) AS recycled,
        COUNT(CASE WHEN r.status='pending' THEN 1 END) AS pending,
        COUNT(*) AS total_requests
      FROM collection_requests r JOIN waste_reports w ON w.id=r.report_id {scope}""", args, one=True)
    row["unread"] = query("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0", (u["id"],), one=True)["n"]
    return jsonify(row)

# ---------- 11. analytics ----------
@app.get("/api/reports")
@login_required("admin", "worker")
def reports():
    by_cat = query("""SELECT c.name, ROUND(SUM(w.quantity_kg),1) AS kg, COUNT(*) AS n
        FROM waste_reports w JOIN categories c ON c.id=w.category_id GROUP BY c.id ORDER BY kg DESC""")
    by_status = query("SELECT status, COUNT(*) n FROM collection_requests GROUP BY status")
    monthly = query("""SELECT strftime('%Y-%m', w.created_at) AS month, ROUND(SUM(w.quantity_kg),1) AS kg
        FROM waste_reports w GROUP BY month ORDER BY month DESC LIMIT 6""")
    fb = query("SELECT ROUND(AVG(rating),2) AS avg, COUNT(*) AS n FROM feedback", one=True)
    return jsonify(by_category=by_cat, by_status=by_status, monthly=monthly[::-1], feedback=fb)

# ---------- 12. feedback ----------
@app.post("/api/feedback")
@login_required("farmer")
def add_feedback():
    d = request.get_json(force=True)
    r = query("SELECT status FROM collection_requests WHERE id=? AND farmer_id=?", (d.get("request_id"), g.user["id"]), one=True)
    if not r or r["status"] not in ("collected", "recycled"):
        return jsonify(error="You can rate a request after it is collected."), 400
    rating = int(d.get("rating", 0))
    if not 1 <= rating <= 5: return jsonify(error="Choose 1 to 5 stars."), 400
    try:
        execute("INSERT INTO feedback(request_id,farmer_id,rating,comment) VALUES (?,?,?,?)",
                (d["request_id"], g.user["id"], rating, d.get("comment")))
    except sqlite3.IntegrityError:
        return jsonify(error="You already rated this request."), 409
    return jsonify(ok=True), 201

# ---------- 10. admin ----------
@app.get("/api/admin/users")
@login_required("admin")
def admin_users():
    return jsonify(query("SELECT id,name,email,phone,role,created_at FROM users ORDER BY id"))

@app.delete("/api/admin/users/<int:uid>")
@login_required("admin")
def admin_delete_user(uid):
    if uid == g.user["id"]: return jsonify(error="You can't delete yourself."), 400
    execute("DELETE FROM users WHERE id=?", (uid,))
    return jsonify(ok=True)

@app.delete("/api/admin/requests/<int:rid>")
@login_required("admin")
def admin_delete_request(rid):
    execute("DELETE FROM waste_reports WHERE id=(SELECT report_id FROM collection_requests WHERE id=?)", (rid,))
    return jsonify(ok=True)

@app.get("/api/admin/feedback")
@login_required("admin")
def admin_feedback():
    return jsonify(query("""SELECT fb.*, u.name AS farmer FROM feedback fb JOIN users u ON u.id=fb.farmer_id ORDER BY fb.id DESC"""))

# ---------- errors + health ----------
from werkzeug.exceptions import HTTPException

@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e
    app.logger.exception(e)
    return jsonify(error=f"Server error ({type(e).__name__}): {e}"), 500

@app.get("/api/health")
def health():
    pub = app.static_folder
    return jsonify(ok=True, vercel=ON_VERCEL, users=query("SELECT COUNT(*) n FROM users", one=True)["n"],
                   public_folder_found=os.path.isdir(pub),
                   files=sorted(os.listdir(pub)) if os.path.isdir(pub) else [],
                   root_files=sorted(os.listdir(BASE)))

# ---------- frontend ----------
@app.get("/")
def index():
    if not os.path.exists(os.path.join(app.static_folder, "index.html")):
        return ("The API is running, but public/index.html is missing from the deployment. "
                "Check that the 'public' folder is in your GitHub repo. See /api/health.", 500)
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
