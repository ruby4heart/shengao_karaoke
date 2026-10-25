"""Inline choices share the selected word and the original audio player."""
import copy
from PySide6.QtCore import Qt,Signal,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QSizePolicy,QPlainTextEdit
from studio_backend.reading_candidates import review
from studio_backend.reading_change import preview


class ReadingCandidates(QWidget):
    audition=Signal(int,int)
    applyRequested=Signal(object)
    rememberRequested=Signal(str)
    manageRequested=Signal(str)
    undoPersonalRequested=Signal()
    rubyRequested=Signal()
    romanizationRequested=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.data=None;self.context={};self.proposal=None;self.raw_ass=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        def label(text=''):
            v=QLabel(text);v.setTextFormat(Qt.TextFormat.PlainText);v.setWordWrap(True);layout.addWidget(v);return v
        self.title=label('所选词组的读音候选');self.title.setObjectName('sectionTitle')
        self.choices=QComboBox();self.choices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.choices.setMinimumContentsLength(12);self.choices.setMinimumWidth(0);self.choices.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);self.choices.setToolTip('当前读音、词典多读法、转录假名及已保存的 DeepSeek 文字建议；都需要试听确认。');layout.addWidget(self.choices)
        self.reason=QPlainTextEdit();self.reason.setReadOnly(True);self.reason.setTabChangesFocus(True);self.reason.setMinimumHeight(64);self.reason.setMaximumHeight(110);self.reason.setAccessibleName('读音候选的文字依据');layout.addWidget(self.reason);self.notice=label();self.change=label();self.romanization_state=label()
        row=QHBoxLayout();self.listen=QPushButton('带前后试听这个词');self.listen.setToolTip('播放所选词组前后各 180 毫秒的实际音轨；不会把候选合成为语音。');row.addWidget(self.listen)
        self.apply=QPushButton('采用这个读音');self.apply.setToolTip('只修改所选词组的读音。先看下方音节处理说明，其他词组保持；一次操作一步撤销。');self.apply.setObjectName('primary');row.addWidget(self.apply);layout.addLayout(row)
        row=QHBoxLayout();self.dictionary_scope=QComboBox();self.dictionary_scope.addItem('本歌词典','song');self.dictionary_scope.addItem('个人词典','personal');self.dictionary_scope.setToolTip('本歌随工程保存；个人词典在本机跨工程使用，不会自动改歌词。');row.addWidget(self.dictionary_scope)
        self.remember=QPushButton('记住当前读音');self.remember.setToolTip('记住所选词组当前已经填写的假名，不采用尚未应用的候选；不改时间或确认。');self.remember.clicked.connect(lambda:self.rememberRequested.emit(self.dictionary_scope.currentData()));row.addWidget(self.remember)
        self.manage=QPushButton('管理词典…');self.manage.setToolTip('编辑、删除、导入或导出上面所选范围的读音词典。');self.manage.clicked.connect(lambda:self.manageRequested.emit(self.dictionary_scope.currentData()));row.addWidget(self.manage);layout.addLayout(row)
        self.undo_personal=QPushButton('撤销本次个人词典保存');self.undo_personal.setToolTip('只撤销本窗口最近一次个人词典保存；文件被别处更改时不会覆盖。');self.undo_personal.clicked.connect(lambda:self.undoPersonalRequested.emit());self.undo_personal.hide();layout.addWidget(self.undo_personal)
        self.extra_tools=QVBoxLayout();self.ruby=QPushButton('汉字与假名对应…');self.ruby.setToolTip('选择自动、整词、手工范围或不显示本词注音；只改注音排版，音节轴与原文保持。');self.ruby.clicked.connect(lambda:self.rubyRequested.emit());self.extra_tools.addWidget(self.ruby);layout.addLayout(self.extra_tools)
        self.romanization=QPushButton('罗马音规则／手写…');self.romanization.setToolTip('选择自动拼写规则、保留或修改手写覆盖；先比较当前值和新值，不改假名与时间。');self.romanization.clicked.connect(lambda:self.romanizationRequested.emit());self.extra_tools.addWidget(self.romanization)
        self.choices.currentIndexChanged.connect(self.choose);self.listen.clicked.connect(self.listen_word);self.apply.clicked.connect(self.accept)

    def set_line(self,line,index,context,transcript=(),verified=False,raw_ass=False,notice='',song_dictionary=None,personal_dictionary=None):
        old=self.choices.currentData() if self.data and self.data['original']==line.to_dict() and self.data['word']==index and self.context==context else None
        self.context=copy.deepcopy(context);self.raw_ass=raw_ass
        try:self.data=review(line,index,transcript,verified,song_dictionary,personal_dictionary)
        except (ValueError,TypeError) as error:
            self.data=None;self.title.setText('所选词组的读音候选');self.choices.clear();self.choices.setEnabled(False);self.reason.setPlainText(str(error));self.notice.clear();self.change.clear();self.apply.setEnabled(False);self.listen.setEnabled(False);return
        self.choices.setEnabled(True)
        from studio_backend.romanization import state
        from studio_backend.japanese import hiragana
        unit=line.units[index];roman=state(unit,context.get('romanization_rules'));badge={'auto':'自动','manual':'手写覆盖','legacy':'旧值，来源未记录'}[roman['mode']]
        if roman['mode']=='manual' and hiragana(roman.get('basis',''))!=hiragana(unit.kana):badge+=' · 假名已改，请复核'
        text=unit.romaji if len(unit.romaji)<=55 else unit.romaji[:52]+'…';self.romanization_state.setText('罗马音：'+badge+' · '+(text or '尚未生成'));self.romanization_state.setToolTip(unit.romaji)
        short=lambda s:s if len(s)<=40 else s[:37]+'…'
        self.title.setText('读音候选 · '+short(self.data['text'])+'\n当前：'+short(self.data['current'] or '尚未填写'));self.title.setToolTip(self.data['text']+'\n当前：'+self.data['current']);block=QSignalBlocker(self.choices);self.choices.clear()
        names={'current':'当前','dictionary_context':'词典默认','dictionary_entry':'词典其他读法','transcript':'转录假名','deepseek':'DeepSeek 文字建议','song_dictionary':'本歌词典','personal_dictionary':'个人词典'}
        for choice in self.data['choices']:self.choices.addItem(choice['kana']+' · '+'／'.join(names[s] for s in choice['sources']),choice['kana'])
        if old is not None and self.choices.findData(old)>=0:self.choices.setCurrentIndex(self.choices.findData(old))
        del block;self.notice.setText(self.data['notice']+(' '+notice if notice else ''));self.listen.setEnabled(bool(context.get('media')));self.choose()

    def choose(self,*_):
        self.proposal=None
        if not self.data:return
        kana=self.choices.currentData();choice=next((v for v in self.data['choices'] if v['kana']==kana),None)
        if choice is None:self.reason.setPlainText('没有可用候选，可在上方直接填写假名。');self.apply.setEnabled(False);return
        self.reason.setPlainText('\n'.join(choice['reasons']))
        from studio_backend.model import LyricLine
        try:
            result=preview(LyricLine.from_dict(self.data['original']),self.data['word'],kana,self.context.get('romanization_rules'))
            if not result['changed']:self.change.setText('当前已使用这个读音。选择其他候选前，可先按原声试听。');self.apply.setEnabled(False);return
            self.proposal=result
            text=(f'保留 {result["after_count"]} 个现有音节的起止、人工与固定边界，只改读音标签。' if result['kept_boundaries'] else f'本词从 {result["before_count"]} 个音节变成 {result["after_count"]} 个，按原词组范围重新估算；需要再校准时间。')
            if result.get('manual_romaji_kept'):text+=' 手写或旧罗马音保持，假名变化后请另行复核。'
            self.change.setText(text+' 采用后本句读音与时间待确认；原文、分词和其他词组保持。'+(' 采用后使用声稿样式，原 ASS 保留，可撤销。' if self.raw_ass else ''))
        except ValueError as error:self.change.setText(str(error))
        self.apply.setEnabled(self.proposal is not None)

    def listen_word(self):
        if self.data:self.audition.emit(*self.data['listen'])
    def accept(self):
        self.choose()
        if self.proposal:self.applyRequested.emit({'original':copy.deepcopy(self.data['original']),'context':copy.deepcopy(self.context),'word':self.data['word'],'kana':self.choices.currentData()})
