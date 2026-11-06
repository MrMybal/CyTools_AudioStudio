---
id: operation-process-audio
title: process_audio
description: Render un workflow (effets, VST3/CLAP/LV2/JSFX plugins, modèles) sur un fichier, avec un rendu en queue de file afin que les retards et les délais ne soient jamais coupés. Un processus de sélection ne traite que cette région…
section: Référence
order: 200
parent: operations
sourceRevision: e985451e54271f79
---

Render un workflow (effets, VST3/CLAP/LV2/JSFX plugins, modèles) sur un fichier, avec un rendu en queue de file afin que les retards et les délais ne soient jamais coupés. Un processus de sélection ne traite que cette région et superpose son queue de file sur le son audio suivant.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `input` | `string` | Oui | Fichier audio à traiter  |
| `workflow` | `object` | Non | Document de workflow intégré (format cytools-audiostudio-workflow). Utilisez workflow_name au lieu de cela pour faire référence à un workflow enregistré.  |
| `workflow_name` | `string` | Non | Nom d'un workflow enregistré dans data/workflows (voir list_workflows). Vide = pas de traitement. `default=""` |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `selection_start` | `number` | Non | Début de la région à traiter (s) ; -1 = tout le fichier `default=-1.0`, `minimum=-1.0`, `maximum=360000.0` |
| `selection_end` | `number` | Non | Fin de la région à traiter (s) ; -1 = fin du fichier `default=-1.0`, `minimum=-1.0`, `maximum=360000.0` |
| `tail` | `object` | Non | Surcharge de rendu de la queue ; quand omis, les paramètres du workflow s'appliquent.  |
| `output_name` | `string` | Non | Nom du fichier de sortie sans extension ; par défaut = nom du fichier d'entrée + suffixe `default=""` |
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
runtime\python\Scripts\python.exe app\tool.py describe-operation process_audio
```
