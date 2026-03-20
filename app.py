import os
import json
import re
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

PMU_BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_HEADERS = {
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

# ═══════════════════════
#  HEALTH CHECK
# ═══════════════════════
@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "message": "PMU Proxy actif",
        "ia": bool(ANTHROPIC_KEY)
    })

# ═══════════════════════
#  PROGRAMME PMU
# ═══════════════════════
@app.route("/programme")
def programme():
    date_param = request.args.get("date", "")
    try:
        dt = datetime.strptime(date_param, "%Y-%m-%d") if date_param else datetime.today()
        date_pmu = dt.strftime("%d%m%Y")
    except:
        return jsonify({"error": "Format invalide", "courses": []})
    try:
        resp = requests.get(
            f"{PMU_BASE}/programme/{date_pmu}",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        if resp.status_code != 200:
            return jsonify({"error": f"PMU {resp.status_code}", "courses": []})
        return jsonify({"date": dt.strftime("%Y-%m-%d"), "courses": extraire_courses(resp.json())})
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
                courses.append({
                    "reunion": f"R{nr}", "course": f"C{nc}",
                    "hippo": hippo, "partants": partants,
                    "type": type_c, "quinte": quinte, "libelle": libelle
                })
    except Exception as e:
        print(f"Erreur extraction PMU: {e}")
    return courses

# ═══════════════════════
#  IA — PRONOSTICS
# ═══════════════════════
@app.route("/ia/pronostics", methods=["POST"])
def ia_pronostics():
    if not ANTHROPIC_KEY:
        return jsonify({"error": "Cle API manquante"}), 500
    body = request.get_json() or {}
    course = body.get("course", "")
    hippo = body.get("hippo", "")
    date = body.get("date", datetime.today().strftime("%Y-%m-%d"))

    prompt = (
        f"Tu es un expert PMU. Nous sommes le {date}. "
        f"Cherche sur internet les pronostics du Quinte+ pour la course {course} a l hippodrome {hippo}. "
        "Consulte Geny.com, Paris-Turf, ZEturf, Equidia et Turf-fr. "
        "Pour chaque site donne les 8 chevaux selectionnes par leur numero. "
        "Reponds uniquement avec ce JSON sans aucun autre texte: "
        '{"sites":[{"nom":"Geny","numeros":[1,2,3,4,5,6,7,8]},{"nom":"Paris-Turf","numeros":[1,2,3,4,5,6,7,8]},{"nom":"ZEturf","numeros":[1,2,3,4,5,6,7,8]},{"nom":"Equidia","numeros":[1,2,3,4,5,6,7,8]},{"nom":"Turf-fr","numeros":[1,2,3,4,5,6,7,8]}]}'
    )

    try:
        result = call_claude_with_search(prompt)
        data = extract_json(result)
        if not data or "sites" not in data:
            return jsonify({"error": "Donnees non trouvees", "raw": result[:200]}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════
#  IA — STATS
# ═══════════════════════
@app.route("/ia/stats", methods=["POST"])
def ia_stats():
    if not ANTHROPIC_KEY:
        return jsonify({"error": "Cle API manquante"}), 500
    body = request.get_json() or {}
    course = body.get("course", "")
    hippo = body.get("hippo", "")
    nb = body.get("nb", 16)
    date = body.get("date", datetime.today().strftime("%Y-%m-%d"))

    prompt = (
        f"Tu es un expert PMU. Nous sommes le {date}. "
        f"Cherche sur Geny.com et Paris-Turf les fiches des {nb} partants de la course {course} a {hippo}. "
        "Pour chaque cheval donne: numero, nom du cheval, nom du jockey, nom de l ecurie ou entraineur, "
        "pourcentage de victoires, pourcentage de places dans le top 3, forme sur 5 (5=excellent), poids handicap. "
        "Reponds uniquement avec ce JSON sans aucun autre texte: "
        '{"partants":[{"num":1,"cheval":"Nom","cavalier":"Jockey","ecurie":"Ecurie","vicPct":20,"place3Pct":45,"forme":4,"poidsH":0}]}'
    )

    try:
        result = call_claude_with_search(prompt)
        data = extract_json(result)
        if not data or "partants" not in data:
            return jsonify({"error": "Donnees non trouvees", "raw": result[:200]}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════
#  IA — EXTRACTION TEXTE
# ═══════════════════════
@app.route("/ia/extraire", methods=["POST"])
def ia_extraire():
    if not ANTHROPIC_KEY:
        return jsonify({"error": "Cle API manquante"}), 500
    body = request.get_json() or {}
    texte = body.get("texte", "")[:3000]
    type_e = body.get("type", "prono")
    site = body.get("site", "")

    if type_e == "prono":
        prompt = (
            f"Analyse ce texte du site {site} et extrait les numeros des chevaux selectionnes pour le Quinte+. "
            "Reponds uniquement avec ce JSON: "
            '{"numeros":[1,2,3,4,5,6,7,8],"commentaire":"explication"} '
            f"Texte: {texte}"
        )
    else:
        prompt = (
            "Analyse ce texte et extrait les statistiques du cheval, jockey ou ecurie. "
            "Reponds uniquement avec ce JSON: "
            '{"num":0,"cheval":"","cavalier":"","ecurie":"","vicPct":0,"place3Pct":0,"forme":3,"poidsH":0,"notes":"resume"} '
            f"Texte: {texte}"
        )

    try:
        result = call_claude_simple(prompt)
        data = extract_json(result)
        if not data:
            return jsonify({"error": "Extraction echouee", "raw": result[:200]}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════
#  HELPERS
# ═══════════════════════
def call_claude_with_search(prompt):
    headers = {**ANTHROPIC_HEADERS, "x-api-key": ANTHROPIC_KEY}
    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        "messages": [{"role": "user", "content": prompt}]
    }
    resp = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    print(f"STATUS: {resp.status_code}")
    print(f"RESPONSE: {resp.text[:500]}")
    data = resp.json()
    if resp.status_code != 200:
        raise Exception(f"Anthropic {resp.status_code}: {data.get('error', {}).get('message', str(data))}")
    texts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    if not texts:
        raise Exception("Aucune reponse texte")
    return texts[-1]
        
        

def call_claude_simple(prompt):
    """Appel Claude sans recherche web"""
    headers = {**ANTHROPIC_HEADERS, "x-api-key": ANTHROPIC_KEY}
    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }
    resp = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=30)
    data = resp.json()
    if resp.status_code != 200:
        raise Exception(f"Anthropic {resp.status_code}: {data.get('error', {}).get('message', str(data))}")
    return data["content"][0]["text"]

def extract_json(text):
    """Extrait le premier objet JSON valide d un texte"""
    text = text.strip()
    # Retirer les balises markdown
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    # Chercher un objet JSON
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass
    # Essayer de parser directement
    try:
        return json.loads(text)
    except:
        return None

port = int(os.environ.get("PORT", 8080))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
    
