# Fehlerbehebung

| Problem | Ursache / Lösung |
|---|---|
| Plug-ins erscheinen nicht in Cubase | `AIME.vst3` muss in `C:\Program Files\Common Files\VST3\` liegen (`scripts\install_windows.ps1`). Im Plug-in-Manager „Blockierte Plug-ins“ prüfen und neu scannen. |
| Build: „VST3 SDK nicht gefunden“ | `scripts\fetch_vst3sdk.ps1` ausführen oder `VST3_SDK_ROOT` setzen. |
| Build: Compiler fehlt | Visual Studio 2022 bzw. Build Tools mit „Desktopentwicklung mit C++“ installieren. |
| Linux-Build: „cannot find -lstdc++“ | Der Standard-Compiler ist clang ohne libstdc++ → `CXX=g++ CC=gcc scripts/build.sh`. |
| Plugin-Link: keine Instanzen | App muss *vor* oder während Cubase laufen (die Plug-ins verbinden sich jede Sekunde neu). Firewall-Abfrage für 127.0.0.1 erlauben. Port belegt → `AIME_LINK_PORT` für Cubase **und** App gleich setzen. |
| Instanz „(noch kein Name)“ | Cubase hat den Kanalnamen noch nicht gemeldet. MixConsole öffnen oder Spur kurz umbenennen. Alternativ manuell zuordnen. |
| Aufnahme meldet Lücken | Echtzeit-Wiedergabe statt Offline-Export verwenden. CPU-Last senken (Puffergröße erhöhen). |
| Aufnahme leer | Transport lief nicht. Es wird nur bei laufender Wiedergabe aufgenommen. |
| Gesendete Werte kommen nicht an | Plug-in-Fenster nicht nötig. Prüfen, ob die Instanz verbunden ist (Tabelle). Automation-Modus der Spur auf „Read/Off“, damit vorhandene Automation die Werte nicht überschreibt. |
| MIDI Remote: Ports nicht gefunden | In loopMIDI genau `AIME to Cubase` und `AIME from Cubase` anlegen. `python-rtmidi` ist durch `install_windows.ps1` installiert. |
| MIDI Remote: „nicht kalibriert“ | Das Skript sendet keine Anzeigewerte. Skript im MIDI Remote Manager neu laden. Falls `mOnDisplayValueChange` in Ihrer Cubase-Version nicht existiert, `SEND_FEEDBACK = false` setzen. Dann setzt die App über MIDI Remote nur Transport und Bank. |
| MIDI Remote: Skriptfehler zu `bindToPitchBend` | Im Skript `USE_PITCHBEND_FOR_VOLUME = false` setzen (Fader über CC 7, geringere Auflösung). |
| Master leiser als Ziel | Ziel war nur mit Überkompression erreichbar. Siehe Bericht („target_note“). Anderen Mastering-Zweck wählen oder dichter mischen. |
| Falsche Rolle erkannt | In der Tabelle korrigieren. Gelb markierte Zeilen immer prüfen. |
| GUI startet nicht (Linux) | Qt braucht `libegl1`, `libgl1`, `libxkbcommon0`, `libfontconfig1`. |
