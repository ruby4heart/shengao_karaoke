import copy
from test_reading_candidates_workflow import reading_window
from studio_backend.convert import annotation_suggestion
from studio_backend.translation import manual,info


def pending(w,kana='ひとけ'):
    old=w.line.to_dict();value=annotation_suggestion(w.line,{'groups':[{'text':u.text,'kana':kana if i==0 else u.kana,'romaji':u.romaji} for i,u in enumerate(w.line.units)],'translation':'AI 的候选译文'}).to_dict()
    w.pending={'action':'annotate','snapshots':{old['id']:old},'checks':copy.deepcopy(w.project.checks),'result':{'suggestions':[value]}}
    return value


def test_text_review_can_keep_fixed_and_manual_boundaries_and_undo(reading_window):
    w=reading_window;value=pending(w);before=w.project.to_dict();w.apply_suggestions([value])
    assert not w.pending and w.line.units[0].kana=='ひとけ' and w.line.units[0].highlights[1].start==1210
    assert w.line.units[0].highlights[1].fixed_edges==['start'] and not w.project.checks[w.line.id]['reading']
    w.undo();assert w.project.to_dict()==before


def test_text_review_rejects_forged_axis_and_keeps_result_for_review(reading_window):
    w=reading_window;value=pending(w);value['units'][0]['highlights'][1]['start']+=10;before=w.project.to_dict();w.apply_suggestions([value])
    assert w.pending and w.project.to_dict()==before and '固定边界' in w.status.text()


def test_late_reading_confirmation_change_rejects_old_text_result(reading_window):
    w=reading_window;value=pending(w);w.project.checks[w.line.id]['reading']=False;before=w.project.to_dict();w.apply_suggestions([value])
    assert w.pending and w.project.to_dict()==before and '0 行' in w.status.text()


def test_translation_only_suggestion_preserves_japanese_confirmation_and_human_translation(reading_window):
    w=reading_window;w.project.lines[0]=manual(w.line,'我的译文');w.refresh();value=pending(w,'にんき');w.apply_suggestions([value])
    assert not w.pending and w.line.translation=='我的译文' and info(w.line)['source']=='manual'
    assert w.line.reading_review['translation_suggestion']['text']=='AI 的候选译文'
    assert w.line.reviewed and w.project.checks[w.line.id]['reading']
