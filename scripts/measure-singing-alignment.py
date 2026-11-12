"""Measure line onset/tail accuracy of the local singing alignment against human labels.

Runs the app's own alignment engine (desktop/alignment_engine.py) on the
public PJS singing corpus with its human phoneme labels, twice per phrase:
once as before (no edge tags) and once with the model's optional breath (AP)
and release (EP) tags at free line edges. Nothing is downloaded or bundled;
point the script at local copies:

  .venv-align\\Scripts\\python scripts\\measure-singing-alignment.py ^
      --corpus D:\\data\\PJS_corpus_ver1.1 --labels D:\\data\\pjs-manual-labels\\lab

Line ranges imitate the app: "draft" jitters the human range like a coarse
transcript and pads it like automatic draft fitting (500 ms before, 1500 ms
after, never into a neighbour); "tight" is a hand-drawn line range a little
wider than the singing. Conditions add a fixed synthetic room or room+noise
so reverb tails can be compared. All randomness is seeded, so repeated runs
give the same ranges. The whole corpus takes roughly 10-20 minutes per
scenario and condition on a laptop CPU; --songs limits it.

--bundled needs no corpus: it measures the public PJS056 song and human labels
that ship with the app (desktop/assets/alignment-demo), repeating each phrase
with several seeded ranges (--trials, default 20) for every scenario and
condition. It also runs the app's own line-tail check on the results to show
how many badly placed line tails it flags and whether its candidates would
have helped; the check never changes timing by itself.

  .venv-align\\Scripts\\python scripts\\measure-singing-alignment.py --bundled
"""
from pathlib import Path
import argparse,glob,json,random,sys,tempfile,wave
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'));sys.path.insert(0,str(ROOT/'backend'))
BUNDLED=ROOT/'desktop/assets/alignment-demo'
import numpy as np
import alignment_engine as engine

VOWELS={'a','i','u','e','o'}
CONDITIONS={'clean':None,'room':(1.2,0.0,2,None),'noisy-room':(0.9,3.0,4,30.0)}


def reverse_dictionary(path):
    value={}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            k,v=line.split('\t',1);value.setdefault(tuple(v.split()),k)
    return value


def phrases(lab,reverse):
    """Split HTK labels at pau/br/sil into phrases of dictionary morae (ms)."""
    rows=[]
    for line in Path(lab).read_text(encoding='utf-8').splitlines():
        if line.strip():
            a,b,p=line.split();rows.append((int(a)/10000,int(b)/10000,p))
    out=[];cur=[];skip=False;pend=[]
    def close():
        nonlocal cur,skip
        if cur and not skip:out.append(cur)
        cur=[];skip=False
    for i,(a,b,p) in enumerate(rows):
        if p in ('pau','br','sil'):
            if pend:skip=True;pend=[]
            close();continue
        q=p.lower() if p in ('U','I','O') else p
        if q=='cl':
            nxt=rows[i+1][2].lower() if i+1<len(rows) else 'pau'
            if pend or nxt in VOWELS or not cur:skip=True
            pend=[];cur.append([(a,b,'cl')]);continue
        if q=='N':
            if pend:skip=True;pend=[]
            cur.append([(a,b,'N')]);continue
        pend.append((a,b,q))
        if q in VOWELS:cur.append(pend);pend=[]
    if pend:skip=True
    close()
    result=[]
    for phrase in out:
        keys=[reverse.get(tuple(x[2] for x in m)) for m in phrase]
        if None not in keys:result.append([{'key':k,'start':m[0][0],'end':m[-1][1]} for k,m in zip(keys,phrase)])
    return result


def read_wav(path):
    with wave.open(str(path),'rb') as f:
        if f.getframerate()!=48000:raise SystemExit(f'{path}: expected 48 kHz audio')
        width=f.getsampwidth();channels=f.getnchannels();raw=f.readframes(f.getnframes())
    if width==3:
        b=np.frombuffer(raw,dtype=np.uint8).reshape(-1,3).astype(np.int32)
        x=(b[:,0]|(b[:,1]<<8)|(b[:,2]<<16));x=np.where(x>=1<<23,x-(1<<24),x)/float(1<<23)
    elif width==2:x=np.frombuffer(raw,dtype='<i2')/32768.0
    else:raise SystemExit(f'{path}: unsupported sample width')
    return x.reshape(-1,channels).mean(axis=1).astype('f4')


def condition(audio,name):
    spec=CONDITIONS[name]
    if spec is None:return audio
    rt,wet,seed,snr=spec;r=np.random.default_rng(seed);n=int(48000*rt*1.2);t=np.arange(n)/48000
    ir=np.concatenate([np.zeros(int(48000*0.02)),r.standard_normal(n)*np.exp(-6.9*t/rt)]);ir/=np.sqrt(np.sum(ir**2))
    size=1<<int(np.ceil(np.log2(len(audio)+len(ir)-1)))
    wetsig=np.fft.irfft(np.fft.rfft(audio,size)*np.fft.rfft(ir,size),size)[:len(audio)]
    out=(audio+wetsig*10**(wet/20)).astype('f4')
    if snr is not None:
        noise=r.standard_normal(len(out)).astype('f4');noise*=np.sqrt(np.mean(out**2))/np.sqrt(np.mean(noise**2))*10**(-snr/20);out=out+noise
    return out


def ranges(phrase_list,duration,scenario,rng):
    coarse=[]
    for p in phrase_list:
        a,b=p[0]['start'],p[-1]['end']
        if scenario=='draft':s=a+rng.uniform(-300,300);e=b+rng.uniform(-500,300)
        else:s=a-rng.uniform(50,200);e=b+rng.uniform(100,400)
        coarse.append([max(0,round(s)),min(round(duration),round(e))])
    if scenario=='tight':return coarse
    padded=[]
    for k,(s,e) in enumerate(coarse):
        left=coarse[k-1][1] if k else 0;right=coarse[k+1][0] if k+1<len(coarse) else round(duration)
        budget=max(0,60000-(e-s));before=min(500,budget,max(0,s-left));after=min(1500,budget-before,max(0,right-e))
        padded.append([max(0,s-before),min(round(duration),e+after)])
    return padded


def stats(values):
    x=np.abs(np.array(values,float))
    if not len(x):return {'n':0}
    return {'n':len(values),'mae_ms':round(float(x.mean()),1),'median_ms':round(float(np.median(values)),1),'p90_abs_ms':round(float(np.percentile(x,90)),1),'within_50ms_pct':round(float((x<=50).mean()*100),1),'within_100ms_pct':round(float((x<=100).mean()*100),1)}


def compare(rows,humans):
    on=[];tail=[];syl=[];ends=[]
    for row,h in zip(rows,humans):
        if row.get('error'):continue
        m=row['mora'];on.append(m[0]['start']-h[0]['start']);tail.append(m[-1]['end']-h[-1]['end'])
        syl+=[a['start']-b['start'] for a,b in zip(m[1:],h[1:])];ends+=[a['end']-b['end'] for a,b in zip(m[:-1],h[:-1])]
    return {'line_onset':stats(on),'line_tail':stats(tail),'syllable_onset':stats(syl),'syllable_end':stats(ends)}


def tail_check(rows,humans,meta,audio_of,tagged):
    """The app's line-tail check on each predicted line; counts only, timing is never changed."""
    from studio_backend import line_tails as tails
    where={(m['song'],m['trial'],m['index']):k for k,m in enumerate(meta)}
    total=bad=flagged=caught=0;codes={};options={};advice=[]
    for k,(row,human,m) in enumerate(zip(rows,humans,meta)):
        if row.get('error'):continue
        last=row['mora'][-1];a,e=last['start'],last['end'];truth=human[-1]['end']
        n=where.get((m['song'],m['trial'],m['index']+1));following=rows[n] if n is not None else None
        onset=following['mora'][0]['start'] if following and not following.get('error') else None
        next_start=onset if onset is not None and onset>a+tails.MIN_TAIL else None
        bound=m['end'] if next_start is None else min(m['end'],next_start)
        target={'start':a,'end':e,'line_end':m['end'],'limit':max(e,bound),'next_start':next_start,'text':human[-1]['key'],
                'model_tail':bool(tagged and e<=m['end'])}
        metrics=tails.measure(audio_of(m['song']),48000,target);found=tails.flags(target,metrics,'vocals')
        values=tails.candidates(target,metrics);pick=tails.recommend(found,tails.tail_type(target,metrics),values,e)
        wrong=abs(e-truth)>100;total+=1;bad+=wrong;flagged+=bool(found);caught+=bool(found and wrong)
        for x in found:codes[x['code']]=codes.get(x['code'],0)+1
        for x in values:options.setdefault(x['name'],[]).append((abs(x['end']-truth),abs(e-truth)))
        if pick:advice.append((abs(next(x['end'] for x in values if x['name']==pick)-truth),abs(e-truth)))
    def pair(values):
        x=np.array(values,float).reshape(-1,2)
        return {'n':len(x),'candidate_mae_ms':round(float(x[:,0].mean()),1) if len(x) else None,
                'model_mae_ms':round(float(x[:,1].mean()),1) if len(x) else None,'candidate_better':int(np.sum(x[:,0]<x[:,1]))}
    return {'lines':total,'tail_error_over_100ms':bad,'flagged':flagged,'flagged_and_over_100ms':caught,'flag_codes':codes,
            'recommended':pair(advice),'candidates':{name:pair(v) for name,v in options.items()}}


def inputs(args):
    if args.bundled:return [('pjs056',BUNDLED/'pjs056.lab',BUNDLED/'pjs056_song.wav')]
    if not args.corpus or not args.labels:raise SystemExit('Give --corpus and --labels, or use --bundled.')
    labels=sorted(glob.glob(str(Path(args.labels)/'*.lab')))
    if args.songs:labels=labels[:args.songs]
    return [(Path(lab).stem,Path(lab),Path(args.corpus)/Path(lab).stem/f'{Path(lab).stem}_song.wav') for lab in labels]


def prepare(songs,reverse,scenario,name,trials,temp):
    """Seeded line ranges for one scenario and condition, written as model input; nothing is aligned yet."""
    rng=random.Random(20261110);humans=[];plain=[];tagged=[];meta=[];paths={}
    for song,lab,wav in songs:
        found=phrases(lab,reverse)
        if not found:continue
        audio=condition(read_wav(wav),name);paths[song]=wav
        for trial in range(trials):
            for k,((s,e),p) in enumerate(zip(ranges(found,len(audio)/48,scenario,rng),found)):
                pcm=Path(temp)/f'{scenario}-{name}-{song}-{trial}-{k}.f32';audio[s*48:e*48].astype('<f4').tofile(pcm)
                mora=[{'unit':0,'highlight':n,'kana':m['key'],'pronunciation':m['key']} for n,m in enumerate(p)]
                plain.append({'start':s,'end':e,'mora':mora,'pcm':str(pcm)});meta.append({'song':song,'trial':trial,'index':k,'end':e})
                tagged.append({**plain[-1],'edges':{'lead':True,'trail':True}});humans.append(p)
    if not humans:raise SystemExit('No labelled phrases found; check --corpus and --labels.')
    return {'scenario':scenario,'condition':name,'trials':trials,'plain':plain,'tagged':tagged,'humans':humans,'meta':meta,'paths':paths}


def report(case,rows,engine_version):
    """Before/after errors and the tail check for one scenario and condition."""
    half=len(case['plain']);humans,meta,paths,name=case['humans'],case['meta'],case['paths'],case['condition'];cache={}
    def audio_of(song):
        if song not in cache:cache.clear();cache[song]=np.round(np.clip(condition(read_wav(paths[song]),name),-1,1)*32767).astype('<i2')
        return cache[song]
    order=sorted(range(half),key=lambda k:meta[k]['song'])
    pick=lambda part:[part[k] for k in order]
    return {'engine':engine_version,'scenario':case['scenario'],'condition':name,'phrases':half,'trials':case['trials'],
            'without_edge_tags':compare(rows[:half],humans),'with_edge_tags':compare(rows[half:],humans),
            'tail_check_without_edge_tags':tail_check(pick(rows[:half]),pick(humans),pick(meta),audio_of,False),
            'tail_check_with_edge_tags':tail_check(pick(rows[half:]),pick(humans),pick(meta),audio_of,True)}


def show(report):
    print(f"{report['engine']}  {report['scenario']}/{report['condition']}  {report['phrases']} phrases  (prediction minus human label)")
    for part in ('line_onset','line_tail','syllable_onset','syllable_end'):
        a=report['without_edge_tags'][part];b=report['with_edge_tags'][part]
        print(f"{part:15} mae {a['mae_ms']:6.1f} -> {b['mae_ms']:6.1f} ms   within 50 ms {a['within_50ms_pct']:5.1f}% -> {b['within_50ms_pct']:5.1f}%   median {a['median_ms']:+6.1f} -> {b['median_ms']:+6.1f} ms   p90 {a['p90_abs_ms']:6.1f} -> {b['p90_abs_ms']:6.1f} ms")
    t=report['tail_check_with_edge_tags'];r=t['recommended']
    print(f"tail check      {t['flagged']}/{t['lines']} flagged, {t['flagged_and_over_100ms']} of {t['tail_error_over_100ms']} tails off by >100 ms caught {t['flag_codes']}"
          +(f"; recommended on {r['n']}: {r['model_mae_ms']} -> {r['candidate_mae_ms']} ms, better on {r['candidate_better']}" if r['n'] else ''))


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bundled',action='store_true',help='use the PJS056 song and labels shipped with the app')
    parser.add_argument('--corpus',help='PJS_corpus_ver1.1 folder with pjsNNN/pjsNNN_song.wav')
    parser.add_argument('--labels',help='pjs-manual-labels lab folder with pjsNNN.lab')
    parser.add_argument('--model',default=str(ROOT/'vendor/tifa-model'));parser.add_argument('--tifa',default=str(ROOT/'vendor/tifa'))
    parser.add_argument('--scenario',choices=('draft','tight','all'),default=None,help='default: draft, or all with --bundled')
    parser.add_argument('--condition',choices=(*CONDITIONS,'all'),default=None,help='default: clean, or all with --bundled')
    parser.add_argument('--songs',type=int,default=0,help='only the first N labelled songs (0 = all)')
    parser.add_argument('--trials',type=int,default=0,help='seeded ranges per phrase (default 1, or 20 with --bundled)')
    parser.add_argument('--threads',type=int,default=4);parser.add_argument('--out',help='write the report as JSON')
    args=parser.parse_args()
    scenario=args.scenario or ('all' if args.bundled else 'draft');name=args.condition or ('all' if args.bundled else 'clean')
    trials=args.trials or (20 if args.bundled else 1)
    reverse=reverse_dictionary(Path(args.model)/'dictionaries/japanese_dict_full.txt');songs=inputs(args)
    with tempfile.TemporaryDirectory() as temp:
        cases=[prepare(songs,reverse,s,c,trials,temp) for s in (('draft','tight') if scenario=='all' else (scenario,))
               for c in (tuple(CONDITIONS) if name=='all' else (name,))]
        jobs=[job for case in cases for job in case['plain']+case['tagged']]
        def emit(**value):
            if value.get('stage')=='align':print(f"\r{value['completed']}/{value['total']}",end='',file=sys.stderr,flush=True)
        # One model run for every case: the engine sets its thread pool once per process.
        result=engine.align(args.model,args.tifa,{'jobs':jobs,'cache_dir':temp},emit,threads=args.threads)
        print(file=sys.stderr)
    reports=[];offset=0
    for case in cases:
        size=2*len(case['plain']);reports.append(report(case,result['jobs'][offset:offset+size],result['engine']));offset+=size;show(reports[-1])
    if args.out:Path(args.out).write_text(json.dumps(reports[0] if len(reports)==1 else reports,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
