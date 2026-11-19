

## Native AI communication (Core 0.11.0)

The packaged CyMCPSDK 0.7.1 library implements CLI, JSONL, HTTP and MCP.
Call `ai_communication_status` with `includeOperations: true` for the effective complete
operation schemas, backends, permissions and resources. Use `DescribeOperation`,
`CanRun` and `EstimateResources` before `SubmitJob`; poll `GetJob` or consume `GetEvents`.
MCP provides `op_<operationId>` and the generic `cy_submit_job`; do not flatten or omit
advanced parameters. Absolute readable input paths are imported automatically.
AI sessions are temporary: export wanted results with `cy_export_job` before
`cy_finish_task`; a CLI invocation uses `--export-dir` to retain files.
Never use temporary output paths after task cleanup. Preserve explicit consent for
licences and destructive business actions; discovery does not grant permissions.
Existing application-owned model/provider adapters remain application-owned.
The native communication upgrade does not grant an agent extra filesystem rights.
For the first upgrade from Core 0.10.x use the full Windows package, which includes
the native library. Linux/macOS native builds require validation on those platforms.
