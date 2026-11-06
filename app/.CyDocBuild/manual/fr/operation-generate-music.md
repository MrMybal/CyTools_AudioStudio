---
id: operation-generate-music
title: generate_music
description: Texte en musique avec ACE-Étape 1.5 : une arrangement complète, paroles optionnelles chantées, enregistrement de style optionnel. 48 kHz stéréo.
section: Référence
order: 200
parent: operations
sourceRevision: a686ea7ca3035ad4
---

Texte en musique avec ACE-Étape 1.5 : une arrangement complète, paroles optionnelles chantées, enregistrement de style optionnel. 48 kHz stéréo.

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
| `duration_seconds` | `number` | Non | Durée de la chanson (s) `default=60.0`, `minimum=10.0`, `maximum=600.0` |
| `plan_with_lm` | `boolean` | Non | Laissez le langage de planification à 5Hz affiner la légende, les paroles et les métadonnées (+6 GiB VRAM) `default=true` |
| `creativity` | `number` | Non | Température du planificateur `default=0.85`, `minimum=0.0`, `maximum=2.0` |
| `nucleus` | `number` | Non | Top-p du planificateur `default=0.9`, `minimum=0.1`, `maximum=1.0` |
| `reference_audio` | `string` | Non | Enregistrement de référence optionnel dont le timbre et la production sont suivis `default=""` |
| `reference_strength` | `number` | Non | De quelle manière le enregistrement de référence est suivi `default=0.2`, `minimum=0.0`, `maximum=1.0` |
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
runtime\python\Scripts\python.exe app\tool.py describe-operation generate_music
```
