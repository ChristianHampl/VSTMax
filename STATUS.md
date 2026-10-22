# STATUS – ehrlicher Projektstand

Stand: Entwicklungsumgebung Linux x86_64 (Ubuntu 24.04, GCC 13.3, CMake 3.28, Python 3.12).
**Cubase war nicht verfügbar, Windows ebenfalls nicht.** Alles, was dort laufen muss, ist unten
ausdrücklich als *nicht ausgeführt* markiert.

## Ausgeführt und bestanden

| Bereich | Nachweis | Ergebnis |
|---|---|---|
| C++-DSP-Kern | `build/dsp/aime_dsp_tests` → [docs/results/dsp_tests_linux.log](docs/results/dsp_tests_linux.log) | 145 Prüfungen, 0 Fehler (Filter, Kompressor, Gate/De-Esser/Dyn-Band, True-Peak-Limiter, Latenz/Bypass, Glättung, NaN/Inf, Mono/Stereo/Pan, Samplerate-Wechsel 44,1/48/96 kHz, Sättigung phasengleich, keine Allokation im Audio-Pfad, CPU) |
| VST3-Plug-ins | Build gegen offizielles VST3 SDK v3.8.1_build_84 → [docs/results/build_linux.log](docs/results/build_linux.log) | `AIME.vst3` mit AIME Channel/Bus/Master; keine Warnungen im eigenen Code |
| Steinberg-Validator | `validator AIME.vst3` → [docs/results/vst3_validator_linux.log](docs/results/vst3_validator_linux.log) | **141 Tests bestanden, 0 fehlgeschlagen** |
| Python-Tests | `scripts/run_tests.sh` → [docs/results/pytest_linux.log](docs/results/pytest_linux.log) | **58 bestanden, 0 übersprungen, 0 fehlgeschlagen** |
| Lautheit | EBU-Testfälle (1 kHz −23 LUFS bei 44,1/48 kHz, relatives Gating), True Peak > Sample-Peak | bestanden |
| Python ↔ C++ | `test_native_equivalence.py` | Filter/Gain < 1e-4; Kompressor < 0,5 dB (gemessen ≤ 0,35); De-Esser/Dyn-Band/Gate < 0,1 dB; Master < 0,75 LU |
| Python-Preset → gebautes VST3 | `test_vst3_host.py`, Mini-Host über SDK-Hosting-Klassen | Zustand wird geladen; Ausgabe des Plug-in-Binaries = C++-DSP (< 2e-4) bei allen drei Plug-ins; Latenz 15/30/84 korrekt gemeldet |
| Plugin-Link | `test_plugin_link.py` mit echtem Hub-Code (`aime_link_client`) | Verbindung, Instanzliste, Capture lückenlos und positionsgenau (< 1e-5), Parameter-Push kommt bitgenau an; Capture überschreibt keine Dateien |
| Autopilot | `test_autopilot.py` (Cubase-Seite simuliert) | Capture (bitgenau) → Analyse/Plan/Mastering/Export → Push an alle Instanzen → Undo auf Defaults; Transport über Bridge-Testdouble |
| Ordnerüberwachung | `test_autopilot.py` | verarbeitet stabile Songs genau einmal, Eingangsdateien unverändert |
| MIDI-Remote-Skript | `test_midi_remote.py`: Ausführung in Node.js gegen eine **Attrappe** des API | Skript läuft fehlerfrei; Mapping identisch mit der App; SysEx-Texte (inkl. Umlaute) werden von der Python-Bridge korrekt gelesen |
| MIDI-Bridge-Logik | gegen `CubaseSimulator` (Testdouble mit erfundener Fader-Kurve) | Bisektion auf Anzeigewert (Fader ±0,1 dB, Send ±0,5 dB, Pan ±0,02), Bank-Suche, Transport, „nicht kalibriert“ ohne Rückmeldung |
| GUI | `test_gui_cli.py` headless (Qt offscreen) | Analyse → Rollenkorrektur wirkt auf den Plan → Vorschau → Export; Cubase-Tab zeigt verbundene Instanzen |
| CLI | `python -m app profiles/mix` | bestanden |
| Mastering/Album/Referenz | `test_mastering_album_reference.py` | Ziel-LUFS ±0,5, True Peak ≤ Grenze + 0,1 dB; Überkompressionsschutz verfehlt das Ziel bewusst und dokumentiert das; Album einheitlich ≤ 0,6 LU Streuung, relativer Modus erhält Reihenfolge; Referenzvorschläge gedämpft/begrenzt |
| Originalschutz | Tests in `test_audio_io.py`, Capture, Watcher, Album | Quellen werden nie überschrieben |

## Windows-Build (GitHub Actions, 22. Oktober 2026)

Auf einem Windows-Runner mit dem Microsoft-Compiler, Lauf um 19:40 Uhr Berlin
([Run 39824617914](https://github.com/ChristianHampl/VSTMax/actions/runs/39824617914)):

- DSP-Tests: 1 von 1 bestanden (CTest).
- Steinberg-Validator: **141 Tests bestanden, 0 fehlgeschlagen.**
- pytest: 57 bestanden, 4 fehlgeschlagen. Windows sperrt die temporäre Aufnahmedatei, solange sie als
  Memmap offen ist. Behoben durch explizites Schließen vor dem Löschen.

Zweiter Lauf um 19:50 Uhr Berlin
([Run 39825463735](https://github.com/ChristianHampl/VSTMax/actions/runs/39825463735)): Validator
erneut 141/0. pytest 60 bestanden, 1 fehlgeschlagen (`test_link_with_native_hub`): der Testclient
schlief pro Audioblock 5 ms, Windows rundet das auf etwa 15 ms auf, deshalb lagen nach 1,2 s
Wandzeit nur 0,44 s Audio vor. Der Client zieht überzogene Pausen jetzt an der Wanduhr nach.
`AI-Mix-Engineer-Setup.exe` entsteht erst, wenn dieser Lauf grün ist.

Das Setup ist damit noch nicht auf einem Cubase-Rechner installiert worden.

## Nicht ausgeführt

| Was | Warum / was ist zu tun |
|---|---|
| **Jeder Test in Cubase 15** (Plug-ins laden, Kanalnamen über `IInfoListener`, Capture-Ausrichtung mit Latenzkompensation, Parameter-Push in Cubase, Undo-Verhalten von Cubase, Automation-Interaktion) | Kein Cubase verfügbar. Prüfliste unten. |
| **MIDI-Remote-Skript in Cubase** | Nur gegen eine Attrappe ausgeführt. Unverifiziert sind insbesondere `bindToPitchBend`, `mOnTitleChange`, `mOnDisplayValueChange` sowie das Bank-Verhalten von `makeMixerBankZone`. Fallback-Schalter stehen im Skript. |
| **Setup.exe auf einem echten PC / in Cubase** | Der Microsoft-Compiler und der Validator sind auf dem GitHub-Windows-Runner gelaufen (siehe oben). Installiert und in Cubase geladen wurde das Setup nicht. |
| **PowerShell-/Batch-Skripte lokal** | `build.ps1` ist auf dem GitHub-Runner gelaufen (Compile, CTest, Validator). `install_windows.ps1`, `fetch_vst3sdk.ps1`, `run_tests.ps1` und `start_gui.bat` wurden hier nicht ausgeführt. |
| **Parameter-Push im Controller unter Linux** | Das SDK liefert unter Linux keinen UI-Timer (`Timer::create` → nullptr). Unter Windows/macOS vorhanden, dort aber nicht getestet. |
| **A/B-Wiedergabe** (QtMultimedia) | Kein Audiogerät in der Testumgebung; nur die lautheitsangeglichenen Puffer wurden geprüft. |
| **Echte Musikaufnahmen** | Alle Audiotests nutzen synthetische Spuren (`engine/synth.py`). Klangqualität mit echten Produktionen ist nicht belegt. |
| **macOS** | Nicht gebaut. |

## Bekannte Grenzen

- **Rollenerkennung** ist merkmalsbasiert (kein mitgeliefertes ML-Modell). Bei klanglich ähnlichen Rollen
  (z. B. tiefe Toms ↔ Kick) kann sie irren. Widerspricht der Klang dem Dateinamen, wird die Spur als unsicher
  markiert (max. 60 %) und sollte geprüft werden. Ein eigenes ONNX-Modell lässt sich einbinden.
- **Limiter**: Bei Rausch-Extremsignalen bis 0,53 dB True-Peak-Überschreitung (16×-Referenz). Bei
  musikähnlichem Material ≤ 0,03 dB. Der Offline-Master wird nach dem Limiter gemessen und berichtet.
- **Capture** setzt Echtzeit-Wiedergabe voraus (Ringpuffer ≈ 5,4 s). Lücken werden gemeldet, nicht verdeckt.
- **Undo** kennt nur Werte, die AIME gesendet hat, nicht spätere Handänderungen in Cubase.
- Plug-in-Editor: generischer Host-Editor (kein eigenes GUI im Plug-in).
- Nur 32-Bit-Float-Verarbeitung im Plug-in (`canProcessSampleSize(kSample64)` → false).

## Prüfliste für den ersten Cubase-Test

1. `scripts\build.ps1` → Validator meldet „0 tests failed“.
2. `scripts\install_windows.ps1` → Cubase startet, Plug-ins im Plug-in-Manager sichtbar.
3. `AIME Channel` auf zwei Spuren mit derselben Datei; App: *Plugin-Link starten* → beide Instanzen mit
   **richtigem Kanalnamen**?
4. *Aufnehmen* (8 s abspielen) → beide WAVs identisch und zum Original ausgerichtet? Danach dasselbe mit
   einem latenzbehafteten Plug-in vor AIME auf einer Spur (Latenzkompensation).
5. *Werte senden* → Parameter im Plug-in-Fenster sichtbar geändert? Undo der App wirksam?
   Verhalten von Cubase-Undo (Strg+Z) notieren.
6. MIDI Remote: Skript erscheint im Manager? Fader per App auf −6 dB → Anzeige −6,0 dB? Falls Fehler:
   `USE_PITCHBEND_FOR_VOLUME`/`SEND_FEEDBACK` umstellen und Ergebnis notieren.
7. Ergebnisse in dieser Datei unter „Ausgeführt“ nachtragen.
