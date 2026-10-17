"""Generate app/CyTool.json — the single contract shared by the ImGui interface, CLI, JSONL, HTTP and MCP.

    python app/build_manifest.py            # writes CyTool.json
    python app/build_manifest.py --check    # exits 1 when CyTool.json is stale

Never edit CyTool.json by hand. Platform "tested" records come from app/platform-tested.json
and are only written there after real executions on the machine.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from audiostudio import __version__  # noqa: E402
from audiostudio.backends import registry as backends  # noqa: E402
from audiostudio import models as model_catalog  # noqa: E402
from audiostudio.dsp import effects  # noqa: E402

TOOL_ID = 'cy.tool.audiostudio'
TOOL_NAME = 'CyTools_AudioStudio'
GiB = 1024 ** 3
MiB = 1024 ** 2

# ----------------------------------------------------------------------------- schema helpers

def STRING(description, default=None, max_length=None, min_length=None, multiline=False, required=False, **extra):
    spec = {'type': 'string', 'description': description}
    if default is not None: spec['default'] = default
    if max_length: spec['maxLength'] = max_length
    if min_length: spec['minLength'] = min_length
    spec['x-cy-kind'] = 'MultilineString' if multiline else 'String'
    spec.update(extra)
    return spec


def FILE(description, kind='Audio', default=None, **extra):
    spec = {'type': 'string', 'description': description, 'x-cy-kind': kind, 'maxLength': 1024}
    if default is not None: spec['default'] = default
    spec.update(extra)
    return spec


def FILES(description, max_items=500):
    return {'type': 'array', 'description': description, 'items': {'type': 'string', 'maxLength': 1024}, 'minItems': 1, 'maxItems': max_items, 'x-cy-kind': 'Files'}


def NUMBER(description, default, minimum=None, maximum=None, advanced=False, **extra):
    spec = {'type': 'number', 'description': description, 'default': default, 'x-cy-kind': 'Float'}
    if minimum is not None: spec['minimum'] = minimum
    if maximum is not None: spec['maximum'] = maximum
    if advanced: spec['x-cy-ui'] = {'advanced': True}
    spec.update(extra)
    return spec


def INTEGER(description, default, minimum=None, maximum=None, advanced=False, seed=False, **extra):
    spec = {'type': 'integer', 'description': description, 'default': default, 'x-cy-kind': 'Seed' if seed else 'Integer'}
    if minimum is not None: spec['minimum'] = minimum
    if maximum is not None: spec['maximum'] = maximum
    if advanced: spec['x-cy-ui'] = {'advanced': True}
    spec.update(extra)
    return spec


def BOOLEAN(description, default=False, advanced=False):
    spec = {'type': 'boolean', 'description': description, 'default': default, 'x-cy-kind': 'Boolean'}
    if advanced: spec['x-cy-ui'] = {'advanced': True}
    return spec


def ENUM(description, values, default, advanced=False):
    spec = {'enum': list(values), 'description': description, 'default': default, 'x-cy-kind': 'Enum'}
    if advanced: spec['x-cy-ui'] = {'advanced': True}
    return spec


def OBJECT(properties, required=(), description='', additional=False, **extra):
    spec = {'type': 'object', 'properties': properties, 'additionalProperties': additional}
    if required: spec['required'] = list(required)
    if description: spec['description'] = description
    spec.update(extra)
    return spec


def operation(op_id, name, description, inputs, outputs, *, backends_=(), ram=256 * MiB, vram=None, threads=2, disk=64 * MiB,
              progress=True, cancel=True, permissions=(), output_items=(), duration=None):
    resources = {'ramBytes': ram, 'cpuThreads': threads, 'diskBytes': disk}
    if vram:
        resources['vramBytes'] = {'auto': vram}
    spec = {'id': op_id, 'name': name, 'description': description, 'inputSchema': inputs, 'outputSchema': outputs,
            'outputs': [{'id': key, 'type': kind, 'description': text} for key, kind, text in output_items],
            'supportedBackends': list(backends_), 'resourceRequirements': resources, 'permissions': list(permissions),
            'canRunAsync': True, 'canCancel': cancel, 'supportsProgress': progress}
    if duration:
        spec['estimatedDurationSeconds'] = duration
    return spec


# Operations that must never overlap (SDK 0.10 exclusiveGroups), whatever the concurrency policy:
#   gpu           one model at a time on the graphics card (WorkerPool.make_exclusive evicts the others)
#   engine_torch  / engine_piper: install_engine rewrites the environment the workers run in
#   model_files   install / verify / remove touch the weights a generation is reading
# The groups are logical names: VRAM reservations and device selection stay in resourceRequirements.
_TORCH = ('gpu', 'engine_torch', 'model_files')
_ALL_ENGINES = ('gpu', 'engine_torch', 'engine_piper')
EXCLUSIVE_GROUPS = {
    'generate_sfx': _TORCH, 'generate_music': _TORCH, 'remix_music': _TORCH, 'repaint_music': _TORCH, 'write_lyrics': _TORCH,
    'voice_qwen3tts': _TORCH, 'voice_fishspeech': _TORCH, 'prepare_tts_text': _TORCH, 'transcribe_audio': _TORCH,
    'voice_piper': ('engine_piper', 'model_files'),
    'generate_voice': _ALL_ENGINES + ('model_files',),
    'install_model': ('model_files',), 'verify_model': ('model_files',), 'remove_model': ('model_files',),
    'install_engine': ('engine_torch', 'engine_piper'),
    'diagnose_backend': _ALL_ENGINES, 'release_workers': _ALL_ENGINES,
}


# ----------------------------------------------------------------------------- shared fragments

OUTPUT_FORMAT = ENUM('Output audio format', ['wav', 'flac', 'mp3', 'ogg', 'aac'], 'wav')
SUBTYPE = ENUM('Sample format for WAV/FLAC/AIFF (ignored by lossy formats)', ['PCM_16', 'PCM_24', 'PCM_32', 'FLOAT'], 'PCM_24', advanced=True)
BITRATE = ENUM('Bitrate in kbit/s for MP3/AAC', [64, 96, 128, 160, 192, 256, 320], 192, advanced=True)
WORKFLOW_DOC = {'type': 'object', 'description': 'Inline workflow document (format cytools-audiostudio-workflow). Use workflow_name instead to reference a saved workflow.',
                'x-cy-kind': 'Object', 'x-cy-ui': {'advanced': True}}
WORKFLOW_NAME = STRING('Name of a workflow saved in data/workflows (see list_workflows). Empty = no processing.', '', 200)
POST_WORKFLOW = STRING('Optional workflow (saved name) applied to the generated audio, with tail rendering.', '', 200)
TAIL = OBJECT({'enabled': BOOLEAN('Keep rendering after the input ends until the output is silent (reverb/delay tails)', True),
               'threshold_db': NUMBER('Silence threshold (dBFS)', -60.0, -120.0, 0.0), 'max_seconds': NUMBER('Maximum extension (s)', 10.0, 0.0, 600.0),
               'hold_seconds': NUMBER('Kept after the last audible sample (s)', 0.1, 0.0, 10.0)},
              description='Tail rendering override; when omitted the workflow settings apply.', **{'x-cy-ui': {'advanced': True}})
SELECTION_START = NUMBER('Start of the region to process (s); -1 = whole file', -1.0, -1.0, 360000.0, advanced=True)
SELECTION_END = NUMBER('End of the region to process (s); -1 = end of file', -1.0, -1.0, 360000.0, advanced=True)
DEVICE_CPU_CUDA = ENUM('Compute device', ['cuda', 'cpu'], 'cuda')

FILE_RESULT = OBJECT({'file': FILE('Result file', 'File'), 'mimeType': STRING('MIME type'), 'sampleRate': INTEGER('Sample rate', 48000), 'channels': INTEGER('Channels', 2),
                      'durationSeconds': NUMBER('Duration (s)', 0.0), 'sizeBytes': INTEGER('Size in bytes', 0), 'report': {'type': 'object', 'description': 'Render report'}},
                     required=('file', 'mimeType', 'sampleRate', 'channels', 'durationSeconds'), additional=True)
VOICE_RESULT = OBJECT({'file': FILE('Speech WAV', 'File'), 'mimeType': STRING('MIME type'), 'sampleRate': INTEGER('Sample rate', 24000), 'channels': INTEGER('Channels', 1),
                       'durationSeconds': NUMBER('Duration (s)', 0.0), 'backend': STRING('Backend id'), 'model': STRING('Model id'),
                       'processedFile': STRING('Result after the post workflow, when one was applied', ''), 'generationSeconds': NUMBER('Generation time (s)', 0.0),
                       'preset': {'type': 'object', 'description': 'Reusable preset (parameters without text) to regenerate the same voice'},
                       'warnings': {'type': 'array', 'items': {'type': 'string'}}},
                      required=('file', 'mimeType', 'sampleRate', 'channels', 'durationSeconds', 'backend'), additional=True)
VARIATIONS_RESULT = OBJECT({'variations': {'type': 'array', 'description': 'Generated files', 'items': OBJECT({'file': FILE('WAV file', 'File'), 'seed': INTEGER('Seed', 0),
                                                                                                         'durationSeconds': NUMBER('Duration', 0.0), 'peakDbfs': NUMBER('Peak', -1.0),
                                                                                                         'rmsDbfs': NUMBER('RMS', -20.0), 'sizeBytes': INTEGER('Size', 0),
                                                                                                         'processedFile': STRING('After post workflow', '')}, additional=True)},
                            'backend': STRING('Backend id'), 'engine': STRING('Engine name'), 'sampleRate': INTEGER('Sample rate', 44100),
                            'recipe': {'type': ['object', 'null'], 'description': 'Procedural recipe (sfx_procedural only)'},
                            'warnings': {'type': 'array', 'items': {'type': 'string'}}, 'report': {'type': 'object'}},
                           required=('variations', 'backend', 'sampleRate'), additional=True)
TRACKS_RESULT = OBJECT({'tracks': {'type': 'array', 'items': OBJECT({'file': FILE('Track', 'File'), 'seed': INTEGER('Seed', 0), 'durationSeconds': NUMBER('Duration', 0.0),
                                                                     'channels': INTEGER('Channels', 2), 'sampleRate': INTEGER('Sample rate', 48000), 'sizeBytes': INTEGER('Size', 0),
                                                                     'processedFile': STRING('After post workflow', '')}, additional=True)},
                        'captionUsed': STRING('Caption sent to the model'), 'lyricsUsed': STRING('Lyrics sent to the model'), 'metadata': {'type': 'object'},
                        'taskType': STRING('Task'), 'sampleRate': INTEGER('Sample rate', 48000), 'outputFormat': STRING('Format'), 'timings': {'type': 'object'},
                        'vramPeakBytes': INTEGER('VRAM peak', 0), 'report': {'type': 'object'}}, required=('tracks', 'sampleRate'), additional=True)
ANY = {'type': 'object', 'additionalProperties': True}

LANGUAGES_ACE = ['unknown', 'ar', 'az', 'bg', 'bn', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es', 'fa', 'fi', 'fr', 'he', 'hi', 'hr', 'ht', 'hu', 'id', 'is', 'it', 'ja', 'ko',
                 'la', 'lt', 'ms', 'ne', 'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sa', 'sk', 'sr', 'sv', 'sw', 'ta', 'te', 'th', 'tl', 'tr', 'uk', 'ur', 'vi', 'yue', 'zh']
QWEN_LANGUAGES = ['Auto', 'French', 'English', 'Chinese', 'Japanese', 'Korean', 'German', 'Russian', 'Portuguese', 'Spanish', 'Italian']
QWEN_SPEAKERS = ['Ryan', 'Aiden', 'Vivian', 'Serena', 'Uncle_Fu', 'Dylan', 'Eric', 'Ono_Anna', 'Sohee']
QWEN_MODELS = ['0.6B-CustomVoice', '1.7B-CustomVoice', '0.6B-Base', '1.7B-Base', '1.7B-VoiceDesign']


def music_common():
    return {
        'caption': STRING('Style caption (genre, mood, instruments, production)', None, 512, 1, multiline=True),
        'lyrics': STRING('Lyrics with optional [Verse]/[Chorus] tags; empty for instrumental', '', 4096, multiline=True),
        'instrumental': BOOLEAN('No vocals', False),
        'language': ENUM('Vocal language (unknown = let the model decide)', LANGUAGES_ACE, 'unknown'),
        'bpm': {'type': ['integer', 'null'], 'minimum': 30, 'maximum': 300, 'default': None, 'description': 'Tempo; null = model decides', 'x-cy-kind': 'Integer'},
        'keyscale': STRING('Key, e.g. "C Major"; empty = model decides', '', 32),
        'time_signature': ENUM('Time signature; empty = model decides', ['', '2', '3', '4', '6'], ''),
        'steps': INTEGER('Diffusion steps (turbo model trained for 8)', 8, 1, 60, advanced=True),
        'seed': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 2147483647, 'default': None, 'description': 'Seed; null = random. Track N uses seed+N-1', 'x-cy-kind': 'Seed'},
        'output_format': ENUM('Track format (mp3 needs ffmpeg)', ['flac', 'wav', 'mp3'], 'flac'),
        'track_count': INTEGER('Number of tracks', 1, 1, 4),
        'post_workflow': POST_WORKFLOW,
    }


def build():
    ops = []
    # ------------------------------------------------------------------ processing
    ops.append(operation('process_audio', 'Process audio', 'Render a workflow (effects, VST3/CLAP/LV2/JSFX plugins, models) over a file, with tail rendering so reverb and delay decays are never cut. A selection processes only that region and overlaps its tail onto the following audio.',
        OBJECT({'input': FILE('Audio file to process'), 'workflow': WORKFLOW_DOC, 'workflow_name': WORKFLOW_NAME, 'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE,
                'bitrate_kbps': BITRATE, 'selection_start': SELECTION_START, 'selection_end': SELECTION_END, 'tail': TAIL,
                'output_name': STRING('Output file name without extension; default = input name + suffix', '', 200)}, required=('input',)),
        FILE_RESULT, ram=2 * GiB, threads=4, disk=2 * GiB, output_items=(('file', 'Audio', 'Processed audio file'),)))
    ops.append(operation('batch_process', 'Batch process', 'Render the same workflow over several files. Each output keeps the source name plus a suffix.',
        OBJECT({'inputs': FILES('Audio files'), 'workflow': WORKFLOW_DOC, 'workflow_name': WORKFLOW_NAME, 'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE,
                'bitrate_kbps': BITRATE, 'suffix': STRING('Suffix appended to each output name', '_processed', 40), 'tail': TAIL,
                'continue_on_error': BOOLEAN('Keep going when one file fails', True)}, required=('inputs',)),
        OBJECT({'results': {'type': 'array', 'items': ANY}, 'failed': {'type': 'array', 'items': ANY}, 'count': INTEGER('Processed files', 0)}, required=('results', 'count'), additional=True),
        ram=2 * GiB, threads=4, disk=8 * GiB, output_items=(('results', 'Object', 'One entry per processed file'),)))
    ops.append(operation('convert_audio', 'Convert audio', 'Change format, sample rate, bit depth or channel count.',
        OBJECT({'input': FILE('Audio file'), 'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE, 'bitrate_kbps': BITRATE,
                'samplerate': ENUM('Target sample rate; 0 keeps the source rate', [0, 8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000], 0),
                'channels': ENUM('Target channels; 0 keeps the source layout', [0, 1, 2], 0)}, required=('input',)),
        FILE_RESULT, ram=1 * GiB, disk=2 * GiB, output_items=(('file', 'Audio', 'Converted file'),)))
    ops.append(operation('analyze_audio', 'Analyze audio', 'Duration, peak, RMS, integrated loudness (LUFS), true peak, clipping, DC offset, leading/trailing silence.',
        OBJECT({'input': FILE('Audio file')}, required=('input',)), ANY, ram=1 * GiB, progress=False, output_items=(('info', 'Object', 'Measurements'),)))
    ops.append(operation('render_session', 'Render session', 'Mix an editor session (tracks, insert chains, automation lanes, master bus) to a file; stateful inserts ring out after the end (tail).',
        OBJECT({'session': STRING('Session folder or session.json saved by the editor', None, 1024, 1), 'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE, 'bitrate_kbps': BITRATE,
                'tail': TAIL, 'selection': {'type': ['array', 'null'], 'items': {'type': 'number', 'minimum': 0}, 'minItems': 2, 'maxItems': 2, 'default': None,
                                            'description': 'Optional [start, end] seconds to render instead of the whole session', 'x-cy-kind': 'Array'}}, required=('session',)),
        FILE_RESULT, ram=2 * GiB, disk=2 * GiB, output_items=(('file', 'Audio', 'Rendered mix'),)))
    ACTION = {'type': 'object', 'additionalProperties': True, 'required': ['action'],
              'properties': {'action': ENUM('What to do', ['add_track', 'replace_audio', 'remove_track', 'add_clip', 'move_clip', 'remove_clip', 'reverse_clip', 'set_track', 'set_inserts', 'set_master',
                                                           'clear_automation', 'set_tail'], 'add_track'),
                             'file': FILE('Audio file (add_track, replace_audio, add_clip)'), 'track': STRING('Track id or exact name', None, 200), 'name': STRING('Track or clip name', None, 200),
                             'clip': STRING('Clip id, exact name or index such as "0" (move_clip, remove_clip, reverse_clip)', None, 200),
                             'to_track': STRING('Track that receives the clip (move_clip); its inserts then apply to it', None, 200),
                             'after_clips': BOOLEAN('add_clip: a position already taken by a clip puts the new clip after the last one', True),
                             'target': STRING("Track id / name, or 'master'", None, 200), 'offset_seconds': NUMBER('Start position', 0.0, 0.0), 'gain_db': NUMBER('Gain', 0.0, -60.0, 24.0),
                             'pan': NUMBER('Pan', 0.0, -1.0, 1.0), 'mute': BOOLEAN('Mute'), 'solo': BOOLEAN('Solo'), 'inserts_from': STRING('Copy the chain and lanes of this track', None, 200),
                             'workflow_name': STRING('Saved workflow to install as the chain', None, 200), 'nodes': {'type': 'array', 'items': ANY, 'x-cy-kind': 'Array'}, 'key': STRING('Automation lane key', None, 200)}}
    ops.append(operation('edit_session', 'Edit session (scripted)', 'Create or open a session, apply actions (add / replace / remove tracks, add / move / reverse / remove clips, insert chains, master, tail, automation), save it and optionally render the mix. The headless counterpart of the editor.',
        OBJECT({'session': STRING('Existing session folder or session.json; empty = new session', None, 1024), 'samplerate': ENUM('Sample rate of a new session', [44100, 48000, 96000], 48000),
                'actions': {'type': 'array', 'items': ACTION, 'maxItems': 500, 'default': [], 'description': 'Actions applied in order', 'x-cy-kind': 'Array'},
                'save_as': STRING('Session name (under data/sessions) or absolute folder; empty = do not save', None, 1024), 'render': BOOLEAN('Render the mix after the actions', False),
                'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE, 'bitrate_kbps': BITRATE, 'tail': TAIL,
                'selection': {'type': ['array', 'null'], 'items': {'type': 'number', 'minimum': 0}, 'minItems': 2, 'maxItems': 2, 'default': None, 'description': 'Optional [start, end] seconds to render', 'x-cy-kind': 'Array'}}),
        OBJECT({'actions': {'type': 'array', 'items': ANY}, 'session': {'type': ['string', 'null']}, 'document': ANY}, required=('actions', 'document'), additional=True),
        ram=2 * GiB, disk=4 * GiB, output_items=(('document', 'Object', 'Session description after the actions'), ('file', 'Audio', 'Rendered mix (when render is true)'))))
    ops.append(operation('batch_session', 'Batch sounds through a session', 'Render a session once per input sound: each sound is placed in a slot track (an existing placeholder track whose audio is replaced, keeping its inserts and automation, or a new track), the mix is rendered with the tail, then the next sound takes its place.',
        OBJECT({'session': STRING('Session folder or session.json', None, 1024, 1), 'inputs': FILES('Sounds to batch'),
                'slot': OBJECT({'track': STRING('Placeholder track name/id to replace, or name of the track to create', 'Batch', 200), 'offset_seconds': NUMBER('Start position of the sound', 0.0, 0.0),
                                'gain_db': NUMBER('Gain', 0.0, -60.0, 24.0), 'pan': NUMBER('Pan', 0.0, -1.0, 1.0), 'inserts_from': STRING('Copy the chain of this track onto a new slot track', None, 200),
                                'workflow_name': STRING('Saved workflow to install on a new slot track', None, 200), 'solo': BOOLEAN('Render the slot track alone (other tracks muted)', False)}),
                'output_dir': STRING('Output folder; empty = job workspace', None, 1024), 'suffix': STRING('Suffix appended to each output name', '', 40),
                'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE, 'bitrate_kbps': BITRATE, 'tail': TAIL,
                'selection': {'type': ['array', 'null'], 'items': {'type': 'number', 'minimum': 0}, 'minItems': 2, 'maxItems': 2, 'default': None, 'description': 'Optional [start, end] seconds to render', 'x-cy-kind': 'Array'}},
               required=('session', 'inputs')),
        OBJECT({'results': {'type': 'array', 'items': ANY}, 'failed': {'type': 'array', 'items': ANY}, 'count': INTEGER('Rendered files', 0), 'outputDir': STRING('Folder')}, required=('results', 'count'), additional=True),
        ram=2 * GiB, threads=4, disk=8 * GiB, output_items=(('results', 'Object', 'One entry per rendered sound'),)))
    ops.append(operation('list_effects', 'List effects', 'Native effects available as workflow nodes and track inserts, with their parameter schemas; "realtime" marks the ones usable as inserts, "sidechain" the ones keyed by another track.', OBJECT({}), ANY, ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('list_workflows', 'List workflows', 'Saved workflows in data/workflows.', OBJECT({}), ANY, ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('get_workflow', 'Get workflow', 'Read a saved workflow document.', OBJECT({'name': STRING('Workflow name or path', None, 260, 1)}, required=('name',)), ANY, ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('save_workflow', 'Save workflow', 'Persist a workflow document under data/workflows (explicit user action).',
        OBJECT({'name': STRING('Workflow name', None, 80, 1), 'workflow': {**WORKFLOW_DOC, 'x-cy-ui': {}}, 'overwrite': BOOLEAN('Replace an existing workflow of that name', False)}, required=('name', 'workflow')),
        OBJECT({'path': STRING('Saved path'), 'name': STRING('Name'), 'summary': STRING('Chain summary')}, required=('path',), additional=True), ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('scan_plugins', 'Scan audio plugins', 'Scan folders for VST3, CLAP, LV2 and JSFX plugins in an isolated worker process and cache their parameters. A crashing plugin is reported, not fatal.',
        OBJECT({'directories': {'type': 'array', 'items': {'type': 'string', 'maxLength': 1024}, 'maxItems': 32, 'default': [], 'description': 'Extra folders; the standard plugin folders are always scanned', 'x-cy-kind': 'Array'},
                'force': BOOLEAN('Rescan plugins already cached', False)}),
        OBJECT({'plugins': {'type': 'array', 'items': ANY}, 'failures': {'type': 'array', 'items': ANY}, 'count': INTEGER('Plugins found', 0)}, required=('plugins', 'count'), additional=True),
        ram=1 * GiB, output_items=(('plugins', 'Object', 'Plugin catalogue'),)))
    ops.append(operation('list_plugins', 'List audio plugins', 'Cached VST3, CLAP, LV2 and JSFX catalogue (run scan_plugins first).', OBJECT({}), ANY, ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('describe_plugin', 'Describe audio plugin', 'Load one VST3, CLAP, LV2 or JSFX plugin in a worker and return its parameters.',
        OBJECT({'plugin': FILE('Path to a VST3, CLAP, LV2 bundle or JSFX script', 'File'), 'plugin_name': STRING('Plugin name or ID within a bundle', '', 1024)}, required=('plugin',)), ANY, ram=1 * GiB, progress=False))
    ops.append(operation('read_jsfx', 'Read JSFX script', 'Read a JSFX script without executing it.',
        OBJECT({'script': FILE('JSFX source path', 'File')}, required=('script',)), ANY, ram=64 * MiB, progress=False))
    ops.append(operation('validate_jsfx', 'Compile JSFX script', 'Compile source in an isolated process. Relative imports resolve beside the selected source directory. Does not replace any script.',
        OBJECT({'source': STRING('JSFX source code', None, 2097152, 1, multiline=True), 'directory': STRING('Directory for relative JSFX imports', '', 1024)}, required=('source',)), ANY, ram=256 * MiB))
    ops.append(operation('save_jsfx', 'Save JSFX script', 'Compile first, then save under data/scripts/JSFX. A compilation error preserves the existing script.',
        OBJECT({'name': STRING('Script name without extension', None, 80, 1), 'source': STRING('JSFX source code', None, 2097152, 1, multiline=True), 'overwrite': BOOLEAN('Replace existing script', False)}, required=('name', 'source')), ANY, ram=256 * MiB))
    # ------------------------------------------------------------------ SFX
    ops.append(operation('generate_sfx', 'Generate sound effect', 'Text to sound effect. Backend sfx_procedural synthesises deterministically from a catalogue of 36 archetypes (no model, instant); backend audioldm runs the AudioLDM diffusion model on CPU or CUDA.',
        OBJECT({'prompt': STRING('Description of the sound (English or French)', None, 600, 1, multiline=True),
                'negative_prompt': STRING('What to avoid (audioldm only)', '', 600, advanced=True),
                'duration_seconds': {'type': ['number', 'null'], 'minimum': 0.2, 'maximum': 30.0, 'default': None, 'description': 'Length in seconds; null = natural length (procedural) or 5 s (audioldm)', 'x-cy-kind': 'Float'},
                'seed': INTEGER('Seed; variation N uses seed+N', 0, 0, 2147483647, seed=True), 'variations': INTEGER('Number of variations', 1, 1, 4),
                'sample_rate': ENUM('Output sample rate', [16000, 22050, 24000, 44100, 48000], 44100), 'bit_depth': ENUM('WAV bit depth', [16, 24], 16, advanced=True),
                'peak_dbfs': NUMBER('Peak normalisation target (dBFS)', -1.0, -40.0, 0.0, advanced=True),
                'steps': INTEGER('Diffusion steps (audioldm only)', 20, 5, 100, advanced=True), 'guidance_scale': NUMBER('Guidance scale (audioldm only)', 2.5, 1.0, 15.0, advanced=True),
                'device': ENUM('Compute device (audioldm only)', ['cuda', 'cpu'], 'cuda'), 'post_workflow': POST_WORKFLOW}, required=('prompt',)),
        VARIATIONS_RESULT, backends_=('sfx_procedural', 'audioldm'), ram=3 * GiB, disk=256 * MiB, output_items=(('variations', 'Audio', 'Generated WAV files'),)))
    ops.append(operation('preview_sfx_recipe', 'Preview procedural recipe', 'Parse a prompt with the procedural synthesizer and return the exact recipe without rendering.',
        OBJECT({'prompt': STRING('Description', None, 600, 1), 'duration_seconds': {'type': ['number', 'null'], 'minimum': 0.2, 'maximum': 30.0, 'default': None, 'x-cy-kind': 'Float'},
                'seed': INTEGER('Seed', 0, 0, 2147483647, seed=True), 'sample_rate': ENUM('Sample rate', [16000, 22050, 24000, 44100, 48000], 44100), 'peak_dbfs': NUMBER('Peak', -1.0, -40.0, 0.0)},
               required=('prompt',)), ANY, ram=256 * MiB, progress=False))
    ops.append(operation('list_sfx_types', 'List procedural sound types', 'Archetypes of the procedural synthesizer with the English and French words that select them.',
        OBJECT({'language': ENUM('Keyword language', ['all', 'en', 'fr'], 'all'), 'query': STRING('Filter', '', 64)}), ANY, ram=128 * MiB, progress=False, cancel=False))
    # ------------------------------------------------------------------ music
    ops.append(operation('generate_music', 'Generate music', 'Text to music with ACE-Step 1.5: a full arrangement, optional sung lyrics, optional style reference recording. 48 kHz stereo.',
        OBJECT({**music_common(), 'duration_seconds': NUMBER('Length of the song (s)', 60.0, 10.0, 600.0),
                'plan_with_lm': BOOLEAN('Let the 5Hz planning language model refine caption, lyrics and metadata (+6 GiB VRAM)', True),
                'creativity': NUMBER('Planner temperature', 0.85, 0.0, 2.0, advanced=True), 'nucleus': NUMBER('Planner top-p', 0.9, 0.1, 1.0, advanced=True),
                'reference_audio': FILE('Optional reference recording whose timbre and production are followed', default=''),
                'reference_strength': NUMBER('How strongly the reference is followed', 0.2, 0.0, 1.0)}, required=('caption',)),
        TRACKS_RESULT, backends_=('acestep',), ram=13 * GiB, vram=16 * GiB, threads=4, disk=1 * GiB, output_items=(('tracks', 'Audio', 'Generated tracks'),), duration=90))
    ops.append(operation('remix_music', 'Remix music', 'Audio to audio: regenerate a recording under a new caption and optional lyrics while keeping its structure (task cover).',
        OBJECT({**music_common(), 'source_audio': FILE('Recording to remix'), 'similarity': NUMBER('Similarity to the source', 0.6, 0.0, 1.0)}, required=('caption', 'source_audio')),
        TRACKS_RESULT, backends_=('acestep',), ram=13 * GiB, vram=10 * GiB, threads=4, disk=1 * GiB, output_items=(('tracks', 'Audio', 'Remixed tracks'),), duration=60))
    ops.append(operation('repaint_music', 'Repaint section', 'Rewrite one time range of a recording and splice it back, leaving the rest untouched.',
        OBJECT({**music_common(), 'source_audio': FILE('Recording to edit'), 'start_seconds': NUMBER('Start of the region', 0.0, 0.0, 600.0),
                'end_seconds': NUMBER('End of the region; -1 = end of file', -1.0, -1.0, 600.0), 'repaint_mode': ENUM('Mode', ['conservative', 'balanced', 'aggressive'], 'balanced'),
                'repaint_strength': NUMBER('Strength (balanced mode)', 0.5, 0.0, 1.0)}, required=('caption', 'source_audio')),
        TRACKS_RESULT, backends_=('acestep',), ram=13 * GiB, vram=10 * GiB, threads=4, disk=1 * GiB, output_items=(('tracks', 'Audio', 'Edited tracks'),), duration=60))
    ops.append(operation('write_lyrics', 'Write lyrics', 'Planning language model only: turn an idea into caption, lyrics and metadata (create) or format existing lyrics (format).',
        OBJECT({'mode': ENUM('Mode', ['create', 'format'], 'create'), 'idea': STRING('Idea or theme (create)', '', 1024, multiline=True),
                'caption': STRING('Caption (format)', '', 512), 'lyrics': STRING('Lyrics (format)', '', 4096, multiline=True), 'instrumental': BOOLEAN('Instrumental', False),
                'language': ENUM('Language', LANGUAGES_ACE, 'unknown'),
                'bpm': {'type': ['integer', 'null'], 'minimum': 30, 'maximum': 300, 'default': None, 'x-cy-kind': 'Integer', 'description': 'Tempo'},
                'duration_seconds': {'type': ['number', 'null'], 'minimum': 10, 'maximum': 600, 'default': None, 'x-cy-kind': 'Float', 'description': 'Target duration'},
                'keyscale': STRING('Key', '', 32), 'time_signature': ENUM('Time signature', ['', '2', '3', '4', '6'], ''),
                'creativity': NUMBER('Temperature', 0.85, 0.0, 2.0, advanced=True), 'nucleus': NUMBER('Top-p', 0.9, 0.1, 1.0, advanced=True)}, required=('mode',)),
        OBJECT({'caption': STRING('Caption'), 'lyrics': STRING('Lyrics'), 'metadata': ANY, 'statusMessage': STRING('Status', '')}, required=('caption', 'lyrics'), additional=True),
        backends_=('acestep',), ram=13 * GiB, vram=10 * GiB, threads=4, output_items=(('lyrics', 'Object', 'Caption, lyrics and metadata'),), duration=45))
    # ------------------------------------------------------------------ voices
    ops.append(operation('voice_piper', 'Speak with Piper', 'CPU text-to-speech with a Piper ONNX voice (22.05 kHz mono). Raw text only, no annotations.',
        OBJECT({'text': STRING('Text to speak', None, 20000, 1, multiline=True), 'voice': STRING('Voice key, e.g. fr_FR-siwis-medium (see list_voices)', 'fr_FR-siwis-medium', 80),
                'speaker': INTEGER('Speaker index for multi-speaker voices', 0, 0, 1000), 'length_scale': NUMBER('Speed (1 = normal, 2 = twice slower)', 1.0, 0.25, 4.0),
                'noise_scale': NUMBER('Expressiveness', 0.667, 0.0, 2.0, advanced=True), 'noise_w_scale': NUMBER('Phoneme width variation', 0.8, 0.0, 2.0, advanced=True),
                'volume': NUMBER('Volume', 1.0, 0.01, 2.0), 'normalize': BOOLEAN('Normalise output', True, advanced=True), 'threads': INTEGER('CPU threads', 2, 1, 16, advanced=True),
                'post_workflow': POST_WORKFLOW}, required=('text',)),
        VOICE_RESULT, backends_=('piper',), ram=1 * GiB, threads=2, disk=256 * MiB, output_items=(('file', 'Audio', 'Speech WAV'),)))
    ops.append(operation('voice_qwen3tts', 'Speak with Qwen3-TTS', 'Expressive text-to-speech: preset speakers with natural-language instructions (custom), voice cloning from a reference recording (clone) or voice design from a description (design). Inline [tone: ...] and [pause: 500ms] annotations are supported with the 1.7B CustomVoice model. 24 kHz mono.',
        OBJECT({'text': STRING('Text to speak; paragraphs separated by blank lines', None, 10000, 1, multiline=True),
                'model': ENUM('Model variant (custom needs CustomVoice, clone needs Base, design needs VoiceDesign)', QWEN_MODELS, '1.7B-CustomVoice'),
                'mode': ENUM('Mode', ['custom', 'clone', 'design'], 'custom'), 'language': ENUM('Language', QWEN_LANGUAGES, 'French'),
                'speaker': ENUM('Preset speaker (custom)', QWEN_SPEAKERS, 'Ryan'), 'instruction': STRING('Delivery instruction (custom, 1.7B) or voice description (design)', '', 2000, multiline=True),
                'reference_audio': FILE('Reference recording (clone)', default=''), 'reference_text': STRING('Exact transcription of the reference (clone)', '', 4000, multiline=True),
                'x_vector_only': BOOLEAN('Clone from the speaker embedding only, no transcription', False, advanced=True),
                'device': DEVICE_CPU_CUDA, 'delivery': ENUM('Split the text into passages', ['paragraphs', 'segments', 'complete'], 'paragraphs'),
                'temperature': NUMBER('Temperature', 0.9, 0.1, 2.0, advanced=True), 'top_k': INTEGER('Top-k', 50, 1, 200, advanced=True), 'top_p': NUMBER('Top-p', 1.0, 0.05, 1.0, advanced=True),
                'repetition_penalty': NUMBER('Repetition penalty', 1.05, 1.0, 2.0, advanced=True), 'max_new_tokens': INTEGER('Max new tokens per passage', 2048, 32, 4096, advanced=True),
                'seed': INTEGER('Seed', 42, 0, 2147483647, seed=True), 'text_annotations': BOOLEAN('Enable [tone: ...] / [pause: ...] annotations (1.7B CustomVoice only)', False),
                'post_workflow': POST_WORKFLOW}, required=('text',)),
        VOICE_RESULT, backends_=('qwen3tts',), ram=10 * GiB, vram=8 * GiB, threads=4, disk=512 * MiB, output_items=(('file', 'Audio', 'Speech WAV'),), duration=30))
    ops.append(operation('voice_fishspeech', 'Speak with Fish Speech S2 Pro', 'Multi-speaker dialogue with natural-language expressions per turn and voice cloning from short references (0.1-30 s with their transcription). CUDA only, 44.1 kHz mono.',
        OBJECT({'turns': {'type': 'array', 'minItems': 1, 'maxItems': 30, 'x-cy-kind': 'Array', 'description': 'Dialogue turns in order',
                          'items': OBJECT({'speaker': INTEGER('Speaker index (maps to references[N])', 0, 0, 4), 'text': STRING('Text', None, 4000, 1, multiline=True),
                                           'expression': STRING('Expression in natural language, e.g. whisper, excited', '', 150)}, required=('text',))},
                'references': {'type': 'array', 'maxItems': 5, 'default': [], 'x-cy-kind': 'Array', 'description': 'Reference recordings per speaker index',
                               'items': OBJECT({'audio': FILE('Reference recording'), 'text': STRING('Exact transcription', None, 2000, 1)}, required=('audio', 'text'))},
                'temperature': NUMBER('Temperature', 0.8, 0.1, 1.5, advanced=True), 'top_p': NUMBER('Top-p', 0.8, 0.1, 1.0, advanced=True), 'top_k': INTEGER('Top-k', 30, 1, 100, advanced=True),
                'seed': INTEGER('Seed', 42, 0, 2147483647, seed=True), 'max_new_tokens': INTEGER('Max new tokens', 1024, 128, 4096, advanced=True),
                'chunk_length': INTEGER('Chunk length', 200, 50, 500, advanced=True), 'precision': ENUM('Precision', ['bfloat16', 'float16'], 'bfloat16', advanced=True),
                'post_workflow': POST_WORKFLOW}, required=('turns',)),
        VOICE_RESULT, backends_=('fishspeech',), ram=16 * GiB, vram=20 * GiB, threads=4, disk=512 * MiB, output_items=(('file', 'Audio', 'Speech WAV'),), duration=60))
    ops.append(operation('generate_voice', 'Speak with a saved voice preset', 'Regenerate a voice from a saved preset (backend, model, every parameter) with new text. Warns when a reference recording changed.',
        OBJECT({'preset': STRING('Preset id (see list_voice_presets)', None, 200, 1), 'text': STRING('Text to speak', None, 20000, 1, multiline=True),
                'seed': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 2147483647, 'default': None, 'x-cy-kind': 'Seed', 'description': 'Override the preset seed'},
                'post_workflow': {'type': ['string', 'null'], 'default': None, 'maxLength': 200, 'description': 'Override the preset post workflow (empty string = none)'}},
               required=('preset', 'text')),
        VOICE_RESULT, ram=2 * GiB, threads=4, disk=512 * MiB, output_items=(('file', 'Audio', 'Speech WAV'),), duration=60))
    ops.append(operation('list_voices', 'List voices', 'Voices per backend: Piper voice catalogue (installed and downloadable), Qwen3-TTS speakers and modes, Fish Speech capabilities, and saved presets.',
        OBJECT({'backend': ENUM('Backend filter', ['all', 'piper', 'qwen3tts', 'fishspeech'], 'all'), 'language': STRING('Language filter (e.g. fr, en)', '', 16),
                'installed_only': BOOLEAN('Only installed Piper voices', False)}), ANY, ram=128 * MiB, progress=False, cancel=False))
    ops.append(operation('save_voice_preset', 'Save voice preset', 'Store the parameters of a voice (without text) as a reusable preset.',
        OBJECT({'name': STRING('Preset name', None, 120, 1), 'backend': ENUM('Voice backend', ['piper', 'qwen3tts', 'fishspeech'], 'qwen3tts'),
                'parameters': {'type': 'object', 'description': 'Parameters of the corresponding voice_* operation (text is ignored)', 'x-cy-kind': 'Object'},
                'post_workflow': POST_WORKFLOW, 'notes': STRING('Notes', '', 2000, multiline=True), 'preset_id': STRING('Existing preset id to overwrite', '', 200)},
               required=('name', 'backend', 'parameters')),
        OBJECT({'id': STRING('Preset id'), 'path': STRING('Saved path'), 'preset': ANY}, required=('id', 'path'), additional=True), ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('list_voice_presets', 'List voice presets', 'Saved voice presets.', OBJECT({}), ANY, ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('delete_voice_preset', 'Delete voice preset', 'Remove a saved voice preset.', OBJECT({'preset': STRING('Preset id', None, 200, 1)}, required=('preset',)),
        OBJECT({'deleted': BOOLEAN('Deleted', True)}, required=('deleted',)), ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('prepare_tts_text', 'Prepare text for a voice', 'Turn plain text into the markup a voice backend expects: [tone]/[pause] annotations for Qwen3-TTS, dialogue turns with expressions for Fish Speech, sentence-per-line text for Piper. Method heuristic needs no model; method llm uses the local Qwen3-1.7B assistant and falls back to the heuristic when its output is not usable. An AI client can skip this and annotate itself.',
        OBJECT({'text': STRING('Plain text', None, 20000, 1, multiline=True), 'target': ENUM('Voice backend', ['qwen3tts', 'fishspeech', 'piper'], 'qwen3tts'),
                'method': ENUM('Annotation method', ['heuristic', 'llm'], 'heuristic'), 'style': STRING('Overall delivery wanted (e.g. warm and calm narration)', '', 200),
                'language': STRING('Language hint for the assistant', '', 40), 'pause_ms': INTEGER('Pause inserted between paragraphs (heuristic)', 500, 0, 3000),
                'device': DEVICE_CPU_CUDA, 'max_new_tokens': INTEGER('Assistant output budget', 1024, 64, 4096, advanced=True)}, required=('text',)),
        OBJECT({'target': STRING('Backend'), 'method': STRING('Method actually used'), 'text': STRING('Annotated text (qwen3tts, piper)', ''),
                'turns': {'type': 'array', 'items': ANY}, 'textAnnotations': BOOLEAN('Pass text_annotations=true to voice_qwen3tts', False),
                'fallbackReason': STRING('Why the llm output was replaced by the heuristic', ''), 'raw': STRING('Raw assistant output', '')},
               required=('target', 'method'), additional=True),
        ram=9 * GiB, vram=5 * GiB, threads=4, output_items=(('text', 'Object', 'Annotated text or turns'),), duration=20))
    ops.append(operation('transcribe_audio', 'Transcribe audio', 'Speech to text with Whisper large-v3 turbo (99 languages, segment timestamps). Used to get the exact transcription of a reference recording before cloning a voice.',
        OBJECT({'input': FILE('Recording to transcribe'), 'language': STRING('Language code (fr, en, ...); empty = automatic detection', '', 8),
                'device': DEVICE_CPU_CUDA}, required=('input',)),
        OBJECT({'text': STRING('Transcription'), 'segments': {'type': 'array', 'items': ANY}, 'durationSeconds': NUMBER('Audio duration', 0.0),
                'language': STRING('Language used'), 'seconds': NUMBER('Processing time', 0.0)}, required=('text',), additional=True),
        backends_=('whisper',), ram=4 * GiB, vram=3 * GiB, threads=4, output_items=(('text', 'Object', 'Transcription'),), duration=15))
    ops.append(operation('master_audio', 'Master audio', 'Mastering: match a reference recording (Matchering: spectrum, dynamics and loudness) or normalise to a loudness target with a true-peak limiter. Optional post workflow.',
        OBJECT({'input': FILE('Track to master'), 'reference': FILE('Reference recording to match (mode reference)', default=''),
                'mode': ENUM('Mode', ['reference', 'loudness'], 'loudness'), 'target_lufs': NUMBER('Integrated loudness target (mode loudness)', -14.0, -30.0, -5.0),
                'ceiling_db': NUMBER('True-peak ceiling (dBTP)', -1.0, -6.0, 0.0), 'output_format': OUTPUT_FORMAT, 'subtype': SUBTYPE, 'bitrate_kbps': BITRATE,
                'post_workflow': POST_WORKFLOW}, required=('input',)),
        FILE_RESULT, backends_=('matchering',), ram=4 * GiB, threads=4, disk=2 * GiB, output_items=(('file', 'Audio', 'Mastered file'),), duration=60))
    # ------------------------------------------------------------------ models & engines
    ops.append(operation('list_models', 'List models', 'Catalogue and installation state of every model (state, size, present bytes, licence, source).',
        OBJECT({'backend': STRING('Backend filter', '', 40), 'include_voices': BOOLEAN('Include the 177 Piper voices', False)}), ANY, ram=128 * MiB, progress=False, cancel=False))
    ops.append(operation('install_model', 'Install model', 'Download or resume a model with verification. The licence must be accepted personally when the source requires it; a gated source returns AccessRequired with the official page.',
        OBJECT({'model': STRING('Model id (see list_models), e.g. piper.en_US-lessac-medium', None, 200, 1), 'accept_license': BOOLEAN('I have read and accept the licence of this model', False),
                'repair': BOOLEAN('Re-hash existing files and re-download corrupted ones', False)}, required=('model',)),
        OBJECT({'modelId': STRING('Model'), 'state': STRING('State'), 'downloaded': INTEGER('Bytes downloaded', 0)}, required=('modelId', 'state'), additional=True),
        ram=512 * MiB, disk=12 * GiB, permissions=('network',), output_items=(('state', 'Object', 'Installation state'),)))
    ops.append(operation('verify_model', 'Verify model', 'Re-check presence, sizes and hashes of an installed model.', OBJECT({'model': STRING('Model id', None, 200, 1)}, required=('model',)), ANY, ram=256 * MiB))
    ops.append(operation('remove_model', 'Remove model', 'Delete the files of a model under data/models.', OBJECT({'model': STRING('Model id', None, 200, 1)}, required=('model',)), ANY, ram=64 * MiB, progress=False))
    ops.append(operation('engine_status', 'Engine status', 'State of the engine environments (torch, piper), their sources and the worker pool.', OBJECT({}), ANY, ram=64 * MiB, progress=False, cancel=False))
    ops.append(operation('install_engine', 'Install engine', 'Create or repair an engine environment (PyTorch CUDA or CPU, Piper) at its final path, with vendored sources and an import check.',
        OBJECT({'engine': ENUM('Engine', ['torch', 'piper'], 'torch'), 'cpu_only': BOOLEAN('Install the CPU build of PyTorch', False)}, required=('engine',)),
        ANY, ram=1 * GiB, disk=15 * GiB, permissions=('network',), duration=1200))
    ops.append(operation('diagnose_backend', 'Diagnose backend', 'Start the worker of a backend and report engine versions, CUDA availability and resident models.',
        OBJECT({'backend': ENUM('Backend', list(backends.BACKENDS), 'sfx_procedural')}, required=('backend',)), ANY, ram=512 * MiB, progress=False))
    ops.append(operation('release_workers', 'Release workers', 'Stop resident workers to free VRAM and RAM.', OBJECT({}), ANY, ram=64 * MiB, progress=False, cancel=False))
    known = {op['id'] for op in ops}
    unknown = sorted(set(EXCLUSIVE_GROUPS) - known)
    if unknown:
        raise SystemExit('EXCLUSIVE_GROUPS names operations that do not exist: ' + ', '.join(unknown))
    for op in ops:
        op['exclusiveGroups'] = list(EXCLUSIVE_GROUPS.get(op['id'], ()))

    tested = {}
    tested_path = APP / 'platform-tested.json'
    if tested_path.is_file():
        tested = json.loads(tested_path.read_text('utf-8-sig'))
    platforms = [
        {'os': 'Windows', 'architecture': 'x64', 'status': tested.get('windows', {}).get('status', 'Experimental'), 'computeBackends': ['CPU', 'CUDA'],
         **({'tested': tested['windows']['tested']} if tested.get('windows', {}).get('tested') else {}),
         'notes': tested.get('windows', {}).get('notes', 'Not yet validated on this machine.')},
        {'os': 'Linux', 'architecture': 'x64', 'status': 'Unknown', 'computeBackends': ['CPU', 'CUDA'], 'notes': 'Launcher script provided; never executed by the author.'},
    ]
    models_by_backend = {b: model_catalog.manifest_models(b) for b in backends.BACKENDS}
    manifest = {
        'schemaVersion': 1, 'protocolVersion': '1.0', 'id': TOOL_ID, 'name': TOOL_NAME, 'version': __version__,
        'description': 'Audio studio: multitrack editor, effects and VST3/CLAP/LV2/JSFX workflows with tail rendering, sound-effect, music and voice generation (procedural, AudioLDM, ACE-Step 1.5, Piper, Qwen3-TTS, Fish Speech S2 Pro), voice presets, mastering tools. Standalone Dear ImGui application, CLI and MCP on one runtime.',
        'vendor': 'Cyberalien', 'author': 'Cyberalien', 'license': 'GPL-3.0-only (Tool code, see LICENSE). CyToolsCore SDK: MIT (LICENCES/CyToolsCore-MIT.txt). Engines and model weights keep their own licences: see backends, app/licenses.json and LICENCES/.',
        'executable': 'runtime/python/Scripts/python.exe app/tool.py', 'categories': ['audio', 'generation', 'processing'],
        'tags': ['audio', 'editor', 'vst3', 'clap', 'lv2', 'jsfx', 'workflow', 'tts', 'music', 'sfx', 'mastering'],
        'capabilities': ['jobs', 'cancellation', 'progress', 'backends', 'models'],
        'backends': backends.manifest_entries(models_by_backend), 'platforms': platforms,
        'interfaces': ['Native', 'CLI', 'JSONL', 'HTTP', 'MCP', 'ImGui'],
        'runtimeRequirements': [{'id': 'python', 'version': '>=3.11,<3.13', 'required': True, 'executable': 'python'},
                                {'id': 'git', 'required': False, 'executable': 'git', 'notes': 'Used by install_engine to vendor Fish Speech and ACE-Step sources'},
                                {'id': 'ffmpeg', 'required': False, 'executable': 'ffmpeg', 'notes': 'Only for MP3 output of the music backend'}],
        'concurrency': {'policy': 'Sequential', 'maxWorkers': 1},
        'idleUnloadPolicy': 'After5Minutes',
        'operations': ops,
        'standaloneExecutable': 'CyTools_AudioStudio.exe',
    }
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    manifest = build()
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'
    target = APP / 'CyTool.json'
    if args.check:
        current = target.read_text('utf-8-sig') if target.exists() else ''
        if current != text:
            print('CyTool.json is stale; run build_manifest.py')
            return 1
        print('CyTool.json is up to date')
        return 0
    target.write_text(text, 'utf-8')
    print(f'wrote {target} ({len(manifest["operations"])} operations, {len(manifest["backends"])} backends)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
