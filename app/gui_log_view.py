"""Host log adapter: CyUI diagnostics plus character-selectable original text.
Disk logging, redaction and copying the entire file stay with the Journal.
"""
import re
from cyui_modules.diagnostics import LogBuffer, LogState, log_view

class LogView:
    def __init__(self):
        self.buffer=LogBuffer(); self.state=LogState(); self.text=None; self.source=None
    def update(self,text,source):
        if self.text==text and self.source==source:return
        append_only=self.source==source and self.text is not None and self.text.endswith('\n') and text.startswith(self.text)
        delta=text[len(self.text):] if append_only else text
        if not append_only:
            self.buffer.clear()
            self.state.selected=0
        self.text,self.source=text,source
        for line in delta.splitlines()[-10000:]:
            match=re.search(r'\b(ERROR|WARNING|DEBUG|INFO|CRITICAL)\b',line)
            level=match.group().lower() if match else 'info'
            self.buffer.append('error' if level=='critical' else level,line,source)
    def draw(self,ui,text,source,tr):
        import cyui
        self.update(text,source)
        focus=False
        if ui.begin_tab_bar('##log-views'):
            opened,_=ui.begin_tab_item(tr('Structured log')+'###structured-log')
            if opened:
                log_view('##diagnostics',self.state,self.buffer,(0,max(cyui.dp(80),ui.get_content_region_avail().y)))
                ui.end_tab_item()
            opened,_=ui.begin_tab_item(tr('Selectable text')+'###selectable-log')
            if opened:
                ui.input_text_multiline('##standalone-log',text,(max(cyui.dp(50),ui.get_content_region_avail().x),max(cyui.dp(80),ui.get_content_region_avail().y)),flags=ui.InputTextFlags_.read_only)
                focus=ui.is_item_active()
                ui.end_tab_item()
            ui.end_tab_bar()
        return focus
