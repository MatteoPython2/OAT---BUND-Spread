import json
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from playwright.sync_api import sync_playwright


BASE = "https://www.worldgovernmentbonds.com"

PAYS = {
    "france": "france",
    "allemagne": "germany",
    "espagne": "spain",
    "italie": "italy",
    "royaume-uni": "united-kingdom",
}

PERIODES = {
    "1_week": "1 Week",
    "1_month": "1 Month",
    "6_months": "6 Months",
    "1_year": "1 Year",
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; OAT-Bund-Spread/1.0)",
})


def recuperer_taux_10_ans(slug):
    """Récupère le taux actuel à 10 ans d'un pays."""
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
        raise RuntimeError(f"Tableau des taux introuvable pour {slug}")

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

def recuperer_serie_historique(slug):
    """Récupère les points datés du graphique historique à 10 ans."""
    page_url = f"{BASE}/bond-historical-data/{slug}/10-years/"
    page = session.get(page_url, timeout=30)
    page.raise_for_status()

    variables = re.search(
        r"var\s+jsGlobalVars\s*=\s*(\{.*?\});",
        page.text,
        re.DOTALL,
    )

    if not variables:
        raise RuntimeError(
            f"Configuration du graphique introuvable pour {slug}"
        )

    global_vars = json.loads(variables.group(1))
    endpoint = global_vars["ENDPOINT"]

    resultat = session.post(
        endpoint,
        json={"GLOBALVAR": global_vars},
        headers={"Origin": BASE},
        timeout=60,
    )
    resultat.raise_for_status()

    contenu = resultat.json().get("result", {})
    quotes = contenu.get("quote", {})

    lignes = quotes.values() if isinstance(quotes, dict) else quotes
    serie = {}

    for point in lignes:
        date = point.get("DATA_VAL")
        taux = point.get("CLOSE_VAL")

        if date and taux is not None:
            serie[date] = float(taux)

    if not serie:
        raise RuntimeError(f"Série historique vide pour {slug}")

    return serie


def recuperer_historique_pays(page, slug):
    """Lit les variations affichées sur la page historique du pays."""
    url = f"{BASE}/bond-historical-data/{slug}/10-years/"

    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Attendre que le contenu historique soit chargé
    page.wait_for_function(
        """() => {
            const texte = document.body.innerText;
            return texte.includes("1 Week") && texte.includes("Current Yield");
        }""",
        timeout=60000,
    )

    texte = " ".join(page.locator("body").inner_text().split())
    variations = {}

    for cle, libelle in PERIODES.items():
        correspondance = re.search(
            rf"{re.escape(libelle)}\s+.*?([+-]?\d+(?:[.,]\d+)?)\s*bp",
            texte,
            re.IGNORECASE,
        )

        if correspondance:
            valeur = correspondance.group(1).replace(",", ".")
            variations[cle] = float(valeur)

    periodes_manquantes = set(PERIODES) - set(variations)
    if periodes_manquantes:
        raise RuntimeError(
            f"Variations introuvables pour {slug} : "
            f"{', '.join(sorted(periodes_manquantes))}"
        )

    return variations


def recuperer_historique():
    """Récupère les historiques France/Allemagne et calcule le spread."""
    with sync_playwright() as playwright:
        navigateur = playwright.chromium.launch()
        page = navigateur.new_page()

        try:
            france = recuperer_historique_pays(page, "france")
            allemagne = recuperer_historique_pays(page, "germany")
        finally:
            navigateur.close()

    historique = {}

    for periode in PERIODES:
        historique[periode] = {
            "france": france[periode],
            "allemagne": allemagne[periode],
            "spread": round(france[periode] - allemagne[periode], 1),
        }

    return historique


# Récupération des taux actuels des cinq pays
donnees = {
    nom: recuperer_taux_10_ans(slug)
    for nom, slug in PAYS.items()
}

# Historique France/Allemagne et variation du spread
donnees["history"] = recuperer_historique()
serie_france = recuperer_serie_historique("france")
serie_allemagne = recuperer_serie_historique("germany")

dates_communes = sorted(
    serie_france.keys() & serie_allemagne.keys()
)

donnees["chart_series"] = [
    {
        "date": date,
        "france": serie_france[date],
        "allemagne": serie_allemagne[date],
    }
    for date in dates_communes
]

donnees["updated_at"] = datetime.now(timezone.utc).strftime(
    "%Y-%m-%d %H:%M UTC"
)

Path("data.json").write_text(
    json.dumps(donnees, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print("Données enregistrées dans data.json")
