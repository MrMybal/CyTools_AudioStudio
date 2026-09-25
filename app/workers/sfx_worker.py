"""Procedural SFX worker (base environment, no model). Persistent so batches stay fast."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, inside  # noqa: E402

import numpy as np  # noqa: E402


class _Cancel:
    def __init__(self):
        self.flag = False

    def check(self):
        if self.flag:
            raise WorkerError('Cancelled', 'Cancelled')


def generate(request, reporter):
    from audiostudio.backends import sfx_procedural
    from audiostudio import audio_io
    workspace = request.get('workspace')
    outputs = request['output_files']
    variations = len(outputs)
    results = sfx_procedural.generate(request['prompt'], seed=int(request.get('seed', 0)), sample_rate=int(request.get('sample_rate', 44100)),
                                      duration_seconds=request.get('duration_seconds'), peak_dbfs=float(request.get('peak_dbfs', -1.0)),
                                      variations=variations, cancellation=_Cancel(),
                                      progress=lambda fraction, message='': reporter.progress(fraction * 90.0, step='Synthesising', message=message))
    produced = []
    subtype = 'PCM_24' if int(request.get('bit_depth', 16)) == 24 else 'PCM_16'
    for item, target in zip(results, outputs):
        path = inside(workspace, target) if workspace else Path(target)
        audio = item['audio']
        audio_io.save(path, audio, item['recipe']['sample_rate'], fmt='wav', subtype=subtype)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) if audio.size else 0.0
        produced.append({'file': str(path), 'seed': item['seed'], 'durationSeconds': round(audio.shape[1] / item['recipe']['sample_rate'], 4),
                         'peakDbfs': round(20 * np.log10(max(peak, 1e-10)), 3), 'rmsDbfs': round(20 * np.log10(max(rms, 1e-10)), 3),
                         'sizeBytes': path.stat().st_size, 'recipe': item['recipe']})
    reporter.progress(100, step='Done')
    return {'variations': produced, 'engine': 'procedural-dsp', 'recipe': produced[0]['recipe'] if produced else None,
            'warnings': list(produced[0]['recipe'].get('warnings', [])) if produced else []}


def preview(request, reporter):
    from audiostudio.backends import sfx_procedural
    recipe = sfx_procedural.build_recipe(request['prompt'], int(request.get('seed', 0)), int(request.get('sample_rate', 44100)),
                                         request.get('duration_seconds'), float(request.get('peak_dbfs', -1.0)))
    return recipe


def catalogue(request, reporter):
    from audiostudio.backends import sfx_procedural
    return {'types': sfx_procedural.catalogue(request.get('language', 'all'), request.get('query', ''))}


HANDLERS = {'generate': generate, 'preview': preview, 'catalogue': catalogue, 'status': lambda r, rep: {'engine': 'procedural-dsp'}}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
