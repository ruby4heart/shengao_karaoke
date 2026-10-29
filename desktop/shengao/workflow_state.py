"""Shared workflow decisions for headings, primary actions and progress markers.

Keep page headings, primary actions and step markers driven by one decision.
No Qt, file access, project mutation or service requests occur here.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Facts:
    media_selected: bool = False
    media_ready: bool = False
    media_loading: bool = False
    line_count: int = 0
    unsegmented_count: int = 0
    timing_confirmed: int = 0
    reading_confirmed: int = 0
    recognition_pending: bool = False
    suggestion_count: int = 0
    task_running: bool = False
    resumable_draft: bool = False
    current_output: bool = False
    full_output: bool = False
    source_ass_active: bool = False
    inline_pending: bool = False


@dataclass(frozen=True)
class Action:
    command: str
    text: str
    stage: int


@dataclass(frozen=True)
class Decision:
    key: str
    heading: str
    detail: str
    primary: Action
    secondary: tuple[Action, ...]
    # "ready" is deliberately different from completed/confirmed.
    stages: tuple[str, str, str, str, str]
    captions: tuple[str, str, str, str, str]


ADD_MEDIA = Action('add_media', '添加视频或音频', 0)
RELOCATE_MEDIA = Action('add_media', '重新定位素材', 0)
ORIGINAL = Action('original_lyrics', '粘贴原歌词', 0)
RECOGNIZE = Action('recognize', '没有原歌词？识别并核对', 1)
SEGMENT = Action('missing_segmentation', '处理未分词歌词', 2)
DRAFT = Action('draft_options', '生成可审核初稿', 1)
REVIEW = Action('review_suggestions', '继续审核建议', 1)
TIMING = Action('pending_timing', '继续校准时间', 2)
READING = Action('pending_reading', '继续核对读音', 2)
STYLE = Action('style', '检查字幕样式', 3)
EXPORT = Action('export', '先看样片，再导出', 4)
PLAY_OUTPUT = Action('play_output', '播放本次输出', 4)


def decide(facts: Facts) -> Decision:
    """Choose the next useful action from content, never the visited page."""
    f = facts
    for value in (f.line_count, f.unsegmented_count, f.timing_confirmed,
                  f.reading_confirmed, f.suggestion_count):
        if type(value) is not int or value < 0:
            raise ValueError('工作流计数无效')
    if max(f.unsegmented_count, f.timing_confirmed, f.reading_confirmed) > f.line_count:
        raise ValueError('工作流计数超过歌词行数')
    has_lines = f.line_count > 0
    ready_lyrics = has_lines and f.unsegmented_count == 0
    confirmed = ready_lyrics and f.timing_confirmed == f.reading_confirmed == f.line_count
    stages = ('done' if f.media_ready and has_lines and not f.media_loading else 'needs_work',
              'done' if ready_lyrics else 'needs_work',
              'done' if confirmed else 'needs_work',
              'ready' if ready_lyrics or f.source_ass_active else 'unavailable',
              'done' if f.current_output and f.full_output else 'ready' if f.media_ready and has_lines else 'unavailable')
    captions=('素材与原文已准备' if stages[0]=='done' else '正在读取素材' if f.media_loading else '添加素材与原歌词',
              '词组已准备，仍需试听' if ready_lyrics else f'{f.unsegmented_count}句待分词' if has_lines else '原歌词保持，建议先审核',
              f'时间{f.timing_confirmed}/{f.line_count} · 读音{f.reading_confirmed}/{f.line_count}',
              '保留原ASS样式与特效' if f.source_ass_active else '检查字体、接唱与安全区',
              '整片已生成' if f.current_output and f.full_output else '已有样片，可继续压制' if f.current_output else '先看样片，再压制整片')

    def result(key, heading, detail, primary, *secondary):
        return Decision(key, heading, detail, primary, tuple(secondary), stages, captions)

    if f.inline_pending:
        return result('pending_edit', '本句还有未采用的编辑预览',
                      '先应用或取消这份预览，再继续其他步骤；原工程仍然保留。',
                      Action('pending_edit', '回到本句编辑预览', 2))

    if f.media_loading:
        return result('media_loading', '正在读取素材',
                      '可以先准备原歌词，读取完成后继续试听和校轴。', ORIGINAL)
    if not f.media_ready:
        if f.media_selected:
            return result('media_missing', '原素材需要重新定位',
                          '已有歌词与人工校准保留；可以先改字，试听与压制需要可用素材。',
                          RELOCATE_MEDIA, READING if has_lines else ORIGINAL)
        return result('no_media', '先添加视频或音频',
                      '已有歌词可以保留；也可以先打开工程或离线练习。', ADD_MEDIA, ORIGINAL)
    if f.suggestion_count:
        return result('suggestions', '有建议等待审核',
                      f'{f.suggestion_count} 行建议尚未采用；人工内容继续保留。', REVIEW,
                      TIMING if has_lines else ORIGINAL)
    if f.recognition_pending:
        return result('recognition', '先核对识别原文',
                      '识别文字仍是草稿，核对后再加入字幕。',
                      Action('review_recognition', '继续核对识别原文', 1), ORIGINAL)
    if not has_lines:
        return result('no_lyrics', '准备正确的原歌词',
                      '每行一句；有原歌词时优先粘贴，没有时再识别。', ORIGINAL, RECOGNIZE)
    if f.task_running:
        return result('task_running', '后台任务正在处理',
                      '可以继续手工校对；不重复提交请求。', TIMING,
                      Action('tasks', '查看任务进度', 1))
    if f.source_ass_active:
        return result('raw_ass', '当前保留原ASS样式与特效',
                      '可以直接检查和导出；需要声稿注音时，再明确选择新的制作流程。',
                      EXPORT, DRAFT)
    if f.unsegmented_count:
        return result('unsegmented', '还有歌词没有分词',
                      f'{f.unsegmented_count} 句仍可先定唱词范围，再分词或生成建议。',
                      SEGMENT, Action('resume_draft', '继续上次初稿', 1) if f.resumable_draft else DRAFT)
    if f.timing_confirmed < f.line_count:
        return result('timing', '试听并校准演唱时间',
                      f'时间确认 {f.timing_confirmed}/{f.line_count}；保存作品与确认时间分别记录。',
                      TIMING, READING)
    if f.reading_confirmed < f.line_count:
        return result('reading', '核对假名与实际唱法',
                      f'读音确认 {f.reading_confirmed}/{f.line_count}；采用建议后仍需试听确认。',
                      READING, STYLE)
    return result('ready', '歌词校对已确认',
                  '用当前视频检查接唱、注音和字体，再看样片与导出。', STYLE, EXPORT,
                  Action('draft_options', '重新生成初稿…', 1))


def primary_for_stage(decision, stage, *, current_output=False):
    if decision.key in ('ready','raw_ass'):
        if stage==4 and current_output:return PLAY_OUTPUT
        if stage>=3:return EXPORT
    return decision.primary


