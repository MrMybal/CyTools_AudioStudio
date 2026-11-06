---
id: operation-edit-session
title: edit_session
description: Create or open a session, apply actions (add / replace / remove tracks, add / move / reverse / remove clips, insert chains, master, tail, automation), save it and optionally render the mix. The headless counterpart of the editor.
section: Reference
order: 200
parent: operations
revision: 093ddac98cb36d78
---

Create or open a session, apply actions (add / replace / remove tracks, add / move / reverse / remove clips, insert chains, master, tail, automation), save it and optionally render the mix. The headless counterpart of the editor.

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `session` | `string` | No | Existing session folder or session.json; empty = new session  |
| `samplerate` | `value` | No | Sample rate of a new session `default=48000`, `enum=[44100, 48000, 96000]` |
| `actions` | `array` | No | Actions applied in order `default=[]` |
| `save_as` | `string` | No | Session name (under data/sessions) or absolute folder; empty = do not save  |
| `render` | `boolean` | No | Render the mix after the actions `default=false` |
| `output_format` | `value` | No | Output audio format `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | No | Sample format for WAV/FLAC/AIFF (ignored by lossy formats) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | No | Bitrate in kbit/s for MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `tail` | `object` | No | Tail rendering override; when omitted the workflow settings apply.  |
| `selection` | `array/null` | No | Optional [start, end] seconds to render `default=null` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `actions` | `array` | Yes | See the operation parameters.  |
| `session` | `string/null` | No | See the operation parameters.  |
| `document` | `object` | Yes | See the operation parameters.  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: none declared.
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation edit_session
```
