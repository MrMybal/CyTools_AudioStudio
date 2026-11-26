import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from workers._protocol import WorkerError
from workers import qwen_tts_zml

APP = Path(__file__).resolve().parents[1]
if (APP / "workers" / "qwen3tts_worker.py").is_file():
    from workers import qwen3tts_worker as worker
else:
    from workers import tts_worker as worker


class Reporter:
    def progress(self, *args, **kwargs):
        pass

    def resident(self, *args, **kwargs):
        pass


class QwenZmlTest(unittest.TestCase):
    def test_explicit_torch_and_unconfigured_auto(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(qwen_tts_zml.CONFIG_ENV, None)
            self.assertEqual(qwen_tts_zml.runtime({}), "torch")
            self.assertEqual(qwen_tts_zml.runtime({"runtime": "torch"}), "torch")
            with self.assertRaises(WorkerError):
                qwen_tts_zml.load()

    def test_zml_worker_checks_reference_and_writes_timeline(self):
        with tempfile.TemporaryDirectory(prefix="qwen-zml-worker-test-") as folder:
            workspace = Path(folder)
            output = workspace / "outputs"
            config = self.configuration(workspace)
            request = self.request(workspace, output)
            with patch.dict(os.environ, {qwen_tts_zml.CONFIG_ENV: str(config)}), \
                    patch.object(worker, "_load", side_effect=AssertionError("Torch must not load")):
                self.assertEqual(qwen_tts_zml.runtime(request), "zml")
                result = worker.synthesize(request, Reporter())
                self.assertEqual(result["runtime"], "zml")
                self.assertEqual(result["sampleRate"], 24000)
                self.assertEqual(result["segments"][0]["startSample"], 0)
                self.assertEqual(result["segments"][0]["sampleCount"], 240)
                self.assertEqual(list(workspace.glob("qwen-zml-*")), [])
                with wave.open(result["file"], "rb") as speech:
                    self.assertEqual(speech.getnframes(), 240)
                with self.assertRaises(WorkerError):
                    worker.synthesize({**request, "reference_text": ""}, Reporter())
                self.assertEqual(list(workspace.glob("qwen-zml-*")), [])
                if hasattr(worker, "synthesize_batch"):
                    items = [
                        {"id": "a", "file": "a", "text": "Bonjour.", "reference_text": "Reference.",
                         "reference_audio": request["reference_audio"], "x_vector_only": False},
                        {"id": "b", "file": "b", "text": "Merci.", "reference_text": "Reference.",
                         "reference_audio": request["reference_audio"], "x_vector_only": False},
                    ]
                    batch = worker.synthesize_batch({**request, "items": items, "batch_size": 12}, Reporter())
                    self.assertEqual(batch["runtime"], "zml")
                    self.assertEqual(batch["batchSize"], 1)
                    self.assertEqual([item["error"] for item in batch["items"]], ["", ""])
                    self.assertTrue(all(Path(item["file"]).is_file() for item in batch["items"]))

    @staticmethod
    def configuration(workspace):
        bridge = workspace / "fake_bridge.py"
        bridge.write_text('''
import wave
from pathlib import Path

def synthesize(config, request, item, output):
    fields = {**request, **item}
    if fields["reference_text"] != "Reference." or not Path(fields["reference_audio"]).is_file():
        raise ValueError("Missing ICL reference")
    assert not fields["x_vector_only"] and request["seed"] == 42
    with wave.open(str(output), "wb") as wav:
        wav.setparams((1, 2, 24000, 240, "NONE", "not compressed"))
        wav.writeframes(b"\\0\\1" * 240)
''', encoding="utf-8")
        config = workspace / "zml.json"
        config.write_text(json.dumps({"bridge": str(bridge)}), encoding="utf-8")
        return config

    @staticmethod
    def request(workspace, output):
        reference = workspace / "reference.wav"
        with wave.open(str(reference), "wb") as wav:
            wav.setparams((1, 2, 24000, 240, "NONE", "not compressed"))
            wav.writeframes(b"\0\1" * 240)
        return {"workspace": str(workspace), "model_path": str(workspace), "output_dir": str(output),
                "mode": "clone", "text": "Bonjour.", "reference_audio": str(reference), "reference_text": "Reference.",
                "x_vector_only": False, "seed": 42, "delivery": "complete", "device": "cpu"}
