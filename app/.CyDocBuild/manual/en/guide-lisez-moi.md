---
id: guide-lisez-moi
title: User guide
description: Use the application step by step.
section: Guide
order: 10
parent: overview
revision: d393ef81b1fe1a3e
---

## CyTools Audio Studio {#cytools-audiostudio}

Standalone audio studio: multi-track editor with per-track inserts (106 native effects including 92 real-time, plugins VST3, each with its own interface), automation, master bus, effects and plugins VST3 in workflows (with rendering of the tail of reverb/delay), sound effects generation, music and voice creation, voice presets, mastering, optional text assistant. One application replaces CyTools_AudioGen, ACE-Step 1.5, FishSpeech S2 Pro, Piper TTS and Qwen3-TTS.

## Start {#demarrer}

Double-click `CyTools_AudioStudio.exe`. No terminal, no JSON to edit.

Tabs :

- Editor: import WAV, FLAC, MP3, OGG, AAC and other supported audio, or record from the microphone. A session contains tracks and clips; save sessions under `data/sessions`. The toolbar groups Session, Transport, Output, Display, Options and Export. Each control has a tooltip.
  - Add an empty track with + Track. Tracks have gain, pan, mute and solo controls. All clips on a track pass through its insert chain. Drag a clip’s title bar to move it in time or to another track; moving it to another track applies that track’s effects. Drag its left or right edge for non-destructive trimming, and its upper corner handle for a fade. The context menu offers deletion, duplication, reverse playback, splitting, moving to the cursor and moving to another track. Drag inside the waveform to select audio. Cut, copy, paste, delete, trim, silence and split selections, with undo/redo. Apply an effect with preview or apply a workflow to a selection.
  - Navigate with the wheel to zoom. Shift+wheel, right/middle dragging, Space+dragging, the Hand tool (H), the scrollbar and the overview pan horizontally. Double-click the overview for the complete view. Click or drag the ruler to place the cursor. Ctrl+wheel zooms vertically; drag a track’s lower edge to resize it. Shortcuts include Space, Ctrl+Z/Y, Ctrl+X/C/V, Delete, Home, Esc, H and F.
  - The FX button on a track or the Master row opens its insert chain in the lower panel. Add, remove, bypass or drag effects and VST3 plugins to reorder them. Each effect has its own controls and meters: input/output waveforms and spectra, compressor transfer and gain-reduction curves, EQ bands, multiband crossovers, reverb decay, delay echoes, LFO, stereo scope and analyzers. Listen during playback. Select the sidechain for ducking, a triggered gate or a vocoder carrier. Save per-effect and per-plugin presets, bake an insert into a clip including its tail, or send the chain to Workflows. Inserts belong to the selected track or Master.
  - Drop audio on a track to create a clip at the pointer when space is free, otherwise after its last clip. Drop below the tracks to create a new track. An empty track retains its inserts. Drop a session folder to open it, a workflow JSON to load it, or an impulse response for convolution. Effect and plugin lists have a search field insensitive to accents and case; Enter selects the first match.
  - The A button chooses an automation lane for track/Master gain, pan, mute or any insert parameter. Right-click an effect control to show its curve. Click to add a point, drag to move it, and double-click or right-click to remove it. Ctrl+drag selects. Write automation records control changes during playback. Buffer size (256–4096) and DSP load appear in Transport.
  - Export the mix as WAV, FLAC, MP3, OGG or AAC. Rendering includes track inserts, automation and Master effects and can extend until the effect tails become silent.
- Generate : sound effects (procedural synthesis or AudioLDM), music (ACE-Step 1.5 : song, remix, editing a section, writing lyrics), voice (Piper CPU, Qwen3-TTS, Fish Speech S2 Pro, or a saved preset). Each generation can go through a post-processing workflow and is automatically added to the editor.
- Effects (106) : compressor, vintage compressor (opto / VCA / FET / vari-mu), expander, noise gate, limiter, lookahead maximizer, multiband compressor, EQ dynamic, de-esser, transient shaper; parametric EQ 8-band, graphic EQ 10-band, tilt, high-pass/low-pass, band-pass, notch, peak, bell, ladder filter, auto-wah, ladder filter LFO; reverb (JUCE, hall/plaque/room/chamber/cathedral/spring by impulse response, convolution on file, shimmer, gated), delay, ping-pong delay, multi-tap delay, band delay, tempo delay, double L/R delay, inverted delay, Haas. chorus, ensemble chorus, doubler, flanger, phaser, vibrato, tremolo, auto-pan, ring modulator, frequency shifter, rotating cabinet, resonator, real-time time transposer, octave / sub-bass; tape and tube saturation, overdrive, fuzz, wavefolder, exciter, guitar / bass amplifier (clean, crunch, lead, bass + speaker cabinets 1x12/2x12/4x12/1x15), cabinet only, multiband saturation, distortion, clipping, bitcrush, sample rate reducer, telephone, vinyl, cassette, codecs GSM/MP3; vocoder, formant filter, pitch correction (auto-tune, pitch choice), harmonizer; stutter and trance gate (16-step motif, tempo) ; width stereo, 3-band stereo imager, mid/side, panoramic, balance, bass in mono, channel tool; anti-rumble, click removal, real-time spectral noise reduction (learned or adaptive profile, 75 ms latency) ; analyzer, loudness meter LUFS, test generator, dither; utilities and file-wide effects (normalization, LUFS, fades, inversion, transposition, time stretch, noise reduction, resampling...).
- Workflows : native and plugin VST3 effect chain, 'extend until silence' setting (reverb or delay are never cut off), save/load, apply to selection, all tracks, or files in batch.
- Plugins : VST3 folders, scan in a separate process (a plugin that crashes does not close the application), catalog, open plugin window (state is preserved in the workflow).
- Models : engines (PyTorch CUDA, Piper) and models: state, size, source, license, Download / Resume / Repair / Verify / Delete, accept personal licenses.
- Updates : GitHub application updates (repository to configure), engine source updates (pinned revisions) with rollback; weights follow their own catalog.
- Options : language (english by default, french), theme (medium grey, light grey, amber night, violet, navy blue), density (compact or comfortable), text size, licenses, save/load configuration, shared storage.
- Interface : designed with CyUI, the Cy* software interface library (Python port in `app/gui/cyui`). Toolbars are icon buttons with a tooltip naming the action and its shortcut (Space, Ctrl+O, Ctrl+S, Ctrl+Z, Ctrl+Y, Ctrl+X/C/V, Del, H, F). The status bar at the bottom displays the last message, ongoing jobs (progress, cancel button) and the audio engine status; events also appear as notifications.

## Batch processing of a session (CLI / MCP, without interface) {#traitement-par-lots-d-une-session-cli-mcp-sans-interface}

Prepare the project in the editor (background tracks, one 'placement' track with its insert chain and automation, master inserts), save the session, then control it from a script :

- `batch_session` : renders the session once for each input sound; each sound replaces the audio of the placeholder track (its chain, its curves, its gain and its position are kept), the mix is rendered with the tail, then the next sound takes its place. Output: a file per sound in the chosen folder.
- `edit_session` : scripted actions (add / replace / delete a track, place a chain of effects or a workflow, set the master and effect tail), save and render in the same call.

Example (Windows ; under Linux `runtime/python/bin/python`, not executed by the author)

```powershell
.\runtime\python\Scripts\python.exe app\tool.py invoke batch_session --params "{\"session\": \"D:/x/data/sessions/modele\", \"inputs\": [\"D:/sons/a.wav\", \"D:/sons/b.wav\"], \"slot\": {\"track\": \"Voice\"}, \"output_dir\": \"D:/rendus\", \"suffix\": \"_mix\"}"
```

Input paths must be absolute. See [Automation and API](doc:operations) for operation parameters.

## Voice: presets and annotations {#voix-presets-et-annotations}

After generation, saving a preset preserves the engine, model, and all parameters (including the reference voice with its fingerprint): the same voice is regenerated with new text. Qwen3-TTS (model 1.7B CustomVoice) accepts `[tone: chuchoté]` and `[pause: 500ms]` in the text. Operation `prepare_tts_text` (heuristic or assistant Qwen3-1.7B) prepares these annotations, or dialogue turns for Fish Speech; an AI controlling the tool via MCP can do this itself.

## Locations {#emplacements}

- `runtime/python` : Python from the application ; `runtime/engines` : engine environments ; `runtime/sources` : pinned Fish Speech sources and ACE-Step.
