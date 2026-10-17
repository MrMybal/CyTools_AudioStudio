"""Non-blocking JSFX source editor, backed by the same runtime operations as CLI/MCP."""
from pathlib import Path
from imgui_bundle import imgui
from audiostudio.plugins.scripts import read_source
from audiostudio.paths import APP
from . import cyui


class JsfxEditor:
    def __init__(self, app):
        self.app = app
        self.path = ''
        self.name = 'My effect'
        self.source = 'desc:My effect\nslider1:0<-60,12,0.1>Gain (dB)\n@slider\ngain = 10^(slider1/20);\n@sample\nspl0 *= gain; spl1 *= gain;\n'
        self.overwrite = False
        self.message = ''
        self.expanded = False

    def open(self, path):
        try:
            self.source = read_source(path)
            self.path = str(path)
            self.name = Path(path).stem
            self.expanded = True
        except Exception as exc:
            self.message = str(exc)

    def submit(self, save=False):
        tr = self.app.tr
        params = {'source': self.source}
        if save:
            params.update(name=self.name, overwrite=self.overwrite)
        else:
            params['directory'] = str(Path(self.path).parent) if self.path else ''
        def done(job):
            if job['state'] == 'Completed':
                if save:
                    self.path = job['outputs']['path']
                    self.message = tr('JSFX saved. Scan plugins to use it in an insert or workflow.')
                else:
                    self.message = tr('JSFX compilation succeeded.')
        self.app.jobs.submit('save_jsfx' if save else 'validate_jsfx', params, done, tr('JSFX script'))

    def draw(self):
        tr = self.app.tr
        if self.expanded:
            imgui.set_next_item_open(True, imgui.Cond_.always)
            self.expanded = False
        if not cyui.begin_section(tr('JSFX script editor') + '###jsfx-editor', False):
            return
        cyui.text_wrapped_dim(tr('Edit EEL2 source, compile in an isolated worker, then save to the user JSFX folder. A failed compilation keeps the previous script.'))
        if self.path:
            cyui.text_faint(self.path)
        if cyui.button(tr('Open JSFX script') + '###open-jsfx'):
            self.app.dialogs.open_file('jsfx-source', tr('Open JSFX script'), filters=['JSFX', '*.jsfx *'])
        imgui.same_line()
        if cyui.button(tr('New JSFX script') + '###new-jsfx'):
            self.open(APP / 'examples/JSFX/CyDAW Gain.jsfx')
            self.path = ''
            self.name = 'My effect'
        event = self.app.dialogs.poll() if self.app.dialogs.purpose == 'jsfx-source' else None
        if event:
            self.open(event[1][0] if isinstance(event[1], list) else event[1])
        if cyui.begin_properties('##jsfx-properties', 140):
            cyui.property(tr('Script name'))
            _, self.name = imgui.input_text('##jsfx-name', self.name)
            cyui.property(tr('Replace existing script'))
            _, self.overwrite = imgui.checkbox('##jsfx-overwrite', self.overwrite)
            cyui.end_properties()
        _, self.source = imgui.input_text_multiline('##jsfx-source', self.source, (-1, cyui.dp(230)), imgui.InputTextFlags_.allow_tab_input)
        busy = self.app.jobs.is_running('validate_jsfx') or self.app.jobs.is_running('save_jsfx')
        with cyui.scoped_disabled(busy):
            if cyui.button(tr('Compile JSFX') + '###compile-jsfx'):
                self.submit()
            imgui.same_line()
            if cyui.button(tr('Save JSFX') + '###save-jsfx'):
                self.submit(save=True)
        if self.message:
            cyui.text_wrapped_dim(self.message)
        cyui.end_section()
