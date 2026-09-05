#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeryLivraison — Location de véhicules de livraison (partout au Québec)
Flux : page vitrine -> login simple (nom + téléphone) -> formulaire de réservation.
Backend : disponibilité temps réel, chatbot IA (Hermes API 8642),
comptes utilisateurs (sessions Flask).
"""
import json
import os
import secrets
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "delivery.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PORT = int(os.environ.get("PORT", "8777"))


def _load_local_env():
    """Charge <app_dir>/.env (KEY=VALUE, secrets SMTP etc.) sans écraser les
    variables d'environnement déjà définies. Ne loggue jamais les valeurs."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_local_env()

DEFAULT_CONFIG = {
    "secret_key": "",
    "admin_url": "http://127.0.0.1:8778",
    "hermes_api_url": "http://127.0.0.1:8642",
    "hermes_api_key": "hermes-chat-key-2026",
}

VEHICLES_SEED = [
    {"name": "Camion 1", "type": "camion", "price_per_day": 350.0, "price_2h": 100.0, "price_day": 350.0, "capacity_kg": 3500, "description": "Camion cube de livraison 3.5 t — idéal pour les meubles et gros volumes."},
    {"name": "Camion 2", "type": "camion", "price_per_day": 350.0, "price_2h": 100.0, "price_day": 350.0, "capacity_kg": 3500, "description": "Camion cube de livraison 3.5 t — idéal pour les meubles et gros volumes."},
    {"name": "Camion 3", "type": "camion", "price_per_day": 400.0, "price_2h": 100.0, "price_day": 400.0, "capacity_kg": 5000, "description": "Grand camion cube 5 t — pour les chargements lourds."},
    {"name": "Fourgonnette 1", "type": "fourgonnette", "price_per_day": 140.0, "price_2h": 70.0, "price_day": 140.0, "capacity_kg": 1200, "description": "Petit véhicule — parfaite pour les électros et petites livraisons."},
    {"name": "Fourgonnette 2", "type": "fourgonnette", "price_per_day": 140.0, "price_2h": 70.0, "price_day": 140.0, "capacity_kg": 1200, "description": "Petit véhicule — parfaite pour les électros et petites livraisons."},
]

VEHICLE_IMAGES = {
    "Camion 1": "/static/truck1.jpg",
    "Camion 2": "/static/truck2.jpg",
    "Camion 3": "/static/truck3.jpg",
    "Fourgonnette 1": "/static/van1.jpg",
    "Fourgonnette 2": "/static/van2.jpg",
}

# ── TeryLivraison — Québec (Canada) ──────────────────────────────────────
COMPANY_NAME = "TeryLivraison"
COMPANY_PHONE = "+1 450 502-8022"      # numéro d'appel affiché sur le site
COMPANY_PHONE_TEL = "+14505028022"
COMPANY_PHONE_2 = "+1 514 549-4473"    # second numéro d'appel affiché sur le site
COMPANY_PHONE_TEL_2 = "+15145494473"
COMPANY_ADDRESS = "1115 rue Villeneuve ouest"
COMPANY_EMAIL = "contact@terylivraison.com"
PRICE_2H = 70.0          # petit véhicule — location 2 heures (fallback)
PRICE_DAY = 140.0        # petit véhicule — journée complète (fallback)
PAYMENT_LABELS = {"credit_card": "Carte de crédit", "transfer": "Virement bancaire", "cash": "Espèces"}
DURATION_LABELS = {"2h": "2 heures", "journee": "Journée complète"}
EMAIL_LOG = os.path.join(BASE_DIR, "email_notif.log")


def notify_admin_email(booking_id, lines):
    """Envoie le récap de réservation par email (SMTP QQ) à l'admin.
    Actif si EMAIL_ENABLED=true + EMAIL_SMTP_PASS (dans ~/.hermes/.env).
    Ne bloque jamais la réservation (thread daemon + timeout)."""
    if os.environ.get("EMAIL_ENABLED", "").lower() != "true":
        return
    host = os.environ.get("EMAIL_SMTP_HOST", "smtp.qq.com")
    port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))
    user = os.environ.get("EMAIL_SMTP_USER", "robertomaliro@qq.com")
    pwd = os.environ.get("EMAIL_SMTP_PASS", "")
    to = os.environ.get("EMAIL_TO", "robertomaliro@qq.com")
    if not pwd:
        with open(EMAIL_LOG, "a", encoding="utf-8") as f:
            f.write("[{}] CONFIG manquante (EMAIL_SMTP_PASS)\n".format(datetime.now().isoformat()))
        return
    subject = "🚚 Nouvelle réservation TeryLivraison #{}".format(booking_id)
    try:
        import smtplib
        from email.message import EmailMessage
        m = EmailMessage()
        m["From"] = user
        m["To"] = to
        m["Subject"] = subject
        m.set_content("\n".join(lines))
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(m)
        with open(EMAIL_LOG, "a", encoding="utf-8") as f:
            f.write("[{}] OK envoyé à {}\n".format(datetime.now().isoformat(), to))
    except Exception as e:
        with open(EMAIL_LOG, "a", encoding="utf-8") as f:
            f.write("[{}] EXC {}\n".format(datetime.now().isoformat(), e))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    for key in ("hermes_api_key",):
        env_val = os.environ.get(key.upper())
        if env_val:
            cfg[key] = env_val
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return cfg


CONFIG = load_config()

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.secret_key = CONFIG["secret_key"]


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            price_per_day REAL NOT NULL,
            price_2h REAL DEFAULT 70.0,
            price_day REAL DEFAULT 140.0,
            capacity_kg INTEGER NOT NULL,
            description TEXT DEFAULT '',
            image TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            role TEXT DEFAULT 'client',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT DEFAULT '',
            license_number TEXT NOT NULL,
            vehicle_id INTEGER NOT NULL,
            cage_type TEXT NOT NULL,
            weight_kg REAL NOT NULL,
            destination TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    # colonne user_id sur une base existante
    cols = [r[1] for r in db.execute("PRAGMA table_info(bookings)")]
    if "user_id" not in cols:
        db.execute("ALTER TABLE bookings ADD COLUMN user_id INTEGER DEFAULT NULL")
    if "cage_detail" not in cols:
        db.execute("ALTER TABLE bookings ADD COLUMN cage_detail TEXT DEFAULT ''")
    # nouveaux champs formulaire
    for col, ddl in [
        ("pickup_address", "ALTER TABLE bookings ADD COLUMN pickup_address TEXT DEFAULT ''"),
        ("distance_km", "ALTER TABLE bookings ADD COLUMN distance_km REAL DEFAULT 0"),
        ("duration", "ALTER TABLE bookings ADD COLUMN duration TEXT DEFAULT '2h'"),
        ("driver_needed", "ALTER TABLE bookings ADD COLUMN driver_needed INTEGER DEFAULT 0"),
        ("payment_method", "ALTER TABLE bookings ADD COLUMN payment_method TEXT DEFAULT 'cash'"),
        ("exact_time", "ALTER TABLE bookings ADD COLUMN exact_time TEXT DEFAULT ''"),
    ]:
        if col not in cols:
            try:
                db.execute(ddl)
                cols.append(col)
            except sqlite3.OperationalError:
                pass  # ajouté en parallèle par l'autre app (admin + user partagent la base)
    # migration users : email devient optionnel (login simple nom + téléphone)
    ucols = {r[1]: r for r in db.execute("PRAGMA table_info(users)")}
    if ucols.get("email") and ucols["email"][3] == 1:  # notnull == 1 -> ancien schéma
        db.execute(
            "ALTER TABLE users RENAME TO users_old"
        )
        db.execute(
            """CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT DEFAULT '',
                role TEXT DEFAULT 'client',
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        db.execute(
            """INSERT OR IGNORE INTO users (id, email, password_hash, full_name, phone, role, created_at)
               SELECT id, email, password_hash, full_name, phone, role, created_at FROM users_old"""
        )
        db.execute("DROP TABLE users_old")
    # colonne image véhicules (base existante)
    vcols = [r[1] for r in db.execute("PRAGMA table_info(vehicles)")]
    if "image" not in vcols:
        db.execute("ALTER TABLE vehicles ADD COLUMN image TEXT DEFAULT ''")
    # tarifs par type de véhicule (petits 70/140 ; camions cube 100/350-400)
    # → AVANT le seed : une base neuve (Render) n'a pas encore ces colonnes
    vcols = [r[1] for r in db.execute("PRAGMA table_info(vehicles)")]
    added_prices = False
    if "price_2h" not in vcols:
        try:
            db.execute("ALTER TABLE vehicles ADD COLUMN price_2h REAL DEFAULT 70.0")
            added_prices = True
        except sqlite3.OperationalError:
            pass
    if "price_day" not in vcols:
        try:
            db.execute("ALTER TABLE vehicles ADD COLUMN price_day REAL DEFAULT 140.0")
            added_prices = True
        except sqlite3.OperationalError:
            pass
    if added_prices:
        db.execute("UPDATE vehicles SET price_2h = 70.0, price_day = 140.0 WHERE type = 'fourgonnette'")
        db.execute("UPDATE vehicles SET price_2h = 100.0, price_day = 400.0 WHERE type = 'camion' AND capacity_kg >= 5000")
        db.execute("UPDATE vehicles SET price_2h = 100.0, price_day = 350.0 WHERE type = 'camion' AND capacity_kg < 5000")
    # véhicules
    n = db.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    if n == 0:
        db.executemany(
            "INSERT INTO vehicles (name, type, price_per_day, price_2h, price_day, capacity_kg, description) VALUES (:name, :type, :price_per_day, :price_2h, :price_day, :capacity_kg, :description)",
            VEHICLES_SEED,
        )
    # images par défaut (fichiers locaux stables)
    for name, url in VEHICLE_IMAGES.items():
        db.execute("UPDATE vehicles SET image = ? WHERE name = ?", (url, name))
    # admin par défaut
    n = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if n == 0:
        db.execute(
            "INSERT INTO users (email, password_hash, full_name, phone, role) VALUES (?, ?, ?, ?, 'admin')",
            ("admin@kargo.com", generate_password_hash("admin123"), "Administrateur TeryLivraison", ""),
        )
    db.commit()
    db.close()


def vehicle_available(vehicle_id, start, end):
    """Un véhicule est dispo s'il n'a aucune réservation active chevauchant [start, end]."""
    db = get_db()
    row = db.execute(
        """SELECT COUNT(*) FROM bookings
           WHERE vehicle_id = ? AND status NOT IN ('cancelled', 'refused')
             AND NOT (end_date < ? OR start_date > ?)""",
        (vehicle_id, start, end),
    ).fetchone()
    return row[0] == 0


def vehicle_next_available(vehicle_id, start, end):
    """Prochaine date de disponibilité (fin de la résa qui bloque + 1 jour), ou None."""
    db = get_db()
    row = db.execute(
        """SELECT MIN(end_date) AS d FROM bookings
           WHERE vehicle_id = ? AND status NOT IN ('cancelled', 'refused')
             AND NOT (end_date < ? OR start_date > ?)""",
        (vehicle_id, start, end),
    ).fetchone()
    d = parse_date(row["d"] if row else None)
    if d:
        return (d + timedelta(days=1)).isoformat()
    return None


def parse_date(s, default=None):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user():
            session.clear()  # session périmée (compte supprimé) -> reconnexion propre
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def base_ctx():
    return {
        "current_user": current_user(),
        "company_name": COMPANY_NAME,
        "company_phone": COMPANY_PHONE,
        "company_phone_tel": COMPANY_PHONE_TEL,
        "company_phone_2": COMPANY_PHONE_2,
        "company_phone_tel_2": COMPANY_PHONE_TEL_2,
        "company_address": COMPANY_ADDRESS,
        "company_email": COMPANY_EMAIL,
    }


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", **base_ctx())


@app.route("/register", methods=["GET", "POST"])
def register():
    """Le login est unifié : un seul écran nom + téléphone (email optionnel)."""
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("reserver"))
    error = None
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        if not full_name or not phone:
            error = "Votre prénom et votre numéro de téléphone sont obligatoires."
        else:
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
            if user:
                if email:
                    clash = db.execute(
                        "SELECT id FROM users WHERE email = ? AND id != ?", (email, user["id"])
                    ).fetchone()
                    if clash:
                        error = "Cet email est déjà utilisé par un autre compte."
                    else:
                        db.execute(
                            "UPDATE users SET full_name = ?, email = ? WHERE id = ?",
                            (full_name, email, user["id"]),
                        )
                        db.commit()
                else:
                    db.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user["id"]))
                    db.commit()
                session["user_id"] = user["id"]
            else:
                cur = db.execute(
                    "INSERT INTO users (email, password_hash, full_name, phone) VALUES (?, ?, ?, ?)",
                    (email or None, generate_password_hash(secrets.token_hex(8)), full_name, phone),
                )
                db.commit()
                session["user_id"] = cur.lastrowid
            if not error:
                nxt = request.args.get("next") or url_for("reserver")
                if nxt != url_for("logout"):
                    return redirect(nxt)
                return redirect(url_for("reserver"))
    return render_template("login.html", error=error, **base_ctx())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


SIDE_USER = [
    {"url": "/reserver", "label": "Accueil"},
    {"url": "/reservations", "label": "Mes réservations"},
]


def side_items(items, active_url):
    return [dict(it, active=it["url"] == active_url) for it in items]


@app.route("/reserver")
@login_required
def reserver():
    return render_template("reserver.html", side_items=side_items(SIDE_USER, "/reserver"), **base_ctx())


@app.route("/reservations")
@login_required
def reservations():
    db = get_db()
    rows = db.execute(
        """SELECT b.*, v.name AS vehicle_name FROM bookings b
           JOIN vehicles v ON v.id = b.vehicle_id
           WHERE b.user_id = ? ORDER BY b.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    return render_template("reservations.html", bookings=[dict(r) for r in rows],
                           side_items=side_items(SIDE_USER, "/reservations"), **base_ctx())


@app.route("/admin")
def admin_redirect():
    """L'administration est une app séparée (admin_app.py, port 8778)."""
    return redirect(CONFIG.get("admin_url", "http://127.0.0.1:8778"))


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.route("/api/vehicles")
def api_vehicles():
    start = parse_date(request.args.get("start"), date.today())
    end = parse_date(request.args.get("end"), start + timedelta(days=1))
    if end < start:
        end = start
    db = get_db()
    vehicles = db.execute("SELECT * FROM vehicles WHERE active = 1 ORDER BY type, id").fetchall()
    out = []
    for v in vehicles:
        item = dict(v)
        item["available"] = vehicle_available(v["id"], start.isoformat(), end.isoformat())
        item["next_available"] = None if item["available"] else vehicle_next_available(
            v["id"], start.isoformat(), end.isoformat())
        out.append(item)
    return jsonify({"start": start.isoformat(), "end": end.isoformat(), "vehicles": out})


@app.route("/api/booking", methods=["POST"])
@login_required
def api_booking():
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    license_number = (data.get("license_number") or "").strip()
    vehicle_id = data.get("vehicle_id")
    cage_type = (data.get("cage_type") or "").strip()
    cage_detail = (data.get("cage_detail") or "").strip()
    pickup_address = (data.get("pickup_address") or "").strip()
    destination = (data.get("destination") or "").strip()
    start = parse_date(data.get("start_date"))
    end = parse_date(data.get("end_date"))
    duration = (data.get("duration") or "2h").strip()
    payment_method = (data.get("payment_method") or "cash").strip()
    exact_time = (data.get("exact_time") or "").strip()
    driver_needed = 1 if data.get("driver_needed") else 0
    try:
        weight_kg = float(data.get("weight_kg") or 0)
    except (TypeError, ValueError):
        weight_kg = -1
    try:
        distance_km = float(data.get("distance_km") or 0)
    except (TypeError, ValueError):
        distance_km = 0

    if not all([full_name, phone, license_number, vehicle_id, cage_type, destination, pickup_address, exact_time, start, end]):
        return jsonify({"error": "Tous les champs obligatoires doivent être remplis."}), 400
    if weight_kg < 0:
        return jsonify({"error": "Le poids du colis est invalide."}), 400
    if end < start:
        return jsonify({"error": "La date de fin doit être après la date de début."}), 400
    if duration == "2h" and end != start:
        return jsonify({"error": "La location de 2 heures se fait sur une seule journée. Choisissez « Journée complète » pour louer sur plusieurs jours."}), 400
    if cage_type == "Autre" and not cage_detail:
        return jsonify({"error": "Précisez le contenu de votre colis (champ obligatoire pour « Autre »)."}), 400
    if duration not in DURATION_LABELS:
        return jsonify({"error": "Durée de location invalide."}), 400
    if payment_method not in PAYMENT_LABELS:
        return jsonify({"error": "Méthode de paiement invalide."}), 400

    db = get_db()
    vehicle = db.execute("SELECT * FROM vehicles WHERE id = ? AND active = 1", (vehicle_id,)).fetchone()
    if not vehicle:
        return jsonify({"error": "Véhicule introuvable."}), 404
    if weight_kg > vehicle["capacity_kg"]:
        return jsonify({
            "error": "Le poids du colis ({:.0f} kg) dépasse la capacité du {} ({} kg). Choisissez un véhicule plus grand.".format(
                weight_kg, vehicle["name"], vehicle["capacity_kg"])
        }), 400
    if not vehicle_available(vehicle_id, start.isoformat(), end.isoformat()):
        return jsonify({"error": "Ce véhicule n'est plus disponible pour ces dates. Choisissez-en un autre."}), 409

    days = (end - start).days + 1
    price_2h = vehicle["price_2h"] if vehicle["price_2h"] is not None else PRICE_2H
    price_day = vehicle["price_day"] if vehicle["price_day"] is not None else PRICE_DAY
    if duration == "journee":
        total = round(price_day * days, 2)
    else:
        total = price_2h
    cur = db.execute(
        """INSERT INTO bookings
          (user_id, full_name, phone, email, license_number, vehicle_id, cage_type, cage_detail, weight_kg,
           pickup_address, destination, distance_km, duration, driver_needed, payment_method, exact_time,
           start_date, end_date, total_price)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session["user_id"], full_name, phone, email, license_number, vehicle_id, cage_type, cage_detail, weight_kg,
         pickup_address, destination, distance_km, duration, driver_needed, payment_method, exact_time,
         start.isoformat(), end.isoformat(), total),
    )
    db.commit()
    booking_id = cur.lastrowid

    # Notification email de l'admin (en arrière-plan, jamais bloquant)
    lines = [
        "👤 {} ({})".format(full_name, phone),
        "📧 {}".format(email or "non renseigné"),
        "🪪 Permis : {}".format(license_number),
        "🚚 {} — {}".format(vehicle["name"], DURATION_LABELS.get(duration, duration)),
        "📅 {} → {}".format(start.isoformat(), end.isoformat()),
        "🕒 Récupération : {}".format(exact_time),
        "📍 {} → {}".format(pickup_address, destination),
    ]
    if distance_km > 0:
        lines.append("📏 Distance GPS : {} km".format(distance_km))
    if driver_needed:
        lines.append("👷 Chauffeur / main d'œuvre : OUI (prix par téléphone)")
    lines.append("💳 Paiement : {} (sur place)".format(PAYMENT_LABELS.get(payment_method, payment_method)))
    lines.append("💰 Total : {} $".format(total))
    threading.Thread(target=notify_admin_email, args=(booking_id, lines), daemon=True).start()

    return jsonify({
        "ok": True,
        "booking_id": booking_id,
        "vehicle": vehicle["name"],
        "type": vehicle["type"],
        "days": days,
        "duration": duration,
        "total": total,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }), 201


# --------------------------------------------------------------------------
# GPS : géocodage (Photon/OSM) + distance temps réel (OSRM)
# --------------------------------------------------------------------------
@app.route("/api/geocode")
def api_geocode():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Adresse manquante."}), 400
    try:
        url = "https://photon.komoot.io/api/?limit=1&q=" + urllib.parse.quote(q)
        req = urllib.request.Request(url, headers={"User-Agent": "TeryLivraison/1.0 (Quebec)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        feats = body.get("features") or []
        if not feats:
            return jsonify({"error": "Adresse introuvable. Précisez la ville (ex : Montréal)."}), 404
        lon, lat = feats[0]["geometry"]["coordinates"]
        props = feats[0].get("properties", {}) or {}
        name = props.get("name") or ""
        street = props.get("street") or ""
        city = props.get("city") or props.get("state") or ""
        label = ", ".join(x for x in [street or name, city] if x)
        return jsonify({"ok": True, "lat": lat, "lon": lon, "name": label})
    except urllib.error.HTTPError as e:
        return jsonify({"error": "Service de géolocalisation indisponible ({}).".format(e.code)}), 502
    except Exception:
        return jsonify({"error": "Service de géolocalisation indisponible. Réessayez."}), 502


@app.route("/api/distance")
def api_distance():
    try:
        f_lat = float(request.args.get("from_lat"))
        f_lon = float(request.args.get("from_lon"))
        t_lat = float(request.args.get("to_lat"))
        t_lon = float(request.args.get("to_lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "Coordonnées invalides."}), 400
    try:
        url = "https://router.project-osrm.org/route/v1/driving/{},{};{},{}?overview=false&alternatives=false".format(
            f_lon, f_lat, t_lon, t_lat)
        req = urllib.request.Request(url, headers={"User-Agent": "TeryLivraison/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("code") != "Ok" or not body.get("routes"):
            return jsonify({"error": "Aucun itinéraire trouvé entre ces deux adresses."}), 404
        route = body["routes"][0]
        km = route["distance"] / 1000.0
        minutes = route["duration"] / 60.0
        return jsonify({"ok": True, "km": round(km, 1), "minutes": round(minutes)})
    except urllib.error.HTTPError as e:
        return jsonify({"error": "Service de calcul de distance indisponible ({}).".format(e.code)}), 502
    except Exception:
        return jsonify({"error": "Service de calcul de distance indisponible. Réessayez."}), 502


# --------------------------------------------------------------------------
# Chatbot (proxy -> Hermes API 8642)
# --------------------------------------------------------------------------
def build_system_prompt():
    db = get_db()
    today = date.today().isoformat()
    vehicles = db.execute("SELECT * FROM vehicles WHERE active = 1 ORDER BY type, id").fetchall()
    lines = []
    for v in vehicles:
        p2h = v["price_2h"] if v["price_2h"] is not None else PRICE_2H
        pday = v["price_day"] if v["price_day"] is not None else PRICE_DAY
        if vehicle_available(v["id"], today, today):
            lines.append("- {} ({}): DISPONIBLE aujourd'hui, capacité {} kg — {} $/2 h, {} $/jour".format(
                v["name"], v["type"], v["capacity_kg"], p2h, pday))
        else:
            nxt = vehicle_next_available(v["id"], today, today)
            lines.append("- {} ({}): occupé aujourd'hui, sera dispo le {}, capacité {} kg — {} $/2 h, {} $/jour".format(
                v["name"], v["type"], nxt or "?", v["capacity_kg"], p2h, pday))
    availability = "\n".join(lines)
    return (
        "Tu es l'assistant du site de location de véhicules de livraison TeryLivraison, au Québec (Canada). "
        "Tu connais la disponibilité des véhicules en temps réel et tu GUIDES le client pas à pas pour remplir "
        "sa réservation. Tu réponds UNIQUEMENT sur ce sujet.\n"
        "INFOS À CONNAÎTRE :\n"
        "- Entreprise : TeryLivraison — location de véhicules de livraison, partout au Québec (Québec, Montréal, "
        "Trois-Rivières, Sherbrooke, Granby).\n"
        "- Coordonnées : téléphone {phone}, adresse : {address}, courriel : {email}.\n"
        "- Tarifs par type de véhicule : petits véhicules (fourgonnettes) = 70 $/2 h, 140 $/journée ; camions cube = "
        "100 $/2 h, 350 $/journée (400 $ pour le camion 5 t).\n"
        "- GUIDE DU FORMULAIRE (6 étapes) :\n"
        "  1. Le véhicule : choisir un camion/fourgonnette disponible, la date de début, la date de fin et la durée "
        "(2 heures = UNE SEULE journée, date de fin verrouillée ; journée complète = plusieurs jours possibles), "
        "puis la date et l'heure de récupération du véhicule.\n"
        "  2. Identité & permis : prénom, téléphone, email (optionnel) et numéro de permis de conduire.\n"
        "  3. Le colis (chargement) : type (meubles, électros, autre), précision si « autre », et poids en kg "
        "(ne doit pas dépasser la capacité du véhicule).\n"
        "  4. Livraison & distance : adresse de départ (où le client est) et destination. La distance se calcule "
        "automatiquement (GPS).\n"
        "  5. Chauffeur ou main d'œuvre : le client peut venir chercher le véhicule lui-même ou cocher l'option "
        "chauffeur/main d'œuvre (prix à discuter par téléphone au {phone} ou au {phone2}).\n"
        "  6. Paiement : la méthode de paiement : carte de crédit, virement bancaire ou espèces (paiement sur place). Il faut aussi "
        "accepter les 2 conditions : rendre le véhicule avec le même niveau de carburant qu'au départ, et être "
        "responsable des réparations en cas d'accident.\n"
        "- Pour accéder au formulaire, le client entre son prénom et son numéro de téléphone sur la page de connexion "
        "(email optionnel) — pas de mot de passe.\n"
        "- RÉSERVATION PAR TÉLÉPHONE : si le client veut réserver par téléphone, réponds-lui textuellement : "
        "« Passez votre réservation par téléphone : appelez le {phone} ou le {phone2}. Notre équipe prend votre réservation et vous "
        "confirme le prix. » Tu peux aussi lui rappeler qu'il peut réserver en ligne via le formulaire.\n"
        "- Le colis (le chargement) peut être des meubles, des électros, etc. Le poids du colis ne doit pas "
        "dépasser la capacité du véhicule.\n"
        "- Le site calcule la distance entre l'adresse de départ et la destination (GPS).\n"
        "- Disponibilités d'aujourd'hui ({}) :\n{}\n"
        "Réponds en français, de façon courte et utile. Guide le client étape par étape quand il demande de l'aide "
        "pour réserver. Propose le téléphone ({phone} ou {phone2}) pour le chauffeur ou la confirmation."
        .format(today, availability, phone=COMPANY_PHONE, phone2=COMPANY_PHONE_2, address=COMPANY_ADDRESS, email=COMPANY_EMAIL)
    )


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "").strip()
    if not message:
        return jsonify({"error": "Message vide."}), 400

    api_url = CONFIG["hermes_api_url"].rstrip("/")
    auth = "Bearer {}".format(CONFIG["hermes_api_key"])
    system_prompt = build_system_prompt()

    try:
        if not session_id:
            title = "kargo_chat_{}".format(int(time.time() * 1000))
            req = urllib.request.Request(
                api_url + "/api/sessions",
                data=json.dumps({"title": title}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": auth},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            session_id = body.get("session", {}).get("id")
            if not session_id:
                return jsonify({"error": "Impossible de créer la session de chat."}), 502

        req = urllib.request.Request(
            api_url + "/api/sessions/{}/chat".format(session_id),
            data=json.dumps({"message": message, "system_message": system_prompt}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": auth},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        reply = body.get("message", {}).get("content")
        if not reply:
            return jsonify({"error": "Réponse vide de l'assistant."}), 502
        return jsonify({"reply": reply, "session_id": session_id})
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        return jsonify({"error": "Erreur assistant ({}). {}".format(e.code, detail)}), 502
    except Exception as e:
        return jsonify({"error": "Assistant indisponible pour le moment. Réessayez dans quelques instants."}), 502


# --------------------------------------------------------------------------
# Démarrage
# --------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=False)
