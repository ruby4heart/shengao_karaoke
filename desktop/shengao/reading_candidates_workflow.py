"""Candidates stay beside the selected word, with the normal history guard."""
from studio_backend.model import LyricLine
from studio_backend.reading_change import preview
from .project import file_stamp
from .reading_candidates_widget import ReadingCandidates
from .reading_dictionary_store import DictionaryStore
from .reading_dictionary_dialog import DictionaryDialog
from studio_backend.reading_dictionary import put
from PySide6.QtWidgets import QDialog
import copy,hashlib,json


class ReadingCandidatesWorkflow:
    def build_reading_candidates(self,layout):
        self.reading_dictionary_store=DictionaryStore(self.home)
        self.reading_candidates=ReadingCandidates(self);layout.addWidget(self.reading_candidates);self.reading_candidates.hide()
        self.reading_candidates.audition.connect(self.playback.audition)
        self.reading_candidates.applyRequested.connect(self.apply_reading_candidate)
        self.reading_candidates.rememberRequested.connect(self.remember_current_reading)
        self.reading_candidates.manageRequested.connect(self.manage_reading_dictionary)
        self.reading_candidates.undoPersonalRequested.connect(self.undo_personal_dictionary)
        self.reading_candidates.rubyRequested.connect(self.edit_ruby_correspondence)
        self.reading_candidates.romanizationRequested.connect(self.edit_romanization)

    def dictionary_sources(self):
        error=''
        try:personal=self.reading_dictionary_store.read()
        except (ValueError,OSError) as problem:personal={};error='个人词典暂不可读，原文件保持。'+str(problem)
        song=self.project.reading_dictionary
        revision=hashlib.sha256(json.dumps([song,personal],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return song,personal,error,revision

    def refresh_reading_candidates(self):
        if not hasattr(self,'reading_candidates'):return
        line=self.line;index=self.timeline.word
        visible=bool(self.calibration_tabs.currentIndex()==1 and line and 0<=index<len(line.units))
        self.reading_candidates.setVisible(visible)
        if not visible:return
        stamp=file_stamp(self.project.media);known_mismatch=bool(self.project.transcript_stamp) and self.project.transcript_stamp!=stamp
        song,personal,error,revision=self.dictionary_sources()
        context={'project':self.project.uid,'media':stamp,'reading_confirmed':bool(self.project.checks.get(line.id,{}).get('reading')),'dictionary':revision,'romanization_rules':copy.deepcopy(self.project.reading_preferences.get('romaji'))}
        try:transcript=[LyricLine.from_dict(v) for v in self.project.transcript] if not known_mismatch else []
        except (TypeError,ValueError):transcript=[]
        self.reading_candidates.set_line(line,index,context,transcript,bool(self.project.transcript_stamp and not known_mismatch),self.project.source_ass_active,
            ('当前素材与旧转录版本不同，未使用该转录。' if known_mismatch else '')+error,song,personal)
        self.reading_candidates.undo_personal.setVisible(self.reading_dictionary_store.previous is not None)
        self.reading_candidates.setEnabled(not self.inline_segment.pending)

    def apply_reading_candidate(self,payload):
        if not self.flush_edits():return False
        context=payload.get('context',{});old=payload.get('original',{})
        if not self.line or context.get('project')!=self.project.uid or context.get('media')!=file_stamp(self.project.media) or old!=self.line.to_dict() or context.get('reading_confirmed')!=bool(self.project.checks.get(self.line.id,{}).get('reading')) or context.get('dictionary')!=self.dictionary_sources()[3] or context.get('romanization_rules')!=self.project.reading_preferences.get('romaji'):
            self.message('本句、素材或确认状态已变化，旧候选未采用；请按当前内容重新选择。');self.refresh_reading_candidates();return False
        try:result=preview(self.line,payload.get('word'),payload.get('kana',''),self.project.reading_preferences.get('romaji'))
        except ValueError as error:self.message(str(error));return False
        if not result['changed']:return False
        row=self.current;uid=self.line.id
        def apply(project):
            project.lines[row]=result['line'];project.checks.setdefault(uid,{})['reading']=False;project.source_ass_active=False
        changed=self.edit('采用所选词组读音',apply)
        if changed:self.message('已采用所选词组读音。'+('现有音节边界保持。' if result['kept_boundaries'] else '本词音节是重新估算，需再校准。')+'其他词组保持，可一步撤销。')
        return changed

    def remember_current_reading(self,scope):
        if not self.flush_edits() or not self.line or not 0<=self.timeline.word<len(self.line.units):return False
        unit=self.line.units[self.timeline.word]
        try:
            if scope=='song':
                value=put(self.project.reading_dictionary,unit.text,unit.kana);self.edit('记入本歌词典',lambda p:setattr(p,'reading_dictionary',value))
            elif scope=='personal':self.reading_dictionary_store.save(put(self.reading_dictionary_store.read(),unit.text,unit.kana))
            else:raise ValueError('请选择本歌或个人词典。')
        except (ValueError,OSError) as error:self.message(str(error));return False
        self.refresh_reading_candidates();self.message('已记住所选词当前读音；歌词、时间和确认保持。'+('本歌修改可一步撤销。' if scope=='song' else '可撤销本次个人词典保存。'));return True

    def manage_reading_dictionary(self,scope):
        if not self.flush_edits():return False
        uid=self.project.uid
        try:original=copy.deepcopy(self.project.reading_dictionary) if scope=='song' else self.reading_dictionary_store.read()
        except ValueError as error:self.message(str(error));return False
        try:digest=self.reading_dictionary_store.digest() if scope=='personal' else None
        except OSError as error:self.message('个人词典暂不可读，原文件保持。'+str(error));return False
        dialog=DictionaryDialog(original,scope,self,[self.path,self.reading_dictionary_store.path])
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        try:
            if scope=='song':
                if self.project.uid!=uid or self.project.reading_dictionary!=original:raise ValueError('工程或本歌词典已变化，旧草稿未覆盖。')
                self.edit('修改本歌词典',lambda p:setattr(p,'reading_dictionary',dialog.document))
            elif scope=='personal':
                if self.reading_dictionary_store.digest()!=digest:raise ValueError('个人词典已被别处修改，旧草稿未覆盖。')
                self.reading_dictionary_store.save(dialog.document)
            else:raise ValueError('词典范围无效。')
        except (OSError,ValueError) as error:self.message(str(error));return False
        self.refresh_reading_candidates();self.message('当前词典已保存；原歌词、读音与时间保持，选用候选时再采用。');return True

    def undo_personal_dictionary(self):
        try:self.reading_dictionary_store.undo_save()
        except (OSError,ValueError) as error:self.message(str(error));return False
        self.refresh_reading_candidates();self.message('已撤销本次个人词典保存，工程内容保持。');return True

    def edit_ruby_correspondence(self):
        if not self.flush_edits() or not self.line or not 0<=self.timeline.word<len(self.line.units):return False
        from .ruby_dialog import RubyDialog
        row=self.current;word=self.timeline.word;before=self.line.to_dict();uid=self.project.uid
        try:dialog=RubyDialog(self.project,row,word,self)
        except (ValueError,OSError) as error:self.message(str(error));return False
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        if self.project.uid!=uid or not self.line or self.line.to_dict()!=before:self.message('工程或本句已变化，旧注音对应没有覆盖。');return False
        def apply(project):project.lines[row]=dialog.result_line;project.source_ass_active=False
        result=self.edit('修改汉字与假名对应',apply)
        if result:self.select_target(word,-1);self.message('已应用本词注音对应，演唱时间与确认保持，可一步撤销。')
        return result

    def edit_romanization(self):
        if not self.flush_edits() or not self.line or not 0<=self.timeline.word<len(self.line.units):return False
        from .romanization_dialog import RomanizationDialog
        uid=self.project.uid;before=[line.to_dict() for line in self.project.lines];preferences=copy.deepcopy(self.project.reading_preferences)
        dialog=RomanizationDialog(self.project,self.current,self.timeline.word,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        if self.project.uid!=uid or preferences!=self.project.reading_preferences or before!=[line.to_dict() for line in self.project.lines]:self.message('工程、歌词或罗马音规则已变化，旧设置未覆盖。');return False
        def apply(project):
            for index,line in dialog.result_lines.items():project.lines[index]=copy.deepcopy(line)
            project.reading_preferences=copy.deepcopy(dialog.result_preferences)
            if dialog.result_lines:project.source_ass_active=False
        changed=self.edit('修改罗马音显示与来源',apply)
        if changed:self.message('已应用罗马音设置；原文、假名、时间和确认保持，可一步撤销。')
        return changed
