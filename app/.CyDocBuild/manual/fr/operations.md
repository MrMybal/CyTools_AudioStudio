---
id: operations
title: Automatisation et API
description: Connectez un client et consultez les opérations disponibles.
section: Référence
order: 80
parent: overview
sourceRevision: 1a923e0b044103da
---

## Ligne de commande {#cli}

Depuis la racine de l’application, utilisez son interpréteur Python privé. `describe` et `list-operations` examinent le contrat public.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe
runtime\python\Scripts\python.exe app\tool.py list-operations
runtime\python\Scripts\python.exe app\tool.py invoke list_effects --params "{}"
```

## MCP {#mcp}

Configurez votre client MCP pour lancer l’interpréteur privé avec `app/tool.py mcp`, en utilisant le dossier de l’application comme dossier de travail. Reconnectez-le lorsque le catalogue d’opérations exposées change.

## Fichiers des tâches {#task-files}

Les entrées locales acceptent des chemins absolus lisibles et sont importées automatiquement dans l’espace de la tâche. Exportez les résultats utiles avant de terminer la tâche. Ne réutilisez pas les chemins temporaires après nettoyage.

## Opérations {#operations}

- [`process_audio`](doc:operation-process-audio)
- [`batch_process`](doc:operation-batch-process)
- [`convert_audio`](doc:operation-convert-audio)
- [`analyze_audio`](doc:operation-analyze-audio)
- [`render_session`](doc:operation-render-session)
- [`edit_session`](doc:operation-edit-session)
- [`batch_session`](doc:operation-batch-session)
- [`list_effects`](doc:operation-list-effects)
- [`list_workflows`](doc:operation-list-workflows)
- [`get_workflow`](doc:operation-get-workflow)
- [`save_workflow`](doc:operation-save-workflow)
- [`scan_plugins`](doc:operation-scan-plugins)
- [`list_plugins`](doc:operation-list-plugins)
- [`describe_plugin`](doc:operation-describe-plugin)
- [`read_jsfx`](doc:operation-read-jsfx)
- [`validate_jsfx`](doc:operation-validate-jsfx)
- [`save_jsfx`](doc:operation-save-jsfx)
- [`generate_sfx`](doc:operation-generate-sfx)
- [`preview_sfx_recipe`](doc:operation-preview-sfx-recipe)
- [`list_sfx_types`](doc:operation-list-sfx-types)
- [`generate_music`](doc:operation-generate-music)
- [`remix_music`](doc:operation-remix-music)
- [`repaint_music`](doc:operation-repaint-music)
- [`write_lyrics`](doc:operation-write-lyrics)
- [`voice_piper`](doc:operation-voice-piper)
- [`voice_qwen3tts`](doc:operation-voice-qwen3tts)
- [`voice_fishspeech`](doc:operation-voice-fishspeech)
- [`generate_voice`](doc:operation-generate-voice)
- [`list_voices`](doc:operation-list-voices)
- [`save_voice_preset`](doc:operation-save-voice-preset)
- [`list_voice_presets`](doc:operation-list-voice-presets)
- [`delete_voice_preset`](doc:operation-delete-voice-preset)
- [`prepare_tts_text`](doc:operation-prepare-tts-text)
- [`transcribe_audio`](doc:operation-transcribe-audio)
- [`master_audio`](doc:operation-master-audio)
- [`list_models`](doc:operation-list-models)
- [`install_model`](doc:operation-install-model)
- [`verify_model`](doc:operation-verify-model)
- [`remove_model`](doc:operation-remove-model)
- [`engine_status`](doc:operation-engine-status)
- [`install_engine`](doc:operation-install-engine)
- [`diagnose_backend`](doc:operation-diagnose-backend)
- [`release_workers`](doc:operation-release-workers)
