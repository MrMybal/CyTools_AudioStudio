"""Transport: plays the document mix through PortAudio, records from an input device.

The audio callback renders blocks through the player's ``Renderer`` (track inserts, automation,
master chain) so every change is heard immediately and the playhead is the callback's own
frame counter. Recording appends float32 blocks from an InputStream into a buffer that becomes
a new track when stopped. Device choices and the buffer size are persisted in
data/settings/audio.json.
"""
import json
from pathlib import Path
import threading
import time

import numpy as np

from audiostudio.paths import SETTINGS
from audiostudio.editor.renderer import Renderer

SETTINGS_PATH = SETTINGS / 'audio.json'
BUFFER_SIZES = (256, 512, 1024, 2048, 4096)


def list_devices():
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        apis = sd.query_hostapis()
        result = []
        for index, device in enumerate(devices):
            result.append({'index': index, 'name': device['name'], 'api': apis[device['hostapi']]['name'], 'inputs': int(device['max_input_channels']),
                           'outputs': int(device['max_output_channels']), 'samplerate': float(device['default_samplerate'])})
        return result
    except Exception:
        return []


def load_settings():
    try:
        return json.loads(SETTINGS_PATH.read_text('utf-8-sig'))
    except (OSError, ValueError):
        return {}


def save_settings(values):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(values, indent=2), 'utf-8')


class Player:
    def __init__(self, document):
        self.document = document
        self.stream = None
        self.frame = 0
        self.playing = False
        self.loop = False
        self.volume = 1.0
        self.error = ''
        self.lock = threading.Lock()
        settings = load_settings()
        self.output_device = settings.get('outputDevice')     # index or None = default
        self.input_device = settings.get('inputDevice')
        self.buffer_size = int(settings.get('bufferSize', 1024)) if int(settings.get('bufferSize', 1024)) in BUFFER_SIZES else 1024
        self.renderer = Renderer(document)
        self.peak = (0.0, 0.0)
        self.load = 0.0                                      # callback time / block time
        self.recording = None                                # list of blocks while recording
        self.record_stream = None
        self.record_channels = 2
        self.record_started_frame = 0
        self.record_monitor = False

    # ------------------------------------------------------------------ playback
    def _callback(self, out, frames, time_info, status):
        with self.lock:
            document = self.document
            position = self.frame
            low, high = 0, document.frames
            if self.loop and document.selection:
                a, b = sorted(document.selection)
                low, high = document.seconds_to_frame(a), document.seconds_to_frame(b)
                if position < low or position >= high:
                    position = low
            if not self.playing or high <= low:
                out[:] = 0
                self.peak = (0.0, 0.0)
                return
            count = min(frames, high - position)
            started = time.perf_counter()
            try:
                block = self.renderer.render(position, count, channels=out.shape[1]) * self.volume if count > 0 else np.zeros((out.shape[1], 0), np.float32)
            except Exception as exc:                      # never let the audio thread die
                self.error = 'Render error: ' + str(exc)
                block = np.zeros((out.shape[1], count), np.float32)
            self.load = 0.8 * self.load + 0.2 * ((time.perf_counter() - started) / max(1e-6, frames / float(document.samplerate)))
            out[:count] = block.T
            out[count:] = 0
            position += count
            if position >= high:
                if self.loop:
                    position = low
                else:
                    self.playing = False
            self.frame = position
            self.peak = (float(np.max(np.abs(out[:, 0]))) if out.size else 0.0, float(np.max(np.abs(out[:, 1]))) if out.shape[1] > 1 and out.size else 0.0)

    def _open(self):
        import sounddevice as sd
        rate = self.document.samplerate
        if self.stream is not None and (int(self.stream.samplerate) != rate or (self.stream.device != self.output_device and self.output_device is not None)):
            self._close()
        if self.stream is None:
            self.stream = sd.OutputStream(samplerate=rate, channels=2, dtype='float32', callback=self._callback, blocksize=self.buffer_size, latency='low', device=self.output_device)
            self.stream.start()

    def _close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def play(self, from_seconds=None):
        if from_seconds is not None:
            self.seek(from_seconds)
        try:
            with self.lock:
                if self.frame >= self.document.frames:
                    self.frame = self.document.seconds_to_frame(self.document.selection[0]) if self.document.selection else 0
                self.playing = True
            self._open()
            self.error = ''
        except Exception as exc:
            self.playing = False
            self.error = 'Audio output unavailable: ' + str(exc)

    def pause(self):
        self.playing = False

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def stop(self):
        self.playing = False
        with self.lock:
            self.frame = self.document.seconds_to_frame(self.document.selection[0]) if self.document.selection else self.document.seconds_to_frame(self.document.cursor)

    def seek(self, seconds):
        with self.lock:
            self.frame = max(0, min(self.document.frames, self.document.seconds_to_frame(seconds)))

    @property
    def position(self):
        return self.document.frame_to_seconds(self.frame)

    def set_output_device(self, index):
        self.output_device = index
        settings = load_settings()
        settings['outputDevice'] = index
        save_settings(settings)
        self._close()
        if self.playing:
            self.play()

    def set_input_device(self, index):
        self.input_device = index
        settings = load_settings()
        settings['inputDevice'] = index
        save_settings(settings)

    def set_buffer_size(self, frames):
        self.buffer_size = int(frames)
        settings = load_settings()
        settings['bufferSize'] = int(frames)
        save_settings(settings)
        self._close()
        if self.playing:
            self.play()

    def reset_renderer(self):
        """Fresh processor states (after a session load or a big structural change)."""
        with self.lock:
            self.renderer = Renderer(self.document)

    # ------------------------------------------------------------------ recording
    def start_recording(self, channels=2):
        import sounddevice as sd
        if self.record_stream is not None:
            return
        self.recording = []
        self.record_channels = channels
        self.record_started_frame = self.document.seconds_to_frame(self.document.cursor)
        rate = self.document.samplerate

        def callback(indata, frames, time_info, status):
            self.recording.append(np.array(indata, dtype=np.float32, copy=True))
            self.peak = (float(np.max(np.abs(indata[:, 0]))) if indata.size else 0.0, float(np.max(np.abs(indata[:, -1]))) if indata.size else 0.0)
        try:
            self.record_stream = sd.InputStream(samplerate=rate, channels=channels, dtype='float32', callback=callback, device=self.input_device, latency='low')
            self.record_stream.start()
            self.error = ''
            if self.document.frames > self.record_started_frame and self.record_monitor:
                self.play(self.document.cursor)
        except Exception as exc:
            self.record_stream = None
            self.recording = None
            self.error = 'Audio input unavailable: ' + str(exc)
            raise

    @property
    def is_recording(self):
        return self.record_stream is not None

    def recorded_seconds(self):
        if not self.recording:
            return 0.0
        return sum(len(b) for b in self.recording) / float(self.document.samplerate)

    def stop_recording(self):
        """Stop the input stream and return the recorded (channels, frames) buffer."""
        stream, self.record_stream = self.record_stream, None
        if stream is None:
            return None
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        self.playing = False
        blocks, self.recording = self.recording, None
        if not blocks:
            return np.zeros((self.record_channels, 0), np.float32)
        return np.ascontiguousarray(np.concatenate(blocks, axis=0).T)

    def close(self):
        self.playing = False
        self._close()
        if self.record_stream is not None:
            self.stop_recording()
