#!/usr/bin/env python3
"""Read-only technical audio audit, with no automatic acceptance decision."""
import argparse
import array
import hashlib
import json
import math
import pathlib
import re
import subprocess
import sys

def number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(name+' must be a finite number')
    return float(value)

def load_manifest(path):
    cfg=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg,dict):raise ValueError('manifest must be an object')
    items=cfg.get('items')
    if not isinstance(items,list) or not items:raise ValueError('items must be a nonempty array')
    seen=set();result=[]
    for item in items:
        if not isinstance(item,dict):raise ValueError('each item must be an object')
        ident=item.get('id');audio=item.get('audio')
        if not isinstance(ident,str) or not ident.strip() or ident in seen:raise ValueError('unique nonempty item ID required')
        if not isinstance(audio,str) or not audio.strip():raise ValueError('audio path required')
        heard=item.get('heard_review','not_performed')
        if heard not in ('not_performed','passed','failed'):raise ValueError('invalid heard_review')
        path_audio=(path.parent/pathlib.Path(audio)).resolve()
        for field in ('expected_text','asr_text'):
            if field in item and not isinstance(item[field],str):raise ValueError(field+' must be text')
        seen.add(ident);result.append((ident,path_audio,heard,item.get('expected_text'),item.get('asr_text')))
    opts=cfg.get('thresholds',{})
    if not isinstance(opts,dict):raise ValueError('thresholds must be an object')
    tp=number(opts.get('true_peak_limit_dbtp',-1),'true_peak_limit_dbtp'); tail=number(opts.get('tail_rms_threshold_dbfs',-35),'tail_rms_threshold_dbfs')
    if not -100<=tp<=10 or not -100<=tail<=0:raise ValueError('threshold outside meaningful bounds')
    return result,tp,tail

def run(cmd):
    p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if p.returncode:raise RuntimeError(pathlib.Path(cmd[0]).name+' failed: '+p.stderr.strip()[-1000:])
    return p.stdout,p.stderr

def audit(ident,audio,heard,expected,asr,tp,tail,ffmpeg,ffprobe):
    raw,_=run([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(audio)])
    info=json.loads(raw);duration=float(info['format']['duration'])
    run([ffmpeg,'-v','error','-xerror','-i',str(audio),'-f','null','-'])
    _,log=run([ffmpeg,'-hide_banner','-nostats','-i',str(audio),'-af','silencedetect=noise=-40dB:d=0.12,ebur128=peak=true','-f','null','-'])
    peaks=re.findall(r'Peak:\s*(-inf|[-+0-9.]+) dBFS',log);lufs=re.findall(r'I:\s*(-inf|[-+0-9.]+) LUFS',log)
    if not peaks:raise RuntimeError('true peak unavailable')
    rawtail=subprocess.run([ffmpeg,'-v','error','-ss',str(max(0,duration-.1)),'-i',str(audio),'-f','s16le','-ac','1','-ar','16000','pipe:1'],capture_output=True,check=True).stdout
    v=array.array('h');v.frombytes(rawtail[:len(rawtail)//2*2]);rms=math.sqrt(sum(x*x for x in v)/len(v))/32768 if v else 0
    h=hashlib.sha256()
    with audio.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    silent=peaks[-1]=='-inf';peak=None if silent else float(peaks[-1])
    return {'id':ident,'input':str(audio),'sha256':h.hexdigest(),'duration_seconds':duration,'decode_ok':True,'true_peak_dbtp':peak,'silent_audio':silent,'true_peak_limit_dbtp':tp,'true_peak_exceeds_limit':False if silent else peak>tp,'integrated_lufs':float(lufs[-1]) if lufs and lufs[-1]!='-inf' else None,'silence_threshold_db':-40,'silence_min_seconds':0.12,'silence_starts':[float(x) for x in re.findall(r'silence_start: ([0-9.]+)',log)],'silence_ends':[float(x) for x in re.findall(r'silence_end: ([0-9.]+)',log)],'tail_last_100ms_rms':rms,'tail_rms_threshold_dbfs':tail,'tail_active_risk_candidate':rms>10**(tail/20),'tail_note':'Risk only, not proof of truncation','heard_review':heard,'expected_text':expected,'asr_text':asr,'asr_differences':'manual_review_required' if expected is not None and asr is not None else 'not_checked'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--dry-run',action='store_true');p.add_argument('--ffmpeg',default='ffmpeg');p.add_argument('--ffprobe',default='ffprobe');a=p.parse_args()
    manifest=pathlib.Path(a.manifest).resolve();out=pathlib.Path(a.output).resolve();items,tp,tail=load_manifest(manifest)
    if out==manifest or out.exists() or any(out==item[1] for item in items):raise ValueError('output must be a new file distinct from inputs')
    if a.dry_run:print(json.dumps({'dry_run':True,'mode':'structure_only','items':[{'id':x[0],'media_exists':x[1].is_file(),'media_tested':False} for x in items],'writes':False}));return
    results=[]
    for i,f,h,e,s in items:
        try:
            if not f.is_file():raise FileNotFoundError('audio file does not exist')
            item=audit(i,f,h,e,s,tp,tail,a.ffmpeg,a.ffprobe);item['status']='success';results.append(item)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError,subprocess.CalledProcessError,json.JSONDecodeError) as exc:
            results.append({'id':i,'input':str(f),'status':'error','error_type':type(exc).__name__,'error':str(exc),'heard_review':h})
    errors=sum(x['status']=='error' for x in results)
    result={'items':results,'status':'partial' if errors and errors<len(results) else ('failed' if errors else 'complete'),'overall_pass':False,'overall_note':'Technical checks are not overall or listening acceptance.'}
    with out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'output':str(out),'items':len(results),'status':result['status'],'overall_pass':False}))
    if errors:sys.exit(2)
if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,subprocess.CalledProcessError,json.JSONDecodeError) as e:print(str(e),file=sys.stderr);sys.exit(1)
