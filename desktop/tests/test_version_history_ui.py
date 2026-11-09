"""Dialog and window-side flows with a stand-in for the Windows-only main window."""
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget,QMessageBox

from shengao import draft_recovery
from shengao.project import History,Project,file_stamp
from shengao.tap_timing import TapDraft
from shengao.version_history_dialog import VersionWorkflow,VersionHistoryDialog,DraftRecoveryDialog


class Studio(QWidget,VersionWorkflow):
    def __init__(self,home,project):
        super().__init__();self.home=Path(home);self.history=History(project);self.path=None;self.pending=None
        self.current=0;self.test=True;self.closing=False;self.validation_error='';self.messages=[];self.audition_role='original'
        self.init_version_history()
    @property
    def project(self):return self.history.project
    def edit(self,title,fn,*args,**kwargs):
        self.validation_error=''
        try:return self.history.apply(title,fn)
        except (ValueError,IndexError,KeyError) as error:self.validation_error=str(error);self.message(str(error));return False
    def flush_edits(self,*args):return True
    def message(self,text):self.messages.append(text)
    def refresh(self,*args):pass


@pytest.fixture
def studio(qapp,tmp_path,project):
    from tests.test_version_history import shifted
    first=project.lines[0];project.lines=[first,shifted(first,'second',6000)];project.checks={first.id:{'reading':True}};project.validate()
    window=Studio(tmp_path/'home',project);yield window;window.deleteLater()


def test_history_dialog_restores_selected_line_as_one_undo(studio):
    saved=studio.record_version('save',wait=True);assert saved
    studio.edit('改时间',lambda p:setattr(p.lines[0].units[0].highlights[0],'start',p.lines[0].units[0].highlights[0].start+30))
    studio.edit('改译文',lambda p:setattr(p.lines[1],'translation','新译文'))
    after=studio.project.to_dict()
    dialog=VersionHistoryDialog(studio)
    assert dialog.versions.count()==1 and dialog.table.rowCount()==2 and '2 句不同' in dialog.summary.text()
    dialog.table.selectRow(0);assert dialog.restore_line_button.isEnabled()
    dialog.restore_line()
    assert studio.project.lines[0].to_dict()==dialog.snapshot['lines'][0] and studio.project.lines[1].translation=='新译文'
    assert '已恢复这一句' in dialog.status.text() and dialog.table.rowCount()==1
    assert studio.history.undo() and studio.project.to_dict()==after
    dialog.close()


def test_whole_restore_records_the_state_before_it(studio,monkeypatch):
    studio.record_version('save',wait=True)
    studio.edit('删一句',lambda p:p.lines.pop())
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    dialog=VersionHistoryDialog(studio);dialog.restore_all()
    assert len(studio.project.lines)==2
    reasons=[e['reason'] for e in studio.version_store().entries()]
    assert reasons==['before_restore','save'] and dialog.versions.count()==2
    dialog.close()


def test_auto_checkpoint_waits_for_interval_and_real_edits(studio):
    studio.maybe_auto_version();assert studio.version_store().entries()==[]
    studio.edit('改译文',lambda p:setattr(p.lines[1],'translation','x'))
    studio.maybe_auto_version();assert studio.version_store().entries()==[]
    studio._version_time-=400;studio.maybe_auto_version()
    entries=studio.version_store().entries()
    assert len(entries)==1 and entries[0]['label']=='改译文' and entries[0]['reason']=='auto'


def test_moved_media_is_relocated_as_undoable_edit(studio,tmp_path):
    media=tmp_path/'old'/'mv.wav';media.parent.mkdir();media.write_bytes(b'1'*40)
    stamp=file_stamp(media)
    studio.history=History(Project.from_dict({**studio.project.to_dict(),'media':str(media),'media_stamp':stamp,
        'media_versions':{'original':{'path':str(media),'duration':0,'stamp':dict(stamp)}}}))
    target=tmp_path/'song'/'media'/'mv.wav';target.parent.mkdir(parents=True);shutil.move(media,target)
    assert studio.relocate_missing_media(tmp_path/'song'/'mv.sgproj')
    assert studio.project.media==str(target.resolve()) and studio.project.media_stamp==file_stamp(target)
    assert '已自动找到' in studio.messages[-1] and studio.history.undo() and studio.project.media==str(media)


def test_missing_media_without_match_explains_next_step(studio,tmp_path):
    studio.history=History(Project.from_dict({**studio.project.to_dict(),'media':str(tmp_path/'none'/'x.mp4')}))
    assert not studio.relocate_missing_media(tmp_path/'p.sgproj') and '重新定位媒体' in studio.messages[-1]


def test_draft_dialog_only_restores_current_drafts(studio):
    line=studio.project.lines[0];draft=TapDraft(line);draft.add(line.start+10)
    ready=draft_recovery.tap_record(studio.project,line,draft,file_stamp(studio.project.media),'original')
    stale=dict(ready,line_id='second',original=studio.project.lines[1].to_dict(),text='旧')
    studio.edit('后来改过第二句',lambda p:setattr(p.lines[1],'translation','改好的'))
    dialog=DraftRecoveryDialog(studio,[ready,stale])
    assert [s for s,_ in dialog.states]==['ready','stale'] and '已过期' in dialog.list.item(1).text()
    dialog.list.setCurrentRow(1);assert not dialog.restore_button.isEnabled()
    dialog.discard();assert len(dialog.records)==1
    dialog.list.setCurrentRow(0);assert dialog.restore_button.isEnabled();dialog.restore()
    assert dialog.restore_index==0
