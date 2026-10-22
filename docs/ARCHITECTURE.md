# Architektur

```
┌────────────── AIME-App (Python, lokal) ──────────────┐        ┌──────────── Cubase ────────────┐
│ app/gui (PySide6)   app/cli                           │        │ AIME Channel/Bus/Master (VST3) │
│ app/orchestration: Pipeline, Autopilot, Watcher       │◄─TCP──►│  plugins/source + dsp/core     │
│ engine: Analyse, Klassifikation, Planer, Mixer,       │127.0.0.1│                                │
│         Optimierer, Mastering, Referenz, Album        │        │ MIDI Remote „AIME Bridge“ (JS) │
│ integration: plugin_link, midi_remote, presets,       │◄─MIDI─►│  integration/midi_remote/AIME  │
│              protocol (Parameter-Definition), fallback│        └────────────────────────────────┘
└───────────────────────────────────────────────────────┘
```

## Komponenten

| Pfad | Aufgabe |
|---|---|
| `engine/` | Rechenkern ohne GUI: Import/Export (`audio_io`), Analyse, Rollen (`classification`), Phase/Duplikate, Maskierung, Planer (`mix_planner`), Offline-Mixer (`mixing`), Optimierer, Mastering, Lautheit (BS.1770-4), Referenz, Album, Validierung |
| `profiles/*.json` | 8 Genre-Profile mit Vererbung von `_base.json` |
| `dsp/core/` | Header-only C++17-DSP (Echtzeit-tauglich): Filter, Dynamik, Sättigung (2× OS), True-Peak-Limiter, Lautheitsmessung, Strips |
| `dsp/tests`, `dsp/tools/aime_render` | DSP-Tests (Genauigkeit, Latenz, NaN/Inf, Allokation, CPU) und Offline-Renderer für den Abgleich mit Python |
| `plugins/` | VST3-Plug-ins auf Basis des offiziellen Steinberg VST3 SDK; Plugin-Link-Hub; Testwerkzeuge `aime_host_render`, `aime_link_client` |
| `integration/protocol/plugin_params.json` | **Einzige Quelle** aller Plug-in-Parameter (IDs, Bereiche, Kennlinien). `scripts/gen_params.py` erzeugt daraus `dsp/core/aime_params_gen.h` |
| `integration/presets` | `.vstpreset`-Export (gleiches Zustandsformat wie das Plug-in) |
| `integration/plugin_link` | Server, Capture, Zuordnung, Parameter-Push |
| `integration/midi_remote` | Cubase-Skript, Python-Bridge mit Kalibrierung, MixConsole-Plan, Testdouble |
| `integration/fallback` | Einrichtungsblatt (HTML) für den manuellen Weg |
| `app/orchestration` | `Pipeline` (Stufen mit Fortschritt/Abbruch), `Autopilot` (Capture → Plan → Push, Snapshots), `FolderWatcher` |

## Datenfluss Offline

Import → Analyse je Spur → Paaranalyse (Doubles, Duplikate, Polarität/Laufzeit) → Rollen (Merkmale,
Dateiname als schwaches Indiz, optional eigenes ONNX-Modell, Kontextregeln) → Plan (Profil + Charakter) →
Kalibrierung der Dynamikstufen am echten Signal → Optimierung (lautester Ausschnitt) → Rendering →
Mastering → Qualitätsprüfung → Export (neuer Ordner) + Bericht.

## Gleichheit Offline ↔ Plug-in

Offline-Mixer und Plug-ins verwenden dieselben Formeln, Kennlinien und Parameter. Belegt ist das durch
`tests/test_native_equivalence.py` (Python ↔ C++-DSP) und `tests/test_vst3_host.py` (Python-Preset →
gebautes `AIME.vst3` im SDK-Host → Vergleich mit dem C++-DSP). Toleranzen und Messwerte stehen in STATUS.md.

## Echtzeitregeln im Plug-in

- Keine Allokation, keine Locks und kein I/O im Audio-Thread. Zustandsübernahme per `try_lock` und
  Capture über einen SPSC-Ringpuffer.
- Parameter werden geglättet. Beim Aktivieren wird ein geladener Zustand ohne Rampe übernommen.
- Konstante Latenz (Channel 15, Bus 30, Master 84 Samples bei 48 kHz) wird an den Host gemeldet.
  Bypass ist latenzkompensiert.
- NaN/Inf-Schutz am Ausgang.

## Sicherheit / Datenschutz

- Netzwerk ausschließlich `127.0.0.1`. Keine Telemetrie, keine Cloud.
- Schreibzugriffe nur in neue Ordner. Exporte prüfen, dass keine Quelldatei überschrieben wird
  (`protected`). Capture-Dateien erhalten bei Namenskonflikt einen Zusatz.
