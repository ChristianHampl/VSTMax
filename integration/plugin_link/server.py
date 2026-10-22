"""Plugin-Link-Server: lokale Gegenstelle der AIME-Plug-ins in Cubase.

- lauscht ausschließlich auf 127.0.0.1 (keine Netzwerk-/Cloud-Übertragung)
- führt die Liste der Plug-in-Instanzen (Cubase-Kanalname, Typ, Samplerate, Latenz)
- nimmt auf Wunsch das Eingangssignal aller Instanzen auf (Capture), ausgerichtet an der
  Cubase-Projektposition, und schreibt es direkt auf die Festplatte (kein RAM-Engpass bei langen Songs)
- sendet Parameterwerte (Klarwerte, IDs aus plugin_params.json) an einzelne Instanzen
"""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from . import protocol as pr

EventCb = Callable[[str, dict], None]


def configured_port() -> int:
    try:
        v = int(os.environ.get("AIME_LINK_PORT", pr.DEFAULT_PORT))
        return v if 0 < v < 65536 else pr.DEFAULT_PORT
    except ValueError:
        return pr.DEFAULT_PORT


@dataclass
class Instance:
    id: int
    plugin: str
    channel_name: str = ""
    channel_uid: str = ""
    label: str = ""
    sample_rate: float = 0.0
    channels: int = 0
    latency: int = 0
    connection: int = 0

    @property
    def hex_id(self) -> str:
        return f"{self.id:016x}"

    def to_dict(self) -> dict:
        return {"instance": self.hex_id, "plugin": self.plugin, "channel_name": self.channel_name,
                "channel_uid": self.channel_uid, "label": self.label, "sample_rate": self.sample_rate,
                "channels": self.channels, "latency": self.latency}


class _CaptureSink:
    """Rohdaten je Instanz in eine Temp-Datei; Index (Projektposition, Frames, Offset) im Speicher."""

    def __init__(self, path: Path):
        self.path = path
        self.f = open(path, "wb")
        self.index: list[tuple[int, int, int]] = []
        self.channels = 0
        self.offset = 0

    def add(self, pos: int, x: np.ndarray):
        self.channels = max(self.channels, x.shape[1])
        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)
        b = np.ascontiguousarray(x, dtype="<f4").tobytes()
        self.f.write(b)
        self.index.append((pos, x.shape[0], self.offset))
        self.offset += len(b)

    def close(self):
        if not self.f.closed:
            self.f.close()


@dataclass
class CaptureResult:
    folder: str
    start_pos: int | None
    end_pos: int | None
    files: dict[str, str] = field(default_factory=dict)      # Instanz (hex) -> WAV-Pfad
    instances: dict[str, dict] = field(default_factory=dict)  # Instanz (hex) -> Metadaten
    warnings: list[str] = field(default_factory=list)


class LinkServer:
    def __init__(self, port: int | None = None, on_event: EventCb | None = None):
        self.port = configured_port() if port is None else port
        self.on_event = on_event
        self._lock = threading.RLock()
        self._instances: dict[int, Instance] = {}
        self._conns: dict[int, socket.socket] = {}
        self._next_conn = 1
        self._srv: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._running = threading.Event()
        self._capture_on = False
        self._sinks: dict[int, _CaptureSink] = {}
        self._capture_dir: Path | None = None
        self._changed = threading.Condition(self._lock)
        self.stats = {"audio_chunks": 0, "dropped_not_playing": 0, "protocol_errors": 0}
        self.last_audio = 0.0      # monotonic: letzter aufgenommener Chunk (Wiedergabe läuft)
        self.last_stopped = 0.0    # monotonic: letzter Chunk mit gestopptem Transport

    # ---------------------------------------------------------------- Lebenszyklus
    def start(self) -> "LinkServer":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.port))
        s.listen(8)
        s.settimeout(0.2)
        self.port = s.getsockname()[1]
        self._srv = s
        self._running.set()
        t = threading.Thread(target=self._accept_loop, name="aime-link-accept", daemon=True)
        t.start()
        self._threads.append(t)
        return self

    def stop(self):
        self._running.clear()
        if self._srv:
            self._srv.close()
        with self._lock:
            for c in self._conns.values():
                try:
                    c.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                c.close()
        for t in self._threads:
            t.join(timeout=2)
        with self._lock:
            for s in self._sinks.values():
                s.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ---------------------------------------------------------------- Abfragen
    def instances(self) -> list[Instance]:
        with self._lock:
            return list(self._instances.values())

    def wait_for(self, predicate: Callable[[list[Instance]], bool], timeout: float = 10.0) -> bool:
        end = time.monotonic() + timeout
        with self._changed:
            while not predicate(list(self._instances.values())):
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._changed.wait(left)
        return True

    @property
    def connected(self) -> bool:
        with self._lock:
            return bool(self._conns)

    # ---------------------------------------------------------------- Befehle
    def set_params(self, instance: int, values: dict[int, float]) -> bool:
        with self._lock:
            inst = self._instances.get(instance)
            conn = self._conns.get(inst.connection) if inst else None
        if conn is None or not values:
            return False
        return self._send(conn, pr.encode_set_params(instance, values))

    def ping(self):
        self._broadcast(pr.frame(pr.PING))

    def start_capture(self, folder: str | Path):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for s in self._sinks.values():
                s.close()
            self._sinks = {}
            self._capture_dir = folder
            self._capture_on = True
        self._broadcast(pr.encode_capture(True))
        self._emit("capture", {"on": True, "folder": str(folder)})

    def stop_capture(self, settle_s: float = 0.3) -> CaptureResult:
        self._broadcast(pr.encode_capture(False))
        time.sleep(settle_s)  # bereits gesendete Chunks noch annehmen
        with self._lock:
            self._capture_on = False
            sinks, self._sinks = self._sinks, {}
            folder = self._capture_dir
            insts = dict(self._instances)
        for s in sinks.values():
            s.close()
        res = self._assemble(folder, sinks, insts)
        self._emit("capture", {"on": False, "files": res.files})
        return res

    # ---------------------------------------------------------------- Capture -> WAV
    def _assemble(self, folder: Path | None, sinks: dict[int, _CaptureSink], insts: dict[int, Instance]) -> CaptureResult:
        all_idx = [(p, n) for s in sinks.values() for p, n, _ in s.index]
        if folder is None or not all_idx:
            return CaptureResult(str(folder), None, None, warnings=["Keine Audiodaten empfangen (lief die Wiedergabe?)"])
        start = min(p for p, _ in all_idx)
        end = max(p + n for p, n in all_idx)
        res = CaptureResult(str(folder), start, end)
        rates = {insts[i].sample_rate for i in sinks if i in insts and insts[i].sample_rate}
        if len(rates) > 1:
            res.warnings.append(f"Instanzen melden unterschiedliche Sampleraten: {sorted(rates)}")
        used: set[str] = set()
        for iid, s in sinks.items():
            inst = insts.get(iid)
            sr = int(inst.sample_rate) if inst and inst.sample_rate else 48000
            base = _safe_name(inst.channel_name if inst and inst.channel_name else f"instance_{iid:016x}")
            name = base
            k = 2
            while name.lower() in used or (folder / f"{name}.wav").exists():
                name = f"{base} ({k})"
                k += 1
            used.add(name.lower())
            n_total = end - start
            buf = np.lib.format.open_memmap(folder / f".{name}.tmp.npy", mode="w+", dtype=np.float32, shape=(n_total, 2))
            raw = np.memmap(s.path, dtype="<f4", mode="r") if s.offset else np.zeros(0, np.float32)
            covered = 0
            for pos, frames, off in s.index:  # spätere Durchläufe überschreiben frühere (Loop/Neustart)
                a = pos - start
                buf[a:a + frames] = np.asarray(raw[off // 4: off // 4 + frames * 2]).reshape(frames, 2)
                covered += frames
            out = folder / f"{name}.wav"
            ch = 1 if s.channels == 1 else 2
            with sf.SoundFile(out, "x", samplerate=sr, channels=ch, subtype="FLOAT") as w:
                for o in range(0, n_total, 1 << 16):
                    blk = np.asarray(buf[o:o + (1 << 16)])
                    w.write(blk[:, :1] if ch == 1 else blk)
            del buf, raw
            (folder / f".{name}.tmp.npy").unlink(missing_ok=True)
            s.path.unlink(missing_ok=True)
            hid = f"{iid:016x}"
            res.files[hid] = str(out)
            res.instances[hid] = (inst.to_dict() if inst else {"instance": hid}) | {"covered_frames": covered}
            if covered < 0.9 * n_total:
                res.warnings.append(f"{name}: nur {100 * covered / n_total:.0f} % des Bereichs aufgenommen")
        return res

    # ---------------------------------------------------------------- Netzwerk
    def _accept_loop(self):
        while self._running.is_set():
            try:
                c, addr = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if addr[0] != "127.0.0.1":
                c.close()
                continue
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                cid = self._next_conn
                self._next_conn += 1
                self._conns[cid] = c
                capture = self._capture_on
            if capture:
                self._send(c, pr.encode_capture(True))
            t = threading.Thread(target=self._conn_loop, args=(cid, c), name=f"aime-link-{cid}", daemon=True)
            t.start()
            self._threads.append(t)

    def _conn_loop(self, cid: int, c: socket.socket):
        reader = pr.FrameReader()
        c.settimeout(0.5)
        try:
            while self._running.is_set():
                try:
                    data = c.recv(1 << 16)
                except socket.timeout:
                    continue
                if not data:
                    break
                for t, p in reader.feed(data):
                    try:
                        self._handle(cid, t, p)
                    except pr.ProtocolError:
                        self.stats["protocol_errors"] += 1
        except (OSError, pr.ProtocolError):
            pass
        finally:
            with self._changed:
                self._conns.pop(cid, None)
                gone = [i for i, v in self._instances.items() if v.connection == cid]
                for i in gone:
                    self._instances.pop(i)
                self._changed.notify_all()
            c.close()
            self._emit("disconnected", {"connection": cid, "instances": [f"{i:016x}" for i in gone]})

    def _handle(self, cid: int, t: int, p: bytes):
        if t == pr.AUDIO:
            ch = pr.decode_audio(p)
            with self._lock:
                if not self._capture_on or self._capture_dir is None:
                    return
                if not ch.playing or ch.pos < 0:
                    self.stats["dropped_not_playing"] += 1
                    self.last_stopped = time.monotonic()
                    return
                s = self._sinks.get(ch.instance)
                if s is None:
                    s = self._sinks[ch.instance] = _CaptureSink(self._capture_dir / f".{ch.instance:016x}.raw")
                s.add(ch.pos, ch.samples)
                self.stats["audio_chunks"] += 1
                self.last_audio = time.monotonic()
        elif t in (pr.INSTANCE_ADD, pr.INSTANCE_UPDATE):
            d = pr.decode_json(p)
            iid = pr.instance_int(d["instance"])
            with self._changed:
                inst = Instance(iid, d.get("plugin", ""), d.get("channel_name", ""), d.get("channel_uid", ""),
                                d.get("label", ""), float(d.get("sample_rate", 0)), int(d.get("channels", 0)),
                                int(d.get("latency", 0)), cid)
                self._instances[iid] = inst
                self._changed.notify_all()
            self._emit("instance", inst.to_dict())
        elif t == pr.INSTANCE_REMOVE:
            d = pr.decode_json(p)
            with self._changed:
                self._instances.pop(pr.instance_int(d["instance"]), None)
                self._changed.notify_all()
            self._emit("instance_removed", d)
        elif t == pr.HELLO:
            d = pr.decode_json(p)
            if d.get("protocol") != pr.PROTOCOL_VERSION:
                self._emit("warning", {"message": f"Plug-in spricht Protokoll {d.get('protocol')}, "
                                                  f"App erwartet {pr.PROTOCOL_VERSION}"})
            self._emit("hello", d)

    def _send(self, c: socket.socket, data: bytes) -> bool:
        try:
            with self._lock:
                c.sendall(data)
            return True
        except OSError:
            return False

    def _broadcast(self, data: bytes):
        with self._lock:
            conns = list(self._conns.values())
        for c in conns:
            self._send(c, data)

    def _emit(self, kind: str, data: dict):
        if self.on_event:
            try:
                self.on_event(kind, data)
            except Exception:
                pass


def _safe_name(name: str) -> str:
    s = "".join(ch if ch.isalnum() or ch in " -_()" else "_" for ch in name).strip()
    return s[:80] or "track"
