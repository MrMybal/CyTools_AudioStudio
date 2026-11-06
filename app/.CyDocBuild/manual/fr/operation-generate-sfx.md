---
id: operation-generate-sfx
title: generate_sfx
description: Texte vers effet sonore. Backend sfxprocedural synthétise déterministiquement à partir d'un catalogue de 36 archétypes (pas de modèle, instantané) ; backend audioldm exécute le modèle de diffusion AudioLDM sur CPU ou CUDA.
section: Référence
order: 200
parent: operations
sourceRevision: e73ac535a0d93f6f
---

Texte vers effet sonore. Backend sfx_procedural synthétise déterministiquement à partir d'un catalogue de 36 archétypes (pas de modèle, instantané) ; backend audioldm exécute le modèle de diffusion AudioLDM sur CPU ou CUDA.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `prompt` | `string` | Oui | Description de l'effet sonore (en anglais ou en français)  |
| `negative_prompt` | `string` | Non | À éviter (audioldm seulement) `default=""` |
| `duration_seconds` | `number/null` | Non | Longueur en secondes ; null = longueur naturelle (procedural) ou 5 s (audioldm) `default=null`, `minimum=0.2`, `maximum=30.0` |
| `seed` | `integer` | Non | Graine ; la variation N utilise la graine+N `default=0`, `minimum=0`, `maximum=2147483647` |
| `variations` | `integer` | Non | Nombre de variations `default=1`, `minimum=1`, `maximum=4` |
| `sample_rate` | `value` | Non | Taux d'échantillonnage de sortie `default=44100`, `enum=[16000, 22050, 24000, 44100, 48000]` |
| `bit_depth` | `value` | Non | WAV profondeur de bit `default=16`, `enum=[16, 24]` |
| `peak_dbfs` | `number` | Non | Cible de normalisation pic (dBFS) `default=-1.0`, `minimum=-40.0`, `maximum=0.0` |
| `steps` | `integer` | Non | Étapes de diffusion (seulement audioldm) `default=20`, `minimum=5`, `maximum=100` |
| `guidance_scale` | `number` | Non | Échelle de guidance (seulement audioldm) `default=2.5`, `minimum=1.0`, `maximum=15.0` |
| `device` | `value` | Non | Dispositif de calcul (seulement audioldm) `default="cuda"`, `enum=["cuda", "cpu"]` |
| `post_workflow` | `string` | Non | Travail optionnel (nom enregistré) appliqué au son généré, avec le rendu en queue. `default=""` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `variations` | `array` | Oui | Fichiers générés  |
| `backend` | `string` | Oui | Identifiant backend  |
| `engine` | `string` | Non | Nom de l'engine  |
| `sampleRate` | `integer` | Oui | Taux d'échantillonnage `default=44100` |
| `recipe` | `object/null` | Non | Recette procédurale (seulement sfx_procedural)  |
| `warnings` | `array` | Non | Voir les paramètres de l’opération.  |
| `report` | `object` | Non | Voir les paramètres de l’opération.  |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : `sfx_procedural`, `audioldm`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation generate_sfx
```
