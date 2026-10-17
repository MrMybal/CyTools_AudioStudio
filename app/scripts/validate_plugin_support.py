"""Check the actual MCP stdio API for native plugin support (no model loading)."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from tests.test_plugin_formats import SOURCE
from scripts.validate_mcp import run


async def main():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    report = {'transport':'MCP stdio', 'operations':{}}
    with tempfile.TemporaryDirectory(prefix='audiostudio-plugin-mcp-') as temp:
        external = Path(temp) / 'External.jsfx'
        external.write_text(SOURCE, 'utf-8')
        server = StdioServerParameters(command=sys.executable, args=[str(APP / 'tool.py'), '--data-dir', str(Path(temp) / 'jobs'), 'mcp'], env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {'op_scan_plugins','op_list_plugins','op_describe_plugin','op_read_jsfx','op_validate_jsfx','op_save_jsfx'} <= names
                read = await run(session, 'op_read_jsfx', {'parameters':{'script':str(external)}})
                assert read['outputs']['source'] == SOURCE
                checked = await run(session, 'op_validate_jsfx', {'parameters':{'source':SOURCE}})
                assert checked['outputs']['valid']
                saved = await run(session, 'op_save_jsfx', {'parameters':{'name':'MCP-Test-' + uuid.uuid4().hex,'source':SOURCE}})
                target = Path(saved['outputs']['path'])
                try:
                    info = await run(session, 'op_describe_plugin', {'parameters':{'plugin':str(target)}})
                    assert info['outputs']['format'] == 'JSFX'
                    report['operations'] = {key:'passed' for key in ('catalogue','read_jsfx','validate_jsfx','save_jsfx','describe_plugin')}
                finally:
                    target.unlink(missing_ok=True)
    destination = APP.parent / 'data/reports/plugin-mcp-validation.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report,indent=2), 'utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    asyncio.run(main())
