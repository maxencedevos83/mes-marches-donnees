# Mes Marchés — données

Historique des prix des carburants en France, station par station, sur 12 mois glissants.
Utilisé par l'application Android personnelle *Mes Marchés*.

- Source : [prix-carburants.gouv.fr](https://www.prix-carburants.gouv.fr/rubrique/opendata/) (fichiers annuels officiels, licence ouverte Etalab).
- Mise à jour : chaque nuit par GitHub Actions (`scripts/build_fr.py`), publiée sur la branche `data`.
- `fr/s/<id>.json` : historique d'une station (`f.<carburant>` = paires jour depuis `d0`, prix en millièmes d'euro ; seuls les changements sont listés).
- `fr/d/<département>.json` : prix de chaque station 7 et 30 jours avant la dernière date.
