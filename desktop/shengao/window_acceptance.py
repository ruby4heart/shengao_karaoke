"""Window checks in an own offscreen instance: window sizes of real screens,
save and reopen, failure recovery and render cancel.

Run normally and with ``QT_SCALE_FACTOR=1.5`` (``scripts/run-window-checks.py``
does both).  Everything happens in a window this process creates, with its own
settings folder inside the output folder; the user's desktop, projects and
settings are never touched.

  python desktop/main.py --window-check --output tmp/window-check
"""
from pathlib import Path
import argparse, json, os, sys, time, traceback

from .window_size import DEFAULT, MINIMUM, available, startup_geometry

# Physical screen size and Windows display scale; each gets the size the app
# opens with on that screen and the maximised size.
SCREENS = (
    ('1920×1080 · 100%', 1920, 1080, 1.0),
    ('1366×768 · 100%', 1366, 768, 1.0),
    ('1920×1080 · 125%', 1920, 1080, 1.25),
    ('1920×1080 · 150%', 1920, 1080, 1.5),
    ('1366×768 · 125%', 1366, 768, 1.25),
    ('1366×768 · 150%', 1366, 768, 1.5),
    ('2560×1440 · 150%', 2560, 1440, 1.5),
    ('3840×2160 · 150%', 3840, 2160, 1.5),
)
STAGES = ('开始', '歌词', '校准', '设计', '导出')
TITLES = {
    'demo_opens': '离线练习工程可以打开',
    'save_writes_project': '保存写出工程并标记为已保存',
    'reopen_in_new_instance': '新开一个实例重开工程',
    'reopen_same_content': '重开后的内容与保存时完全一致',
    'reopen_restores_place': '重开后回到保存时编辑的句子和词',
    'save_failure_reported': '保存失败时说明原因，返回失败',
    'save_failure_keeps_edits': '保存失败后修改仍在窗口中、仍标记为未保存',
    'save_after_failure': '换个位置后可以正常保存',
    'recovery_record_written': '未保存的修改写入自动恢复记录',
    'recovery_restores_edits': '模拟崩溃后新实例恢复全部修改',
    'recovery_restores_place': '恢复后回到崩溃前编辑的词',
    'recovery_stays_unsaved': '恢复的工程标记为未保存，提醒另存',
    'damaged_recovery_reported': '损坏的恢复记录给出说明，不弹窗',
    'damaged_recovery_set_aside': '损坏的恢复记录被另存，原位置清空',
    'damaged_recovery_told_once': '同一份损坏记录不会再次提示',
    'render_cancel_started': '压制任务开始后可以取消',
    'render_cancel_finished': '取消后任务结束为“已取消”',
    'render_cancel_no_output': '取消后没有半成品、没有临时文件夹',
    'render_cancel_recorded': '任务记录写为“已取消”',
    'render_queue_continues': '取消所选任务后，排在后面的任务照常完成',
}


def layout_cases():
    """[(key, label, minimum, size)] for every screen, plus the smallest allowed window."""
    cases = []
    for label, width, height, scale in SCREENS:
        area = available(width, height, scale); minimum, size = startup_geometry(*area)
        key = f'{width}x{height}-{round(scale * 100)}'
        cases.append((key + '-start', f'{label} 打开时 {size[0]}×{size[1]}', minimum, size))
        if area != size: cases.append((key + '-max', f'{label} 最大化 {area[0]}×{area[1]}', minimum, area))
    cases.append(('minimum', f'最小窗口 {MINIMUM[0]}×{MINIMUM[1]}', MINIMUM, MINIMUM))
    return cases


def _name(widget):
    text = widget.text() if hasattr(widget, 'text') else ''
    return (text or widget.toolTip() or widget.objectName() or type(widget).__name__).replace('&', '').splitlines()[0][:24]


def inspect(window, stage):
    """Problems a person would see on this step at the current window size."""
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtWidgets import QAbstractButton, QLabel, QScrollArea, QToolButton
    from .widgets import ElidedLabel
    problems = []; page = window.pages.widget(stage); step = f'第 {stage + 1} 步“{STAGES[stage]}”'
    if isinstance(page, QScrollArea) and page.horizontalScrollBar().maximum() > 0:
        problems.append(f'{step}需要左右滚动 {page.horizontalScrollBar().maximum()} 像素才能看全')
    buttons = [b for b in window.findChildren(QAbstractButton) if b.isVisible() and b.window() is window]
    for b in buttons:
        r = QRect(b.mapTo(window, QPoint(0, 0)), b.size())
        if r.left() < 0 or r.right() > window.width():
            problems.append(f'{step}按钮“{_name(b)}”超出窗口左右边缘')
        text = b.text().replace('&', '')
        if text and '\n' not in text:
            need = b.fontMetrics().horizontalAdvance(text); picture = b.iconSize().width() if not b.icon().isNull() else 0
            style = b.toolButtonStyle() if isinstance(b, QToolButton) else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            if style == Qt.ToolButtonStyle.ToolButtonTextUnderIcon: need = max(need, picture)    # picture above the text
            elif style == Qt.ToolButtonStyle.ToolButtonIconOnly: need = picture
            elif style != Qt.ToolButtonStyle.ToolButtonTextOnly: need += picture
            if b.width() < need: problems.append(f'{step}按钮“{_name(b)}”文字显示不全（宽 {b.width()}，需要 {need}）')
    for label in window.findChildren(QLabel):
        if isinstance(label, ElidedLabel) or not label.isVisible() or label.window() is not window or label.wordWrap() or not label.text() or label.textFormat() == Qt.TextFormat.RichText: continue
        text = label.text()
        if '\n' in text or '<' in text: continue
        need = label.fontMetrics().horizontalAdvance(text)
        if label.width() + 1 < need and label.minimumSizeHint().width() > label.width():
            problems.append(f'{step}文字“{text[:16]}”显示不全')
    siblings = {}
    for b in buttons: siblings.setdefault(id(b.parentWidget()), []).append(b)
    for group in siblings.values():
        for i, a in enumerate(group):
            for c in group[i + 1:]:
                if a.geometry().intersected(c.geometry()).width() > 1 and a.geometry().intersected(c.geometry()).height() > 1:
                    problems.append(f'{step}按钮“{_name(a)}”和“{_name(c)}”互相遮挡')
    if stage == 2:
        tl = window.timeline
        if not tl.isVisible() or tl.visibleRegion().boundingRect().height() < tl.height() or tl.height() < 120:
            problems.append(f'{step}时间轴被遮挡或太矮（高 {tl.height()}）')
        if not window.calibrate_footer.isVisible(): problems.append(f'{step}底部的校准按钮不可见')
    if stage in (2, 3):
        pb = window.playback
        if not pb.isVisible() or pb.width() < 240 or pb.height() < 135:
            problems.append(f'{step}视频预览不可见或太小（{pb.width()}×{pb.height()}）')
    if stage == 4:
        for button in (window.sample_button, window.encode_button):
            if isinstance(page, QScrollArea): page.ensureWidgetVisible(button)
        for button in (window.sample_button, window.encode_button):
            if not button.isVisible() or button.visibleRegion().boundingRect().height() < min(30, button.height()):
                problems.append(f'{step}“{_name(button)}”无法完整显示')
    return problems


def check_layout(app, window, out, check, wait, cases=None):
    """Every step at every size; all problems are collected before any check fails."""
    def settle(ms=60): wait(lambda: False, ms)
    results = []; navigation_open = window.workflow_toggle.isChecked()
    for key, label, minimum, size in (cases or layout_cases()):
        window.setMinimumSize(*minimum); window.resize(*size); settle()
        problems = []
        if (window.width(), window.height()) != tuple(size):
            problems.append(f'窗口无法缩小到 {size[0]}×{size[1]}（实际 {window.width()}×{window.height()}），会超出屏幕')
        for stage in range(5):
            window.set_stage(stage); settle(); found = inspect(window, stage)
            if found: window.grab().save(str(out / f'window-{key}-stage-{stage + 1}.png'))
            problems += found
        if not window.workflow_toggle.isChecked(): window.workflow_toggle.click(); settle()
        clipped = [b.text().splitlines()[0] for b in window.steps if not b.isVisible() or b.visibleRegion().boundingRect().height() < b.height()]
        if clipped: problems.append('展开步骤导航时“' + '”“'.join(clipped) + '”显示不全')
        if window.workflow_toggle.isChecked() != navigation_open: window.workflow_toggle.click(); settle()
        if not problems: window.grab().scaledToWidth(min(1200, window.grab().width())).save(str(out / f'window-{key}.png'))
        results.append({'key': key, 'label': label, 'size': list(size), 'minimum': list(minimum),
                        'device_pixel_ratio': window.devicePixelRatioF(), 'problems': problems})
    (out / 'window-layout.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    window.setMinimumSize(*MINIMUM); window.resize(*DEFAULT); settle()
    for row in results: check(f'layout_{row["key"]}', not row['problems'])
    return results


def _answer_question(app, parent, yes=True, tries=200):
    """Answer the next yes/no question box ``parent`` shows (the test's own window)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    def answer(left=tries):
        box = next((b for b in parent.findChildren(QMessageBox) if b.isVisible()), None)
        if box is None:
            if left: QTimer.singleShot(25, lambda: answer(left - 1))
            return
        box.button(QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No).click()
    QTimer.singleShot(25, answer)


def _new_window(StudioWindow, home, size=(1256, 648)):
    other = StudioWindow(home=home, test=True); other.playback.audio.setMuted(True)
    other.resize(*size); other.show()
    return other


def check_save_reopen(app, StudioWindow, window, out, check, wait):
    window.open_demo()
    check('demo_opens', bool(window.project.lines) and Path(window.project.media or '').is_file()
          and wait(lambda: window.analysis_job is None and window.project.duration > 0, 30000))
    window.edit('窗口检查：译文', lambda p: setattr(p.lines[0], 'translation', '窗口检查译文'))
    window.select_target(1, -1)
    path = out / '窗口检查.sgproj'; window.path = path
    check('save_writes_project', window.save() and path.is_file() and window.history.saved == window.project.to_dict())
    other = _new_window(StudioWindow, window.home)
    try:
        check('reopen_in_new_instance', other.open_path(path) and other.path == path)
        wait(lambda: other.analysis_job is None and other.project.duration > 0, 30000)
        check('reopen_same_content', other.project.to_dict() == window.project.to_dict())
        check('reopen_restores_place', other.current == window.current and other.timeline.word == 1)
    finally:
        other.close(); app.processEvents()
    return path


def check_recovery(app, StudioWindow, window, out, check, wait, path):
    # Saving into a "folder" that is really a file fails the same way on every system.
    blocker = out / '不是文件夹.txt'; blocker.write_text('占位', encoding='utf-8')
    window.edit('窗口检查：未保存的修改', lambda p: setattr(p.lines[0], 'translation', '保存失败前的修改'))
    edited = window.project.to_dict(); window.path = blocker / '放不进去.sgproj'
    saved = window.save(); status = window.status.text()
    check('save_failure_reported', saved is False and '保存失败' in status and '当前修改仍在窗口中' in status)
    check('save_failure_keeps_edits', window.project.to_dict() == edited and window.history.saved != edited)
    window.path = path; check('save_after_failure', window.save() and window.history.saved == edited)
    # Crash recovery: unsaved edits reach the recovery record; a new instance offers them.
    window.edit('窗口检查：崩溃前的修改', lambda p: setattr(p.lines[0], 'translation', '崩溃前没来得及保存'))
    window.select_target(2, -1); window.save_recovery(); crashed = window.project.to_dict()
    check('recovery_record_written', window.recovery_path().is_file())
    other = _new_window(StudioWindow, window.home)
    try:
        _answer_question(app, other, yes=True); other.offer_recovery()
        wait(lambda: other.analysis_job is None and other.project.duration > 0, 30000)
        check('recovery_restores_edits', other.project.to_dict() == crashed)
        check('recovery_restores_place', other.current == 0 and other.timeline.word == 2)
        check('recovery_stays_unsaved', other.history.saved != other.project.to_dict())
    finally:
        other.close(); app.processEvents()
    window.save(); window.clear_recovery()
    # A damaged record is explained once and set aside, never offered or asked about again.
    from PySide6.QtWidgets import QMessageBox
    home = out / 'home-damaged-recovery'; home.mkdir(parents=True, exist_ok=True)
    record = home / 'desktop-recovery.json'; record.write_text('{"project": [没写完', encoding='utf-8')
    other = _new_window(StudioWindow, home)
    try:
        other.offer_recovery(); app.processEvents(); status = other.status.text()
        asked = any(b.isVisible() for b in other.findChildren(QMessageBox))
        check('damaged_recovery_reported', '无法读取' in status and '不会再提示' in status and not asked)
        kept = list(home.glob('desktop-recovery.damaged-*.json'))
        check('damaged_recovery_set_aside', not record.exists() and len(kept) == 1)
        other.message('—'); other.offer_recovery(); app.processEvents()
        check('damaged_recovery_told_once', other.status.text() == '—' and len(list(home.glob('desktop-recovery.damaged-*.json'))) == 1)
    finally:
        other.close(); app.processEvents()


def check_render_cancel(app, window, out, check, wait):
    from PySide6.QtCore import Qt
    from .encode import EncodeOptions
    from .render_queue import STAGE_PREFIX
    folder = out / '压制取消'; folder.mkdir(parents=True, exist_ok=True)
    def leftovers(): return [p.name for p in folder.iterdir() if p.name.startswith(STAGE_PREFIX)]
    first = folder / '取消的成品.mp4'
    task = window.encode_to(EncodeOptions(str(first), size='1080p', quality='high'))
    check('render_cancel_started', task is not None and wait(lambda: bool(task.stage) or task.done, 30000) and not task.done)
    window.cancel_renders()
    check('render_cancel_finished', wait(lambda: task.done and window.local_job is None, 60000) and task.state == 'cancelled')
    check('render_cancel_no_output', not first.exists() and not leftovers() and not Path(task.stage).exists())
    record = json.loads((window.home / 'desktop-renders' / f'{task.id}.json').read_text(encoding='utf-8'))
    check('render_cancel_recorded', record['state'] == 'cancelled' and 'pid' not in record)
    a = window.encode_to(EncodeOptions(str(folder / '取消所选.mp4'), size='1080p', quality='high'))
    b = window.encode_to(EncodeOptions(str(folder / '后续样片.mp4'), 1000, 2000))
    wait(lambda: bool(a.stage) or a.done, 30000)
    for row in range(window.render_list.count()):
        if window.render_list.item(row).data(Qt.ItemDataRole.UserRole) == a.id: window.render_list.setCurrentRow(row)
    window.cancel_selected_render()
    finished = wait(lambda: b.done and window.local_job is None, 90000)
    check('render_queue_continues', finished and a.state == 'cancelled' and b.state == 'completed'
          and Path(b.options.output).is_file() and not (folder / '取消所选.mp4').exists() and not leftovers())


def exercise(app, StudioWindow, out, check, wait, cases=None):
    """All four groups in one window (used by tests); stops at the first failed check."""
    out = Path(out); window = _new_window(StudioWindow, out / 'home', DEFAULT)
    try:
        path = check_save_reopen(app, StudioWindow, window, out, check, wait)
        check_recovery(app, StudioWindow, window, out, check, wait, path)
        check_render_cancel(app, window, out, check, wait)
        check_layout(app, window, out, check, wait, cases)
    finally:
        window.close(); app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--window-check', action='store_true'); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from .app import StudioWindow
    from .gui_gc import install
    from .theme import STYLE
    app = QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE); install(app)
    checks = []; groups = []; started = time.time()
    def check(name, condition):
        checks.append({'name': name, 'title': TITLES.get(name, ''), 'passed': bool(condition)})
        if not condition: raise AssertionError(name)
    def wait(fn, timeout=10000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            app.processEvents(); QTest.qWait(25)
            if fn(): return True
        return False
    window = _new_window(StudioWindow, out / 'home', DEFAULT); layout = []
    def group(title, fn):
        try: value = fn(); groups.append({'title': title, 'completed': True}); return value
        except Exception as error:
            groups.append({'title': title, 'completed': False, 'error': traceback.format_exc() if not isinstance(error, AssertionError) else ''})
            return None
    try:
        path = group('保存与重开', lambda: check_save_reopen(app, StudioWindow, window, out, check, wait))
        group('失败恢复', lambda: check_recovery(app, StudioWindow, window, out, check, wait, path or out / '窗口检查.sgproj'))
        group('压制取消', lambda: check_render_cancel(app, window, out, check, wait))
        layout = group('窗口尺寸', lambda: check_layout(app, window, out, check, wait)) or []
    finally:
        passed = bool(checks) and all(c['passed'] for c in checks) and all(g['completed'] for g in groups)
        report = {'passed': passed, 'checks': checks, 'groups': groups, 'layout': layout or _saved_layout(out),
                  'device_pixel_ratio': window.devicePixelRatioF(), 'scale_factor': os.environ.get('QT_SCALE_FACTOR', ''),
                  'platform': app.platformName(), 'runtime': 'standalone' if getattr(sys, 'frozen', False) else 'development',
                  'seconds': round(time.time() - started, 1), 'last_status': window.status.text()}
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.close(); app.processEvents()
    print(json.dumps({'ok': passed, 'checks': len(checks), 'output': str(out)}, ensure_ascii=False))
    return 0 if passed else 1


def _saved_layout(out):
    try: return json.loads((out / 'window-layout.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return []
