# DSP-Design der AIME-Plug-ins

Header-only C++17 in `dsp/core/` (keine Abhängigkeiten). Dieselben Bausteine nutzen die VST3-Plug-ins,
der Offline-Renderer `aime_render` und die DSP-Tests. Die Python-Offline-Engine (`engine/dsp.py`)
implementiert dieselben Formeln.

## Regeln

- `prepare()` darf Speicher anfordern, `process*()` nie. Die DSP-Tests prüfen das mit einem globalen
  Allokationszähler.
- Ausgänge werden gegen NaN/Inf geschützt (`sanitize`).
- Parameteränderungen werden geglättet: lineare Rampen bzw. EQ-Koeffizienten in 32-Sample-Schritten.
  Beim Aktivieren mit geladenem Zustand gibt es keine Rampe.
- Konstante, gemeldete Latenz. Bypass mischt latenzrichtig (Dry-Pfad verzögert).

## Bausteine

| Baustein | Verfahren |
|---|---|
| EQ | Biquads nach RBJ Audio EQ Cookbook (TDF II): Bell, Low/High-Shelf, HPF/LPF (12 oder 24 dB/Okt.) |
| Pegeldetektor | Gleitendes Maximum bzw. Mittel über 32 Samples (entspricht `ENV_BLOCK` der Offline-Engine) |
| Kompressor | Feed-forward, Peak-Detektor (Maximum über Kanäle), Soft-Knee, Attack/Release auf der Gain Reduction, Makeup, Dry/Wet |
| Gate | Expander mit Range, Attack, Hold, Release |
| De-Esser | Detektor = Hochpass ab `freq`. Wirkung = Überblendung zwischen trockenem Signal und High-Shelf mit −Range. Oberhalb `freq` entspricht die Absenkung genau der momentanen Gain Reduction |
| Dynamisches Band (2×) | `x + (g−1)·bandpass(x)`, Detektor intern oder über den Sidechain-Eingang (z. B. Gitarren-Ducking durch Vocals) |
| Sättigung | tanh mit 2× Oversampling (Halbband-FIR, 31 Taps), konstante Latenz 15 Samples, Dry phasengleich verzögert |
| True-Peak | 4× Oversampling, Polyphasen-FIR (24 Taps je Phase) |
| Limiter | Lookahead (1,5 ms) mit True-Peak-Detektor im Regelpfad |
| Lautheit | BS.1770-4 K-Filter, Momentary 400 ms, Short-term 3 s (Anzeige im Master) |

## Strips (= Plug-ins)

- **AIME Channel** (Stereo/Mono, Stereo-Sidechain): DC-Filter → Rechts invertieren → Polarität →
  Laufzeitausgleich (0–50 ms) → Trim → Gate → HPF (2 Stufen) → LPF → EQ (8 Bänder) → Dyn-Band (2) →
  Kompressor → De-Esser → Sättigung → Output, Breite, Pan. Latenz 15 Samples.
- **AIME Bus**: Input → Parallelzweig (Kompressor + Sättigung, Anteil) ‖ Hauptpfad (verzögert) → Bus-Kompressor →
  Sättigung → Output. Latenz 30 Samples.
- **AIME Master**: Input → EQ (4) → Glue-Kompressor (Makeup) → Limiter-Drive → True-Peak-Limiter → Output,
  mit Lautheits- und True-Peak-Anzeige. Latenz 84 Samples bei 48 kHz (lookahead-abhängig).

Parameter: Channel 78, Bus 19, Master 34 (davon 2/1/4 Anzeigewerte). Definition in
`integration/protocol/plugin_params.json`. IDs bleiben stabil, neue Parameter bekommen neue IDs.

## Zustand / Presets

Format `AIMS`: Magic, Version, Anzahl, Paare (u32 ID, f64 Klarwert), Label. Unbekannte IDs werden
ignoriert (vorwärtskompatibel), fehlende behalten ihren Default. `.vstpreset` enthält diesen Zustand
als `Comp`-Chunk. Getestet in beiden Richtungen (Python schreibt, Plug-in liest).

## Gemessene Werte (Linux, GCC 13, Release; siehe docs/results)

- CPU (Stereo, 48 kHz, 10 s Audio): Channel 3,2 %, Bus 4,0 %, Master 1,2 % eines Kerns in Echtzeit.
- Python ↔ C++: Filter/Gain < 1e-4 absolut; Kompressor-Lautheit < 0,5 dB (gemessen ≤ 0,35);
  De-Esser/Dyn-Band/Gate < 0,1 dB Lautheit; Master-Kette < 0,75 LU.
- Plug-in-Binary ↔ C++-DSP: Abweichung < 2e-4 bei allen drei Plug-ins (gleiche Eingangsdaten,
  `aime_host_render` mit 512er-Blöcken).
- Limiter: Bei realistischem Material liegt der True Peak innerhalb von 0,03 dB über der Grenze.
  Beim Rausch-Stresstest wurden bis zu 0,53 dB Überschreitung gemessen (Referenz: 16× Oversampling).
  Der Test toleriert 0,7 dB,
  das ist eine bekannte Grenze (siehe STATUS.md).
