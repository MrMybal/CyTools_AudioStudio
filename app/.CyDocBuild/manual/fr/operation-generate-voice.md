---
id: operation-generate-voice
title: generate_voice
description: Reproduire une voix à partir d'un préréglage enregistré (backend, modèle, tous les paramètres) avec du nouveau texte. Avertit lorsque l'enregistrement de référence a changé.
section: Référence
order: 200
parent: operations
sourceRevision: 6b561e02fe90b0d5
---

Reproduire une voix à partir d'un préréglage enregistré (backend, modèle, tous les paramètres) avec du nouveau texte. Avertit lorsque l'enregistrement de référence a changé.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `preset` | `string` | Oui | Id du préréglage (voir list_voice_presets)  |
| `text` | `string` | Oui | Texte à prononcer  |
| `seed` | `integer/null` | Non | Surcharger la semence du préréglage `default=null`, `minimum=0`, `maximum=2147483647` |
| `post_workflow` | `string/null` | Non | Surcharge le workflow post-préétabli (chaîne vide = aucun) `default=null` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `file` | `string` | Oui | Discours WAV  |
| `mimeType` | `string` | Oui | MIME type  |
| `sampleRate` | `integer` | Oui | Taux d'échantillonnage `default=24000` |
| `channels` | `integer` | Oui | Canaux `default=1` |
| `durationSeconds` | `number` | Oui | Durée (s) `default=0.0` |
| `backend` | `string` | Oui | Identifiant backend  |
| `model` | `string` | Non | Identifiant du modèle  |
| `processedFile` | `string` | Non | Résultat après le workflow post, lorsque l'un a été appliqué `default=""` |
| `generationSeconds` | `number` | Non | Temps de génération (s) `default=0.0` |
| `preset` | `object` | Non | Prévisualisation réutilisable (paramètres sans texte) pour regénérer la même voix  |
| `warnings` | `array` | Non | Voir les paramètres de l’opération.  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation generate_voice
```
