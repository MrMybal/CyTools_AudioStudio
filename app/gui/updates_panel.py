"""Updates tab: application releases (GitHub), engine sources (git revisions) and their rollback."""
import time

from imgui_bundle import imgui

import maintenance
from . import cyui


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
        icon = cyui.icon
        self.log = self.task.poll()
        if time.monotonic() - self.last_state > 5.0:
            self.state = maintenance.update_state()
            self.last_state = time.monotonic()
        busy = self.task.busy or self.app.jobs.is_running()
        app_state = self.state['application']
        cyui.panel_header(tr('Updates'), tr('Application releases from GitHub, upstream engine sources, and the way back to the previous version.'))
        cyui.space(4.0)
        if cyui.begin_section(tr('Application') + '###application'):
            if cyui.begin_properties('##app-update', 220):
                cyui.property(tr('Installed version'))
                imgui.text(str(app_state['installed']))
                if app_state.get('available'):
                    cyui.property(tr('Latest release'))
                    imgui.text(str(app_state['available']))
                cyui.property(tr('GitHub repository (owner/name)'), tr('Releases are read from this GitHub repository (the one shipped in release.json unless you change it). A release must ship cytools-app.zip and its .sha256; it replaces app/ only, never data/.'))
                _, self.repository = imgui.input_text('##repository', self.repository)
                cyui.property(tr('Check for updates at start'))
                _, self.auto_check = cyui.toggle_switch('##auto-check', self.auto_check)
                cyui.property(tr('Download and verify automatically'))
                _, self.auto_download = cyui.toggle_switch('##auto-download', self.auto_download)
                cyui.end_properties()
            if app_state.get('pending'):
                cyui.callout(cyui.WARNING, tr('Update ') + str(app_state['pending']) + tr(' is staged and will be activated at the next start.'))
            if cyui.icon_text_button(icon.save, tr('Save settings') + '###Save settings'):
                try:
                    self.settings = maintenance.save_update_settings({'tool_repository': self.repository, 'auto_check': self.auto_check, 'auto_download': self.auto_download})
                    self.message = tr('Update settings saved')
                except ValueError as exc:
                    self.message = str(exc)
            imgui.same_line(0, 12)
            with cyui.scoped_disabled(busy):
                if cyui.primary_button(cyui.icon_label(icon.refresh, tr('Check application')) + '###Check application'):
                    self.task.start('tool-check')
                imgui.same_line(0, 4)
                if cyui.icon_text_button(icon.download, tr('Download and verify') + '###Download and verify'):
                    self.task.start('tool-fetch')
                imgui.same_line(0, 4)
                if cyui.ghost_button(tr('Roll back application') + '###Roll back application'):
                    self.task.start('tool-rollback')
            cyui.end_section()
        if cyui.begin_section(tr('Engine sources') + '###engine-sources'):
            cyui.text_wrapped_faint(tr('Vendored upstream sources (Fish Speech, ACE-Step) are pinned by revision in engines.json. A newer revision can be staged beside the active one, activated, and rolled back.'))
            if cyui.begin_properties('##engines', 160):
                for name, entry in self.state['engine'].items():
                    cyui.property(name)
                    cyui.text_mono(f"{tr('active')} {entry.get('active', '')[:12] or '-'}  ·  {tr('pinned')} {entry['pinned'][:12]}"
                                   + (f"  ·  {tr('upstream')} {entry['available'][:12]}" if entry.get('available') else '') + (f"  ·  {tr('staged')} {entry['staged'][:12]}" if entry.get('staged') else ''))
                cyui.end_properties()
            with cyui.scoped_disabled(busy):
                if cyui.icon_text_button(icon.refresh, tr('Check engine sources') + '###Check engine sources'):
                    self.task.start('engine-check')
                imgui.same_line(0, 4)
                if cyui.icon_text_button(icon.download, tr('Stage newest revision') + '###Stage newest revision'):
                    self.task.start('engine-fetch')
                imgui.same_line(0, 4)
                if cyui.button(tr('Activate staged engine') + '###Activate staged engine'):
                    self.task.start('engine-apply')
                imgui.same_line(0, 4)
                if cyui.ghost_button(tr('Roll back engine') + '###Roll back engine'):
                    self.task.start('engine-rollback')
            cyui.end_section()
        if cyui.begin_section(tr('Model weights') + '###model-weights', False):
            cyui.text_wrapped_faint(tr('Weights follow their own catalogue (app/models/catalog.json) and are installed, verified and removed from the Models tab. A new catalogue revision is an application update.'))
            cyui.end_section()
        if self.task.busy:
            cyui.spinner('##maint-spinner')
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            cyui.text_coloured(cyui.palette().warning, self.task.status)
            imgui.same_line()
            if cyui.danger_button(tr('Cancel maintenance') + '###Cancel maintenance'):
                self.task.cancel()
        elif self.task.status:
            cyui.text_dim(self.task.status)
        with cyui.scoped_font(cyui.mono_font()):
            imgui.input_text_multiline('##maintlog', self.log, (-1, max(cyui.dp(120.0), imgui.get_content_region_avail().y - 4)), imgui.InputTextFlags_.read_only)
