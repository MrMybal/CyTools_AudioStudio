"""Generate tab: sound effects, music and voices (including voice cloning), results sent to the editor."""
from pathlib import Path
import time

from imgui_bundle import imgui

from audiostudio.paths import DATA, INPUTS
from audiostudio import audio_io
from .widgets import status_line, multiline, field, thumbnail
from . import cyui
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

    def _prop(self, label, help=None):
        cyui.property(self.tr(label), self.tr(help) if help else None)

    @staticmethod
    def _begin(id):
        return cyui.begin_properties(id, 190)

    def _post_combo(self, state, key='post'):
        """Post workflow row (inside a property table)."""
        names = self.workflow_names()
        index = names.index(state[key]) if state[key] in names else 0
        self._prop('Post workflow', 'Saved workflow applied to the generated audio, with tail rendering.')
        changed, index = imgui.combo('###post', index, [self.tr('(none)')] + names[1:])
        if changed:
            state[key] = names[index]

    def _actions(self):
        """A little room before the action row of a form."""
        cyui.space(6.0)

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
        cyui.panel_header(tr('Generate'), tr('Sound effects, music and voices; results can go straight to the editor.'))
        cyui.space(4.0)
        if imgui.begin_tab_bar('##generate'):
            for name, draw in (('Sound effects', self._sfx), ('Music', self._music), ('Voices', self._voices)):
                flags = imgui.TabItemFlags_.set_selected if forced == name else 0
                if imgui.begin_tab_item(tr(name) + '###' + name, flags=flags)[0]:
                    draw()
                    imgui.end_tab_item()
            imgui.end_tab_bar()
        self.app.test_subtab = None
        cyui.divider()
        _, self.app.auto_import = cyui.toggle_switch(tr('Add results to the editor automatically') + '###autoimport', self.app.auto_import)
        self._jobs_row()
        cyui.space(4.0)
        cyui.heading(tr('Results'), 3)
        if not self.results:
            cyui.text_faint(tr('Generated files appear here: listen to them, add them to the editor or use them as a voice reference.'))
        for index, (label, file) in enumerate(self.results[:8]):
            imgui.push_id(index)
            cyui.begin_card('##result', None)
            duration = thumbnail(file, 240, 34)
            imgui.same_line()
            imgui.begin_group()
            cyui.badge(tr(label).upper(), cyui.ACCENT)
            imgui.same_line(0, 6)
            imgui.align_text_to_frame_padding()
            imgui.text(Path(file).name + (f'  ({duration:.2f} s)' if duration else ''))
            if cyui.icon_text_button(cyui.icon.play, tr('Play') + '###play', cyui.GHOST):
                self.app.preview_file(file)
            imgui.same_line(0, 2)
            if cyui.icon_text_button(cyui.icon.add, tr('Add to editor') + '###add', cyui.GHOST):
                self.app.editor.import_files([file])
            imgui.same_line(0, 2)
            if cyui.icon_text_button(cyui.icon.microphone, tr('Use as voice reference') + '###ref', cyui.GHOST):
                self.voice['reference'] = str(file)
            imgui.same_line(0, 2)
            if cyui.icon_text_button(cyui.icon.folder, tr('Folder') + '###folder', cyui.GHOST):
                self.app.open_folder(Path(file).parent)
            imgui.end_group()
            cyui.end_card()
            imgui.pop_id()
        imgui.end_child()

    def _jobs_row(self):
        tr = self.tr
        jobs = self.app.jobs
        for job in jobs.running():
            progress = job.get('progress') or {}
            percent = float(progress.get('percent', 0)) / 100.0
            cyui.progress_bar(percent if percent > 0 else -1.0, (cyui.dp(360.0), 0), jobs.progress_text(job)[:80])
            imgui.same_line()
            if cyui.icon_button(cyui.icon.close, tr('Cancel this job'), id='cancel' + job['jobId'], fallback='x'):
                jobs.cancel(job['jobId'])

    # ------------------------------------------------------------------ sound effects
    def _sfx(self):
        tr = self.tr
        s = self.sfx
        _, s['prompt'] = multiline('Description', s['prompt'], 60, 'sfx-prompt', tr)
        if self._begin('##sfx-form'):
            self._prop('Engine', 'Procedural: instant, no model, follows the words of the description. AudioLDM: an AI model (GPU).')
            _, s['backend'] = imgui.combo('###sfxbackend', s['backend'], [tr('Procedural (instant, no model)'), tr('AudioLDM (AI model)')])
            self._prop('Duration (s, 0 = natural)')
            _, s['duration'] = cyui.slider_bar('###sfxdur', s['duration'], 0.0, 30.0, '%.1f s', -1)
            self._prop('Seed', 'The same seed and description give the same sound.')
            _, s['seed'] = imgui.input_int('###sfxseed', s['seed'])
            self._prop('Variations')
            _, s['variations'] = imgui.slider_int('###sfxvar', s['variations'], 1, 4)
            if s['backend'] == 1:
                self._prop('Steps')
                _, s['steps'] = imgui.slider_int('###sfxsteps', s['steps'], 5, 100)
                self._prop('Guidance')
                _, s['guidance'] = cyui.slider_bar('###sfxguid', s['guidance'], 1.0, 15.0, '%.1f', -1)
                self._prop('Device')
                _, s['device'] = imgui.combo('###sfxdev', s['device'], ['cuda', 'cpu'])
            self._post_combo(s)
            cyui.end_properties()
        self._actions()
        if cyui.primary_button(cyui.icon_label(cyui.icon.play, tr('Generate sound')) + '###Generate sound'):
            params = {'prompt': s['prompt'], 'seed': max(0, s['seed']), 'variations': s['variations'], 'post_workflow': s['post']}
            if s['duration'] > 0:
                params['duration_seconds'] = s['duration']
            if s['backend'] == 1:
                params.update({'steps': s['steps'], 'guidance_scale': s['guidance'], 'device': ['cuda', 'cpu'][s['device']]})
            self.app.jobs.submit('generate_sfx', params, self._on_result('SFX'), tr('Sound effect'), backend_id=['sfx_procedural', 'audioldm'][s['backend']])
        if s['backend'] == 0:
            imgui.same_line()
            if cyui.ghost_button(tr('Preview recipe') + '###Preview recipe'):
                try:
                    recipe = self.app.jobs.run_sync('preview_sfx_recipe', {'prompt': s['prompt'], 'seed': max(0, s['seed'])})
                    self.message = 'Recipe: ' + ' + '.join(l['archetype'] for l in recipe['layers']) + (' | ' + tr('unrecognised: ') + ', '.join(recipe['unrecognized_words']) if recipe.get('unrecognized_words') else '')
                except Exception as exc:
                    self.message = str(exc)
            cyui.tooltip(tr('Shows which sound layers the description gives, without rendering'))

    # ------------------------------------------------------------------ music
    def _music(self):
        tr = self.tr
        m = self.music
        if self._begin('##music-task'):
            self._prop('Task')
            _, m['mode'] = imgui.combo('###mtask', m['mode'], [tr('Generate a song'), tr('Remix a recording'), tr('Repaint a section'), tr('Write lyrics (LM only)')])
            cyui.end_properties()
        if m['mode'] == 3:
            _, m['idea'] = multiline('Idea', m['idea'], 50, 'm-idea', tr)
        _, m['caption'] = multiline('Caption (style)', m['caption'], 50, 'm-caption', tr)
        _, m['lyrics'] = multiline('Lyrics', m['lyrics'], 90, 'm-lyrics', tr)
        if self._begin('##music-form'):
            self._prop('Instrumental')
            _, m['instrumental'] = cyui.toggle_switch('###minstr', m['instrumental'])
            self._prop('Language')
            _, m['language'] = imgui.combo('###mlang', m['language'], LANGS_ACE)
            if m['mode'] == 0:
                self._prop('Duration (s)')
                _, m['duration'] = cyui.slider_bar('###mdur', m['duration'], 10.0, 600.0, '%.0f s', -1)
                self._prop('Plan with the language model', '+6 GiB VRAM: the language model plans the structure before the song is generated.')
                _, m['plan'] = cyui.toggle_switch('###mplan', m['plan'])
            elif m['mode'] == 1:
                self._prop('Similarity')
                _, m['similarity'] = cyui.slider_bar('###msim', m['similarity'], 0.0, 1.0, '%.2f', -1)
            elif m['mode'] == 2:
                self._prop('Start (s)')
                _, m['start'] = imgui.input_float('###mstart', m['start'])
                self._prop('End (s, -1 = end)')
                _, m['end'] = imgui.input_float('###mend', m['end'])
                self._prop('Mode')
                _, m['repaint_mode'] = imgui.combo('###mrmode', m['repaint_mode'], ['conservative', 'balanced', 'aggressive'])
                self._prop('Strength')
                _, m['repaint_strength'] = cyui.slider_bar('###mrstr', m['repaint_strength'], 0.0, 1.0, '%.2f', -1)
            if m['mode'] != 3:
                self._prop('Seed (-1 = random)')
                _, m['seed'] = imgui.input_int('###mseed', m['seed'])
                self._prop('Tracks')
                _, m['tracks'] = imgui.slider_int('###mtracks', m['tracks'], 1, 4)
                self._prop('Steps')
                _, m['steps'] = imgui.slider_int('###msteps', m['steps'], 1, 60)
                self._prop('Format')
                _, m['format'] = imgui.combo('###mfmt', m['format'], ['flac', 'wav', 'mp3'])
                self._post_combo(m)
            cyui.end_properties()
        if m['mode'] == 0:
            self._file_picker('Reference recording (optional)', m, 'reference', 'music-reference')
            if m['reference'] and self._begin('##music-reference'):
                self._prop('Reference strength')
                _, m['reference_strength'] = cyui.slider_bar('###mrefs', m['reference_strength'], 0.0, 1.0, '%.2f', -1)
                cyui.end_properties()
        elif m['mode'] in (1, 2):
            self._file_picker('Source recording', m, 'source', 'music-source')
        self._actions()
        label = 'Write lyrics' if m['mode'] == 3 else 'Generate music'
        if cyui.primary_button(cyui.icon_label(cyui.icon.note, tr(label)) + '###' + label):
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
        if cyui.icon_text_button(cyui.icon.folder, tr('Browse') + '###' + purpose, cyui.SECONDARY):
            self.app.dialogs.open_file(purpose, tr(label))
        imgui.same_line(0, 3)
        if cyui.ghost_button(tr('Use editor selection') + '###sel-' + purpose):
            path = self.app.export_selection_temp()
            if path:
                state[key] = str(path)
        cyui.tooltip(tr('Uses the selected region of the selected track in the editor'))
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
        if self._begin('##voice-engine'):
            self._prop('Voice engine')
            _, v['backend'] = imgui.combo('###vengine', v['backend'], ['Piper (CPU)', 'Qwen3-TTS', 'Fish Speech S2 Pro', tr('Saved preset')])
            cyui.end_properties()
        _, v['text'] = multiline('Text to speak', v['text'], 90, 'v-text', tr)
        backend = v['backend']
        if backend == 0:
            if self._begin('##piper-form'):
                keys = [m['voiceKey'] for m in self.piper_voices] or ['fr_FR-siwis-medium']
                index = keys.index(v['piper_voice']) if v['piper_voice'] in keys else 0
                self._prop('Voice')
                _, index = imgui.combo('###pvoice', index, keys)
                v['piper_voice'] = keys[index]
                self._prop('Length scale (speed)')
                _, v['piper_speed'] = cyui.slider_bar('###pspeed', v['piper_speed'], 0.5, 2.0, '%.2f', -1)
                self._prop('Volume')
                _, v['piper_volume'] = cyui.slider_bar('###pvol', v['piper_volume'], 0.1, 2.0, '%.2f', -1)
                self._post_combo(v)
                cyui.end_properties()
            cyui.text_wrapped_faint(tr('Piper cannot copy a voice. To clone a voice, choose Qwen3-TTS (mode Clone) or Fish Speech.'))
            cyui.text_wrapped_faint(tr('More voices: install them in the Models tab (177 languages/voices).'))
        elif backend == 1:
            if self._begin('##qwen-form'):
                self._prop('Mode')
                changed, v['qwen_mode'] = imgui.combo('###qmode', v['qwen_mode'], [tr('Preset speaker (custom)'), tr('Clone a voice from a recording'), tr('Design from a description')])
                if changed:
                    # Each mode needs its own model family: pick the matching 1.7B variant.
                    wanted = '1.7B-' + QWEN_MODE_SUFFIX[self._qwen_mode()]
                    v['qwen_model'] = QWEN_MODELS.index(wanted)
                models = [m for m in QWEN_MODELS if m.endswith(QWEN_MODE_SUFFIX[self._qwen_mode()])]
                current = QWEN_MODELS[v['qwen_model']] if QWEN_MODELS[v['qwen_model']] in models else models[0]
                self._prop('Model')
                _, index = imgui.combo('###qmodel', models.index(current), models)
                v['qwen_model'] = QWEN_MODELS.index(models[index])
                self._prop('Language')
                _, v['qwen_language'] = imgui.combo('###qlang', v['qwen_language'], QWEN_LANGUAGES)
                if self._qwen_mode() == 'custom':
                    self._prop('Speaker')
                    _, v['qwen_speaker'] = imgui.combo('###qspeaker', v['qwen_speaker'], QWEN_SPEAKERS)
                cyui.end_properties()
            if self._qwen_mode() in ('custom', 'design'):
                label = 'Voice description (design)' if self._qwen_mode() == 'design' else 'Delivery instruction (1.7B)'
                _, v['instruction'] = multiline(label, v['instruction'], 40, 'q-instruction', tr)
            if self._qwen_mode() == 'clone':
                self._reference_section(allow_embedding_only=True)
            if self._begin('##qwen-options'):
                if self._qwen_mode() == 'custom':
                    self._prop('Inline annotations', '[tone: ...] [pause: 500ms] in the text (1.7B CustomVoice).')
                    _, v['annotations'] = cyui.toggle_switch('###qann', v['annotations'])
                self._prop('Split text')
                _, v['delivery'] = imgui.combo('###qsplit', v['delivery'], ['paragraphs', 'segments', 'complete'])
                self._prop('Device')
                _, v['device'] = imgui.combo('###qdev', v['device'], ['cuda', 'cpu'])
                self._prop('Seed')
                _, v['seed'] = imgui.input_int('###qseed', v['seed'])
                self._prop('Temperature')
                _, v['temperature'] = cyui.slider_bar('###qtemp', v['temperature'], 0.1, 2.0, '%.2f', -1)
                self._post_combo(v)
                cyui.end_properties()
        elif backend == 2:
            if self._begin('##fish-form'):
                self._prop('Expression', 'whisper, excited, ...')
                _, v['fish_expression'] = imgui.input_text('###fexpr', v['fish_expression'])
                self._prop('Seed')
                _, v['seed'] = imgui.input_int('###fseed', v['seed'])
                self._post_combo(v)
                cyui.end_properties()
            cyui.text_wrapped_faint(tr('Optional: give a reference to copy a voice; without it the model picks a voice.'))
            self._reference_section(allow_embedding_only=False)
            cyui.text_wrapped_faint(tr('Multi-speaker dialogues: use the Advanced operations tab (turns[]) or MCP.'))
        else:
            if self._begin('##preset-form'):
                labels = [f"{p['name']} [{p['backend']}]" + (f" - {p['references']} ref." if p.get('references') else '') for p in self.presets] or [tr('(no preset saved)')]
                self._prop('Preset')
                _, v['preset_index'] = imgui.combo('###vpreset', min(v['preset_index'], len(labels) - 1), labels)
                self._post_combo(v)
                cyui.end_properties()
            if cyui.icon_button(cyui.icon.refresh, tr('Refresh the list of presets'), id='Refresh', fallback='R'):
                self.refresh_catalogues()
            if self.presets:
                imgui.same_line(0, 3)
                if cyui.danger_button(tr('Delete preset') + '###Delete preset'):
                    preset = self.presets[min(v['preset_index'], len(self.presets) - 1)]
                    try:
                        self.app.jobs.run_sync('delete_voice_preset', {'preset': preset['id']})
                        self.message = tr('Preset deleted: ') + preset['name']
                    except Exception as exc:
                        self.message = str(exc)
                    self.refresh_catalogues()
        self._actions()
        if cyui.primary_button(cyui.icon_label(cyui.icon.microphone, tr('Generate voice')) + '###Generate voice'):
            self._submit_voice()
        if backend != 3:
            imgui.same_line(0, 12)
            imgui.push_item_width(cyui.dp(170.0))
            _, v['preset_name'] = imgui.input_text_with_hint('###vpresetname', tr('Preset name'), v['preset_name'])
            imgui.pop_item_width()
            imgui.same_line(0, 3)
            if cyui.icon_text_button(cyui.icon.save, tr('Save as preset') + '###Save as preset'):
                self._save_preset()
            cyui.tooltip(tr('Keeps the engine, model, every setting and a copy of the reference recording, to regenerate the same voice later.'))

    def _reference_section(self, allow_embedding_only):
        """Reference voice: file, editor selection or microphone; transcription (typed or Whisper)."""
        tr = self.tr
        v = self.voice
        cyui.space(4.0)
        cyui.heading(tr('Voice to copy'), 3)
        cyui.text_wrapped_dim(tr('Give 3 to 30 seconds of clean speech from the voice to copy (no music, one speaker).'))
        if cyui.icon_text_button(cyui.icon.folder, tr('Choose a file') + '###Choose a file'):
            self.app.dialogs.open_file('voice-reference', tr('Recording of the voice to copy'), str(INPUTS))
        imgui.same_line(0, 3)
        if cyui.ghost_button(tr('Use editor selection') + '###Use editor selection'):
            path = self.app.export_selection_temp()
            if path:
                v['reference'] = str(path)
        imgui.same_line(0, 3)
        if not self.mic.active:
            if cyui.icon_text_button(cyui.icon.microphone, tr('Record from microphone') + '###Record from microphone'):
                self.mic.device = self.app.player.input_device
                self.mic.samplerate = 48000
                self.mic.start()
        else:
            if cyui.icon_text_button(cyui.icon.stop, tr('Stop recording') + '###Stop recording', cyui.DANGER):
                path = self.mic.stop()
                if path:
                    v['reference'] = str(path)
                    self.message = tr('Recording saved: ') + str(path)
            imgui.same_line()
            cyui.progress_bar(min(1.0, self.mic.level), (cyui.dp(120.0), 0), f'{self.mic.seconds():.1f} s', cyui.ERROR)
        if self.mic.error:
            status_line(self.mic.error, error=True)
        event = self.app.dialogs.poll() if self.app.dialogs.purpose == 'voice-reference' else None
        if event:
            v['reference'] = event[1][0] if isinstance(event[1], list) else event[1]
        if v['reference']:
            path = Path(v['reference'])
            if path.is_file():
                duration = thumbnail(path, 320, 36, cyui.palette().success)
                imgui.same_line()
                imgui.begin_group()
                imgui.text(path.name + (f'  ({duration:.1f} s)' if duration else ''))
                if cyui.icon_text_button(cyui.icon.play, tr('Listen') + '###Listen', cyui.GHOST):
                    self.app.preview_file(path)
                imgui.same_line(0, 2)
                if cyui.icon_text_button(cyui.icon.close, tr('Remove') + '###Remove', cyui.GHOST):
                    v['reference'] = ''
                imgui.end_group()
                if duration and duration > REFERENCE_MAX_SECONDS:
                    status_line(tr('The reference is longer than 30 s: select a shorter part in the editor and use "Use editor selection".'), error=True)
                elif duration and duration < 2.0:
                    status_line(tr('The reference is very short; 5 to 15 s give a better copy.'), error=True)
            else:
                status_line(tr('Reference file not found: ') + str(path), error=True)
        _, v['reference_text'] = multiline('Exact transcription of the reference', v['reference_text'], 40, 'v-reftext', tr)
        imgui.push_item_width(cyui.dp(80.0))
        _, v['transcribe_language'] = imgui.combo('##whisperlang', v['transcribe_language'], [tr('auto')] + WHISPER_LANGS[1:])
        imgui.pop_item_width()
        cyui.tooltip(tr('Language spoken in the reference (auto: detected by Whisper)'))
        imgui.same_line(0, 3)
        busy = self.app.jobs.is_running('transcribe_audio')
        with cyui.scoped_disabled(busy or not v['reference']):
            if cyui.icon_text_button(cyui.icon.document, tr('Transcribe automatically (Whisper)') + '###Transcribe automatically (Whisper)'):
                self._transcribe()
        if allow_embedding_only:
            _, v['x_vector'] = cyui.toggle_switch(tr('Without transcription (voice timbre only, lower fidelity)') + '###Without transcription', v['x_vector'])

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
