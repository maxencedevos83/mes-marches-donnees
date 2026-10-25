"""Historique des prix des carburants en France, station par station.

Source : fichiers annuels officiels de prix-carburants.gouv.fr (donnees.roulez-eco.fr).
Sortie (dans le dossier donné en argument) :
  fr/s/<id>.json   historique d'une station sur 12 mois glissants
                   {"id","d0","fin","f":{carburant:[jour,prix,jour,prix,...]}}
                   jour = nombre de jours depuis d0, prix en millièmes d'euro ;
                   seuls les changements sont listés, le dernier couple marque la fin connue.
  fr/d/<dep>.json  tendances par département : {"maj","s":{id:{carburant:[prix J-7, prix J-30]}}}
  fr/index.json    date de mise à jour et nombre de stations
"""
import datetime as dt
import io
import json
import os
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

FUELS = {"1": "diesel", "2": "sp95", "3": "e85", "4": "lpg", "5": "e10", "6": "sp98"}
FUELS_BY_NAME = {"Gazole": "diesel", "SP95": "sp95", "E85": "e85", "GPLc": "lpg", "E10": "e10", "SP98": "sp98"}
WINDOW_DAYS = 366
STALE_DAYS = 10  # au-delà, on considère que la station ne vend plus ce carburant
URL = "https://donnees.roulez-eco.fr/opendata/annee/{}"


def download(year):
    req = urllib.request.Request(URL.format(year), headers={"User-Agent": "mes-marches-donnees/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    return z.open(z.namelist()[0])


def parse_date(s):
    s = (s or "").strip().replace(" ", "T")
    try:
        return dt.datetime.fromisoformat(s[:19])
    except ValueError:
        return None


def dep_of(cp):
    cp = (cp or "").strip()
    if cp.startswith("97") or cp.startswith("98"):
        return cp[:3]
    return cp[:2] if len(cp) >= 2 else "xx"


def read_year(stream, start, stations):
    """Ajoute à `stations` les relevés (date, prix) postérieurs à `start`."""
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag != "pdv":
            continue
        sid = el.get("id")
        st = stations.setdefault(sid, {"cp": el.get("cp"), "f": {}})
        st["cp"] = el.get("cp") or st["cp"]
        for p in el.findall("prix"):
            key = FUELS.get(p.get("id")) or FUELS_BY_NAME.get(p.get("nom"))
            when = parse_date(p.get("maj"))
            try:
                val = float(p.get("valeur"))
            except (TypeError, ValueError):
                continue
            if not key or not when or val <= 0:
                continue
            if val > 100:  # ancien format en millièmes
                val /= 1000
            if when.date() < start:
                # garde le dernier prix connu avant la fenêtre pour amorcer la courbe
                prev = st.setdefault("avant", {}).get(key)
                if prev is None or when >= prev[0]:
                    st["avant"][key] = (when, val)
                continue
            st["f"].setdefault(key, []).append((when, val))
        el.clear()


def build(out_dir, today):
    start = today - dt.timedelta(days=WINDOW_DAYS)
    stations = {}
    years = sorted({start.year, today.year})
    for y in years:
        try:
            read_year(download(y), start, stations)
            print(f"année {y} lue, {len(stations)} stations", flush=True)
        except Exception as e:  # l'année précédente peut manquer en tout début d'année
            print(f"année {y} ignorée : {e}", flush=True)

    last_day = None
    for st in stations.values():
        for rows in st["f"].values():
            m = max(r[0].date() for r in rows)
            last_day = m if last_day is None or m > last_day else last_day
    if last_day is None:
        sys.exit("aucune donnée")
    d0 = last_day - dt.timedelta(days=WINDOW_DAYS - 1)

    os.makedirs(os.path.join(out_dir, "fr", "s"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "fr", "d"), exist_ok=True)
    deps = {}
    written = 0
    total_bytes = 0
    for sid, st in stations.items():
        series = {}
        trends = {}
        for key in set(st["f"]) | set(st.get("avant", {})):
            rows = sorted(st["f"].get(key, []))
            seed = st.get("avant", {}).get(key)
            # prix en vigueur en fin de chaque journée
            by_day = {}
            for when, val in rows:
                by_day[when.date()] = val
            if not by_day and not seed:
                continue
            last_seen = max(by_day) if by_day else seed[0].date()
            if (last_day - last_seen).days > STALE_DAYS:
                continue
            first = min(by_day) if by_day else d0
            cur = seed[1] if seed else None
            day = d0 if seed else max(first, d0)
            pts = []
            daily = {}
            while day <= last_seen:
                if day in by_day:
                    cur = by_day[day]
                if cur is not None:
                    daily[day] = cur
                    milli = round(cur * 1000)
                    if not pts or pts[-1] != milli:
                        pts += [(day - d0).days, milli]
                day += dt.timedelta(days=1)
            if not pts:
                continue
            end = (last_seen - d0).days
            if pts[-2] != end:
                pts += [end, pts[-1]]
            series[key] = pts
            p7 = daily.get(last_seen - dt.timedelta(days=7))
            p30 = daily.get(last_seen - dt.timedelta(days=30))
            trends[key] = [round(p7 * 1000) if p7 else None, round(p30 * 1000) if p30 else None]
        if not series:
            continue
        doc = {"id": sid, "d0": d0.isoformat(), "fin": last_day.isoformat(), "f": series}
        txt = json.dumps(doc, separators=(",", ":"))
        with open(os.path.join(out_dir, "fr", "s", f"{sid}.json"), "w") as fh:
            fh.write(txt)
        written += 1
        total_bytes += len(txt)
        deps.setdefault(dep_of(st["cp"]), {})[sid] = trends

    for dep, s in deps.items():
        with open(os.path.join(out_dir, "fr", "d", f"{dep}.json"), "w") as fh:
            json.dump({"maj": last_day.isoformat(), "s": s}, fh, separators=(",", ":"))
    with open(os.path.join(out_dir, "fr", "index.json"), "w") as fh:
        json.dump({"maj": last_day.isoformat(), "d0": d0.isoformat(), "stations": written,
                   "genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, fh)
    print(f"{written} stations écrites, {total_bytes / 1e6:.1f} Mo, {len(deps)} départements, dernier jour {last_day}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "site", dt.date.today())
