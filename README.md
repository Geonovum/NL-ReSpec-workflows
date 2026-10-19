# NL-ReSpec-workflows

Centrale GitHub Actions workflows voor ReSpec-documenten van Geonovum en
BROprogramma. Documentrepositories (gemaakt met
[NL-ReSpec-template](https://github.com/Geonovum/NL-ReSpec-template)) bevatten
alleen twee kleine aanroepende workflows; de build-, controle- en
publicatiestappen staan hier.

Deze repository is bedoeld voor beheerders. Uitleg voor auteurs staat in de
README van [NL-ReSpec-template](https://github.com/Geonovum/NL-ReSpec-template).

## Inhoud

| Pad | Doel |
| --- | --- |
| `.github/workflows/build.yml` | Snapshot, Mermaid-normalisatie, PDF en controles (HTML, WCAG, links) |
| `.github/workflows/publish.yml` | Publicatie naar docs.geostandaarden.nl |
| `.github/workflows/visual-regression-reusable.yml` | Visuele vergelijking van snapshots |
| `.github/workflows/normalize-mermaid-svg.mjs`, `pdf.js`, `.github/mermaid-svg/` | Hulpbestanden die `build.yml` zelf ophaalt |
| `.github/actions/validate-html`, `.github/actions/check-links` | HTML- en linkcontrole, gedeeld door `build.yml` en de PR-controle van docs.geostandaarden.nl; versies staan alleen hier |
| `document-repo/.github/workflows/` | De aanroepende workflows (`main.yml`, `visual-regression.yml`) die naar documentrepos worden uitgerold |
| `.github/workflows/update-workflows.yml`, `scripts/`, `.github/repos.json` | Uitrol naar documentrepos |
| `.github/workflows/release-tag.yml` | Verplaatst de major-tag (`v1`) bij een nieuwe versietag |
| `.github/workflows/template-regression.yml`, `tests/` | Regressietests van deze workflows |
| `index.html`, `js/config.js`, `*.md`, `media/`, `snapshot.html` | Voorbeelddocument waarop de regressietests draaien |

## Gebruik in een documentrepository

Een documentrepository bevat alleen de bestanden uit
[`document-repo/.github/workflows/`](document-repo/.github/workflows/), bijvoorbeeld:

```yaml
jobs:
  build:
    uses: Geonovum/NL-ReSpec-workflows/.github/workflows/build.yml@v1
```

Hulpbestanden zoals de Mermaid-normalisatie en `pdf.js` haalt de centrale
workflow zelf op uit dezelfde versie van deze repository. Een fix hier bereikt
dus alle documentrepositories zonder dat daar iets hoeft te veranderen.

## Versies

* Elke workflowrelease krijgt een vaste tag volgens semver, bijv. `v1.0.1`.
* De tag `v1` wijst altijd naar de nieuwste `v1.x.y`. De workflow
  **"Move major version tag"** verplaatst `v1` automatisch zodra een
  nieuwe `v1.x.y`-tag gepusht wordt.
* Documentrepositories gebruiken `@v1`: niet-brekende wijzigingen
  (fixes, nieuwe controles) krijgen ze automatisch.
* Alleen bij een brekende wijziging (bijv. andere verplichte velden in
  `config.js` of andere secrets) komt er een `v2`. Dan worden de
  aanroepende workflows eenmalig uitgerold met de update-workflow hieronder.
* Terugdraaien: zet `v1` terug naar de vorige `v1.x.y`-tag.

Een nieuwe versie maken (vanaf `main`):

```bash
git tag v1.0.1
git push origin v1.0.1
```

## Testen

Pull requests draaien **Template regression checks**: de build en de visuele
vergelijking via de workflows van de eigen branch op het voorbeelddocument in
de root, plus de Python-tests:

```bash
(cd .github/mermaid-svg && npm ci --ignore-scripts)
python3 -m pip install PyYAML
python3 -m unittest discover -s tests -v
```

## Workflows updaten in document-repos

De aanroepende workflows in alle document-repositories kunnen centraal
bijgewerkt worden vanuit deze repository via de workflow
**"Update workflows in document repos"**.

### Repos bijhouden (automatisch)

Bij elke run wordt [`.github/repos.json`](.github/repos.json) eerst
automatisch bijgewerkt:

* Repos met `js/config.js` die **nog niet in de lijst staan** worden
  toegevoegd met `"updateAllow": true`
* Repos met `js/config.js` krijgen ook `respecBuildUrl` en
  `respecVersion` mee op basis van `index.html` en `snapshot.html`
* Repos die **gearchiveerd of verwijderd** zijn worden uit de lijst verwijderd
* De bijgewerkte `repos.json` wordt terug gecommit naar deze repository

Wil je een repo **uitsluiten** van updates, zet dan
`"updateAllow": false` in `repos.json`. Die repo wordt dan nooit meer
aangeraakt, ook niet bij toekomstige runs.

Repos met een `config.js` in de root (maar nog niet in `js/`) krijgen een
aparte PR om dit bestand te verplaatsen naar `js/config.js` en meteen de
beheerde `.github`-bestanden uit deze repository mee te nemen. Zo'n repo
wordt pas bij een volgende run automatisch aan `repos.json` toegevoegd,
nadat de migratie-PR is gemerged.

### Handmatig triggeren

Ga naar
[Actions → Update workflows in document repos](https://github.com/Geonovum/NL-ReSpec-workflows/actions/workflows/update-workflows.yml)
en klik op **"Run workflow"**.

* **Dry run** aanvinken om te zien welke repos bijgewerkt zouden worden,
  zonder te committen of PRs aan te maken.

### Wat wordt bijgewerkt?

Alleen een vaste set bestanden wordt bijgewerkt. Bestaande andere
bestanden onder `.github/`, zoals extra workflows of templates, blijven
onaangeraakt.

De volgende bestanden worden bijgewerkt, met als bron
[`document-repo/.github/workflows/`](document-repo/.github/workflows/):

* `.github/workflows/main.yml`
* `.github/workflows/visual-regression.yml`

De volgende verouderde kopieën worden verwijderd, omdat ze nu centraal
gebruikt worden:

* `.github/dependabot.yml`
* `.github/mermaid-svg/package.json` en `package-lock.json`
* `.github/workflows/build.yml`
* `.github/workflows/normalize-mermaid-svg.mjs`
* `.github/workflows/pdf.js`
* `.github/workflows/publish.yml`
