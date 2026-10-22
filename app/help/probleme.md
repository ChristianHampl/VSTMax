# Wenn etwas hakt

## Nach dem Klick passiert nichts

Im Task-Manager nach **pythonw.exe** suchen. Der Pfad muss `AI Mix Engineer` enthalten. Steht der Prozess und die CPU arbeitet, warten: der erste Start prüft viele Bibliotheken und kann eine Minute dauern. Beenden nur diesen Prozess, keinen anderen Python-Prozess.

Liegt kein pythonw.exe mehr, ist der Start abgestürzt, ohne ein Fenster zu öffnen. Diese zwei Dateien im Explorer öffnen (Windows-Taste+R):

- `%APPDATA%\AI_Mix_Engineer.launch.pyw.log`
- `%APPDATA%\AI-Mix-Engineer\start_error.txt`

## Die Plug-ins erscheinen nicht in Cubase

Hier **Für Cubase einrichten** klicken und Cubase neu starten. Im Plug-in-Manager *Blockierte Plug-ins* prüfen und neu scannen. Der Ablageort ist der Benutzerordner `AppData\Local\Programs\Common\VST3\AIME.vst3`.

## Keine Spuren im Tab Cubase

Zuerst **Plugin-Link starten**, danach Cubase öffnen oder das Projekt neu laden. Die Plug-ins versuchen jede Sekunde, sich zu verbinden. Erscheint eine Instanz als „(noch kein Name)“, die MixConsole öffnen oder die Spur kurz umbenennen.

## Die Aufnahme ist leer oder hat Lücken

Aufgenommen wird nur, während der Transport läuft. Bitte in Echtzeit abspielen, nicht über den schnellen Export. Lücken meldet das Protokoll unten.

## Gesendete Werte ändern sich nicht

Automation der Spur auf *Read* oder *Off* stellen, sonst überschreibt vorhandene Automation die Werte. Die Instanz muss in der Tabelle stehen.

## MIDI-Bridge verbindet nicht

In loopMIDI müssen die Ports exakt `AIME to Cubase` und `AIME from Cubase` heißen. Cubase neu starten, im MIDI Remote Manager das Skript neu laden, dann in der App erneut verbinden.

## „Nicht kalibriert“ bei Fader oder Send

Cubase hat keinen Anzeigewert zurückgeschickt. Ohne diese Rückmeldung rät die App keinen Pegel. Skript neu laden. Wenn deine Cubase-Version die Anzeige nicht liefert, setzt die App über MIDI nur Transport und Bank, die Klangbearbeitung läuft weiter über die Plug-ins.

## Der Master ist leiser als das Ziel

Absicht. Das Lautheitsziel wäre nur mit hörbarer Überkompression erreichbar gewesen. Der Bericht nennt den Grund. Anderen Mastering-Zweck wählen oder dichter mischen.

## Eine Rolle ist falsch

Gelbe Zeile prüfen und die Rolle von Hand setzen. Danach Vorschau oder Export erneut starten.
