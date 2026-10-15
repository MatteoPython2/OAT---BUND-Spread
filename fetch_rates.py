import json
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

BASE = "https://www.worldgovernmentbonds.com"
PAYS = {
    "france": "france",
    "allemagne": "germany",
    "espagne": "spain",
    "italie": "italy",
    "royaume-uni": "united-kingdom",
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; OAT-Bund-Spread/1.0)",
})

def recuperer_taux_10_ans(slug):
    page_url = f"{BASE}/country/{slug}/"
    page = session.get(page_url, timeout=30)
    page.raise_for_status()

    symbole = re.search(r'"SYMBOL"\s*:\s*"([^"]+)"', page.text)
    if not symbole:
        raise RuntimeError(f"Symbole du pays introuvable : {slug}")

    payload = {
        "GLOBALVAR": {
            "JS_VARIABLE": "jsGlobalVars",
            "FUNCTION": "Country",
            "DOMESTIC": True,
            "ENDPOINT": f"{BASE}/wp-json/country/v1/historical",
            "DATE_RIF": "2099-12-31",
            "OBJ": None,
            "COUNTRY1": {"SYMBOL": symbole.group(1)},
            "COUNTRY2": None,
            "OBJ1": None,
            "OBJ2": None,
        }
    }

    resultat = session.post(
        f"{BASE}/wp-json/country/v1/main",
        json=payload,
        headers={"Origin": BASE},
        timeout=30,
    )
    resultat.raise_for_status()

    html_tableau = resultat.json().get("mainTable")
    if not html_tableau:
        raise RuntimeError(f"Tableau introuvable pour {slug}")

    for tableau in pd.read_html(StringIO(html_tableau)):
        for ligne in tableau.itertuples(index=False, name=None):
            cellules = [str(cellule).strip() for cellule in ligne]

            for index, cellule in enumerate(cellules):
                if re.search(r"\b10\s*years?\b", cellule, re.IGNORECASE):
                    if index + 1 >= len(cellules):
                        continue

                    valeur = cellules[index + 1].replace(",", ".")
                    nombre = re.search(r"-?\d+(?:\.\d+)?", valeur)
                    if nombre:
                        return float(nombre.group())

    raise RuntimeError(f"Taux à 10 ans introuvable pour {slug}")

donnees = {
    nom: recuperer_taux_10_ans(slug)
    for nom, slug in PAYS.items()
}
donnees["updated_at"] = datetime.now(timezone.utc).strftime(
    "%Y-%m-%d %H:%M UTC"
)

Path("data.json").write_text(
    json.dumps(donnees, indent=2),
    encoding="utf-8",
)
