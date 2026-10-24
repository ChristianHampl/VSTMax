# Cubase-Vorlage für den AIME-Autopiloten

Einmal einrichten, als Projektvorlage speichern und danach für jeden Song verwenden.
Die Schritte nutzen nur Standardfunktionen von Cubase. Menünamen können je nach Version leicht abweichen.

## 1. Plug-ins und MIDI Remote installieren

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

- Cubase neu starten und im *Plug-in-Manager* prüfen, ob `AIME Channel`, `AIME Bus` und `AIME Master`
  (Kategorie *Fx*) erscheinen.
- In loopMIDI zwei Ports anlegen: `AIME to Cubase` und `AIME from Cubase`.
- *Studio → MIDI Remote Manager*: Das Skript „AIME Bridge“ sollte automatisch erkannt werden. Sonst
  über *Controller-Skript hinzufügen* die beiden Ports von Hand zuweisen.

## 2. Spurstruktur

| Element | Inhalt |
|---|---|
| Audiospuren | Je Instrument eine Spur, **Name = Dateiname des Stems** (z. B. „Kick In“, „Gtr Rhythm L“). Insert-Slot 1: `AIME Channel` |
| Gruppenkanäle | `Drums`, `Bass`, `Guitars`, `Vocals`, `Keys` (Namen oder deutsche Aliase, siehe CUBASE_INTEGRATION.md). Insert: `AIME Bus` |
| FX-Kanal 1 | „Reverb“ (z. B. REVerence oder RoomWorks). **Send 1** jeder Spur führt hierhin |
| FX-Kanal 2 | „Delay“ (z. B. StereoDelay, tempo-synchron). **Send 2** jeder Spur führt hierhin |
| Stereo Out | Insert 1: `AIME Bus` (Mixbus), Insert 2: `AIME Master` |

- Sends bei allen Spuren **aktivieren** und auf −∞ dB stellen. Den Pegel setzt die App.
- Sidechain (optional, Gitarren-Ducking bei Vocals): Beim `AIME Channel` der Gitarren den Sidechain-Eingang
  aktivieren und von der Vocal-Spur speisen. Die App aktiviert das dynamische Band, wenn der Plan es vorsieht.
- Fader auf 0 dB, Pan Mitte. Pegel und Pan regelt `AIME Channel`.

## 3. Ablauf pro Song

1. Stems importieren (*Datei → Importieren → Audiodatei*, „Dateien in Projektordner kopieren“) oder die
   eigenen Aufnahmen verwenden. Spuren wie oben benennen.
2. AIME-App starten → Tab **Cubase** → *Plugin-Link starten* → Instanzen erscheinen mit Kanalnamen.
3. Optional *MIDI-Remote-Bridge verbinden* (dann startet und stoppt die App den Transport selbst).
4. **Automation-Write ausschalten**, Positionszeiger an den Songanfang.
5. *Alles automatisch (1–3)*: Aufnahme während der Wiedergabe → Analyse/Plan → Werte senden.
6. Anhören. Bei Bedarf in der App Rollen korrigieren oder den Charakter ändern und erneut senden.
   *Letztes Senden rückgängig* stellt den vorherigen Stand wieder her.

## 4. Album

Für ein ganzes Album dieselbe Vorlage und dasselbe Profil verwenden. Danach die Mixdowns im Tab **Album**
gemeinsam mastern (einheitliche Lautheit oder relative Unterschiede erhalten, tonaler Angleich).
