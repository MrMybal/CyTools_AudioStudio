# Capability coverage — CyTools_AudioStudio 0.1.0

Status legend: **tested** = executed on the author's machine (see data/reports); **implemented** = code
present, not validated by a real run; **not exposed** = engine capability deliberately left out;
**n/a** = not applicable.

## Editing and processing (base environment)

| Native capability | Operation / control | Standalone control | Status / evidence |
|---|---|---|---|
| Decode WAV/FLAC/OGG/AIFF/MP3 (libsndfile), AAC/M4A/WMA/video containers (PyAV) | `process_audio.input`, editor Open | Editor > Open audio | tested (5 formats round trip, `dsp-test.*`) |
| Encode wav/flac/ogg/aiff (subtypes), mp3 (pedalboard), aac (PyAV, bitrate) | `output_format`, `subtype`, `bitrate_kbps` | Editor export bar, Workflows | tested |
| 106 native effects with typed parameters (92 real-time), application code under GPL-3.0 | workflow `effect` nodes, track inserts, `list_effects` (`realtime`, `sidechain`, `ui`) | Editor Effect..., Workflows > Add effect, Editor > FX panel | tested (every effect renders block-wise and offline; test_dsp, test_processors) |
| Insert chains per track and on the master bus (effects + VST3), enable/bypass, mix, reorder, side-chain, presets, bake | session schema 2, `render_session` | Editor > FX / Master FX, inserts panel | tested (test_renderer, interaction run, CLI render_session) |
| Effect interfaces: meters + live scope, transfer curve/GR (dynamics, maximizer), crossovers (multiband compressor and saturation), draggable EQ over the spectrum, dynamic EQ with live band gains, filter response (incl. formants, hum notches), reverb decay, delay taps (tape, tempo), LFO (rotary, ensemble, doubler, shifters), distortion curve, vocoder bands, goniometer (imager, mid/side), analyser, LUFS loudness meter, noise reduction spectrum with learn mode, 16-step pattern editor, pitch correction gauge | — | Editor > FX panel | tested (screenshots `ui-fx-*.png`, knob drag in the interaction run) |
| Automation lanes: volume, pan, mute, any insert parameter; point add/move/delete, write while playing, undo | session schema 2, `render_session` | Editor > A button, lane overlay, Write automation | tested (test_renderer, interaction run) |
| Master bus lane with gain, mute, meters, inserts, automation | session schema 2 | Editor > Master lane | tested (interaction run) |
| Mouse navigation: right-drag / middle-drag / Space+drag / hand tool, scrollbar, overview strip, ruler scrub, wheel zoom | — | Editor timeline | tested (interaction run) |
| Export and `render_session` render inserts + automation + master with the tail (never cut) | `render_session` | Editor > Export mix | tested (CLI: 1.3 s tail on a session) |
| Headless session scripting: add / replace / remove tracks, chains from workflows, master, tail, save, render | `edit_session` | — (script counterpart of the editor) | tested (test_batch, CLI: create, render, reopen, replace, add, remove, render) |
| Batch of sounds through one project (slot track, chain and automation kept, one render per sound, external output folder) | `batch_session` | — | tested (test_batch, CLI: 3 sounds -> 3 mixes) |
| Tail rendering (extend until silence, threshold, max, hold) | workflow `tail`, `process_audio.tail` | Workflows > Tail rendering | tested (1 s in -> 4.9 s out; editor scenario +17821 frames) |
| VST3 scan / describe / process / state / native window | `scan_plugins`, `list_plugins`, `describe_plugin`, `vst3` nodes | Plugins tab, Workflows > Add VST3, Open plugin window | tested with CyDAW Test Gain (scan, render, state); window open implemented, not scripted |
| VST3 instruments (MIDI input) | — | — | not exposed |
| VST2 | — | — | not exposed (no licence) |
| Selection processing with tail overlap | `selection_start/end`, editor Apply workflow | Editor | tested (CLI selection render; editor scenario) |
| Batch processing | `batch_process` | Workflows > Process files... | tested (test_runtime) |
| Conversion (rate, channels, format) | `convert_audio` | Advanced operations | tested |
| Analysis: peak, RMS, LUFS, true peak, clipping, DC, silences | `analyze_audio` | Advanced operations | tested |
| Mastering: reference (Matchering) and loudness target + true-peak limiter | `master_audio` | Advanced operations | tested (both modes, CLI) |
| Multitrack editor: tracks, gain/pan/mute/solo, move, undo/redo, cut/copy/paste/delete/trim/silence/split/insert silence, record, sessions | editor only (interactive) | Editor tab | tested (document tests; scripted UI scenario; real playback) |
| Real-time monitoring of a chain during playback | — | Editor inserts (heard live, DSP load shown) | tested (interaction run, playback through the renderer) |
| ASIO | — | — | not exposed (no Steinberg SDK licence); WASAPI/DirectSound via sounddevice |

## Sound effects

| Native capability | Operation | Standalone | Status |
|---|---|---|---|
| Procedural synthesizer: 36 archetypes, EN/FR keywords, modifiers, repeats, seed, variations, natural duration | `generate_sfx` (backend `sfx_procedural`), `preview_sfx_recipe`, `list_sfx_types` | Generate > Sound effects | tested (bit-identical port, CLI, MCP) |
| AudioLDM: prompt, negative prompt, steps, guidance, duration, seed, variations, device cpu/cuda, resample, peak | `generate_sfx` (backend `audioldm`) | Generate > Sound effects (AudioLDM) | tested CUDA (CLI); CPU path implemented, not run |
| AudioLDM custom checkpoints / LoRA | — | — | not exposed (model library template not wired) |

## Music (ACE-Step 1.5)

| Native capability | Operation | Standalone | Status |
|---|---|---|---|
| text2music: caption, lyrics, instrumental, language, bpm, key, time signature, steps, seeds, duration, planner (thinking + CoT flags), creativity, nucleus, format, tracks | `generate_music` | Generate > Music | tested 20 s no planner (CLI); planner path implemented (same code as former Tool, tested there), not rerun here |
| Style reference (reference_audio + strength) | `generate_music.reference_audio` | Generate > Music | implemented (former Tool validated it), not rerun |
| cover (remix) with similarity | `remix_music` | Generate > Music > Remix | implemented, not rerun |
| repaint (start/end, mode, strength) | `repaint_music` | Generate > Music > Repaint | implemented, not rerun |
| 5Hz LM: create / format lyrics and metadata | `write_lyrics` | Generate > Music > Write lyrics | tested (CLI create) |
| Other upstream tasks (lego, extract, complete, vocal-to-BGM), base/sft/XL checkpoints, LoRA | — | — | not exposed |

## Voices

| Native capability | Operation | Standalone | Status |
|---|---|---|---|
| Piper: 177 voices catalogue, speaker index, length/noise/noise_w/volume/normalise/threads | `voice_piper`, `list_voices`, `install_model piper.<key>` | Generate > Voices > Piper; Models | tested fr_FR-siwis-medium (CLI, MCP, preset); other voices downloadable, not tested |
| Qwen3-TTS custom (9 speakers, instruction), clone (reference + transcription or x-vector), design (description); 5 variants; device; delivery split; sampling; seed | `voice_qwen3tts` | Generate > Voices > Qwen3-TTS | tested custom 0.6B/1.7B with annotations (CLI/MCP); clone and design implemented (validated in the former Tool), not rerun |
| Inline annotations [tone]/[pause] | `text_annotations` | checkbox | tested (5 segments) |
| Fish Speech S2 Pro: turns with speaker index and expression, references with transcription, sampling, chunk length, precision | `voice_fishspeech` | Generate > Voices > Fish Speech (single turn; dialogues via Advanced/MCP) | tested 2 turns without reference (CLI); cloning implemented, not run |
| Voice presets: save/list/delete, regenerate with new text, reference change detection | `save_voice_preset`, `list_voice_presets`, `delete_voice_preset`, `generate_voice` | Generate > Voices > Save as preset / Saved preset | tested (Piper preset round trip) |
| Text preparation: heuristic; LLM Qwen3-1.7B per target, validation and fallback | `prepare_tts_text` | Advanced operations (MCP/CLI oriented) | tested (heuristic 3 targets; LLM qwen3tts paragraph mode, fishspeech turns, piper) |

## Models, engines, maintenance

| Capability | Operation | Standalone | Status |
|---|---|---|---|
| Catalogue state per file, download with resume, verify, repair, remove, licence acceptance, gated access states, keyring token | `list_models`, `install_model`, `verify_model`, `remove_model` | Models tab | state/verify tested on the 9 migrated models; download tested only for a Piper voice in the former Tool — not rerun here (no missing model to download) |
| Engine environments at final path, import check, CPU-only build | `engine_status`, `install_engine` | Models tab | torch and piper built and verified here; CPU-only not run |
| GitHub application release (zip + sha256, staging, verification, activation at start, rollback) | maintenance.py | Updates tab | implemented; archive safety and rollback covered by fixtures only — no real repository configured |
| Engine source staging / activation / rollback | maintenance.py | Updates tab | implemented, not run against upstream |
| Shared installation storage, CUDA toolkit registration | SDK operations | Options | provided by the SDK template |
