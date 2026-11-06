---
id: operation-write-lyrics
title: write_lyrics
description: Modèle de plan : transformer une idée en légende, paroles et métadonnées (créer) ou formater des paroles existantes (formater).
section: Référence
order: 200
parent: operations
sourceRevision: 8e6b683c7cd67136
---

Modèle de plan : transformer une idée en légende, paroles et métadonnées (créer) ou formater des paroles existantes (formater).

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `mode` | `value` | Oui | Mode `default="create"`, `enum=["create", "format"]` |
| `idea` | `string` | Non | Idée ou thème (créer) `default=""` |
| `caption` | `string` | Non | Légende (formater) `default=""` |
| `lyrics` | `string` | Non | Paroles (formater) `default=""` |
| `instrumental` | `boolean` | Non | Instrumental `default=false` |
| `language` | `value` | Non | Langue `default="unknown"`, `enum=["unknown", "ar", "az", "bg", "bn", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fr", "he", "hi", "hr", "ht", "hu", "id", "is", "it", "ja", "ko", "la", "lt", "ms", "ne", "nl", "no", "pa", "pl", "pt", "ro", "ru", "sa", "sk", "sr", "sv", "sw", "ta", "te", "th", "tl", "tr", "uk", "ur", "vi", "yue", "zh"]` |
| `bpm` | `integer/null` | Non | Tempo `default=null`, `minimum=30`, `maximum=300` |
| `duration_seconds` | `number/null` | Non | Durée cible `default=null`, `minimum=10`, `maximum=600` |
| `keyscale` | `string` | Non | Clé `default=""` |
| `time_signature` | `value` | Non | Signe temporel `default=""`, `enum=["", "2", "3", "4", "6"]` |
| `creativity` | `number` | Non | Température `default=0.85`, `minimum=0.0`, `maximum=2.0` |
| `nucleus` | `number` | Non | Top-p `default=0.9`, `minimum=0.1`, `maximum=1.0` |
## Retours {#returns}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `caption` | `string` | Oui | Sous-titre  |
| `lyrics` | `string` | Oui | Lettres de chanson  |
| `metadata` | `object` | Non | Voir les paramètres de l’opération.  |
| `statusMessage` | `string` | Non | État `default=""` |

## Comportement et accès {#behaviour}

- Autorisations requises : aucune déclarée.
- Moteurs : `acestep`
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation write_lyrics
```
