---
id: operation-render-session
title: render_session
description: Mélange une session d'édition (pistes, chaînes d'inserts, voies d'automatisation, bus maître) vers un fichier ; les inserts étatiques retentissent après la fin (queue).
section: Référence
order: 200
parent: operations
sourceRevision: 2758125ec6a2f40a
---

Mélange une session d'édition (pistes, chaînes d'inserts, voies d'automatisation, bus maître) vers un fichier ; les inserts étatiques retentissent après la fin (queue).

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `session` | `string` | Oui | Dossier de session ou session.json enregistré par l'éditeur  |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `tail` | `object` | Non | Surcharge de rendu de la queue ; quand omis, les paramètres du workflow s'appliquent.  |
| `selection` | `array/null` | Non | Optionnel [début, fin] secondes à rendre au lieu de l'ensemble de la session `default=null` |
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
runtime\python\Scripts\python.exe app\tool.py describe-operation render_session
```
