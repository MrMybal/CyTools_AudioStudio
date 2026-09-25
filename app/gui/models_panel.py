"""Models tab: engines and model weights — state, size, source, licence, download/resume/repair/remove."""
import time
import webbrowser

from imgui_bundle import imgui

from audiostudio import models as model_catalog
from audiostudio.engines import registry as engines
from .widgets import status_line

STATE_COLOUR = {'Installed': (0.5, 0.9, 0.5, 1.0), 'Downloading': (0.95, 0.8, 0.3, 1.0), 'Verifying': (0.95, 0.8, 0.3, 1.0), 'Partial': (0.95, 0.7, 0.3, 1.0),
                'Interrupted': (0.95, 0.6, 0.3, 1.0), 'Failed': (1.0, 0.45, 0.4, 1.0), 'AccessRequired': (1.0, 0.55, 0.4, 1.0),
                'LicenseAcceptanceRequired': (0.95, 0.7, 0.3, 1.0), 'Cancelled': (0.8, 0.8, 0.8, 1.0), 'NotInstalled': (0.7, 0.7, 0.75, 1.0)}


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

    def draw(self):
        tr = self.tr
        jobs = self.app.jobs
        if time.monotonic() - self.last_refresh > (2.0 if jobs.is_running('install_model', 'install_engine', 'verify_model', 'remove_model') else 15.0):
            self.refresh()
        imgui.separator_text(tr('Engines'))
        imgui.text_wrapped(tr('Engines are private Python environments under runtime/engines. They are created at their final path with the pinned versions and checked by import before use.'))
        for name, info in self.engine_status.items():
            imgui.push_id(name)
            colour = STATE_COLOUR['Installed'] if info['installed'] else STATE_COLOUR['NotInstalled']
            imgui.text_colored(colour, info['state'])
            imgui.same_line()
            imgui.text(info['label'] + (f"  (torch {info['torch']}, {info['device']})" if info.get('torch') else '') + f"  ~{gb(info.get('estimatedBytes'))}")
            for source, item in info.get('sources', {}).items():
                imgui.bullet_text(f"{source}: {'ok' if item['ok'] else tr('missing or wrong revision')} ({item['expected'][:12]})")
            running = jobs.is_running('install_engine')
            imgui.begin_disabled(running)
            if imgui.button(tr('Install or repair (GPU)')):
                jobs.submit('install_engine', {'engine': name, 'cpu_only': False}, lambda job: self.refresh(), tr('Engine ') + name)
            if info.get('backends') and 'torch' == name:
                imgui.same_line()
                if imgui.button(tr('Install CPU-only build')):
                    jobs.submit('install_engine', {'engine': name, 'cpu_only': True}, lambda job: self.refresh(), tr('Engine ') + name)
            imgui.end_disabled()
            imgui.pop_id()
        for job in jobs.running('install_engine'):
            imgui.progress_bar(0.5, (400, 0), jobs.progress_text(job)[:90])
            imgui.same_line()
            if imgui.small_button(tr('Cancel') + '##eng'):
                jobs.cancel(job['jobId'])
        imgui.separator_text(tr('Hugging Face access'))
        imgui.text_wrapped(tr('All catalogue models are public. A token is only needed for gated models you add later; it is stored in the Windows credential store, never in files or logs.'))
        imgui.push_item_width(300)
        _, self.token = imgui.input_text(tr('Token'), self.token, imgui.InputTextFlags_.password)
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.button(tr('Store token')):
            try:
                model_catalog.store_token(self.token)
                self.token = ''
                self.message = tr('Token stored in the credential store')
            except Exception as exc:
                self.message = str(exc)
        imgui.same_line()
        if imgui.button(tr('Forget token')):
            model_catalog.store_token('')
            self.message = tr('Token removed')
        imgui.same_line()
        if imgui.button(tr('Create a read token')):
            webbrowser.open('https://huggingface.co/settings/tokens')
        imgui.separator_text(tr('Models'))
        changed, self.show_voices = imgui.checkbox(tr('Show all 177 Piper voices'), self.show_voices)
        if changed:
            self.refresh()
        if self.show_voices:
            imgui.same_line()
            imgui.push_item_width(200)
            _, self.voice_filter = imgui.input_text(tr('Filter voices'), self.voice_filter)
            imgui.pop_item_width()
        imgui.begin_child('##models', (0, max(200.0, imgui.get_content_region_avail().y - 30)), True)
        for model in self.models:
            if self.show_voices and model['backend'] == 'piper' and self.voice_filter and self.voice_filter.lower() not in model['id'].lower():
                continue
            self._draw_model(model)
        imgui.end_child()
        if self.message:
            status_line(self.message)

    def _draw_model(self, model):
        tr = self.tr
        jobs = self.app.jobs
        imgui.push_id(model['id'])
        colour = STATE_COLOUR.get(model['state'], STATE_COLOUR['NotInstalled'])
        header = f"{model['name']}  [{model['backend']}]"
        if imgui.collapsing_header(header + '###hdr'):
            imgui.text_colored(colour, tr(model['state']))
            imgui.same_line()
            imgui.text(f"{tr('Download')}: {gb(model['downloadBytes'])}   {tr('present')}: {gb(model['presentBytes'])}   {tr('missing files')}: {model['missing']}")
            imgui.text_disabled(model['directory'])
            source = model.get('source', {})
            license_info = model.get('license', {})
            imgui.text(tr('Licence: ') + str(license_info.get('name', 'Not declared')) + ('  (' + tr('non-commercial') + ')' if license_info.get('commercialUse') == 'forbidden' else ''))
            if license_info.get('notes'):
                imgui.text_wrapped(str(license_info['notes']))
            if source.get('url'):
                if imgui.button(tr('Official page')):
                    webbrowser.open(source['url'])
                imgui.same_line()
            if license_info.get('url') and license_info.get('url') != source.get('url'):
                if imgui.button(tr('Licence page')):
                    webbrowser.open(license_info['url'])
                imgui.same_line()
            if model.get('resources', {}).get('vramBytes'):
                imgui.text_disabled(tr('VRAM ~') + gb(model['resources']['vramBytes']) + '  ' + tr('RAM ~') + gb(model['resources'].get('ramBytes')))
            else:
                imgui.new_line()
            if model.get('message'):
                imgui.text_wrapped(tr(model['message']))
            if model.get('error'):
                imgui.text_colored((1.0, 0.45, 0.4, 1.0), str(model['error'])[:300])
            running = [j for j in jobs.running('install_model', 'verify_model', 'remove_model') if j['parameters'].get('model') == model['id']]
            if running:
                job = running[0]
                progress = job.get('progress') or {}
                imgui.progress_bar(float(progress.get('percent', 0)) / 100.0, (400, 0), jobs.progress_text(job)[:80])
                imgui.same_line()
                if imgui.small_button(tr('Cancel')):
                    jobs.cancel(job['jobId'])
            else:
                needs_acceptance = bool(license_info.get('requiresAcceptance')) and not model['installed']
                if needs_acceptance:
                    _, self.accepted[model['id']] = imgui.checkbox(tr('I have read this licence and I accept it personally'), self.accepted.get(model['id'], False))
                label = tr('Repair') if model['state'] in ('Failed', 'Partial') else tr('Resume') if model['state'] in ('Interrupted', 'Cancelled', 'Downloading') else tr('Download')
                if not model['installed']:
                    imgui.begin_disabled(needs_acceptance and not self.accepted.get(model['id'], False))
                    if imgui.button(label):
                        jobs.submit('install_model', {'model': model['id'], 'accept_license': bool(self.accepted.get(model['id'], False)), 'repair': model['state'] in ('Failed', 'Partial')},
                                    lambda job: self.refresh(), tr('Install ') + model['name'])
                    imgui.end_disabled()
                    imgui.same_line()
                if model['presentBytes'] > 0:
                    if imgui.button(tr('Verify files')):
                        jobs.submit('verify_model', {'model': model['id']}, lambda job: self.refresh(), tr('Verify ') + model['name'])
                    imgui.same_line()
                    if imgui.button(tr('Remove')):
                        jobs.submit('remove_model', {'model': model['id']}, lambda job: self.refresh(), tr('Remove ') + model['name'])
        imgui.pop_id()
