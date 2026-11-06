---
id: operation-batch-process
title: batch_process
description: Rendu du même workflow sur plusieurs fichiers. Chaque sortie conserve le nom de la source avec un suffixe.
section: Référence
order: 200
parent: operations
sourceRevision: 47e9638848134a91
---

Rendu du même workflow sur plusieurs fichiers. Chaque sortie conserve le nom de la source avec un suffixe.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `inputs` | `array` | Oui | Fichiers audio  |
| `workflow` | `object` | Non | Document de workflow intégré (format cytools-audiostudio-workflow). Utilisez workflow_name au lieu de cela pour faire référence à un workflow enregistré.  |
| `workflow_name` | `string` | Non | Nom d'un workflow enregistré dans data/workflows (voir list_workflows). Vide = pas de traitement. `default=""` |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `suffix` | `string` | Non | Suffixe ajouté à chaque nom de sortie `default="_processed"` |
| `tail` | `object` | Non | Surcharge de rendu de la queue ; quand omis, les paramètres du workflow s'appliquent.  |
| `continue_on_error` | `boolean` | Non | Continuer quand un fichier échoue `default=true` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `results` | `array` | Oui | Voir les paramètres de l’opération.  |
| `failed` | `array` | Non | Voir les paramètres de l’opération.  |
| `count` | `integer` | Oui | Fichiers traités `default=0` |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation batch_process
```
