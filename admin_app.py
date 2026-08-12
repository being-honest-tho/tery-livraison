#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TERYLIVRAISON ADMIN — application d'administration SÉPARÉE (port 8778).
Accès réservé aux comptes administrateurs : voir les réservations en
attente, les détails, valider / refuser, état du parc.
Partage la même base (delivery.db) que l'app client.
"""
import json
import os
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app import load_config, vehicle_available

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "delivery.db")
PORT = int(os.environ.get("ADMIN_PORT", "8778"))

CONFIG = load_config()

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.secret_key = CONFIG["secret_key"]


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


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            session.clear()
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def base_ctx():
    return {"current_user": current_user()}


SIDE_ADMIN = [
    {"url": "/", "label": "Réservations"},
    {"url": "/parc", "label": "Parc"},
]


def side_items(items, active_url):
    return [dict(it, active=it["url"] == active_url) for it in items]


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user() and current_user()["role"] == "admin":
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Identifiants incorrects."
        elif user["role"] != "admin":
            error = "Ce compte n'a pas les droits administrateur."
        else:
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
    return render_template("admin_login.html", error=error, **base_ctx())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@admin_required
def index():
    db = get_db()
    bookings = db.execute(
        """SELECT b.*, u.email AS user_email FROM bookings b
           LEFT JOIN users u ON u.id = b.user_id
           ORDER BY b.created_at DESC"""
    ).fetchall()
    rows = []
    for b in bookings:
        d = dict(b)
        v = db.execute("SELECT name FROM vehicles WHERE id = ?", (b["vehicle_id"],)).fetchone()
        d["vehicle_name"] = v["name"] if v else "?"
        rows.append(d)
    return render_template(
        "admin.html",
        bookings=rows,
        bookings_json=json.dumps(rows, ensure_ascii=False),
        side_items=side_items(SIDE_ADMIN, "/"),
        **base_ctx(),
    )


@app.route("/parc")
@admin_required
def parc():
    db = get_db()
    vehicles = db.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
    today = date.today().isoformat()
    veh_out = []
    for v in vehicles:
        item = dict(v)
        item["available"] = vehicle_available(v["id"], today, today)
        veh_out.append(item)
    return render_template("admin_vehicules.html", vehicles=veh_out, today=today,
                           side_items=side_items(SIDE_ADMIN, "/parc"), **base_ctx())


@app.route("/bookings/<int:booking_id>/status", methods=["POST"])
@admin_required
def booking_status(booking_id):
    status = (request.form.get("status") or "").strip()
    if status not in ("pending", "validated", "refused"):
        flash("Statut invalide.", "err")
        return redirect(url_for("index"))
    db = get_db()
    cur = db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    db.commit()
    if cur.rowcount:
        flash("Réservation #{} : statut mis à « {} ».".format(booking_id, status), "ok")
    else:
        flash("Réservation #{} introuvable.".format(booking_id), "err")
    return redirect(url_for("index"))


if __name__ == "__main__":
    from app import init_db
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=False)
