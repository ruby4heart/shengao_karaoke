"""File-based native IPC. Requests/results never contain API keys."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys

from . import api
from .convert import annotation_suggestion, eleven_lines, mai_lines
from .media import extract
from .model import LyricLine,Unit, align_characters, plain_ass
from .settings import Settings, atomic_json
from .continuity import continuous_result,DEFAULT_GAP_MS


def fingerprint(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            digest.update(chunk)
    return digest.hexdigest()


def alignment_suggestions(lines,raw,start=0):
    """Replay raw cached characters locally, before applying timing preferences."""
    from .analysis import aligned_words
    units=align_characters('\n'.join(line.text for line in lines),raw.get('characters',[]),start)
    suggestions=[];offset=0
    for line in lines:
        selected=[];length=0
        while offset<len(units) and length<len(line.text):
            unit=units[offset]
            if length+len(unit.text)>len(line.text):raise ValueError('对齐字符跨越歌词分行边界')
            selected.append(unit);length+=len(unit.text);offset+=1
        if ''.join(u.text for u in selected)!=line.text:raise ValueError('时间对齐结果的歌词分行不一致')
        if offset<len(units) and units[offset].text=='\n':offset+=1
        value=LyricLine(line.id,line.text,selected[0].start,max(selected[-1].end,selected[0].start+10),selected,line.kana,line.romaji,line.translation)
        from .provenance import group_basis
        value.timing_origin=group_basis(selected,value.start,value.end,'character_alignment_envelope')
        value=aligned_words(value,line);value.validate();suggestions.append(value.to_dict())
    return suggestions


def timing_result(result,request):
    result=continuous_result(result,request.get('gap_ms',0),request.get('join_lines',False))
    rules=request.get('romanization_rules')
    if rules is not None and request.get('action') in {'match','transcribe_match','align'}:
        from .romanization import apply_rules,validate_rules
        validate_rules(rules)
        for data in result.get('suggestions',[]):
            if data.get('match',{}).get('status')=='protected':continue
            line=LyricLine.from_dict(data)
            indices=[i for i,u in enumerate(line.units) if not u.reading_options.get('romaji')]
            value=apply_rules(line,indices,rules)['line'];data.update(value.to_dict())
            for choice in data.get('match',{}).get('candidates',[]):
                candidate=LyricLine(line.id,line.text,choice['start'],choice['end'],[Unit(**u) for u in choice['units']])
                candidate=apply_rules(candidate,[i for i,u in enumerate(candidate.units) if not u.reading_options.get('romaji')],rules)['line']
                choice['units']=candidate.to_dict()['units']
    return result


async def operation(request, root, report):
    settings=Settings(root)
    action=request['action']
    if action=='settings':
        return {'settings':settings.public()}
    if action=='configure':
        provider=request['provider']
        options={k:request[k] for k in ('endpoint','model') if k in request}
        if provider=='mai' and options.get('endpoint'):
            api.azure_url(options['endpoint'])
        if request.get('forget',False):
            settings.forget(provider)
        else:
            settings.save(provider,request.get('key',''),**options)
        return {'settings':settings.public()}
    if action=='draft':
        from .draft import run
        return await run(request,root,report,operation)
    if action=='chorus_reuse':
        from .chorus_workflow import run
        return await run(request,root,report)
    if action=='confirm_recognition':
        from .recognition import confirmed_lines,validate
        draft=request['recognition_draft'];transcript=request['transcript'];validate(draft,transcript,require_text=True)
        media=Path(request['media'])
        if not media.is_file():raise ValueError('原素材不存在，请先重新定位')
        stamp={'path':os.path.normcase(str(media.resolve())),'size':media.stat().st_size,'modified_ns':media.stat().st_mtime_ns}
        if stamp!=draft['media_stamp']:raise ValueError('识别草稿对应的素材版本不同，请切回原素材')
        if draft.get('media_fingerprint') and await asyncio.to_thread(fingerprint,media)!=draft['media_fingerprint']:
            raise ValueError('素材内容已变化，未生成新的歌词；原文草稿保留')
        report('confirming_text','在本机按已核对原文生成可编辑粗稿；不重新上传')
        return await asyncio.to_thread(confirmed_lines,draft,transcript,request.get('romanization_rules'))
    if action not in {'transcribe','align','annotate','export','match','transcribe_match','segment','refine'}:
        raise ValueError('不支持的后台操作')
    lines=[LyricLine.from_dict(line) for line in request.get('lines',[])]
    if action=='export':
        from .export import export_file
        return export_file(lines,request)
    if action=='refine':
        from .analysis import analyze_line,annotation_input,reading_protected as protected
        if not lines:raise ValueError('请先选择要二次校对的歌词')
        transcript=[LyricLine.from_dict(item) for item in request.get('transcript',[])]
        report('analyzing','结合转录、原歌词和词典分析读音及短空隙；原文保持不变')
        values=[];protected_ids=[]
        for line in lines:
            value,skipped=await asyncio.to_thread(analyze_line,line,transcript,request.get('gap_ms',0),request.get('preserve_legacy',False),request.get('preserve_manual',True),request.get('romanization_rules'));values.append(value)
            if not skipped and transcript:
                value.reading_review['source_verified']=bool(request.get('transcript_verified'))
                if not request.get('transcript_verified') and not request.get('manual_source'):
                    value.reading_review['notice']+=' 旧转录未记录媒体版本，请确认文件未被替换。'
            if skipped:protected_ids.append(line.id)
        if request.get('use_llm'):
            key=settings.key('deepseek')
            if not key:raise ValueError('请先在 API 设置中填写 DeepSeek 密钥，或选择离线分析')
            config=settings.read().get('deepseek',{});diagnostics={}
            context=[LyricLine.from_dict(item) for item in request.get('context',[])] or lines
            pending=[]
            for index,value in enumerate(values):
                if protected(value):continue
                position=next((i for i,item in enumerate(context) if item.id==value.id),-1)
                neighbors=(context[position-1].text if position>0 else '',context[position+1].text if 0<=position<len(context)-1 else '')
                payload=await asyncio.to_thread(annotation_input,value,transcript,neighbors)
                if len(value.text)>6000:raise ValueError('单行超过 6000 字，请拆成歌词行后复核')
                pending.append((index,payload))
            batches=[];batch=[];length=0
            for item in pending:
                if batch and (len(batch)>=30 or length+len(item[1]['text'])>6000):batches.append(batch);batch=[];length=0
                batch.append(item);length+=len(item[1]['text'])
            if batch:batches.append(batch)
            completed=[];warnings=[]
            for batch_number,batch in enumerate(batches):
                payloads=[payload for _,payload in batch];model=config.get('model') or 'deepseek-flash'
                signature=hashlib.sha256(json.dumps({'model':model,'lines':payloads,'version':1},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                cache=settings.root/'readings'/f'{signature}.json'
                report('annotating',f'DeepSeek 结合转录复核第 {batch_number+1}/{len(batches)} 批；已完成批次会缓存')
                try:
                    if cache.is_file():annotations=api.validate_annotations(json.loads(cache.read_text(encoding='utf-8')),payloads)
                    else:
                        annotations=await api.deepseek_annotate(payloads,key,model,diagnostics)
                        cache.parent.mkdir(parents=True,exist_ok=True);atomic_json(cache,{'lines':annotations})
                except api.ApiError as error:
                    if not completed:raise
                    warnings.append('后续批次失败：'+str(error)+'；已完成结果已保留，未自动重试。')
                    break
                for (index,_),annotation in zip(batch,annotations):
                    value=values[index];result=annotation_suggestion(value,annotation,request.get('romanization_rules'))
                    result.reading_review['method']='deepseek+transcript'
                    for word,group,unit in zip(result.reading_review.get('words',[]),annotation['groups'],result.units):
                        word['suggested']=unit.kana;word['deepseek_suggested']=group['kana'];word['suggested_romaji']=unit.romaji
                        word['changed']=word['before']!=unit.kana or word.get('before_romaji','')!=unit.romaji
                        word['basis']='manual' if unit.reading_source=='manual' else 'deepseek'
                        word['reason']=group.get('reason','')
                    values[index]=result;completed.append(index)
            if warnings:
                return {'suggestions':[values[i].to_dict() for i in completed],'review_required':True,'partial':True,
                        'message':f'完成 {len(completed)}/{len(pending)} 行。'+warnings[0],
                        'completed_lines':len(completed),'requested_lines':len(pending),'warnings':warnings,'diagnostics':diagnostics}
        return {'suggestions':[v.to_dict() for v in values],'protected_ids':protected_ids,'review_required':True,
                'local':not request.get('use_llm'),'transcript_used':bool(transcript),'analysis':'readings+gaps'}
    if action=='segment':
        from .japanese import segment_line
        if not lines:raise ValueError('请先选择原歌词')
        report('segmenting','正在本地按原歌词分词、生成假名；不使用转录空格')
        suggestions=[];protected=[]
        for line in lines:
            value,skipped=await asyncio.to_thread(segment_line,line,request.get('mode','words'),request.get('romanization_rules'))
            if not skipped and value.match.get('status')=='unmatched':value.match={}
            suggestions.append(value.to_dict())
            if skipped:protected.append(line.id)
        return timing_result({'suggestions':suggestions,'protected_ids':protected,'review_required':True,'local':True,
                'segmentation_mode':request.get('mode','words'),'dictionary':'Janome/IPADIC'},request)
    if action in {'match','transcribe_match'}:
        from .matching import match_lyrics
        if not lines:
            raise ValueError('请先粘贴普通歌词，每行一句，不需要 LRC 时间标签')
        if action=='transcribe_match':
            # Reuse the exact raw-transcription cache, independent of corrected lyrics.
            raw=await operation({**request,'action':'transcribe','lines':[]},root,report)
            transcript=raw['suggestions']
        else:
            raw={}
            transcript=request.get('transcript',[])
        report('matching','正在本机按顺序和文字相似度分行；粗轴仍需试听校准')
        try:
            result=await asyncio.to_thread(match_lyrics,lines,[LyricLine.from_dict(value) for value in transcript],request.get('match_range'),request.get('rematch_confirmed') is True)
            result=timing_result(result,request)
        except ValueError as error:
            if action=='transcribe_match':
                error.args=('转录已返回，但歌词匹配未完成：'+str(error)+'。可从“复用已有转录”读取结果，无需再次上传。',)
                error.transcript=transcript
                error.diagnostics=raw.get('diagnostics',{})
            raise
        return {**result,'transcript':transcript,'cached':raw.get('cached',False),
                'media_fingerprint':raw.get('media_fingerprint',''),
                'diagnostics':raw.get('diagnostics',{}),'original_api_result':raw.get('original_api_result',{})}
    provider=request.get('provider','elevenlabs') if action=='transcribe' else ('deepseek' if action=='annotate' else 'elevenlabs')
    key=settings.key(provider)
    if not key:
        raise ValueError('请先在 API 设置中配置 '+provider+' 密钥')
    if any(line.locked or any(unit.locked for unit in line.units) for line in lines):
        raise ValueError('选中范围包含已锁定歌词，请先取消锁定或调整选择')
    config=settings.read().get(provider,{})
    diagnostics={}
    if action=='annotate':
        report('annotating','DeepSeek 正在生成假名、罗马音和中文翻译；完成后需人工审核')
        from .analysis import annotation_input
        payloads=[annotation_input(line,[],('','')) if line.units else {'id':line.id,'text':line.text} for line in lines]
        annotations=await api.deepseek_annotate(payloads,key,
                                               config.get('model') or 'deepseek-flash',diagnostics)
        suggestions=[annotation_suggestion(line,annotation,request.get('romanization_rules')).to_dict() for line,annotation in zip(lines,annotations)]
        return {'suggestions':suggestions,'annotations':annotations,'diagnostics':diagnostics,'review_required':True}
    media=Path(request['media'])
    if not media.is_file():
        raise ValueError('请先打开有效的音视频文件')
    if action=='align' and not lines:
        raise ValueError('请选择至少一句已校对歌词')
    report('preparing','正在检查音频与缓存')
    audio_hash=await asyncio.to_thread(fingerprint,media)
    signature=json.dumps({'audio':audio_hash,'action':action,'provider':provider,
                          'endpoint':config.get('endpoint',''),'language':request.get('language','ja'),
                          'range_mode':request.get('range_mode','full'),
                          # Display-only edits must keep the pre-0.13 cache key:
                          # they do not change uploaded text or the audio range.
                          'lines':[{k:v for k,v in line.to_dict().items() if k not in {'display_start','display_end'}} for line in lines]},ensure_ascii=False,sort_keys=True)
    cache_id=hashlib.sha256(signature.encode()).hexdigest()
    cache=settings.root/'cache'/f'{cache_id}.json'
    if cache.exists() and not request.get('force',False):
        result=json.loads(cache.read_text(encoding='utf-8'))
        result['media_fingerprint']=audio_hash
        result['cached']=True
        if action=='align':
            raw=result.get('original_api_result',{})
            if raw.get('characters'):
                start=min(line.start for line in lines) if request.get('range_mode','full')=='selection' else 0
                result['suggestions']=alignment_suggestions(lines,raw,start)
            return timing_result(result,request)
        return result
    settings.root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='audio-',dir=settings.root) as folder:
        audio=Path(folder)/'audio.flac'
        report('extracting','正在本机提取音轨')
        if action=='align':
            # Local range alignment prevents repeated chorus sections being confused.
            if request.get('range_mode','full')=='selection':
                start=min(line.start for line in lines)
                end=max(line.end for line in lines)
                await extract(media,audio,start,end)
            else:
                start=0
                await extract(media,audio)
            text='\n'.join(line.text for line in lines)
            report('aligning','ElevenLabs 正在将所选歌词对齐到音频')
            raw=await api.eleven_align(audio,text,key,diagnostics)
            suggestions=alignment_suggestions(lines,raw,start)
        else:
            await extract(media,audio)
            report('transcribing','正在上传音频并等待识别结果')
            if provider=='elevenlabs':
                raw=await api.eleven_transcribe(audio,key,request.get('language','ja'),diagnostics)
                suggestions=[line.to_dict() for line in eleven_lines(raw)]
            elif provider=='mai':
                raw=await api.mai_transcribe(audio,key,config.get('endpoint',''),request.get('language','ja'),diagnostics)
                suggestions=[line.to_dict() for line in mai_lines(raw)]
            else:
                raise ValueError('不支持的识别服务')
        result={'suggestions':suggestions,'original_api_result':raw,'diagnostics':diagnostics,
                'review_required':True,'cached':False,'media_fingerprint':audio_hash}
        atomic_json(cache,result)
        return timing_result(result,request) if action=='align' else result


async def execute(request, root, result_path):
    progress_path=Path(str(result_path)+'.progress.json')
    cancel_path=Path(str(result_path)+'.cancel')
    def report(phase,message):
        atomic_json(progress_path,{'phase':phase,'message':message})
    report.task_dir=Path(result_path).resolve().parent
    task=asyncio.create_task(operation(request,root,report))
    try:
        while not task.done():
            if cancel_path.exists():
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                raise asyncio.CancelledError()
            await asyncio.wait({task},timeout=.25)
        result=await task
        atomic_json(result_path,{'ok':True,**result})
        report('done','后台处理完成，请检查建议结果')
    except asyncio.CancelledError:
        partial={}
        if request.get('action')=='draft':
            from .draft import saved_result
            partial=saved_result(request,root)
        elif request.get('action')=='chorus_reuse':
            from .chorus_workflow import saved_result
            partial=saved_result(request,root)
        message='本地已取消，复用读音及已完成声音结果保留，可继续未完成部分。' if request.get('action')=='chorus_reuse' else '已取消本地任务；已完成阶段保留，已提交的云端请求可能仍会计费'
        atomic_json(result_path,{'ok':bool(partial.get('suggestions')),'cancelled':True,**partial,
                                'message':message})
        report('cancelled','任务已取消')
    except (ValueError,KeyError,TypeError,OSError) as error:
        # ApiError messages are deliberately sanitized; never dump HTTP headers.
        message=str(error) if isinstance(error,ValueError) else '文件、配置或接口返回结构无效，请检查后重试'
        atomic_json(result_path,{'ok':False,'message':message,'exception':type(error).__name__,
                                'diagnostics':getattr(error,'diagnostics',{}),
                                **({'transcript':error.transcript} if hasattr(error,'transcript') else {})})
        report('error',message)
    except Exception as error:
        atomic_json(result_path,{'ok':False,'message':'后台处理失败，请检查文件与配置','exception':type(error).__name__})
        report('error','后台处理失败')
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    parser.add_argument('--result',required=True)
    parser.add_argument('--home')
    args=parser.parse_args()
    request=json.loads(sys.stdin.buffer.read().decode('utf-8') if args.request=='-' else Path(args.request).read_text(encoding='utf-8'))
    asyncio.run(execute(request,args.home,args.result))


if __name__=='__main__':
    main()
