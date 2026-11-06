---
id: operation-master-audio
title: master_audio
description: Maîtrise : adapter à une enregistrement de référence (Matchering : spectre, dynamique et niveau sonore) ou normaliser vers un cible de niveau sonore avec un limiteur de pic réel. Travail post optionnel.
section: Référence
order: 200
parent: operations
sourceRevision: ff08599f2d461100
---

Maîtrise : adapter à une enregistrement de référence (Matchering : spectre, dynamique et niveau sonore) ou normaliser vers un cible de niveau sonore avec un limiteur de pic réel. Travail post optionnel.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `input` | `string` | Oui | Bande son vers maîtrise  |
| `reference` | `string` | Non | Enregistrement de référence à adapter (mode référence) `default=""` |
| `mode` | `value` | Non | Mode `default="loudness"`, `enum=["reference", "loudness"]` |
| `target_lufs` | `number` | Non | Cible de niveau sonore intégré (mode niveau) `default=-14.0`, `minimum=-30.0`, `maximum=-5.0` |
| `ceiling_db` | `number` | Non | Plafond de pic réel (dBTP) `default=-1.0`, `minimum=-6.0`, `maximum=0.0` |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `post_workflow` | `string` | Non | Travail optionnel (nom enregistré) appliqué au son généré, avec le rendu en queue. `default=""` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `file` | `string` | Oui | Fichier de résultat  |
| `mimeType` | `string` | Oui | MIME type  |
| `sampleRate` | `integer` | Oui | Taux d'échantillonnage `default=48000` |
| `channels` | `integer` | Oui | Canaux `default=2` |
| `durationSeconds` | `number` | Oui | Durée (s) `default=0.0` |
| `sizeBytes` | `integer` | Non | Taille en octets `default=0` |
| `report` | `object` | Non | Rapport de rendu  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : `matchering`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation master_audio
```
