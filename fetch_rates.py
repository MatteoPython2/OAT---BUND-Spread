import json
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.worldgovernmentbonds.com/"
PAYS = {
    "france": ["france"],
    "allemagne": ["germany"],
    "espagne": ["spain"],
    "italie": ["italy"],
    "royaume-uni": ["united kingdom", "uk"],
}

response = requests.get(
    URL,
    headers={"User-Agent": "OAT-Bund-Spread/1.0"},
    timeout=30,
)
response.raise_for_status()
tables = pd.read_html(StringIO(response.text))

def normaliser(value):
    return re.sub(r"\s+", " ", str(value)).strip().lower()

table = None
col_taux = None

for candidate in tables:
    candidate.columns = [
        " ".join(map(str, col)).strip() if isinstance(col, tuple) else str(col)
        for col in candidate.columns
    ]
    for col in candidate.columns:
        nom = normaliser(col)
        if "10y" in nom or "10 year" in nom or "10-year" in nom:
            table, col_taux = candidate, col
            break
    if table is not None:
        break

if table is None:
    raise RuntimeError("Tableau des taux à 10 ans introuvable.")

def trouver_taux(aliases):
    for _, row in table.iterrows():
        ligne = " ".join(normaliser(v) for v in row.values)
        if any(alias in ligne for alias in aliases):
            match = re.search(r"-?\d+(?:[.,]\d+)?", str(row[col_taux]))
            if match:
                return float(match.group().replace(",", "."))
    raise RuntimeError(f"Taux introuvable pour : {aliases}")

data = {pays: trouver_taux(aliases) for pays, aliases in PAYS.items()}
data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

Path("data.json").write_text(
    json.dumps(data, indent=2),
    encoding="utf-8",
)
