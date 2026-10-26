"""Isolated Xfyun ISE probe; never enables production diagnosis."""
import asyncio
import base64
import io
import json
import wave
from lxml import etree
import websockets
from suntone_probe import Probe, signed_url


def parameters(reference, core='read_syllable', **extra):
    return {'sub':'ise','ent':'cn_vip','category':core,'cmd':'ssb',
            'text':'\ufeff'+reference,'tte':'utf-8','ttp_skip':True,
            'aue':'raw','auf':'audio/L16;rate=16000','rstcd':'utf8',
            'group':'adult','check_type':'common','rst':'entirety',
            'ise_unite':'1','extra_ability':'syll_phone_err_msg;multi_dimension',**extra}


def frames(config, params, wav):
    with wave.open(io.BytesIO(wav),'rb') as source:
        if (source.getframerate(),source.getnchannels(),source.getsampwidth())!=(16000,1,2):
            raise ValueError('ISE probe needs 16kHz mono PCM16 WAV')
        pcm=source.readframes(source.getnframes())
    if len(pcm)<4:
        raise ValueError('Empty or too short WAV')
    yield {'common':{'app_id':config['app_id']},'business':params,'data':{'status':0,'data':''}}
    chunks=[pcm[i:i+1280] for i in range(0,len(pcm),1280)]
    if len(chunks)==1:
        mid=len(pcm)//4*2;chunks=[pcm[:mid],pcm[mid:]]
    for i,chunk in enumerate(chunks):
        last=i==len(chunks)-1
        yield {'business':{'cmd':'auw','aus':4 if last else 1 if i==0 else 2},
               'data':{'status':2 if last else 1,'data':base64.b64encode(chunk).decode()}}


async def evaluate(config, params, wav):
    packets=list(frames(config,params,wav))
    async with asyncio.timeout(45):
        url=signed_url(config,host='ise-api.xfyun.cn',path='/v2/open-ise')
        async with websockets.connect(url,open_timeout=15,max_size=8_000_000) as ws:
            async def send():
                for packet in packets:
                    await ws.send(json.dumps(packet,ensure_ascii=False))
                    await asyncio.sleep(.04)
            sender=asyncio.create_task(send())
            try:
                async for raw in ws:
                    envelope=json.loads(raw)
                    if envelope.get('code',0):
                        message=str(envelope.get('message',''))
                        for value in config.values():message=message.replace(str(value),'[redacted]')
                        return {'status':'provider_error','code':envelope['code'],'message':message}
                    data=envelope.get('data',{})
                    if data.get('status')==2:
                        if not data.get('data'):return {'status':'missing_result'}
                        return {'status':'ok','xml':base64.b64decode(data['data']).decode('utf-8-sig')}
                return {'status':'connection_closed'}
            finally:
                sender.cancel();await asyncio.gather(sender,return_exceptions=True)


class IseProbe(Probe):
    cache_namespace=b'ise-pcm16-v1'
    parameters=staticmethod(parameters)

    async def call(self,audio_path,reference,core='read_syllable',**extra):
        return await super().call(audio_path,reference,core,**extra)

    async def evaluate(self,config,params,audio):
        return await evaluate(config,params,audio)


def public_result(response):
    if response['status']!='ok':
        return {k:response[k] for k in ('status','code','error_type','http_status') if k in response}
    root=etree.fromstring(response['xml'].encode(),parser=etree.XMLParser(resolve_entities=False,no_network=True))
    allowed=('content','symbol','beg_pos','end_pos','is_yun','perr_msg','perr_level_msg',
             'dp_message','mono_tone','rec_node_type','total_score','phone_score','tone_score',
             'accuracy_score','fluency_score','integrity_score','is_rejected','except_info')
    paper_syllables = [n for n in root.iter('syll') if n.get('rec_node_type') == 'paper'
                       and len(n.get('content','')) == 1 and '\u3400' <= n.get('content','') <= '\u9fff']
    syllable_indices = {n: index for index, n in enumerate(paper_syllables)}
    nodes=[]
    for node in root.iter():
        if node.tag not in ('read_syllable','read_word','read_sentence','word','syll','phone'):
            continue
        row={'tag':node.tag,**{k:v for k,v in node.attrib.items() if k in allowed}}
        if node in syllable_indices:
            row['syll_index'] = syllable_indices[node]
        if node.tag=='phone':
            word=next((a for a in node.iterancestors() if a.tag=='word'),None)
            if word is not None:
                row['word_content']=word.get('content','')
            syll=next((a for a in node.iterancestors() if a.tag=='syll'),None)
            if syll is not None:
                row['syll_content']=syll.get('content','')
                row['syll_symbol']=syll.get('symbol','')
                for field in ('beg_pos', 'end_pos', 'dp_message'):
                    if syll.get(field) is not None:
                        row['syll_' + field] = syll.get(field)
                if syll in syllable_indices:
                    row['syll_index'] = syllable_indices[syll]
        nodes.append(row)
    return {'status':'ok','nodes':nodes}


def final_observation(finals):
    if len(finals) != 1:
        return {'state':'ambiguous_target','finals':finals}
    node = finals[0]
    if node.get('syll_dp_message', '0') not in ('0', '128'):
        return {'state':'unusable_alignment','finals':finals}
    if node.get('dp_message') not in ('0','128') or (node.get('dp_message') != '128' and node.get('perr_msg') not in ('0','1','2','3')):
        return {'state':'unusable_alignment','finals':finals}
    flagged = node.get('perr_msg') in ('1','3') or node.get('dp_message') == '128'
    return {'state':'flagged' if flagged else 'not_flagged','finals':finals}


def target_at(result, reference, position):
    """Identify a particular repeated character only after full sequence parity.

    Missing/inserted/misordered paper characters invalidate the mapping. This
    does not turn the vendor's expected phoneme into a recognized pronunciation.
    """
    if result['status'] != 'ok':
        return {'state':'unavailable','finals':[]}
    nodes = result['nodes']
    if any(n.get('is_rejected') == 'true' or n.get('except_info','0') != '0' for n in nodes):
        return {'state':'rejected','finals':[]}
    chars = [ch for ch in reference if '\u3400' <= ch <= '\u9fff']
    syllables = [n for n in nodes if n.get('tag') == 'syll' and 'syll_index' in n]
    if not 0 <= position < len(chars) or [n['content'] for n in syllables] != chars:
        return {'state':'unusable_alignment','finals':[]}
    finals = [n for n in nodes if n.get('tag') == 'phone' and n.get('is_yun') == '1'
              and n.get('syll_index') == position]
    return final_observation(finals)
