"""Isolated, offline CPU Demucs worker. No Qt, network or user credentials."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import time

MODEL_SHA256='8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4'
ENGINE_VERSION='htdemucs-4.0.1-cpu-v1'

def emit(**value):
    print(json.dumps(value,ensure_ascii=True),flush=True)

def separate(model_path,source,target,threads=4):
    import numpy as np
    import torch
    from demucs.states import load_model
    import demucs.apply as apply
    path=Path(model_path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_SHA256:raise ValueError('The bundled vocal model failed verification')
    torch.set_num_threads(max(1,min(threads,8)));torch.set_num_interop_threads(1)
    emit(stage='model',message='Loading verified offline model')
    # Demucs checkpoints contain the model class. Only this one fixed, hashed
    # official checkpoint is accepted, before invoking the trusted loader.
    package=torch.load(path,map_location='cpu',weights_only=False)
    model=load_model(package,strict=True).eval()
    if model.samplerate!=44100 or model.audio_channels!=2:raise ValueError('Unexpected model audio format')
    raw=np.fromfile(source,dtype='<f4')
    if not raw.size or raw.size%2 or not np.isfinite(raw).all():raise ValueError('Invalid stereo PCM input')
    mix=torch.from_numpy(raw.reshape(-1,2).T.copy());frames=mix.shape[1]
    ref=mix.mean(0);mean=ref.mean();std=ref.std()
    if not torch.isfinite(std) or std<1e-8:
        vocals=torch.zeros_like(mix)
    else:
        mix=(mix-mean)/std
        def progress(items,**kwargs):
            for i,item in enumerate(items):
                emit(stage='separate',completed=i,total=len(items))
                yield item
            emit(stage='separate',completed=len(items),total=len(items))
        apply.tqdm.tqdm=progress
        with torch.inference_mode():
            estimates=apply.apply_model(model,mix[None],device='cpu',shifts=0,split=True,overlap=.25,progress=True,num_workers=0)
            vocals=(estimates[0,model.sources.index('vocals')]*std+mean).contiguous()
    if vocals.shape!=(2,frames) or not torch.isfinite(vocals).all():raise ValueError('Invalid separated audio')
    vocals.T.contiguous().numpy().astype('<f4').tofile(target)
    return {'engine':ENGINE_VERSION,'model_sha256':MODEL_SHA256,'sample_rate':44100,'channels':2,'frames':frames,'peak':float(vocals.abs().max())}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--input');parser.add_argument('--output');parser.add_argument('--align-request');parser.add_argument('--owner-job');parser.add_argument('--report',required=True);parser.add_argument('--threads',type=int,default=min(4,os.cpu_count() or 1));args=parser.parse_args()
    if args.owner_job:
        from shengao.process_tree import join_owner_job
        join_owner_job(args.owner_job)
    started=time.monotonic()
    try:
        if args.align_request:
            import importlib
            module=importlib.import_module('alignment_engine')
            source=Path(sys.executable).parent/'tifa' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'vendor/tifa'
            request=json.loads(Path(args.align_request).read_text(encoding='utf-8'))
            result=module.align(args.model,source,request,emit,args.threads)
        else:
            if not args.input or not args.output:raise ValueError('Missing separation input/output')
            result=separate(args.model,args.input,args.output,args.threads)
        result['seconds']=round(time.monotonic()-started,3)
        Path(args.report).write_text(json.dumps(result,indent=2),encoding='utf-8');emit(stage='done',**result)
    except Exception as error:
        emit(stage='failed',message=str(error));raise

if __name__=='__main__':main()
