# Referential fixtures

Small **real** extracts of the five IDFM Opendatasoft datasets used by the
referential exporter (downloaded on 2026-09-27), limited to seven hubs
(zones de correspondance):

| Hub id | Name | Why |
|---|---|---|
| 474151 | Châtelet - Les Halles | RER only, one stop area |
| 71264 | Châtelet | metro + a bus stop area (excluded unless BUS is selected) |
| 71410 | Gare du Nord | metro, RER, Transilien, two TER lines both labelled "TER" |
| 71517 | La Défense | metro, RER, Transilien, tram, three stop areas |
| 66403 | Les Ambassadeurs / Norton | bus only |
| 73848, 73849 | Funiculaire de Montmartre (top, bottom) | funicular, plus bus stop areas |

Every record of `zones-d-arrets`, `arrets`, `arrets-lignes` and
`referentiel-des-lignes` that belongs to these hubs is kept, so the extracts are
consistent (every reference resolves).

Licences (see the README of the repository): `zones-de-correspondance`,
`zones-d-arrets` and `arrets` are under Licence Ouverte 2.0 (Etalab);
`arrets-lignes` and `referentiel-des-lignes` are under ODbL. Source:
Île-de-France Mobilités, https://data.iledefrance-mobilites.fr.
