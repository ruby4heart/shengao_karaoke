"""Export page: visible sample range, output folder, batch queue and font checks.

Every video, single or batch, goes through one ``RenderQueue``: a task keeps
its own project snapshot and settings, runs after the one before it, reports
its own progress and can be cancelled on its own.  ``encode_to`` keeps the old
single-task entry point used by the self test.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from . import jobs
from .encode import encode, EncodeOptions
from .media_versions import ROLES
from .project import Project, file_stamp
from .render_plan import (SAMPLE_MODES, SAMPLE_DEFAULT, SAMPLE_MIN, SAMPLE_MAX, SIZES, QUALITIES, clock,
                          describe_options, font_warnings, output_folder, output_name, sample_range,
                          unique_path, version_snapshot)
from .render_queue import RenderQueue, RenderRecords


def _label(text, kind='muted'):
    item = QLabel(text); item.setTextFormat(Qt.TextFormat.PlainText); item.setObjectName(kind); item.setWordWrap(True)
    return item


def _button(text, fn, tip=''):
    widget = QPushButton(text); widget.clicked.connect(fn)
    if tip: widget.setToolTip(tip)
    return widget


def _path_field():
    # A long folder path has no spaces to wrap at; a read-only field keeps the
    # export panel's width (no sideways scrolling) and the path stays copyable.
    item = QLineEdit(); item.setReadOnly(True); item.setMinimumWidth(80)
    return item


def font_export_note(report, kind):
    if kind != 'ass' or not report: return ''
    text = f'已随附 {len(report["fonts"])} 个字体文件。'
    if report['missing']: text += '以下字体文件已找不到，没能随附：' + '、'.join(report['missing'][:6]) + '。'
    return text


class RenderWorkflow:
    """Mixed into the studio window."""
    def init_render_workflow(self):
        self.render_records = RenderRecords(self.home)
        self.render_queue = RenderQueue(self._start_render, self.render_records, self._render_changed)
        self._last_sample = None

    # ------------------------------------------------------------ controls
    def build_render_controls(self, layout):
        row = QHBoxLayout(); row.addWidget(QLabel('样片范围'))
        self.sample_mode = QComboBox()
        for key, text in SAMPLE_MODES.items(): self.sample_mode.addItem(text, key)
        self.sample_start = QDoubleSpinBox(); self.sample_start.setDecimals(1); self.sample_start.setRange(0, 24 * 3600); self.sample_start.setSuffix(' 秒起')
        self.sample_start.setToolTip('自定义样片的起点，单位为秒')
        self.sample_length = QDoubleSpinBox(); self.sample_length.setDecimals(0); self.sample_length.setRange(SAMPLE_MIN / 1000, SAMPLE_MAX / 1000)
        self.sample_length.setValue(SAMPLE_DEFAULT / 1000); self.sample_length.setSuffix(' 秒'); self.sample_length.setToolTip('样片长度，2 到 60 秒')
        row.addWidget(self.sample_mode, 1); row.addWidget(self.sample_start); row.addWidget(self.sample_length); layout.addLayout(row)
        self.sample_label = _label(''); layout.addWidget(self.sample_label)
        row = QHBoxLayout(); row.addWidget(QLabel('输出目录'))
        self.output_folder_label = _path_field(); row.addWidget(self.output_folder_label, 1)
        row.addWidget(_button('更改…', self.choose_output_folder, '选择样片和成品默认保存的文件夹；会记住这次的选择'))
        layout.addLayout(row)
        saved = self.preferences.data.get('sample')
        if isinstance(saved, dict):
            if saved.get('mode') in SAMPLE_MODES: self.sample_mode.setCurrentIndex(self.sample_mode.findData(saved['mode']))
            if type(saved.get('length')) is int: self.sample_length.setValue(max(SAMPLE_MIN, min(SAMPLE_MAX, saved['length'])) / 1000)
        self.sample_mode.currentIndexChanged.connect(self.sample_settings_changed)
        self.sample_start.valueChanged.connect(self.sample_settings_changed)
        self.sample_length.valueChanged.connect(self.sample_settings_changed)

    def build_render_queue(self, layout):
        layout.addWidget(_label('批量压制队列', 'heading'))
        layout.addWidget(_label('每个任务使用加入时的工程快照，依次压制；可以单独取消。结果都写入任务记录。'))
        self.render_list = QListWidget(); self.render_list.setWordWrap(True); self.render_list.setMinimumHeight(90)
        layout.addWidget(self.render_list)
        row = QGridLayout()   # two by two: four buttons in one row do not fit the compact export panel
        row.addWidget(_button('批量导出…', self.open_batch_dialog, '一次加入多个视频版本或分辨率，按顺序压制'), 0, 0)
        row.addWidget(_button('清除已结束', self.clear_finished_renders, '从列表移除已完成、失败或已取消的任务；任务记录保留'), 0, 1)
        row.addWidget(_button('取消所选', self.cancel_selected_render, '取消所选任务；正在压制的会停止，不会留下半成品'), 1, 0)
        row.addWidget(_button('全部取消', self.cancel_renders, '取消正在压制和等待中的全部任务'), 1, 1)
        layout.addLayout(row)

    def sample_settings_changed(self, *args):
        try: self.preferences.set('sample', {'mode': self.sample_mode.currentData(), 'length': int(self.sample_length.value() * 1000)})
        except (OSError, ValueError): pass
        self.refresh_sample_range()

    def current_sample(self):
        return sample_range(self.project, self.sample_mode.currentData(), self.current, self.playback.canvas.position,
                            round(self.sample_start.value() * 1000), round(self.sample_length.value() * 1000))

    def refresh_sample_range(self):
        if not hasattr(self, 'sample_label'): return
        mode = self.sample_mode.currentData(); self.sample_start.setVisible(mode == 'custom')
        length = self.sample_length.value()
        if hasattr(self, 'sample_button'): self.sample_button.setText(f'先看 {length:g} 秒样片')
        try:
            text = self.current_sample()['text']
            if mode == 'playhead': text += '；按点击时的播放点计算'
        except ValueError as error: text = str(error)
        self.sample_label.setText(text)
        self.show_output_folder(self.output_directory())

    # ------------------------------------------------------------ destination
    def output_directory(self):
        saved = self.preferences.data.get('output_folder', '')
        return output_folder(saved if isinstance(saved, str) else '', self.path, self.project.media)

    def remember_output_folder(self, folder):
        self.preferences.set('output_folder', str(Path(folder)))
        if hasattr(self, 'output_folder_label'): self.show_output_folder(str(Path(folder)))

    def show_output_folder(self, folder):
        text = str(folder); self.output_folder_label.setText(text); self.output_folder_label.setToolTip(text)
        self.output_folder_label.setCursorPosition(0)

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择输出目录', self.output_directory())
        if folder: self.remember_output_folder(folder); self.message('样片和成品默认保存到：' + folder)

    def queued_outputs(self):
        return [t.options.output for t in self.render_queue.tasks if not t.done]

    # ------------------------------------------------------------ fonts
    def confirm_fonts(self, action):
        """Say which fonts are substituted, missing or incomplete before export."""
        warnings = font_warnings(self.project)
        if not warnings: return True
        text = '；'.join(warnings[:3]) + (f' 等 {len(warnings)} 项' if len(warnings) > 3 else '')
        if self.test: self.message('字体提醒：' + text); return True
        box = QMessageBox(self); box.setWindowTitle('字体提醒'); box.setIcon(QMessageBox.Icon.Warning)
        box.setText('以下字体问题会让' + action + '的字幕与选定的字体不同：')
        box.setInformativeText('\n'.join('· ' + w for w in warnings[:8]) + ('\n…' if len(warnings) > 8 else ''))
        go = box.addButton('仍然' + action, QMessageBox.ButtonRole.AcceptRole)
        box.addButton('先去处理', QMessageBox.ButtonRole.RejectRole); box.setDefaultButton(go); box.exec()
        if box.clickedButton() is go: return True
        self.message('已暂停' + action + '。可在“注音样式”中重新选择字体：' + text)
        return False

    def note_font_problems(self):
        """Appended to the status line when a project is opened."""
        try: warnings = font_warnings(self.project)
        except (ValueError, OSError): return ''
        if not warnings: return ''
        note = '字体提醒：' + '；'.join(warnings[:2]) + (f' 等 {len(warnings)} 项，导出前会再次提示' if len(warnings) > 2 else '')
        self.message((self.status.text() + ' ' if self.status.text() else '') + note)
        return note

    # ------------------------------------------------------------ starting renders
    def encode_settings(self, sample):
        start = duration = 0
        if sample:
            chosen = self.current_sample(); start, duration = chosen['start'], chosen['duration']
        codec = (self.encoder_capabilities or {}).get('cpu_codec') or 'h264_mf'
        return EncodeOptions('', start, duration, self.output_size.currentData(), self.quality.currentData(), self.encoder.currentData(), codec)

    def start_encode(self, sample):
        if not self.flush_edits(): return
        if self.source_job: self.message('请等待换源任务完成再压制'); return
        if not self.project.duration: self.message('请先添加视频或音频，等待素材读取完成'); return
        try: options = self.encode_settings(sample)
        except ValueError as error: self.message(str(error)); return
        if not self.confirm_fonts('压制'): return
        suggested = unique_path(self.output_directory(), output_name(self.project, sample, options.size), self.queued_outputs())
        path, _ = QFileDialog.getSaveFileName(self, '试压视频' if sample else '压制成品视频', str(suggested), 'MP4 视频 (*.mp4)')
        if not path: return
        if not path.lower().endswith('.mp4'): path += '.mp4'
        if any(Path(path).resolve() == Path(x).resolve() for x in self.queued_outputs()):
            self.message('这个文件已在压制队列中，请换一个文件名'); return
        self.remember_output_folder(Path(path).parent)
        options.output = path
        self.encode_to(options, kind='sample' if sample else 'full')

    def encode_to(self, options, kind=None, project=None, label=None):
        if self.source_job: self.message('请等待换源完成再压制'); return None
        found = (self.encoder_capabilities or {}).get('cpu_codec')
        if options.encoder == 'cpu' and found and options.codec != found: options.codec = found   # e.g. libx264 when Media Foundation is missing
        snapshot = project if project is not None else Project.from_dict(self.project.to_dict())
        kind = kind or ('sample' if options.duration else 'full')
        if label is None:
            role = ROLES.get(snapshot.media_role, '') if len(snapshot.media_versions) > 1 else ''
            label = ('样片' if kind == 'sample' else '成品') + ' · ' + describe_options(options, role)
        ahead = len(self.render_queue.waiting()) + (1 if self.render_queue.running else 0)
        task = self.render_queue.add(snapshot, options, label, kind)
        if ahead: self.message(f'已加入压制队列，前面还有 {ahead} 个任务；使用当前工程的独立快照。')
        else: self.message('压制任务已开始，使用当前工程的独立快照。')
        return task

    def open_batch_dialog(self):
        if not self.flush_edits(): return
        p = self.project
        if not p.duration or not p.lines: self.message('请先添加素材和歌词，并等待素材读取完成'); return
        if self.source_job: self.message('请等待换源任务完成再压制'); return
        dialog = QDialog(self); dialog.setWindowTitle('批量导出视频'); dialog.resize(520, 420); l = QVBoxLayout(dialog)
        l.addWidget(_label('勾选要导出的视频版本和分辨率，会按顺序逐个压制。画质与编码方式使用导出页当前的设置：'
                           f'{QUALITIES.get(self.quality.currentData(), "")}，{self.encoder.currentText()}。'))
        roles = [p.media_role] + [r for r in p.media_versions if r != p.media_role]
        role_checks = {}
        l.addWidget(_label('视频版本', 'heading'))
        for role in roles:
            path = p.media if role == p.media_role else p.media_versions[role].path
            check = QCheckBox(f'{ROLES.get(role, role)} · {Path(path).name}'); check.setChecked(role == p.media_role)
            role_checks[role] = check; l.addWidget(check)
        l.addWidget(_label('分辨率', 'heading'))
        size_checks = {}
        for size, text in SIZES.items():
            check = QCheckBox(text); check.setChecked(size == self.output_size.currentData()); size_checks[size] = check; l.addWidget(check)
        sample_only = QCheckBox('只压样片（使用导出页的样片范围）'); l.addWidget(sample_only)
        folder_label = _label('保存到：' + self.output_directory()); l.addWidget(folder_label)
        folder_button = _button('更改输出目录…', lambda: (self.choose_output_folder(), folder_label.setText('保存到：' + self.output_directory())))
        l.addWidget(folder_button); l.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('加入队列')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); l.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        chosen_roles = [r for r, c in role_checks.items() if c.isChecked()]
        sizes = [s for s, c in size_checks.items() if c.isChecked()]
        self.queue_batch(chosen_roles, sizes, sample_only.isChecked())

    def queue_batch(self, roles, sizes, sample=False):
        """Add one task per version and size; returns the added tasks."""
        if not roles or not sizes: self.message('请至少勾选一个视频版本和一个分辨率'); return []
        try: base = self.encode_settings(sample)
        except ValueError as error: self.message(str(error)); return []
        if not self.confirm_fonts('批量压制'): return []
        folder = self.output_directory(); taken = self.queued_outputs(); added = []; skipped = []
        for role in roles:
            try: snapshot = version_snapshot(self.project, role)
            except ValueError as error: skipped.append(str(error)); continue
            for size in sizes:
                name = output_name(self.project, sample, size, role, with_size=len(sizes) > 1)
                path = unique_path(folder, name, taken); taken.append(str(path))
                options = EncodeOptions(str(path), base.start, base.duration, size, base.quality, base.encoder, base.codec)
                label = ('样片' if sample else '成品') + ' · ' + describe_options(options, ROLES.get(role, role))
                added.append(self.render_queue.add(Project.from_dict(snapshot.to_dict()), options, label, 'sample' if sample else 'full'))
        text = f'已加入 {len(added)} 个压制任务，保存到 {folder}。' if added else '没有加入压制任务。'
        if skipped: text += '未加入：' + '；'.join(skipped) + '。'
        self.message(text)
        return added

    # ------------------------------------------------------------ queue callbacks
    def _start_render(self, task, done, failed, progress):
        stamp = file_stamp(task.project.media)
        def finished(result):
            self.local_job = None
            try: self._render_done(task, result, stamp)
            finally: done(result); self.busy_changed()
        def broke(message):
            self.local_job = None
            failed(message)
            self.message(task.message if task.state == 'cancelled' else message); self.busy_changed()
        job = jobs.run(lambda cancel, report: encode(task.project, task.options, cancel, report), finished, broke, progress)
        self.local_job = job; self.busy_changed()
        return job

    def _render_done(self, task, result, stamp):
        p = task.project
        self.last_output = result['output']; self._last_output_snapshot = p.to_dict(); self._last_output_stamp = stamp
        self._last_output_full = task.kind == 'full' and task.options.start == 0 and (not task.options.duration or task.options.duration >= p.duration)
        note = ''
        if task.kind == 'sample':
            self._last_sample = {'uid': p.uid, 'fingerprint': result.get('fingerprint'), 'output': result['output']}
        elif self._last_sample and self._last_sample['uid'] == p.uid and result.get('fingerprint'):
            same = self._last_sample['fingerprint'] == result['fingerprint']; result['matches_sample'] = same
            note = ('与上次样片使用同一份时间、排版和字体。' if same else
                    '注意：成品与上次样片的字幕时间、排版或字体不同（样片之后有修改），建议再看一次样片。')
        checked = result.get('checked') or {}
        seconds = f'{checked["duration_ms"] / 1000:.1f} 秒' if checked.get('duration_ms') else ''
        self.output_label.setText('已完成：' + result['output'] + (f'（已读回检查：H.264 + AAC，{seconds}）' if seconds else ''))
        left = len(self.render_queue.waiting())
        self.message(('样片' if task.kind == 'sample' else '视频') + '已导出并检查可以播放，可以播放成品或打开文件夹。' + note
                     + (f'队列中还有 {left} 个任务。' if left else ''))

    def _render_changed(self, task):
        if task.state == 'running' and hasattr(self, 'progress'):
            self.progress.setValue(round(task.ratio * 100))
            if task.ratio > 0:
                left = len(self.render_queue.waiting())
                self.message(f'正在压制 {task.label} {task.ratio:.0%}' + (f' · 预计剩余 {task.remaining:.0f} 秒' if task.remaining is not None else '')
                             + (f' · 队列中还有 {left} 个' if left else ''))
        self.refresh_render_list()

    def refresh_render_list(self):
        if not hasattr(self, 'render_list'): return
        selected = self.render_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.render_list.currentItem() else None
        self.render_list.clear()
        for task in self.render_queue.tasks:
            item = QListWidgetItem(task.line()); item.setData(Qt.ItemDataRole.UserRole, task.id); item.setToolTip(task.options.output)
            self.render_list.addItem(item)
            if task.id == selected: self.render_list.setCurrentItem(item)

    def cancel_selected_render(self):
        item = self.render_list.currentItem()
        if item is None: self.message('请先在队列中选择一个任务'); return
        if self.render_queue.cancel(item.data(Qt.ItemDataRole.UserRole)): self.message('正在取消所选压制任务，不会留下半成品。')
        else: self.message('所选任务已经结束。')

    def cancel_renders(self):
        if not self.render_queue.busy: self.message('压制队列中没有进行或等待的任务。'); return
        self.render_queue.cancel_all(); self.message('正在取消压制任务，等待中的任务也已取消。')

    def clear_finished_renders(self):
        count = self.render_queue.clear_finished(); self.refresh_render_list()
        self.message(f'已从列表移除 {count} 个已结束的任务；任务记录仍保留。' if count else '没有已结束的任务。')

    def recover_interrupted_renders(self):
        try: found = self.render_records.recover()
        except OSError: return []
        if found:
            unverified = sum(1 for x in found if x['state'] == 'unverified')
            self.message(f'上次有 {len(found)} 个压制任务没有正常结束，已标记为未完成'
                         + (f'（其中 {unverified} 个成品文件需要播放检查）' if unverified else '') + '，可在任务记录查看。')
        return found
