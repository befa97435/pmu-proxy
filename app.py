from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

PMU_BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"

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
    except Exception:
        return jsonify({"error": "Format invalide. Utilisez YYYY-MM-DD"}), 400

    url = f"{PMU_BASE}/programme/{date_pmu}"
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })
        if resp.status_code != 200:
            return jsonify({"error": f"PMU a répondu {resp.status_code}", "courses": []}), 200

        data = resp.json()
        courses = extraire_courses(data)
        return jsonify({"date": dt.strftime("%Y-%m-%d"), "courses": courses})

    except requests.exceptions.Timeout:
        return jsonify({"error": "Timeout PMU", "courses": []}), 200
    except Exception as e:
        return jsonify({"error": str(e), "courses": []}), 200


def extraire_courses(data):
    courses = []
    try:
        reunions = data.get("programme", {}).get("reunions", [])
        for reunion in reunions:
            num_reunion = reunion.get("numOfficiel", reunion.get("numReunion", "?"))
            hippo = reunion.get("hippodrome", {}).get("libelleCourt", "—")
            discipline = reunion.get("disciplinesMeres", [""])[0] if reunion.get("disciplinesMeres") else ""
            type_map = {
                "PLAT": "plat", "TROT": "trot",
                "TROT_ATTELE": "trot", "TROT_MONTE": "trot",
                "OBSTACLE": "obstacle", "CROSS": "obstacle", "HAIES": "obstacle",
            }
            type_course = type_map.get(discipline.upper(), "plat")
            for course in reunion.get("courses", []):
                num_course = course.get("numOrdre", course.get("numCourse", "?"))
                partants = course.get("nombreDeclaresPartants", 0)
                libelle = course.get("libelle", "")
                is_quinte = False
                for p in course.get("paris", []):
                    code = str(p.get("codePari", "")).upper()
                    if "QUINTE" in code or code == "E_QUINTE":
                        is_quinte = True
                        break
                if "quinté" in libelle.lower() or "quinte" in libelle.lower():
                    is_quinte = True
                courses.append({
                    "reunion": f"R{num_reunion}",
                    "course": f"C{num_course}",
                    "hippo": hippo,
                    "partants": partants,
                    "type": type_course,
                    "quinte": is_quinte,
                    "libelle": libelle
                })
    except Exception as e:
        print(f"Erreur extraction: {e}")
    return courses


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
