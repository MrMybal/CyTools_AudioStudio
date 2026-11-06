---
id: operation-voice-qwen3tts
title: voice_qwen3tts
description: Discours expressif : interprètes de texte-à-parole avec instructions en langage naturel (personnalisé), clonage de la voix à partir d’un enregistrement de référence (clone) ou conception de la voix à partir d’une description…
section: Référence
order: 200
parent: operations
sourceRevision: 009c4a9416040e22
---

Discours expressif : interprètes de texte-à-parole avec instructions en langage naturel (personnalisé), clonage de la voix à partir d’un enregistrement de référence (clone) ou conception de la voix à partir d’une description (conception). Les annotations inline [tone: ...] et [pause: 500ms] sont prises en charge avec le modèle CustomVoice 1.7B. 24 kHz mono.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | `string` | Oui | Texte à prononcer ; paragraphe séparés par des lignes vides  |
| `model` | `value` | Non | Variant du modèle (custom nécessite CustomVoice, clone nécessite Base, design nécessite VoiceDesign) `default="1.7B-CustomVoice"`, `enum=["0.6B-CustomVoice", "1.7B-CustomVoice", "0.6B-Base", "1.7B-Base", "1.7B-VoiceDesign"]` |
| `mode` | `value` | Non | Mode `default="custom"`, `enum=["custom", "clone", "design"]` |
| `language` | `value` | Non | Langue `default="French"`, `enum=["Auto", "French", "English", "Chinese", "Japanese", "Korean", "German", "Russian", "Portuguese", "Spanish", "Italian"]` |
| `speaker` | `value` | Non | Interprète de texte (custom) `default="Ryan"`, `enum=["Ryan", "Aiden", "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee"]` |
| `instruction` | `string` | Non | Instructions de livraison (custom, 1.7B) ou description de la voix (conception) `default=""` |
| `reference_audio` | `string` | Non | Enregistrement de référence (clone) `default=""` |
| `reference_text` | `string` | Non | Transcription exacte de l’enregistrement de référence (clone) `default=""` |
| `x_vector_only` | `boolean` | Non | Cloner uniquement les embeddings du locuteur, pas de transcription `default=false` |
| `device` | `value` | Non | Dispositif de calcul `default="cuda"`, `enum=["cuda", "cpu"]` |
| `delivery` | `value` | Non | Diviser le texte en passages `default="paragraphs"`, `enum=["paragraphs", "segments", "complete"]` |
| `temperature` | `number` | Non | Température `default=0.9`, `minimum=0.1`, `maximum=2.0` |
| `top_k` | `integer` | Non | Top-k `default=50`, `minimum=1`, `maximum=200` |
| `top_p` | `number` | Non | Top-p `default=1.0`, `minimum=0.05`, `maximum=1.0` |
| `repetition_penalty` | `number` | Non | Pénalité de répétition `default=1.05`, `minimum=1.0`, `maximum=2.0` |
| `max_new_tokens` | `integer` | Non | Nombre maximum de nouveaux tokens par passage `default=2048`, `minimum=32`, `maximum=4096` |
| `seed` | `integer` | Non | Semence `default=42`, `minimum=0`, `maximum=2147483647` |
| `text_annotations` | `boolean` | Non | Activer les annotations [tone: ...] / [pause: ...] (seulement CustomVoice 1.7B) `default=false` |
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
- Moteurs : `qwen3tts`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation voice_qwen3tts
```
