# Cubase-Anbindung

Cubase bietet keine öffentliche Schnittstelle, über die ein externes Programm Spuren auslesen,
Plug-ins einfügen oder Presets laden kann. AIME nutzt deshalb nur dokumentierte Wege und kombiniert
sie so, dass nach einer einmaligen Einrichtung (Vorlage) möglichst alles automatisch läuft.

| Weg | Was damit geht | Status |
|---|---|---|
| **Eigene VST3-Plug-ins + Plugin-Link** | Audio jeder Spur aufnehmen, alle Bearbeitungsparameter (EQ, Dynamik, Sättigung, Pegel, Pan, Breite, Laufzeit, Bus, Master) setzen | gebaut, validiert, mit simulierten Instanzen getestet; **in Cubase nicht ausgeführt** |
| **MIDI-Remote-Skript „AIME Bridge“** | Fader, Pan, Mute/Solo, Send 1/2, Bank-Navigation, Transport; Kanalnamen und Anzeigewerte zurück | Skript gegen eine API-Attrappe ausgeführt; **in Cubase nicht ausgeführt** |
| **Datei-Workflow (Fallback)** | Stems exportieren, offline mischen/mastern, `.vstpreset` + Einrichtungsblatt | vollständig getestet (ohne Cubase) |

## 1. Plugin-Link (Hauptweg)

Jede Instanz von `AIME Channel`, `AIME Bus` und `AIME Master` öffnet eine gemeinsame TCP-Verbindung
zu `127.0.0.1:47800` (änderbar über die Umgebungsvariable `AIME_LINK_PORT`). Es werden keine Daten
ins Netz übertragen; der Server nimmt nur Verbindungen von `127.0.0.1` an.

- **Kanalname**: Cubase meldet Name und UID der Spur über die VST3-Schnittstelle
  `ChannelContext::IInfoListener` (`kChannelNameKey`, `kChannelUIDKey`). Damit ordnet die App
  Instanz ↔ Spur zu. Ob Cubase 15 diese Infos sofort beim Laden oder erst beim Öffnen der MixConsole
  sendet, ist **zu verifizieren**. Ohne Namen erscheint die Instanz als „(noch kein Name)“ und kann von
  Hand zugeordnet werden.
- **Aufnahme (Capture)**: Auf Befehl der App schreibt jede Instanz ihr *Eingangssignal* (vor der
  Bearbeitung) mit der Projektposition (`ProcessContext::projectTimeSamples`) in einen lock-freien
  Ringpuffer. Ein Hintergrund-Thread sendet die Daten an die App, die je Spur eine WAV-Datei schreibt,
  ausgerichtet an der Projektposition. Läuft der Transport nicht, wird nichts aufgenommen.
  - Empfohlen: normale Wiedergabe in Echtzeit vom Songanfang bis zum Ende. Bei schnellerem
    Offline-Export kann der Ringpuffer (≈ 5,4 s bei 48 kHz) überlaufen. Die App meldet Lücken als Warnung.
  - Ob `projectTimeSamples` in Cubase bei aktiver Latenzkompensation für alle Spuren identisch
    ausgerichtet ist, ist **zu verifizieren** (Test: gleiche Datei auf zwei Spuren, Aufnahmen vergleichen).
- **Parameter senden**: Die App schickt Klarwerte (IDs aus `integration/protocol/plugin_params.json`).
  Der Controller übernimmt sie im UI-Thread (Timer, 30 ms) mit `beginEdit/performEdit/endEdit`,
  wie bei einer Bedienung im Editor. Cubase erfährt die Änderung dadurch regulär (Projekt geändert,
  Automation im Write-Modus würde mitschreiben). **Automation-Write vor dem Senden ausschalten.**
  Ob Cubase diese Änderungen in seine eigene Undo-Liste aufnimmt, ist **zu verifizieren**. AIME
  legt deshalb vor jedem Senden selbst einen Snapshot an (`Rückgängig`).
- Unter Linux gibt es in diesem Zusammenhang keinen UI-Timer des SDK. Dort kommen gesendete Werte nicht
  im Controller an. Cubase läuft nur unter Windows und macOS, wo der Timer existiert.

### Zuordnung Cubase-Kanal ↔ Plan

- Channel: exakter Name (Groß-/Kleinschreibung, Sonderzeichen egal) oder ähnlicher Name (≥ 75 %).
  Mehrdeutige Fälle (z. B. „Gtr Rhythm“ passt zu L und R) werden **nicht** geraten, sondern als
  Konflikt gemeldet und können manuell zugeordnet werden.
- Bus: Kanalname = Gruppen-ID oder Alias (`Drums`/`Schlagzeug`, `Guitars`/`Gitarren`, `Vocals`/`Gesang`, …).
  Ein `AIME Bus` auf dem Stereo-Out (Name `Stereo Out`, `Mix`, `Summe` …) erhält die Mixbus-Einstellungen.
- `AIME Master` erhält immer die Master-Einstellungen.

## 2. MIDI Remote „AIME Bridge“

`integration/midi_remote/AIME/Bridge/AIME_Bridge.js` ist ein Skript für das MIDI-Remote-API
(`midiremote_api_v1`). Es bildet 8 Kanäle der MixConsole (ohne Ein-/Ausgangskanäle) als Bank ab.

- Ports: zwei virtuelle MIDI-Ports `AIME to Cubase` und `AIME from Cubase` (z. B. loopMIDI).
- App → Cubase: Fader per Pitchbend (14 Bit), Pan/Mute/Solo/Send 1/Send 2 per CC, Bank vor/zurück,
  Start/Stopp/Aufnahme/Cycle. Belegung: `integration/midi_remote/mapping.json`; der Test
  `test_script_mapping_block_matches_json` stellt sicher, dass Skript und App dieselbe Belegung nutzen.
- Cubase → App: Kanalname, Anzeigewert (z. B. `-6.02 dB`) und normierter Wert als SysEx.
- **Kalibrierung statt Raten**: Cubase legt die Fader-Kennlinie nicht offen. Die App setzt einen Wert,
  liest die Anzeige zurück und regelt per Bisektion nach. Ohne Rückmeldung meldet sie „nicht kalibriert“,
  statt einen Wert zu raten.
- **Zu verifizieren in Cubase** (im Skript markiert): `bindToPitchBend` (Fallback: Konstante
  `USE_PITCHBEND_FOR_VOLUME = false` → CC 7, nur 7 Bit), `mOnTitleChange`, `mOnDisplayValueChange`
  (Fallback: `SEND_FEEDBACK = false`; dann sind nur ungeprüfte Werte möglich und die App meldet das).
- Pegel, Pan und Bearbeitung liegen im Plug-in. Über die MixConsole setzt AIME nur Effekt-Sends
  (Send 1 = Reverb-FX, Send 2 = Delay-FX laut Vorlage) und stellt Fader auf 0 dB und Pan auf Mitte,
  damit nichts doppelt wirkt.

## 3. Datei-Workflow (Fallback, immer verfügbar)

1. In Cubase: *Datei → Exportieren → Audio-Mixdown → Kanal-Batch-Export*, alle Spuren als WAV
   (gleiche Länge, Startpunkt Projektanfang) in einen Ordner.
2. App: Ordner hinzufügen → Analysieren → Rollen prüfen → Mischen, Mastern & Exportieren.
3. Ergebnis: `master.wav`, `mix_unmastered.wav`, Bus-Stems, `report.html`, `plan.json`,
   `presets/*.vstpreset` und `setup_sheet.html`. Die Presets lassen sich in Cubase im jeweiligen
   AIME-Plug-in über das Preset-Menü laden. Das Einrichtungsblatt nennt für jede Spur Preset,
   Gruppe, Pan, Pegel, Sends und Sidechain.

Mit der **Ordnerüberwachung** wird Schritt 2 automatisch: Jeder neue Unterordner im Eingangsordner
wird verarbeitet, sobald Cubase mit dem Schreiben fertig ist.

## Was bewusst nicht gemacht wird

- Keine Fernsteuerung über undokumentierte Schnittstellen, keine Manipulation von `.cpr`-Dateien.
- Kein Einfügen von Plug-ins durch die App. Das übernimmt die Vorlage ([CUBASE_TEMPLATE.md](CUBASE_TEMPLATE.md)).
- Keine Cloud-Übertragung. Es gibt keine Cloud-Funktion im Programm.
