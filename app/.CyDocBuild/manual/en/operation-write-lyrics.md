---
id: operation-write-lyrics
title: write_lyrics
description: Planning language model only: turn an idea into caption, lyrics and metadata (create) or format existing lyrics (format).
section: Reference
order: 200
parent: operations
revision: 8e6b683c7cd67136
---

Planning language model only: turn an idea into caption, lyrics and metadata (create) or format existing lyrics (format).

## Parameters {#contract}

| Name | Type | Required | Description |
|---|---|---|---|
| `mode` | `value` | Yes | Mode `default="create"`, `enum=["create", "format"]` |
| `idea` | `string` | No | Idea or theme (create) `default=""` |
| `caption` | `string` | No | Caption (format) `default=""` |
| `lyrics` | `string` | No | Lyrics (format) `default=""` |
| `instrumental` | `boolean` | No | Instrumental `default=false` |
| `language` | `value` | No | Language `default="unknown"`, `enum=["unknown", "ar", "az", "bg", "bn", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fr", "he", "hi", "hr", "ht", "hu", "id", "is", "it", "ja", "ko", "la", "lt", "ms", "ne", "nl", "no", "pa", "pl", "pt", "ro", "ru", "sa", "sk", "sr", "sv", "sw", "ta", "te", "th", "tl", "tr", "uk", "ur", "vi", "yue", "zh"]` |
| `bpm` | `integer/null` | No | Tempo `default=null`, `minimum=30`, `maximum=300` |
| `duration_seconds` | `number/null` | No | Target duration `default=null`, `minimum=10`, `maximum=600` |
| `keyscale` | `string` | No | Key `default=""` |
| `time_signature` | `value` | No | Time signature `default=""`, `enum=["", "2", "3", "4", "6"]` |
| `creativity` | `number` | No | Temperature `default=0.85`, `minimum=0.0`, `maximum=2.0` |
| `nucleus` | `number` | No | Top-p `default=0.9`, `minimum=0.1`, `maximum=1.0` |
## Returns {#returns}

| Name | Type | Required | Description |
|---|---|---|---|
| `caption` | `string` | Yes | Caption  |
| `lyrics` | `string` | Yes | Lyrics  |
| `metadata` | `object` | No | See the operation parameters.  |
| `statusMessage` | `string` | No | Status `default=""` |

## Behaviour and access {#behaviour}

- Required permissions: none declared.
- Backends: `acestep`
- Cancellation: supported.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation write_lyrics
```
