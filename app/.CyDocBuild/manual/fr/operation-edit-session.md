---
id: operation-edit-session
title: edit_session
description: Crée ou ouvre une session, applique des actions (ajoute/remplace/supprime des pistes, ajoute/mouve/inverse/supprime des clips, ajoute des chaînes, maître, queue, automatisation), enregistre et sauvegarde. La version sans…
section: Référence
order: 200
parent: operations
sourceRevision: 093ddac98cb36d78
---

Crée ou ouvre une session, applique des actions (ajoute/remplace/supprime des pistes, ajoute/mouve/inverse/supprime des clips, ajoute des chaînes, maître, queue, automatisation), enregistre et sauvegarde. La version sans interface graphique de l'éditeur.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `session` | `string` | Non | Dossier de session existant ou session.json ; vide = nouvelle session  |
| `samplerate` | `value` | Non | Taux d'échantillonnage d'une nouvelle session `default=48000`, `enum=[44100, 48000, 96000]` |
| `actions` | `array` | Non | Actions appliquées dans l'ordre `default=[]` |
| `save_as` | `string` | Non | Nom de la session (sous data/sessions) ou dossier absolu ; vide = ne pas enregistrer  |
| `render` | `boolean` | Non | Enregistrer le mélange après les actions `default=false` |
| `output_format` | `value` | Non | Format audio de sortie `default="wav"`, `enum=["wav", "flac", "mp3", "ogg", "aac"]` |
| `subtype` | `value` | Non | Format d'échantillon pour WAV/FLAC/AIFF (ignoré par les formats perte de qualité) `default="PCM_24"`, `enum=["PCM_16", "PCM_24", "PCM_32", "FLOAT"]` |
| `bitrate_kbps` | `value` | Non | Taux de bits en kbit/s pour MP3/AAC `default=192`, `enum=[64, 96, 128, 160, 192, 256, 320]` |
| `tail` | `object` | Non | Surcharge de rendu de la queue ; quand omis, les paramètres du workflow s'appliquent.  |
| `selection` | `array/null` | Non | Optionnel [début, fin] secondes pour l'enregistrement `default=null` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `actions` | `array` | Oui | Voir les paramètres de l’opération.  |
| `session` | `string/null` | Non | Voir les paramètres de l’opération.  |
| `document` | `object` | Oui | Voir les paramètres de l’opération.  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation edit_session
```
