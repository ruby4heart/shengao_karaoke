"""Independent five-stage Qt workstation for Japanese karaoke production."""
from pathlib import Path
import copy
import json
import os
import sys
from PySide6.QtCore import Qt,QTimer,QUrl,QSignalBlocker,QSize,QRect,QEvent,QItemSelectionModel
from PySide6.QtGui import QAction,QKeySequence,QFont,QColor,QDesktopServices,QPixmap,QIcon,QPainter,QImage
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QStackedWidget,QScrollArea,QSplitter,QListWidget,QListWidgetItem,QLineEdit,
    QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTableWidget,QTableWidgetItem,QHeaderView,
    QAbstractItemView,QCheckBox,QSlider,QFileDialog,QMessageBox,QInputDialog,QProgressBar,
    QFormLayout,QTabWidget,QDialog,QColorDialog,QDialogButtonBox,QToolButton,QSizePolicy,QMenu,QStyle)
from studio_backend.model import LyricLine
from studio_backend.settings import default_home,atomic_json
from .project import Project,Style,History,load_project,save_project,file_stamp
from .recovery import RecoveryWriter
from .fonts import bundled_fonts,register_qt_fonts,missing,font_weight,family_name
from .subtitles import compose,layout_issues,_compose_after_edit
from .presentation import display_windows
from .display_ribbon import DisplayTimingRibbon
from .display_timing import change_display
from .playback import Playback
from .timeline import Timeline,stamp
from .timeline_context import PreviousContext
from .timing import set_time,edit_reading,merge_words,split_word,shift_following
from .api_jobs import ApiJob
from . import jobs,media
from .encode import encode,EncodeOptions,capabilities
from .dialogs import LyricsDialog,PauseDialog,ReviewDialog,SettingsDialog,button
from .paths import ROOT,ASSETS
from .theme import STYLE
from .widgets import TimeEdit,StepButton,Collapsible,WelcomePane,LyricDelegate,icon,time_text
from .preferences import Preferences
from .continuity_dialog import ContinuityDialog
from .segmentation_dialog import SegmentationDialog
from .audio_controls import AudioControls
from .tail_dialog import TailDialog
from .tail_model import shift_line
from .time_transform import scope_indices,locked_rows,shift_limits,TimeTransform,transform_project
from .time_correction_dialog import TimeCorrectionDialog
from .match_range_dialog import MatchRangeDialog
from .source_switch import SourceSwitch
from .line_editor import InlineSegmentation,MoraStrip
from .editor_model import missing_mora_indices
from .media_versions import MediaVersion,ROLES
from .draft_workflow import DraftWorkflow
from .recognition_workflow import RecognitionWorkflow
from .vocal_workflow import VocalWorkflow
from .acoustic_workflow import AcousticWorkflow
from .sound_gap_workflow import SoundGapWorkflow
from .chorus_workflow import ChorusWorkflow
from .color_workflow import ColorWorkflow
from .reading_candidates_workflow import ReadingCandidatesWorkflow
from .translation_workflow import TranslationWorkflow
from .song_info_dialog import SongInfoWorkflow
from .mora_editing_widget import MoraEditingWorkflow
from .fine_listening import FineListeningWorkflow
from .issues_workflow import IssuesWorkflow
from .style_workflow import StyleWorkflow
from .proxy_workflow import ProxyWorkflow

def label(text,kind='',wrap=True):
    item=QLabel(text);item.setTextFormat(Qt.TextFormat.PlainText);item.setObjectName(kind);item.setWordWrap(wrap);return item

def vertical(parent=None,margins=14):
    layout=QVBoxLayout(parent);layout.setContentsMargins(margins,margins,margins,margins);layout.setSpacing(10);return layout

class StudioWindow(QMainWindow,SourceSwitch,DraftWorkflow,RecognitionWorkflow,VocalWorkflow,AcousticWorkflow,SoundGapWorkflow,ChorusWorkflow,ColorWorkflow,ReadingCandidatesWorkflow,TranslationWorkflow,SongInfoWorkflow,MoraEditingWorkflow,FineListeningWorkflow,IssuesWorkflow,StyleWorkflow,ProxyWorkflow):
    def __init__(self,home=None,test=False):
        super().__init__();self.home=Path(home) if home else default_home();self.test=test
        self.history=History(Project());self.path=None;self.current=-1;self.stage=0;self.refreshing=False;self.pending=None
        self.preferences=Preferences(self.home);self.last_output='';self.next_callback=None;self._flushing=False
        self.api=ApiJob(self,self.home);self.local_job=None;self.analysis_job=None;self.extra_fonts=[];self.snapshots={}
        self.analysis_generation=0;self.closing=False
        self.init_proxy_workflow()
        self.encoder_capabilities=None;self.capability_job=None
        self._render_snapshot=None;self._render_font_stamp=None;self._render_text=None
        from .subtitles import CompositionCache
        self._composition_cache=CompositionCache()
        self.validation_error=None;self.preview_expanded=False
        self._selected_lyric_ids=set();self._selection_uid=None;self._retain_lyrics=False
        self.setWindowTitle('声稿 · Karaoke Studio');self.setWindowIcon(QIcon(str(ASSETS/'shengao.svg')));self.resize(1460,940);self.setMinimumSize(900,620);self.setAcceptDrops(True)
        register_qt_fonts();self.build()
        from .action_help import explain_buttons
        explain_buttons(self);self.connect_signals();self.shortcuts();self.refresh()
        from .fast_snapshot import enable as enable_fast_snapshot
        self.snapshot_accelerator=enable_fast_snapshot()
        self.recovery_writer=RecoveryWriter(self.recovery_path(),self.recovery_failed)
        self._edited_recovery=None;self.edited_recovery_timer=QTimer(self);self.edited_recovery_timer.setSingleShot(True);self.edited_recovery_timer.setInterval(1000);self.edited_recovery_timer.timeout.connect(self.publish_edited_checkpoint)
        self.autosave=QTimer(self);self.autosave.setInterval(15000);self.autosave.timeout.connect(self.queue_recovery);self.autosave.start()
        self.render_timer=QTimer(self);self.render_timer.setSingleShot(True);self.render_timer.setInterval(100);self.render_timer.timeout.connect(self.render_subtitles)
        if not test:QTimer.singleShot(250,self.offer_recovery)
        saved=self.preferences.data
        volume=saved.get('volume',70)
        if type(volume) is int:self.volume.setValue(max(0,min(100,volume)))
        if type(saved.get('subtitles')) is bool:self.subtitle_toggle.setChecked(saved['subtitles'])
        self.audio_view.setCurrentIndex(0 if saved.get('audio_view','spectrum')=='spectrum' else 1)
        self.timeline.medusa_hotkeys=saved.get('medusa_hotkeys',False) is True
        speed=saved.get('speed',1.)
        if type(speed) in (int,float) and speed in (.5,.75,1.,1.25):self.speed.setCurrentIndex(self.speed.findData(speed))
        self.volume.valueChanged.connect(lambda value:self.preferences.set('volume',value))
        self.speed.currentIndexChanged.connect(lambda _:self.preferences.set('speed',self.speed.currentData()))
        self.subtitle_toggle.toggled.connect(lambda value:self.preferences.set('subtitles',value))
        self.continuous_timing.toggled.connect(lambda value:self.preferences.set('legacy_gap_timing',value))

    @property
    def project(self):return self.history.project
    @property
    def line(self):return self.project.lines[self.current] if 0<=self.current<len(self.project.lines) else None

    def build(self):
        root=QWidget();self.setCentralWidget(root);outer=vertical(root,0)
        header=QFrame();header.setObjectName('header');row=QHBoxLayout(header);row.setContentsMargins(20,10,20,10);row.setSpacing(8)
        row.addWidget(label('声稿','brand',False));self.project_label=label('未命名作品','',False);row.addWidget(self.project_label,1)
        self.project_label.setMaximumWidth(220);self.project_label.setMinimumWidth(0);self.project_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.project_label.setObjectName('projectName');self.save_state=label('尚未保存','saveState',False);row.addWidget(self.save_state)
        project_menu=QMenu(self)
        for title,fn in [('另存工程…',self.save_as),('重命名作品…',self.rename_project),('重新定位媒体…',self.add_media)]:project_menu.addAction(title).triggered.connect(fn)
        project_menu.addSeparator();project_menu.addAction('快速上手',self.show_guide);project_menu.addAction('轻量视频预览…',self.open_proxy_settings)
        project_menu.addAction('新建作品',self.new);self.recent_menu=project_menu.addMenu('最近作品');self.refresh_recent_menu()
        project_button=QPushButton('作品');project_button.setMenu(project_menu);row.addWidget(project_button);row.addStretch()
        self.workflow_toggle=QPushButton('流程');self.workflow_toggle.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown));self.workflow_toggle.setCheckable(True);self.workflow_toggle.setToolTip('展开／收起五步制作流程；默认收起，为视频留出空间。');row.addWidget(self.workflow_toggle)
        self.lyrics_toggle=button('歌词列表',self.toggle_lyrics);row.addWidget(self.lyrics_toggle)
        self.undo_button=button('',self.undo);self.redo_button=button('',self.redo)
        for b,name,tip in [(self.undo_button,'undo','撤销上一步 Ctrl+Z'),(self.redo_button,'redo','重做 Ctrl+Y')]:b.setIcon(icon(name));b.setObjectName('iconButton');b.setToolTip(tip);b.setAccessibleName(tip);row.addWidget(b)
        for text,fn,name in [('打开',self.open_dialog,'folder'),('服务设置',self.settings,'settings'),('保存作品',self.save,'save')]:
            b=button(text,fn);b.setIcon(icon(name,'#ffffff' if name=='save' else '#73829a'));row.addWidget(b)
            if name=='save':b.setObjectName('primary');b.setAccessibleName('保存作品 Ctrl+S')
        outer.addWidget(header)
        self.navigation_panel=QWidget();navigation=QHBoxLayout(self.navigation_panel);navigation.setContentsMargins(14,0,14,0);self.steps=[]
        for i,text in enumerate(['导入素材','生成字幕','校准歌词','调整样式','导出作品']):
            b=StepButton(i,text);b.setChecked(i==self.stage);b.clicked.connect(lambda checked=False,n=i:self.set_stage(n));navigation.addWidget(b,1);self.steps.append(b)
        outer.addWidget(self.navigation_panel);self.workflow_toggle.toggled.connect(self.toggle_workflow)
        self.workflow_toggle.setChecked(self.preferences.data.get('show_workflow',False) is True);self.navigation_panel.setVisible(self.workflow_toggle.isChecked())
        self.workflow_banner=QFrame();self.workflow_banner.setObjectName('workflowBanner');banner=QHBoxLayout(self.workflow_banner);banner.setContentsMargins(14,8,10,8)
        self.next_hint=label('','nextHint');banner.addWidget(self.next_hint,1);self.next_button=button('开始制作',self.next_step);self.next_button.setObjectName('textButton');banner.addWidget(self.next_button);outer.addWidget(self.workflow_banner)
        self.splitter=QSplitter();self.splitter.setChildrenCollapsible(False);self.splitter.setHandleWidth(8)
        left=QFrame();self.left_panel=left;left.setObjectName('card');left.setMinimumWidth(190);left.setMaximumWidth(310);ll=vertical(left,10)
        ll.addWidget(label('歌词与进度','heading'));self.search=QLineEdit();self.search.setPlaceholderText('搜索原文、假名、罗马音');ll.addWidget(self.search)
        self.filter=QComboBox();self.filter.addItems(['全部歌词','时间待确认','读音待确认']);ll.addWidget(self.filter)
        self.lyrics=QListWidget();self.lyrics.setObjectName('lyricsList');self.lyrics.setWordWrap(True);self.lyrics.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.lyrics.setToolTip('单击切句；Ctrl 点选多句，Shift 选择连续多句。右侧“修改范围”决定移动哪些歌词。');ll.addWidget(self.lyrics,1)
        self.lyrics.setItemDelegate(LyricDelegate(self.lyrics));self.lyrics.setSpacing(2)
        # LyricDelegate gives every row the same height, including placeholders.
        # Let Qt derive scrolling from that height without querying every row.
        self.lyrics.setUniformItemSizes(True)
        self.count=label('尚未加入歌词','muted');ll.addWidget(self.count);ll.addWidget(button('＋ 粘贴原歌词',self.paste_lyrics));self.splitter.addWidget(left)
        middle=QFrame();middle.setObjectName('card');middle_layout=vertical(middle,0);self.center_pages=QStackedWidget();middle_layout.addWidget(self.center_pages)
        self.welcome=WelcomePane(self.add_media,self.paste_lyrics,self.open_dialog,self.open_demo);self.welcome.openProject.connect(self.open_recent);self.welcome.set_recent(self.preferences.recent())
        welcome_scroll=QScrollArea();welcome_scroll.setWidgetResizable(True);welcome_scroll.setWidget(self.welcome);welcome_scroll.setMinimumSize(0,0);self.center_pages.addWidget(welcome_scroll)
        workspace=QWidget();workspace.setObjectName('workspace');self.workspace=workspace;ml=vertical(workspace,10);ml.setSpacing(8)
        self.workspace_scroll=QScrollArea();self.workspace_scroll.setWidgetResizable(True);self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame);self.workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.workspace_scroll.setMinimumSize(0,0);self.workspace_scroll.setWidget(workspace);self.center_pages.addWidget(self.workspace_scroll)
        self._center_reveal_widget=None;self._center_reveal_geometry=None;self._center_reveal_attempts=0;self.center_reveal_timer=QTimer(self);self.center_reveal_timer.setSingleShot(True);self.center_reveal_timer.timeout.connect(self.reveal_center_target)
        self.current_text=label('从拖入视频和原歌词开始','heading');current_row=QHBoxLayout();current_row.addWidget(self.current_text,1);self.original_button=button('编辑原歌词',self.edit_original);current_row.addWidget(self.original_button);ml.addLayout(current_row)
        self.current_info=label('新用户可以打开离线练习，不需要 API 密钥。','muted');ml.addWidget(self.current_info)
        self.edit_tools=QWidget();tools_row=QHBoxLayout(self.edit_tools);tools_row.setContentsMargins(0,0,0,0);tools_row.setSpacing(6)
        self.quick_segment=button('① 分词',self.resegment_current);self.quick_reading=button('② 注音',self.go_reading);self.quick_timing=button('③ 调时间',self.go_audio_timing);self.quick_tail=button('尾音细听',self.open_inline_listening)
        for b in [self.quick_segment,self.quick_reading,self.quick_timing,self.quick_tail]:tools_row.addWidget(b,1)
        self.quick_segment.setToolTip('从原歌词划分词组，未匹配也能编辑；点击某字在它前面切分。')
        self.quick_reading.setToolTip('修改汉字的实际假名读音、罗马音与中文译文；不会改写原歌词。')
        self.quick_timing.setToolTip('选择词组或演唱音节，试听并调整起止时间。')
        self.quick_tail.setToolTip('在主编辑区带前音慢放、循环、增强与原声对照；没有选择时定位句尾。另保留独立放大微调窗口。');ml.addWidget(self.edit_tools)
        self.center_split=QSplitter(Qt.Orientation.Vertical);self.center_split.setChildrenCollapsible(False)
        preview_group=QWidget();self.preview_group=preview_group;vl=vertical(preview_group,0)
        self.playback=Playback();self.playback.viewport.setMinimumHeight(280);vl.addWidget(self.playback,1)
        self.preview_tools=QWidget();preview_tools=QHBoxLayout(self.preview_tools);preview_tools.setContentsMargins(0,0,0,0);preview_tools.addWidget(label('视频预览','muted',False))
        self.video_zoom=QComboBox();self.video_zoom.setMinimumContentsLength(6);self.video_zoom.addItem('适合窗口',None)
        for value in [.125,.25,.375,.5,.625,.75,.875,1.,1.25,1.5,2.,3.,4.,10.]:self.video_zoom.addItem(f'{value*100:g}%',value)
        self.video_zoom.setToolTip('在视频上滚轮缩放，每格 12.5%；双击视频恢复适合窗口。');preview_tools.addWidget(self.video_zoom)
        self.video_zoom.currentIndexChanged.connect(lambda _:self.playback.set_zoom(self.video_zoom.currentData()))
        self.playback.zoomChanged.connect(self.update_video_zoom)
        self.large_video=button('放大视频',self.enlarge_video);preview_tools.addWidget(self.large_video);preview_tools.addWidget(self.build_source_switch());self.locate_lyric_button=button('定位唱词',self.locate_lyric_at_playhead);self.locate_lyric_button.setToolTip('按当前播放点选择对应歌词与音节；间奏选择最近句，重叠时优先保留当前句。不改字幕时间。');preview_tools.addWidget(self.locate_lyric_button);preview_tools.addStretch();vl.addWidget(self.preview_tools)
        self.build_proxy_preview_note(vl)
        self.transport_controls=QWidget();transport=QHBoxLayout(self.transport_controls);transport.setContentsMargins(0,0,0,0)
        self.play_button=button('播放',self.playback.toggle);self.play_button.setIcon(icon('play'));transport.addWidget(self.play_button);transport.addWidget(button('试听本句',self.audition_line))
        self.loop=QCheckBox('循环');transport.addWidget(self.loop)
        self.speed=QComboBox()
        for n in [.5,.75,1,1.25]:self.speed.addItem(f'{n:g}×',n)
        self.speed.setCurrentIndex(2);self.speed.setToolTip('慢放保留音高');transport.addWidget(self.speed)
        self.view_choice=QComboBox();self.view_choice.addItems(['视频＋时间轴','只看时间轴','只看视频']);self.view_choice.setToolTip('同时显示时可上下滚动；只看时间轴或视频可扩大对应区域。软件记住每个步骤的选择，调整窗口不会自动切换。');self.view_choice.currentIndexChanged.connect(self.apply_view);self.view_choice.activated.connect(self.remember_view);transport.addWidget(self.view_choice)
        self.subtitle_toggle=QPushButton();self.subtitle_toggle.setIcon(icon('eye'));self.subtitle_toggle.setObjectName('iconButton');self.subtitle_toggle.setCheckable(True);self.subtitle_toggle.setChecked(True);self.subtitle_toggle.setToolTip('显示／隐藏字幕，比较原画面 Ctrl+Shift+P');self.subtitle_toggle.toggled.connect(self.toggle_subtitles);transport.addWidget(self.subtitle_toggle)
        transport.addStretch();self.play_time=label('00:00.00','',False);transport.addWidget(self.play_time);vl.addWidget(self.transport_controls)
        self.seek_controls=QWidget();row=QHBoxLayout(self.seek_controls);row.setContentsMargins(0,0,0,0);self.seek_slider=QSlider(Qt.Orientation.Horizontal);self.seek_slider.setRange(0,0);row.addWidget(self.seek_slider,1)
        self.volume=QSlider(Qt.Orientation.Vertical);self.volume.setRange(0,100);self.volume.setValue(70);self.volume.setToolTip('试听音量');vl.addWidget(self.seek_controls)
        self.center_split.addWidget(preview_group);audio_group=QWidget();self.audio_group=audio_group;al=vertical(audio_group,0)
        row=QHBoxLayout();self.audio_heading=label('音频时间轴','',False);row.addWidget(self.audio_heading);row.addStretch();self.audio_view=QComboBox();self.audio_view.addItem('频谱','spectrum');self.audio_view.addItem('波形','waveform');self.audio_view.setToolTip('切换 Aegisub 原版频谱／波形；不会改变时间或播放位置。');row.addWidget(self.audio_view)
        self.granularity=QComboBox();self.granularity.addItem('调整词组','words');self.granularity.addItem('调整演唱音节','mora');self.granularity.addItem('调整整句','line');row.addWidget(self.granularity)
        row.addWidget(self.build_vocal_tools());row.addWidget(button('显示设置',self.audio_options));row.addWidget(button('定位本句',lambda:self.timeline.focus_line()));al.addLayout(row)
        self.timeline=Timeline();audio_navigation=QHBoxLayout();self.drag_line=QPushButton('拖动整句');self.drag_line.setCheckable(True);self.drag_line.setToolTip('开启后左键拖整句，所有词组一起移动；再次点击恢复逐音边界。也可按 Alt 拖动。');self.drag_line.toggled.connect(self.set_move_mode);audio_navigation.addWidget(self.drag_line)
        self.focus_playhead=button('找播放点',self.timeline.focus_position);self.focus_playhead.setToolTip('把时间轴视图移到当前播放位置，不改变歌词时间。');audio_navigation.addWidget(self.focus_playhead)
        self.focus_selected=button('放大所选',self.timeline.focus_selection);self.focus_selected.setToolTip('放大当前音节附近，便于抓住短音和相邻边界。');audio_navigation.addWidget(self.focus_selected);al.addLayout(audio_navigation)
        self.display_ribbon_toggle=QPushButton('字幕留屏');self.display_ribbon_toggle.setCheckable(True);self.display_ribbon_toggle.setToolTip('显示与原音频同刻度的前／本／后句留屏条；只改字幕出现／消失，不改演唱和音节。');audio_navigation.addWidget(self.display_ribbon_toggle)
        audio_body=QHBoxLayout();self.audio_body_layout=audio_body;audio_body.setContentsMargins(0,0,0,0);audio_body.setSpacing(4);audio_left=QWidget();audio_left.setMinimumWidth(0);left_audio_layout=vertical(audio_left,0);self.previous_context=PreviousContext(self.timeline);self.next_context=PreviousContext(self.timeline,direction=1);left_audio_layout.addWidget(self.previous_context);left_audio_layout.addWidget(self.next_context)
        self.display_ribbon=DisplayTimingRibbon(self.timeline);left_audio_layout.addWidget(self.display_ribbon);self.display_ribbon.hide();left_audio_layout.addWidget(self.timeline,1);audio_body.addWidget(audio_left,1)
        self.display_ribbon_toggle.toggled.connect(self.toggle_display_ribbon);self.display_ribbon.changed.connect(self.adopt_display_ribbon);self.display_ribbon.selected.connect(self.select_display_line);self.display_ribbon.preview.connect(self.preview_display_boundary);self.display_ribbon.notice.connect(self.message)
        self.audio_controls=AudioControls(self.timeline,self.volume);audio_body.addWidget(self.audio_controls);al.addLayout(audio_body,1)
        self.center_split.addWidget(audio_group);self.center_split.setStretchFactor(0,3);self.center_split.setStretchFactor(1,1);self.center_split.setSizes([540,240]);ml.addWidget(self.center_split,1)
        vl.removeWidget(self.seek_controls);vl.removeWidget(self.transport_controls);middle_layout.addWidget(self.seek_controls);middle_layout.addWidget(self.transport_controls);self.splitter.addWidget(middle)
        right=QFrame();self.right_panel=right;right.setObjectName('card');right.setMinimumWidth(310);right.setMaximumWidth(440);rl=vertical(right,0)
        self.pages=QStackedWidget();rl.addWidget(self.pages)
        self.calibrate_footer=button('✓ 确认时间，进入下一句',self.confirm_current);self.calibrate_footer.setObjectName('primary');rl.addWidget(self.calibrate_footer);self.calibrate_footer.hide()
        self.page_layouts=[]
        for _ in range(5):
            scroll=QScrollArea();scroll.setWidgetResizable(True);page=QWidget();page.setObjectName('workspace');layout=vertical(page);scroll.setWidget(page);self.pages.addWidget(scroll);self.page_layouts.append(layout)
        self.build_prepare();self.build_generate();self.build_calibrate();self.build_design();self.build_export()
        self.export_footer=QWidget();footer=vertical(self.export_footer,0);row=QHBoxLayout();self.sample_button=button('先看 12 秒样片',lambda:self.start_encode(True));self.encode_button=button('导出成品视频',lambda:self.start_encode(False));self.encode_button.setObjectName('primary');row.addWidget(self.sample_button);row.addWidget(self.encode_button);footer.addLayout(row)
        self.output_actions=QWidget();actions=QHBoxLayout(self.output_actions);actions.setContentsMargins(0,0,0,0);actions.addWidget(self.play_output_button);actions.addWidget(self.folder_output_button);footer.addWidget(self.output_actions);self.output_actions.hide();rl.addWidget(self.export_footer);self.export_footer.hide();self.splitter.addWidget(right)
        self.splitter.setSizes([230,800,360]);outer.addWidget(self.splitter,1)
        status=QHBoxLayout();status.setContentsMargins(14,0,14,8);self.status=label('准备就绪。可以拖入视频、工程或歌词文件。','muted');self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);status.addWidget(self.status,1)
        self.progress=QProgressBar();self.progress.setFixedWidth(170);self.progress.hide();status.addWidget(self.progress)
        self.cancel_button=button('取消任务',self.cancel_task);self.cancel_button.hide();status.addWidget(self.cancel_button);self.task_button=button('任务记录',self.task_history);status.addWidget(self.task_button);outer.addLayout(status)

    def build_prepare(self):
        l=self.page_layouts[0];l.addWidget(label('先添加素材，再准备歌词','heading'));l.addWidget(label('有正确原歌词时优先粘贴，每行一句。没有原歌词也能先识别，核对文字后再做注音和校轴。','muted'))
        l.addWidget(button('① 添加视频／音频',self.add_media));self.media_label=label('尚未添加媒体','muted');l.addWidget(self.media_label);l.addWidget(label('视频上方一键切换原唱／伴奏；右侧箭头可更换任一版本文件。两个版本共用歌词、注音和时间轴。','muted'))
        self.build_proxy_controls(l)
        l.addWidget(button('② 粘贴原歌词',self.paste_lyrics));l.addWidget(label('不需要提前准备时间标签；识别多出的空格不会改变原歌词。','muted'))
        self.build_recognition_entry(l,prepare=True)
        b=button('素材准备好，生成初稿 →',lambda:self.set_stage(1));b.setObjectName('primary');l.addWidget(b)
        l.addStretch();l.addWidget(label('第一次使用','heading'));l.addWidget(button('打开离线练习',self.open_demo));l.addWidget(label('练习包含合成音频与示例字幕，可以体验校轴、注音、样式和保存，无需联网。','muted'));l.addWidget(button('打开已有工程／ASS',self.open_dialog))

    def build_generate(self):
        l=self.page_layouts[1]
        l.addWidget(label('先做一份可以修改的初稿','heading'))
        l.addWidget(label('原歌词保持原样，结果先由你审核。选一种方式开始。','muted'))
        self.build_recognition_entry(l)
        self.continuous_timing=QCheckBox('按时长收拢（旧方式）');self.continuous_timing.setChecked(self.preferences.data.get('legacy_gap_timing',False) is True)
        self.continuous_timing.setToolTip('高级选项：固定 500 ms 规则可能覆盖真正的短休止。默认关闭；推荐初稿后用“按声音检查空白”。')
        self.continuity_info=label('初稿默认保留间隔。生成后在校轴页按声音检查空白，避免用固定时长填平真正的休止。','muted');l.addWidget(self.continuity_info)
        self.build_draft_workflow(l)
        self.build_chorus_tools(l)
        generation_layout=l;self.single_steps=Collapsible('单独运行某一步（进阶）');l=self.single_steps.body
        l.addWidget(self.continuous_timing)
        l.addWidget(label('不联网，也能开始','sectionTitle'))
        self.segment_button=button('离线生成分词与注音',lambda:self.start_api('segment',mode='mora'));self.segment_button.setObjectName('primary');l.addWidget(self.segment_button)
        l.addWidget(label('使用内置日语词典。时间按句子范围估算，稍后边听边调整。','muted'))
        l.addWidget(label('让识别结果帮助对齐','sectionTitle'))
        self.provider=QComboBox();self.provider.addItem('ElevenLabs · Scribe','elevenlabs');self.provider.addItem('Microsoft AI','mai');l.addWidget(self.provider)
        self.cloud_button=button('联网转录并对齐歌词',lambda:self.start_api('transcribe_match',provider=self.provider.currentData()));l.addWidget(self.cloud_button)
        l.addWidget(label('会上传音轨并使用服务额度。在顶栏“服务设置”填写密钥。','muted'))
        self.more_matching=Collapsible('已有转录／只修正一句')
        self.reuse_button=button('使用已有转录，重新匹配',lambda:self.start_api('match',transcript=self.project.transcript));self.more_matching.body.addWidget(self.reuse_button)
        self.align_button=button('当前句：ElevenLabs 精确对齐',lambda:self.start_api('align',only_current=True,range_mode='selection'));self.more_matching.body.addWidget(self.align_button)
        self.local_match_button=button('当前句：限定时间重新匹配',self.local_match);self.more_matching.body.addWidget(self.local_match_button);l.addWidget(self.more_matching)
        self.more_reading=Collapsible('用 DeepSeek 复核注音与译文')
        self.more_reading.body.addWidget(label('发送歌词和文字依据，不发送音频。特殊唱法仍需试听确认。','muted'))
        self.llm_button=button('复核整首待确认读音',lambda:self.refine_reading(True,False));self.more_reading.body.addWidget(self.llm_button);l.addWidget(self.more_reading)
        generation_layout.addWidget(self.single_steps);l=generation_layout
        self.review_button=button('审核返回的建议',self.review_pending);l.addWidget(self.review_button)
        self.discard_button=button('不采用剩余建议',self.discard_suggestions);self.discard_button.setObjectName('textButton');l.addWidget(self.discard_button)
        l.addStretch();self.go_calibrate_button=button('开始听歌校对 →',lambda:self.set_stage(2));l.addWidget(self.go_calibrate_button)

    def build_calibrate(self):
        l=self.page_layouts[2];l.addWidget(label('本句编辑 · 边听边改','heading'))
        self.build_issue_tools(l)
        row=QHBoxLayout();row.addWidget(button('← 上一句',lambda:self.move_line(-1)));row.addWidget(button('下一句 →',lambda:self.move_line(1)));l.addLayout(row)
        self.pending_line_button=button('下一待确认',lambda:self.next_unconfirmed());self.pending_line_button.setObjectName('textButton');self.pending_line_button.setToolTip('按当前确认内容跳到待确认的时间或读音 Ctrl+J；具体问题见集中疑点清单。');row.addWidget(self.pending_line_button)
        self.segmentation_hint=label('','muted');l.addWidget(self.segmentation_hint);self.resegment_button=self.quick_segment
        row=QHBoxLayout();row.addWidget(label('本次确认','sectionTitle',False));self.confirmation_kind=QComboBox();self.calibration_tabs=self.confirmation_kind
        self.confirmation_kind.addItems(['本句时间','本句读音']);self.confirmation_kind.setToolTip('只决定底部确认按钮的作用；原文、读音和时间始终在同一区域。Aegisub Enter/G 始终提交时间。');row.addWidget(self.confirmation_kind,1);l.addLayout(row)
        self.inline_segment=InlineSegmentation();l.addWidget(self.inline_segment)
        self.units=QTableWidget(0,3);self.units.setObjectName('readingTable');self.units.setHorizontalHeaderLabels(['词组原文','日语假名','罗马音']);self.units.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.units.verticalHeader().hide();self.units.setAlternatingRowColors(True);self.units.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.units.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.units.setFixedHeight(126);l.addWidget(self.units)
        self.change_reading_button=button('直接改假名',self.edit_selected_reading);self.change_reading_button.setToolTip('直接在本句表格里填写实际假名，原文保持；变化的词组会重新估算音节，其他词组保留。')
        self.word_source=label('','muted');row=QHBoxLayout();row.addWidget(self.change_reading_button);row.addWidget(self.word_source,1);l.addLayout(row)
        self.build_reading_candidates(l)
        self.optional_reading=Collapsible('罗马音与中文译文（可选）');self.show_editor_romaji=QCheckBox('显示罗马音列');self.show_editor_romaji.setChecked(self.preferences.data.get('editor_romaji',False) is True);self.optional_reading.body.addWidget(self.show_editor_romaji)
        self.translation=QLineEdit();self.translation.setPlaceholderText('中文译文；可手改或采用 DeepSeek 建议');self.optional_reading.body.addWidget(self.translation)
        self.build_translation_tools(self.optional_reading.body)
        self.show_editor_romaji.toggled.connect(lambda value:(self.units.setColumnHidden(2,not value),self.preferences.set('editor_romaji',value)));self.units.setColumnHidden(2,not self.show_editor_romaji.isChecked())
        self.range_button=button('整句范围',self.select_entire_line);self.range_button.setToolTip('未匹配时先确定唱词范围；已有词组时只改整句头尾，不重新分词。');self.fill_mora_button=button('补全音节',self.fill_missing_mora);row=QHBoxLayout();row.addWidget(label('演唱音节','sectionTitle'),1);row.addWidget(self.fill_mora_button);row.addWidget(self.range_button);l.addLayout(row);self.mora_strip=MoraStrip();l.addWidget(self.mora_strip)
        self.build_fine_listening(l)
        self.build_mora_editing_tools(l)
        self.cleanup_gaps_button=button('检查空白…',self.start_sound_gaps);self.cleanup_gaps_button.setToolTip('按当前试听音轨检查声音连续性与已有音素依据；先试听再处理，不按固定时长填平休止。')
        self.build_acoustic_tools(l,secondary=self.cleanup_gaps_button)
        self.sound_gap_review=button('试听并审核空隙建议',self.review_pending);l.addWidget(self.sound_gap_review)
        self.target=label('当前调整：整句','sectionTitle');l.addWidget(self.target)
        source_row=QHBoxLayout();self.timing_origin_info=label('','muted');source_row.addWidget(self.timing_origin_info,1)
        self.timing_sources_button=button('来源／提示',self.show_timing_sources);self.timing_sources_button.setToolTip('查看本句的字符／词时间、估算音节、歌声候选和人工修改；可试听并直接去校准。');source_row.addWidget(self.timing_sources_button);l.addLayout(source_row)
        self.begin=TimeEdit();self.end=TimeEdit();self.begin.installEventFilter(self);self.end.installEventFilter(self);row=QHBoxLayout()
        for title,field in [('开始时间',self.begin),('结束时间',self.end)]:
            box=QVBoxLayout();box.setSpacing(4);box.addWidget(label(title,'muted'));box.addWidget(field);row.addLayout(box)
        l.addLayout(row);row=QHBoxLayout();row.addWidget(button('应用所选起止',self.apply_spins));row.addWidget(button('试听所选',self.audition_selected));l.addLayout(row)
        row=QHBoxLayout();row.addWidget(button('以播放位置为开始',lambda:self.set_edge_from_playhead(0)));row.addWidget(button('以播放位置为结束',lambda:self.set_edge_from_playhead(1)));l.addLayout(row)
        row=QHBoxLayout();self.reading_confirm=QCheckBox('读音已确认');self.timing_confirm=QCheckBox('时间已确认');row.addWidget(self.reading_confirm);row.addWidget(self.timing_confirm);l.addLayout(row)
        l.addWidget(self.optional_reading)
        self.bulk_timing=Collapsible('整体错位（本句／多句／整首）')
        scope_row=QHBoxLayout();scope_row.addWidget(label('修改范围','sectionTitle',False));self.time_scope=QComboBox()
        for text,key in [('这一句','current'),('选中多句','selected'),('从当前句到结尾','following'),('整首','all')]:self.time_scope.addItem(text,key)
        self.time_scope.setToolTip('整体移动、拖动和漂移校正都使用此范围；音节边界编辑仍只修改当前选择。');scope_row.addWidget(self.time_scope,1);self.bulk_timing.body.addLayout(scope_row)
        self.time_scope_summary=label('','muted');self.bulk_timing.body.addWidget(self.time_scope_summary)
        self.bulk_timing.body.addWidget(label('整体错位先选范围，再移到播放点或提前／延后；内部时长和读音保留。','muted'))
        self.move_to_playhead=button('整句移到播放点',self.move_current_to_playhead);self.move_to_playhead.setToolTip('把本句开始对齐当前播放位置，所有词组和音节一起平移；支持一步撤销。');self.bulk_timing.body.addWidget(self.move_to_playhead)
        self.offset_button=button('整体提前／延后…',lambda:self.correct_timing('offset'));self.offset_button.setToolTip('预览当前范围的新旧时间、提前／延后指定秒数，应用后整次可撤销。');self.bulk_timing.body.addWidget(self.offset_button)
        self.more_correction=Collapsible('逐渐偏移／配错段／整首概览')
        self.drift_button=button('开头对、后面越来越偏…',lambda:self.correct_timing('drift'));self.drift_button.setToolTip('设置两个或更多原字幕位置与实际歌声位置，分段校正字幕时间。');self.more_correction.body.addWidget(self.drift_button)
        self.wrong_segment_button=button('这一段配到了别处…',self.rematch_timing_scope);self.wrong_segment_button.setToolTip('选择实际演唱范围，复用本工程转录重新匹配当前修改范围；先审核，不重新上传。');self.more_correction.body.addWidget(self.wrong_segment_button)
        self.overview_button=button('查看整首时间轴',self.show_song_overview);self.overview_button.setToolTip('缩小时间轴以查看整首；不改变歌词时间。');self.more_correction.body.addWidget(self.overview_button);self.bulk_timing.body.addWidget(self.more_correction)
        self.time_scope.currentIndexChanged.connect(self.update_timing_scope)
        l.addWidget(self.bulk_timing)
        self.extra_timing=Collapsible('微调、空白与字幕留屏')
        self.more_timing=Collapsible('微调与空白时间')
        row=QHBoxLayout();row.addWidget(button('提前 10ms',lambda:self.nudge(-10)));row.addWidget(button('延后 10ms',lambda:self.nudge(10)));self.more_timing.body.addLayout(row)
        self.more_timing.body.addWidget(button('试听并处理空白时间',self.edit_pauses));self.more_timing.body.addWidget(button('只按时长处理空白（高级）',self.cleanup_auto_gaps));self.extra_timing.body.addWidget(self.more_timing)
        self.display_timing=Collapsible('本句字幕出现／消失时间');self.display_timing.body.addWidget(label('只改画面留屏，不改演唱与音节时间。唱完前保持可见。','muted'))
        row=QHBoxLayout();self.display_begin=TimeEdit();self.display_end=TimeEdit();row.addWidget(self.display_begin);row.addWidget(self.display_end);self.display_timing.body.addLayout(row)
        self.display_apply=button('应用本句显示时间',self.apply_display_timing);self.display_apply.setToolTip('修改本句出现和消失时间，演唱轴保持；支持撤销。');self.display_timing.body.addWidget(self.display_apply)
        self.display_reset=button('范围内恢复自动显示',self.reset_display_timing);self.display_reset.setToolTip('按右侧修改范围清除手工留屏时间，重新使用接唱模板；演唱轴保持，可撤销。');self.display_timing.body.addWidget(self.display_reset);self.extra_timing.body.addWidget(self.display_timing)
        l.addWidget(self.extra_timing)
        self.word_tools=Collapsible('单独编辑窗口与词组进阶操作');self.word_tools.body.addWidget(button('单独窗口重新分词…',self.resegment_dialog));self.word_tools.body.addWidget(button('单独窗口修改假名…',self.reading_dialog));self.word_tools.body.addWidget(button('拆分所选词组…',self.split_selected));self.word_tools.body.addWidget(button('合并选中的相邻词组',self.merge_selected));l.addWidget(self.word_tools)
        self.reading_tools=Collapsible('复核本句读音与译文');self.reading_tools.body.addWidget(button('离线词典复核',lambda:self.refine_reading(False)));self.reading_tools.body.addWidget(button('DeepSeek 复核／翻译',lambda:self.refine_reading(True)));l.addWidget(self.reading_tools)
        self.locked=QCheckBox('锁定本句，保护后续自动处理');l.addWidget(self.locked);l.addStretch()
        self.confirmation_kind.currentIndexChanged.connect(self.update_confirmation_action)
        self.inline_segment.selected.connect(self.select_editor_character);self.inline_segment.pendingChanged.connect(self.segmentation_pending_changed);self.inline_segment.applyRequested.connect(self.apply_inline_segmentation)
        self.mora_strip.selected.connect(self.select_editor_mora);self.mora_strip.audition.connect(self.audition_editor_mora);self.units.cellClicked.connect(self.editor_word_clicked);self.timing_confirm.toggled.connect(self.set_timing_confirmed)

    def build_design(self):
        l=self.page_layouts[3];l.addWidget(label('用这首歌选择样式','heading'));l.addWidget(label('中央预览使用实际字体和最终字幕渲染器。选择模板后可以继续调整。','muted'))
        self.compatibility=label('','nextHint');l.addWidget(self.compatibility)
        rolling=button('应用双行接唱 · 日式注音',lambda:self.apply_preset(2));rolling.setObjectName('primary');l.addWidget(rolling)
        l.addWidget(label('上左、下右交替；汉字上方显示假名。下一句提前出现，演唱高亮仍跟随原来的音节时间。','muted'))
        self.display_mode=QComboBox();self.display_mode.addItem('逐句显示','single');self.display_mode.addItem('双行接唱 · 上下交替','alternating');l.addWidget(self.display_mode)
        self.display_mode.currentIndexChanged.connect(lambda _:self.set_style('display_mode',self.display_mode.currentData()))
        self.display_summary=label('','muted');l.addWidget(self.display_summary)
        self.display_axis_button=button('在时间轴调整出现／消失',self.open_display_ribbon);self.display_axis_button.setToolTip('展开本句及前后句的字幕留屏条，拖动后一次采用；保持演唱、音节、读音和确认，Ctrl+Z撤销。');l.addWidget(self.display_axis_button)
        self.presentation_options=Collapsible('调整接唱速度与光晕');form=QFormLayout();self.presentation_spins={}
        for name,title,maximum,factor,suffix in [('preview_percent','唱到多少时提示下一句',90,1,' %'),('previous_hold_ms','下句出现后保留上句',15,1000,' 秒'),('preview_lead_ms','最多提前显示',15,1000,' 秒'),('glow','演唱光晕',12,1,'')]:
            spin=QDoubleSpinBox();spin.setRange(10 if name=='preview_percent' else 0,maximum);spin.setDecimals(0 if factor==1 else 1);spin.setSingleStep(5 if name=='preview_percent' else .5 if factor==1000 else 1);spin.setSuffix(suffix)
            spin.valueChanged.connect(lambda value,n=name,f=factor:self.set_style(n,round(value*f) if n!='glow' else value));form.addRow(title,spin);self.presentation_spins[name]=(spin,factor)
        self.presentation_options.body.addLayout(form);self.presentation_options.body.addWidget(label('短句会缩短保留时间给下一句让位；间奏会清屏。持续演唱的句子不会提前消失。','muted'));l.addWidget(self.presentation_options)
        self.preset_buttons=[];self.preset_indices=[2,3]
        for i,text in zip(self.preset_indices,['日式接唱 · 特粗明朝','清晰注音 · 高可读粗黑体']):
            b=QToolButton();b.setObjectName('fontCard');b.setText(text);b.setToolTip('应用此字体和排版；下方可继续调整，支持撤销。');b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon);b.setIconSize(QSize(240,80));b.setMinimumHeight(112);b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);b.clicked.connect(lambda checked=False,n=i:self.apply_preset(n));self.preset_buttons.append(b);l.addWidget(b)
        self.cards_key=None;self.cards_renderer=None
        self.build_style_workbench(l)
        self.build_proxy_controls(l)
        l.addWidget(label('字体推荐与缺字检查'));self.font_role=QComboBox();self.font_role.addItems(['原文与罗马音','假名注音','中文译文']);l.addWidget(self.font_role)
        self.font_choice=QComboBox();self.font_choice.setMinimumContentsLength(12);self.font_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for font in bundled_fonts():self.font_choice.addItem(font.kind+' · '+font.family,font)
        l.addWidget(self.font_choice);self.font_coverage=label('','muted');l.addWidget(self.font_coverage);l.addWidget(button('添加本地字体文件',self.add_font))
        form=QFormLayout();self.style_spins={}
        for name,title,minimum,maximum in [('size','原文字号',8,180),('ruby_size','假名字号',8,100),('romaji_size','罗马音字号',8,100),('translation_size','译文字号',8,100),('bottom','底部留白',0,400)]:
            spin=QSpinBox();spin.setRange(minimum,maximum);self.style_spins[name]=spin;form.addRow(title,spin);spin.valueChanged.connect(lambda value,n=name:self.set_style(n,value))
        l.addLayout(form)
        self.position_choice=QComboBox();self.position_choice.addItem('画面下方','bottom');self.position_choice.addItem('画面中间','center');self.position_choice.addItem('画面上方','top');l.addWidget(self.position_choice);self.position_choice.currentIndexChanged.connect(lambda _:self.set_style('position',self.position_choice.currentData()))
        form=QFormLayout();self.style_decimals={}
        for name,title in [('outline','描边粗细'),('shadow','阴影距离')]:
            spin=QDoubleSpinBox();spin.setRange(0,12);spin.setSingleStep(.5);self.style_decimals[name]=spin;form.addRow(title,spin);spin.valueChanged.connect(lambda value,n=name:self.set_style(n,value))
        l.addLayout(form)
        row=QHBoxLayout();row.addWidget(button('文字颜色',lambda:self.choose_color('color')));row.addWidget(button('高亮颜色',lambda:self.choose_color('highlight')));row.addWidget(button('描边颜色',lambda:self.choose_color('outline_color')));l.addLayout(row)
        self.build_color_tools(l)
        self.build_song_info_tools(l)
        self.style_checks={}
        for name,title in [('show_ruby','显示假名'),('show_romaji','显示罗马音'),('show_translation','显示译文')]:
            check=QCheckBox(title);self.style_checks[name]=check;l.addWidget(check);check.toggled.connect(lambda value,n=name:self.set_style(n,value))
        l.addWidget(label('字号按 1080p 设计，导出时随画面缩放。','muted'));l.addStretch();l.addWidget(button('检查并导出 →',lambda:self.set_stage(4)))

    def build_export(self):
        l=self.page_layouts[4];l.addWidget(label('先看样片，再生成成品','heading'));l.addWidget(label('工程用于继续编辑；ASS 用于字幕交付；成品视频会把字幕直接烧进画面。','muted'))
        l.addWidget(button('检查时间、读音与排版',self.check_project));self.issue_summary=label('','muted');l.addWidget(self.issue_summary);self.export_issues=QListWidget();self.export_issues.setWordWrap(True);self.export_issues.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.export_issues.setMinimumHeight(130);l.addWidget(self.export_issues)
        l.addWidget(button('前往处理所选项',lambda:self.goto_issue(self.export_issues.currentItem()) if self.export_issues.currentItem() else None))
        row=QHBoxLayout();row.addWidget(button('保存作品',self.save));row.addWidget(button('导出字幕文件…',self.export_ass));l.addLayout(row)
        l.addWidget(label('ASS 保留卡拉 OK 高亮；也可导出 SRT 或纯歌词。','muted'))
        self.output_size=QComboBox();self.output_size.addItem('分辨率跟随原视频','source');self.output_size.addItem('1920 × 1080','1080p');self.output_size.addItem('1280 × 720','720p');l.addWidget(self.output_size)
        self.quality=QComboBox();self.quality.addItem('标准画质 · 6 Mbps','standard');self.quality.addItem('较高画质 · 12 Mbps','high');l.addWidget(self.quality)
        self.encoder=QComboBox();self.encoder.addItem('CPU 编码 · H.264 / AAC','cpu');self.encoder.addItem('显卡编码 · 需要硬件与驱动支持','hardware');l.addWidget(self.encoder)
        self.output_label=label('输出帧率跟随原视频。压制在后台运行，工程可以继续编辑；任务使用开始时的工程快照。','muted');l.addWidget(self.output_label);l.addStretch()
        row=QHBoxLayout();self.play_output_button=button('播放成品',lambda:self.open_last_output(False));self.folder_output_button=button('打开文件夹',lambda:self.open_last_output(True));row.addWidget(self.play_output_button);row.addWidget(self.folder_output_button);l.addLayout(row)

    def connect_signals(self):
        self.search.textChanged.connect(self.refresh_lyrics);self.filter.currentIndexChanged.connect(self.refresh_lyrics)
        self.filter.currentIndexChanged.connect(lambda index:self.calibration_tabs.setCurrentIndex(index-1) if index in (1,2) else None)
        self.lyrics.currentRowChanged.connect(self.choose_list);self.speed.currentIndexChanged.connect(lambda _:self.playback.set_rate(self.speed.currentData()))
        self.playback.temporaryChanged.connect(self.update_play_button)
        self.lyrics.itemSelectionChanged.connect(self.lyric_selection_changed)
        self.lyrics.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.lyrics.customContextMenuRequested.connect(self.lyric_menu)
        self.seek_slider.sliderMoved.connect(self.playback.seek);self.volume.valueChanged.connect(lambda v:self.playback.audio.setVolume(v/100))
        self.playback.positionChanged.connect(self.position_changed);self.playback.durationChanged.connect(lambda v:self.seek_slider.setMaximum(v));self.playback.error.connect(self.message)
        self.playback.player.playbackStateChanged.connect(lambda state:(setattr(self.timeline,'playing',state.name=='PlayingState'),self.timeline.update()))
        self.timeline.seek.connect(self.playback.seek);self.timeline.audition.connect(lambda a,b:self.playback.audition(a,b,self.loop.isChecked()));self.timeline.select.connect(self.select_target);self.timeline.boundary.connect(self.change_boundary);self.timeline.shifted.connect(self.change_following)
        self.timeline.action.connect(self.audio_action)
        self.timeline.moved.connect(self.move_current_line);self.timeline.notice.connect(self.message)
        self.timeline.viewChanged.connect(self.preview_scope_drag)
        self.previous_context.selected.connect(self.select_previous_segment)
        self.previous_context.audition.connect(lambda a,b:self.playback.audition(a,b,self.loop.isChecked()))
        self.next_context.selected.connect(self.select_next_segment);self.next_context.audition.connect(lambda a,b:self.playback.audition(a,b,self.loop.isChecked()))
        self.units.itemSelectionChanged.connect(self.select_table);self.units.cellChanged.connect(self.reading_changed)
        self.translation.textEdited.connect(self.edit_translation);self.translation.editingFinished.connect(self.edit_translation);self.reading_confirm.toggled.connect(self.confirm_reading);self.locked.toggled.connect(self.lock_line)
        self.font_choice.currentIndexChanged.connect(self.font_changed);self.font_role.currentIndexChanged.connect(self.refresh_font_choice)
        self.audio_view.currentIndexChanged.connect(self.change_audio_view)
        self.granularity.currentIndexChanged.connect(self.change_granularity)
        self.api.progress.connect(self.message);self.api.completed.connect(self.api_done);self.api.failed.connect(self.api_failed);self.api.changed.connect(self.busy_changed)
        self.api.workflowChanged.connect(self.show_draft_progress)
        self.export_issues.itemDoubleClicked.connect(self.goto_issue)
        self.loop.toggled.connect(lambda value:setattr(self.playback,'loop',value))
        self.playback.player.playbackStateChanged.connect(self.update_play_button)

    def change_granularity(self):
        self.timeline.granularity=self.granularity.currentData();self.timeline.snap_enabled=self.timeline.granularity=='line';self.timeline.set_line(None,False);self.timeline.set_line(self.line,False);self.refresh_target()
        self.message('整句模式：左键设置开始，右键设置结束；中键定位。Shift 临时关闭吸附。' if self.timeline.granularity=='line' else '卡拉 OK 模式：左键选择／拖动音节，右键试听。默认不额外吸附，10ms 精度。')

    def change_following(self,index,part,boundary,delta):
        if not self.flush_edits():return
        if self.line:
            row=self.current;self.edit('移动此后演唱边界',lambda p:p.lines.__setitem__(row,shift_following(p.lines[row],boundary,delta)))

    def toggle_workflow(self,expanded):
        # Keep the audio region the user is already editing in view while the
        # header changes height. Do not pull a video-focused view down to audio.
        keep_axis=hasattr(self,'timeline') and self.stage==2 and self.timeline.isVisible() and self.timeline.visibleRegion().contains(self.timeline.rect().center())
        self.navigation_panel.setVisible(expanded);self.workflow_toggle.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp if expanded else QStyle.StandardPixmap.SP_ArrowDown));self.preferences.set('show_workflow',expanded)
        if hasattr(self,'center_split'):self.fit_center_layout()
        if keep_axis:self.reveal_center_widget(self.timeline)

    def go_reading(self):
        if not self.flush_edits():return
        self.set_stage(2);self.calibration_tabs.setCurrentIndex(1)
        if not self.line or not self.line.units:self.message('先点击“① 分词”划分本句，之后即可选择词组并修改假名。')
        elif self.edit_selected_reading():self.message('直接填写所选词组的假名；只有变化的词组重估音节，其他人工数据保留。')

    def show_editor_widget(self,widget):
        if self.stage!=2:self.set_stage(2)
        self.pages.widget(2).ensureWidgetVisible(widget,8,20)

    def resegment_current(self):
        if not self.flush_edits(allow_segmentation=True) or not self.line:return
        if self.line.locked:self.message('本句已锁定，请先解除锁定。');return
        if self.stage!=2:self.set_stage(2)
        self.inline_segment.mode.setChecked(True);self.show_editor_widget(self.inline_segment)
        self.message('直接点击原文增加或合并分界；先预览，再应用，不打开新窗口。')

    def edit_selected_reading(self):
        if not self.flush_edits() or not self.line:return
        if not self.line.units:self.resegment_current();self.message('先在本句设置整句范围并分词，再填写实际假名。');return
        index=self.timeline.word if 0<=self.timeline.word<len(self.line.units) else 0
        if self.line.locked or self.line.units[index].locked:self.message('所选词组已锁定，请选择其他词组或解除锁定。');return
        self.calibration_tabs.setCurrentIndex(1);self.select_target(index,-1);self.show_editor_widget(self.units)
        self.units.setCurrentCell(index,1);self.units.setFocus();self.units.editItem(self.units.item(index,1));return True

    def select_editor_character(self,position):
        if not self.line or not self.flush_edits():return
        cursor=0
        for index,unit in enumerate(self.line.units):
            if cursor<=position<cursor+len(unit.text):self.select_target(index,-1);self.seek_selection_preview();self.edit_selected_reading();return
            cursor+=len(unit.text)
        self.resegment_current()

    def editor_word_clicked(self,row,col):
        if not self.line or not 0<=row<len(self.line.units) or self.inline_segment.pending:return
        if self.timeline.granularity=='line':self.granularity.setCurrentIndex(self.granularity.findData('words'))
        self.select_target(row,-1);self.seek_selection_preview()
        if col==0:self.edit_selected_reading()

    def select_editor_mora(self,index,part):
        if not self.flush_edits() or not self.line or not 0<=index<len(self.line.units):return
        if part>=len(self.line.units[index].highlights) or part<-1:self.message('读音或音节已变化，请重新选择音节。');return
        self.drag_line.setChecked(False);self.calibration_tabs.setCurrentIndex(0);self.granularity.setCurrentIndex(self.granularity.findData('mora' if part>=0 else 'words'));self.select_target(index,part);self.timeline.focus_selection();self.seek_selection_preview();self.show_editor_widget(self.target);self.show_audio_axis();return True

    def audition_editor_mora(self,index,part):
        if self.select_editor_mora(index,part):self.audition_selected()

    def seek_selection_preview(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.line and self.playback.player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState:self.playback.seek(self.selected_times()[0])

    def locate_lyric_at_playhead(self):
        if not self.flush_edits() or not self.project.lines:return
        position=self.playback.canvas.position;rows=self.project.lines
        active=[i for i,line in enumerate(rows) if line.start<=position<line.end]
        if self.current in active:index=self.current
        elif active:index=max(active,key=lambda i:rows[i].start)
        else:index=min(range(len(rows)),key=lambda i:(min(abs(position-rows[i].start),abs(position-rows[i].end)),i!=self.current,i))
        self.current=index;self._selected_lyric_ids={self.line.id};self.refresh(False)
        values=self.timeline.reference_segments(self.line)
        value=next((part for part in values if part[2]<=position<part[3]),None)
        if value is None and values:value=min(values,key=lambda part:min(abs(position-part[2]),abs(position-part[3])))
        word,part=(value[0],value[1]) if value else (-1,-1)
        self.drag_line.setChecked(False)
        self.calibration_tabs.setCurrentIndex(0);self.granularity.setCurrentIndex(self.granularity.findData('mora' if part>=0 else 'words' if word>=0 else 'line'))
        self.set_stage(2);self.select_target(word,part);self.timeline.focus_selection();self.show_editor_widget(self.target)
        self.message('已按播放点选中对应歌词与音节，字幕时间保持不变。')

    def select_entire_line(self):
        if not self.flush_edits():return
        self.drag_line.setChecked(False);self.calibration_tabs.setCurrentIndex(0);self.granularity.setCurrentIndex(self.granularity.findData('line'));self.select_target(-1,-1);self.timeline.focus_line();self.show_editor_widget(self.target)

    def segmentation_pending_changed(self,pending):
        if pending:self.timeline.cancel_drag()
        self.update_workflow()

    def fill_missing_mora(self):
        if not self.flush_edits() or not self.line:return
        self.inline_segment.propose_mora();self.show_editor_widget(self.inline_segment)

    def apply_inline_segmentation(self,candidate,expected,uid):
        if not self.flush_edits(allow_segmentation=True):return
        old_units=expected.get('units',[]);old_word,old_part=self.timeline.word,self.timeline.part
        cursor=sum(len(unit['text']) for unit in old_units[:old_word]) if 0<=old_word<len(old_units) else 0
        reading_changed=[(unit.text,unit.kana,unit.romaji) for unit in candidate.units]!=[(unit['text'],unit.get('kana',''),unit.get('romaji','')) for unit in expected.get('units',[])]
        def apply(project):
            if project.uid!=uid:raise ValueError('工程已切换，请重新预览分词')
            row=next((i for i,line in enumerate(project.lines) if line.id==expected['id']),None)
            if row is None or project.lines[row].to_dict()!=expected:raise ValueError('原句已修改，请重新预览；没有覆盖人工数据')
            result=copy.deepcopy(candidate)
            defaults=project.reading_preferences.get('romaji')
            if defaults is not None:
                from studio_backend.romanization import apply_rules
                previous=set();offset=0
                for old in old_units:previous.add((offset,offset+len(old['text'])));offset+=len(old['text'])
                fresh=[];offset=0
                for index,unit in enumerate(result.units):
                    if (offset,offset+len(unit.text)) not in previous:fresh.append(index)
                    offset+=len(unit.text)
                result=apply_rules(result,fresh,defaults)['line']
            project.lines[row]=result
            if reading_changed:project.checks.setdefault(candidate.id,{})['reading']=False
            project.source_ass_active=False
        if self.edit('应用本句分词预览' if reading_changed else '补全估算音节',apply):
            self.inline_segment.reset();self.calibration_tabs.setCurrentIndex(1 if reading_changed else 0);self.granularity.setCurrentIndex(self.granularity.findData('mora' if any(u.highlights for u in candidate.units) else 'words'))
            offset=0
            for index,unit in enumerate(candidate.units):
                if offset<=cursor<offset+len(unit.text):
                    part=old_part if 0<=old_word<len(old_units) and unit.text==old_units[old_word]['text'] and 0<=old_part<len(unit.highlights) else -1
                    self.select_target(index,part);break
                offset+=len(unit.text)
            self.message('本句分词已应用，其他词组的人工数据保留；直接改假名或点音节调时间。Ctrl+Z 一步撤销。' if reading_changed else '已补充估算音节，读音、词组时间和已有人工音节保留；请试听校准，可一步撤销。')

    def refresh_inline_editor(self):
        if not hasattr(self,'inline_segment') or getattr(self,'_inline_refreshing',False):return
        self._inline_refreshing=True
        try:
            line=self.line;self.inline_segment.raw_ass=self.project.source_ass_active;self.inline_segment.set_line(line,self.project.uid,self.timeline.word)
            pending=self.inline_segment.pending;self.timeline.editing_enabled=not pending
            for widget in (self.units,self.mora_strip,self.begin,self.end,self.range_button,self.bulk_timing,self.extra_timing,self.optional_reading,self.word_tools,self.reading_tools,self.reading_confirm,self.timing_confirm,self.locked):widget.setEnabled(bool(line and not pending))
            self.change_reading_button.setEnabled(bool(line and line.units and not line.locked and not pending and not line.units[max(0,min(self.timeline.word,len(line.units)-1))].locked))
            self.calibrate_footer.setEnabled(bool(line and not pending))
            missing=sum(not unit.highlights for unit in line.units) if line else 0;eligible=len(missing_mora_indices(line))
            self.fill_mora_button.setVisible(bool(missing));self.fill_mora_button.setEnabled(bool(eligible and not pending))
            self.fill_mora_button.setToolTip(f'{eligible} 个未锁定词组可按已有假名与范围均分音节，先预览；属于估算，需要试听。已有人工音节保持。'+(f' {missing-eligible} 个词组缺有效假名、范围过短或已锁定。' if missing>eligible else ''))
            if pending:
                self.next_hint.setText('本句编辑仍在预览：请先应用或取消预览。');self.next_button.hide()
                for widget in (self.draft_button,self.draft_resume_button,self.segment_button,self.cloud_button,self.align_button,self.reuse_button,self.local_match_button,self.llm_button,self.sample_button,self.encode_button):widget.setEnabled(False)
        finally:self._inline_refreshing=False

    def set_timing_confirmed(self,value):
        if self.refreshing or not self.line:return
        if not self.flush_edits():return
        row=self.current
        def apply(project):
            line=project.lines[row];line.reviewed=value
            if value:
                from studio_backend.provenance import preserve_before_confirmation
                preserve_before_confirmation(line)
                for unit in line.units:
                    unit.source='manual'
                    for part in unit.highlights:part.source='manual'
        self.edit('确认本句时间' if value else '标记时间待确认',apply)

    def go_audio_timing(self):
        if not self.flush_edits():return
        self.drag_line.setChecked(False)
        self.set_stage(2);self.calibration_tabs.setCurrentIndex(0)
        mode='mora' if self.line and any(u.highlights for u in self.line.units) else 'words'
        self.granularity.setCurrentIndex(self.granularity.findData(mode));self.timeline.focus_line();self.timeline.setFocus();self.show_editor_widget(self.target);self.show_audio_axis()

    def reading_dialog(self):
        if not self.flush_edits() or not self.line:return
        index=self.timeline.word
        if not 0<=index<len(self.line.units):
            if not self.line.units:self.message('本句尚未分词，请先点击“① 分词”。');return
            index=0
        word=self.line.units[index]
        if self.line.locked or word.locked:self.message('所选词组已锁定，请先解除锁定。');return
        dialog=QInputDialog(self);dialog.setWindowTitle('修改所选词组假名');dialog.setLabelText(f'原词组：{word.text}\n填写实际唱出的日语假名，例如 きょう。罗马音会跟随更新。');dialog.setTextValue(word.kana);dialog.setOkButtonText('应用假名');dialog.setCancelButtonText('取消')
        ok=dialog.exec()==QDialog.DialogCode.Accepted;text=dialog.textValue()
        if ok and text!=word.kana:
            row=self.current;uid=self.line.id
            def apply(p):p.lines[row]=edit_reading(p.lines[row],index,text,defaults=p.reading_preferences.get('romaji'));p.checks.setdefault(uid,{})['reading']=False
            if self.edit('修改词组假名',apply):self.select_target(index,-1)

    def set_move_mode(self,on):
        self.timeline.cancel_drag();self.timeline.move_mode=on
        self.message('范围拖动已开启：左键移动当前修改范围，松开应用；Esc 取消。右侧可选择本句、多句或整首。' if on else '已恢复逐音调整；也可按 Alt 拖动当前修改范围。')

    def timing_indices(self):
        selected=[i for i,line in enumerate(self.project.lines) if line.id in self._selected_lyric_ids]
        return scope_indices(self.project,self.time_scope.currentData(),self.current,selected)

    def timing_scope_title(self,indices):
        key=self.time_scope.currentData()
        if key=='all':return f'整首 {len(indices)} 句'
        if key=='following':return f'第 {indices[0]+1} 句到结尾 · {len(indices)} 句'
        if key=='selected':return f'选中 {len(indices)} 句'
        return f'第 {indices[0]+1} 句'

    def show_song_overview(self):
        if not self.project.lines:return
        self.timeline.focus_range(0,self.project.duration or max(line.end for line in self.project.lines));self.message('正在查看整首时间轴；“定位本句”返回本句，视野缩放不改歌词时间。')

    def apply_display_timing(self):
        if not self.line or not self.flush_edits():return
        self.display_begin.interpretText();self.display_end.interpretText();start,end=self.display_begin.value(),self.display_end.value();row=self.current
        def apply(project):
            line=project.lines[row]
            if line.locked:raise ValueError('本句已锁定，请先解除锁定')
            if project.source_ass_active:raise ValueError('请先选择声稿样式，再设置独立留屏时间')
            if project.duration and end>project.duration:raise ValueError('消失时间不能超出素材结尾')
            line.display_start,line.display_end=start,end
        if self.edit('修改本句显示时间',apply):self.message('已修改本句画面留屏，演唱和音节时间保持；Ctrl+Z 撤销。')

    def toggle_display_ribbon(self,visible):
        self.display_ribbon.setVisible(visible);self.fit_center_layout()

    def reveal_center_widget(self,widget):
        if self.closing:return
        self._center_reveal_widget=widget;self._center_reveal_geometry=None;self._center_reveal_attempts=0;self.center_reveal_timer.start(0)

    def reveal_center_target(self):
        widget=self._center_reveal_widget
        if self.closing or widget is None or not widget.isVisible() or self.center_pages.currentIndex()!=1:self._center_reveal_widget=None;return
        self.workspace_scroll.ensureWidgetVisible(widget,8,12)
        viewport=self.workspace_scroll.viewport();pos=widget.mapTo(viewport,widget.rect().topLeft());rect=widget.rect().translated(pos)
        geometry=(rect.x(),rect.y(),rect.width(),rect.height(),viewport.width(),viewport.height(),self.workspace_scroll.verticalScrollBar().maximum())
        # Showing a splitter pane relays geometry in more than one layout
        # event. Verify a stable full rectangle before dropping the request.
        fully_inside=viewport.rect().contains(rect);ancestor=widget.parentWidget()
        while fully_inside and ancestor is not None and ancestor is not viewport:
            at=widget.mapTo(ancestor,widget.rect().topLeft());fully_inside=ancestor.rect().contains(widget.rect().translated(at));ancestor=ancestor.parentWidget()
        if fully_inside and geometry==self._center_reveal_geometry:self._center_reveal_widget=None;return
        self._center_reveal_geometry=geometry;self._center_reveal_attempts+=1
        if self._center_reveal_attempts<10:self.center_reveal_timer.start(16)
        else:self._center_reveal_widget=None

    def show_audio_axis(self):
        if self.view_choice.currentIndex()==2:self.view_choice.setCurrentIndex(0)
        self.reveal_center_widget(self.timeline)

    def open_display_ribbon(self):
        if not self.line or not self.flush_edits():return
        self.display_ribbon_toggle.setChecked(True);self.view_choice.setCurrentIndex(0);self.timeline.focus_line();self.display_ribbon.setFocus();self.show_audio_axis()
        self.message('拖留屏条的两端只改出现／消失；松开采用、Esc取消、Ctrl+Z撤销。Home／End选择边界，左右键10ms、Shift为100ms；双击查看边界。')

    def select_display_line(self,row):
        if not 0<=row<len(self.project.lines) or not self.flush_edits():return False
        view=(self.timeline.left,self.timeline.span,self.timeline.zoom_level);self.current=row;self._selected_lyric_ids={self.line.id};self.refresh(False)
        self.timeline.left,self.timeline.span,self.timeline.zoom_level=view;self.timeline.invalidate();return True

    def preview_display_boundary(self,row,part):
        if row!=self.current and not self.select_display_line(row):return
        if not 0<=row<len(self.project.lines):return
        window=display_windows(self.project)[row];self.playback.seek(window.start if part=='start' else window.end)
        if self.view_choice.currentIndex()==1:self.view_choice.setCurrentIndex(0)
        self.reveal_center_widget(self.playback)
        self.message(f'正在查看第 {row+1} 句字幕'+('出现' if part=='start' else '消失')+'位置；演唱和音节时间保持。')

    def adopt_display_ribbon(self,row,start,end,part,context):
        if row!=self.current or not self.flush_edits():return
        if self.edit('拖动字幕留屏',lambda p:change_display(p,row,start,end,part=part,context=context)):
            self.playback.seek(start if part!='end' else end)
            self.message(f'第 {row+1} 句字幕留屏已采用；演唱、音节、读音和确认保持。Ctrl+Z一步撤销。')

    def reset_display_timing(self):
        if not self.flush_edits():return
        try:indices=self.timing_indices()
        except ValueError as error:self.message(str(error));return
        def apply(project):
            if locked_rows(project,indices):raise ValueError('范围内包含锁定歌词，请解除锁定或重新选择范围')
            for index in indices:project.lines[index].display_start=project.lines[index].display_end=None
        if self.edit('恢复自动接唱显示',apply):self.message('所选范围已恢复模板显示时间，演唱和音节轴保持；Ctrl+Z 撤销。')

    def rematch_timing_scope(self,only_current=False):
        if not self.flush_edits():return
        if not self.project.transcript:self.message('本工程还没有转录，可先整体移动或手动校轴；生成一次转录后能在此本地重匹配。');return
        try:indices=[self.current] if only_current else self.timing_indices()
        except ValueError as error:self.message(str(error));return
        protected=locked_rows(self.project,indices)
        if protected:self.message('第 '+ '、'.join(str(i+1) for i in protected)+' 句或其中词组已锁定，请先解除锁定。');return
        ids=[self.project.lines[i].id for i in indices];dialog=MatchRangeDialog(self.project,indices,self.playback,self)
        accepted=dialog.exec()==QDialog.DialogCode.Accepted;time_range=dialog.range;dialog.deleteLater()
        if accepted:self.start_api('match',line_ids=ids,transcript=self.project.transcript,match_range=time_range,rematch_confirmed=True)

    def update_timing_scope(self,*args):
        if not hasattr(self,'time_scope_summary'):return
        t=self.timeline;t.move_limits=None;t.move_error='';t.move_scope_label='本句'
        try:
            indices=self.timing_indices();title=self.timing_scope_title(indices);protected=locked_rows(self.project,indices)
            text=title+' · 全部词组和音节一起移动'
            if protected:
                t.move_error='第 '+ '、'.join(str(i+1) for i in protected[:10])+' 句或其中词组已锁定，请先解除锁定或重新选择范围。';text+='\n'+t.move_error
            else:
                try:t.move_limits=shift_limits(self.project,indices)
                except ValueError as error:t.move_error=str(error);text+='\n'+t.move_error
            if self.current not in indices and not t.move_error:t.move_error='当前句不在所选范围内；请点选范围内的一句后拖动，或使用右侧整体校正。'
            t.move_scope_label=title;self.time_scope_summary.setText(text)
            self.move_to_playhead.setText('整句移到播放点' if self.time_scope.currentData()=='current' else '把范围开始移到播放点')
            self.move_to_playhead.setToolTip(f'把{title}的最早开始位置对齐播放点，全部词组和音节一起移动；一步撤销。')
            self.drag_line.setText('拖动整句' if self.time_scope.currentData()=='current' else f'拖动{len(indices)}句')
            self.move_to_playhead.setEnabled(not protected and t.move_limits is not None);self.drag_line.setEnabled(not t.move_error)
            self.offset_button.setEnabled(True);self.drift_button.setEnabled(True)
            self.wrong_segment_button.setEnabled(True);self.overview_button.setEnabled(True)
        except ValueError as error:
            t.move_error=str(error);self.time_scope_summary.setText(str(error));self.move_to_playhead.setEnabled(False);self.drag_line.setEnabled(False);self.offset_button.setEnabled(False);self.drift_button.setEnabled(False)
            self.wrong_segment_button.setEnabled(False);self.overview_button.setEnabled(bool(self.project.lines))

    def preview_scope_drag(self):
        if not hasattr(self,'time_scope'):return
        t=self.timeline;previous=self.project.lines[self.current-1] if self.current>0 else None;following=self.project.lines[self.current+1] if 0<=self.current<len(self.project.lines)-1 else None
        if t.moving is not None:
            try:
                indices=set(self.timing_indices())
                if previous and self.current-1 in indices:previous=shift_line(previous,t.move_delta)
                if following and self.current+1 in indices:following=shift_line(following,t.move_delta)
            except ValueError:pass
        t.previous_line,t.next_line=previous,following
        self.previous_context.refresh();self.next_context.refresh()

    def apply_timing_result(self,result,original,title):
        uid=original.uid;expected={original.lines[row['index']].id:original.lines[row['index']].to_dict() for row in result.rows}
        replacements={result.project.lines[row['index']].id:result.project.lines[row['index']] for row in result.rows}
        def apply(project):
            if project.uid!=uid:raise ValueError('工程已变化，请重新打开校轴工具')
            by_id={line.id:i for i,line in enumerate(project.lines)}
            for key,value in expected.items():
                if key not in by_id or project.lines[by_id[key]].to_dict()!=value:raise ValueError('校轴范围内的歌词已经变化，本次未覆盖，请重新预览')
            for key,value in replacements.items():project.lines[by_id[key]]=copy.deepcopy(value)
        if self.edit(title,apply):
            warning=' '+result.warnings[0] if result.warnings else ''
            self.message(f'已调整 {len(result.rows)} 句，原文和读音保留；Ctrl+Z 整次撤销。'+warning);return True
        return False

    def correct_timing(self,mode):
        if not self.flush_edits():return
        try:indices=self.timing_indices()
        except ValueError as error:self.message(str(error));return
        original=copy.deepcopy(self.project);dialog=TimeCorrectionDialog(original,indices,self.playback,self.timeline,self.timing_scope_title(indices),mode,self)
        accepted=dialog.exec()==QDialog.DialogCode.Accepted;result=dialog.result;dialog.deleteLater()
        if accepted:self.apply_timing_result(result,original,'校正范围时间')

    def move_current_line(self,delta):
        if not self.line or not self.flush_edits():return
        try:result=transform_project(self.project,self.timing_indices(),TimeTransform(offset=int(delta)))
        except ValueError as error:self.message(str(error));return
        self.apply_timing_result(result,self.project,'平移范围时间')

    def move_current_to_playhead(self):
        if not self.line or not self.flush_edits():return
        try:
            indices=self.timing_indices();lower,upper=shift_limits(self.project,indices);first=min(self.project.lines[i].start for i in indices)
            delta=max(lower,round(self.playback.canvas.position/10)*10-first)
            if upper is not None:delta=min(delta,upper)
        except ValueError as error:self.message(str(error));return
        self.move_current_line(delta);self.timeline.focus_line()

    def inspect_tail(self):
        if not self.flush_edits() or not self.line:return
        if self.line.locked or any(u.locked for u in self.line.units):self.message('本句或词组已锁定，请先解除锁定。');return
        if not any(u.highlights for u in self.line.units):self.go_reading();self.message('先点击“① 分词”生成本句音节，或填写词组假名，再使用尾音细听。');return
        row=self.current;uid=self.line.id;snapshot=self.line.to_dict();dialog=TailDialog(self.line,self.playback,self.timeline,self)
        accepted=dialog.exec()==QDialog.DialogCode.Accepted;result=dialog.result_line;dialog.deleteLater()
        if accepted:
            if not self.line or self.line.id!=uid or self.line.to_dict()!=snapshot:self.message('本句已在窗口打开期间发生变化，未覆盖当前内容，请重新打开尾音细听。');return
            changed_reading=any(a.kana!=b.kana for a,b in zip(self.line.units,result.units))
            def apply(p):
                p.lines[row]=result
                if changed_reading:p.checks.setdefault(uid,{})['reading']=False;p.source_ass_active=False
            if self.edit('校准句尾音节',apply):self.message('尾音修改已保存，可一步撤销；请带前音再听一次确认。')

    def cancel_audio(self):
        self.timeline.cancel_drag();self.display_ribbon.cancel();self.playback.stop()

    def change_audio_view(self,*args):
        value=self.audio_view.currentData();self.timeline.show_spectrum=value=='spectrum';self.timeline.cache_key=None;self.timeline.update();self.preferences.set('audio_view',value)

    def update_video_zoom(self,value):
        blocker=QSignalBlocker(self.video_zoom)
        if not value:self.video_zoom.setCurrentIndex(0);return
        index=self.video_zoom.findData(value)
        if index<0:
            if self.video_zoom.itemData(self.video_zoom.count()-1,Qt.ItemDataRole.UserRole+1)=='custom':self.video_zoom.removeItem(self.video_zoom.count()-1)
            self.video_zoom.addItem(f'{value*100:g}%',value);index=self.video_zoom.count()-1;self.video_zoom.setItemData(index,'custom',Qt.ItemDataRole.UserRole+1)
        self.video_zoom.setCurrentIndex(index)

    def enlarge_video(self):
        if not self.preview_expanded:
            self._preview_previous_view=self.view_choice.currentIndex();self.view_choice.setCurrentIndex(2);self.preview_expanded=True;self.left_panel.hide();self.right_panel.hide();self.large_video.setText('恢复制作视图')
        else:
            self.preview_expanded=False;self.view_choice.setCurrentIndex(getattr(self,'_preview_previous_view',0));self.update_workflow();self.large_video.setText('放大视频')

    def resegment_dialog(self):
        if not self.flush_edits() or not self.line:return
        if self.line.locked or any(u.locked for u in self.line.units):self.message('本句或词组已锁定，请先解除锁定。');return
        dialog=SegmentationDialog(self.line,self.playback,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            row=self.current;uid=self.line.id
            def apply(p):p.lines[row]=dialog.result_line;p.checks.setdefault(uid,{})['reading']=False;p.source_ass_active=False
            self.edit('本句重新分词',apply,True);self.calibration_tabs.setCurrentIndex(1);self.set_stage(2)
            self.message('本句分词已更新。可在同一区域改假名或点音节调时间；Ctrl+Z 撤销。')

    def commit_audio(self,reset=False):
        if not self.flush_edits() or not self.line:return
        if self.line.locked:self.message('本句已锁定，请先解除锁定。');return
        row=self.current;end=self.line.end;line_mode=self.timeline.granularity=='line';advance=reset or self.preferences.data.get('audio_next_on_commit',True) is not False
        if reset and line_mode and row+1<len(self.project.lines) and (self.project.lines[row+1].locked or any(u.locked for u in self.project.lines[row+1].units)):
            self.message('下一句已锁定，不能重置其时间。');return
        def apply(p):
            line=p.lines[row];line.reviewed=True
            from studio_backend.provenance import preserve_before_confirmation
            preserve_before_confirmation(line)
            for u in line.units:
                u.source='manual'
                for h in u.highlights:h.source='manual'
            if reset and line_mode and row+1<len(p.lines):
                from .segmentation_dialog import regroup
                following=p.lines[row+1];cursor=0;cuts=[]
                for u in following.units[:-1]:cursor+=len(u.text);cuts.append(cursor)
                p.lines[row+1]=regroup(following,cuts,end,end+3000);p.checks.setdefault(following.id,{})['reading']=False
        self.validation_error=None;self.edit('提交音频时间',apply)
        if self.validation_error:return
        if advance and self.current+1<len(self.project.lines):
            self.current+=1;self.refresh(True)
            if not line_mode:self.audition_selected()
        self.message('已提交时间。Enter／G 按原稿顺序进入下一句；音节模式的 Shift+G 同样保留下一句原时间。')

    def audio_action(self,name):
        if name=='medusa_toggle':
            self.timeline.medusa_hotkeys=not self.timeline.medusa_hotkeys;self.preferences.set('medusa_hotkeys',self.timeline.medusa_hotkeys);self.message('Medusa 小键盘打轴快捷键：'+('开启' if self.timeline.medusa_hotkeys else '关闭'));return
        if name=='toggle':
            from PySide6.QtMultimedia import QMediaPlayer
            if self.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:self.playback.stop()
            else:self.audition_selected()
            return
        if name=='stop':self.playback.stop();return
        if name.startswith('scroll_'):
            self.timeline.left=max(0,self.timeline.left+128*self.timeline.pixel_ms/self.timeline.devicePixelRatioF()*(-1 if name=='scroll_left' else 1));self.timeline.invalidate();return
        if not self.line:return
        a,b=self.selected_times()
        if name in ('next','previous'):
            values=self.timeline.segments();current=next((n for n,v in enumerate(values) if (v[0],v[1])==(self.timeline.word,self.timeline.part)),0)
            target=current+(1 if name=='next' else -1)
            if 0<=target<len(values):self.select_target(values[target][0],values[target][1])
            else:
                old=self.current;self.move_line(1 if name=='next' else -1)
                if self.current!=old:
                    values=self.timeline.segments()
                    if values:v=values[0] if name=='next' else values[-1];self.select_target(v[0],v[1])
            if self.timeline.granularity!='line':self.audition_selected()
            return
        if name in ('confirm','confirm_default'):self.commit_audio(name=='confirm_default');return
        if name=='lead_in':self.change_boundary(-1,-1,max(0,self.line.start-100),self.line.end);return
        if name=='lead_out':self.change_boundary(-1,-1,self.line.start,self.line.end+350);return
        if name.startswith(('length_','start_')):
            delta=10 if 'plus' in name else -10
            values=self.timeline.segments();position=next((n for n,v in enumerate(values) if (v[0],v[1])==(self.timeline.word,self.timeline.part)),0)
            karaoke=self.timeline.granularity!='line' and bool(self.line.units)
            if name.startswith('start_'):
                if karaoke and position==0:return
                lower=(values[position-1][2]+10 if values[position-1][3]==a else values[position-1][3]) if karaoke and position else 0
                self.change_boundary(self.timeline.word,self.timeline.part,max(lower,min(b-10,a+delta)),b)
            else:
                if karaoke and position==len(values)-1:return
                if name.endswith('_shift') and karaoke:self.change_following(self.timeline.word,self.timeline.part,b,delta)
                else:
                    upper=(values[position+1][3]-10 if values[position+1][2]==b else values[position+1][2]) if karaoke and position+1<len(values) else b+10
                    self.change_boundary(self.timeline.word,self.timeline.part,a,max(a+10,min(upper,b+delta)))
            return
        ranges={'line':(self.line.start,self.line.end),'selection':(a,b),'before':(max(0,a-500),a),
                'after':(b,min(self.project.duration or b+500,b+500)),'begin':(a,min(b,a+500)),
                'end':(max(a,b-500),b),'to_end':(a,self.project.duration or b)}
        if name in ranges:
            start,end=ranges[name]
            if end>start:self.playback.audition(start,end,self.loop.isChecked())

    def audio_options(self):
        dialog=QDialog(self);dialog.setWindowTitle('音频显示 · Aegisub 原版参数');dialog.resize(480,340);l=vertical(dialog)
        l.addWidget(label('原版 FFT、频率曲线、Icy Blue 频谱与 Green 波形配色。可以拖动预览和时间轴之间的分隔条调整高度。','muted'))
        form=QFormLayout();quality=QComboBox();quality.addItems(['0 · 基础','1 · 原版默认','2 · 较高时间分辨率','3 · 高时间分辨率','4 · 高频率分辨率','5 · 最高']);quality.setCurrentIndex(self.timeline.quality)
        curve=QComboBox();curve.addItems(['线性 · 原版默认','偏线性','均衡','偏对数','对数']);curve.setCurrentIndex(self.timeline.curve)
        gain=QDoubleSpinBox();gain.setRange(.1,20);gain.setSingleStep(.1);gain.setValue(self.timeline.amplitude)
        zoom=QSpinBox();zoom.setRange(-30,200);zoom.setValue(self.timeline.zoom_level)
        form.addRow('频谱质量',quality);form.addRow('频率映射',curve);form.addRow('波形／频谱增益',gain);form.addRow('水平缩放级别',zoom);l.addLayout(form)
        averages=QCheckBox('波形同时显示最大值与平均值');averages.setChecked(self.timeline.waveform_averages);l.addWidget(averages)
        keyframes=QCheckBox('显示视频关键帧与吸附参考线');keyframes.setChecked(self.timeline.show_keyframes);l.addWidget(keyframes)
        snap=QCheckBox('吸附到关键帧／邻行边界（Shift 暂时关闭）');snap.setChecked(self.timeline.snap_enabled);l.addWidget(snap)
        medusa=QCheckBox('启用 Aegisub Medusa 小键盘快捷键（可在其他编辑框生效）');medusa.setChecked(self.timeline.medusa_hotkeys);l.addWidget(medusa)
        advance=QCheckBox('Enter／G 提交后进入下一句（Aegisub 默认）');advance.setChecked(self.preferences.data.get('audio_next_on_commit',True) is not False);l.addWidget(advance)
        l.addWidget(button('查看 Aegisub 打轴快捷键',self.show_audio_shortcuts))
        l.addWidget(label('鼠标滚轮平移，Ctrl＋滚轮缩放；拖动上方时间刻度平移；右键试听音节，中键定位视频。','muted'))
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);controls.accepted.connect(dialog.accept);controls.rejected.connect(dialog.reject);l.addWidget(controls)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.timeline.quality=quality.currentIndex();self.timeline.curve=curve.currentIndex();self.timeline.amplitude=gain.value();self.timeline.waveform_averages=averages.isChecked();self.timeline.show_keyframes=keyframes.isChecked();self.timeline.snap_enabled=snap.isChecked();self.timeline.set_zoom(zoom.value());self.timeline.invalidate()
            self.timeline.medusa_hotkeys=medusa.isChecked();self.preferences.set('medusa_hotkeys',medusa.isChecked());self.preferences.set('audio_next_on_commit',advance.isChecked())

    def show_audio_shortcuts(self):
        dialog=QDialog(self);dialog.setWindowTitle('Aegisub 3.5.0 · 打轴快捷键');dialog.resize(620,600);layout=vertical(dialog)
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText('光标放在音频时间轴时生效（和 Aegisub Audio 上下文一致）\n\nR：试听整句\nS / 空格：试听所选\nB：试听所选／停止\nH：停止\nQ / W：试听所选前／后 500ms\nE / D：试听所选开头／结尾 500ms\nT：从所选开始一直播放到末尾\nA / F：向左／右滚动 128 像素\n← / Z、→ / X：上一／下一词组或音节，音节模式自动试听\nC / V：整句增加 100ms 引入／350ms 引出\n小键盘 − / +：缩短／延长 10ms\nShift + 小键盘 − / +：同时移动后续内部边界\nEnter / G：提交并顺序进入下一句\nShift+G：提交；整句模式重置下句为 3 秒，音节模式保留原时间\nCtrl+小键盘 *：开关 Medusa 模式\n\nMedusa 开启后，小键盘在主窗口各编辑区生效：\nEnter：提交，5：试听，8：停止\n1 / 3：试听前／后 500ms\n0 / 2：上一／下一音节（整句模式为上一／下一句）\n4 / 6：起点前移／后移 10ms\n7 / 9：缩短／延长 10ms\n\n音节模式不通过这些微调键移动整句的头尾；C/V 或鼠标调整整句范围。\n默认关闭 Medusa，输入假名和数字时不会被小键盘打轴截获。')
        layout.addWidget(text);layout.addWidget(button('关闭',dialog.accept));dialog.exec()

    def shortcuts(self):
        for key,fn in [('Ctrl+S',self.save),('F2',self.save),('Ctrl+Shift+S',self.save_as),('Ctrl+O',self.open_dialog),('Ctrl+N',self.new),('Ctrl+Z',self.undo),('Ctrl+Y',self.redo),('F6',self.audition_line),('Ctrl+Return',self.confirm_next),('Escape',self.cancel_audio),('Ctrl+P',self.playback.toggle),('Ctrl+1',lambda:self.playback.seek(self.line.start) if self.line else None),('Ctrl+2',lambda:self.playback.seek(self.line.end) if self.line else None)]:
            action=QAction(self);action.setShortcut(QKeySequence(key));action.triggered.connect(fn);self.addAction(action)
        for key,fn in [('Ctrl+J',self.next_unconfirmed),('Ctrl+Shift+P',self.subtitle_toggle.toggle)]:
            action=QAction(self);action.setShortcut(QKeySequence(key));action.triggered.connect(fn);self.addAction(action)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.FocusIn and isinstance(obj,QWidget) and hasattr(self,'confirmation_kind') and not self.refreshing:
            if obj in (self.begin,self.end) or self.begin.isAncestorOf(obj) or self.end.isAncestorOf(obj):self.confirmation_kind.setCurrentIndex(0)
            elif isinstance(obj,QLineEdit) and self.units.isAncestorOf(obj):self.confirmation_kind.setCurrentIndex(1)
        if event.type() in (QEvent.Type.KeyPress,QEvent.Type.ShortcutOverride) and self.timeline.medusa_hotkeys and isinstance(obj,QWidget) and (obj is self or self.isAncestorOf(obj)) and obj.window() is self:
            from .aeg_hotkeys import command
            name=command(event,medusa=True)
            if name:
                event.accept()
                if event.type()==QEvent.Type.KeyPress:self.audio_action(name)
                return True
        return super().eventFilter(obj,event)

    def update_play_button(self,*args):
        from PySide6.QtMultimedia import QMediaPlayer
        playing=self.playback.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
        temporary=self.playback.temporary_owner is not None
        self.play_button.setText('停止细听' if temporary else '暂停' if playing else '播放');self.play_button.setIcon(icon('pause' if temporary or playing else 'play'))

    def toggle_subtitles(self,on):
        self.playback.canvas.show_subtitles=on;self.playback.canvas.update()
        self.subtitle_toggle.setToolTip(('隐藏字幕，比较原画面' if on else '显示字幕')+' Ctrl+Shift+P')

    def next_step(self):
        if self.next_callback:self.next_callback()

    def update_confirmation_action(self,*args):
        self.refresh_reading_candidates()
        self.calibrate_footer.setText('✓ 确认读音，继续下一句' if self.calibration_tabs.currentIndex()==1 else '✓ 确认时间，继续下一句')
        self.calibrate_footer.setToolTip('只确认本句假名读音，再找下一句待确认读音。' if self.calibration_tabs.currentIndex()==1 else '只确认本句时间，再找下一句待确认时间；读音需单独确认。')
        if not self.refreshing and hasattr(self,'play_output_button'):self.update_workflow()

    def confirm_current(self):
        if self.calibration_tabs.currentIndex()==0:self.confirm_next();return
        if not self.flush_edits() or not self.line:return
        self.confirm_reading(True)
        if all(self.project.checks.get(line.id,{}).get('reading') for line in self.project.lines):self.message('整首歌的读音已确认，可以检查字幕样式并导出。')
        else:self.next_unconfirmed(reading=True);self.message('本句读音已确认，已进入下一句待确认读音。')

    def refresh_recent_menu(self):
        self.recent_menu.clear();values=self.preferences.recent()
        for value in values:self.recent_menu.addAction(value['title'],lambda checked=False,path=value['path']:self.open_recent(path))
        if not values:self.recent_menu.addAction('还没有最近作品').setEnabled(False)

    def remember_project(self):
        if self.path:self.preferences.remember(self.path,self.project.title)
        self.refresh_recent_menu();self.welcome.set_recent(self.preferences.recent())

    def open_recent(self,path):
        target=Path(path)
        if not target.is_file():self.message('这份作品已移动或删除。点击“打开”选择新的位置。');self.preferences.forget(path);self.refresh_recent_menu();self.welcome.set_recent(self.preferences.recent());return
        if self.path and target.resolve()==self.path.resolve():self.set_stage(2);return
        self.open_path(target)

    def update_workflow(self,dirty=None):
        p=self.project;summary=p.summary();media_ready=bool(p.media and Path(p.media).is_file());has_lines=bool(p.lines);pending=bool(self.pending and self.pending.get('result',{}).get('suggestions'));idle=not self.api.busy
        self.save_state.setText('有未保存修改' if (self.history.dirty if dirty is None else dirty) else '已保存' if self.path else '新作品')
        self.undo_button.setEnabled(bool(self.history.undo_stack));self.redo_button.setEnabled(bool(self.history.redo_stack))
        ready=idle and has_lines and not pending
        self.refresh_recognition()
        self.refresh_acoustic_tools()
        self.refresh_mora_editing()
        self.refresh_fine_listening()
        self.refresh_issue_tools()
        self.refresh_sound_gap_tools()
        self.go_calibrate_button.setVisible(has_lines);self.go_calibrate_button.setEnabled(has_lines)
        for widget in [self.draft_button,self.draft_status,self.draft_resume_button,self.single_steps,self.continuous_timing,self.continuity_info]:widget.setVisible(has_lines)
        self.draft_button.setEnabled(ready and not self.source_job)
        self.draft_resume_button.setEnabled(idle and has_lines and not self.source_job)
        if self._draft_summary and self._draft_summary.get('context',{}).get('project')!=p.uid:
            self._draft_summary=None;self.draft_status.setText('可按步骤生成初稿，或继续此工程上次保存的流程。')
        for b in [self.segment_button,self.llm_button]:b.setEnabled(ready)
        for b in [self.cloud_button,self.align_button]:b.setEnabled(ready and media_ready)
        for b in [self.reuse_button,self.local_match_button]:b.setEnabled(ready and bool(p.transcript))
        self.refresh_chorus_tools()
        self.review_button.setVisible(pending);self.discard_button.setVisible(pending)
        if pending:self.review_button.setText(f'审核 {len(self.pending["result"]["suggestions"])} 行建议')
        if pending and self.pending.get('action')=='sound_gaps':self.review_button.setText(f'审核 {len(self.pending["result"]["gap_report"]["gaps"])} 处声音空隙')
        self.pending_line_button.setEnabled(has_lines)
        self.edit_tools.setVisible(has_lines and self.stage in (1,2,3));self.quick_reading.setEnabled(has_lines);self.quick_timing.setEnabled(has_lines);self.quick_tail.setEnabled(has_lines)
        editable=bool(self.line and not self.line.locked and not any(u.locked for u in self.line.units))
        self.move_to_playhead.setEnabled(editable);self.drag_line.setEnabled(editable)
        self.change_reading_button.setEnabled(bool(editable and self.line.units))
        self.play_output_button.setEnabled(bool(self.last_output and Path(self.last_output).is_file()));self.folder_output_button.setEnabled(self.play_output_button.isEnabled())
        if hasattr(self,'output_actions'):
            self.output_actions.setVisible(self.play_output_button.isEnabled())
            available=bool(media_ready and p.duration>0 and has_lines and not self.local_job)
            self.sample_button.setEnabled(available);self.encode_button.setEnabled(available)
            if not available:
                tip='先添加素材、歌词并等待读取完成；已有导出任务时请等待或取消。'
                self.sample_button.setToolTip(tip);self.encode_button.setToolTip(tip)
            else:self.sample_button.setToolTip('试听／检查当前句附近的 12 秒样片');self.encode_button.setToolTip('将字幕写入完整视频；音频素材使用纯色背景')
        empty=not p.media and not has_lines;self.center_pages.setCurrentIndex(0 if empty else 1)
        if empty and self.stage==0:self.left_panel.hide();self.right_panel.hide()
        elif self.stage==0 or has_lines:self.right_panel.show();self.left_panel.setVisible(has_lines and self.width()>=1180 and self.view_choice.currentIndex()==0)
        if self.preview_expanded:self.left_panel.hide();self.right_panel.hide()
        complete=[media_ready and has_lines,has_lines and all(x.units for x in p.lines),has_lines and summary['timing']==summary['lines'] and summary['readings']==summary['lines'],has_lines and self.stage==4,bool(self.last_output)]
        for b,done in zip(self.steps,complete):b.set_complete(done)
        if not media_ready:text,callback='添加视频或音频',self.add_media
        elif not has_lines:text,callback=('核对识别原文',self.review_recognition) if p.recognition_draft else ('没有歌词？先识别初稿',self.begin_recognition)
        elif pending:text,callback='审核建议',self.review_pending
        elif not all(x.units for x in p.lines):text,callback='生成初稿',lambda:self.set_stage(1)
        elif summary['timing']<summary['lines']:text,callback='去听歌校对',self.go_timing
        elif summary['readings']<summary['lines']:text,callback='检查待确认读音',lambda:self.show_pending_readings()
        elif self.stage<3:text,callback='选择字幕样式',lambda:self.set_stage(3)
        else:text,callback='试压与导出',lambda:self.set_stage(4)
        show_next=True
        if media_ready and has_lines and not pending:
            if self.stage==0:text,callback='下一步：生成字幕',lambda:self.set_stage(1)
            elif self.stage==1 and all(x.units for x in p.lines):text,callback='下一步：检查假名',self.go_reading
            elif self.stage==2:
                if not all(x.units for x in p.lines):text,callback='补全未分词歌词',self.go_missing_segmentation
                elif summary['timing']==summary['lines'] and summary['readings']==summary['lines']:text,callback='下一步：调整样式',lambda:self.set_stage(3)
                elif summary['timing']==summary['lines'] and self.calibration_tabs.currentIndex()==0:text,callback='下一步：检查假名',self.go_reading
                elif summary['readings']==summary['lines'] and self.calibration_tabs.currentIndex()==1:text,callback='下一步：校准时间',self.go_audio_timing
                else:show_next=False
            elif self.stage==3:text,callback='下一步：先看样片',lambda:self.set_stage(4)
            elif self.stage==4 and self.last_output:text,callback='播放成品',lambda:self.open_last_output(False)
        # Resolve visibility before touching the layout. Showing then hiding
        # this button makes the wrapped banner resize the entire workbench on
        # every timing edit, even when the final state is unchanged.
        self.next_button.setText(text+' →');self.next_callback=callback
        self.refresh_inline_editor()
        self.next_button.setVisible(show_next and not self.inline_segment.pending)

    def go_missing_segmentation(self):
        if not self.flush_edits():return
        index=next((n for n,line in enumerate(self.project.lines) if not line.units),None)
        if index is not None:self.current=index;self.refresh(True);self.set_stage(2);self.resegment_current()

    def show_pending_readings(self):
        self.filter.setCurrentIndex(2);self.calibration_tabs.setCurrentIndex(1);self.set_stage(2)
        if self.line and self.project.checks.get(self.line.id,{}).get('reading'):self.next_unconfirmed()

    def go_timing(self):
        self.calibration_tabs.setCurrentIndex(0);self.set_stage(2)
        if self.line and self.line.reviewed:self.next_unconfirmed(reading=False)

    def next_unconfirmed(self,*args,reading=None):
        if not self.flush_edits() or not self.project.lines:return
        if reading is None:reading=self.filter.currentIndex()==2 or self.calibration_tabs.currentIndex()==1
        count=len(self.project.lines)
        candidates=[i for i in [(self.current+offset)%count for offset in range(1,count+1)] if (not self.project.checks.get(self.project.lines[i].id,{}).get('reading') if reading else not self.project.lines[i].reviewed)]
        if not candidates:self.message('本首歌的读音已全部确认。' if reading else '本首歌的时间已全部确认，可以检查样式并导出。');return
        self.current=candidates[0];self.refresh(True);self.set_stage(2)

    def set_edge_from_playhead(self,edge):
        if not self.flush_edits() or not self.line:return
        a,b=self.selected_times();value=int((self.playback.canvas.position+5)//10*10)
        if (edge==0 and value>=b) or (edge==1 and value<=a):self.message('开始须早于结束；先选中要调整的词组，再定位播放位置。');return
        self.change_boundary(self.timeline.word,self.timeline.part,value if edge==0 else a,value if edge==1 else b)

    def discard_suggestions(self):
        self.pending=None;self.save_recovery();self.refresh();self.message('剩余建议未采用。原始结果仍可从任务记录恢复。')

    def open_last_output(self,folder=False):
        path=Path(self.last_output) if self.last_output else None
        if not path or not path.is_file():self.message('成品已移动或删除，请从任务记录查看原路径。');return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))

    def message(self,text):self.status.setText(text);self.status.setToolTip(text)

    def edit(self,title,fn,focus=False,merge_key=None,render_now=False):
        try:
            if self.history.apply(title,fn,merge_key):
                self.finish_history_edit(focus,render_now)
                return True
        except (ValueError,IndexError,KeyError) as error:self.validation_error=str(error);self.message(str(error));return False
        return False

    def finish_history_edit(self,focus=False,render_now=False):
        snapshot=self.history._applied_snapshot
        # The new History candidate is detached and fully validated. Compose
        # before refresh binds it to editable widgets; never retain validation
        # across event-loop turns or reuse it for independent rendering.
        windows=display_windows(self.project) if render_now else None
        error=self.render_subtitles(_snapshot=snapshot,_windows=windows,_after_edit=True) if render_now else None
        self.refresh(focus,_snapshot=snapshot,_windows=windows)
        self.checkpoint_edited_snapshot(snapshot)
        if error:self.message(error)

    def refresh(self,focus=False,*,_snapshot=None,_windows=None):
        from .gui_gc import activity
        activity()
        self.refreshing=True
        try:
            p=self.project;self.current=min(self.current,len(p.lines)-1)
            if self.current<0 and p.lines:self.current=0
            # Only edit() supplies its just-created immutable snapshot. Other
            # callers still observe direct data changes with a fresh snapshot.
            snapshot=p.to_dict() if _snapshot is None else _snapshot;dirty=snapshot!=self.history.saved;self.project_label.setText(p.title);self.project_label.setToolTip(p.title);self.setWindowTitle(p.title+(' *' if dirty else '')+' — 声稿 Karaoke Studio')
            kind='音频 · 成品使用深色背景' if p.has_video is False else f'{p.width} × {p.height}' if p.has_video else '正在读取素材'
            self.media_label.setText((ROLES[p.media_role]+' · '+Path(p.media).name+f'\n{time_text(p.duration)} · '+kind) if p.media else '尚未添加素材')
            self.output_size.setItemText(0,'默认背景 · 1920 × 1080' if p.has_video is False else '分辨率跟随原视频')
            self.refresh_lyrics();line=self.line
            self.original_button.setText('编辑原歌词' if p.lines else '粘贴原歌词')
            self.original_button.setToolTip('修改当前句原文，变化的词组需重新校对，可撤销。' if p.lines else '有正确原歌词时优先粘贴，每行一句；不会采用识别多出的空格。')
            self.current_text.setText(line.text if line else '从拖入视频和原歌词开始')
            self.current_info.setText(f'第 {self.current+1} 句 · {stamp(line.start)} — {stamp(line.end)} · '+('时间已确认' if line.reviewed else '时间待校准') if line else '新用户可以打开离线练习，不需要 API 密钥。')
            if not line and p.media:
                self.current_text.setText('识别原文待确认' if p.recognition_draft else '视频已导入，接着准备歌词')
                self.current_info.setText(f'{len(p.recognition_draft.get("rows",[]))} 句识别文字待核对，尚未加入字幕。' if p.recognition_draft else '有原歌词就粘贴；没有原歌词可以先识别。')
            self.segmentation_hint.setText('未匹配：先定唱词范围，再分词。' if line and line.match.get('status')=='unmatched' else '尚未分词：点击①或直接在原文切分。' if line and not line.units else f'本句 {len(line.units)} 个词组 · 改假名，再点音节校时。' if line else '先加入原歌词。')
            self.resegment_button.setEnabled(bool(line and not line.locked))
            self.timeline.set_neighbors(p.lines[self.current-1] if self.current>0 else None,p.lines[self.current+1] if self.current+1<len(p.lines) and self.current>=0 else None)
            self.timeline.set_line(line,focus);self.previous_context.refresh();self.refresh_table();self.refresh_target()
            self.next_context.refresh()
            translation=line.translation if line else ''
            if self.translation.text()!=translation:self.translation.setText(translation)
            self.translation.setEnabled(bool(line))
            self.reading_confirm.setChecked(bool(line and p.checks.get(line.id,{}).get('reading')));self.timing_confirm.setChecked(bool(line and line.reviewed));self.locked.setChecked(bool(line and line.locked))
            for name,spin in self.style_spins.items():spin.setValue(getattr(p.style,name))
            for name,spin in self.style_decimals.items():spin.setValue(getattr(p.style,name))
            self.position_choice.setCurrentIndex(max(0,self.position_choice.findData(p.style.position)))
            self.display_mode.setCurrentIndex(max(0,self.display_mode.findData(p.style.display_mode)))
            for name,(spin,factor) in self.presentation_spins.items():spin.setValue(getattr(p.style,name)/factor)
            windows=display_windows(p) if _windows is None else _windows
            if line:
                self.display_begin.setValue(windows[self.current].start);self.display_end.setValue(windows[self.current].end)
            self.display_apply.setEnabled(bool(line and not line.locked and not p.source_ass_active))
            self.display_summary.setText((f'本句显示 {time_text(windows[self.current].start)} — {time_text(windows[self.current].end)}\n演唱 {time_text(line.start)} — {time_text(line.end)}' if line else '加入歌词后可预览接唱。'))
            for name,check in self.style_checks.items():check.setChecked(getattr(p.style,name))
            self.compatibility.setVisible(p.source_ass_active);self.compatibility.setText('当前保留原 ASS 的样式与特效。选择声稿模板后使用新的注音排版；原始 ASS 仍保存在工程中。')
            if not p.media:hint='下一步：添加一段视频或音频。也可以先打开离线练习。'
            elif not p.lines:hint='下一步：试听并核对识别原文，再加入歌词。' if p.recognition_draft else '下一步：优先粘贴正确原歌词；没有原歌词时可以先识别初稿。'
            elif self.pending:hint='初稿已返回：请审核建议，再加入工程。'
            elif not any(x.units for x in p.lines):hint='下一步：生成词组、读音和粗轴，然后逐句试听。'
            else:
                s=p.summary();hint=f'{s["lines"]} 句歌词 · 时间确认 {s["timing"]}/{s["lines"]} · 读音确认 {s["readings"]}/{s["lines"]}。'+('可检查样式并试压。' if s['timing']==s['lines'] else '试听当前句，校准后确认并继续。')
            self.next_hint.setText(hint);self.refresh_font_choice()
            self.update_workflow(dirty=dirty)
        finally:self.refreshing=False
        self.update_timing_scope()
        self.refresh_inline_editor()
        self.refresh_media_source()
        self.refresh_vocal_tools()
        self.refresh_proxy_tools()
        self.display_ribbon.set_project(self.project,self.current,windows)
        self.fit_center_layout()
        if hasattr(self,'render_timer'):
            if p is self.project and self.render_unchanged(snapshot):
                self.render_timer.stop()
                if self.stage==3:self.refresh_font_cards()
            else:self.render_timer.start()
        else:self.render_subtitles()
        return windows

    def refresh_lyrics(self,*args):
        if self._retain_lyrics:return
        new_document=self._selection_uid!=self.project.uid
        if new_document:
            self._selected_lyric_ids=set();self._selection_uid=self.project.uid
        if args and not self.refreshing:self._selected_lyric_ids=set()
        valid={line.id for line in self.project.lines};self._selected_lyric_ids.intersection_update(valid)
        if not self._selected_lyric_ids and self.line:self._selected_lyric_ids={self.line.id}
        selected=self.line.id if self.line else None;text=self.search.text().casefold();kind=self.filter.currentIndex()
        blocker=QSignalBlocker(self.lyrics);chosen=-1;visible=[]
        for index,line in enumerate(self.project.lines):
            if text and text not in (line.text+line.kana+line.romaji).casefold():continue
            if kind==1 and line.reviewed:continue
            if kind==2 and self.project.checks.get(line.id,{}).get('reading'):continue
            visible.append((index,line))
        id_role=int(Qt.ItemDataRole.UserRole)+1
        existing=[self.lyrics.item(row).data(id_role) for row in range(self.lyrics.count())]
        reuse=not new_document and existing==[line.id for index,line in visible]
        if not reuse:self.lyrics.clear()
        for row,(index,line) in enumerate(visible):
            state='✓ 时间已确认' if line.reviewed else '○ 待校准'
            display=f'{index+1:02}  {stamp(line.start)}   {state}\n{line.text}'
            if reuse:item=self.lyrics.item(row)
            else:
                item=QListWidgetItem();item.setData(id_role,line.id);self.lyrics.addItem(item)
            # Read actual values, rather than caching model identities. This
            # also repairs direct text/metadata changes without a full reset.
            if item.text()!=display:item.setText(display)
            if item.data(Qt.ItemDataRole.UserRole)!=index:item.setData(Qt.ItemDataRole.UserRole,index)
            if item.toolTip()!=line.text:item.setToolTip(line.text)
            marked=line.id in self._selected_lyric_ids
            if item.isSelected()!=marked:item.setSelected(marked)
            if line.id==selected:chosen=row
        if self.lyrics.currentRow()!=chosen:self.lyrics.setCurrentRow(chosen,QItemSelectionModel.SelectionFlag.NoUpdate)
        self._selected_lyric_ids={self.project.lines[item.data(Qt.ItemDataRole.UserRole)].id for item in self.lyrics.selectedItems() if type(item.data(Qt.ItemDataRole.UserRole)) is int}
        if not self.project.lines:self.lyrics.addItem('这里将显示核对后的歌词。\n\n可以粘贴原歌词，或先识别并核对初稿。')
        self.count.setText(f'共 {len(self.project.lines)} 句 · 显示 {self.lyrics.count() if self.project.lines else 0} 句')
        self.update_timing_scope()

    def lyric_selection_changed(self):
        if self.refreshing:return
        indices=[item.data(Qt.ItemDataRole.UserRole) for item in self.lyrics.selectedItems()]
        self._selected_lyric_ids={self.project.lines[i].id for i in indices if type(i) is int and 0<=i<len(self.project.lines)}
        self.timeline.cancel_drag();self.update_timing_scope()

    def choose_list(self,row):
        if self.refreshing or row<0:return
        item=self.lyrics.item(row);index=item.data(Qt.ItemDataRole.UserRole)
        if index is not None:
            self._retain_lyrics=True
            try:
                if not self.flush_edits():QTimer.singleShot(0,self.refresh_lyrics);return
                self.current=index;self.refresh(True);self.seek_selection_preview()
            finally:self._retain_lyrics=False

    def move_line(self,delta):
        if self.project.lines and self.flush_edits():
            self.current=max(0,min(len(self.project.lines)-1,self.current+delta));self._selected_lyric_ids={self.line.id};self.refresh(True)

    def select_previous_segment(self,index,part):
        if self.current<=0 or not self.flush_edits():return
        self.drag_line.setChecked(False)
        t=self.timeline;view=(t.left,t.span,t.zoom_level);self.current-=1;self._selected_lyric_ids={self.line.id}
        mode='mora' if part>=0 else 'line' if index<0 else 'words'
        self.granularity.setCurrentIndex(self.granularity.findData(mode));self.refresh(False)
        self.calibration_tabs.setCurrentIndex(0);self.set_stage(2);self.select_target(index,part)
        a,b=self.selected_times()
        if a>=view[0] and b<=view[0]+view[1]:t.left,t.span,t.zoom_level=view;t.invalidate()
        self.seek_selection_preview();self.show_editor_widget(self.target)
        self.message('已选中上句音节。可拖边界或修改右侧时间；灰色竖线是下一句开始，时间修改支持撤销。')

    def select_next_segment(self,index,part):
        if self.current+1>=len(self.project.lines) or not self.flush_edits():return
        self.drag_line.setChecked(False)
        t=self.timeline;view=(t.left,t.span,t.zoom_level);self.current+=1;self._selected_lyric_ids={self.line.id}
        self.granularity.setCurrentIndex(self.granularity.findData('mora' if part>=0 else 'line' if index<0 else 'words'));self.refresh(False)
        self.calibration_tabs.setCurrentIndex(0);self.set_stage(2);self.select_target(index,part);self.seek_selection_preview()
        a,b=self.selected_times()
        if a>=view[0] and b<=view[0]+view[1]:t.left,t.span,t.zoom_level=view;t.invalidate()
        self.show_editor_widget(self.target);self.message('已选中下一句对应音节；共用原来的时间刻度，可以直接校准。')

    def lyric_menu(self,position):
        menu=QMenu(self)
        menu.addAction('复制当前句原文',lambda:QApplication.clipboard().setText(self.line.text if self.line else ''))
        menu.addAction('复制全部原歌词',lambda:QApplication.clipboard().setText('\n'.join(line.text for line in self.project.lines)))
        menu.addSeparator();menu.addAction('本句重新分词…',self.resegment_current);menu.addAction('编辑本句原文…',self.edit_original);menu.addAction('删除本句（可撤销）',self.delete_current)
        menu.addAction('粘贴原歌词…',self.paste_lyrics);menu.exec(self.lyrics.mapToGlobal(position))

    def edit_original(self):
        if not self.flush_edits():return
        if not self.line:self.message('请先加入歌词');return
        if self.line.locked:self.message('本句已锁定，请先解除锁定');return
        text,ok=QInputDialog.getMultiLineText(self,'编辑本句原文','保留整句时间与译文。原文改变后会清空本句分词和读音，便于重新制作；可以撤销。',self.line.text)
        if ok and text!=self.line.text:
            if not text.strip():self.message('原文不能为空；删除整句可使用歌词列表右键菜单');return
            row=self.current
            def update(p):
                old=p.lines[row];p.lines[row]=LyricLine(old.id,text,old.start,old.end,translation=old.translation)
                from studio_backend.translation import carry_after_lyric_edit
                carry_after_lyric_edit(old,p.lines[row]);p.checks[old.id]={'reading':False}
            self.edit('修改本句原文',update)

    def delete_current(self):
        if not self.flush_edits():return
        if not self.line:return
        if self.line.locked:self.message('本句已锁定，请先解除锁定');return
        row=self.current;uid=self.line.id
        def delete(p):p.lines.pop(row);p.checks.pop(uid,None)
        self.edit('删除本句',delete,True)

    def rename_project(self):
        text,ok=QInputDialog.getText(self,'重命名作品','作品名称',text=self.project.title)
        if ok and text.strip():self.edit('重命名作品',lambda p:setattr(p,'title',text.strip()))

    def show_guide(self):
        dialog=QDialog(self);dialog.setWindowTitle('快速上手 · 声稿');dialog.resize(700,620);l=vertical(dialog)
        text=QPlainTextEdit();text.setReadOnly(True)
        try:text.setPlainText((ASSETS/'快速开始.txt').read_text(encoding='utf-8'))
        except OSError:text.setPlainText('添加媒体 → 粘贴原歌词 → 生成并审核初稿 → 逐句校准 → 字体与样式 → 试压并导出')
        l.addWidget(text,1);l.addWidget(button('关闭',dialog.accept));dialog.exec()

    def save_as(self):
        previous=self.path;self.path=None
        if not self.save():self.path=previous

    def set_stage(self,index):
        if hasattr(self,'units') and not self.flush_edits():
            for i,b in enumerate(self.steps):b.setChecked(i==self.stage)
            return
        self.stage=index;self.pages.setCurrentIndex(index)
        self.calibrate_footer.setVisible(index==2)
        self.export_footer.setVisible(index==4)
        if self.width()<1180:self.left_panel.hide();self.right_panel.show()
        raw_views=self.preferences.data.get('stage_views',{});preferred=raw_views.get(str(index)) if isinstance(raw_views,dict) else None
        self.view_choice.setCurrentIndex(preferred if type(preferred) is int and preferred in (0,1,2) else 0 if index==2 else 2)
        for i,b in enumerate(self.steps):b.setChecked(i==index)
        if index==2:self.timeline.focus_line()
        if index==3:self.refresh_font_cards()
        if index==4:self.check_project();self.probe_encoders()
        self.update_workflow()
        self.fit_center_layout()

        # Entering calibration is an explicit navigation action. Its saved
        # view can already be selected, so no combo change will reveal audio.
        if index==2 and self.view_choice.currentIndex()!=2:self.reveal_center_widget(self.timeline)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'left_panel') or not hasattr(self,'right_panel'):return
        if self.width()<1180:self.left_panel.hide();self.right_panel.show()
        elif hasattr(self,'view_choice') and self.view_choice.currentIndex()==0:self.left_panel.show();self.right_panel.show()
        if hasattr(self,'play_output_button'):self.update_workflow()
        if hasattr(self,'timeline'):self.fit_center_layout()

    def toggle_lyrics(self):
        if self.width()<1180:
            show=not self.left_panel.isVisible();self.left_panel.setVisible(show);self.right_panel.setVisible(not show)
        else:self.left_panel.setVisible(not self.left_panel.isVisible())

    def apply_view(self):
        if not hasattr(self,'audio_group') or not hasattr(self,'right_panel'):return
        mode=self.view_choice.currentIndex();self.playback.setVisible(mode!=1);self.audio_group.setVisible(mode!=2)
        self.left_panel.setVisible(mode==0 and self.width()>=1180);self.right_panel.show()
        if hasattr(self,'play_output_button'):self.update_workflow()
        self.fit_center_layout()

    def remember_view(self,index):
        if type(index) is not int or index not in (0,1,2):return
        raw=self.preferences.data.get('stage_views',{});views={k:v for k,v in raw.items() if k in {'0','1','2','3','4'} and type(v) is int and v in (0,1,2)} if isinstance(raw,dict) else {}
        views[str(self.stage)]=index;self.preferences.set('stage_views',views)

    def fit_center_layout(self):
        expanded=self.workflow_toggle.isChecked();calibration=self.stage==2;compact=self.height()<700
        self.current_info.setVisible(self.height()>=780 and not (calibration and expanded))
        self.workflow_banner.setVisible(not (calibration and (expanded or self.height()<640)))
        self.transport_controls.setVisible(self.center_pages.currentIndex()==1)
        both=bool(self.timeline.previous_line and self.timeline.next_line)
        shared=self.view_choice.currentIndex()==0 and bool(self.timeline.previous_line or self.timeline.next_line)
        self.previous_context.combined_caption=both;self.previous_context.set_compact(compact or self.height()<900 or both)
        self.next_context.set_compact(compact or self.height()<900 or both,hide_caption=both)
        self.previous_context.refresh();self.next_context.refresh()
        self.audio_group.layout().setSpacing(6 if compact else 10)
        self.timeline.setMinimumHeight(((140 if self.height()<640 else 160) if expanded else 180) if compact else (180 if shared else 222))
        self.preview_tools.setVisible(self.view_choice.currentIndex()!=1)
        self.seek_controls.setVisible(self.center_pages.currentIndex()==1)
        self.audio_heading.setVisible(self.workspace_scroll.viewport().width()>=680)
        # Propagate dynamic lane/height changes through both nested layouts.
        # QSplitter otherwise keeps an old minimum after leaving compact mode.
        audio_left=self.timeline.parentWidget()
        audio_left.layout().setSpacing(2 if both else 10)
        if audio_left.layout():audio_left.layout().invalidate();audio_left.layout().activate()
        audio_left.setMinimumHeight(audio_left.layout().totalMinimumSize().height());audio_left.updateGeometry()
        self.audio_body_layout.invalidate();self.audio_body_layout.activate();self.audio_group.layout().invalidate();self.audio_group.layout().activate();self.audio_group.updateGeometry()
        self.audio_group.setMinimumHeight(self.audio_group.layout().totalMinimumSize().height())
        self.preview_group.layout().invalidate();self.preview_group.updateGeometry()
        self.preview_group.setMaximumHeight(self.preview_group.layout().totalMinimumSize().height() if self.view_choice.currentIndex()==1 else 16777215)
        self.center_split.updateGeometry();self.center_pages.widget(1).updateGeometry();self.center_pages.updateGeometry()
        self.center_pages.parentWidget().layout().invalidate();self.center_pages.parentWidget().updateGeometry()

    def probe_encoders(self):
        if self.encoder_capabilities is not None or self.capability_job:return
        def done(value):
            self.capability_job=None
            if self.closing:return
            self.encoder_capabilities=value
            for index,key in enumerate(['cpu','hardware']):self.encoder.model().item(index).setEnabled(value[key])
            if not value['cpu'] and value['hardware']:self.encoder.setCurrentIndex(1)
            self.output_label.setText('本机编码检查：'+('CPU 可用' if value['cpu'] else 'CPU 不可用')+'；'+('显卡可用' if value['hardware'] else '显卡不可用')+('。音频将生成深色背景的字幕视频。' if self.project.has_video is False else '。输出帧率跟随源视频。'))
        def failed(message):
            self.capability_job=None
            if not self.closing:self.message('编码能力检查未完成：'+message)
        self.capability_job=jobs.run(lambda cancel,progress:capabilities(),done,failed)

    def refresh_table(self):
        blocker=QSignalBlocker(self.units);line=self.line;self.units.setRowCount(len(line.units) if line else 0)
        if not line:return
        from studio_backend.provenance import describe,voice_lookup
        lookup=voice_lookup(line)
        for row,u in enumerate(line.units):
            for col,text in enumerate([u.text,u.kana,u.romaji]):
                item=QTableWidgetItem(text)
                if col==0 or line.locked or u.locked:item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                origin=describe(u,line,row,-1,lookup)
                item.setToolTip(f'{stamp(u.start)} — {stamp(u.end)} · '+origin['title']+'；'+('人工读音' if u.reading_source=='manual' else '读音建议，需试听确认')+'\n'+'\n'.join(origin['detail']+origin['issues']));self.units.setItem(row,col,item)
        if 0<=self.timeline.word<len(line.units):self.units.selectRow(self.timeline.word)

    def select_target(self,index,part):
        if self.timeline.granularity=='mora' and self.line and 0<=index<len(self.line.units) and part<0 and self.line.units[index].highlights:part=0
        self.timeline.word,self.timeline.part=index,part;self.timeline.update();self.refresh_target()
        if index>=0:
            blocker=QSignalBlocker(self.units);self.units.selectRow(index)
            if self.units.item(index,0):self.units.scrollToItem(self.units.item(index,0))

    def select_table(self):
        if self.refreshing:return
        if self.timeline.granularity=='line':return
        row=self.units.currentRow()
        if row>=0:self.select_target(row,-1)

    def selected_times(self):
        line=self.line
        if not line:return 0,0
        i,j=self.timeline.word,self.timeline.part
        if 0<=i<len(line.units):
            value=line.units[i]
            if 0<=j<len(value.highlights):value=value.highlights[j]
            return value.start,value.end
        return line.start,line.end

    def refresh_target(self):
        a,b=self.selected_times();self.begin.setValue(a);self.end.setValue(b)
        i,j=self.timeline.word,self.timeline.part
        text='整句'
        if self.line and 0<=i<len(self.line.units):text=self.line.units[i].text+(f' · 音节 {j+1}' if j>=0 else '')
        self.target.setText('当前调整：'+text)
        if hasattr(self,'timing_origin_info'):
            from studio_backend.provenance import describe,line_summary
            item=self.line.units[i].highlights[j] if self.line and 0<=i<len(self.line.units) and 0<=j<len(self.line.units[i].highlights) else self.line.units[i] if self.line and 0<=i<len(self.line.units) else self.line
            value=describe(item,self.line,i,j) if item else None
            self.timing_origin_info.setText(value['title']+(f'（{len(value["issues"])} 项提示）' if value['issues'] else '') if value else '加入歌词后可查看时间依据')
            self.timing_origin_info.setToolTip('\n'.join([line_summary(self.line),*value['detail'],*value['issues']]) if value else '')
            self.timing_sources_button.setEnabled(bool(item))
        if hasattr(self,'word_source'):
            unit=self.line.units[i] if self.line and 0<=i<len(self.line.units) else None
            self.word_source.setText((('人工读音' if unit.reading_source=='manual' else '读音建议')+f' · {len(unit.highlights)} 音节') if unit else '先选词组或定范围')
            self.word_source.setToolTip('修改假名只重估所选词组，其他人工音节保留；时间来源可在音节上悬停查看。')
        self.refresh_reading_candidates()
        self.refresh_translation_tools()
        if hasattr(self,'mora_strip'):self.mora_strip.set_line(self.line,i,j)
        self.refresh_acoustic_tools()
        self.refresh_mora_editing()
        self.refresh_fine_listening()
        if hasattr(self,'inline_segment'):self.inline_segment.selected_word=i;self.inline_segment.render()

    def show_timing_sources(self):
        if not self.line or not self.flush_edits():return
        from .timing_sources import TimingSourceDialog
        dialog=TimingSourceDialog(self.line,self.playback,self.timeline.word,self.timeline.part,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted or dialog.selection is None:return
        word,part=dialog.selection;self.set_stage(2)
        if word<0:self.select_entire_line()
        else:
            mode='mora' if part>=0 else 'words';self.granularity.setCurrentIndex(self.granularity.findData(mode));self.select_target(word,part)
            self.timeline.focus_selection();self.seek_selection_preview();self.show_editor_widget(self.target)

    def change_boundary(self,index,part,start,end):
        if not self.flush_edits():return
        if self.line:
            try:
                if self.history.apply_line('调整演唱时间',self.current,lambda line:set_time(line,index,start,end,None if part<0 else part)):self.finish_history_edit(render_now=True)
            except (ValueError,IndexError,KeyError) as error:self.validation_error=str(error);self.message(str(error))

    def apply_spins(self):self.change_boundary(self.timeline.word,self.timeline.part,self.begin.value(),self.end.value())
    def nudge(self,delta):
        a,b=self.selected_times();self.change_boundary(self.timeline.word,self.timeline.part,a+delta,b+delta)
    def audition_line(self):
        if self.line:self.playback.audition(self.line.start,self.line.end,self.loop.isChecked())
        else:self.message('请先加入歌词')
    def audition_selected(self):
        if self.line:a,b=self.selected_times();self.playback.audition(a,b,self.loop.isChecked())
    def position_changed(self,value):
        self.play_time.setText(stamp(value));self.timeline.follow_position(value)
        if not self.seek_slider.isSliderDown():self.seek_slider.setValue(value)

    def reading_changed(self,row,col):
        if self.refreshing or col==0 or not self.line:return
        kana=self.units.item(row,1).text();latin='' if col==1 and kana!=self.line.units[row].kana else self.units.item(row,2).text();index=self.current
        if kana==self.line.units[row].kana and latin==self.line.units[row].romaji:return
        def update(p):
            changed_kana=p.lines[index].units[row].kana!=kana
            p.lines[index]=edit_reading(p.lines[index],row,kana,latin,p.reading_preferences.get('romaji'))
            if changed_kana:p.checks.setdefault(p.lines[index].id,{})['reading']=False
        if not self.edit('修改词组读音',update):self.refresh_table()
    def edit_translation(self,*args):
        if not self.refreshing and self.line:
            row=self.current;text=self.translation.text();uid=self.line.id
            if text==self.line.translation or self.line.locked:return
            from studio_backend.translation import manual
            self.edit('修改译文',lambda p:p.lines.__setitem__(row,manual(p.lines[row],text)),merge_key=('translation',uid))
    def flush_edits(self,allow_segmentation=False):
        if self._flushing:return True
        if not allow_segmentation and hasattr(self,'inline_segment') and self.inline_segment.pending:
            self.message('本句编辑预览尚未应用，请先应用或取消预览。');return False
        self._flushing=True
        self.validation_error=None
        try:
            focus=QApplication.focusWidget()
            if not (focus and self.units.isAncestorOf(focus)) and self.units.state()==QAbstractItemView.State.EditingState:
                focus=next((editor for editor in self.units.findChildren(QLineEdit) if editor.isVisible()),None)
            if focus and self.units.isAncestorOf(focus):
                from PySide6.QtWidgets import QAbstractItemDelegate
                delegate=self.units.itemDelegate();delegate.commitData.emit(focus);delegate.closeEditor.emit(focus,QAbstractItemDelegate.EndEditHint.NoHint)
            if self.validation_error:return False
            self.begin.interpretText();self.end.interpretText()
            self.edit_translation();return self.validation_error is None
        finally:self._flushing=False
    def confirm_reading(self,value):
        if not self.refreshing and self.line:
            uid=self.line.id;self.edit('确认读音',lambda p:p.checks.setdefault(uid,{}).__setitem__('reading',value))
    def lock_line(self,value):
        if not self.refreshing and self.line:
            row=self.current;self.edit('锁定歌词' if value else '解除锁定',lambda p:setattr(p.lines[row],'locked',value))
    def confirm_next(self):
        if not self.flush_edits():return
        if not self.line:return
        row=self.current
        def confirm(p):
            line=p.lines[row];line.reviewed=True
            from studio_backend.provenance import preserve_before_confirmation
            preserve_before_confirmation(line)
            for unit in line.units:
                unit.source='manual'
                for part in unit.highlights:part.source='manual'
        self.edit('确认本句时间',confirm)
        if all(line.reviewed for line in self.project.lines):self.message('整首歌的时间已确认。接着核对读音，或进入字幕样式和导出。')
        else:self.next_unconfirmed(reading=False);self.message('本句时间已确认，已跳到下一句待确认歌词。Ctrl+S 保存作品。')
    def edit_pauses(self):
        if not self.line or not self.flush_edits():return
        dialog=PauseDialog(self.line,self.playback,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            row=self.current;self.edit('处理停顿',lambda p:p.lines.__setitem__(row,dialog.result))

    def cleanup_auto_gaps(self):
        if not self.line or not self.flush_edits():return
        dialog=ContinuityDialog(self.project,self.current,self.playback,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.edit('收拢自动分轴空白',lambda p:setattr(p,'lines',dialog.result_lines))
            self.message(f'已收拢 {len(dialog.changes)} 处自动轴短空白；起音和人工时间保持不变，可一步撤销。')
    def split_selected(self):
        if not self.flush_edits():return
        index=self.timeline.word
        if not self.line or index<0:self.message('先在词组表或时间轴选中一个词组');return
        word=self.line.units[index]
        if len(word.text)<2:self.message('此词组只有一个字，无法再拆分');return
        position,ok=QInputDialog.getInt(self,'拆分词组',f'原文：{word.text}\n在第几个字后拆开？新读音和边界需要复核。',1,1,len(word.text)-1)
        if ok:
            row=self.current;self.edit('拆分词组',lambda p:p.lines.__setitem__(row,split_word(p.lines[row],index,position)))
    def merge_selected(self):
        if not self.flush_edits():return
        selected=sorted(set(index.row() for index in self.units.selectedIndexes()))
        if not self.line or len(selected)<2:self.message('在表中按 Ctrl 或 Shift 选中相邻的至少两个词组');return
        if selected!=list(range(selected[0],selected[-1]+1)):self.message('只能合并相邻词组');return
        row=self.current;self.edit('合并词组',lambda p:p.lines.__setitem__(row,merge_words(p.lines[row],selected[0],selected[-1])))

    def render_unchanged(self,snapshot):
        if snapshot!=self._render_snapshot or self.playback.canvas.renderer.text!=self._render_text:return False
        from .fonts import project_font_files
        return [file_stamp(path) for path in project_font_files(self.project)]==self._render_font_stamp

    def render_subtitles(self,*,_snapshot=None,_windows=None,_after_edit=False):
        if self.closing:return
        if hasattr(self,'render_timer'):self.render_timer.stop()
        try:
            from .fonts import project_font_files
            fonts=project_font_files(self.project);font_stamp=[file_stamp(path) for path in fonts];snapshot=self.project.to_dict() if _snapshot is None else _snapshot;renderer=self.playback.canvas.renderer
            renderer.add_fonts(fonts)
            if snapshot!=self._render_snapshot or font_stamp!=self._render_font_stamp or renderer.text!=self._render_text:
                composer=_compose_after_edit if _after_edit else compose
                text=composer(self.project,cache=self._composition_cache,_snapshot=snapshot,_windows=_windows,_font_stamp=font_stamp);renderer.set_text(text);self._render_snapshot=snapshot;self._render_font_stamp=font_stamp;self._render_text=text
                self.playback.canvas.update()
            if self.stage==3 and not _after_edit:self.refresh_font_cards()
        except (ValueError,OSError) as error:self.message(str(error));return str(error)

    def refresh_font_choice(self,*args):
        role=self.font_role.currentIndex();s=self.project.style;name=['font','ruby_font','translation_font'][role]
        path_name=['font_file','ruby_font_file','translation_font_file'][role]
        family=getattr(s,name);path=getattr(s,path_name);blocker=QSignalBlocker(self.font_choice);choices=[];resolved_family=family_name(path,family) if path and Path(path).is_file() else family
        for i in range(self.font_choice.count()):
            font=self.font_choice.itemData(i)
            if font.family in (family,resolved_family):
                score=0 if path and Path(path)==Path(font.path) else 1 if path and Path(path).is_file() and font_weight(path,family)==font_weight(font.path,font.family) else 2
                choices.append((score,i))
        if choices:self.font_choice.setCurrentIndex(min(choices)[1])
        font=self.font_choice.currentData()
        if font and self.line:
            text=''.join(line.text+line.romaji if role==0 else ''.join(u.kana for u in line.units) if role==1 else line.translation for line in self.project.lines)
            absent=missing(font.path,text,font.family);self.font_coverage.setText('本工程缺少字符：'+absent[:30] if absent else '本工程所需字符完整。黑体适合清晰的小字，明朝体适合较大的原文；注音可单独选黑体。')

    def refresh_font_cards(self):
        if not self.line:return
        local_palette={'global':self.project.color_styles.get('global'),'lines':{self.line.id:self.project.color_styles['lines'][self.line.id]} if self.line.id in self.project.color_styles.get('lines',{}) else {}} if self.project.color_styles else {}
        local_layout={self.line.id:self.project.layout_styles[self.line.id]} if self.line.id in self.project.layout_styles else {}
        key=json.dumps({'line':self.line.to_dict(),'colors':local_palette,'layout':local_layout},ensure_ascii=False,sort_keys=True)
        if key==self.cards_key:return
        import numpy as np
        from .render import AssRenderer
        if self.cards_renderer is None:self.cards_renderer=AssRenderer()
        for index,b in zip(self.preset_indices,self.preset_buttons):
            p=copy.copy(self.project);p.lines=[copy.deepcopy(self.line)];p.source_ass_active=False;p.color_styles=copy.deepcopy(local_palette);p.layout_styles=copy.deepcopy(local_layout);p.song_info={}
            p.style=self.preset_style(index)
            self.cards_renderer.set_text(compose(p));when=(p.lines[0].start+p.lines[0].end)//2
            pixels=self.cards_renderer.rgba(960,540,when);array=np.frombuffer(pixels,np.uint8).reshape(540,960,4);ys,xs=np.where(array[:,:,3]>12)
            image=self.cards_renderer.image(960,540,when)
            if len(xs):
                left=max(0,int(xs.min())-18);top=max(0,int(ys.min())-12);right=min(960,int(xs.max())+18);bottom=min(540,int(ys.max())+12)
                image=image.copy(QRect(left,top,right-left,bottom-top))
            pixmap=QPixmap(276,80);pixmap.fill(QColor('#142238'));painter=QPainter(pixmap)
            fitted=image.scaled(264,72,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation);painter.drawImage((276-fitted.width())//2,(80-fitted.height())//2,fitted);painter.end();b.setIcon(QIcon(pixmap))
        self.cards_key=key
    def font_changed(self,*args):
        if self.refreshing:return
        font=self.font_choice.currentData();role=self.font_role.currentIndex()
        if font:
            a,b=[('font','font_file'),('ruby_font','ruby_font_file'),('translation_font','translation_font_file')][role]
            def apply(p):setattr(p.style,a,font.family);setattr(p.style,b,font.path);p.source_ass_active=False
            self.edit('选择字体',apply)
    def set_style(self,name,value):
        if self.refreshing:return
        def apply(p):setattr(p.style,name,value);p.source_ass_active=False
        if self.edit('修改字幕样式',apply) and name=='display_mode':self.preview_style()
    def preview_style(self):
        if not self.line:return
        from PySide6.QtMultimedia import QMediaPlayer
        self.subtitle_toggle.setChecked(True)
        position=self.playback.canvas.position;windows=display_windows(self.project)
        if self.playback.player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState and not any(w.start<=position<w.end for w in windows):
            self.playback.seek(self.line.start+min(500,(self.line.end-self.line.start)//2));self.message('已定位到本句预览字幕样式。')
        self.render_subtitles()
    def preset_style(self,index):
        fonts=bundled_fonts();font=fonts[3 if index==2 else 2 if index==3 else index];ruby=fonts[2] if index in (2,3) else font
        style=Style(name='清晰通用' if index==0 else '明朝风格',font=font.family,font_file=font.path,ruby_font=ruby.family,ruby_font_file=ruby.path,translation_font=fonts[0].family,translation_font_file=fonts[0].path,highlight='#73e8bb' if index in (0,3) else '#ffd58a')
        if index==2:
            style.name='日式接唱 · 特粗明朝';style.display_mode='alternating';style.size=108;style.ruby_size=46;style.highlight='#58abf4';style.outline_color='#10151d';style.outline=6;style.shadow=0;style.glow=4;style.show_romaji=False;style.show_translation=False
        elif index==3:style.name='清晰注音 · 粗黑体';style.size=82;style.ruby_size=34;style.outline=3.5;style.shadow=0
        return style

    def apply_preset(self,index):
        def apply(p):p.style=self.preset_style(index);p.source_ass_active=False
        if self.edit('应用样式模板',apply):self.preview_style()
    def choose_color(self,name):
        if self.project.color_styles:return self.edit_color_states(quick=name)
        color=QColorDialog.getColor(QColor(getattr(self.project.style,name)),self,'选择字幕颜色')
        if color.isValid():self.set_style(name,color.name())
    def add_font(self):
        path,_=QFileDialog.getOpenFileName(self,'添加本地字体','','字体文件 (*.ttf *.otf *.ttc *.otc)')
        if not path:return
        try:
            from .fonts import families_in_file,key,fonts_in_file
            fonts=fonts_in_file(path);register_qt_fonts(fonts);self.extra_fonts.extend(fonts)
            from .subtitle_import import needed_fonts
            available={key(x) for x in families_in_file(path)}
            matched=[name for name in needed_fonts(self.project.source_ass) if key(name) in available] if self.project.source_ass_active else []
            if matched:
                self.edit('补充原 ASS 字体',lambda p:p.font_assets.update({name:path for name in matched}));self.message('已补充原 ASS 字体，原样式与特效保留。')
            else:
                first=self.font_choice.count()
                for font in fonts:self.font_choice.addItem(font.family,font)
                self.font_choice.setCurrentIndex(first)
        except Exception as error:self.message('字体无法加载：'+str(error))

    def undo(self):
        if not self.flush_edits():return
        before=self.project.media
        if self.history.undo():
            self.drop_edited_checkpoint();self.sync_history_media(before);snapshot=self.project.to_dict();self.refresh(_snapshot=snapshot);self.checkpoint_edited_snapshot(snapshot)
    def redo(self):
        if not self.flush_edits():return
        before=self.project.media
        if self.history.redo():
            self.drop_edited_checkpoint();self.sync_history_media(before);snapshot=self.project.to_dict();self.refresh(_snapshot=snapshot);self.checkpoint_edited_snapshot(snapshot)
    def sync_history_media(self,before):
        if before!=self.project.media:
            if self.project.media and Path(self.project.media).is_file():self.load_media(self.project.media,False,self.playback.canvas.position,self.playback.zoom,True)
            else:self.clear_media()

    def clear_media(self):
        self.audition_role='original';self.original_audio=None
        self.clear_proxy()
        self.analysis_generation+=1
        if self.analysis_job:self.analysis_job.cancel.set();self.analysis_job=None
        self.playback.clear();self.timeline.peaks=None;self.timeline.duration=0;self.timeline.keyframes=[];self.timeline.cache_key=None
        self.playback.canvas.frame=QImage();self.playback.canvas.audio_only=False;self.timeline.cache_rgb=None
        if self.timeline.audio:self.timeline.audio.close();self.timeline.audio=None

    def can_replace(self):
        self._discarding=False
        if not self.flush_edits():return False
        if self.api.busy or self.local_job or self.source_job:self.message('请先完成或取消当前制作任务，再切换工程');return False
        if not self.history.dirty:return True
        answer=QMessageBox.question(self,'工程尚未保存','是否保存当前工程后继续？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel)
        if answer==QMessageBox.StandardButton.Cancel:return False
        if answer==QMessageBox.StandardButton.Save:return self.save()
        self._discarding=True
        return True
    def new(self):
        if self.can_replace():self.clear_media();self.clear_recovery();self.history=History(Project());self.path=None;self.current=-1;self.pending=None;self.last_output='';self.timeline.spectrum=None;self.refresh();self.set_stage(0)
    def open_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,'打开工程或字幕','','工程与字幕 (*.sgproj *.json *.ass *.ssa *.lrc *.srt);;所有文件 (*)')
        if path:self.open_path(path)
    def open_path(self,path,guard=True):
        if guard and not self.can_replace():return False
        try:p=load_project(path)
        except (ValueError,OSError) as error:self._discarding=False;self.message('打开失败：'+str(error));return False
        self.clear_media();self.history=History(p);self.path=Path(path) if Path(path).suffix.lower()=='.sgproj' else None;self.current=0;self.pending=None
        self.clear_recovery();self.last_output='';self.preferences.remember(path,p.title);self.refresh_recent_menu();self.welcome.set_recent(self.preferences.recent())
        self.refresh(True);self.set_stage(2 if p.lines else 0)
        if p.media and Path(p.media).is_file():self.load_media(p.media,edit=False)
        self.message('已打开工程。' if p.media and Path(p.media).is_file() else '已打开字幕；请添加或重新定位对应音视频。');return True
    def save(self):
        if not self.flush_edits():return False
        path=self.path
        if not path:
            selected,_=QFileDialog.getSaveFileName(self,'保存可继续编辑的工程',self.project.title+'.sgproj','声稿工程 (*.sgproj)')
            if not selected:return False
            path=Path(selected)
            if path.suffix.lower()!='.sgproj':path=path.with_suffix('.sgproj')
        try:save_project(self.project,path)
        except (ValueError,OSError) as error:self.message('保存失败：'+str(error));return False
        self.path=path;self.history.mark_saved();self.clear_recovery();self.remember_project();self.refresh();self.message('作品已保存：'+str(path));return True
    def paste_lyrics(self):
        if not self.flush_edits():return
        dialog=LyricsDialog(self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            text=dialog.text.toPlainText();append=dialog.append.isChecked()
            if not append and self.project.lines:
                if QMessageBox.question(self,'替换原歌词','替换会重建词组和时间；可以撤销。继续？')!=QMessageBox.StandardButton.Yes:return
            self.edit('加入原歌词',lambda p:p.replace_lyrics(text,append),True)
    def add_media(self):
        path,_=QFileDialog.getOpenFileName(self,'添加音视频','','音视频 (*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)')
        if path:self.load_media(path)
    def load_media(self,path,edit=True,position=0,zoom=None,preview=False):
        if edit and self.project.media:return self.switch_media_source(self.project.media_role,path)
        path=str(Path(path).resolve())
        if not Path(path).is_file():self.message('媒体文件不存在');return
        self.clear_media()
        self.analysis_generation+=1;generation=self.analysis_generation
        # setSource starts Qt's asynchronous demux/probe. Let it overlap the
        # detached history transaction rather than waiting for its full copy.
        # Backend notifications are queued and cannot bind the old document.
        self.playback.open(path,position,preview=preview)
        if edit:
            def apply(p):
                p.media=path;p.media_role='original';p.media_versions={'original':MediaVersion(path)}
                if p.title=='未命名作品':p.title=Path(path).stem
                p.duration=0;p.has_video=None;p.transcript=[];p.transcript_stamp={};p.media_stamp={}
            if not self.edit('添加媒体',apply):
                self.playback.clear();return
        self.playback.set_zoom(zoom);self.timeline.peaks=None;self.timeline.spectrum=None;self.message('正在后台生成波形和频谱，可以先粘贴歌词。')
        uid=self.project.uid
        def done(result):
            if self.closing or generation!=self.analysis_generation:return
            self.analysis_job=None
            if self.project.uid!=uid or self.project.media!=path:return
            self.timeline.set_audio(result)
            self.original_audio=result
            p=self.project;p.duration=int(result['duration']);p.width=int(result['width']);p.height=int(result['height']);p.fps=float(result['fps']);p.media_stamp=file_stamp(path);p.has_video=bool(result['has_video']);self.playback.canvas.audio_only=not p.has_video;self.playback.set_reference_size(p.width,p.height)
            if p.media_role in p.media_versions:p.media_versions[p.media_role]=MediaVersion(path,p.duration,p.media_stamp.copy())
            self.refresh();self.seek_slider.setMaximum(self.project.duration);self.message('音频波形已就绪。')
        def failed(message):
            if self.closing or generation!=self.analysis_generation:return
            self.analysis_job=None;self.message(message)
        def progress(value):
            if self.closing or generation!=self.analysis_generation or self.api.busy or self.local_job:return
            self.message(value if isinstance(value,str) else f'正在准备可试听的时间轴 · 已读取 {value/1048576:.1f} MB 音频')
        self.analysis_job=jobs.run(lambda cancel,progress:media.analyze(path,self.home/'wave-cache',cancel,progress),done,failed,progress)
        self.refresh_media_source()
    def open_demo(self):
        path=ASSETS/'demo'/'tutorial.json'
        if not path.exists():path=ROOT/'demo'/'tutorial.json'
        if self.open_path(path):self.message('离线练习：这是合成音调和人工示例，可以放心体验校准和样式。')

    def settings(self):
        if self.api.busy:self.message('请等待当前 API 任务完成');return
        from studio_backend.settings import Settings
        try:dialog=SettingsDialog(self,Settings(self.home))
        except (OSError,ValueError) as error:self.message(str(error));return
        if dialog.exec()==QDialog.DialogCode.Accepted:self.api.start(dialog.request())
    def refine_reading(self,use_llm,only_current=True):
        verified=bool(self.project.transcript_stamp) and self.project.transcript_stamp==file_stamp(self.project.media)
        self.start_api('refine',only_current=only_current,use_llm=use_llm,transcript=self.project.transcript,transcript_verified=verified,context=[line.to_dict() for line in self.project.lines])
    def local_match(self):
        self.rematch_timing_scope(only_current=True)
    def start_api(self,action,only_current=False,line_ids=None,**options):
        if not self.flush_edits():return
        if self.api.busy or self.source_job:self.message('已有后台任务正在执行，请等候换源或当前任务完成');return
        if self.pending and self.pending.get('result',{}).get('suggestions'):self.message('先审核或放弃当前建议，再生成新的初稿。原始结果仍保存在任务记录。');return
        if not self.project.lines:self.message('请先粘贴原歌词');return
        if line_ids is not None:
            lines=[line for line in self.project.lines if line.id in line_ids]
            if len(lines)!=len(set(line_ids)):self.message('歌词选择已变化，请重新选择范围');return
            if any(line.locked or any(unit.locked for unit in line.units) for line in lines):self.message('所选范围包含锁定内容，请先解除锁定');return
        elif only_current and self.line:lines=[self.line]
        elif action in {'match','transcribe_match'}:
            # Confirmed/locked rows remain immutable context for whole-song
            # matching. Removing them here would let repeated verses cross the
            # very human positions that the backend is meant to respect.
            from studio_backend.matching_context import protected
            lines=list(self.project.lines) if any(not protected(x) for x in self.project.lines) else []
        elif action in {'refine','annotate'}:lines=[x for x in self.project.lines if not x.locked and not self.project.checks.get(x.id,{}).get('reading')]
        else:lines=[x for x in self.project.lines if not x.reviewed and not x.locked]
        if not lines:self.message('当前范围已经确认或锁定；可以选中具体一句再操作');return
        if action in {'transcribe_match','align'} and not self.project.media:self.message('请先添加音视频');return
        if action=='match' and not self.project.transcript:self.message('本工程没有可复用的转录，请先完成一次转录');return
        if action=='match' and self.project.transcript_stamp and self.project.transcript_stamp!=file_stamp(self.project.media):self.message('素材已被替换，已有转录不再对应当前版本，请重新添加正确素材或重新转录');return
        context={'project':self.project.uid,'media':file_stamp(self.project.media)}
        automatic_axis=action in {'segment','match','transcribe_match','align'} and self.continuous_timing.isChecked()
        if action in {'annotate','refine','segment','match','transcribe_match','align'}:
            from studio_backend.romanization import DEFAULT
            options.setdefault('romanization_rules',copy.deepcopy(self.project.reading_preferences.get('romaji',DEFAULT)))
        request={'action':action,'lines':[x.to_dict() for x in lines],'media':self.project.media,'language':'ja','gap_ms':500 if automatic_axis else 0,'join_lines':bool(automatic_axis),'_studio_context':context,'_studio_checks':copy.deepcopy(self.project.checks),**options}
        self.snapshots={x.id:x.to_dict() for x in lines}
        if action=='match' and options.get('rematch_confirmed'):
            request['_studio_snapshots']=copy.deepcopy(self.snapshots)
            for value in request['lines']:value['reviewed']=False
        self.api.start(request);self.message('任务已开始；结果会先进入审核。')
    def api_done(self,result):
        action=self.api.request.get('action')
        if action=='configure':self.message('API 设置已加密保存到本机。');return
        if result.get('workflow'):self.show_draft_progress(result['workflow'])
        context=self.api.request.get('_studio_context',{})
        if context and (context['project']!=self.project.uid or context['media']!=file_stamp(self.project.media)):
            self.message('任务期间工程或素材版本已变化，结果已保留在任务记录，没有写入当前工程。');return
        if action in {'transcribe','confirm_recognition'}:
            self.handle_recognition_result(result,self.api.request,self.api.folder);return
        self.keep_background_reading()
        self.pending={'result':result,'snapshots':self.snapshots,'folder':str(self.api.folder),'action':action,'context':context,'checks':self.api.request.get('_studio_checks')}
        # Returned proposals do not change editor widgets. Keep unfinished
        # reading/time input until the user explicitly opens review or adopts.
        self.remember_transcript(result,context,quiet=True)
        if result.get('workflow') and not result.get('suggestions'):self.pending=None
        self.save_recovery();self.update_workflow();self.message(result.get('message') if result.get('workflow') or result.get('chorus_workflow') else (f'已收拢 {result["closed_gaps"]} 处自动轴短空白。' if result.get('closed_gaps') else '')+'初稿已返回，请点击“审核上次任务结果”。')
    def keep_background_reading(self):
        # Persist the user's valid active reading, without closing its editor
        # or refreshing unrelated unfinished time/segmentation controls.
        if not self.line or self.units.state()!=QAbstractItemView.State.EditingState:return
        editor=QApplication.focusWidget()
        if not isinstance(editor,QLineEdit) or not self.units.isAncestorOf(editor):editor=next((e for e in self.units.findChildren(QLineEdit) if e.isVisible()),None)
        if editor is None:return
        # Row selection may report currentColumn()==0 while the delegate is
        # editing column 1. Use the editor's actual cell, not selection state.
        cell=self.units.indexAt(editor.mapTo(self.units.viewport(),editor.rect().center()))
        row=cell.row();col=cell.column()
        if row<0 or row>=len(self.line.units) or col not in {1,2}:return
        old=self.line.units[row];kana=editor.text() if col==1 else self.units.item(row,1).text()
        latin=editor.text() if col==2 else '' if kana!=old.kana else old.romaji
        if (kana,latin)==(old.kana,old.romaji):return
        index=self.current
        def keep(p):
            changed_kana=p.lines[index].units[row].kana!=kana
            p.lines[index]=edit_reading(p.lines[index],row,kana,latin,p.reading_preferences.get('romaji'))
            if changed_kana:p.checks.setdefault(p.lines[index].id,{})['reading']=False
        try:self.history.apply('修改词组读音',keep)
        except ValueError:return # Invalid input stays visible for explicit repair.
        cursor=editor.cursorPosition();selection=editor.selectionStart();length=len(editor.selectedText())
        blocked=self.units.blockSignals(True)
        try:
            self.units.item(row,1).setText(kana);self.units.item(row,2).setText(self.line.units[row].romaji)
        finally:self.units.blockSignals(blocked)
        if selection>=0:editor.setSelection(selection,length)
        else:editor.setCursorPosition(cursor)
    def remember_transcript(self,result,context,quiet=False):
        data=result.get('transcript')
        fingerprint=result.get('media_fingerprint','')
        if data and (data!=self.project.transcript or fingerprint and fingerprint!=self.project.transcript_fingerprint):
            if self.project.recognition_draft:return
            def keep(p):p.transcript=data;p.transcript_stamp=context.get('media',{});p.transcript_fingerprint=fingerprint
            if quiet:
                try:self.history.apply('保留原始转录',keep)
                except ValueError:self.message('转录已保存在任务记录；当前工程输入需要修正后再复用。')
            else:self.edit('保留原始转录',keep)
    def api_failed(self,message):self.message(message)
    def review_pending(self):
        if not self.pending:self.message('目前没有待审核结果，可从任务记录恢复以前的结果。');return
        if self.pending.get('action')=='sound_gaps':self.review_sound_gaps();return
        if not self.flush_edits():return
        context=self.pending.get('context',{})
        if context and (context['project']!=self.project.uid or context['media']!=file_stamp(self.project.media)):
            self.message('结果对应的工程或音视频与当前不同，请切回对应素材后审核；结果仍保留。');return
        self.remember_transcript(self.pending['result'],context)
        dialog=ReviewDialog(self.project,self.pending['result'],self.playback,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.apply_suggestions(dialog.selected())
        elif dialog.rematch_uid:
            if self.shelve_for_manual(dialog.rematch_uid):self.rematch_timing_scope(only_current=True)
        elif dialog.manual_uid:self.shelve_for_manual(dialog.manual_uid)
    def shelve_for_manual(self,uid):
        if not self.pending:return False
        import uuid
        folder=self.home/'desktop-tasks'/uuid.uuid4().hex
        request={'action':'review_saved','_studio_origin_action':self.pending.get('action'),
                 '_studio_context':self.pending.get('context',{}),'_studio_snapshots':self.pending.get('snapshots',{}),
                 '_studio_checks':self.pending.get('checks'),'lines':list(self.pending.get('snapshots',{}).values()),'plan':copy.deepcopy(self.pending.get('plan',{}))}
        try:
            atomic_json(folder/'request.json',request);atomic_json(folder/'result.json',{'ok':True,**self.pending['result']})
        except OSError:self.message('建议暂存失败，当前建议保留；请检查保存目录后重试。');return False
        self.pending=None;self.current=next((i for i,line in enumerate(self.project.lines) if line.id==uid),self.current)
        self.time_scope.setCurrentIndex(0);self.set_stage(2);self.refresh(True);self.select_entire_line();self.save_recovery()
        self.message('本次建议已暂存到任务记录，原内容保留。现在可改本句假名、整句范围或直接划音。')
        return True
    def apply_suggestions(self,selected):
        if not self.flush_edits():return
        pending_result=self.pending.get('result',{}) if self.pending else {}
        context=self.pending.get('context',{}) if self.pending else {}
        if context and (context['project']!=self.project.uid or context['media']!=file_stamp(self.project.media)):
            self.message('当前素材与任务版本不同，建议仍保留，未改动工程。');return
        if pending_result.get('reading_reuse') and not self.chorus_reference_valid(pending_result):
            self.message('来源副歌或确认状态已变化，建议保留但未采用；请按当前来源重新生成。');return
        if self.pending and (self.pending.get('action')=='acoustic' or self.pending['result'].get('acoustic')):
            from .vocal_audio import digest
            expected=self.pending['result'].get('source_sha256') or self.pending['result'].get('acoustic',{}).get('source_sha256')
            try:source_matches=digest(self.project.media)==expected
            except OSError:source_matches=False
            if not source_matches:self.message('当前素材内容与歌声任务不同，建议保留，未改动工程。');return
        snapshots=self.pending.get('snapshots',{}) if self.pending else {};skipped=[];accepted=[]
        def apply(p):
            by_id={x.id:i for i,x in enumerate(p.lines)}
            for data in selected:
                uid=data['id'];index=by_id.get(uid)
                if index is None:skipped.append(uid);continue
                old=p.lines[index]
                chorus=bool(self.pending and self.pending['result'].get('reading_reuse'))
                if chorus:
                    from studio_backend.matching_context import protected
                    if protected(old) or p.checks.get(uid,{}).get('reading') or uid not in self.pending['result']['reading_reuse']['eligible_ids']:skipped.append(uid);continue
                acoustic=bool(self.pending and self.pending.get('action')=='acoustic')
                acoustic_plan=self.pending.get('plan',{}) if self.pending else {}
                if not isinstance(acoustic_plan,dict):raise ValueError('声学任务请求格式无效，未采用。')
                recalculation=acoustic_plan.get('recalculation',{})
                if not isinstance(recalculation,dict):raise ValueError('内部重算许可格式无效，未采用。')
                textual=bool(self.pending and self.pending.get('action') in {'refine','annotate'})
                if not acoustic and not textual and any(h.fixed_edges for u in old.units for h in u.highlights):skipped.append(uid);continue
                if old.locked or (old.reviewed and acoustic and not recalculation.get('allow_reviewed')) or (any(u.locked for u in old.units) and not acoustic) or old.to_dict()!=snapshots.get(uid):skipped.append(uid);continue
                check_snapshot=self.pending.get('checks') if self.pending else None
                if self.pending and self.pending.get('action') in {'draft','acoustic','chorus_reuse','refine','annotate'} and isinstance(check_snapshot,dict) and p.checks.get(uid,{})!=check_snapshot.get(uid,{}):skipped.append(uid);continue
                if data['text']!=old.text:raise ValueError('建议更改了原歌词，已拒绝应用；原始建议仍保留')
                same_reading=(old.kana,old.romaji,[(u.text,u.kana,u.romaji) for u in old.units])==(data.get('kana',''),data.get('romaji',''),[(u['text'],u.get('kana',''),u.get('romaji','')) for u in data.get('units',[])])
                candidate=LyricLine.from_dict(data)
                if textual:
                    from studio_backend.reading_suggestion import validate_text_result
                    validate_text_result(old,candidate)
                if not acoustic and not textual and any(h.fixed_edges for u in candidate.units for h in u.highlights):
                    raise ValueError('自动建议不能新建人工固定点，原内容保留。')
                if acoustic:
                    from studio_backend.acoustic import protected_equal
                    if candidate.timing_evidence.get('recalculation') and not recalculation:
                        raise ValueError('内部重算缺少原始许可请求，建议保留但未采用。')
                    if recalculation:
                        if acoustic_plan.get('original')!=old.to_dict():raise ValueError('内部重算请求与当前句不符，未采用。')
                        from studio_backend.recalculation import validate_result as validate_recalculation
                        validate_recalculation(acoustic_plan,candidate)
                    else:protected_equal(old,candidate)
                    guide_plan=acoustic_plan
                    if candidate.timing_evidence.get('guide_points') and not guide_plan.get('guide_points'):
                        raise ValueError('定位任务缺少原始固定点请求，建议保留但未采用。')
                    if not guide_plan.get('guide_points'):
                        fixed=lambda line:[(i,j,h.fixed_edges) for i,u in enumerate(line.units) for j,h in enumerate(u.highlights) if h.fixed_edges]
                        if fixed(old)!=fixed(candidate):raise ValueError('普通歌声建议不能新建人工固定点，原内容保留。')
                    if guide_plan.get('guide_points'):
                        from studio_backend.acoustic_guides import validate_result
                        validate_result(guide_plan,candidate)
                p.lines[index]=candidate
                if chorus or textual:p.source_ass_active=False
                if acoustic or (self.pending and self.pending['result'].get('acoustic',{}).get('lines',{}).get(uid,{}).get('status')=='aligned'):p.source_ass_active=False
                same_japanese=(old.kana or ''.join(u.kana for u in old.units))==(candidate.kana or ''.join(u.kana for u in candidate.units)) and [(u.text,u.kana) for u in old.units]==[(u.text,u.kana) for u in candidate.units]
                if not ((textual and same_japanese) or (self.pending and self.pending.get('action') in {'draft','acoustic'} and same_reading)):p.checks.setdefault(uid,{})['reading']=False
                accepted.append(uid)
        self.edit('采用审核建议',apply)
        if self.validation_error:return
        if self.pending:
            sequence=bool(self.pending['result'].get('sequence_review'))
            self.pending['result']['suggestions']=[value for value in self.pending['result'].get('suggestions',[]) if value['id'] not in accepted and not (sequence and value.get('match',{}).get('status')=='protected')]
            if not self.pending['result']['suggestions']:self.pending=None
        self.save_recovery();self.refresh()
        self.message(f'已采用 {len(accepted)} 行建议。'+(f'{len(skipped)} 行已修改或锁定，保留当前内容；未采用的建议仍可审核。' if skipped else '其余建议仍可继续审核。' if self.pending else '请试听并确认时间与读音。'))

    def busy_changed(self):
        busy=self.api.busy or bool(self.local_job) or bool(self.source_job) or bool(self.proxy_job);self.cancel_button.setVisible(busy);self.progress.setVisible(busy)
        if self.api.busy or self.source_job or self.proxy_job:self.progress.setRange(0,0)
        else:self.progress.setRange(0,100)
        self.update_workflow();self.refresh_media_source();self.refresh_vocal_tools();self.refresh_proxy_tools()
    def cancel_task(self):
        if self.api.busy:self.api.cancel()
        if self.local_job:self.local_job.cancel.set();self.message('正在取消压制任务。')
        if self.proxy_job:self.cancel_proxy_request();self.message('正在取消轻量预览任务，当前素材与字幕保持。')
        if self.source_job:self.source_job.cancel.set();self.message('正在取消声音空隙检查，原时间保留。' if self.source_job_kind=='sound_gaps' else '正在取消歌声对齐，原时间与人工校准保留。' if self.source_job_kind=='acoustic' else '正在取消人声任务，原素材与字幕保留。' if self.source_job_kind=='vocals' else '正在取消换源，当前视频与字幕保留。')

    def check_project(self):
        self.export_issues.clear()
        rows={line.id:(i,line.text) for i,line in enumerate(self.project.lines,1)}
        def title(uid,text):
            if uid not in rows:return text
            number,original=rows[uid];return f'第 {number} 句 · '+text+'\n'+original[:32]
        for kind,uid,text in self.project.issues():
            item=QListWidgetItem(title(uid,text));item.setData(Qt.ItemDataRole.UserRole,(uid,kind));self.export_issues.addItem(item)
        try:
            for uid,text in layout_issues(self.project):
                item=QListWidgetItem(title(uid,text));item.setData(Qt.ItemDataRole.UserRole,(uid,'layout'));self.export_issues.addItem(item)
        except (ValueError,OSError) as error:self.message(str(error))
        count=self.export_issues.count();self.issue_summary.setText(f'还有 {count} 项可检查，选中后前往处理。' if count else '检查通过，可以先导出一段样片。')
        if not count:self.export_issues.addItem('✓ 时间、读音和排版检查通过。')
        else:self.export_issues.setCurrentRow(0)
    def goto_issue(self,item):
        if not self.flush_edits():return
        data=item.data(Qt.ItemDataRole.UserRole)
        if not data:return
        uid,kind=data
        if uid:
            self.current=next((i for i,x in enumerate(self.project.lines) if x.id==uid),self.current);self.refresh(True)
            if kind!='layout':self.calibration_tabs.setCurrentIndex(1 if kind=='reading' else 0)
            self.set_stage(3 if kind=='layout' else 2)
        else:self.set_stage(3 if kind=='layout' else 0)
        if kind=='layout':self.pages.widget(3).ensureWidgetVisible(self.style_workbench_button)
    def export_ass(self):
        if not self.flush_edits():return
        if not self.project.lines:self.message('请先加入歌词');return
        path,selected_filter=QFileDialog.getSaveFileName(self,'导出字幕',self.project.title+'.ass','ASS 字幕 (*.ass);;SRT 字幕 (*.srt);;纯文本歌词 (*.txt)')
        if not path:return
        try:
            from .subtitle_files import export_subtitle
            kind='srt' if 'SRT' in selected_filter else 'txt' if '*.txt' in selected_filter else 'ass'
            destination=Path(path).with_suffix('.'+kind);export_subtitle(self.project,destination,kind);self.message('字幕已导出：'+str(destination))
        except (ValueError,OSError) as error:self.message(str(error))
    def start_encode(self,sample):
        if not self.flush_edits():return
        if self.local_job or self.source_job:self.message('请等待当前压制或换源任务完成');return
        if not self.project.duration:self.message('请先添加视频或音频，等待素材读取完成');return
        version='-'+ROLES[self.project.media_role] if len(self.project.media_versions)>1 else ''
        suffix=version+('-试压.mp4' if sample else '-字幕成品.mp4')
        path,_=QFileDialog.getSaveFileName(self,'试压视频' if sample else '压制成品视频',self.project.title+suffix,'MP4 视频 (*.mp4)')
        if not path:return
        start=max(0,self.line.start-1000) if sample and self.line else 0
        duration=min(12000,self.project.duration-start) if sample else 0
        options=EncodeOptions(path,start,duration,self.output_size.currentData(),self.quality.currentData(),self.encoder.currentData())
        self.encode_to(options)
    def encode_to(self,options):
        if self.source_job:self.message('请等待换源完成再压制');return
        snapshot=Project.from_dict(self.project.to_dict());self.progress.setRange(0,100);self.progress.setValue(0)
        def done(result):
            self.local_job=None;self.last_output=result['output'];self.busy_changed();self.output_label.setText('已完成：'+result['output']);self.message('视频已导出，可以播放成品或打开文件夹。');self.record_task('encode','completed',result)
        def failed(message):
            self.local_job=None;self.busy_changed();self.message(message);self.record_task('encode','failed',{'message':message})
        def progress(value):
            self.progress.setValue(round(value['ratio']*100));remaining=value.get('remaining');self.message(f'正在压制 {value["ratio"]:.0%}'+(f' · 预计剩余 {remaining:.0f} 秒' if remaining is not None else ''))
        self.local_job=jobs.run(lambda cancel,report:encode(snapshot,options,cancel,report),done,failed,progress);self.busy_changed();self.message('压制任务已开始，使用当前工程的独立快照。')
    def record_task(self,kind,state,data):
        import uuid,time
        record={'kind':kind,'state':state,'created':time.time(),'title':self.project.title,**data}
        try:atomic_json(self.home/'desktop-renders'/(uuid.uuid4().hex+'.json'),record)
        except OSError:self.message('任务已结束，但任务记录无法保存，请记录输出位置。')
    def task_history(self):
        dialog=QDialog(self);dialog.setWindowTitle('任务记录与结果恢复');dialog.resize(800,520);l=vertical(dialog)
        items=QListWidget();l.addWidget(items);entries=[]
        render_root=self.home/'desktop-renders'
        for file in sorted(render_root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50] if render_root.exists() else []:
            try:
                value=json.loads(file.read_text(encoding='utf-8'));entries.append((None,{'action':'encode'},value));items.addItem('视频压制 · '+('完成 · '+str(value.get('output','')) if value.get('state')=='completed' else value.get('message','未完成')))
            except (ValueError,OSError):continue
        root=self.home/'desktop-tasks'
        for folder in sorted(root.iterdir(),key=lambda x:x.stat().st_mtime,reverse=True)[:100] if root.exists() else []:
            request=folder/'request.json';result=folder/'result.json'
            if not request.exists():continue
            try:
                req=json.loads(request.read_text(encoding='utf-8'));value=json.loads(result.read_text(encoding='utf-8')) if result.exists() else {'message':'没有最终结果，请确认服务端状态后再重试'}
                if req.get('action')=='chorus_reuse':
                    if not value.get('suggestions'):
                        from studio_backend.chorus_workflow import saved_result
                        cached=saved_result(req,self.home)
                        if cached:value={'ok':True,**cached}
                    items.addItem('复用已校对副歌 · '+('结果已保存，可审核或继续' if value.get('ok') else value.get('message','未完成')))
                elif req.get('action')=='draft':
                    state=value.get('workflow',{}).get('status')
                    text='完成，待审核' if state=='completed' else '未全部完成，可查看阶段与继续'
                    items.addItem('分阶段初稿 · '+text)
                elif req.get('action') in {'transcribe','confirm_recognition'}:
                    title='识别原文' if req['action']=='transcribe' else '原文确认（本地）'
                    items.addItem(title+' · '+('结果已保存，可恢复' if value.get('ok') else value.get('message','未完成')))
                else:items.addItem(('暂存的校对建议' if req.get('action')=='review_saved' else '本地歌声对齐' if req.get('action')=='acoustic' else str(req.get('action')))+' · '+('完成，待审核' if value.get('ok') else value.get('message','未完成')))
                entries.append((folder,req,value))
            except (ValueError,OSError):continue
        def restore():
            index=items.currentRow()
            if index<0:return
            folder,request,result=entries[index]
            if request.get('action') in {'transcribe','confirm_recognition'}:
                dialog.accept();self.restore_recognition_result(request,result,folder);return
            if not result.get('suggestions'):self.message(result.get('message','此任务没有字幕建议'));return
            self.pending={'result':result,'snapshots':request.get('_studio_snapshots') or {x['id']:x for x in request.get('lines',[])},'folder':str(folder),'action':request.get('_studio_origin_action') or request.get('action'),'context':request.get('_studio_context',{}),'checks':request.get('_studio_checks'),'plan':request.get('plan',{})};dialog.accept();self.refresh();self.review_pending()
        def open_output():
            index=items.currentRow()
            if index<0:return
            path=entries[index][2].get('output','')
            if path and Path(path).is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
        def resume_workflow():
            index=items.currentRow()
            if index<0:return
            request=entries[index][1];value=entries[index][2]
            if (request.get('action')=='acoustic' or request.get('_studio_origin_action')=='acoustic') and request.get('plan',{}).get('recalculation'):
                dialog.accept();self.resume_acoustic_recalculation(request);return
            if (request.get('action')=='acoustic' or request.get('_studio_origin_action')=='acoustic') and request.get('plan',{}).get('guide_points'):
                dialog.accept();self.resume_acoustic_guides(request);return
            if request.get('action')=='chorus_reuse' or value.get('chorus_workflow'):
                dialog.accept();self.resume_chorus_workflow(request.get('workflow_id') or value.get('chorus_workflow',{}).get('id'));return
            if request.get('action')!='draft' and not value.get('workflow'):self.message('此记录没有可继续的初稿或副歌检查点，可直接恢复建议审核。');return
            dialog.accept();self.resume_draft(request.get('workflow_id') or value.get('workflow',{}).get('id'))
        l.addWidget(button('恢复所选建议并审核',restore));l.addWidget(button('继续所选处理流程…',resume_workflow));l.addWidget(button('播放所选压制成品',open_output));l.addWidget(button('关闭',dialog.accept));dialog.exec()

    def recovery_path(self):return self.home/'desktop-recovery.json'
    def recovery_failed(self,error):
        if not self.closing:self.message('自动恢复文件无法写入，请及时保存工程：'+str(error))
    def recovery_record(self,snapshot):
        # Workers never read the live project or a mutable pending API result.
        return {'project':snapshot,'path':str(self.path or ''),'pending':copy.deepcopy(self.pending)}
    def checkpoint_edited_snapshot(self,snapshot):
        # Only the successful synchronous History transaction calls this.
        # Its detached snapshot is immutable to all internal readers. Exact
        # JSON data has no encoding hooks that could mutate a shared cache.
        # Pending API results/unusual Python values retain fresh timed capture.
        from .checkpoint_encoding import shareable
        if self.closing or not self.autosave.isActive() or self.pending is not None or not shareable(snapshot):
            self.drop_edited_checkpoint();return False
        if snapshot!=self.history.saved:
            self._edited_recovery=(self.project.uid,self.recovery_record(snapshot))
            if not self.edited_recovery_timer.isActive():self.edited_recovery_timer.start()
        else:self.clear_recovery()
        self.autosave.start()
        return True
    def drop_edited_checkpoint(self):
        self.edited_recovery_timer.stop();self._edited_recovery=None
    def publish_edited_checkpoint(self):
        value=self._edited_recovery;self.drop_edited_checkpoint()
        if value is None or self.closing or not self.autosave.isActive():return
        uid,record=value
        if uid!=self.project.uid or self.pending is not None:self.queue_recovery()
        else:self.recovery_writer.queue_owned(record)
    def queue_recovery(self):
        if self.closing:return
        self.drop_edited_checkpoint()
        snapshot=self.project.to_dict()
        if snapshot!=self.history.saved or self.pending:self.recovery_writer.queue_owned(self.recovery_record(snapshot))
        else:self.clear_recovery()
    def save_recovery(self):
        self.drop_edited_checkpoint()
        snapshot=self.project.to_dict()
        if snapshot!=self.history.saved or self.pending:
            try:self.recovery_writer.write_now(self.recovery_record(snapshot))
            except (OSError,ValueError) as error:self.recovery_failed(error)
        else:self.clear_recovery()
    def clear_recovery(self):
        self.drop_edited_checkpoint()
        try:self.recovery_writer.clear()
        except OSError:pass
    def offer_recovery(self):
        path=self.recovery_path()
        if not path.exists():return
        if QMessageBox.question(self,'恢复上次制作','发现上次未保存的工程或待审核结果，是否恢复？')!=QMessageBox.StandardButton.Yes:return
        try:
            data=json.loads(path.read_text(encoding='utf-8'));self.history=History(Project.from_dict(data['project']));self.history.saved={};self.path=Path(data['path']) if data.get('path') else None;self.pending=data.get('pending');self.current=0;self.refresh(True)
            if self.project.media and Path(self.project.media).exists():self.load_media(self.project.media,False)
        except (OSError,ValueError) as error:self.message('恢复失败：'+str(error))
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):
        if not self.flush_edits():event.ignore();return
        for url in event.mimeData().urls():
            path=Path(url.toLocalFile());suffix=path.suffix.lower()
            if suffix in {'.sgproj','.json','.ass','.ssa','.lrc','.srt'}:self.open_path(path)
            elif suffix=='.txt':
                try:text=path.read_text(encoding='utf-8-sig');self.edit('导入歌词',lambda p:p.replace_lyrics(text))
                except (ValueError,OSError) as error:self.message(str(error))
            else:self.load_media(path)
        event.acceptProposedAction()
    def closeEvent(self,event):
        if self.test:
            self.api.abandon();self.dispose();event.accept();return
        if self.api.busy or self.local_job or self.source_job or self.proxy_job:
            QMessageBox.information(self,'任务仍在运行','请等待任务完成，或点击“取消任务”后再关闭。');event.ignore();return
        if not self.can_replace():event.ignore();return
        if getattr(self,'_discarding',False):self.clear_recovery()
        else:self.save_recovery()
        self.dispose();event.accept()

    def dispose(self):
        if self.closing:return
        self.closing=True;self._source_serial+=1
        self.drop_edited_checkpoint();self.recovery_writer.close()
        if self.issue_dialog is not None:self.issue_dialog.timer.stop();self.issue_dialog.detail_timer.stop();self.issue_dialog.hide()
        self.fine_listener.dispose()
        self.cancel_proxy_request(False)
        if self.source_job:self.source_job.cancel.set()
        self.center_reveal_timer.stop();self._center_reveal_widget=None
        QApplication.instance().removeEventFilter(self);self.autosave.stop();self.render_timer.stop();self.playback.timer.stop();self.clear_media();self.playback.canvas.close_frame_scaler();self.playback.canvas.renderer.close()
        if self.cards_renderer:self.cards_renderer.close()

def main():
    app=QApplication(sys.argv);app.setApplicationName('Shengao Independent Studio');app.setOrganizationName('Shengao');app.setStyle('Fusion');app.setStyleSheet(STYLE)
    from .gui_gc import install
    install(app)
    window=StudioWindow()
    if len(sys.argv)>1 and Path(sys.argv[1]).is_file():window.open_path(sys.argv[1],False)
    screen=app.primaryScreen().availableGeometry()
    window.setMinimumSize(min(900,screen.width()-24),min(620,screen.height()-24));window.resize(min(1460,screen.width()-24),min(940,screen.height()-24))
    window.set_stage(0 if not window.project.lines else 2);window.show();sys.exit(app.exec())
