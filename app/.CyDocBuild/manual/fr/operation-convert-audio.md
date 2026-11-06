---
id: operation-convert-audio
title: convert_audio
description: Changer le format, la fréquence d'échantillonnage, la profondeur du bit ou le nombre de canaux.
section: Référence
order: 200
parent: operations
sourceRevision: 855f4d4a43a35d09
---

Changer le format, la fréquence d'échantillonnage, la profondeur du bit ou le nombre de canaux.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `input` | `string` | Oui | Fichier audio  |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `samplerate` | `value` | Non | Fréquence d'échantillonnage cible ; 0 conserve le taux source `default=0`, `enum=[0, 8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000]` |
| `channels` | `value` | Non | Nombre de canaux cible ; 0 conserve le disposition source `default=0`, `enum=[0, 1, 2]` |
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
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation convert_audio
```
