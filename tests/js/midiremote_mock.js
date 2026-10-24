// Führt ein MIDI-Remote-Skript gegen eine aufzeichnende Attrappe von midiremote_api_v1 aus.
// Ausgabe (JSON): benutzte API-Pfade, registrierte Callbacks und per sendMidi gesendete Bytes
// nach dem Auslösen von mOnActivate / mOnTitleChange / mOnDisplayValueChange / mOnProcessValueChange.
// ACHTUNG: Die Attrappe akzeptiert jeden Aufruf. Sie prüft Syntax, Laufzeitfehler und Kodierung,
// nicht, ob Cubase die benutzten API-Elemente tatsächlich anbietet.
'use strict'
const Module = require('module')
const path = require('path')

const used = new Set()
const callbacks = []
const sent = []

function make(p) {
    const store = {}
    const target = function () {}
    return new Proxy(target, {
        get(_, key) {
            if (typeof key === 'symbol')
                return undefined
            if (key in store)
                return store[key]
            const np = p + '.' + key
            used.add(np)
            if (key === 'sendMidi')
                return function (dev, bytes) { sent.push(Array.from(bytes)) }
            const child = make(np)
            store[key] = child
            return child
        },
        set(_, key, value) {
            if (typeof value === 'function' && String(key).startsWith('mOn'))
                callbacks.push({ path: p + '.' + key, fn: value })
            store[key] = value
            used.add(p + '.' + key + '=')
            return true
        },
        apply(_, __, args) {
            used.add(p + '()')
            return make(p + '()')
        },
    })
}

const origLoad = Module._load
Module._load = function (req, parent, isMain) {
    if (req === 'midiremote_api_v1')
        return make('api')
    return origLoad.apply(this, arguments)
}

const script = path.resolve(process.argv[2])
require(script)

const device = {}
const title = process.argv[3] || 'Gesang Ä'
for (const cb of callbacks) {
    if (cb.path.endsWith('.mOnActivate'))
        cb.fn(device)
    else if (cb.path.endsWith('.mOnTitleChange'))
        cb.fn(device, title, 'Volume')
    else if (cb.path.endsWith('.mOnDisplayValueChange'))
        cb.fn(device, '-6.02', 'dB')
    else if (cb.path.endsWith('.mOnProcessValueChange'))
        cb.fn(device, 0.5, 0)
}
process.stdout.write(JSON.stringify({ used: Array.from(used).sort(), callbacks: callbacks.map(c => c.path), sent }))
