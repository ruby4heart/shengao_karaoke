"""Exercise the actual workbench, temporary preview, adoption and undo."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel
from shengao.app import StudioWindow
from shengao.color_dialog import ColorDialog
from shengao.color_states import effective_profile
from shengao.project import Project,History,save_project,load_project
from studio_backend.model import LyricLine,Unit


def window(tmp_path):
    w=StudioWindow(home=tmp_path/'home',test=True)
    line=LyricLine('a','今日も歌う',1000,3000,[Unit('今日も歌う',1000,3000,kana='きょうもうたう',source='manual',locked=True)],reviewed=True,locked=True,display_start=0,display_end=4000)
    w.history=History(Project(lines=[line],checks={'a':{'reading':True}}));w.current=0;w.refresh();w.set_stage(3);w.show()
    return w


def test_real_preview_is_readonly_then_one_adoption_save_and_undo(qapp,tmp_path):
    w=window(tmp_path);before=w.project.to_dict();position=w.playback.canvas.position;observed={}
    def edit():
        d=next(v for v in w.findChildren(ColorDialog) if v.isVisible())
        d.state.setCurrentIndex(d.state.findData('sung'));d.fields['outline'].hex.setText('#ff0011');d.box_enabled.setChecked(True)
        observed['readonly']=w.project.to_dict()==before and w.playback.canvas.position==position
        d.previewRequested.emit('sung');qapp.processEvents()
        observed['preview']=any(label.pixmap() is not None and not label.pixmap().isNull() for label in d.findChildren(QLabel))
        d.accept_changes()
    QTimer.singleShot(20,edit);assert w.edit_color_states()
    assert observed=={'readonly':True,'preview':True}
    assert w.project.lines[0].to_dict()==before['lines'][0] and w.project.checks==before['checks'] and w.playback.canvas.position==position
    assert effective_profile(w.project.color_styles,'a')['layers']['lyrics']['sung']['outline']['color']=='#ff0011'
    path=tmp_path/'有配色.sgproj';save_project(w.project,path);assert load_project(path).to_dict()==w.project.to_dict()
    w.undo();assert w.project.to_dict()==before;w.close()


def test_cancel_and_late_colour_change_do_not_overwrite_current(qapp,tmp_path):
    w=window(tmp_path);before=w.project.to_dict()
    QTimer.singleShot(20,lambda:next(v for v in w.findChildren(ColorDialog) if v.isVisible()).reject())
    assert not w.edit_color_states() and w.project.to_dict()==before
    from shengao.color_states import default_profile,update_settings
    palette=default_profile(w.project.style)
    def late():
        d=next(v for v in w.findChildren(ColorDialog) if v.isVisible());d.fields['primary'].hex.setText('#ff0000')
        palette['layers']['lyrics']['waiting']['primary']['color']='#0000ff'
        w.edit('其他配色修改',lambda p:setattr(p,'color_styles',update_settings({},palette)));d.accept_changes()
    QTimer.singleShot(20,late);assert not w.edit_color_states()
    assert w.project.color_styles==update_settings({},palette)
    w.close()
