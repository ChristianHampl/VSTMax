// AIME Bridge – MIDI-Remote-Skript für Cubase (12+; Ziel: Cubase 15)
//
// Verbindet die AIME-App über zwei virtuelle MIDI-Ports mit der MixConsole:
//   App -> Cubase ("AIME to Cubase"):   Fader, Pan, Mute, Solo, Send 1/2, Bank, Transport
//   Cubase -> App ("AIME from Cubase"): Kanalnamen, Anzeigewerte (z. B. "-6.02 dB") und Werte als SysEx
//
// Installation: Ordner AIME/Bridge nach
//   Dokumente\Steinberg\Cubase\MIDI Remote\Driver Scripts\Local\
// kopieren (scripts/install_midi_remote.ps1). Virtuelle Ports z. B. mit loopMIDI (kostenlos) anlegen.
//
// Verwendete API-Elemente aus midiremote_api_v1. Mit "ZU VERIFIZIEREN" markierte Stellen konnten
// ohne Cubase nicht ausgeführt werden; Fallbacks sind über die Konstanten unten schaltbar.

var midiremote_api = require('midiremote_api_v1')

// ---- BEGIN MAPPING (generiert aus integration/midi_remote/mapping.json, nicht von Hand ändern) ----
var MAP = {"version": 1, "vendor": "AIME", "device": "Bridge", "ports": {"to_cubase": "AIME to Cubase", "from_cubase": "AIME from Cubase"}, "strips": 8, "strip_channel_base": 0, "volume": {"type": "pitchbend", "fallback_cc": 7}, "cc": {"pan": 10, "mute": 20, "solo": 21, "send1": 22, "send2": 23}, "global_channel": 15, "global_cc": {"prev_bank": 100, "next_bank": 101, "start": 110, "stop": 111, "record": 112, "cycle": 113}, "sysex": {"header": [240, 125, 65, 73], "title": 1, "display": 2, "value": 3, "hello": 4}, "params": {"volume": 0, "pan": 1, "mute": 2, "solo": 3, "send1": 4, "send2": 5}}
// ---- END MAPPING ----

// ZU VERIFIZIEREN: bindToPitchBend (14 Bit). Bei Problemen auf false setzen -> Fader über CC (7 Bit).
var USE_PITCHBEND_FOR_VOLUME = true
// ZU VERIFIZIEREN: mOnTitleChange / mOnDisplayValueChange liefern Kanalnamen und Anzeigewerte.
var SEND_FEEDBACK = true

var deviceDriver = midiremote_api.makeDeviceDriver(MAP.vendor, MAP.device, 'AI Mix Engineer')
var midiInput = deviceDriver.mPorts.makeMidiInput()
var midiOutput = deviceDriver.mPorts.makeMidiOutput()

deviceDriver.makeDetectionUnit().detectPortPair(midiInput, midiOutput)
    .expectInputNameEquals(MAP.ports.to_cubase)
    .expectOutputNameEquals(MAP.ports.from_cubase)

var surface = deviceDriver.mSurface

// ---- SysEx-Rückmeldung -------------------------------------------------------------------------
// Texte: jede UTF-16-Codeeinheit als drei 7-Bit-Bytes (verlustfrei auch für Umlaute)
function encodeText(text) {
    var out = []
    var s = String(text || '')
    for (var i = 0; i < s.length && i < 48; ++i) {
        var c = s.charCodeAt(i)
        out.push((c >> 14) & 0x03, (c >> 7) & 0x7F, c & 0x7F)
    }
    return out
}

function sendSysex(activeDevice, kind, strip, param, payload) {
    if (!SEND_FEEDBACK)
        return
    var msg = MAP.sysex.header.slice(0)
    msg.push(kind & 0x7F, strip & 0x7F, param & 0x7F)
    for (var i = 0; i < payload.length; ++i)
        msg.push(payload[i] & 0x7F)
    msg.push(0xF7)
    midiOutput.sendMidi(activeDevice, msg)
}

function attachFeedback(surfaceValue, strip, param) {
    // ZU VERIFIZIEREN: Signaturen gemäß API-Referenz (activeDevice, objectTitle, valueTitle)
    surfaceValue.mOnTitleChange = function (activeDevice, objectTitle, valueTitle) {
        if (param === MAP.params.volume)
            sendSysex(activeDevice, MAP.sysex.title, strip, 0, encodeText(objectTitle))
    }
    // ZU VERIFIZIEREN: (activeDevice, value, units)
    surfaceValue.mOnDisplayValueChange = function (activeDevice, value, units) {
        sendSysex(activeDevice, MAP.sysex.display, strip, param, encodeText(value + (units ? ' ' + units : '')))
    }
    surfaceValue.mOnProcessValueChange = function (activeDevice, value) {
        var v = Math.max(0, Math.min(16383, Math.round(value * 16383)))
        sendSysex(activeDevice, MAP.sysex.value, strip, param, [(v >> 7) & 0x7F, v & 0x7F])
    }
}

// ---- Oberfläche (unsichtbare Bedienelemente, nur für das Mapping) -------------------------------
var strips = []
for (var i = 0; i < MAP.strips; ++i) {
    var ch = MAP.strip_channel_base + i
    var x = i * 2
    var st = {
        volume: surface.makeFader(x, 4, 1, 4),
        pan: surface.makeKnob(x, 0, 1, 1),
        send1: surface.makeKnob(x, 1, 1, 1),
        send2: surface.makeKnob(x, 2, 1, 1),
        mute: surface.makeButton(x + 1, 0, 1, 1),
        solo: surface.makeButton(x + 1, 1, 1, 1)
    }
    if (USE_PITCHBEND_FOR_VOLUME)
        st.volume.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToPitchBend(ch)
    else
        st.volume.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, MAP.volume.fallback_cc)
    st.pan.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, MAP.cc.pan)
    st.send1.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, MAP.cc.send1)
    st.send2.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, MAP.cc.send2)
    st.mute.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, MAP.cc.mute)
    st.solo.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(ch, MAP.cc.solo)

    attachFeedback(st.volume.mSurfaceValue, i, MAP.params.volume)
    attachFeedback(st.pan.mSurfaceValue, i, MAP.params.pan)
    attachFeedback(st.mute.mSurfaceValue, i, MAP.params.mute)
    attachFeedback(st.solo.mSurfaceValue, i, MAP.params.solo)
    attachFeedback(st.send1.mSurfaceValue, i, MAP.params.send1)
    attachFeedback(st.send2.mSurfaceValue, i, MAP.params.send2)
    strips.push(st)
}

function globalButton(cc, x) {
    var b = surface.makeButton(x, 9, 1, 1)
    b.mSurfaceValue.mMidiBinding.setInputPort(midiInput).bindToControlChange(MAP.global_channel, cc)
    return b
}
var btnPrevBank = globalButton(MAP.global_cc.prev_bank, 0)
var btnNextBank = globalButton(MAP.global_cc.next_bank, 1)
var btnStart = globalButton(MAP.global_cc.start, 3)
var btnStop = globalButton(MAP.global_cc.stop, 4)
var btnRecord = globalButton(MAP.global_cc.record, 5)
var btnCycle = globalButton(MAP.global_cc.cycle, 6)

// ---- Mapping auf die MixConsole ----------------------------------------------------------------
var page = deviceDriver.mMapping.makePage('AIME')
var zone = page.mHostAccess.mMixConsole.makeMixerBankZone('AIME Bank')
    .excludeInputChannels()
    .excludeOutputChannels()

for (var k = 0; k < strips.length; ++k) {
    var bankChannel = zone.makeMixerBankChannel()
    var s = strips[k]
    page.makeValueBinding(s.volume.mSurfaceValue, bankChannel.mValue.mVolume)
    page.makeValueBinding(s.pan.mSurfaceValue, bankChannel.mValue.mPan)
    page.makeValueBinding(s.mute.mSurfaceValue, bankChannel.mValue.mMute)
    page.makeValueBinding(s.solo.mSurfaceValue, bankChannel.mValue.mSolo)
    page.makeValueBinding(s.send1.mSurfaceValue, bankChannel.mSends.getByIndex(0).mLevel)
    page.makeValueBinding(s.send2.mSurfaceValue, bankChannel.mSends.getByIndex(1).mLevel)
}

page.makeActionBinding(btnPrevBank.mSurfaceValue, zone.mAction.mPrevBank)
page.makeActionBinding(btnNextBank.mSurfaceValue, zone.mAction.mNextBank)

var transport = page.mHostAccess.mTransport.mValue
page.makeValueBinding(btnStart.mSurfaceValue, transport.mStart)
page.makeValueBinding(btnStop.mSurfaceValue, transport.mStop)
page.makeValueBinding(btnRecord.mSurfaceValue, transport.mRecord)
page.makeValueBinding(btnCycle.mSurfaceValue, transport.mCycleActive).setTypeToggle()

deviceDriver.mOnActivate = function (activeDevice) {
    sendSysex(activeDevice, MAP.sysex.hello, 0, MAP.version, encodeText('AIME Bridge'))
}
