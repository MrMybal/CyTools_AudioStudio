---
id: operation-remix-music
title: remix_music
description: Audio to audio: regenerate a recording under a new caption and optional lyrics while keeping its structure (task cover).
section: Reference
order: 200
parent: operations
revision: 0c2ef9f7f8f07120
---

Audio to audio: regenerate a recording under a new caption and optional lyrics while keeping its structure (task cover).

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `caption` | `string` | Yes | Style caption (genre, mood, instruments, production)  |
| `lyrics` | `string` | No | Lyrics with optional [Verse]/[Chorus] tags; empty for instrumental `default=""` |
| `instrumental` | `boolean` | No | No vocals `default=false` |
| `language` | `value` | No | Vocal language (unknown = let the model decide) `default="unknown"`, `enum=["unknown", "ar", "az", "bg", "bn", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fr", "he", "hi", "hr", "ht", "hu", "id", "is", "it", "ja", "ko", "la", "lt", "ms", "ne", "nl", "no", "pa", "pl", "pt", "ro", "ru", "sa", "sk", "sr", "sv", "sw", "ta", "te", "th", "tl", "tr", "uk", "ur", "vi", "yue", "zh"]` |
| `bpm` | `integer/null` | No | Tempo; null = model decides `default=null`, `minimum=30`, `maximum=300` |
| `keyscale` | `string` | No | Key, e.g. "C Major"; empty = model decides `default=""` |
| `time_signature` | `value` | No | Time signature; empty = model decides `default=""`, `enum=["", "2", "3", "4", "6"]` |
| `steps` | `integer` | No | Diffusion steps (turbo model trained for 8) `default=8`, `minimum=1`, `maximum=60` |
| `seed` | `integer/null` | No | Seed; null = random. Track N uses seed+N-1 `default=null`, `minimum=0`, `maximum=2147483647` |
| `output_format` | `value` | No | Track format (mp3 needs ffmpeg) `default="flac"`, `enum=["flac", "wav", "mp3"]` |
| `track_count` | `integer` | No | Number of tracks `default=1`, `minimum=1`, `maximum=4` |
| `post_workflow` | `string` | No | Optional workflow (saved name) applied to the generated audio, with tail rendering. `default=""` |
| `source_audio` | `string` | Yes | Recording to remix  |
| `similarity` | `number` | No | Similarity to the source `default=0.6`, `minimum=0.0`, `maximum=1.0` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `tracks` | `array` | Yes | See the operation parameters.  |
| `captionUsed` | `string` | No | Caption sent to the model  |
| `lyricsUsed` | `string` | No | Lyrics sent to the model  |
| `metadata` | `object` | No | See the operation parameters.  |
| `taskType` | `string` | No | Task  |
| `sampleRate` | `integer` | Yes | Sample rate `default=48000` |
| `outputFormat` | `string` | No | Format  |
| `timings` | `object` | No | See the operation parameters.  |
| `vramPeakBytes` | `integer` | No | VRAM peak `default=0` |
| `report` | `object` | No | See the operation parameters.  |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: `acestep`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation remix_music
```
