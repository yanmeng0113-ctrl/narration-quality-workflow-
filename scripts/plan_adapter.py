#!/usr/bin/env python3
"""Validate and filter a narration request plan; never performs network calls."""
import argparse
import hashlib
import json
import math
import pathlib
import re
import sys

SENSITIVE = re.compile(r'(?i)(api[_-]?key|authorization|token|secret|password|credential)')
SECRET_VALUE = re.compile(r'(?i)(?<![a-z0-9])(?:bearer\s+[a-z0-9._~-]{16,}|sk-[a-z0-9_-]{20,}|xox[baprs]-[a-z0-9-]{8,}|(?:api[_-]?key|token|secret|password)\s*=\s*[\"\']?[a-z0-9_./+~-]{12,})')

def text_value(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    if SECRET_VALUE.search(value):
        raise ValueError(f'{label} contains possible credential')
    return value

def validate_value(value, spec, label):
    if not isinstance(spec, dict):
        raise ValueError(f'{label}: capability specification must be an object')
    kind = spec.get('type')
    if kind == 'string':
        text_value(value, label)
    elif kind == 'number':
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f'{label} must be a finite number')
        if 'min' in spec and value < spec['min'] or 'max' in spec and value > spec['max']:
            raise ValueError(f'{label} outside adapter range')
    else:
        raise ValueError(f'{label}: invalid capability type')
    if 'enum' in spec and (not isinstance(spec['enum'], list) or value not in spec['enum']):
        raise ValueError(f'{label} outside adapter enum')

def plan(manifest, adapter):
    if not isinstance(manifest,dict) or not isinstance(adapter,dict):
        raise ValueError('manifest and adapter must be objects')
    if adapter.get('verified') is not True:
        raise ValueError('adapter unverified; no request planned')
    adapter_name=text_value(adapter.get('name','unnamed'),'adapter name')
    fields = adapter.get('fields')
    if not isinstance(fields,dict):
        raise ValueError('adapter fields must be an object')
    for name,spec in fields.items():
        if not isinstance(name,str) or not name or SENSITIVE.search(name) or not isinstance(spec,dict):
            raise ValueError('invalid or sensitive adapter field')
        if spec.get('type') not in ('string','number'):
            raise ValueError('invalid field type')
        if set(spec)-{'type','min','max','enum'}:raise ValueError(f'{name}: unknown constraint')
        if spec['type']=='string' and ('min' in spec or 'max' in spec):raise ValueError(f'{name}: range requires numeric field')
        for bound in ('min','max'):
            if bound in spec and (isinstance(spec[bound],bool) or not isinstance(spec[bound],(float,int)) or not math.isfinite(spec[bound])):raise ValueError(f'{name}: invalid {bound}')
        if 'min' in spec and 'max' in spec and spec['min']>spec['max']:raise ValueError(f'{name}: min exceeds max')
        if 'enum' in spec:
            if not isinstance(spec['enum'],list) or not spec['enum']:raise ValueError(f'{name}: enum must be a nonempty array')
            for value in spec['enum']:
                if spec['type']=='string' and (not isinstance(value,str) or not value.strip()):raise ValueError(f'{name}: invalid string enum')
                if spec['type']=='number' and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):raise ValueError(f'{name}: invalid numeric enum')
    prompt = adapter.get('prompt', {'mode':'none'})
    if not isinstance(prompt,dict) or prompt.get('mode') not in ('none','field','embedded'):
        raise ValueError('invalid prompt mode')
    if prompt['mode'] != 'none' and prompt.get('sample_verified') is not True:
        raise ValueError('prompt mode requires verified short sample')
    if prompt['mode'] == 'field' and prompt.get('field') not in fields:
        raise ValueError('prompt field not declared')
    if prompt['mode'] == 'embedded':
        text_value(prompt.get('separator'),'prompt separator')
    allowed=prompt.get('allowed_tags',[])
    if not isinstance(allowed,list) or any(not isinstance(x,str) for x in allowed):raise ValueError('allowed_tags must be a string array')
    text_tags=adapter.get('allowed_text_tags',[])
    if not isinstance(text_tags,list) or any(not isinstance(x,str) for x in text_tags):raise ValueError('allowed_text_tags must be a string array')
    def check_prompt(value):
        text_value(value,'prompt')
        for tag in re.findall(r'<[^>]*>',value):
            if tag not in allowed:raise ValueError('unverified prompt tag')
    segments=manifest.get('segments')
    if not isinstance(segments,list) or not segments:
        raise ValueError('segments must be a nonempty array')
    result=[]; ids=set()
    for seg in segments:
        if not isinstance(seg,dict):raise ValueError('each segment must be an object')
        ident=text_value(seg.get('id'),'segment id'); text=text_value(seg.get('text'),'text')
        for tag in re.findall(r'<[^>]*>',text):
            if tag not in text_tags:raise ValueError(f'{ident}: unverified text tag')
        if ident in ids:raise ValueError('duplicate ID')
        ids.add(ident);digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
        if 'text_sha256' in seg and seg['text_sha256'] != digest:raise ValueError(f'{ident}: text hash mismatch')
        intent=seg.get('intent')
        if intent is not None:text_value(intent,'intent')
        request=seg.get('request',{})
        if not isinstance(request,dict):raise ValueError('request must be an object')
        if intent is not None and ('prompt' in request or prompt.get('field') in request):
            raise ValueError('intent conflicts with explicit prompt')
        clean={'text':text}; dropped=[]
        for key,value in request.items():
            if not isinstance(key,str) or SENSITIVE.search(key):raise ValueError('sensitive request field rejected')
            if key == 'text':raise ValueError('request cannot replace locked text')
            if key == 'prompt' and (prompt['mode'] != 'field' or prompt.get('field') != key):raise ValueError('prompt requires verified field mode')
            if key not in fields:
                if isinstance(value,(dict,list)) or not isinstance(value,(str,int,float,bool,type(None))):raise ValueError('unsupported field value must be scalar')
                if isinstance(value,float) and not math.isfinite(value):raise ValueError('unsupported field must be finite')
                if isinstance(value,str) and SECRET_VALUE.search(value):raise ValueError('possible credential rejected')
                dropped.append({'field':key,'value':value,'reason':'unsupported'});continue
            if key==prompt.get('field') and prompt['mode']!='field':raise ValueError('prompt requires verified field mode')
            if key==prompt.get('field'):check_prompt(value)
            validate_value(value,fields[key],key);clean[key]=value
        if intent is not None:
            if prompt['mode']=='none':dropped.append({'field':'intent','value':intent,'reason':'prompt capability unavailable'})
            elif prompt['mode']=='field':
                check_prompt(intent)
                field=prompt['field'];validate_value(intent,fields[field],field);clean[field]=intent
            else:
                check_prompt(intent)
                clean['text']=intent+prompt['separator']+text
        result.append({'id':ident,'text':text,'text_sha256':digest,'intent_record':intent,'request':clean,'dropped':dropped})
    return {'adapter':adapter_name,'plan_only':True,'network_calls':0,'execution_authorized':False,'segments':result}

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--adapter',required=True);p.add_argument('--output',required=True);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    m=pathlib.Path(a.manifest).resolve();c=pathlib.Path(a.adapter).resolve();o=pathlib.Path(a.output).resolve()
    if o in (m,c) or o.exists():raise ValueError('output must be a new file')
    result=plan(json.loads(m.read_text(encoding='utf-8-sig')),json.loads(c.read_text(encoding='utf-8-sig')))
    if not a.dry_run:
        with o.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,json.JSONDecodeError,TypeError) as e:print(str(e),file=sys.stderr);sys.exit(1)
