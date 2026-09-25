# Model catalogue

Two generated files describe every downloadable model of CyTools_AudioStudio. Do not edit
them by hand: re-run `python app/scripts/build_model_catalog.py --verify` from the tool root.

## catalog.json

`models[]` holds one entry per neural model (8 entries: 1 AudioLDM, 1 ACE-Step, 1 Fish
Speech, 5 Qwen3-TTS variants).

| Field | Meaning |
|---|---|
| `id` | Stable identifier used by settings, jobs and the CLI (`audioldm-s-full-v2`, `acestep-1.5`, `fishspeech-s2-pro`, `qwen3tts-<variant>`). |
| `backend` / `family` | Which worker loads it (`audioldm`, `acestep`, `fishspeech`, `qwen3tts`) and which tab it belongs to (`sfx`, `music`, `voice`). |
| `name` / `variant` | Display name and short variant label (empty when the backend has a single model). |
| `directory` | Where the weights live, relative to the tool root: `data/models/<backend>/<subdir>`. ACE-Step is flat (its four component folders sit directly inside); `components` lists them. |
| `source` | Hugging Face repository, pinned 40-hex revision, whether the repository is gated (none is at the moment) and the model page. |
| `files[]` | Every file to download: `path` inside `directory`, `size` in bytes, upstream `sha256` when Hugging Face publishes one (LFS files), `sizeCheckOnly: true` when only the size can be verified. ACE-Step's two `.py` remote-code files carry `presenceOnly: true`: upstream rewrites them without changing the revision, so only their presence is checked. Qwen non-LFS files add `gitBlobSha1` (the git blob hash from the API listing) for an optional stronger check. |
| `downloadBytes` | Sum of `files[].size`. |
| `license` | Name, URL, whether the interface must collect a personal acceptance before downloading, and whether commercial use is `allowed`, `forbidden` or `unknown`. |
| `legacy` | Old tool and path (relative to that tool's root) where the same weights were installed before the merge, so a migration can reuse them instead of downloading again. |
| `resources` | Peak VRAM / RAM to reserve, in bytes. AudioLDM: measured by CyTools_AudioGen (2.7 GB / 3.5 GB decimal). ACE-Step: 16 GiB with the language-model planner (about 10 GiB without) / 12.5 GiB. Fish: 20 GiB declared (not a measured peak) / 16 GiB. Qwen 0.6B: 5 / 6 GiB, 1.7B: 8 / 10 GiB. |
| `default` | Exactly one entry per family: `audioldm-s-full-v2` (sfx), `acestep-1.5` (music), `qwen3tts-1.7B-CustomVoice` (voice). |
| `notes` | Free text for the interface. |

## piper-voices.json

`voices` is keyed by `<lang>-<name>-<quality>` (177 voices) and keeps `language`, `quality`,
`num_speakers`, `speaker_id_map` and `aliases` from the upstream `voices.json`. Each voice adds
`directory` (`data/models/piper/<key>`), `files[]` normalised to `{remotePath, path, size, md5}`
(`remotePath` is appended to `source.baseUrl`, `path` is the basename stored on disk), `downloadBytes`,
the pinned `source` (`rhasspy/piper-voices` at revision `c10ece1a...`), the licence (MIT per voice
model card, personal acceptance required, commercial use unknown because each voice's dataset has
its own terms) and `legacy` (`CyTools_Piper_TTS/data/models/<key>`).

## How it was built

`app/scripts/build_model_catalog.py` reads only:

- `app/audiostudio/backends/_reference/audiogen_config.py` (AudioLDM file table, parsed with `ast`),
- `app/audiostudio/backends/_reference/acestep_model_catalog.json`,
- `app/audiostudio/backends/_reference/fishspeech_model_catalog.json`,
- `<legacy>/CyTools_Qwen3-TTS/data/models/<variant>/source.json` (the pinned Hugging Face API
  listings written by the old tool; if they are absent the previous `catalog.json` entries are kept),
- `app/audiostudio/backends/_reference/piper_voices.json`.

`--verify` (or `--verify-only`) then checks, for every entry whose legacy weights are still installed
under `--legacy-root` (default: the parent of the tool folder), that each listed file exists with the
listed size, and compares the catalogue hashes with the receipts the old tools wrote after download
(`verified.json`, `cytools-acestep15-installed.json`, `installed.json`, `<file>.installed.json`).
Last run (2026-09-22): 8 models and the one installed Piper voice checked, 0 mismatches; the two
ACE-Step `.py` files differ in size as expected (presence-only).
