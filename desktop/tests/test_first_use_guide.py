"""The first-use guide and the in-app quick start say what the program really does:
shortcut tables, default settings, menu and button names and the project format
are read from a fresh window and the code (TODO 11.8)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / 'docs' / 'FIRST-USE-GUIDE.md'
QUICK = ROOT / 'desktop' / 'assets' / '快速开始.txt'


def text(path):
    return path.read_text(encoding='utf-8-sig')


def section(title):
    """Body of the guide section whose heading starts with ``title``, up to the next heading of the same level."""
    lines = text(GUIDE).splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r'#+ ', line) and line.lstrip('#').strip().startswith(title))
    level = len(lines[start]) - len(lines[start].lstrip('#'))
    body = []
    for line in lines[start + 1:]:
        if re.match(r'#{1,%d} ' % level, line): break
        body.append(line)
    return body


def table(title):
    """First column -> second column of the table in a section."""
    rows = {}
    for line in section(title):
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if not line.startswith('|') or len(cells) < 2 or set(cells[0]) <= set('-') or cells[0] in ('设置', '按键', '作用', '操作'): continue
        rows[cells[0]] = cells[1]
    return rows


def keys(cell):
    return set(re.findall(r'`([^`]+)`', cell))


@pytest.fixture
def window(qapp, tmp_path):
    from shengao.app import StudioWindow
    w = StudioWindow(home=tmp_path / 'home', test=True)
    yield w
    w.close()


def test_window_shortcut_table_is_every_window_shortcut(window):
    documented = set()
    for cell in table('窗口快捷键'):
        documented |= {key.replace('Ctrl+Enter', 'Ctrl+Return') for key in keys(cell)}   # the main-keyboard Enter is Return to Qt
    live = {action.shortcut().toString() for action in window.actions() if not action.shortcut().isEmpty()}
    assert documented == live


@pytest.mark.parametrize('title,bindings', [('时间轴键位', 'AUDIO'), ('Medusa 小键盘键位', 'ALWAYS')])
def test_timeline_key_tables_are_the_default_bindings(title, bindings):
    from shengao import aeg_hotkeys
    from shengao.audio_shortcuts import COMMANDS
    expected = {}
    for short, name in COMMANDS.values():
        found = {key for key, action in getattr(aeg_hotkeys, bindings).items() if action == short}
        if found: expected[name] = found
    assert {name: keys(cell) for name, cell in table(title).items()} == expected


def test_default_settings_table_is_what_a_fresh_window_shows(window):
    from studio_backend import romanization
    from shengao.render_plan import SAMPLE_MAX, SAMPLE_MIN, output_folder
    from shengao.preview_preferences import PreviewPreferencesDialog
    from shengao.network_dialog import PREFERENCE
    rows = table('5. 默认设置')
    combo = lambda box: [box.itemText(i) for i in range(box.count())]
    assert rows['顶部五步流程'] == ('展开' if window.workflow_toggle.isChecked() else '收起')
    assert rows['校准页视图'] == window.view_choice.currentText()
    assert rows['时间轴显示'] == window.audio_view.currentText()
    assert rows['本次确认'] == window.confirmation_kind.currentText()
    assert rows['播放速度'] == window.speed.currentText()
    assert all(item in '\n'.join(section('5. 默认设置')) for item in combo(window.speed))
    assert rows['音量'] == str(window.volume.value())
    assert rows['预览字幕'] == ('显示' if window.subtitle_toggle.isChecked() else '隐藏')
    assert rows['自动恢复记录'] == f'每 {window.autosave.interval() // 1000} 秒一次'
    style = window.project.style
    assert rows['新工程样式'].startswith(style.name + '：' + style.font)
    for part in (f'正文 {style.size}', f'假名 {style.ruby_size}', f'罗马音 {style.romaji_size}', f'译文 {style.translation_size}',
                 '白字' if style.color == '#ffffff' else style.color, '高亮 ' + style.highlight, window.display_mode.currentText()):
        assert part in rows['新工程样式'], part
    assert style.show_ruby and style.show_romaji and style.show_translation and '显示假名、罗马音和译文' in rows['新工程样式']
    assert romanization.DEFAULT == {'system': 'hepburn', 'long_vowels': 'literal', 'particles': True}
    assert all(part in rows['罗马音规则'] for part in ('Hepburn', '长音保留假名拼写（ou／oo 等）', '助词 は／へ／を 写作 wa／e／o'))
    assert rows['样片'] == f'{window.sample_mode.currentText()}，{window.sample_length.value():g} 秒（可设 {SAMPLE_MIN // 1000}–{SAMPLE_MAX // 1000} 秒）'
    for name, box in (('输出尺寸', window.output_size), ('画质', window.quality), ('编码器', window.encoder)):
        assert rows[name].startswith(box.currentText()), name
    assert all(item in rows['输出尺寸'] for item in combo(window.output_size))
    assert all(item in rows['画质'] for item in combo(window.quality))
    assert '显卡编码需要硬件与驱动支持' in rows['编码器'] and '显卡编码 · 需要硬件与驱动支持' in combo(window.encoder)
    assert output_folder('', None, '') in (str(Path.home() / 'Videos'), str(Path.home()))
    assert rows['预览用 GPU 缩小视频帧'].startswith('开启' if window.playback.canvas.gpu_enabled else '关闭')
    dialog = PreviewPreferencesDialog(window)
    assert rows['本地后台任务并行数'] == dialog.workers.currentText(); dialog.close()
    assert rows['联网前确认'].startswith('每次都问') and not window.preferences.data.get(PREFERENCE)


def test_steps_menus_and_buttons_named_in_the_guides_exist(window):
    from PySide6.QtWidgets import QAbstractButton, QPushButton
    steps = ' → '.join(step.title for step in window.steps)
    assert steps in text(GUIDE)
    menu = next(b for b in window.findChildren(QPushButton) if b.text() == '作品').menu()
    entries = {action.text() for action in menu.actions() if action.text()}
    for path in (GUIDE, QUICK):
        named = set(re.findall(r'作品 → ([^”）\s]+)', text(path)))
        assert named <= entries, (path.name, named - entries)
    assert re.findall(r'作品 → ([^”）\s]+)', text(GUIDE))
    buttons = {b.text() for b in window.findChildren(QAbstractButton)}
    for name in ('打开离线练习', '服务设置', '任务记录', '流程', '先看 12 秒样片', '导出字幕文件…', '导出成品视频', '更改…'):
        assert f'“{name}”' in text(GUIDE), name
        assert name in buttons, name
    assert '“打开离线练习”' in text(QUICK) and '作品 → 打开离线练习' not in text(QUICK)


def test_project_format_and_where_to_start_are_current():
    from shengao.project import SCHEMA
    assert f'本版保存第 {SCHEMA} 版工程，读取 1–{SCHEMA}' in text(QUICK)
    assert f'本版保存第 {SCHEMA} 版工程格式，可以读取第 1–{SCHEMA} 版' in text(GUIDE)
    assert '首次使用指南.md' in text(QUICK)
    assert '1.0 之前的功能版本' not in text(QUICK)          # the old to-do list is gone


def test_package_ships_the_guide_and_it_states_the_licence_limit():
    build = text(ROOT / 'scripts' / 'build-desktop.py')
    assert "root/'docs'/'FIRST-USE-GUIDE.md',package/'首次使用指南.md'" in build and '首次使用指南.md' in build.split('INDEPENDENT-STUDIO.txt')[1]
    assert "'首次使用指南.md'" in text(ROOT / 'scripts' / 'check-release.py')
    assert 'docs/FIRST-USE-GUIDE.md' in text(ROOT / 'scripts' / 'check-licenses.py')
    assert '非商业' in text(GUIDE) and 'FIRST-USE-GUIDE.md' in text(ROOT / 'README.md')
