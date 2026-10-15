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


def recuperer_historique_pays(page, slug):
    """Récupère les variations en points de base sur la page historique."""
    url = f"{BASE}/bond-historical-data/{slug}/10-years/"

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.locator("#title-yield-range").wait_for(
        state="visible",
        timeout=60000,
    )

    tableau_historique = None

    for tableau in page.locator("table").all():
        texte = " ".join(tableau.inner_text().split())

        if all(libelle in texte for libelle in PERIODES.values()):
            tableau_historique = tableau
            break

    if tableau_historique is None:
        raise RuntimeError(f"Tableau historique introuvable pour {slug}")

    variations = {}

    for ligne in tableau_historique.locator("tr").all():
        texte_ligne = " ".join(ligne.inner_text().split())

        for cle, libelle in PERIODES.items():
            if libelle not in texte_ligne:
                continue

            correspondance = re.search(
                rf"{re.escape(libelle)}\s+([+-]?\d+(?:\.\d+)?)\s*bp",
                texte_ligne,
                re.IGNORECASE,
            )

            if correspondance:
                variations[cle] = float(correspondance.group(1))

    periodes_manquantes = set(PERIODES) - set(variations)
    if periodes_manquantes:
        raise RuntimeError(
            f"Variations manquantes pour {slug} : "
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

donnees["updated_at"] = datetime.now(timezone.utc).strftime(
    "%Y-%m-%d %H:%M UTC"
)

Path("data.json").write_text(
    json.dumps(donnees, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print("Données enregistrées dans data.json")
