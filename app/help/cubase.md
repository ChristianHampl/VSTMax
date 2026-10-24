# Cubase einmal einrichten

Das machst du ein Mal und speicherst es als Projektvorlage. Danach gilt es für jeden Song.

## Spuren

| Was | Einstellung |
|---|---|
| Jede Audiospur | Insert 1: **AIME Channel**. Name der Spur = Name der Aufnahme, zum Beispiel „Kick In“ oder „Gtr Rhythm L“ |
| Gruppenkanäle | `Drums`, `Bass`, `Guitars`, `Vocals`, `Keys`. Insert: **AIME Bus** |
| FX-Kanal 1 | Hall, zum Beispiel RoomWorks. **Send 1** jeder Spur zeigt hierhin |
| FX-Kanal 2 | Delay, temposynchron. **Send 2** jeder Spur zeigt hierhin |
| Stereo Out | Insert 1: **AIME Bus**, Insert 2: **AIME Master** |

Sends bei allen Spuren einschalten und auf −∞ stellen. Den Pegel setzt die App. Fader auf 0 dB, Pan auf Mitte. Pegel und Pan regelt AIME Channel, damit nichts doppelt wirkt.

Optional: Beim AIME Channel der Gitarren den Sidechain-Eingang aktivieren und von der Vocal-Spur speisen. Die App nutzt das, wenn der Plan ein Ducking vorsieht.

## Pro Song

1. Aufnahmen importieren oder die vorhandenen Spuren wie oben benennen.
2. Diese App: Tab **Cubase**, **Plugin-Link starten**. In der Tabelle erscheinen die Spuren mit Namen.
3. **Automation-Write aus**. Positionszeiger an den Songanfang.
4. **Alles automatisch**. Die App spielt den Song ab (oder du drückst selbst Play), nimmt jede Spur auf, rechnet den Mix und schickt die Werte zurück.
5. Anhören. Rollen oder Klangcharakter ändern und erneut senden. **Letztes Senden rückgängig** stellt den Stand davor wieder her.

Vor jedem Senden speichert die App einen Snapshot. Von Hand in Cubase geänderte Regler kennt sie nicht.
