# Songs mischen

## 1. Spuren laden

Tab **Projekt & Mix**, **Ordner hinzufügen** oder einzelne Dateien. WAV, FLAC und AIFF, 44,1 oder 48 kHz. Gleiche Länge und gleicher Startpunkt, so wie Cubase sie beim Kanal-Export schreibt.

## 2. Klang wählen

- **Genre-Profil**: der Grundcharakter. Die Profile beschreiben sich in der Auswahl.
- **Mastering-Zweck**: Genre-Profil, Streaming normal (−14 LUFS), Streaming laut (−10), CD/Club (−9) oder Rundfunk (−23).
- **Regler**: Helligkeit, Punch, Stereobreite, Vocal-Pegel, Dynamik.
- **Referenz** (optional): ein Song als Klangvorbild. Er wird nur auf diesem Rechner analysiert, nie kopiert und nie mit exportiert.

## 3. Analysieren

**1. Analysieren**. Pro Spur stehen Rolle, Sicherheit und Alternativen. **Gelbe Zeilen** sind unsicher, zum Beispiel wenn der Klang nicht zum Dateinamen passt. Dort unter *Rolle (Korrektur)* die richtige Rolle wählen.

## 4. Hören und exportieren

**2. Mix-Vorschau** rechnet den lautesten Ausschnitt. **A: Original** und **B: Mix** sind auf gleiche Lautheit gestellt.

**3. Mischen, Mastern & Exportieren** legt einen neuen Ordner an:

- `master.wav` und `mix_unmastered.wav`
- Bus-Stems
- `report.html` mit Messwerten und jeder Entscheidung samt Begründung
- Presets für die AIME-Plug-ins und ein Einrichtungsblatt

**Projekt speichern** schreibt eine `.aime.json`. Darin stehen nur die Pfade zu deinen Dateien und die Einstellungen, nicht die Audiodaten. Dieselben Einstellungen halten ein Album einheitlich.

Deine Originaldateien und das Cubase-Projekt werden nie überschrieben.
