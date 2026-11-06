---
id: operation-prepare-tts-text
title: prepare_tts_text
description: Transformer du texte brut en la notation attendue par le backend de voix : annotations [ton]/[pause] pour Qwen3-TTS, des tours de dialogue avec des expressions pour Fish Speech, et du texte par ligne par sentence pour Piper.…
section: Référence
order: 200
parent: operations
sourceRevision: 815dce9e3292c662
---

Transformer du texte brut en la notation attendue par le backend de voix : annotations [ton]/[pause] pour Qwen3-TTS, des tours de dialogue avec des expressions pour Fish Speech, et du texte par ligne par sentence pour Piper. La méthode heuristique n'a pas besoin de modèle ; la méthode llm utilise l'assistant local Qwen3-1.7B et tombe en retrait sur la heuristique lorsque son output n'est pas utilisable. Un client AI peut sauter cette étape et annoter lui-même.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `text` | `string` | Oui | Texte brut  |
| `target` | `value` | Non | Backend de voix `default="qwen3tts"`, `enum=["qwen3tts", "fishspeech", "piper"]` |
| `method` | `value` | Non | Méthode d'annotation `default="heuristic"`, `enum=["heuristic", "llm"]` |
| `style` | `string` | Non | Style global de narration souhaité (par exemple, narration chaleureuse et calme) `default=""` |
| `language` | `string` | Non | Indice de langue pour l'assistant `default=""` |
| `pause_ms` | `integer` | Non | Pause insérée entre les paragraphes (heuristique) `default=500`, `minimum=0`, `maximum=3000` |
| `device` | `value` | Non | Dispositif de calcul `default="cuda"`, `enum=["cuda", "cpu"]` |
| `max_new_tokens` | `integer` | Non | Budget de sortie de l'assistant `default=1024`, `minimum=64`, `maximum=4096` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `target` | `string` | Oui | Backend  |
| `method` | `string` | Oui | Méthode réellement utilisée  |
| `text` | `string` | Non | Texte annoté (qwen3tts, piper) `default=""` |
| `turns` | `array` | Non | Voir les paramètres de l’opération.  |
| `textAnnotations` | `boolean` | Non | Ajoutez text_annotations=true à voice_qwen3tts `default=false` |
| `fallbackReason` | `string` | Non | Pourquoi la sortie de l'assistant a-t-elle été remplacée par l'heuristique `default=""` |
| `raw` | `string` | Non | Conversion vocale en texte avec Whisper large-v3 turbo (99 langues, marquage de temps de segment). Utilisé pour obtenir la transcription exacte d'un enregistrement de référence avant de cloner une voix. `default=""` |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation prepare_tts_text
```
