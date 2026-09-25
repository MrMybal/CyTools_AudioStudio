"""Backend descriptors: which engine, which worker script, which model family.

A backend is a way to execute a family of operations. The manifest lists them under
``backends[]`` and operations reference them in ``supportedBackends``. The model
catalogue (app/models/catalog.json, app/models/piper-voices.json) says which weights
each backend needs; ``audiostudio.models`` reports whether they are installed.
"""
from dataclasses import dataclass, field

from ..paths import APP


@dataclass(frozen=True)
class Backend:
    id: str
    family: str                 # sfx | music | voice | process | master
    label: str
    engine: str                 # '' = in-process in the base environment
    worker: str                 # worker script relative to app/, '' = none
    license: str
    license_url: str
    gpu_required: bool = False
    cpu_supported: bool = True
    resident_gpu: bool = False  # worker keeps weights on the GPU between jobs
    idle_seconds: int = 300
    notes: str = ''
    tags: tuple = field(default_factory=tuple)

    def worker_script(self):
        return APP / self.worker if self.worker else None


BACKENDS = {
    'sfx_procedural': Backend('sfx_procedural', 'sfx', 'Procedural synthesizer (no model)', '', 'workers/sfx_worker.py',
                              'GPL-3.0-only (Tool code)', '', notes='Deterministic numpy synthesis from a catalogue of 36 archetypes.'),
    'audioldm': Backend('audioldm', 'sfx', 'AudioLDM (text-to-audio)', 'torch', 'workers/audioldm_worker.py',
                        'CC-BY-NC-SA-4.0 (weights)', 'https://huggingface.co/cvssp/audioldm-s-full-v2',
                        gpu_required=False, resident_gpu=True, notes='Diffusion text-to-audio, 16 kHz native, CPU or CUDA.'),
    'acestep': Backend('acestep', 'music', 'ACE-Step 1.5 (music)', 'torch', 'workers/acestep_worker.py',
                       'MIT (code and weights)', 'https://github.com/ace-step/ACE-Step-1.5',
                       gpu_required=True, cpu_supported=False, resident_gpu=True, idle_seconds=600,
                       notes='Songs with lyrics, style reference, remix and repaint. 48 kHz stereo.'),
    'piper': Backend('piper', 'voice', 'Piper (CPU voices)', 'piper', 'workers/piper_worker.py',
                     'MIT (engine); per-voice model cards', 'https://github.com/OHF-Voice/piper1-gpl',
                     notes='Fast ONNX text-to-speech, 22.05 kHz mono, no GPU.'),
    'qwen3tts': Backend('qwen3tts', 'voice', 'Qwen3-TTS (expressive voices, cloning, design)', 'torch', 'workers/qwen3tts_worker.py',
                        'Apache-2.0', 'https://huggingface.co/Qwen', resident_gpu=True,
                        notes='Preset speakers with instructions, voice cloning from a reference, voice design from a prompt. 24 kHz.'),
    'fishspeech': Backend('fishspeech', 'voice', 'Fish Speech S2 Pro (dialogue, cloning)', 'torch', 'workers/fishspeech_worker.py',
                          'Apache-2.0 (code); Fish Audio Research License (weights, non-commercial)', 'https://huggingface.co/fishaudio/s2-pro',
                          gpu_required=True, cpu_supported=False, resident_gpu=True,
                          notes='Multi-speaker turns with natural-language expressions, cloning from references. 44.1 kHz.'),
    'llm': Backend('llm', 'text', 'Text assistant (Qwen3-1.7B) for TTS annotations', 'torch', 'workers/llm_worker.py',
                   'Apache-2.0', 'https://huggingface.co/Qwen/Qwen3-1.7B', resident_gpu=True, idle_seconds=180,
                   notes='Optional: turns plain text into annotated text for a voice backend. An AI client can do it itself.'),
    'whisper': Backend('whisper', 'text', 'Whisper large-v3 turbo (transcription)', 'torch', 'workers/whisper_worker.py',
                       'MIT', 'https://huggingface.co/openai/whisper-large-v3-turbo', resident_gpu=True, idle_seconds=180,
                       notes='Transcribes reference recordings for voice cloning, or any speech.'),
    'matchering': Backend('matchering', 'master', 'Matchering (reference mastering)', '', 'workers/dsp_worker.py',
                          'GPL-3.0', 'https://github.com/sergree/matchering', notes='Matches EQ, dynamics and loudness of a target to a reference recording; CPU only.'),
}


def get(backend_id):
    backend = BACKENDS.get(backend_id)
    if backend is None:
        raise KeyError('Unknown backend: ' + str(backend_id))
    return backend


def by_family(family):
    return [b for b in BACKENDS.values() if b.family == family]


def manifest_entries(models_by_backend):
    """Backend descriptors for CyTool.json (models filled from the catalogue)."""
    entries = []
    for backend in BACKENDS.values():
        entries.append({
            'id': backend.id, 'name': backend.label, 'version': '1',
            'license': backend.license, 'licenseUrl': backend.license_url,
            'shareableModelInstance': False, 'threadSafe': False, 'concurrentInference': False, 'maxConcurrentInference': 1,
            'gpu': {'required': backend.gpu_required}, 'cpu': {'supported': backend.cpu_supported},
            'models': models_by_backend.get(backend.id, []),
        })
    return entries
