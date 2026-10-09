# Mermaid-regressiefixtures

`sensordata.html` bevat de vier ongewijzigde inline SVG-elementen uit de
[gecommitte snapshot van testbed-sensordata-2026](https://github.com/Geonovum/testbed-sensordata-2026/blob/9cd55c0af07a4569c9cf0394aef7e86cc84f1fb0/snapshot.html).
De omhullende HTML is verkleind om de tests zonder netwerk of publicatie-assets
te draaien. Herkomst: Geonovum, ReSpec 37.2.0 / respec-mermaid 1.0.1.
De twee sequence-diagrammen en twee flowcharts bevatten samen 13 groepen dubbele
ID's (26 definities), drie label-offset-attributen en HTML in foreignObject.

`data-image.html` bevat de ingebedde SVG-afbeeldingen uit de template-snapshot
op de oorspronkelijke PR-head e2fbf2410d2740913d3c0071e564336aafbf0ee9
(ReSpec 37.2.0 / respec-mermaid 1.3.0). Deze variant moet bytegelijk blijven.

De normalizer-test en de browser/PDF-test gebruiken dezelfde oorspronkelijke
fixtures. De browsertest normaliseert zelf een kopie, vergelijkt scherm- en
printweergave en draait het ongewijzigde `.github/workflows/pdf.js` voor beide
versies. PNG's, PDF's en het rapport zijn CI-artifacts, geen bronbestanden.
