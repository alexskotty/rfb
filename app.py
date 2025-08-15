import os, json, csv, time, re
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, jsonify
import pandas as pd

APP_NAME = "Rutherglen Fire Brigade App"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUBMISSIONS_DIR = DATA_DIR / "submissions" / "post_job"
CREW_CSV = DATA_DIR / "crew_list.csv"
EQUIP_CSV = DATA_DIR / "equipment_list.csv"
ADMIN_FILE = DATA_DIR / "admins.txt"

STATUS_OPTIONS = [
    "Ready for Use",
    "Replaced and drying",
    "Note for follow-up",
    "Tagged out for repairs",
    "Damaged or Lost"
]

def username_from_name(name):
    """Lowercase, strip non-alphanum, no spaces."""
    uname = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return uname

def load_users_from_crew():
    """Build user dict from crew CSV and write data/users.csv for reference."""
    if not CREW_CSV.exists():
        return {}
    df = pd.read_csv(CREW_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    if "name" not in df.columns:
        return {}
    users = {}
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        uname = username_from_name(name)
        pwd = f"{uname}3865"
        users[uname] = {"name": name, "password": pwd}
    # Export a users.csv for admin reference
    out = pd.DataFrame(
        [{"name": v["name"], "username": k, "password": v["password"]} for k, v in users.items()]
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(DATA_DIR / "users.csv", index=False)
    return users

def load_equipment_by_appliance():
    """
    Returns {appliance: [equipment_name, ...], ...}
    Auto-detects column names (case/space-insensitive). Accepts 'Equipment' or 'Equipment Name'.
    """
    if not EQUIP_CSV.exists():
        return {}
    df = pd.read_csv(EQUIP_CSV)
    # normalize column names: lowercase, remove spaces
    df.rename(columns={c: re.sub(r"\s+", "", c.strip().lower()) for c in df.columns}, inplace=True)
    # detect appliance and equipment columns
    appliance_col = None
    equip_col = None
    for c in df.columns:
        if "appliance" in c:
            appliance_col = c
        # allow either 'equipment' or 'equipmentname' (and similar)
        if ("equipment" in c and "name" in c) or c == "equipment":
            equip_col = c
    if not appliance_col:
        for c in df.columns:
            if "appliance" in c:
                appliance_col = c
                break
    if not equip_col:
        for c in df.columns:
            if "equip" in c:
                equip_col = c
                break
    if not appliance_col or not equip_col:
        return {}
    equip = {}
    for appliance, sub in df.groupby(appliance_col):
        names = sub[equip_col].dropna().astype(str).tolist()
        equip[str(appliance)] = names
    return equip

def load_admins():
    """Return a set of usernames allowed to access the Admin area."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ADMIN_FILE.exists():
        admins = {line.strip().lower() for line in ADMIN_FILE.read_text().splitlines() if line.strip()}
        # safety default: keep alexscott if file is empty
        return admins or {"alexscott"}
    # create default file with alexscott if missing
    ADMIN_FILE.write_text("alexscott\n")
    return {"alexscott"}

def save_admins(usernames):
    """Persist admin usernames (lowercase, one per line)."""
    usernames = sorted({u.strip().lower() for u in usernames if u.strip()})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_FILE.write_text("\n".join(usernames) + "\n")

def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def admin_only(view):
    """Require the current logged-in user to be on the admins list."""
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

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")  # change for production

@app.context_processor
def inject_globals():
    return {"APP_NAME": APP_NAME}

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = load_users_from_crew()
        uname = request.form.get("username","").strip().lower().replace(" ", "")
        pwd = request.form.get("password","").strip()
        user = users.get(uname)
        if user and pwd == user["password"]:
            session["user"] = {"username": uname, "name": user["name"]}
            return redirect(request.args.get("next") or url_for("home"))
        flash("Invalid credentials. Tip: default password is username + 3865.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/admin", methods=["GET","POST"])
@login_required
@admin_only
def admin():
    msg = None
    if request.method == "POST":
        kind = request.form.get("kind")
        file = request.files.get("file")

        if kind == "admins":
            # textarea named "admins" containing one username per line
            raw = request.form.get("admins", "")
            new_admins = [line for line in raw.splitlines()]
            save_admins(new_admins)
            msg = "Admin user list updated."
        elif file and kind in {"crew","equipment"}:
            path = CREW_CSV if kind == "crew" else EQUIP_CSV
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            file.save(path)
            msg = f"Uploaded and replaced {path.name}."
        else:
            msg = "No file selected or invalid kind."

    users = load_users_from_crew()
    equip = load_equipment_by_appliance()
    return render_template("admin.html", users=users, equipment=equip, message=msg, load_admins=load_admins)

@app.route("/checklists/post-job", methods=["GET","POST"])
@login_required
def post_job_checklist():
    users = load_users_from_crew()
    crew_choices = [{"username":u, "name":info["name"]} for u,info in sorted(users.items(), key=lambda x: x[1]["name"])]
    drivers = crew_choices  # all crew can be drivers by default
    appliances = ["Pumper", "Tanker 1", "Tanker 2", "FCV", "Quick Fill", "Trailer", "Collar Tank"]
    equipment_by_appliance = load_equipment_by_appliance()

    if request.method == "POST":
        data = {
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "date": request.form.get("date"),
            "driver": request.form.get("driver"),
            "crew": request.form.getlist("crew"),
            "job_type": request.form.get("job_type"),
            "appliance": request.form.get("appliance"),
            "confirmed_ready": "confirmed_ready" in request.form
        }
        # collect equipment rows
        equip_rows = []
        for key in request.form:
            if key.startswith("equip__"):
                eq_name = key.split("__", 1)[1]
                status = request.form.get(key)
                note = request.form.get(f"note__{eq_name}", "").strip()
                equip_rows.append({"equipment_name": eq_name, "status": status, "note": note})

        # Note-required validation
        must_note = {"Note for follow-up", "Tagged out for repairs", "Damaged or Lost"}
        for row in equip_rows:
            if row["status"] in must_note and not row["note"]:
                flash(f'Note required for "{row["equipment_name"]}" when status is "{row["status"]}".', "error")
                return render_template(
                    "post_job.html",
                    drivers=drivers, crew=crew_choices, appliances=appliances,
                    equipment_by_appliance=equipment_by_appliance,
                    status_options=STATUS_OPTIONS,
                    now=datetime.now()
                )

        # Guard: no equipment captured
        if not equip_rows:
            flash("No equipment items were captured for this appliance. Check your equipment list CSV or choose a different appliance.", "error")
            return render_template(
                "post_job.html",
                drivers=drivers, crew=crew_choices, appliances=appliances,
                equipment_by_appliance=equipment_by_appliance,
                status_options=STATUS_OPTIONS,
                now=datetime.now()
            )

        # Save to CSV (one row per equipment)
        SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"post_job_{int(time.time())}.csv"
        path = SUBMISSIONS_DIR / filename
        rows = []
        for row in equip_rows:
            rows.append({
                "submitted_at": data["submitted_at"],
                "date": data["date"],
                "driver": data["driver"],
                "crew": ";".join(data["crew"]),
                "job_type": data["job_type"],
                "appliance": data["appliance"],
                "equipment_name": row["equipment_name"],
                "status": row["status"],
                "note": row["note"],
                "confirmed_ready": data["confirmed_ready"]
            })
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        flash(f"Checklist saved: {filename}", "success")
        return redirect(url_for("post_job_checklist_success", fname=filename))

    return render_template(
        "post_job.html",
        drivers=drivers, crew=crew_choices, appliances=appliances,
        equipment_by_appliance=equipment_by_appliance,
        status_options=STATUS_OPTIONS,
        now=datetime.now()
    )

@app.route("/checklists/post-job/success")
@login_required
def post_job_checklist_success():
    fname = request.args.get("fname")
    return render_template("success.html", message=f"Saved {fname}")

@app.route("/api/equipment")
@login_required
def api_equipment():
    return jsonify(load_equipment_by_appliance())

@app.route("/checklists/maintenance-night")
@login_required
def maintenance_night():
    return render_template("placeholder.html", title="Maintenance Night Checklist")

@app.route("/checklists/weekly-maintenance")
@login_required
def weekly_maintenance():
    return render_template("placeholder.html", title="Weekly Maintenance Checklist")

@app.route('/static/<path:filename>')
def custom_static(filename):
    return send_from_directory((BASE_DIR / 'static'), filename)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
