# Maintaining CyTools_AudioStudio

Read README.md (this folder), CyTool.json, tool.py and the SDK contract in Docs/ (AgentGuide.md,
StandaloneDelivery.md, Localization.md, GenerationConfigurations.md, FullOperationAccess.md,
TaskFiles.md) before changing anything.

## Rules specific to this Tool

1. `CyTool.json` is generated: edit `build_manifest.py`, then run
   `..\runtime\python\Scripts\python.exe build_manifest.py` and
   `..\runtime\python\Scripts\cytools.exe validate CyTool.json` (the SDK is public: https://github.com/MrMybal/CyToolsCore, MIT since 0.10.1).
   Every new operation needs a handler registered in `audiostudio/operations/*.py` and a test.
2. Regeneration order after a change: `scripts/build_model_catalog.py` (only when a model pin
   changes) -> `build_manifest.py` -> `scripts/merge_locales.py` (after adding UI strings to
   `locales/audiostudio.fr.json`) -> `cytools validate` -> `python -m unittest discover -s tests`.
3. Heavy code lives in `workers/` and runs in engine environments declared by `engines.json`.
   The application process (interface, CLI, MCP) never imports torch, transformers, diffusers or
   any model library. Base-environment dependencies are `requirements.txt`; engine dependencies are
   `requirements-engine-*.txt` and are installed by `setup_engine.py` at their final path.
   The SDK pin (version and commit) lives in `scripts/build_licences.py`; after changing it run
   that script: it rewrites `../LICENCES/` from the SDK really installed and `tests/test_licences.py`
   fails while the folder is stale. The product stays GPL-3.0 (LICENSE); never replace GPL by MIT
   in a dependency, a model or a third-party source.
4. Workers speak the JSON-lines protocol of `workers/_protocol.py`; the host is
   `audiostudio/engines/workerhost.py`. Progress goes through `reporter.progress`, never stdout.
   A GPU backend keeps its model resident; `WorkerPool.make_exclusive` stops the others first.
   Operations that must never overlap carry `exclusiveGroups` (`EXCLUSIVE_GROUPS` in
   `build_manifest.py`: `gpu`, `engine_torch`, `engine_piper`, `model_files`); a new GPU, engine or
   model-file operation must be added to that table.
5. Tail rendering is mandatory in every rendering path (`audiostudio/dsp/tail.py`): never cut a
   reverb or delay tail; a selection rendered in the editor overlaps its tail onto what follows.
6. Model weights are declared in `models/catalog.json` / `models/piper-voices.json` and checked
   file by file (`audiostudio/models`): a folder that exists is not an installed model. Licences
   requiring acceptance are accepted by the user in the Models tab, never in code or settings.
   Tokens come from the OS keyring only; never in argv, jobs, logs or configurations.
7. The interface follows CyUI (`gui/cyui`, rules of D:/_Project/CyImgui_Interface/docs/AI_GUIDE.md):
   colours from `cyui.palette()` by role only, sizes through `cyui.dp()` or the style, one primary
   button per view, icon buttons with a tooltip naming the action and its shortcut and a stable
   identity (`id=`), property tables in forms, empty panels that say why, messages through the
   panels' `message` (status bar and notification). Check a change in the five themes
   (`desktop.py --ui-test-tab=Editor --ui-test-theme=<key>`).
8. Every visible string of `gui/*.py` and `dsp/effects.py` needs an English source and a French
   entry (`tests/test_locales.py` enforces it). Never translate identifiers, paths, model names,
   prompts or user text.
9. Evidence before claims: `platform-tested.json` and `data/reports/VALIDATION.md` only record
   executions that really happened on this machine. Linux is declared, not tested. ASIO is out of
   scope (no Steinberg SDK licence); VST2 is out of scope.
10. The five superseded Tools (AudioGen, ACE-Step 1.5, FishSpeech S2 Pro, Piper TTS, Qwen3-TTS)
   are gone: their weights live in `data/models/<backend>` (receipt
   `data/reports/migration-legacy.json`) and their reference code in
   `../runtime/backups/legacy-reference/`. Do not resurrect a dependency on them.

## Commands

```powershell
cd <path>\CyTools_AudioStudio\app
..\runtime\python\Scripts\python.exe -m unittest discover -s tests -v
..\runtime\python\Scripts\python.exe tool.py describe
..\runtime\python\Scripts\python.exe tool.py invoke generate_sfx --backend sfx_procedural --params "{\"prompt\": \"laser beep\"}"
..\runtime\python\Scripts\python.exe scripts\validate_mcp.py
..\runtime\python\Scripts\python.exe desktop.py --ui-test-tab=Editor
powershell -ExecutionPolicy Bypass -File build_launcher.ps1
```
