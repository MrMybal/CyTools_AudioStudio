# CyTools AudioStudio

A standalone audio studio for Windows (desktop application, command line and MCP server on one
runtime), built on the [CyToolsCore](https://github.com/MrMybal/CyToolsCore) SDK. French user
guide: [LISEZ-MOI.md](LISEZ-MOI.md). Developer guide: [app/README.md](app/README.md).

## What it does

- **Multitrack editor** in the spirit of GoldWave / Audacity: waveforms per channel, clips you can
  move, trim (non-destructively) and fade, selection editing (cut, copy, paste, delete, trim,
  silence, split), undo / redo, recording from the microphone, playback through the default
  output, sessions saved as folders.
- **Insert chains per track and on the master bus** with 106 native effects (92 of them real-time)
  and VST3 plugins, each with its own interface: input / output meters and a live scope, transfer
  curve and gain-reduction history for the dynamics, draggable bands over the live spectrum for the
  parametric EQ, crossovers for the multiband processors, decay envelope for the reverbs, echo taps
  for the delays, LFO views, goniometer, spectrum analyser, LUFS loudness meter, 16-step pattern
  editor, pitch-correction gauge. Everything is heard while playing.
- **Automation lanes** for volume, pan, mute and any parameter of any insert (native effect or
  VST3), drawn over the track, edited with the mouse, or recorded live while playing.
- **Effects**: compressors (feed-forward, vintage opto / VCA / FET / vari-mu, multiband, dynamic EQ,
  de-esser, transient shaper, look-ahead maximizer, gate, expander), equalisers and filters
  (parametric, graphic, tilt, shelves, notch, ladder, auto-wah, formants, hum remover), reverbs
  (JUCE, impulse-response hall / plate / room / chamber / cathedral / spring, convolution, shimmer,
  gated), delays (tape, tempo-synced, ping-pong, multi-tap, dual, reverse), modulation (chorus,
  ensemble, flanger, phaser, vibrato, tremolo, auto-pan, rotary speaker, ring modulator, frequency
  shifter, doubler, resonator), saturation (tape, tube, overdrive, fuzz, wave folder, multiband,
  guitar amp with cabinets, exciter, bit crusher, cassette, vinyl, telephone), vocal tools (vocoder,
  real-time pitch shifter, pitch correction, harmoniser), stereo tools, restoration (real-time
  spectral noise reduction, de-clicker), analysers and utilities.
- **Workflows**: chains of effects, VST3 plugins and models saved as JSON, applied to a selection,
  a track, a file or a folder, with **tail rendering** so reverb and delay tails are never cut.
- **Generation** with several models per family, selectable in the interface: sound effects
  (procedural synthesiser, AudioLDM), music (ACE-Step 1.5: songs, remix, repaint, lyrics), voices
  (Piper, Qwen3-TTS, Fish Speech S2 Pro) with voice cloning from a file or the microphone, voice
  presets that regenerate the same voice, an optional text assistant for TTS annotations, Whisper
  transcription.
- **Mastering**: loudness normalisation with a true-peak limiter, reference mastering (Matchering).
- **Headless scripting**: `edit_session` and `batch_session` operations script the editor from
  the command line or MCP (add / replace / remove tracks, chains, master, render), including
  batches of sounds through one project.
- **Models and engines** installed from the application (state, size, source, licence, download,
  resume, repair, gated-model authorisation) and **GitHub update streams** for the application,
  the engine sources and the model catalogue, with staging, verification and rollback.

## Requirements

- Windows 10/11 x64 (the only platform executed by the author; a Linux launcher script is provided
  but was never run), Python 3.11, Git on the PATH.
- An NVIDIA GPU with CUDA for the generation models (AudioLDM, ACE-Step, Qwen3-TTS, Fish Speech —
  Fish Speech needs about 20 GB of free VRAM). The editor, the effects, VST3 hosting and Piper run
  on the CPU.
- Model weights are **not** in this repository; they are downloaded from the Models tab.

## Installation

```powershell
git clone https://github.com/MrMybal/CyTools_AudioStudio.git
cd CyTools_AudioStudio
# 1. private Python environment of the application (interface, CLI, MCP, DSP, VST3)
C:\Users\<you>\AppData\Local\Programs\Python\Python311\python.exe -m venv runtime\python
.\runtime\python\Scripts\python.exe -m pip install "cytools-core[mcp] @ git+https://github.com/MrMybal/CyToolsCore.git@442f537"
.\runtime\python\Scripts\python.exe -m pip install --keyring-provider disabled -r app\requirements.txt
# 2. engines (heavy, private): PyTorch CUDA 12.8 stack + pinned Fish Speech / ACE-Step sources, and Piper
.\runtime\python\Scripts\python.exe app\setup_engine.py torch      # add --cpu-only without an NVIDIA GPU
.\runtime\python\Scripts\python.exe app\setup_engine.py piper
# 3. Windows launcher (MSVC Build Tools)
powershell -ExecutionPolicy Bypass -File app\build_launcher.ps1
```

Then double-click `CyTools_AudioStudio.exe`, or run `runtime\python\Scripts\python.exe app\desktop.py`.
Both engines can also be installed from the Models tab.

## Command line and MCP

```powershell
.\runtime\python\Scripts\python.exe app\tool.py describe
.\runtime\python\Scripts\python.exe app\tool.py invoke process_audio --params "{\"input\": \"D:/x.wav\", \"workflow_name\": \"my chain\"}"
.\runtime\python\Scripts\python.exe app\tool.py invoke batch_session --params "{\"session\": \"D:/.../data/sessions/template\", \"inputs\": [\"D:/sounds/a.wav\"], \"slot\": {\"track\": \"Voice\"}, \"output_dir\": \"D:/renders\"}"
.\runtime\python\Scripts\python.exe app\tool.py --data-dir data\jobs-mcp mcp     # MCP stdio server (40 operations)
```

Input paths must be absolute. Operations that download need the `network` permission
(`create-client --permission network`, token in `CYTOOLS_TOKEN`); the interface has it.

## Repository layout

```
CyTools_AudioStudio.exe   Windows launcher (built locally, not in git)
CyTools_AudioStudio.sh    Linux launcher (never executed by the author)
LISEZ-MOI.md              user guide (French)
app/                      code, manifest (CyTool.json), interface, workers, tests, docs, scripts
data/                     inputs, models, jobs, sessions, workflows, presets, settings, logs (not in git)
runtime/                  private Python, engines, vendored sources, updates, backups (not in git)
```

Tests (fixtures only, no GPU): `cd app && ..\runtime\python\Scripts\python.exe -m unittest discover -s tests`.
Evidence of what was actually executed lives in `data/reports/VALIDATION.md` of an installation and
is summarised in [app/Docs/CapabilityCoverage.md](app/Docs/CapabilityCoverage.md).

## Licence

The application code is free software under the **GNU General Public License v3.0**
([LICENSE](LICENSE)), like the CyToolsCore SDK and pedalboard / JUCE it depends on. Engines and
model weights keep their own licences, listed in [app/licenses.json](app/licenses.json) and shown
in the Options tab; the Models tab asks for acceptance before downloading a gated or
non-commercial model.
