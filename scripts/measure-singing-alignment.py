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
"""
from pathlib import Path
import argparse,glob,json,random,sys,tempfile,wave
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
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
    return {'n':len(values),'median_ms':round(float(np.median(values)),1),'p90_abs_ms':round(float(np.percentile(x,90)),1),'within_50ms_pct':round(float((x<=50).mean()*100),1),'within_100ms_pct':round(float((x<=100).mean()*100),1)}


def compare(rows,humans):
    on=[];tail=[];syl=[];ends=[]
    for row,h in zip(rows,humans):
        if row.get('error'):continue
        m=row['mora'];on.append(m[0]['start']-h[0]['start']);tail.append(m[-1]['end']-h[-1]['end'])
        syl+=[a['start']-b['start'] for a,b in zip(m[1:],h[1:])];ends+=[a['end']-b['end'] for a,b in zip(m[:-1],h[:-1])]
    return {'line_onset':stats(on),'line_tail':stats(tail),'syllable_onset':stats(syl),'syllable_end':stats(ends)}


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--corpus',required=True,help='PJS_corpus_ver1.1 folder with pjsNNN/pjsNNN_song.wav')
    parser.add_argument('--labels',required=True,help='pjs-manual-labels lab folder with pjsNNN.lab')
    parser.add_argument('--model',default=str(ROOT/'vendor/tifa-model'));parser.add_argument('--tifa',default=str(ROOT/'vendor/tifa'))
    parser.add_argument('--scenario',choices=('draft','tight'),default='draft')
    parser.add_argument('--condition',choices=tuple(CONDITIONS),default='clean')
    parser.add_argument('--songs',type=int,default=0,help='only the first N labelled songs (0 = all)')
    parser.add_argument('--threads',type=int,default=4);parser.add_argument('--out',help='write the report as JSON')
    args=parser.parse_args()
    reverse=reverse_dictionary(Path(args.model)/'dictionaries/japanese_dict_full.txt')
    labels=sorted(glob.glob(str(Path(args.labels)/'*.lab')))
    if args.songs:labels=labels[:args.songs]
    rng=random.Random(20261110);humans=[];plain=[];tagged=[]
    with tempfile.TemporaryDirectory() as temp:
        for lab in labels:
            name=Path(lab).stem;found=phrases(lab,reverse)
            if not found:continue
            audio=condition(read_wav(Path(args.corpus)/name/f'{name}_song.wav'),args.condition)
            for k,((s,e),p) in enumerate(zip(ranges(found,len(audio)/48,args.scenario,rng),found)):
                pcm=Path(temp)/f'{name}-{k}.f32';audio[s*48:e*48].astype('<f4').tofile(pcm)
                mora=[{'unit':0,'highlight':n,'kana':m['key'],'pronunciation':m['key']} for n,m in enumerate(p)]
                plain.append({'start':s,'end':e,'mora':mora,'pcm':str(pcm)})
                tagged.append({**plain[-1],'edges':{'lead':True,'trail':True}});humans.append(p)
        if not humans:raise SystemExit('No labelled phrases found; check --corpus and --labels.')
        def emit(**value):
            if value.get('stage')=='align':print(f"\r{value['completed']}/{value['total']}",end='',file=sys.stderr,flush=True)
        result=engine.align(args.model,args.tifa,{'jobs':plain+tagged,'cache_dir':temp},emit,threads=args.threads)
        print(file=sys.stderr)
    rows=result['jobs'];half=len(plain)
    report={'engine':result['engine'],'scenario':args.scenario,'condition':args.condition,'phrases':half,
            'without_edge_tags':compare(rows[:half],humans),'with_edge_tags':compare(rows[half:],humans)}
    print(f"{report['engine']}  {args.scenario}/{args.condition}  {half} phrases  (prediction minus human label)")
    for part in ('line_onset','line_tail','syllable_onset','syllable_end'):
        a=report['without_edge_tags'][part];b=report['with_edge_tags'][part]
        print(f"{part:15} within 50 ms {a['within_50ms_pct']:5.1f}% -> {b['within_50ms_pct']:5.1f}%   median {a['median_ms']:+6.1f} -> {b['median_ms']:+6.1f} ms   p90 {a['p90_abs_ms']:6.1f} -> {b['p90_abs_ms']:6.1f} ms")
    if args.out:Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
