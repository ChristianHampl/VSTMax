# Automatik, Album, Ordner

## Automatik über die Plug-ins

Tab **Cubase**. Die Plug-ins verbinden sich nur mit diesem Rechner (`127.0.0.1`), es geht nichts ins Internet.

- **Aufnehmen**: während Cubase abspielt, nimmt jede AIME-Instanz ihr Eingangssignal auf, ausgerichtet an der Projektposition. Normale Wiedergabe, kein schneller Offline-Export.
- **Analyse & Plan**: dieselbe Rechnung wie im Datei-Workflow, inklusive Mastering und Bericht im Arbeitsordner.
- **Werte an Cubase senden**: EQ, Dynamik, Sättigung, Pegel, Pan und Breite gehen an die passenden Instanzen. Der Kanalname entscheidet die Zuordnung. Passt ein Name auf zwei Spuren, wird nichts geraten, sondern ein Konflikt gemeldet.
- **Letztes Senden rückgängig**: der Stand vor dem letzten Senden, oder die Plug-in-Grundwerte beim ersten Mal.
- **Alles automatisch** macht die drei Schritte hintereinander. Mit verbundener MIDI-Bridge startet und stoppt die App den Transport selbst und setzt Hall- und Delay-Sends.

Die Spalte *Zuordnung* zeigt, welche Plan-Spur jede Instanz bekommen hat.

## Album

Tab **Album**: fertige Mixdowns hinzufügen.

- *Einheitliche Lautheit*: alle Songs auf dasselbe Ziel.
- *Relative Unterschiede*: ein absichtlich leiserer Song bleibt leiser.
- *Tonaler Angleich*: wie stark sich die Klangfarben angleichen.

Dieselbe True-Peak-Grenze für alle.

## Ordnerüberwachung

Tab **Ordnerüberwachung**. Jeder Unterordner im Eingang ist ein Song. Sobald Cubase mit dem Export fertig ist und die Dateien ein paar Sekunden unverändert bleiben, wird der Song mit dem Profil aus dem Projekt-Tab gemischt und gemastert. Jeder Stand nur einmal. In den Eingangsordner wird nichts geschrieben.
