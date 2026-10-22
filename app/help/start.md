# So fängst du an

Du brauchst nur die Setup-Datei. Kein Visual Studio, kein Git, kein Python.

1. **AI-Mix-Engineer-Setup.exe** doppelklicken und durchklicken. Die App liegt danach im Startmenü.
2. Cubase **einmal starten und schließen**, damit Cubase seine Ordner anlegt.
3. Hier oben auf **Für Cubase einrichten** klicken. Damit werden das Plug-in und das MIDI-Skript an die richtigen Stellen kopiert. Eine Rückfrage von Windows nach Administratorrechten kommt dabei nicht.
4. Cubase neu starten. Unter *Studio → Plug-in-Manager* müssen **AIME Channel**, **AIME Bus** und **AIME Master** stehen.
5. In dieser App den Tab **Cubase** öffnen und **Plugin-Link starten**.

## MIDI-Ports (einmalig, für Sends und Start/Stopp)

Installiere **loopMIDI** (kostenlos, Tobias Erichsen) und lege zwei Ports an, exakt so benannt:

- `AIME to Cubase`
- `AIME from Cubase`

Danach in Cubase unter *Studio → MIDI Remote Manager* das Skript **AIME Bridge** prüfen. In dieser App auf **MIDI-Remote-Bridge verbinden** klicken.

## Wenn du nur Dateien mischen willst

Cubase ist dafür nicht nötig. Spuren als WAV exportieren, im Tab **Projekt & Mix** den Ordner hinzufügen und **Mischen, Mastern & Exportieren** wählen. Die Schritte stehen unter „Songs mischen“.
