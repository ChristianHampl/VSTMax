# Drittanbieter-Komponenten und Lizenzen

Alle Komponenten sind kostenlos, laufen lokal und übertragen keine Daten.

| Komponente | Verwendung | Lizenz |
|---|---|---|
| [Steinberg VST3 SDK](https://github.com/steinbergmedia/vst3sdk) (Tag v3.8.1_build_84) | Plug-in-Basis, Validator, Hosting-Klassen für Tests. Wird beim Build geladen, nicht im Repository | MIT (seit SDK 3.8) |
| Cubase MIDI Remote API (`midiremote_api_v1`) | Laufzeit-API in Cubase, nicht mitgeliefert | Steinberg |
| [NumPy](https://numpy.org/) | Rechenkern | BSD-3-Clause |
| [SciPy](https://scipy.org/) | Filter, Resampling | BSD-3-Clause |
| [soundfile](https://github.com/bastibe/python-soundfile) / libsndfile | WAV/FLAC/AIFF lesen und schreiben | BSD-3-Clause / LGPL-2.1 |
| [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python) | GUI | LGPL-3.0 |
| [mido](https://github.com/mido/mido) | MIDI-Nachrichten | MIT |
| [python-rtmidi](https://github.com/SpotlightKid/python-rtmidi) (optional) | MIDI-Ports | MIT |
| [onnxruntime](https://onnxruntime.ai/) (optional) | Nur wenn Sie ein **eigenes** Klassifizierungsmodell einbinden | MIT |
| loopMIDI (optional, extern) | Virtuelle MIDI-Ports unter Windows | Freeware (Tobias Erichsen) |
| pytest | Tests | MIT |

Es werden **keine** fremden Audioaufnahmen und **keine** vortrainierten ML-Modelle mitgeliefert.
Testspuren erzeugt `engine/synth.py` synthetisch. Die Rollenerkennung ist merkmalsbasiert. Ein ONNX-Modell
ist optional und muss vom Nutzer selbst bereitgestellt und lizenziert werden.

„VST“ ist eine eingetragene Marke der Steinberg Media Technologies GmbH. Cubase ist ein Produkt von Steinberg.
