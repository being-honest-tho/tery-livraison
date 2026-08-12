#!/usr/bin/env python3
"""Check UI copy TeryLivraison (vitrine + formulaire).

Vérifie : titre « Livraison partout au Québec » + badge retiré, aucun « cage »
visible (remplacé par « colis »), section 6 = « Paiement », date/heure de
récupération côte à côte juste sous le choix de durée, pas de débordement,
pas d'erreur JS. Usage : /usr/bin/python3 check_ui_copy.py (apps 8777/8778 up).
"""
import urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8777"
PHONE = "+15145559876"
R = []


def check(label, ok, extra=""):
    R.append(f"{'PASS' if ok else 'FAIL'}  {label}{('  | ' + extra) if extra else ''}")


for port, path in [("8777", "/"), ("8778", "/login")]:
    try:
        code = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=6).status
        check(f"app {port} HTTP {code}", code == 200)
    except Exception as e:
        check(f"app {port} up", False, str(e)[:60])

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))

    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(1500)
    h1 = pg.evaluate("document.querySelector('.hero-title').textContent.replace(/\\s+/g,' ').trim()")
    check("H1 = « Livraison partout au Québec »", h1 == "Livraison partout au Québec", h1)
    check("badge « Entreprise de livraison » retiré", not pg.evaluate("!!document.querySelector('.hero-brand small')"))

    pg.goto(BASE + "/login?next=/reserver", wait_until="domcontentloaded")
    pg.wait_for_timeout(800)
    pg.fill("#full_name", "Verify UI")
    pg.fill("#phone", PHONE)
    pg.click("button[type=submit]")
    pg.wait_for_url("**/reserver", timeout=15000)
    pg.wait_for_timeout(1500)

    no_cage = pg.evaluate("[...document.querySelectorAll('body *')].some(e => e.children.length===0 && e.tagName!=='SCRIPT' && e.tagName!=='STYLE' && /cage/i.test(e.textContent||''))")
    check("aucun texte « cage » visible (formulaire)", not no_cage)
    titles = pg.evaluate("[...document.querySelectorAll('.form-section-title')].map(t => t.textContent.replace(/\\d+/g,'').trim())")
    check("section 6 = « Paiement »", titles[-1] == "Paiement", " | ".join(titles))
    geo = pg.evaluate("""(() => {
      const d = document.getElementById('pickup_date').getBoundingClientRect();
      const t = document.getElementById('pickup_time').getBoundingClientRect();
      const dur = document.querySelector('#durHint').getBoundingClientRect();
      return {sameRow: Math.abs(d.top - t.top) < 6, sideBySide: d.left !== t.left,
              belowDur: d.top >= dur.bottom - 2, dTop: Math.round(d.top), tTop: Math.round(t.top)};
    })()""")
    check("date + heure côte à côte, même rangée", geo["sameRow"] and geo["sideBySide"], f"tops {geo['dTop']} vs {geo['tTop']}")
    check("champs récup juste SOUS la durée", geo["belowDur"])
    ovf = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    check("pas de débordement horizontal", ovf)
    check("aucune erreur JS", not errs, "; ".join(errs))
    ctx.close()
    b.close()

print("\n".join(R))
bad = sum(1 for r in R if r.startswith("FAIL"))
print(f"\n== {len(R) - bad} / {len(R)} PASS ==" if not bad else f"\n== {bad} ÉCHEC(S) ==")
