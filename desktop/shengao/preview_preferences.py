"""Optional local preview/worker choices; independent of project and exports."""
from PySide6.QtCore import QThread,QThreadPool,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QCheckBox,QComboBox,QLabel,QDialogButtonBox,
    QScrollArea,QWidget)


def validate(gpu,workers):
    if type(gpu) is not bool or type(workers) is not int or workers not in (0,1,2,4):raise ValueError('请选择有效的预览与后台任务设置')


def note(text):
    label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);return label


class PreviewPreferencesDialog(QDialog):
    def __init__(self,studio):
        super().__init__(studio);self.studio=studio;self.setWindowTitle('预览与后台设置');self.resize(560,450);self.setMinimumSize(400,340)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll,1)
        layout.addWidget(note('这些是本机可选设置，不修改歌词、工程、输出分辨率或压制编码器。关闭加速仍可使用普通预览。'))
        self.gpu=QCheckBox('允许GPU缩小符合条件的视频帧');self.gpu.setChecked(studio.playback.canvas.gpu_enabled);layout.addWidget(self.gpu)
        layout.addWidget(note('不支持的格式或GPU失败时自动使用常规预览。关闭后立即回到常规路径；重新开启从后续帧生效。此开关不强制更换系统视频解码器。'))
        current=studio.playback.canvas.frame_scaler_status()
        layout.addWidget(note('当前预览：'+(current.get('backend') or '常规预览')+('；GPU不可用，已自动回退。' if current.get('error') else '')))
        layout.addWidget(note('本地后台任务并行数'))
        self.workers=QComboBox()
        for title,count in [('系统默认',0),('1个（减少同时处理）',1),('2个',2),('4个',4)]:self.workers.addItem(title,count)
        self.workers.setCurrentIndex(self.workers.findData(studio.local_worker_limit));layout.addWidget(self.workers)
        layout.addWidget(note('控制本程序普通本地处理任务同时运行的数量，已运行任务继续完成；不限制独立模型进程、FFmpeg内部线程或显卡用量。转录API不受此项影响。'))
        layout.addWidget(note('需要轻量视频时：作品 → 轻量视频预览。先准备并核对再采用，可随时切回原片；转录与最终输出使用原素材。'))
        self.status=note('');layout.addWidget(self.status);layout.addStretch()
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.save_button=controls.button(QDialogButtonBox.StandardButton.Save);self.save_button.setText('保存并应用');self.save_button.setAutoDefault(False)
        controls.accepted.connect(self.apply);controls.rejected.connect(self.reject);outer.addWidget(controls)

    def apply(self):
        try:self.studio.adopt_preview_preferences(self.gpu.isChecked(),self.workers.currentData())
        except (OSError,ValueError) as error:self.status.setText('未更改，原设置保留：'+str(error));return
        self.accept()


class PreviewPreferencesWorkflow:
    def init_preview_preferences(self):
        saved=self.preferences.data;gpu=saved.get('preview_gpu',True);workers=saved.get('local_worker_limit',0)
        try:validate(gpu,workers)
        except ValueError:gpu,workers=True,0
        self.playback.canvas.set_gpu_enabled(gpu);self.local_worker_limit=workers
        QThreadPool.globalInstance().setMaxThreadCount(workers or max(1,QThread.idealThreadCount()))

    def adopt_preview_preferences(self,gpu,workers):
        validate(gpu,workers)
        if self.closing:raise ValueError('窗口正在关闭，设置未修改')
        self.preferences.set_many({'preview_gpu':gpu,'local_worker_limit':workers})
        self.playback.canvas.set_gpu_enabled(gpu);self.local_worker_limit=workers
        QThreadPool.globalInstance().setMaxThreadCount(workers or max(1,QThread.idealThreadCount()))

    def show_preview_preferences(self):
        dialog=PreviewPreferencesDialog(self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.message('本机预览与后台设置已应用，工程和输出保持。')
