"""Integration tests for the pinned CyUI source and actual application adapters.
Real ImGui frames use the texture protocol without a GPU backend or AI model.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from imgui_bundle import imgui as i
import cyui

APP=Path(__file__).resolve().parents[1]

class Provenance(unittest.TestCase):
    def test_all_selected_sources_match_the_recorded_revision(self):
        record=json.loads((APP/'cyui-source.json').read_text(encoding='utf-8'))
        self.assertEqual(len(record['revision']),40)
        self.assertEqual(record['repository'],'https://github.com/MrMybal/CyUI')
        self.assertEqual(record['modifications'],[])
        for name,digest in record['files'].items():
            data=(APP/name).read_text(encoding='utf-8').replace('\r\n','\n').encode('utf-8')
            self.assertEqual(hashlib.sha256(data).hexdigest(),digest,name)
        for unselected in ('cef','web','nodes','diff'):
            self.assertFalse((APP/'cyui_modules'/f'{unselected}.py').exists())

    def test_logs_refresh_without_reusing_rows_from_another_file(self):
        from gui_log_view import LogView
        from standalone_log import redact
        view=LogView()
        view.update(redact('INFO Ready\nERROR password=secret-value'), 'standalone.log')
        revision,rows=view.buffer.snapshot()
        self.assertEqual([r.level for r in rows],['info','error'])
        self.assertNotIn('secret-value','\n'.join(r.text for r in rows))
        view.update('INFO First\n','append.log')
        _,previous=view.buffer.snapshot()
        view.update('INFO First\nINFO Second\n','append.log')
        _,appended=view.buffer.snapshot()
        self.assertEqual(appended[0].id,previous[0].id,'Appending must retain selected row identities')
        view.update('WARNING Other worker','worker.log')
        _,rows=view.buffer.snapshot(revision)
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0].source,rows[0].level),('worker.log','warning'))

class Frames(unittest.TestCase):
    def setUp(self):
        i.create_context()
        io=i.get_io();io.display_size=(1000,800);io.delta_time=1/60;io.set_ini_filename('')
        io.backend_flags|=i.BackendFlags_.renderer_has_textures
        io.config_input_trickle_event_queue=False
        io.mouse_double_click_time=.005
        cyui.apply()
    def tearDown(self):i.destroy_context()
    def frame(self,draw,position=(-100,-100),button=None):
        io=i.get_io();io.add_mouse_pos_event(*position)
        if button is not None:io.add_mouse_button_event(*button)
        i.new_frame();i.set_next_window_pos((0,0));i.set_next_window_size((1000,800))
        i.begin('Integration',None,i.WindowFlags_.no_title_bar|i.WindowFlags_.no_saved_settings|i.WindowFlags_.no_move)
        i.set_cursor_screen_pos((20,20))
        try:result=draw()
        finally:i.end();i.render()
        return result

    def test_diagnostics_in_every_theme_density_and_dpi(self):
        from gui_log_view import LogView
        from cyui_modules.locale import set_locale
        view=LogView()
        for theme,*_ in cyui.THEMES:
            for density in ('compact','comfortable'):
                for dpi in (1.,1.5,2.):
                    cyui.apply(theme,density,dpi)
                    for language in ('en','fr'):
                        set_locale(language)
                        self.frame(lambda:view.draw(i,'INFO Ready\nERROR Failure','test.log',lambda x:x))
        set_locale('en')

    def test_realtime_monitor_consumes_host_samples_in_common_views(self):
        import numpy as np
        from gui.effect_ui import EffectUI
        document=SimpleNamespace(samplerate=48000)
        host=SimpleNamespace(tr=lambda x:x,document=document)
        effect=EffectUI(host)
        tap=SimpleNamespace(in_peak=(.2,.3),out_peak=(.1,.2),recent=lambda which,count:np.zeros((2,count)))
        renderer=SimpleNamespace(taps={'monitor':tap})
        self.frame(lambda:effect.header({'id':'monitor'},renderer,900.,100.))
        self.frame(lambda:effect.header({'id':'monitor'},renderer,900.,100.))
        self.assertIn('monitor',effect._monitor_states)
        self.assertEqual(len(effect.spectra),2)

if __name__=='__main__':unittest.main()
