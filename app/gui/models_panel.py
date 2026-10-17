"""Models tab: engines and model weights — state, size, source, licence, download/resume/repair/remove."""
import time
import webbrowser

from imgui_bundle import imgui

from audiostudio import models as model_catalog
from audiostudio.engines import registry as engines
from . import cyui

def gb(value):
    return f'{(value or 0) / 1e9:.2f} GB'


class ModelsPanel:
    def __init__(self, app):
        self.app = app
        self.models = []
        self.engine_status = {}
        self.accepted = {}          # in-memory only, never persisted
        self.token = ''
        self.message = ''
        self.show_voices = False
        self.voice_filter = ''
        self.last_refresh = 0.0
        self.refresh()

    def tr(self, text):
        return self.app.tr(text)

    def refresh(self):
        try:
            self.models = model_catalog.status_all(include_voices=self.show_voices)
            self.engine_status = engines.status_all()
        except Exception as exc:
            self.message = str(exc)
        self.last_refresh = time.monotonic()

    def _state_tone(self, state):
        return {'Installed': cyui.SUCCESS, 'Downloading': cyui.ACCENT, 'Verifying': cyui.ACCENT, 'Partial': cyui.WARNING, 'Interrupted': cyui.WARNING,
                'Failed': cyui.ERROR, 'AccessRequired': cyui.ERROR, 'LicenseAcceptanceRequired': cyui.WARNING, 'Cancelled': cyui.NEUTRAL}.get(state, cyui.NEUTRAL)

    def draw(self):
        tr = self.tr
        jobs = self.app.jobs
        icon = cyui.icon
        if time.monotonic() - self.last_refresh > (2.0 if jobs.is_running('install_model', 'install_engine', 'verify_model', 'remove_model') else 15.0):
            self.refresh()
        cyui.panel_header(tr('Models'), tr('Engines and model weights: state, size, source, licence; download, resume, verify, repair or remove them.'))
        cyui.space(4.0)
        if cyui.begin_section(tr('Engines') + '###engines'):
            cyui.text_wrapped_faint(tr('Engines are private Python environments under runtime/engines. They are created at their final path with the pinned versions and checked by import before use.'))
            for name, info in self.engine_status.items():
                imgui.push_id(name)
                cyui.begin_card('##engine', None, 0.0, cyui.NEUTRAL if info['installed'] else cyui.WARNING)
                cyui.badge(tr(info['state']).upper(), cyui.SUCCESS if info['installed'] else cyui.WARNING)
                imgui.same_line(0, 6)
                imgui.align_text_to_frame_padding()
                with cyui.scoped_font(cyui.bold_font()):
                    imgui.text(info['label'])
                imgui.same_line()
                cyui.text_dim((f"torch {info['torch']}, {info['device']}  ·  " if info.get('torch') else '') + f"~{gb(info.get('estimatedBytes'))}")
                for source, item in info.get('sources', {}).items():
                    cyui.status_dot(cyui.palette().success if item['ok'] else cyui.palette().error)
                    imgui.same_line(0, 4)
                    cyui.text_dim(f"{source}: {'ok' if item['ok'] else tr('missing or wrong revision')} ({item['expected'][:12]})")
                running = jobs.is_running('install_engine')
                with cyui.scoped_disabled(running):
                    if cyui.icon_text_button(icon.download, tr('Install or repair (GPU)') + '###Install or repair (GPU)', cyui.PRIMARY if not info['installed'] else cyui.SECONDARY):
                        jobs.submit('install_engine', {'engine': name, 'cpu_only': False}, lambda job: self.refresh(), tr('Engine ') + name)
                    if info.get('backends') and 'torch' == name:
                        imgui.same_line(0, 4)
                        if cyui.ghost_button(tr('Install CPU-only build') + '###Install CPU-only build'):
                            jobs.submit('install_engine', {'engine': name, 'cpu_only': True}, lambda job: self.refresh(), tr('Engine ') + name)
                cyui.end_card()
                imgui.pop_id()
            for job in jobs.running('install_engine'):
                cyui.progress_bar(-1.0, (cyui.dp(400.0), 0), jobs.progress_text(job)[:90])
                imgui.same_line()
                if cyui.icon_button(icon.close, tr('Cancel'), id='eng-cancel', fallback='x'):
                    jobs.cancel(job['jobId'])
            cyui.end_section()
        if cyui.begin_section(tr('Hugging Face access') + '###hf', False):
            cyui.text_wrapped_faint(tr('All catalogue models are public. A token is only needed for gated models you add later; it is stored in the Windows credential store, never in files or logs.'))
            imgui.push_item_width(cyui.dp(300.0))
            _, self.token = imgui.input_text_with_hint('##token', tr('Token'), self.token, imgui.InputTextFlags_.password)
            imgui.pop_item_width()
            imgui.same_line(0, 4)
            with cyui.scoped_disabled(not self.token):
                if cyui.button(tr('Store token') + '###Store token'):
                    try:
                        model_catalog.store_token(self.token)
                        self.token = ''
                        self.message = tr('Token stored in the credential store')
                    except Exception as exc:
                        self.message = str(exc)
            imgui.same_line(0, 4)
            if cyui.ghost_button(tr('Forget token') + '###Forget token'):
                model_catalog.store_token('')
                self.message = tr('Token removed')
            imgui.same_line(0, 4)
            if cyui.link_text(tr('Create a read token')):
                webbrowser.open('https://huggingface.co/settings/tokens')
            cyui.end_section()
        cyui.heading(tr('Models'), 3)
        changed, self.show_voices = cyui.toggle_switch(tr('Show all 177 Piper voices') + '###show-voices', self.show_voices)
        if changed:
            self.refresh()
        if self.show_voices:
            imgui.same_line(0, 12)
            _, self.voice_filter = cyui.search_field('##voice-filter', self.voice_filter, tr('Filter voices'), cyui.dp(220.0))
        imgui.begin_child('##models', (0, max(200.0, imgui.get_content_region_avail().y - 4)))
        for model in self.models:
            if self.show_voices and model['backend'] == 'piper' and self.voice_filter and self.voice_filter.lower() not in model['id'].lower():
                continue
            self._draw_model(model)
        imgui.end_child()

    def _draw_model(self, model):
        tr = self.tr
        jobs = self.app.jobs
        icon = cyui.icon
        p = cyui.palette()
        imgui.push_id(model['id'])
        tone = self._state_tone(model['state'])
        header = f"{model['name']}  [{model['backend']}]"
        opened = cyui.begin_section(header + '###hdr', False)
        imgui.same_line(imgui.get_content_region_avail().x - cyui.dp(140.0))
        cyui.badge(tr(model['state']).upper(), tone)
        if opened:
            if cyui.begin_properties('##model', 160):
                cyui.property(tr('Download'))
                imgui.text(f"{gb(model['downloadBytes'])}   ({tr('present')}: {gb(model['presentBytes'])}, {tr('missing files')}: {model['missing']})")
                cyui.property(tr('Folder'))
                cyui.text_faint(model['directory'])
                source = model.get('source', {})
                license_info = model.get('license', {})
                cyui.property(tr('Licence'))
                imgui.text(str(license_info.get('name', 'Not declared')))
                if license_info.get('commercialUse') == 'forbidden':
                    imgui.same_line()
                    cyui.badge(tr('non-commercial').upper(), cyui.WARNING)
                if model.get('resources', {}).get('vramBytes'):
                    cyui.property(tr('Memory'))
                    imgui.text(tr('VRAM ~') + gb(model['resources']['vramBytes']) + '   ' + tr('RAM ~') + gb(model['resources'].get('ramBytes')))
                cyui.end_properties()
            if license_info.get('notes'):
                cyui.text_wrapped_dim(str(license_info['notes']))
            if source.get('url'):
                if cyui.link_text(tr('Official page') + '##official'):
                    webbrowser.open(source['url'])
                imgui.same_line(0, 12)
            if license_info.get('url') and license_info.get('url') != source.get('url'):
                if cyui.link_text(tr('Licence page') + '##licence'):
                    webbrowser.open(license_info['url'])
            if model.get('message'):
                cyui.callout(cyui.INFO, tr(model['message']))
            if model.get('error'):
                cyui.callout(cyui.ERROR, str(model['error'])[:300])
            running = [j for j in jobs.running('install_model', 'verify_model', 'remove_model') if j['parameters'].get('model') == model['id']]
            if running:
                job = running[0]
                progress = job.get('progress') or {}
                percent = float(progress.get('percent', 0)) / 100.0
                cyui.progress_bar(percent if percent > 0 else -1.0, (cyui.dp(400.0), 0), jobs.progress_text(job)[:80])
                imgui.same_line()
                if cyui.icon_button(icon.close, tr('Cancel'), id='Cancel', fallback='x'):
                    jobs.cancel(job['jobId'])
            else:
                needs_acceptance = bool(license_info.get('requiresAcceptance')) and not model['installed']
                if needs_acceptance:
                    _, self.accepted[model['id']] = imgui.checkbox(tr('I have read this licence and I accept it personally'), self.accepted.get(model['id'], False))
                label = tr('Repair') if model['state'] in ('Failed', 'Partial') else tr('Resume') if model['state'] in ('Interrupted', 'Cancelled', 'Downloading') else tr('Download')
                if not model['installed']:
                    with cyui.scoped_disabled(needs_acceptance and not self.accepted.get(model['id'], False)):
                        if cyui.primary_button(cyui.icon_label(icon.download, label) + '###install'):
                            jobs.submit('install_model', {'model': model['id'], 'accept_license': bool(self.accepted.get(model['id'], False)), 'repair': model['state'] in ('Failed', 'Partial')},
                                        lambda job: self.refresh(), tr('Install ') + model['name'])
                    imgui.same_line(0, 4)
                if model['presentBytes'] > 0:
                    if cyui.button(tr('Verify files') + '###Verify files'):
                        jobs.submit('verify_model', {'model': model['id']}, lambda job: self.refresh(), tr('Verify ') + model['name'])
                    imgui.same_line(0, 4)
                    if cyui.danger_button(tr('Remove') + '###Remove'):
                        jobs.submit('remove_model', {'model': model['id']}, lambda job: self.refresh(), tr('Remove ') + model['name'])
            cyui.end_section()
        imgui.pop_id()
