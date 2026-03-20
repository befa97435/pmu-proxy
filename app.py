import os
import json
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

PMU_BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "PMU Proxy actif", "ia": bool(ANTHROPIC_KEY)})

@app.route("/programme")
def programme():
    date_param = request.args.get("date", "")
    try:
        dt = datetime.strptime(date_param, "%Y-%m-%d") if date_param else datetime.today()
        date_pmu = dt.strftime("%d%m%Y")
    except:
        return jsonify({"error": "Format invalide", "courses": []})
    try:
        resp = requests.get(f"{PMU_BASE}/programme/{date_pmu}", timeout=10,
                           headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        if resp.status_code != 200:
            return jsonify({"error": f"PMU {resp.status_code}", "courses": []})
        courses = extraire_courses(resp.json())
        return jsonify({"date": dt.strftime("%Y-%m-%d"), "courses": courses})
    except Exception as e:
        return jsonify({"error": str(e), "courses": []})

def extraire_courses(data):
    courses = []
    try:
        for reunion in data.get("programme", {}).get("reunions", []):
            nr = reunion.get("numOfficiel", reunion.get("numReunion", "?"))
            hippo = reunion.get("hippodrome", {}).get("libelleCourt", "")
            disc = (reunion.get("disciplinesMeres") or ["plat"])[0].lower()
            type_c = "trot" if "trot" in disc else "obstacle" if any(x in disc for x in ["obstacle","haies","cross"]) else "plat"
            for c in reunion.get("courses", []):
                nc = c.get("numOrdre", c.get("numCourse", "?"))
                partants = c.get("nombreDeclaresPartants", 0)
                libelle = c.get("libelle", "")
                quinte = any("quinte" in str(p.get("codePari","")).lower() for p in c.get("paris",[]))
                if "quinté" in libelle.lower() or "quinte" in libelle.lower():
                    quinte = True
                courses.append({"reunion": f"R{nr}", "course": f"C{nc}", "hippo": hippo,
                               "partants": partants, "type": type_c, "quinte": quinte, "libelle": libelle})
    except Exception as e:
        print(f"Erreur: {e}")
    return courses

@app.route("/ia/pronostics", methods=["POST"])
def ia_pronostics():
    if not ANTHROPIC_KEY:
        return jsonify({"error": "Cle API manquante"}), 500
    body = request.get_json() or {}
    course = body.get("course", "")
    hippo = body.get("hippo", "")
    date = body.get("date", datetime.today().strftime("%Y-%m-%d"))
    prompt = (f"Expert PMU. Date: {date}. Recherche pronostics Quinte+ "
              f"course {course} hippodrome {hippo}. "
              "Sites: Geny.com, Paris-Turf, ZEturf, Equidia, Turf-fr. "
              "Donne 8 chevaux par site. "
              'JSON: {"sites":[{"nom":"Geny","numeros":[1,2,3,4,5,6,7,8]},'
              '{"nom":"Paris-Turf","numeros":[1,2,3,4,5,6,7,8]},'
              '{"nom":"ZEturf","numeros":[1,2,3,4,5,6,7,8]},'
              '{"nom":"Equidia","numeros":[1,2,3,4,5,6,7,8]},'
              '{"nom":"Turf-fr","numeros":[1,2,3,4,5,6,7,8]}]}')
    try:
        result = call_claude_web(prompt)
        clean = result.replace("```json","").replace("```","").strip()
        # Chercher le JSON dans la réponse
        import re
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = json.loads(clean)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e), "details": result if 'result' in dir() else ""}), 500

@app.route("/ia/stats", methods=["POST"])
def ia_stats():
    if not ANTHROPIC_KEY:
        return jsonify({"error": "Cle API manquante"}), 500
    body = request.get_json() or {}
    course = body.get("course", "")
    hippo = body.get("hippo", "")
    nb = body.get("nb", 16)
    date = body.get("date", datetime.today().strftime("%Y-%m-%d"))
    prompt = (f"Expert PMU. Date: {date}. Recherche fiches partants "
              f"course {course} hippodrome {hippo}. "
              f"Geny.com et Paris-Turf, {nb} chevaux. "
              "Nom, jockey, ecurie, stats victoires, forme. "
              '{"partants":[{"num":1,"cheval":"Nom","cavalier":"Jockey",'
              '"ecurie":"Ecurie","vicPct":20,"place3Pct":45,"forme":4,"poidsH":0}]}')
    try:
        result = call_claude_web(prompt)
        clean = result.replace("```json","").replace("```","").strip()
        import re
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = json.loads(clean)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e), "details": result if 'result' in dir() else ""}), 500

@app.route("/ia/extraire", methods=["POST"])
def ia_extraire():
    if not ANTHROPIC_KEY:
        return jsonify({"error": "Cle API manquante"}), 500
    body = request.get_json()
    texte = body.get("texte", "")[:3000]
    type_e = body.get("type", "prono")
    site = body.get("site", "")
    if type_e == "prono":
        prompt = (f"Analyse texte site {site}, extrait numeros chevaux Quinte+. "
                  '{"numeros":[1,2,3,4,5,6,7,8],"commentaire":"..."} Texte: ' + texte)
    else:
        prompt = ('Analyse fiche cheval/jockey/ecurie, extrait stats. '
                  '{"num":0,"cheval":"","cavalier":"","ecurie":"","vicPct":0,"place3Pct":0,"forme":3,"poidsH":0,"notes":"..."} Texte: ' + texte)
    try:
        result = call_claude(prompt)
        data = json.loads(result.replace("```json","").replace("```","").strip())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def call_claude_web(prompt):
    resp = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
              "tools": [{"type": "web_search_20250305", "name": "web_search"}],
              "messages": [{"role": "user", "content": prompt}]}, timeout=30)
    data = resp.json()
    texts = [b for b in data.get("content", []) if b.get("type") == "text"]
    if not texts: raise Exception("Pas de reponse")
    return texts[-1]["text"]

def call_claude(prompt):
    resp = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
              "messages": [{"role": "user", "content": prompt}]}, timeout=30)
    return resp.json()["content"][0]["text"]

port = int(os.environ.get("PORT", 8080))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
