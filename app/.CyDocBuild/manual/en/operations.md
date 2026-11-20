---
id: operations
title: Automation and API
description: Connect a client and inspect the available operations.
section: Reference
order: 80
parent: overview
revision: 8631ed0fe7a84f2f
---

## Command line {#cli}

From the application root, use the private Python interpreter. `describe` and `list-operations` inspect the public contract.

```powershell
runtime\python\Scripts\python.exe app\tool.py describe
runtime\python\Scripts\python.exe app\tool.py list-operations
runtime\python\Scripts\python.exe app\tool.py invoke list_effects --params "{}"
```

## MCP {#mcp}

Configure your MCP client to start the private interpreter with `app/tool.py mcp`, using the application folder as its working directory. Restart the connection when its exposed operation catalogue changes.

## Task files {#task-files}

Local file inputs accept absolute readable paths and are imported into the task workspace automatically. Export wanted results before finishing the task. Do not rely on temporary paths after task cleanup.

## Operations {#operations}

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


## Native communication {#native-communication}

The Windows package includes CyToolsCore 0.12.0 and the native CyMCPSDK 0.7.1
communication library. The same complete operation parameters are available to AI
clients and the standalone application. Run `ai_communication_status` with
`includeOperations: true` to inspect the effective catalogue. This does not contact
an AI provider or generate content.

CLI-generated files are temporary by default. Add `--export-dir` followed by an
absolute destination outside the job store when you want to keep them. In MCP,
export with `cy_export_job` before `cy_finish_task`. The original input file, installed
models, conversations and project documents are not removed by task cleanup.

For the first upgrade from a 0.10.x Core, install the full Windows package.
Application-only updates cannot add the required native library to an older runtime.
Model and provider integrations keep their existing compatibility and permissions;
this upgrade does not make an unsupported model or platform supported.


## Local MCP access {#local-mcp-access}

Core **0.12.0** embeds native CyMCPSDK commit **`34d4bca`**. From the Tool root, start
the local service explicitly:

```powershell
runtime/python/Scripts/python.exe app/tool.py --data-dir data/jobs serve --port 8766
```

Free is the initial profile: connect using only `http://127.0.0.1:8766/mcp`. All exposed
operations are callable without a token or additional transport approval. Arguments,
licence acceptance and explicit destructive-action confirmations remain business rules.
The portable API is at `/v1`; the listener binds only to 127.0.0.1.

Missing choices migrate to Free; explicit profiles are preserved. Use the server option
`--access-profile free`, `--access-profile local_controlled`, `--access-profile token_only`
or `--access-profile protected_access`. Local controlled applies host-selected permissions.
Token only and Protected require a valid token; Protected retains credential permissions.
With the command above, the choice persists in `data/jobs/communication.json`. Restart
the service to change the active profile. CLI/embedded and chat-provider permissions
are unchanged. Use `ai_communication_status` with `includeOperations: true` for discovery.

Install the full Windows package for this native runtime update; app-only updates reject
the old runtime ABI. For a local source upgrade, install the bundled wheel:

```powershell
runtime/python/Scripts/python.exe -m pip install --no-deps app/packages/cytools_core-0.12.0-py3-none-win_amd64.whl
```

Export wanted task files before `cy_finish_task`. Task cleanup preserves original inputs,
installed models, conversations and persistent project documents. Windows x64 is the
validated platform for this update; Linux/macOS native builds require target validation.
