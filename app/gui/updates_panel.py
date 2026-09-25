"""Updates tab: application releases (GitHub), engine sources (git revisions) and their rollback."""
import time

from imgui_bundle import imgui

import maintenance
from .widgets import status_line


class UpdatesPanel:
    def __init__(self, app):
        self.app = app
        self.task = maintenance.Task()
        self.settings = maintenance.update_settings()
        self.repository = self.settings.get('tool_repository', '')
        self.auto_check = bool(self.settings.get('auto_check', False))
        self.auto_download = bool(self.settings.get('auto_download', False))
        self.state = maintenance.update_state()
        self.log = ''
        self.last_state = 0.0
        self.message = ''
        if self.auto_check or self.auto_download:
            self.task.start('auto-download' if self.auto_download else 'auto-check')

    def tr(self, text):
        return self.app.tr(text)

    def draw(self):
        tr = self.tr
        self.log = self.task.poll()
        if time.monotonic() - self.last_state > 5.0:
            self.state = maintenance.update_state()
            self.last_state = time.monotonic()
        busy = self.task.busy or self.app.jobs.is_running()
        app_state = self.state['application']
        imgui.separator_text(tr('Application'))
        imgui.text(tr('Installed version: ') + str(app_state['installed']))
        if app_state.get('available'):
            imgui.same_line()
            imgui.text(tr('  Latest release: ') + str(app_state['available']))
        if app_state.get('pending'):
            imgui.text_colored((0.95, 0.8, 0.3, 1.0), tr('Update ') + str(app_state['pending']) + tr(' is staged and will be activated at the next start.'))
        imgui.push_item_width(320)
        _, self.repository = imgui.input_text(tr('GitHub repository (owner/name)'), self.repository)
        imgui.pop_item_width()
        imgui.same_line()
        if imgui.button(tr('Save settings')):
            try:
                self.settings = maintenance.save_update_settings({'tool_repository': self.repository, 'auto_check': self.auto_check, 'auto_download': self.auto_download})
                self.message = tr('Update settings saved')
            except ValueError as exc:
                self.message = str(exc)
        imgui.text_wrapped(tr('Releases are read from this GitHub repository (the one shipped in release.json unless you change it). A release must ship cytools-app.zip and its .sha256; it replaces app/ only, never data/.'))
        _, self.auto_check = imgui.checkbox(tr('Check for updates at start'), self.auto_check)
        imgui.same_line()
        _, self.auto_download = imgui.checkbox(tr('Download and verify automatically'), self.auto_download)
        imgui.begin_disabled(busy)
        if imgui.button(tr('Check application')):
            self.task.start('tool-check')
        imgui.same_line()
        if imgui.button(tr('Download and verify')):
            self.task.start('tool-fetch')
        imgui.same_line()
        if imgui.button(tr('Roll back application')):
            self.task.start('tool-rollback')
        imgui.end_disabled()
        imgui.separator_text(tr('Engine sources'))
        imgui.text_wrapped(tr('Vendored upstream sources (Fish Speech, ACE-Step) are pinned by revision in engines.json. A newer revision can be staged beside the active one, activated, and rolled back.'))
        for name, entry in self.state['engine'].items():
            imgui.bullet_text(f"{name}: {tr('active')} {entry.get('active', '')[:12] or '-'} | {tr('pinned')} {entry['pinned'][:12]}"
                              + (f" | {tr('upstream')} {entry['available'][:12]}" if entry.get('available') else '') + (f" | {tr('staged')} {entry['staged'][:12]}" if entry.get('staged') else ''))
        imgui.begin_disabled(busy)
        if imgui.button(tr('Check engine sources')):
            self.task.start('engine-check')
        imgui.same_line()
        if imgui.button(tr('Stage newest revision')):
            self.task.start('engine-fetch')
        imgui.same_line()
        if imgui.button(tr('Activate staged engine')):
            self.task.start('engine-apply')
        imgui.same_line()
        if imgui.button(tr('Roll back engine')):
            self.task.start('engine-rollback')
        imgui.end_disabled()
        imgui.separator_text(tr('Model weights'))
        imgui.text_wrapped(tr('Weights follow their own catalogue (app/models/catalog.json) and are installed, verified and removed from the Models tab. A new catalogue revision is an application update.'))
        if self.task.busy:
            imgui.text_colored((0.95, 0.8, 0.3, 1.0), self.task.status)
            imgui.same_line()
            if imgui.button(tr('Cancel maintenance')):
                self.task.cancel()
        elif self.task.status:
            imgui.text(self.task.status)
        imgui.input_text_multiline('##maintlog', self.log, (-1, 160), imgui.InputTextFlags_.read_only)
        if self.message:
            status_line(self.message)
