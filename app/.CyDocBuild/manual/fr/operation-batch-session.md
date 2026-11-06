---
id: operation-batch-session
title: batch_session
description: Enregistrer une session une fois par son d'entrée : chaque son est placé dans une piste de slot (une piste de remplacement existante dont l'audio est remplacé, gardant ses inserts et l'automatisation, ou une nouvelle piste),…
section: Référence
order: 200
parent: operations
sourceRevision: 6fad77828f65a529
---

Enregistrer une session une fois par son d'entrée : chaque son est placé dans une piste de slot (une piste de remplacement existante dont l'audio est remplacé, gardant ses inserts et l'automatisation, ou une nouvelle piste), le mélange est enregistré avec la queue, puis le son suivant prend sa place.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `session` | `string` | Oui | Dossier de la session ou session.json  |
| `inputs` | `array` | Oui | Son à batcher  |
| `slot` | `object` | Non | Voir les paramètres de l’opération.  |
| `output_dir` | `string` | Non | Dossier de sortie ; vide = espace de travail du job  |
| `suffix` | `string` | Non | Suffixe ajouté à chaque nom de sortie `default=""` |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `tail` | `object` | Non | Surcharge de rendu de la queue ; quand omis, les paramètres du workflow s'appliquent.  |
| `selection` | `array/null` | Non | Optionnel [début, fin] secondes pour l'enregistrement `default=null` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `results` | `array` | Oui | Voir les paramètres de l’opération.  |
| `failed` | `array` | Non | Voir les paramètres de l’opération.  |
| `count` | `integer` | Oui | Fichiers enregistrés `default=0` |
| `outputDir` | `string` | Non | Dossier  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation batch_session
```
