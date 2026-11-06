---
id: operation-transcribe-audio
title: transcribe_audio
description: Enregistrement à transcrire
section: Référence
order: 200
parent: operations
sourceRevision: d7f6ccd8340dc5ae
---

Enregistrement à transcrire

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `input` | `string` | Oui | Code de langue (fr, en, ...); vide = détection automatique  |
| `language` | `string` | Non | Transcription `default=""` |
| `device` | `value` | Non | Dispositif de calcul `default="cuda"`, `enum=["cuda", "cpu"]` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | `string` | Oui | Transcription  |
| `segments` | `array` | Non | Voir les paramètres de l’opération.  |
| `durationSeconds` | `number` | Non | Durée d'audio `default=0.0` |
| `language` | `string` | Non | Langue utilisée  |
| `seconds` | `number` | Non | Temps de traitement `default=0.0` |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : `whisper`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation transcribe_audio
```
