"""Summarize isolated flags; never reports learner accuracy or changes progress."""
import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(cells):
    groups=[]
    for kind,voice in sorted({(c['kind'],c['voice']) for c in cells}):
        rows=[c for c in cells if (c['kind'],c['voice'])==(kind,voice)]
        groups.append({'kind':kind,'voice':voice,
                       'matching_reference':dict(Counter(c['observation']['state'] for c in rows if not c['cross_reference'])),
                       'cross_reference':dict(Counter(c['observation']['state'] for c in rows if c['cross_reference']))})
    return {'scope':'Labeled reference clips and their existing voice conversions, not independent speakers or verified learner errors.',
            'interpretation':'flagged means vowel error or replacement at the target, not a confirmed n/ng direction; not_flagged does not mean correct.',
            'count':len(cells),'groups':groups}


def main(args):
    result=json.loads(Path(args.input).read_text());summary=summarize(result['cells'])
    destination=Path(args.output);destination.mkdir(parents=True,exist_ok=True)
    (destination/'report.json').write_text(json.dumps({'summary':summary,'cells':result['cells']},ensure_ascii=False,indent=2)+'\n')
    lines=['# ISE 目标字结果对照','',
           '原声与两种换声版本共享源录音，不是三个独立说话人。每格依次为“按本字要求／按相反鼻音要求”。“未报异常”不等于确定读对，“报异常”不等于确认鼻尾替换。','',
           '| 单字录音标注 | 原声 | 换声女声 | 换声男声 |','|---|---|---|---|']
    def label(row):
        state=row['observation']['state']
        return {'flagged':'报异常','not_flagged':'未报异常'}.get(state,'无法判断')
    for char in ('心','星','林','零','班','帮'):
        cols=[]
        for voice in ('original','news-female','news-male'):
            selected=[c for c in result['cells'] if c['kind']=='single' and c['target']==char and c['voice']==voice]
            cols.append('／'.join(label(c) for c in sorted(selected,key=lambda c:c['cross_reference'])) or '未测')
        lines.append('| '+char+' | '+' | '.join(cols)+' |')
    lines+=['','词语／句子数据及目标位置见 report.json。全部结论仅适用于本轮样本和设置。','']
    (destination/'README.md').write_text('\n'.join(lines))
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',default='data/derived/ise-validation/stability-2026-10-24.json');p.add_argument('--output',default='handoff/ise-stability-2026-10-24')
    main(p.parse_args())
