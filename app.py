import os, json, csv, time, re
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, jsonify

APP_NAME = "Rutherglen Fire Brigade App"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUBMISSIONS_DIR = DATA_DIR / "submissions" / "post_job"
MAINT_SUB_DIR = DATA_DIR / "submissions" / "maintenance_night"

CREW_CSV = DATA_DIR / "crew_list.csv"
EQUIP_CSV = DATA_DIR / "equipment_list.csv"
MAINT_CSV = DATA_DIR / "maintenance_tasks.csv"
ADMIN_FILE = DATA_DIR / "admins.txt"

STATUS_OPTIONS = [
    "Ready for Use",
    "Replaced and drying",
    "Note for follow-up",
    "Tagged out for repairs",
    "Damaged or Lost"
]

def username_from_name(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())

# ---------- Robust CSV I/O (delimiter sniffing) ----------
def _read_csv_rows(path: Path):
    """Read CSV/TSV with delimiter sniffing (comma/tab/semicolon/pipe)."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except Exception:
            class _D(csv.Dialect):
                delimiter = ","
                quotechar = '"'
                doublequote = True
                skipinitialspace = True
                lineterminator = "\n"
                quoting = csv.QUOTE_MINIMAL
            dialect = _D
        reader = csv.DictReader(f, dialect=dialect)
        return list(reader)

def _write_csv_rows(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

# ---------- Loaders ----------
def load_users_from_crew():
    rows = _read_csv_rows(CREW_CSV)
    if not rows:
        return {}
    def norm(k): return re.sub(r"\s+", "", k.strip().lower())
    name_key = None
    if rows:
        norm_keys = {norm(k): k for k in rows[0].keys()}
        if "name" in norm_keys:
            name_key = norm_keys["name"]
        else:
            for nk, orig in norm_keys.items():
                if "name" in nk:
                    name_key = orig
                    break
    if not name_key:
        return {}

    users = {}
    for r in rows:
        name = (r.get(name_key) or "").strip()
        if not name:
            continue
        uname = username_from_name(name)
        pwd = f"{uname}3865"
        users[uname] = {"name": name, "password": pwd}

    out_rows = [{"name": v["name"], "username": k, "password": v["password"]} for k, v in users.items()]
    _write_csv_rows(DATA_DIR / "users.csv", ["name", "username", "password"], out_rows)
    return users

def load_equipment_by_appliance():
    rows = _read_csv_rows(EQUIP_CSV)
    if not rows:
        return {}
    headers = rows[0].keys()
    def norm(k): return re.sub(r"\s+", "", k.strip().lower())
    nmap = {norm(h): h for h in headers}

    appliance_col = nmap.get("appliance") or next((nmap[h] for h in nmap if "appliance" in h), None)
    equip_col = (
        nmap.get("equipmentname")
        or nmap.get("equipment")
        or next((nmap[h] for h in nmap if "equip" in h), None)
    )

    if not appliance_col or not equip_col:
        return {}

    by_appliance = {}
    for r in rows:
        appl = (r.get(appliance_col) or "").strip()
        eq = (r.get(equip_col) or "").strip()
        if not appl or not eq:
            continue
        by_appliance.setdefault(appl, []).append(eq)
    return by_appliance

def load_maintenance_tasks():
    rows = _read_csv_rows(MAINT_CSV)
    if not rows:
        return {}
    headers = rows[0].keys()
    def norm(k): return re.sub(r"\s+", "", k.strip().lower())
    nmap = {norm(h): h for h in headers}

    appl_col = nmap.get("appliance") or next((nmap[h] for h in nmap if "appliance" in h), None)
    task_col = nmap.get("task") or next((nmap[h] for h in nmap if "task" in h), None)
    area_col = nmap.get("area") or next((nmap[h] for h in nmap if "area" in h), None)
    train_col = nmap.get("training") or next((nmap[h] for h in nmap if "train" in h), None)

    if not (appl_col and task_col):
        return {}

    out = {}
    for r in rows:
        appl = (r.get(appl_col) or "").strip()
        task = (r.get(task_col) or "").strip()
        area = (r.get(area_col) or "").strip() if area_col else ""
        training = (r.get(train_col) or "").strip() if train_col else ""
        if not appl or not task:
            continue
        out.setdefault(appl, []).append({"task": task, "area": area, "training": training})
    return out

def load_admins():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ADMIN_FILE.exists():
        admins = {line.strip().lower() for line in ADMIN_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
        return admins or {"alexscott"}
    ADMIN_FILE.write_text("alexscott\n", encoding="utf-8")
    return {"alexscott"}

def save_admins(usernames):
    usernames = sorted({u.strip().lower() for u in usernames if u.strip()})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_FILE.write_text("\n".join(usernames) + "\n", encoding="utf-8")

# ---------- Decorators ----------
def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def admin_only(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        uname = session["user"]["username"].lower()
        if uname not in load_admins():
            flash("You don’t have permission to access Admin.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped

# ---------- App ----------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

@app.context_processor
def inject_globals():
    return {"APP_NAME": APP_NAME}

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = load_users_from_crew()
        uname = request.form.get("username", "").strip().lower().replace(" ", "")
        pwd = request.form.get("password", "").strip()
        user = users.get(uname)
        if user and pwd == user["password"]:
            session["user"] = {"username": uname, "name": user["name"]}
            return redirect(request.args.get("next") or url_for("home"))
        flash("Invalid credentials. If you are having issues logging in, call Alex on 0481 343 156", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# (Rest of file continues exactly as in the last working version you had…)
