"""Preview a chosen reading while retaining usable human time boundaries."""
import copy
from .analysis import kana_only
from .japanese import morae,romaji,add_mora
from .provenance import remember
from .recalculation import inspect


def preview(original,index,kana,defaults=None):
    original.validate()
    if type(index) is not int or not 0<=index<len(original.units):raise ValueError('先选择一个词组。')
    unit=original.units[index]
    if original.locked or unit.locked:raise ValueError('已锁定内容不能改读音，请先解除锁定。')
    reading=kana_only(kana)
    if not reading:raise ValueError('候选须为实际日语假名，不能把汉字或中文当作读音。')
    value=copy.deepcopy(original)
    if reading==unit.kana:return {'line':value,'changed':False,'kept_boundaries':True,'before_count':len(unit.highlights),'after_count':len(unit.highlights)}
    target=value.units[index];parts=morae(reading)
    keep=bool(unit.highlights) and len(parts)==len(unit.highlights)
    sensitive={(p['unit'],p['highlight']) for p in inspect(original)['kept']}
    human=any(h.fixed_edges or (index,j) in sensitive for j,h in enumerate(unit.highlights))
    if human and not keep:
        raise ValueError(f'本词有人工或固定音节边界，候选会从 {len(unit.highlights)} 个音节变成 {len(parts)} 个。旧轴保持，请先手工拆合对应音节；不会自动清除这些边界。')
    remember(target)
    if keep:
        for h,part in zip(target.highlights,parts):remember(h);h.kana=part
    else:target.highlights=[]
    target.kana=reading;target.reading_source='manual'
    from .romanization import after_reading_change
    manual_romaji_kept=after_reading_change(unit,target,defaults)
    if not keep:add_mora(target)
    value.kana=''.join(u.kana for u in value.units);value.romaji=' '.join(u.romaji for u in value.units if u.romaji)
    value.reviewed=False;value.match={}
    value.reading_review['stale']=True
    records=value.reading_review.get('manual_choices',[])
    if not isinstance(records,list):records=[]
    value.reading_review['manual_choices']=[*records[-199:],{'word':index,'text':unit.text,'before':unit.kana,'chosen':reading,'kept_boundaries':keep}]
    value.validate()
    return {'line':value,'changed':True,'kept_boundaries':keep,'before_count':len(unit.highlights),'after_count':len(parts),'manual_romaji_kept':manual_romaji_kept}
