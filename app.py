import os
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "PMU Proxy actif"})

@app.route("/programme")
def programme():
    date_param = request.args.get("date", "")
    try:
        if date_param:
            dt = datetime.strptime(date_param, "%Y-%m-%d")
        else:
            dt = datetime.today()
        date_pmu = dt.strftime("%d%m%Y")
    except:
        return jsonify({"error": "Format invalide", "courses": []})

    try:
        url = f"https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date_pmu}"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        courses = []
        for reunion in data.get("programme", {}).get("reunions", []):
            nr = reunion.get("numOfficiel", "?")
            hippo = reunion.get("hippodrome", {}).get("libelleCourt", "—")
            disc = (reunion.get("disciplinesMeres") or ["plat"])[0].lower()
            type_c = "trot" if "trot" in disc else "obstacle" if any(x in disc for x in ["obstacle","haies","cross"]) else "plat"
            for c in reunion.get("courses", []):
                nc = c.get("numOrdre", "?")
                partants = c.get("nombreDeclaresPartants", 0)
                libelle = c.get("libelle", "")
                quinte = any("quinte" in str(p.get("codePari","")).lower() for p in c.get("paris",[]))
                if "quinté" in libelle.lower() or "quinte" in libelle.lower():
                    quinte = True
                courses.append({"reunion": f"R{nr}", "course": f"C{nc}", "hippo": hippo, "partants": partants, "type": type_c, "quinte": quinte, "libelle": libelle})
        return jsonify({"date": dt.strftime("%Y-%m-%d"), "courses": courses})
    except Exception as e:
        return jsonify({"error": str(e), "courses": []})

port = int(os.environ.get("PORT", 8080))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
