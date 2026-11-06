---
id: operation-install-engine
title: install_engine
description: Créer ou réparer un environnement moteur (PyTorch, CUDA ou CPU, Piper) à son chemin final, avec des sources vendoriées et un contrôle d'importation.
section: Référence
order: 200
parent: operations
sourceRevision: 4afe763ceef0aace
---

Créer ou réparer un environnement moteur (PyTorch, CUDA ou CPU, Piper) à son chemin final, avec des sources vendoriées et un contrôle d'importation.

## Paramètres {#contract}

| Nom | Type | Obligatoire | Description |
|---|---|---|---|
| `engine` | `value` | Oui | Moteur `default="torch"`, `enum=["torch", "piper"]` |
| `cpu_only` | `boolean` | Non | Installer la version CPU de PyTorch `default=false` |
## Retours {#returns}

Aucun champ nommé n’est déclaré à ce niveau. Consultez le schéma avec `describe-operation` pour connaître sa forme exacte.

## Comportement et accès {#behaviour}

- Autorisations requises : `network`
- Moteurs : aucun déclaré.
- Annulation : prise en charge.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe-operation install_engine
```
