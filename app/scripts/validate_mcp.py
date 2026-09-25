"""Real MCP stdio round trip: discover tools, refuse an invalid call, run real jobs, poll them.

    runtime\\python\\Scripts\\python.exe app\\scripts\\validate_mcp.py [--gpu]

Without --gpu: list_effects, process_audio with the tail workflow, generate_sfx (procedural)
and voice_piper. With --gpu: also voice_qwen3tts (0.6B) and generate_music (20 s, no planner).
Writes data/reports/mcp-validation.json. Uses its own data directory (data/test-runs/mcp).
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
DATA_DIR = ROOT / 'data' / 'test-runs' / 'mcp'
TERMINAL = ('Completed', 'Failed', 'Cancelled')


async def poll(session, job, timeout):
    deadline = time.monotonic() + timeout
    while job['state'] not in TERMINAL:
        if time.monotonic() > deadline:
            raise SystemExit('MCP job did not reach a terminal state in time')
        await asyncio.sleep(0.4)
        response = await session.call_tool('cy_get_job', {'jobId': job['jobId']})
        assert not response.isError, response
        job = json.loads(response.content[0].text)
    return job


async def run(session, tool, payload, timeout=900):
    started = await session.call_tool(tool, payload)
    assert not started.isError, started.content[0].text[:2000]
    job = await poll(session, json.loads(started.content[0].text), timeout)
    assert job['state'] == 'Completed', (tool, job.get('error'))
    return job


async def main(gpu):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    sample = ROOT / 'data' / 'reports' / 'smoke-piper.wav'
    parameters = StdioServerParameters(command=sys.executable, args=[str(APP / 'tool.py'), '--data-dir', str(DATA_DIR), 'mcp'],
                                       env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    evidence = {'transport': 'MCP stdio', 'python': sys.version.split()[0], 'jobs': {}}
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listing = await session.list_tools()
            names = {tool.name for tool in listing.tools}
            expected = {'op_process_audio', 'op_generate_sfx', 'op_generate_music', 'op_voice_piper', 'op_voice_qwen3tts', 'op_voice_fishspeech',
                        'op_generate_voice', 'op_list_models', 'op_install_model', 'op_scan_plugins', 'cy_get_job', 'cy_cancel_job'}
            missing = expected - names
            assert not missing, sorted(missing)
            evidence['tools'] = sorted(names)
            refused = await session.call_tool('op_generate_sfx', {'parameters': {'prompt': 'x', 'variations': 99}, 'backendId': 'sfx_procedural'})
            assert refused.isError, refused
            raw = refused.content[0].text
            try:
                evidence['invalidParameterRejection'] = json.loads(raw)
            except ValueError:
                evidence['invalidParameterRejection'] = raw[:500]

            job = await run(session, 'op_list_effects', {'parameters': {}})
            evidence['jobs']['list_effects'] = {'count': job['outputs']['count']}
            if sample.is_file():
                job = await run(session, 'op_process_audio', {'parameters': {'input': str(sample), 'workflow_name': 'test-chain', 'output_format': 'flac'}})
                out = job['outputs']
                assert Path(out['file']).is_file()
                evidence['jobs']['process_audio'] = {'file': out['file'], 'durationSeconds': out['durationSeconds'], 'tailSeconds': out['report'].get('tailSeconds'), 'progress': job['progress']}
            job = await run(session, 'op_generate_sfx', {'parameters': {'prompt': 'coin pickup chime', 'variations': 2}, 'backendId': 'sfx_procedural'})
            evidence['jobs']['generate_sfx_procedural'] = {'files': [v['file'] for v in job['outputs']['variations']], 'layers': [l['archetype'] for l in job['outputs']['recipe']['layers']]}
            job = await run(session, 'op_voice_piper', {'parameters': {'text': 'Validation MCP de la voix Piper.'}})
            evidence['jobs']['voice_piper'] = {'file': job['outputs']['file'], 'durationSeconds': job['outputs']['durationSeconds']}
            if gpu:
                job = await run(session, 'op_voice_qwen3tts', {'parameters': {'text': 'Validation MCP de Qwen.', 'model': '0.6B-CustomVoice', 'delivery': 'complete'}}, timeout=1200)
                evidence['jobs']['voice_qwen3tts'] = {'file': job['outputs']['file'], 'durationSeconds': job['outputs']['durationSeconds'], 'generationSeconds': job['outputs']['generationSeconds']}
                job = await run(session, 'op_generate_music', {'parameters': {'caption': 'sparse lo-fi hip hop beat, dusty vinyl crackle', 'instrumental': True, 'duration_seconds': 20,
                                                                             'plan_with_lm': False, 'seed': 8080, 'output_format': 'flac'}}, timeout=1800)
                track = job['outputs']['tracks'][0]
                assert Path(track['file']).is_file()
                evidence['jobs']['generate_music'] = {'file': track['file'], 'durationSeconds': track['durationSeconds'], 'timings': job['outputs']['timings'], 'vramPeakBytes': job['outputs'].get('vramPeakBytes')}
                job = await run(session, 'op_release_workers', {'parameters': {}})
                evidence['jobs']['release_workers'] = job['outputs']
    target = ROOT / 'data' / 'reports' / 'mcp-validation.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), 'utf-8')
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    print('RESULT: PASS')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main('--gpu' in sys.argv))
