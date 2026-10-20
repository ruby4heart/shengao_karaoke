"""Offline TIFA inference, imported only inside the isolated audio worker."""
from pathlib import Path
import hashlib
import json
import os
import sys

from audio_contract import TIFA_ENGINE_VERSION as ENGINE_VERSION,TIFA_MODEL_SHA256 as MODEL_SHA256,TIFA_FILES as FILES,WORKER_PROTOCOL

def align(model_folder,source_folder,request,emit,threads=4):
    import numpy as np
    import torch
    import yaml
    folder=Path(model_folder)
    for name,expected in FILES.items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:raise ValueError('Bundled alignment model failed verification: '+name)
    os.environ.setdefault('NUMBA_CACHE_DIR',str(Path(request['cache_dir'])/'numba'))
    sys.path.insert(0,str(source_folder))
    from lib.config.schema import ModelConfig,InferenceConfig
    from inference.backend import ForcedAlignmentInferenceModel
    torch.set_num_threads(max(1,min(threads,8)));torch.set_num_interop_threads(1)
    config=yaml.safe_load((folder/'config.yaml').read_text(encoding='utf-8'))
    mc=ModelConfig.model_validate(config['model'],scope=1);ic=InferenceConfig.model_validate(config['inference'],scope=1)
    mc.check(scope_mask=1);ic.check(scope_mask=1)
    emit(stage='model',message='Loading verified offline singing alignment model')
    model=ForcedAlignmentInferenceModel(mc,ic).eval()
    state=torch.load(folder/'model.pt',map_location='cpu',weights_only=True)
    model.load_state_dict(state['state_dict'],strict=True)
    vocabulary=json.loads((folder/'vocabulary.json').read_text(encoding='utf-8'))['symbols']
    dictionary={k:v.split() for line in (folder/'dictionaries/japanese_dict_full.txt').read_text(encoding='utf-8').splitlines() if line.strip() for k,v in [line.split('\t',1)]}
    outputs=[]
    def completed(value):
        outputs.append(value);emit(stage='aligned_job',protocol=WORKER_PROTOCOL,engine=ENGINE_VERSION,model_sha256=MODEL_SHA256,result=value)
    for i,job in enumerate(request['jobs']):
        audio=np.fromfile(job['pcm'],dtype='<f4')
        if not audio.size or not np.isfinite(audio).all() or len(audio)>48000*60:raise ValueError('Invalid alignment audio window')
        if float(np.sqrt(np.mean(audio.astype('float64')**2)))<1e-6:
            completed({'index':i,'error':'此范围几乎没有声音，保留原时间。'});continue
        phones=[];groups=[];owners=[]
        for n,mora in enumerate(job['mora']):
            key=mora['pronunciation']
            if key not in dictionary:raise ValueError('Unsupported Japanese pronunciation: '+key)
            values=dictionary[key];phones+=values;groups += [n+1]*len(values);owners += [n]*len(values)
        ids=[vocabulary['ja/'+p] for p in phones]
        if not ids or len(ids)>1500:raise ValueError('Invalid phoneme count')
        emit(stage='align',completed=i,total=len(request['jobs']))
        with torch.inference_mode():
            spec=model.spectrogram(torch.from_numpy(audio)[None],torch.tensor([len(audio)/48000]))
            result=model.align(spec,tokens=torch.tensor([ids]),groups=torch.tensor([groups]),unit='second')
        spans=result.spans[0].tolist();moras=[]
        for n,mora in enumerate(job['mora']):
            values=[{'phone':p,'start':round(a*1000)+job['start'],'end':round(b*1000)+job['start']} for p,owner,(a,b) in zip(phones,owners,spans) if owner==n]
            moras.append({**mora,'start':values[0]['start'],'end':values[-1]['end'],'phones':values})
        completed({'index':i,'mora':moras,'agreement':float(result.agreement[0])})
        emit(stage='align',completed=i+1,total=len(request['jobs']))
    return {'engine':ENGINE_VERSION,'model_sha256':MODEL_SHA256,'jobs':outputs,'sample_rate':48000,'timestep_ms':10,'protocol':WORKER_PROTOCOL}
