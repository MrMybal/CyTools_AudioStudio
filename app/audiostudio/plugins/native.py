"""AudioStudio native worker bridge. No third-party binary is loaded in Python.

Versioned x64 shared-memory ABI, inherited from CyDAW. Parameters are normalised
[0,1]; displayed text is supplied by the plugin. State is opaque, capped at 4 MiB.
The stereo editor hosts audio effects; instrument/MIDI sequencing is not supplied.
"""
import atexit
import ctypes
import json
import mmap
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
import threading
import time
import weakref

import numpy as np
from ..paths import APP

SIZE = 4414912
FRAME_CAPACITY = 2048
STATE_OFFSET = 220544
STATE_CAPACITY = 4 * 1024 * 1024
_instances = weakref.WeakSet()


def worker_executable():
    machine = platform.machine()
    if machine.lower() in ('amd64', 'x86_64'):
        machine = 'AMD64' if os.name == 'nt' else 'x86_64'
    name = 'AudioStudioPluginWorker' + ('.exe' if os.name == 'nt' else '')
    path = APP / 'native' / 'bin' / (platform.system() + '-' + machine) / name
    if not path.is_file():
        raise RuntimeError('Native plugin host missing. Build it with app/scripts/build_plugin_host.py: ' + str(path))
    return path


def probe(path):
    """One crash/timeout affects this file only, never the rest of a scan."""
    with tempfile.TemporaryDirectory(prefix='audiostudio-probe-') as folder:
        output = Path(folder) / 'probe.json'
        result = subprocess.run([str(worker_executable()), '--probe-plugin', str(Path(path).resolve()), '--output', str(output)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not output.exists():
            raise RuntimeError('Plugin probe failed: ' + result.stderr.decode('utf-8', 'replace')[-2000:])
        data = json.loads(output.read_text('utf-8-sig'))
        rows = data if isinstance(data, list) else data.get('plugins', [data])
        errors = [r.get('error') for r in rows if r.get('error')]
        if errors:
            raise RuntimeError('; '.join(errors))
        return rows


class Parameter:
    def __init__(self, owner, index, label, value, units, text, flags):
        self.owner = weakref.proxy(owner)
        self.index, self.label, self.units, self.text = index, label, units, text
        self.range = (0.0, 1.0)
        self.type = bool if flags & 4 else float
        self.valid_values = None
        self._value = value

    @property
    def raw_value(self):
        return self._value

    @raw_value.setter
    def raw_value(self, value):
        value = float(value)
        if not np.isfinite(value):
            raise ValueError('Plugin parameter must be finite')
        value = max(0.0, min(1.0, value))
        self.owner._command(2, self.index, value)
        self._value = value


class NativePlugin:
    def __init__(self, path, plugin_name=None, metadata=None):
        self.path = str(Path(path).resolve())
        rows = [metadata] if metadata else probe(self.path)
        row = next((r for r in rows if plugin_name in (r.get('name'), r.get('pluginId'))), None) if plugin_name else rows[0]
        if row is None:
            raise ValueError('Plugin not found in bundle: ' + str(plugin_name))
        self.metadata = row
        self.name = row.get('name') or Path(path).stem
        self.manufacturer_name, self.version = row.get('manufacturer', ''), row.get('version', '')
        self.category = row.get('category', '')
        self.is_instrument = bool(row.get('instrument'))
        self.is_effect = not self.is_instrument
        self.parameters = {}
        self._lock = threading.RLock()
        self._temp = None
        self._map = None
        self._process = None
        self._events = None
        self._rate = 48000
        self._position = 0
        self._pending_state = None
        self._start()
        self.refresh()
        _instances.add(self)

    def _get(self, offset, fmt='I'):
        return struct.unpack_from('<' + fmt, self._map, offset)[0]

    def _put(self, offset, value, fmt='I'):
        struct.pack_into('<' + fmt, self._map, offset, value)

    def _text(self, offset, size):
        return self._map[offset:offset + size].split(b'\0')[0].decode('utf-8', 'replace')

    def _start(self):
        self._temp = tempfile.TemporaryDirectory(prefix='audiostudio-plugin-')
        shared = Path(self._temp.name) / 'audio.bin'
        with shared.open('wb') as handle:
            handle.truncate(SIZE)
        with shared.open('r+b') as handle:
            self._map = mmap.mmap(handle.fileno(), SIZE)
        self._put(0, 0x43594457)
        self._put(4, 6, 'H')
        # Descriptor selects one plugin ID in a multi-plugin CLAP/LV2 bundle.
        descriptor = Path(self._temp.name) / 'selected.cyplugin'
        descriptor.write_text(json.dumps({'file': self.path, 'id': self.metadata.get('pluginId', '')}), 'utf-8')
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
            kernel.CreateEventW.restype = ctypes.c_void_p
            kernel.SetEvent.argtypes = [ctypes.c_void_p]
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            base = 'Local\\AudioStudioPlugin_' + Path(self._temp.name).name
            handles = [kernel.CreateEventW(None, False, False, base + suffix) for suffix in ('_request', '_response')]
            if not all(handles):
                for handle in handles:
                    if handle:
                        kernel.CloseHandle(handle)
                raise ctypes.WinError(ctypes.get_last_error())
            self._events = (kernel, *handles)
        args = [str(worker_executable()), '--realtime-plugin', str(descriptor), '--shared-file', str(shared),
                '--parent-pid', str(os.getpid()), '--sample-rate', str(self._rate), '--block-size', str(FRAME_CAPACITY), '--channels', '2']
        self._process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            self._wait(lambda: self._get(56) == 2, 30)
        except Exception:
            self.close()
            raise

    def _wait(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            if self._process.poll() is not None or self._get(56) == 3:
                raise RuntimeError('Plugin worker stopped: ' + self._text(108, 512))
            if time.monotonic() >= deadline:
                raise TimeoutError('Plugin worker did not respond: ' + self.name)
            if self._events:
                self._events[0].WaitForSingleObject(self._events[2], min(20, max(1, int((deadline - time.monotonic()) * 1000))))
            else:
                time.sleep(0.0001)

    def _command(self, command, index=0, value=0.0):
        with self._lock:
            self._put(80, command)
            self._put(88, index)
            self._put(92, value, 'f')
            sequence = self._get(32, 'Q') + 1
            self._put(32, sequence, 'Q')
            if self._events:
                self._events[0].SetEvent(self._events[1])
            self._wait(lambda: self._get(40, 'Q') == sequence)
            if self._get(84, 'i'):
                raise RuntimeError(self._text(620, 256))

    def refresh(self):
        with self._lock:
            self._command(1)
            for i in range(min(512, self._get(100))):
                off = 876 + i * 172
                key = 'p' + str(i)
                p = self.parameters.get(key)
                value = self._get(off + 8, 'f')
                if p is None:
                    p = Parameter(self, i, self._text(off + 12, 96), value, self._text(off + 108, 32), self._text(off + 140, 32), self._get(off + 4))
                    self.parameters[key] = p
                p._value = value
                p.text = self._text(off + 140, 32)

    def __getattr__(self, key):
        params = self.__dict__.get('parameters', {})
        if key in params:
            p = params[key]
            return bool(p.raw_value >= .5) if p.type is bool else p.raw_value
        raise AttributeError(key)

    def __setattr__(self, key, value):
        params = self.__dict__.get('parameters', {})
        if key in params:
            params[key].raw_value = value
        else:
            object.__setattr__(self, key, value)

    @property
    def reported_latency_samples(self):
        return self._get(76) if self._map is not None else 0

    @property
    def raw_state(self):
        with self._lock:
            self._command(3)
            size = self._get(96)
            if size > STATE_CAPACITY:
                raise ValueError('Plugin state too large')
            native = self._map[STATE_OFFSET:STATE_OFFSET + size]
            self.refresh()
            # Some formats apply host parameter changes at the next audio block.
            # Keep their current host values as well as the opaque native payload.
            values = b''.join(struct.pack('<If', p.index, p.raw_value) for p in self.parameters.values())
            return b'ASPH1\0' + struct.pack('<I', len(self.parameters)) + values + native

    @raw_state.setter
    def raw_state(self, state):
        state = bytes(state)
        values = []
        if state.startswith(b'ASPH1\0'):
            if len(state) < 10:
                raise ValueError('Truncated native plugin state')
            count = struct.unpack_from('<I', state, 6)[0]
            if count > 512 or len(state) < 10 + count * 8:
                raise ValueError('Invalid native plugin state parameters')
            values = [struct.unpack_from('<If', state, 10 + i * 8) for i in range(count)]
            if any(not np.isfinite(v) or not 0 <= v <= 1 or i >= 512 for i, v in values):
                raise ValueError('Invalid native plugin state parameter value')
            state = state[10 + count * 8:]
        if len(state) > STATE_CAPACITY:
            raise ValueError('Plugin state exceeds 4 MiB')
        with self._lock:
            self._map[STATE_OFFSET:STATE_OFFSET + len(state)] = state
            self._put(96, len(state))
            self._command(4)
            self.refresh()
            for index, value in values:
                parameter = self.parameters.get('p' + str(index))
                if parameter is not None:
                    parameter.raw_value = value

    def reset(self):
        with self._lock:
            self._command(9)
            self._position = 0

    def __call__(self, audio, samplerate, reset=True):
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.ndim == 1:
            audio = audio[None, :]
        if audio.ndim != 2 or not 1 <= audio.shape[0] <= 8:
            raise ValueError('Plugin audio needs 1 to 8 planar channels')
        if self.is_instrument:
            raise ValueError('This audio editor hosts effects; MIDI instrument sequencing is unavailable')
        with self._lock:
            if float(samplerate) != self._rate:
                state = self.raw_state
                values = {k: p.raw_value for k, p in self.parameters.items()}
                self.close()
                self._rate = float(samplerate)
                self._start()
                self.raw_state = state
                for key, value in values.items():
                    self.parameters[key].raw_value = value
            if reset:
                self.reset()
            output = np.empty_like(audio)
            for start in range(0, audio.shape[1], FRAME_CAPACITY):
                n = min(FRAME_CAPACITY, audio.shape[1] - start)
                inp = np.ndarray((8, FRAME_CAPACITY), np.float32, buffer=self._map, offset=89472)
                inp.fill(0)
                inp[:audio.shape[0], :n] = audio[:, start:start + n]
                del inp
                self._put(64, n)
                self._put(68, audio.shape[0], 'H')
                self._put(70, audio.shape[0], 'H')
                self._put(4414848, self._position / self._rate, 'd')
                self._put(4414856, 120.0, 'd')
                self._put(4414864, self._position / self._rate * 2.0, 'd')
                self._put(4414872, 1)
                self._put(4414876, 4)
                self._put(4414880, 4)
                sequence = self._get(8, 'Q') + 1
                self._put(8, sequence, 'Q')
                if self._events:
                    self._events[0].SetEvent(self._events[1])
                try:
                    self._wait(lambda: self._get(16, 'Q') == sequence, .25)
                except Exception:
                    self.close()
                    raise
                out = np.ndarray((8, FRAME_CAPACITY), np.float32, buffer=self._map, offset=155008)
                output[:, start:start + n] = out[:audio.shape[0], :n]
                del out
                self._position += n
            return output

    def show_editor(self):
        self._command(5)
        # Native worker publishes window visibility before the next command is acknowledged.
        self._command(1)
        while self._get(6, 'H'):
            if self._process.poll() is not None:
                raise RuntimeError('Plugin editor worker stopped')
            time.sleep(.04)
        self.refresh()

    def close(self):
        process = self.__dict__.get('_process')
        mapping = self.__dict__.get('_map')
        if process is not None:
            if mapping is not None:
                self._put(60, 1)
                if self._events:
                    self._events[0].SetEvent(self._events[1])
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            self._process = None
        if mapping is not None:
            mapping.close()
            self._map = None
        if self.__dict__.get('_events'):
            kernel, request, response = self._events
            kernel.CloseHandle(request)
            kernel.CloseHandle(response)
            self._events = None
        temp = self.__dict__.get('_temp')
        if temp is not None:
            temp.cleanup()
            self._temp = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _close_all():
    for instance in list(_instances):
        instance.close()

atexit.register(_close_all)
