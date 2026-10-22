# Was schon geprüft ist, und was nicht

Geprüft auf einem Linux-Rechner, mit synthetischen Testspuren:

- Die Rechenkerne von App und Plug-in liefern dieselben Ergebnisse.
- Der offizielle Steinberg-Validator hat die Plug-ins mit 141 bestandenen Tests und 0 Fehlern geprüft.
- Aufnahme, Zuordnung, Wertesenden und Rückgängig sind mit einer nachgebauten Gegenstelle geprüft, nicht mit Cubase.
- Die Oberfläche ist ohne Bildschirm durchgespielt: Analyse, Rollenkorrektur, Vorschau, Export.

Noch nicht auf einem echten Windows-Rechner mit Cubase geprüft:

- Ob Cubase die Kanalnamen sofort meldet.
- Ob die Aufnahme bei eingeschaltetem Latenzausgleich samplegenau sitzt.
- Ob Cubase die gesendeten Werte in seine eigene Undo-Liste aufnimmt.
- Ob das MIDI-Skript in deiner Cubase-Version jede benutzte Funktion anbietet. Unsichere Stellen haben im Skript einen Schalter.
- Wie der Installer sich auf deinem Rechner verhält. Er wird auf einem Windows-Build-Server erzeugt. Du bist der Erste, der ihn mit Cubase ausprobiert.

Bekannte Grenzen: Bei extremem Rauschen kann der Limiter die True-Peak-Grenze um bis zu etwa 0,5 dB überschreiten. Bei musikähnlichem Material bleibt er darunter. Die Rollenerkennung irrt sich bei ähnlichen Klängen (tiefe Toms und Kick) und markiert den Widerspruch dann gelb. Rückgängig kennt nur Werte, die diese App gesendet hat.

Wenn beim ersten Cubase-Durchgang etwas nicht stimmt, reicht die Meldung aus dem Protokoll unten. Daran lässt sich gezielt nachbessern.
