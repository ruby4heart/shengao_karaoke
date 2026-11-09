"""Version history window, automatic checkpoints, moved media and draft recovery."""
from pathlib import Path
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QTableWidget,
    QTableWidgetItem,QHeaderView,QAbstractItemView,QPushButton,QMessageBox,QInputDialog,QSplitter,QWidget)

from . import jobs
from . import version_history as vh
from . import media_locate
from . import draft_recovery
from .project import Project,file_stamp

AUTO_INTERVAL=300  # seconds between automatic checkpoints while edits continue
STATUS={'changed':'有改动','removed':'当前已删除','added':'该版本没有','unchanged':'相同'}


def note(text):
    widget=QLabel(text);widget.setTextFormat(Qt.TextFormat.PlainText);widget.setWordWrap(True);return widget


def push(text,slot):
    widget=QPushButton(text);widget.setAutoDefault(False);widget.clicked.connect(slot);return widget


def when(meta):
    return time.strftime('%m-%d %H:%M:%S',time.localtime(meta.get('created_ms',0)/1000))


class VersionHistoryDialog(QDialog):
    """Lists checkpoints; compares one with the current document line by line."""
    def __init__(self,studio):
        super().__init__(studio);self.studio=studio;self.snapshot=None;self.changes=[]
        self.setWindowTitle('版本历史');self.resize(980,620);self.setMinimumSize(640,420)
        layout=QVBoxLayout(self)
        layout.addWidget(note('保存时和编辑过程中每隔几分钟自动记录一个版本。选一个版本可逐句比较；恢复单句不改原歌词文字，保留其他句、固定点、单句样式和当前素材，可一步撤销。'))
        split=QSplitter();layout.addWidget(split,1)
        self.versions=QListWidget();self.versions.setMinimumWidth(240);split.addWidget(self.versions)
        right=QWidget();column=QVBoxLayout(right);column.setContentsMargins(0,0,0,0);split.addWidget(right);split.setStretchFactor(1,1)
        self.summary=note('');column.addWidget(self.summary)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['句子','状态','不同之处'])
        header=self.table.horizontalHeader();header.setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch);header.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide();self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);column.addWidget(self.table,1)
        self.only_changed=QPushButton('只看有差异的句');self.only_changed.setCheckable(True);self.only_changed.setChecked(True);self.only_changed.toggled.connect(self.fill_table)
        self.status=note('');column.addWidget(self.status)
        row=QHBoxLayout();row.addWidget(self.only_changed);row.addStretch()
        self.restore_line_button=push('恢复所选句（可撤销）',self.restore_line);row.addWidget(self.restore_line_button)
        self.restore_all_button=push('整份恢复为此版本（可撤销）',self.restore_all);row.addWidget(self.restore_all_button)
        column.addLayout(row)
        bottom=QHBoxLayout();bottom.addWidget(push('立即记录当前版本',self.record_now));bottom.addStretch();bottom.addWidget(push('关闭',self.accept));layout.addLayout(bottom)
        self.versions.currentRowChanged.connect(self.load_selected);self.table.itemSelectionChanged.connect(self.update_buttons)
        self.table.cellDoubleClicked.connect(self.go_to)
        self.fill_versions()

    def store(self):return self.studio.version_store()

    def fill_versions(self,select=None):
        self.versions.blockSignals(True);self.versions.clear()
        try:entries=self.store().entries()
        except OSError as error:entries=[];self.status.setText('无法读取版本历史：'+str(error))
        for meta in entries:
            text=f'{when(meta)} · {vh.REASONS.get(meta.get("reason"),"版本")}'
            if meta.get('label'):text+=f'\n{meta["label"]}'
            text+=f'\n{meta.get("lines",0)} 句 · 时间已确认 {meta.get("timing",0)} · 读音已确认 {meta.get("readings",0)}'
            item=QListWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,meta['id']);self.versions.addItem(item)
        self.versions.blockSignals(False)
        if not entries:
            self.summary.setText('还没有记录的版本。保存工程，或继续编辑几分钟后会自动记录；也可点“立即记录当前版本”。')
            self.snapshot=None;self.changes=[];self.fill_table();return
        index=next((i for i in range(self.versions.count()) if self.versions.item(i).data(Qt.ItemDataRole.UserRole)==select),0)
        self.versions.setCurrentRow(index);self.load_selected(index)

    def load_selected(self,row):
        item=self.versions.item(row) if row>=0 else None
        if item is None:return
        try:self.snapshot=self.store().load(item.data(Qt.ItemDataRole.UserRole))
        except ValueError as error:self.snapshot=None;self.changes=[];self.summary.setText(str(error));self.fill_table();return
        self.refresh_changes()

    def refresh_changes(self):
        if self.snapshot is None:return
        current=self.studio.project.to_dict();self.changes=vh.compare(self.snapshot,current)
        changed=sum(c.status!='unchanged' for c in self.changes)
        text=f'与当前相比：{changed} 句不同，{len(self.changes)-changed} 句相同。'
        media=vh.media_note(self.snapshot,current)
        if media:text+='\n'+media
        self.summary.setText(text);self.fill_table()

    def fill_table(self,*args):
        rows=[c for c in self.changes if c.status!='unchanged' or not self.only_changed.isChecked()]
        self.table.setRowCount(len(rows))
        for index,change in enumerate(rows):
            for column,value in enumerate((change.text,STATUS[change.status],change.description if change.status=='changed' else '')):
                item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,change.line_id);self.table.setItem(index,column,item)
        self.update_buttons()

    def selected_change(self):
        items=self.table.selectedItems()
        if not items:return None
        uid=items[0].data(Qt.ItemDataRole.UserRole)
        return next((c for c in self.changes if c.line_id==uid),None)

    def update_buttons(self):
        change=self.selected_change()
        self.restore_line_button.setEnabled(change is not None and change.status in ('changed','removed'))
        self.restore_all_button.setEnabled(self.snapshot is not None and any(c.status!='unchanged' for c in self.changes))

    def go_to(self,row,column):
        change=self.selected_change()
        if change is None or change.new_index is None:return
        self.studio.current=change.new_index;self.studio.refresh()

    def restore_line(self):
        change=self.selected_change()
        if change is None or self.snapshot is None:return
        if not self.studio.flush_edits():self.status.setText('请先完成主编辑区尚未应用的修改。');return
        notes=[];snapshot=self.snapshot
        if self.studio.edit('恢复历史单句',lambda project:notes.extend(vh.restore_line(project,snapshot,change.line_id))):
            row=next((i for i,line in enumerate(self.studio.project.lines) if line.id==change.line_id),None)
            if row is not None:self.studio.current=row;self.studio.refresh()
            text='已恢复这一句，可一步撤销。'+''.join(notes)
            self.status.setText(text);self.studio.message(text);self.refresh_changes()
        else:self.status.setText(self.studio.validation_error or '这一句与该版本相同，无需恢复。')

    def restore_all(self):
        if self.snapshot is None:return
        if QMessageBox.question(self,'整份恢复','用该版本替换当前全部歌词、时间、读音和样式？素材保持当前设置，可以撤销。')!=QMessageBox.StandardButton.Yes:return
        if not self.studio.flush_edits():self.status.setText('请先完成主编辑区尚未应用的修改。');return
        self.studio.record_version('before_restore','整份恢复前',wait=True)
        snapshot=self.snapshot;notes=[]
        if self.studio.edit('整份恢复历史版本',lambda project:notes.extend(vh.restore_document(project,snapshot))):
            self.studio.current=min(max(self.studio.current,0),len(self.studio.project.lines)-1);self.studio.refresh(True)
            text='已整份恢复为该版本，可一步撤销。'+''.join(notes);self.status.setText(text);self.studio.message(text)
            self.fill_versions(self.versions.currentItem().data(Qt.ItemDataRole.UserRole) if self.versions.currentItem() else None)
        else:self.status.setText(self.studio.validation_error or '当前内容与该版本相同。')

    def record_now(self):
        meta=self.studio.record_version('auto','手动记录',wait=True)
        self.status.setText('已记录当前版本。' if meta else '当前内容与最新版本相同，没有重复记录。')
        self.fill_versions(meta['id'] if meta else None)


class DraftRecoveryDialog(QDialog):
    """Unapplied drafts from the last session: compare first, then restore or discard."""
    def __init__(self,studio,records):
        super().__init__(studio);self.studio=studio;self.records=list(records);self.restore_index=None
        self.setWindowTitle('上次未应用的草稿');self.resize(620,360)
        layout=QVBoxLayout(self)
        layout.addWidget(note('上次关闭时有尚未应用的人工草稿。只有原句、素材和试听源都没变的草稿才能恢复；已过期的草稿不会覆盖后来改好的内容，只能舍弃或暂时保留。'))
        self.list=QListWidget();layout.addWidget(self.list,1)
        self.states=[draft_recovery.assess(r,studio.project,file_stamp(studio.project.media),studio.audition_role) for r in self.records]
        for record,(state,reason) in zip(self.records,self.states):
            label=draft_recovery.describe(record)+(' · 可恢复' if state=='ready' else f' · 已过期：{reason}' if state=='stale' else f' · 无法使用：{reason}')
            self.list.addItem(label)
        self.list.setCurrentRow(0)
        row=QHBoxLayout();self.restore_button=push('恢复所选草稿',self.restore);row.addWidget(self.restore_button)
        row.addWidget(push('舍弃所选',self.discard));row.addStretch();row.addWidget(push('暂时保留并关闭',self.reject));layout.addLayout(row)
        self.list.currentRowChanged.connect(self.update_buttons);self.update_buttons()

    def update_buttons(self,*args):
        row=self.list.currentRow()
        self.restore_button.setEnabled(0<=row<len(self.states) and self.states[row][0]=='ready')

    def restore(self):
        row=self.list.currentRow()
        if 0<=row<len(self.states) and self.states[row][0]=='ready':self.restore_index=row;self.accept()

    def discard(self):
        row=self.list.currentRow()
        if not 0<=row<len(self.records):return
        del self.records[row];del self.states[row];self.list.takeItem(row);self.update_buttons()
        if not self.records:self.reject()


class VersionWorkflow:
    """Mixed into the studio window."""
    def init_version_history(self):
        self._version_time=time.monotonic();self._version_jobs=[];self.kept_drafts=[]

    def version_root(self):return self.home/'version-history'

    def version_store(self):return vh.VersionHistory(self.version_root(),self.project.uid)

    def record_version(self,reason='auto',label='',wait=False):
        """Record a checkpoint of the current document; off the GUI thread unless wait."""
        if getattr(self,'closing',False):return None
        snapshot=self.project.to_dict();root=self.version_root();uid=self.project.uid;path=str(self.path or '')
        self._version_time=time.monotonic()
        def work(cancel=None,progress=None):return vh.VersionHistory(root,uid).record(snapshot,reason,label,path)
        if wait or self.test:
            try:return work()
            except (OSError,ValueError) as error:self.message('版本历史无法写入：'+str(error));return None
        def done(result):
            if job in self._version_jobs:self._version_jobs.remove(job)
        def failed(message):
            done(None)
            if not self.closing:self.message('版本历史无法写入：'+message)
        job=jobs.run(work,done,failed);self._version_jobs.append(job);return None

    def maybe_auto_version(self):
        """Called by the autosave timer: a checkpoint every few minutes while edits continue."""
        if time.monotonic()-self._version_time<AUTO_INTERVAL or not self.history.dirty or self.pending is not None:return
        label=self.history.undo_stack[-1][0] if self.history.undo_stack else ''
        self.record_version('auto',label)

    def open_version_history(self):
        if not self.flush_edits():return
        dialog=VersionHistoryDialog(self);dialog.exec()

    # ------------------------------------------------------- moved media
    def relocate_missing_media(self,project_path=None):
        """Find media that moved since the project was saved; applied as one undoable edit."""
        missing=media_locate.missing_media(self.project)
        if not missing:return False
        found=[];unresolved=[]
        for role,old,stamp in missing:
            candidates=media_locate.locate(old,stamp,project_path)
            if not candidates:unresolved.append(Path(old).name);continue
            choice=candidates[0]
            clear=choice.automatic and (len(candidates)==1 or choice.same_file and not candidates[1].same_file)
            if not clear:
                # Several files fit, or no size was recorded: the person decides.
                if self.test:unresolved.append(Path(old).name);continue
                labels=[c.path+('（同一文件）' if c.same_file else '' if c.size_match else '（仅文件名相同）') for c in candidates]
                text,ok=QInputDialog.getItem(self,'找到可能的素材',f'「{Path(old).name}」已不在原位置。请选择要使用的文件：',labels,0,False)
                if not ok:unresolved.append(Path(old).name);continue
                choice=candidates[labels.index(text)]
            found.append((old,choice))
        if found:
            def apply(project):
                data=project.to_dict()
                for old,choice in found:media_locate.remap(data,old,choice.path,choice.same_file)
                restored=Project.from_dict(data)
                for name in Project.__dataclass_fields__:setattr(project,name,getattr(restored,name))
            if self.edit('找回移动过的素材',apply):
                names='、'.join(Path(c.path).name for _,c in found)
                recheck=any(not c.same_file for _,c in found)
                self.message(f'原素材已移动，已自动找到：{names}。保存后记住新位置，可撤销。'+('其中有文件的修改时间不同，已有转录和缓存需要重新核对。' if recheck else ''))
        if unresolved:self.message('未找到移动后的素材：'+'、'.join(unresolved)+'。请用“作品 → 重新定位媒体…”选择文件；字幕可以先编辑。')
        return bool(found)

    # ------------------------------------------------------- unapplied drafts
    def unapplied_drafts(self):
        records=list(getattr(self,'kept_drafts',[]))
        dialog=getattr(self,'tap_dialog',None)
        try:
            if (dialog is not None and dialog.isVisible() and not dialog.applied and not dialog.stale and dialog.draft.points
                and self.project.lines and dialog.draft.original.id in {x.id for x in self.project.lines}):
                line=next(x for x in self.project.lines if x.id==dialog.draft.original.id)
                records.append(draft_recovery.tap_record(self.project,line,dialog.draft,file_stamp(self.project.media),self.audition_role))
        except RuntimeError:pass  # the dialog was already destroyed
        return records

    def offer_drafts(self,records):
        records=[r for r in records if isinstance(r,dict)]
        if not records:return
        dialog=DraftRecoveryDialog(self,records);dialog.exec()
        chosen=dialog.records[dialog.restore_index] if dialog.restore_index is not None else None
        self.kept_drafts=[r for r in dialog.records if r is not chosen]
        if chosen is not None:self.restore_tap_draft(chosen)
        self.save_recovery()

    def restore_tap_draft(self,record):
        row=next((i for i,x in enumerate(self.project.lines) if x.id==record['line_id']),None)
        if row is None:return False
        self.current=row;self.refresh()
        dialog=self.open_tap_timing()
        if dialog is None:return False
        try:draft=draft_recovery.rebuild(record,self.project.lines[row])
        except ValueError as error:self.message(str(error));return False
        dialog.mode.blockSignals(True);dialog.gaps.blockSignals(True)
        dialog.mode.setCurrentIndex(max(0,dialog.mode.findData(draft.mode)));dialog.gaps.setChecked(draft.acknowledge_gaps)
        dialog.mode.blockSignals(False);dialog.gaps.blockSignals(False)
        dialog.draft=draft;dialog.render();dialog.status.setText('已恢复上次未应用的打点草稿；比较后再应用，或继续试听补录。')
        self.message('已恢复上次的跟唱打点草稿，尚未应用到工程。')
        return True
