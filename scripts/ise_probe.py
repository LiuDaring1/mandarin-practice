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
    nodes=[]
    for node in root.iter():
        if node.tag not in ('read_syllable','read_word','read_sentence','word','syll','phone'):
            continue
        row={'tag':node.tag,**{k:v for k,v in node.attrib.items() if k in allowed}}
        if node.tag=='phone':
            word=next((a for a in node.iterancestors() if a.tag=='word'),None)
            if word is not None:
                row['word_content']=word.get('content','')
        nodes.append(row)
    return {'status':'ok','nodes':nodes}
