---
id: operation-generate-music
title: generate_music
description: Text to music with ACE-Step 1.5: a full arrangement, optional sung lyrics, optional style reference recording. 48 kHz stereo.
section: Reference
order: 200
parent: operations
revision: a686ea7ca3035ad4
---

Text to music with ACE-Step 1.5: a full arrangement, optional sung lyrics, optional style reference recording. 48 kHz stereo.

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
| `duration_seconds` | `number` | No | Length of the song (s) `default=60.0`, `minimum=10.0`, `maximum=600.0` |
| `plan_with_lm` | `boolean` | No | Let the 5Hz planning language model refine caption, lyrics and metadata (+6 GiB VRAM) `default=true` |
| `creativity` | `number` | No | Planner temperature `default=0.85`, `minimum=0.0`, `maximum=2.0` |
| `nucleus` | `number` | No | Planner top-p `default=0.9`, `minimum=0.1`, `maximum=1.0` |
| `reference_audio` | `string` | No | Optional reference recording whose timbre and production are followed `default=""` |
| `reference_strength` | `number` | No | How strongly the reference is followed `default=0.2`, `minimum=0.0`, `maximum=1.0` |
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
runtime\python\Scripts\python.exe app\tool.py describe-operation generate_music
```
