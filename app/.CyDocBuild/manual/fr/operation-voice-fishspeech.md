---
id: operation-voice-fishspeech
title: voice_fishspeech
description: Dialogue multilocuteur avec des expressions en langage naturel par tour et clonage de la voix à partir de brèves références (0,1-30 s avec leur transcription). CUDA uniquement, 44,1 kHz mono.
section: Référence
order: 200
parent: operations
sourceRevision: f976716ee1e2b315
---

Dialogue multilocuteur avec des expressions en langage naturel par tour et clonage de la voix à partir de brèves références (0,1-30 s avec leur transcription). CUDA uniquement, 44,1 kHz mono.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `turns` | `array` | Oui | Passe de dialogue dans l'ordre  |
| `references` | `array` | Non | Enregistrements de référence par index du locuteur `default=[]` |
| `temperature` | `number` | Non | Température `default=0.8`, `minimum=0.1`, `maximum=1.5` |
| `top_p` | `number` | Non | Top-p `default=0.8`, `minimum=0.1`, `maximum=1.0` |
| `top_k` | `integer` | Non | Top-k `default=30`, `minimum=1`, `maximum=100` |
| `seed` | `integer` | Non | Semence `default=42`, `minimum=0`, `maximum=2147483647` |
| `max_new_tokens` | `integer` | Non | Nombre maximum de nouveaux tokens `default=1024`, `minimum=128`, `maximum=4096` |
| `chunk_length` | `integer` | Non | Longueur de l'unité `default=200`, `minimum=50`, `maximum=500` |
| `precision` | `value` | Non | Précision `default="bfloat16"`, `enum=["bfloat16", "float16"]` |
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
- Moteurs : `fishspeech`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation voice_fishspeech
```
