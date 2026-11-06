---
id: operation-repaint-music
title: repaint_music
description: Réécrire une plage de temps d'un enregistrement et le raccorder de nouveau, en laissant le reste inchangé.
section: Référence
order: 200
parent: operations
sourceRevision: 747dafbb8bd6c11f
---

Réécrire une plage de temps d'un enregistrement et le raccorder de nouveau, en laissant le reste inchangé.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `caption` | `string` | Oui | Titre de style (genre, humeur, instruments, production)  |
| `lyrics` | `string` | Non | Paroles avec optionnellement des balises [Couplet]/[Chorus] ; vide pour instrumental `default=""` |
| `instrumental` | `boolean` | Non | Aucun chant `default=false` |
| `language` | `value` | Non | Langue du chant (inconnu = laissez le modèle décider) `default="unknown"`, `enum=["unknown", "ar", "az", "bg", "bn", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fr", "he", "hi", "hr", "ht", "hu", "id", "is", "it", "ja", "ko", "la", "lt", "ms", "ne", "nl", "no", "pa", "pl", "pt", "ro", "ru", "sa", "sk", "sr", "sv", "sw", "ta", "te", "th", "tl", "tr", "uk", "ur", "vi", "yue", "zh"]` |
| `bpm` | `integer/null` | Non | Tempo; null = modèle décide `default=null`, `minimum=30`, `maximum=300` |
| `keyscale` | `string` | Non | Clé, par exemple "C Majeur"; vide = modèle décide `default=""` |
| `time_signature` | `value` | Non | Signe de temps; vide = modèle décide `default=""`, `enum=["", "2", "3", "4", "6"]` |
| `steps` | `integer` | Non | Étapes de diffusion (le modèle turbo a été formé pour 8) `default=8`, `minimum=1`, `maximum=60` |
| `seed` | `integer/null` | Non | Graine; null = aléatoire. Le pistolet N utilise la graine+N-1 `default=null`, `minimum=0`, `maximum=2147483647` |
| `output_format` | `value` | Non | Format de pistolet (mp3 nécessite ffmpeg) `default="flac"`, `enum=["flac", "wav", "mp3"]` |
| `track_count` | `integer` | Non | Nombre de pistes `default=1`, `minimum=1`, `maximum=4` |
| `post_workflow` | `string` | Non | Travail optionnel (nom enregistré) appliqué au son généré, avec le rendu en queue. `default=""` |
| `source_audio` | `string` | Oui | Enregistrement à éditer  |
| `start_seconds` | `number` | Non | Début de la région `default=0.0`, `minimum=0.0`, `maximum=600.0` |
| `end_seconds` | `number` | Non | Fin de la région ; -1 = fin de fichier `default=-1.0`, `minimum=-1.0`, `maximum=600.0` |
| `repaint_mode` | `value` | Non | Mode `default="balanced"`, `enum=["conservative", "balanced", "aggressive"]` |
| `repaint_strength` | `number` | Non | Force (mode équilibré) `default=0.5`, `minimum=0.0`, `maximum=1.0` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `tracks` | `array` | Oui | Voir les paramètres de l’opération.  |
| `captionUsed` | `string` | Non | Légende envoyée au modèle  |
| `lyricsUsed` | `string` | Non | Paroles envoyées au modèle  |
| `metadata` | `object` | Non | Voir les paramètres de l’opération.  |
| `taskType` | `string` | Non | Tâche  |
| `sampleRate` | `integer` | Oui | Taux d'échantillonnage `default=48000` |
| `outputFormat` | `string` | Non | Format  |
| `timings` | `object` | Non | Voir les paramètres de l’opération.  |
| `vramPeakBytes` | `integer` | Non | VRAM pic crested `default=0` |
| `report` | `object` | Non | Voir les paramètres de l’opération.  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : `acestep`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation repaint_music
```
