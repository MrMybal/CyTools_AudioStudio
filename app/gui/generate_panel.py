"""Generate tab: sound effects, music and voices (including voice cloning), results sent to the editor."""
from pathlib import Path
import time

from imgui_bundle import imgui

from audiostudio.paths import DATA, INPUTS
from audiostudio import audio_io
from .widgets import status_line, help_marker, Row, multiline, field, thumbnail
from .recorder import MicRecorder

QWEN_MODELS = ['1.7B-CustomVoice', '0.6B-CustomVoice', '1.7B-Base', '0.6B-Base', '1.7B-VoiceDesign']
QWEN_MODES = ['custom', 'clone', 'design']
QWEN_MODE_SUFFIX = {'custom': 'CustomVoice', 'clone': 'Base', 'design': 'VoiceDesign'}
QWEN_LANGUAGES = ['French', 'English', 'Auto', 'Chinese', 'Japanese', 'Korean', 'German', 'Russian', 'Portuguese', 'Spanish', 'Italian']
QWEN_SPEAKERS = ['Ryan', 'Aiden', 'Vivian', 'Serena', 'Uncle_Fu', 'Dylan', 'Eric', 'Ono_Anna', 'Sohee']
LANGS_ACE = ['unknown', 'fr', 'en', 'es', 'de', 'it', 'pt', 'ja', 'ko', 'zh']
WHISPER_LANGS = ['', 'fr', 'en', 'es', 'de', 'it', 'pt', 'ja', 'ko', 'zh', 'ru', 'nl']
REFERENCE_MAX_SECONDS = 30.0


class GeneratePanel:
    def __init__(self, app):
        self.app = app
        self.sfx = {'prompt': 'explosion lointaine avec reverb', 'backend': 0, 'duration': 0.0, 'seed': 0, 'variations': 1, 'steps': 20, 'guidance': 2.5, 'device': 0, 'post': ''}
        self.music = {'caption': 'calm acoustic guitar instrumental, folk, warm', 'lyrics': '', 'instrumental': True, 'language': 0, 'duration': 30.0, 'plan': False,
                      'seed': -1, 'tracks': 1, 'format': 0, 'reference': '', 'reference_strength': 0.2, 'post': '', 'mode': 0, 'source': '', 'similarity': 0.6,
                      'start': 0.0, 'end': -1.0, 'repaint_mode': 1, 'repaint_strength': 0.5, 'idea': '', 'steps': 8}
        self.voice = {'backend': 1, 'text': 'Bonjour, ceci est une voix off générée par AudioStudio.', 'piper_voice': 'fr_FR-siwis-medium', 'piper_speed': 1.0, 'piper_volume': 1.0,
                      'qwen_model': 0, 'qwen_mode': 0, 'qwen_language': 0, 'qwen_speaker': 0, 'instruction': '',
                      'reference': '', 'reference_text': '', 'x_vector': False, 'transcribe_language': 0,
                      'annotations': False, 'delivery': 0, 'seed': 42, 'temperature': 0.9, 'fish_expression': 'cheerful',
                      'post': '', 'preset_name': '', 'preset_index': 0, 'device': 0}
        self.mic = MicRecorder()
        self.presets = []
        self.piper_voices = []
        self.results = []          # (label, file)
        self.message = ''
        self.refresh_catalogues()

    def tr(self, text):
        return self.app.tr(text)

    def refresh_catalogues(self):
        try:
            from audiostudio.voice import presets
            self.presets = presets.list_all()
        except Exception:
            self.presets = []
        try:
            from audiostudio import models as model_catalog
            self.piper_voices = sorted([m for m in model_catalog.by_backend('piper') if not model_catalog.missing_files(m)], key=lambda m: m['id'])
        except Exception:
            self.piper_voices = []

    def workflow_names(self):
        return [''] + [w['name'] for w in self.app.workflows.saved]

    def _post_combo(self, state, key='post'):
        names = self.workflow_names()
        index = names.index(state[key]) if state[key] in names else 0
        imgui.push_item_width(240)
        changed, index = imgui.combo(self.tr('Post workflow') + '###post', index, [self.tr('(none)')] + names[1:])
        imgui.pop_item_width()
        if changed:
            state[key] = names[index]
        help_marker(self.tr('Saved workflow applied to the generated audio, with tail rendering.'))

    def _on_result(self, label):
        def callback(job):
            if job['state'] != 'Completed':
                return
            outputs = job.get('outputs') or {}
            files = []
            for item in outputs.get('variations') or outputs.get('tracks') or []:
                files.append(item.get('processedFile') or item['file'])
            if outputs.get('file'):
                files.append(outputs.get('processedFile') or outputs['file'])
            for file in files:
                self.results.insert(0, (label, file))
                if self.app.auto_import:
                    self.app.editor.import_files([file], at_cursor=True)
            del self.results[30:]
            if outputs.get('preset'):
                self.app.last_voice_preset = outputs['preset']
            if outputs.get('lyrics'):
                self.music['lyrics'] = outputs['lyrics']
                self.music['caption'] = outputs.get('caption') or self.music['caption']
                self.message = self.tr('Lyrics written into the music form')
        return callback

    # ------------------------------------------------------------------ drawing
    def draw(self):
        tr = self.tr
        forced = getattr(self.app, 'test_subtab', None)
        imgui.begin_child('generate-scroll', (0, 0))
        if imgui.begin_tab_bar('##generate'):
            for name, draw in (('Sound effects', self._sfx), ('Music', self._music), ('Voices', self._voices)):
                flags = imgui.TabItemFlags_.set_selected if forced == name else 0
                if imgui.begin_tab_item(tr(name) + '###' + name, flags=flags)[0]:
                    draw()
                    imgui.end_tab_item()
            imgui.end_tab_bar()
        self.app.test_subtab = None
        imgui.separator()
        _, self.app.auto_import = imgui.checkbox(tr('Add results to the editor automatically') + '###autoimport', self.app.auto_import)
        self._jobs_row()
        if self.results:
            imgui.separator_text(tr('Results'))
            for index, (label, file) in enumerate(self.results[:8]):
                imgui.push_id(index)
                duration = thumbnail(file, 240, 34)
                imgui.same_line()
                imgui.begin_group()
                imgui.text(f'{label}: {Path(file).name}' + (f'  ({duration:.2f} s)' if duration else ''))
                row = Row()
                if row.button('Play', tr, small=True):
                    self.app.preview_file(file)
                if row.button('Add to editor', tr, small=True):
                    self.app.editor.import_files([file])
                if row.button('Use as voice reference', tr, small=True):
                    self.voice['reference'] = str(file)
                if row.button('Folder', tr, small=True):
                    self.app.open_folder(Path(file).parent)
                imgui.end_group()
                imgui.pop_id()
        if self.message:
            status_line(self.message)
        imgui.end_child()

    def _jobs_row(self):
        tr = self.tr
        jobs = self.app.jobs
        for job in jobs.running():
            progress = job.get('progress') or {}
            imgui.progress_bar(float(progress.get('percent', 0)) / 100.0, (320, 0), jobs.progress_text(job)[:80])
            imgui.same_line()
            if imgui.small_button(tr('Cancel') + '###cancel' + job['jobId']):
                jobs.cancel(job['jobId'])

    # ------------------------------------------------------------------ sound effects
    def _sfx(self):
        tr = self.tr
        s = self.sfx
        _, s['prompt'] = multiline('Description', s['prompt'], 60, 'sfx-prompt', tr)
        imgui.push_item_width(240)
        _, s['backend'] = imgui.combo(tr('Backend') + '###sfxbackend', s['backend'], [tr('Procedural (instant, no model)'), tr('AudioLDM (AI model)')])
        _, s['duration'] = imgui.slider_float(tr('Duration (s, 0 = natural)') + '###sfxdur', s['duration'], 0.0, 30.0, '%.1f')
        _, s['seed'] = imgui.input_int(tr('Seed') + '###sfxseed', s['seed'])
        _, s['variations'] = imgui.slider_int(tr('Variations') + '###sfxvar', s['variations'], 1, 4)
        if s['backend'] == 1:
            _, s['steps'] = imgui.slider_int(tr('Steps') + '###sfxsteps', s['steps'], 5, 100)
            _, s['guidance'] = imgui.slider_float(tr('Guidance') + '###sfxguid', s['guidance'], 1.0, 15.0, '%.1f')
            _, s['device'] = imgui.combo(tr('Device') + '###sfxdev', s['device'], ['cuda', 'cpu'])
        imgui.pop_item_width()
        self._post_combo(s)
        row = Row()
        if row.button('Generate sound', tr):
            params = {'prompt': s['prompt'], 'seed': max(0, s['seed']), 'variations': s['variations'], 'post_workflow': s['post']}
            if s['duration'] > 0:
                params['duration_seconds'] = s['duration']
            if s['backend'] == 1:
                params.update({'steps': s['steps'], 'guidance_scale': s['guidance'], 'device': ['cuda', 'cpu'][s['device']]})
            self.app.jobs.submit('generate_sfx', params, self._on_result('SFX'), tr('Sound effect'), backend_id=['sfx_procedural', 'audioldm'][s['backend']])
        if s['backend'] == 0 and row.button('Preview recipe', tr):
            try:
                recipe = self.app.jobs.run_sync('preview_sfx_recipe', {'prompt': s['prompt'], 'seed': max(0, s['seed'])})
                self.message = 'Recipe: ' + ' + '.join(l['archetype'] for l in recipe['layers']) + (' | ' + tr('unrecognised: ') + ', '.join(recipe['unrecognized_words']) if recipe.get('unrecognized_words') else '')
            except Exception as exc:
                self.message = str(exc)

    # ------------------------------------------------------------------ music
    def _music(self):
        tr = self.tr
        m = self.music
        imgui.push_item_width(240)
        _, m['mode'] = imgui.combo(tr('Task') + '###mtask', m['mode'], [tr('Generate a song'), tr('Remix a recording'), tr('Repaint a section'), tr('Write lyrics (LM only)')])
        imgui.pop_item_width()
        if m['mode'] == 3:
            _, m['idea'] = multiline('Idea', m['idea'], 50, 'm-idea', tr)
        _, m['caption'] = multiline('Caption (style)', m['caption'], 50, 'm-caption', tr)
        _, m['lyrics'] = multiline('Lyrics', m['lyrics'], 90, 'm-lyrics', tr)
        imgui.push_item_width(240)
        _, m['instrumental'] = imgui.checkbox(tr('Instrumental') + '###minstr', m['instrumental'])
        _, m['language'] = imgui.combo(tr('Language') + '###mlang', m['language'], LANGS_ACE)
        if m['mode'] == 0:
            _, m['duration'] = imgui.slider_float(tr('Duration (s)') + '###mdur', m['duration'], 10.0, 600.0, '%.0f')
            _, m['plan'] = imgui.checkbox(tr('Plan with the language model (+6 GiB VRAM)') + '###mplan', m['plan'])
            imgui.pop_item_width()
            self._file_picker('Reference recording (optional)', m, 'reference', 'music-reference')
            imgui.push_item_width(240)
            _, m['reference_strength'] = imgui.slider_float(tr('Reference strength') + '###mrefs', m['reference_strength'], 0.0, 1.0, '%.2f')
        elif m['mode'] in (1, 2):
            imgui.pop_item_width()
            self._file_picker('Source recording', m, 'source', 'music-source')
            imgui.push_item_width(240)
            if m['mode'] == 1:
                _, m['similarity'] = imgui.slider_float(tr('Similarity') + '###msim', m['similarity'], 0.0, 1.0, '%.2f')
            else:
                _, m['start'] = imgui.input_float(tr('Start (s)') + '###mstart', m['start'])
                _, m['end'] = imgui.input_float(tr('End (s, -1 = end)') + '###mend', m['end'])
                _, m['repaint_mode'] = imgui.combo(tr('Mode') + '###mrmode', m['repaint_mode'], ['conservative', 'balanced', 'aggressive'])
                _, m['repaint_strength'] = imgui.slider_float(tr('Strength') + '###mrstr', m['repaint_strength'], 0.0, 1.0, '%.2f')
        if m['mode'] != 3:
            _, m['seed'] = imgui.input_int(tr('Seed (-1 = random)') + '###mseed', m['seed'])
            _, m['tracks'] = imgui.slider_int(tr('Tracks') + '###mtracks', m['tracks'], 1, 4)
            _, m['steps'] = imgui.slider_int(tr('Steps') + '###msteps', m['steps'], 1, 60)
            _, m['format'] = imgui.combo(tr('Format') + '###mfmt', m['format'], ['flac', 'wav', 'mp3'])
        imgui.pop_item_width()
        if m['mode'] != 3:
            self._post_combo(m)
        row = Row()
        if row.button('Write lyrics' if m['mode'] == 3 else 'Generate music', tr):
            common = {'caption': m['caption'], 'lyrics': m['lyrics'], 'instrumental': m['instrumental'], 'language': LANGS_ACE[m['language']]}
            if m['mode'] == 3:
                self.app.jobs.submit('write_lyrics', {'mode': 'create' if m['idea'].strip() else 'format', 'idea': m['idea'], **common}, self._on_result('Lyrics'), tr('Lyrics'))
            else:
                common.update({'seed': None if m['seed'] < 0 else m['seed'], 'track_count': m['tracks'], 'steps': m['steps'], 'output_format': ['flac', 'wav', 'mp3'][m['format']], 'post_workflow': m['post']})
                if m['mode'] == 0:
                    params = {**common, 'duration_seconds': m['duration'], 'plan_with_lm': m['plan'], 'reference_audio': m['reference'], 'reference_strength': m['reference_strength']}
                    self.app.jobs.submit('generate_music', params, self._on_result('Music'), tr('Music'))
                elif m['mode'] == 1:
                    self.app.jobs.submit('remix_music', {**common, 'source_audio': m['source'], 'similarity': m['similarity']}, self._on_result('Remix'), tr('Remix'))
                else:
                    self.app.jobs.submit('repaint_music', {**common, 'source_audio': m['source'], 'start_seconds': m['start'], 'end_seconds': m['end'],
                                                           'repaint_mode': ['conservative', 'balanced', 'aggressive'][m['repaint_mode']], 'repaint_strength': m['repaint_strength']},
                                         self._on_result('Repaint'), tr('Repaint'))

    def _file_picker(self, label, state, key, purpose):
        """Path field with Browse and 'editor selection' buttons, plus a thumbnail when set."""
        tr = self.tr
        _, state[key] = field(label, state[key], purpose, tr)
        row = Row()
        if row.button('Browse###' + purpose, tr):
            self.app.dialogs.open_file(purpose, tr(label))
        if row.button('Use editor selection###sel-' + purpose, tr):
            path = self.app.export_selection_temp()
            if path:
                state[key] = str(path)
        if state[key] and Path(state[key]).is_file():
            thumbnail(state[key], 300, 30)
        event = self.app.dialogs.poll() if self.app.dialogs.purpose == purpose else None
        if event:
            state[key] = event[1][0] if isinstance(event[1], list) else event[1]

    # ------------------------------------------------------------------ voices
    def _qwen_mode(self):
        return QWEN_MODES[self.voice['qwen_mode']]

    def _voices(self):
        tr = self.tr
        v = self.voice
        imgui.push_item_width(240)
        _, v['backend'] = imgui.combo(tr('Voice engine') + '###vengine', v['backend'], ['Piper (CPU)', 'Qwen3-TTS', 'Fish Speech S2 Pro', tr('Saved preset')])
        imgui.pop_item_width()
        _, v['text'] = multiline('Text to speak', v['text'], 90, 'v-text', tr)
        backend = v['backend']
        imgui.push_item_width(240)
        if backend == 0:
            keys = [m['voiceKey'] for m in self.piper_voices] or ['fr_FR-siwis-medium']
            index = keys.index(v['piper_voice']) if v['piper_voice'] in keys else 0
            _, index = imgui.combo(tr('Voice') + '###pvoice', index, keys)
            v['piper_voice'] = keys[index]
            _, v['piper_speed'] = imgui.slider_float(tr('Length scale (speed)') + '###pspeed', v['piper_speed'], 0.5, 2.0, '%.2f')
            _, v['piper_volume'] = imgui.slider_float(tr('Volume') + '###pvol', v['piper_volume'], 0.1, 2.0, '%.2f')
            imgui.pop_item_width()
            imgui.text_disabled(tr('Piper cannot copy a voice. To clone a voice, choose Qwen3-TTS (mode Clone) or Fish Speech.'))
            imgui.text_disabled(tr('More voices: install them in the Models tab (177 languages/voices).'))
        elif backend == 1:
            changed, v['qwen_mode'] = imgui.combo(tr('Mode') + '###qmode', v['qwen_mode'], [tr('Preset speaker (custom)'), tr('Clone a voice from a recording'), tr('Design from a description')])
            if changed:
                # Each mode needs its own model family: pick the matching 1.7B variant.
                wanted = '1.7B-' + QWEN_MODE_SUFFIX[self._qwen_mode()]
                v['qwen_model'] = QWEN_MODELS.index(wanted)
            models = [m for m in QWEN_MODELS if m.endswith(QWEN_MODE_SUFFIX[self._qwen_mode()])]
            current = QWEN_MODELS[v['qwen_model']] if QWEN_MODELS[v['qwen_model']] in models else models[0]
            _, index = imgui.combo(tr('Model') + '###qmodel', models.index(current), models)
            v['qwen_model'] = QWEN_MODELS.index(models[index])
            _, v['qwen_language'] = imgui.combo(tr('Language') + '###qlang', v['qwen_language'], QWEN_LANGUAGES)
            if self._qwen_mode() == 'custom':
                _, v['qwen_speaker'] = imgui.combo(tr('Speaker') + '###qspeaker', v['qwen_speaker'], QWEN_SPEAKERS)
            imgui.pop_item_width()
            if self._qwen_mode() in ('custom', 'design'):
                label = 'Voice description (design)' if self._qwen_mode() == 'design' else 'Delivery instruction (1.7B)'
                _, v['instruction'] = multiline(label, v['instruction'], 40, 'q-instruction', tr)
            if self._qwen_mode() == 'clone':
                self._reference_section(allow_embedding_only=True)
            imgui.push_item_width(240)
            if self._qwen_mode() == 'custom':
                _, v['annotations'] = imgui.checkbox(tr('Inline annotations [tone: ...] [pause: 500ms] (1.7B CustomVoice)') + '###qann', v['annotations'])
            _, v['delivery'] = imgui.combo(tr('Split text') + '###qsplit', v['delivery'], ['paragraphs', 'segments', 'complete'])
            _, v['device'] = imgui.combo(tr('Device') + '###qdev', v['device'], ['cuda', 'cpu'])
            _, v['seed'] = imgui.input_int(tr('Seed') + '###qseed', v['seed'])
            _, v['temperature'] = imgui.slider_float(tr('Temperature') + '###qtemp', v['temperature'], 0.1, 2.0, '%.2f')
            imgui.pop_item_width()
        elif backend == 2:
            _, v['fish_expression'] = imgui.input_text(tr('Expression (whisper, excited, ...)') + '###fexpr', v['fish_expression'])
            imgui.pop_item_width()
            imgui.text_disabled(tr('Optional: give a reference to copy a voice; without it the model picks a voice.'))
            self._reference_section(allow_embedding_only=False)
            imgui.push_item_width(240)
            _, v['seed'] = imgui.input_int(tr('Seed') + '###fseed', v['seed'])
            imgui.pop_item_width()
            imgui.text_disabled(tr('Multi-speaker dialogues: use the Advanced operations tab (turns[]) or MCP.'))
        else:
            labels = [f"{p['name']} [{p['backend']}]" + (f" - {p['references']} ref." if p.get('references') else '') for p in self.presets] or [tr('(no preset saved)')]
            _, v['preset_index'] = imgui.combo(tr('Preset') + '###vpreset', min(v['preset_index'], len(labels) - 1), labels)
            imgui.pop_item_width()
            row = Row()
            if row.button('Refresh', tr):
                self.refresh_catalogues()
            if self.presets and row.button('Delete preset', tr):
                preset = self.presets[min(v['preset_index'], len(self.presets) - 1)]
                try:
                    self.app.jobs.run_sync('delete_voice_preset', {'preset': preset['id']})
                    self.message = tr('Preset deleted: ') + preset['name']
                except Exception as exc:
                    self.message = str(exc)
                self.refresh_catalogues()
        self._post_combo(v)
        row = Row()
        if row.button('Generate voice', tr):
            self._submit_voice()
        if backend != 3:
            row.next(220)
            imgui.push_item_width(160)
            _, v['preset_name'] = imgui.input_text(tr('Preset name') + '###vpresetname', v['preset_name'])
            imgui.pop_item_width()
            if row.button('Save as preset', tr):
                self._save_preset()
            if imgui.is_item_hovered():
                imgui.set_tooltip(tr('Keeps the engine, model, every setting and a copy of the reference recording, to regenerate the same voice later.'))

    def _reference_section(self, allow_embedding_only):
        """Reference voice: file, editor selection or microphone; transcription (typed or Whisper)."""
        tr = self.tr
        v = self.voice
        imgui.separator_text(tr('Voice to copy'))
        imgui.text_wrapped(tr('Give 3 to 30 seconds of clean speech from the voice to copy (no music, one speaker).'))
        row = Row()
        if row.button('Choose a file', tr):
            self.app.dialogs.open_file('voice-reference', tr('Recording of the voice to copy'), str(INPUTS))
        if row.button('Use editor selection', tr):
            path = self.app.export_selection_temp()
            if path:
                v['reference'] = str(path)
        if not self.mic.active:
            if row.button('Record from microphone', tr):
                self.mic.device = self.app.player.input_device
                self.mic.samplerate = 48000
                self.mic.start()
        else:
            if row.button('Stop recording', tr):
                path = self.mic.stop()
                if path:
                    v['reference'] = str(path)
                    self.message = tr('Recording saved: ') + str(path)
            row.next(160)
            imgui.progress_bar(min(1.0, self.mic.level), (100, 0), f'{self.mic.seconds():.1f} s')
        if self.mic.error:
            status_line(self.mic.error, error=True)
        event = self.app.dialogs.poll() if self.app.dialogs.purpose == 'voice-reference' else None
        if event:
            v['reference'] = event[1][0] if isinstance(event[1], list) else event[1]
        if v['reference']:
            path = Path(v['reference'])
            if path.is_file():
                duration = thumbnail(path, 320, 36, (0.55, 0.85, 0.5))
                imgui.same_line()
                imgui.begin_group()
                imgui.text(path.name + (f'  ({duration:.1f} s)' if duration else ''))
                row = Row()
                if row.button('Listen', tr, small=True):
                    self.app.preview_file(path)
                if row.button('Remove', tr, small=True):
                    v['reference'] = ''
                imgui.end_group()
                if duration and duration > REFERENCE_MAX_SECONDS:
                    status_line(tr('The reference is longer than 30 s: select a shorter part in the editor and use "Use editor selection".'), error=True)
                elif duration and duration < 2.0:
                    status_line(tr('The reference is very short; 5 to 15 s give a better copy.'), error=True)
            else:
                status_line(tr('Reference file not found: ') + str(path), error=True)
        _, v['reference_text'] = multiline('Exact transcription of the reference', v['reference_text'], 40, 'v-reftext', tr)
        row = Row()
        imgui.push_item_width(80)
        _, v['transcribe_language'] = row.combo('whisperlang', v['transcribe_language'], [tr('auto')] + WHISPER_LANGS[1:], 80)
        imgui.pop_item_width()
        busy = self.app.jobs.is_running('transcribe_audio')
        imgui.begin_disabled(busy or not v['reference'])
        if row.button('Transcribe automatically (Whisper)', tr):
            self._transcribe()
        imgui.end_disabled()
        if allow_embedding_only:
            _, v['x_vector'] = row.checkbox('Without transcription (voice timbre only, lower fidelity)', v['x_vector'], tr)

    def _transcribe(self):
        v = self.voice

        def done(job):
            if job['state'] == 'Completed':
                v['reference_text'] = job['outputs']['text']
                self.message = self.tr('Transcription done; check it before generating.')
            elif job['state'] == 'Failed' and (job.get('error') or {}).get('code') == 'MissingModel':
                self.message = self.tr('Install Whisper in the Models tab (whisper-large-v3-turbo, 1.6 GB) to transcribe automatically.')
        self.app.jobs.submit('transcribe_audio', {'input': v['reference'], 'language': WHISPER_LANGS[v['transcribe_language']], 'device': ['cuda', 'cpu'][v['device']]},
                             done, self.tr('Transcription'))

    def _voice_parameters(self):
        v = self.voice
        backend = v['backend']
        if backend == 0:
            return 'voice_piper', 'piper', {'text': v['text'], 'voice': v['piper_voice'], 'length_scale': v['piper_speed'], 'volume': v['piper_volume'], 'post_workflow': v['post']}
        if backend == 1:
            mode = self._qwen_mode()
            params = {'text': v['text'], 'model': QWEN_MODELS[v['qwen_model']], 'mode': mode, 'language': QWEN_LANGUAGES[v['qwen_language']],
                      'device': ['cuda', 'cpu'][v['device']], 'delivery': ['paragraphs', 'segments', 'complete'][v['delivery']], 'seed': max(0, v['seed']),
                      'temperature': v['temperature'], 'post_workflow': v['post']}
            if mode == 'custom':
                params.update({'speaker': QWEN_SPEAKERS[v['qwen_speaker']], 'instruction': v['instruction'], 'text_annotations': v['annotations']})
            elif mode == 'design':
                params['instruction'] = v['instruction']
            else:
                params.update({'reference_audio': v['reference'], 'reference_text': '' if v['x_vector'] else v['reference_text'], 'x_vector_only': v['x_vector']})
            return 'voice_qwen3tts', 'qwen3tts', params
        if backend == 2:
            references = [{'audio': v['reference'], 'text': v['reference_text']}] if v['reference'] else []
            return 'voice_fishspeech', 'fishspeech', {'turns': [{'speaker': 0, 'text': v['text'], 'expression': v['fish_expression']}], 'references': references,
                                                      'seed': max(0, v['seed']), 'post_workflow': v['post']}
        return None, None, None

    def _check_reference(self, operation, params):
        """Clear message before submitting instead of an engine error later."""
        tr = self.tr
        if operation == 'voice_qwen3tts' and params.get('mode') == 'clone':
            if not params.get('reference_audio'):
                return tr('Choose, select or record the voice to copy first.')
            if not params.get('x_vector_only') and not params.get('reference_text', '').strip():
                return tr('Type or transcribe what is said in the reference, or tick "Without transcription".')
        if operation == 'voice_fishspeech' and params.get('references'):
            if not params['references'][0].get('text', '').strip():
                return tr('Fish Speech needs the exact transcription of the reference (type it or use Whisper).')
        return ''

    def _submit_voice(self):
        tr = self.tr
        v = self.voice
        if v['backend'] == 3:
            if not self.presets:
                self.message = tr('No preset saved yet')
                return
            preset = self.presets[min(v['preset_index'], len(self.presets) - 1)]
            self.app.jobs.submit('generate_voice', {'preset': preset['id'], 'text': v['text']}, self._on_result('Voice'), tr('Voice'))
            return
        operation, backend, params = self._voice_parameters()
        problem = self._check_reference(operation, params)
        if problem:
            self.message = problem
            return
        if v['preset_name'].strip():
            params['preset_name'] = v['preset_name'].strip()
        self.app.jobs.submit(operation, params, self._on_result('Voice'), tr('Voice'))

    def _save_preset(self):
        tr = self.tr
        v = self.voice
        operation, backend, params = self._voice_parameters()
        if backend is None:
            return
        problem = self._check_reference(operation, params)
        if problem:
            self.message = problem
            return
        name = v['preset_name'].strip() or (backend + ' voice')
        stored = {k: val for k, val in params.items() if k not in ('text', 'turns', 'post_workflow')}
        if backend == 'fishspeech':
            stored['expression'] = v['fish_expression']
        try:
            result = self.app.jobs.run_sync('save_voice_preset', {'name': name, 'backend': backend, 'parameters': stored, 'post_workflow': v['post']})
            self.message = tr('Preset saved: ') + result['id']
            self.refresh_catalogues()
        except Exception as exc:
            self.message = tr('Preset save failed: ') + str(exc)
