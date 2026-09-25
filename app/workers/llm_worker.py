"""Text LLM worker (engine 'torch'): chat completion for TTS annotation help. Model stays resident.

chat {"model_path": "<dir>", "system": "...", "user": "...", "max_new_tokens": 512, "temperature": 0.0, "device": "cuda|cpu"}
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workers._protocol import serve, WorkerError, memory_report  # noqa: E402

_state = {}


def _load(model_path, device, reporter):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    key = (str(model_path), device)
    if _state.get('key') == key:
        return _state['model'], _state['tokenizer']
    unload({}, reporter)
    if device == 'cuda' and not torch.cuda.is_available():
        raise WorkerError('MissingDependency', 'CUDA is not available; choose the CPU device', recoverable=True)
    if not Path(model_path, 'config.json').is_file():
        raise WorkerError('MissingModel', 'LLM weights not found: ' + str(model_path), recoverable=True)
    reporter.progress(5, step='Loading language model')
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_bf16_supported() else (torch.float16 if device == 'cuda' else torch.float32)
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(str(model_path), dtype=dtype, local_files_only=True).to(device)
    model.eval()
    _state.update(key=key, model=model, tokenizer=tokenizer, device=device)
    reporter.resident(model=str(model_path), gpu=device == 'cuda')
    return model, tokenizer


def unload(request, reporter):
    _state.clear()
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    reporter.resident()
    return {'unloaded': True}


def chat(request, reporter):
    import torch
    started = time.monotonic()
    device = request.get('device', 'cuda')
    model, tokenizer = _load(request['model_path'], device, reporter)
    messages = [{'role': 'system', 'content': request.get('system', '')}, {'role': 'user', 'content': request['user']}]
    try:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors='pt').to(model.device)
    reporter.progress(30, step='Generating')
    temperature = float(request.get('temperature', 0.0))
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=int(request.get('max_new_tokens', 512)), do_sample=temperature > 0,
                                temperature=max(temperature, 1e-3) if temperature > 0 else None, pad_token_id=tokenizer.eos_token_id)
    text = tokenizer.decode(output[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
    reporter.progress(100, step='Done')
    return {'text': text, 'seconds': round(time.monotonic() - started, 3), 'promptTokens': int(inputs['input_ids'].shape[1]), **memory_report()}


def diagnose(request, reporter):
    import torch
    import transformers
    return {'torch': torch.__version__, 'transformers': transformers.__version__, 'cuda': torch.cuda.is_available(), 'resident': _state.get('key', ('',))[0]}


HANDLERS = {'chat': chat, 'unload': unload, 'diagnose': diagnose, 'status': diagnose}

if __name__ == '__main__':
    raise SystemExit(serve(HANDLERS))
