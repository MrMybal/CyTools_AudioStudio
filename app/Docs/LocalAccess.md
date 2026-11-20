# Local MCP access profiles — Core 0.12.0

The native communication library is built from CyMCPSDK commit
`34d4bcae126bc83d1a2925b5047dac36e3d09d92` (or an explicitly selected compatible
committed revision). The default local MCP profile is **Free**. Starting HTTP is
still explicit: importing Core or opening a local Runtime does not start a server.

| Profile ID | Display name | Token | Operation policy |
| --- | --- | --- | --- |
| `free` | Free | None | All registered operations and public job controls |
| `local_controlled` | Local controlled / Local contrôlé | None | Host-selected operation permissions |
| `token_only` | Token only / Jeton seul | Required | All registered operations and public job controls |
| `protected_access` | Protected / Protégé | Required | Credential permissions and host policy |

All four profiles retain argument/output validation, task ownership, resource
budgets, cancellation and the Tool's own business rules. Free uses
`LocalAccessProfile::free`, `LocalHttpServer::UnauthenticatedLoopback` and
`Policy::allow_all()` in CyMCPSDK. Its permission scope is this HTTP host; it does
not modify stored credentials or the permissions of existing CLI/embedded clients.

## Enable the real local service

```powershell
cytool-test --data-dir ./service-data serve --port 8766
```

Connect an MCP client using only `http://127.0.0.1:8766/mcp`. The portable CyTools
JSON endpoint remains `http://127.0.0.1:8766/v1`. Both run in the same native server
and share the same Tool runtime. The address includes the endpoint path.
No account, token or additional transport approval is needed in Free.

```python
from cytools_core.transports.http import HTTPClient
client = HTTPClient('http://127.0.0.1:8766/v1')
print(client.call('DescribeTool'))
```

The native CLI also accepts the URL alone:

```powershell
cytools-native --connect http://127.0.0.1:8766/v1 describe
cytools-native --connect http://127.0.0.1:8766/v1 invoke generate_file --params-file params.json --export-dir C:/Exports/task
```

A native MCP client can use `cymcp::McpClient(url)` with no credential. Existing
stdio MCP and `--connect URL mcp` bridges continue to work. `CYTOOLS_TOKEN` remains
available for token-only/protected services; an empty token omits Authorization.

## Choose or preserve a profile

The host stores `communication.json` inside the selected runtime data directory:

```json
{"schemaVersion": 1, "accessProfile": "protected_access"}
```

A missing/empty/unset `accessProfile` migrates to `free`, preserving other settings.
An explicit supported choice is preserved. Unknown profiles, invalid JSON and
unsupported settings versions fail instead of silently opening the service.
The configuration schema is `cytools_core/schemas/local-access.schema.json`.

CLI selection is explicit and persistent:

```powershell
cytool-test --data-dir ./service-data serve --port 8766 --access-profile protected_access
```

An embedding host may call `make_server(runtime, access_profile='protected_access')`.
For local controlled access, `local_permissions=[...]` supplies its allowed manifest
permissions. Profile changes require restarting the communication host; its
`server.access` metadata reports the active native settings and `server.mcp_url`
the MCP endpoint. The diagnostic operation reports `configuredLocalAccess` separately.

In Protected, provision identities with `create-client --permission NAME` and pass
the issued credential through the private environment/vault. Only Token only
expands a verified credential's operation scope, and only within that server;
the persisted credential and other hosts remain unchanged.

## Identity and task lifetime

The server always binds **127.0.0.1**, retaining Host/Origin checks and request
bounds. Free and Local controlled share one transport-issued local principal per
running HTTP host. They do not provide per-caller token identity isolation.
Protected and Token only derive the principal from the verified credential.
Business `clientId`, `principal` or `owner` fields never choose that identity.

MCP HTTP calls span multiple POSTs. Stateless calls use a stable scope for the
transport principal; legacy MCP sessions keep their transport-issued session scope. Export wanted files before `cy_finish_task`; finish explicitly
on stateless HTTP clients. Stopping the host cleans its owned MCP tasks after
requests/workers stop. A disconnected stateless HTTP client is not an immediate
cleanup signal; temporary-session expiry remains available. Stdio bridge disconnect
cleanup and the existing reservation lifetime rules are unchanged.

## Local verification

Run `.venv/Scripts/python -m pytest -q`. Coverage includes the real reference Tool's
read/write handler over tokenless HTTP and MCP HTTP, all four profiles, argument
validation, protected isolation, persisted profile migration, native URL-only CLI,
exports and task cleanup. AIChat's existing chat tests and a Free HTTP chat turn were
also exercised locally with fixture providers, without external inference.
Windows x64 is verified here; other native platforms require their own validation.
