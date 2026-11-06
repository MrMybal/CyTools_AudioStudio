---
id: operation-voice-piper
title: voice_piper
description: CPU text-to-speech avec une voix Piper ONNX (22.05 kHz mono). Seulement du texte brut, pas de annotations.
section: Référence
order: 200
parent: operations
sourceRevision: 5d6ae1698b56cc94
---

CPU text-to-speech avec une voix Piper ONNX (22.05 kHz mono). Seulement du texte brut, pas de annotations.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | `string` | Oui | Texte à prononcer  |
| `voice` | `string` | Non | Clé de voix, par exemple fr_FR-siwis-medium (voir list_voices) `default="fr_FR-siwis-medium"` |
| `speaker` | `integer` | Non | Index du locuteur pour les voix à plusieurs locuteurs `default=0`, `minimum=0`, `maximum=1000` |
| `length_scale` | `number` | Non | Vitesse (1 = normal, 2 = deux fois plus lente) `default=1.0`, `minimum=0.25`, `maximum=4.0` |
| `noise_scale` | `number` | Non | Expressivité `default=0.667`, `minimum=0.0`, `maximum=2.0` |
| `noise_w_scale` | `number` | Non | Variation de la largeur de phonème `default=0.8`, `minimum=0.0`, `maximum=2.0` |
| `volume` | `number` | Non | Volume `default=1.0`, `minimum=0.01`, `maximum=2.0` |
| `normalize` | `boolean` | Non | Normaliser la sortie `default=true` |
| `threads` | `integer` | Non | CPU threads `default=2`, `minimum=1`, `maximum=16` |
| `post_workflow` | `string` | Non | Travail optionnel (nom enregistré) appliqué au son généré, avec le rendu en queue. `default=""` |
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
- Moteurs : `piper`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation voice_piper
```
