# Bedienungsanleitung

## Weg A: Dateien (ohne Cubase-Anbindung)

1. **Stems exportieren**: In Cubase alle Spuren per Kanal-Batch-Export ab Projektanfang als WAV exportieren
   (24 Bit oder 32 Bit Float, 44,1 oder 48 kHz). Spurnamen helfen der Erkennung, sind aber kein Muss.
2. **Tab „Projekt & Mix“** → *Ordner hinzufügen*.
3. **Einstellungen**:
   - *Genre-Profil*: Grundcharakter (Tooltips beschreiben die Profile).
   - *Mastering-Zweck*: Genre-Profil, Streaming normalisiert (−14 LUFS), Streaming laut (−10), CD/Club (−9),
     Rundfunk R128 (−23).
   - *Klangcharakter*: Helligkeit, Punch, Stereobreite, Vocal-Pegel, Dynamik.
   - Optional *Referenz*: Ein Song als Klangvorbild. Er wird nur lokal analysiert, gedämpft verglichen und
     nie kopiert oder exportiert.
4. **1. Analysieren**: Pro Spur erscheinen erkannte Rolle, Sicherheit und Alternativen. **Gelb** markierte
   Zeilen sind unsicher, zum Beispiel wenn der Klang dem Dateinamen widerspricht. Dort in *Rolle (Korrektur)*
   die richtige Rolle wählen.
5. **2. Mix-Vorschau** berechnet den Plan und optimiert den lautesten Ausschnitt. Mit *A: Original* und
   *B: Mix* lautheitsangeglichen vergleichen.
6. **3. Mischen, Mastern & Exportieren**: Es entsteht ein neuer Ordner mit Zeitstempel im Ausgabeordner:
   - `master.wav`, `mix_unmastered.wav`, `stems/*.wav`
   - `report.html`: Messwerte, Spektren, alle Entscheidungen mit Begründung, Warnungen
   - `plan.json`, `presets/*.vstpreset`, `setup_sheet.html` (Einrichtung in Cubase von Hand)

*Projekt speichern* legt eine `.aime.json` an. Sie enthält nur Verweise auf die Audiodateien und
alle Einstellungen, zum Beispiel für einheitliche Album-Produktionen.

## Weg B: Cubase-Autopilot

Voraussetzung: Vorlage nach [CUBASE_TEMPLATE.md](CUBASE_TEMPLATE.md).

1. Tab **Cubase** → *Plugin-Link starten*. Die Tabelle zeigt alle AIME-Instanzen mit Kanalnamen.
2. Optional *MIDI-Remote-Bridge verbinden*. Dann steuert die App Start und Stopp und setzt Sends und Fader.
3. *Aufnahmedauer*: „bis Cubase stoppt“ (Wiedergabe von Hand stoppen) oder feste Sekundenzahl.
4. *Alles automatisch (1–3)* oder einzeln: *Aufnehmen* → *Analyse & Plan* → *Werte senden*.
5. In der Spalte *Zuordnung* steht, welcher Plan-Spur jede Instanz zugeordnet wurde. Konflikte stehen im Log.
6. *Letztes Senden rückgängig* stellt den vorherigen Stand wieder her. Das ist der letzte AIME-Stand oder,
   beim ersten Senden, die Plug-in-Defaults. Von Hand in Cubase geänderte Werte kennt die App nicht.

Ergebnisse liegen im Arbeitsordner: `session-*/capture` (Aufnahmen), `session-*/export` (Bericht, Renderings),
`snapshots/`.

## Weg C: Ordnerüberwachung

Tab **Ordnerüberwachung**: Eingangs- und Ausgabeordner wählen und *Überwachung starten*. Jeder Unterordner
im Eingang ist ein Song. Sobald dessen Dateien einige Sekunden unverändert sind, wird er mit Profil und
Zweck aus dem Projekt-Tab gemischt und gemastert. Jeder Stand wird nur einmal verarbeitet.

## Album

Tab **Album**: fertige Mixdowns oder Master hinzufügen, Modus wählen (*einheitliche Lautheit* oder
*relative Unterschiede erhalten*) und den Grad des tonalen Angleichs einstellen. Alle Songs bekommen dieselbe
True-Peak-Grenze und dasselbe Exportformat.

## Tipps für Rock/Metal

- Gitarren-Doubles (L/R) als getrennte Spuren liefern. Die Analyse erkennt echte Doubles und Duplikate
  (identische Kopien werden gemeldet).
- Kick In/Out und Snare Top/Bottom: Polarität und Laufzeit werden automatisch geprüft und im Plug-in
  (Polarität, Laufzeitausgleich) korrigiert.
- Wird das Lautheitsziel ohne Überkompression nicht erreicht, bleibt der Master leiser und der Bericht
  sagt warum. Das ist Absicht.
