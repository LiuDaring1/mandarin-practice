"""Shared, bounded execution primitives for prospective nasal validation."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from audit_latic_nasal_annotations import canonical
from ise_probe import IseProbe,public_result,target_at
from prepare_nasal_feature_data import interval


def durable_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.durable-tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600);os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


class MirroredIseProbe(IseProbe):
    def __init__(self,directory,*,mirror,**kwargs):
        super().__init__(directory,**kwargs);self.mirror=Path(mirror)

    async def _call_locked(self,*args,**kwargs):
        source=self.mirror/'requests.json'
        if source.exists():
            old=json.loads(source.read_text());current=json.loads((self.directory/'requests.json').read_text())
            if current[:len(old)]!=old:raise RuntimeError('Ledger regressed relative to internal mirror; inspect before sending')
        return await super()._call_locked(*args,**kwargs)

    async def evaluate(self,config,params,audio):
        key=hashlib.sha256(self.cache_namespace+json.dumps(params,sort_keys=True,ensure_ascii=False).encode()+audio).hexdigest()
        ledger=json.loads((self.directory/'requests.json').read_text())
        if key not in ledger:raise ValueError('Request was not reserved')
        self.mirror.mkdir(parents=True,exist_ok=True);self.mirror.chmod(0o700)
        durable_json(self.mirror/'requests.json',ledger)
        result=await super().evaluate(config,params,audio)
        durable_json(self.mirror/'cache'/(key+'.json'),result)
        return result


def align_target(row,result):
    """Require the complete reference, expected reading and usable time bounds."""
    observation=target_at(result,row['reference'],row['position'])
    bounds=interval(observation,row['audio'])
    out={**row,'api_state':observation['state']}
    if bounds is None:return {**out,'reason':'unusable_api_interval'},False
    nodes=[n for n in result['nodes'] if n.get('tag')=='syll' and n.get('syll_index')==row['position']]
    try:
        if len(nodes)!=1 or canonical(nodes[0].get('symbol',''))!=row['expected_pinyin']:
            return {**out,'reason':'reference_pinyin_mismatch'},False
    except ValueError:return {**out,'reason':'unsupported_reference_pinyin'},False
    return {**out,'bounds':bounds},True


def model_membership(name,availability):
    flags=np.asarray(availability)
    if flags.ndim!=2 or flags.shape[1]!=3 or flags.dtype!=np.bool_:
        raise ValueError('Expected per-target Xeus/HuBERT/temporal boolean availability')
    if name=='xeus':return flags[:,0]
    if name in ('hubert','hubert_pair'):return flags[:,1]
    if name=='fusion':return flags[:,0]&flags[:,1]
    if name=='hubert_temporal':return flags[:,2]
    raise ValueError('Unknown frozen model')


def xeus_states(model,samples):
    import torch
    speech=torch.from_numpy(samples.copy()).unsqueeze(0).to(model.device)
    lengths=torch.tensor([len(samples)],dtype=torch.long,device=model.device)
    model.conditioning_calls=0;model.conditioning_norms=[]
    with torch.inference_mode():
        encoded,output_lengths=model.model.encode(speech,lengths);final,intermediate=encoded
        states=final[0].float().cpu().numpy().copy()
    expected=(len(samples)-model.field)//model.stride+1
    if (int(output_lengths[0])!=expected or states.shape!=(expected,1024) or not np.isfinite(states).all()
        or [i for i,_ in intermediate]!=[4,8,12] or model.conditioning_calls!=3
        or not all(np.isfinite(x) and x>0 for x in model.conditioning_norms)):
        raise RuntimeError('Xeus conditioning or output grid changed')
    del encoded,final,intermediate,speech,lengths
    if model.device=='mps':torch.mps.empty_cache()
    return states


def pool_features(kind,states,row,start,count,stride,field):
    """Failures remain block-specific; no label or human boundary fallback."""
    from nasal_feature_probe import pool_regions
    from chinese_hubert_features import pool_halves
    from hubert_temporal_features import pool_views
    values={};errors={}
    if kind=='xeus':
        relative={k:[t-start/16000 for t in v] for k,v in row['bounds'].items()}
        try:values['xeus']=pool_regions(states,relative,sample_count=count,stride=stride,receptive_field=field)[2:4].reshape(-1)
        except ValueError as error:errors['xeus']=str(error)
    elif kind=='hubert':
        try:values['hubert']=pool_halves(states[None],row['bounds'],start,count,stride,field)[0]
        except ValueError as error:errors['hubert']=str(error)
        try:values['temporal']=pool_views(states,row['bounds'],start,count,stride,field)[0]['resampled4']
        except ValueError as error:errors['temporal']=str(error)
    else:raise ValueError('Unknown encoder')
    return values,errors
