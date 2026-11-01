#!/usr/bin/env python3
"""Offline decision over explicit final-version evidence; does not run ASR or hear audio."""
import argparse
import hashlib
import json
import math
import pathlib
import sys
import subprocess
from plan_adapter import text_value
from audit_audio import reject_credentials


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and abs(value) <= sys.float_info.max and math.isfinite(value)


def interval(value, duration):
    if not finite(duration) or duration <= 0:
        raise ValueError('duration must be positive finite number')
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('interval must be [start, end]')
    if any(not finite(x) for x in value):
        raise ValueError('interval must be finite')
    if not 0 <= value[0] < value[1] <= duration:
        raise ValueError('interval outside media bounds')
    return value


def covered(ranges, duration):
    if not isinstance(ranges, list):
        raise ValueError('coverage must be an interval array')
    end = 0
    for start, stop in sorted(interval(r, duration) for r in ranges):
        if start > end:
            return False
        end = max(end, stop)
    return end == duration


def bound(evidence, digest):
    return isinstance(evidence, dict) and evidence.get('source_sha256') == digest


def media_facts(source):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(source)], capture_output=True)
    if probe.returncode:
        raise ValueError('actual media probe failed')
    info = json.loads(probe.stdout)
    duration = float(info['format']['duration'])
    interval([0, duration], duration)
    decode = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source), '-f', 'null', '-'], capture_output=True)
    if decode.returncode:
        raise ValueError('actual full decode failed')
    types = [stream['codec_type'] for stream in info['streams']]
    return duration, types


def evidence_record(check, name, digest, base):
    ref = check.get('evidence_ref')
    if not isinstance(ref, dict):
        return False
    path = base / text_value(ref.get('path'), 'evidence path')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref.get('sha256'):
        return False
    record = json.loads(raw)
    reject_credentials(record)
    if not isinstance(record, dict) or record.get('source_sha256') != digest or record.get('check_name') != name:
        return False
    for field in ('tool', 'tool_version', 'method', 'details'):
        text_value(record.get(field), 'evidence ' + field)
    if record.get('coverage') != check.get('coverage') or record.get('status') != check.get('status'):
        return None
    return record


def decide(item, base):
    if not isinstance(item, dict):
        raise ValueError('item must be an object')
    reject_credentials(item)
    ident = text_value(item.get('id'), 'item ID')
    source = (base / text_value(item.get('media'), 'media path')).resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    declared_duration = item.get('duration_seconds')
    interval([0, declared_duration], declared_duration)
    duration, stream_types = media_facts(source)
    if abs(declared_duration-duration) > 0.001:
        raise ValueError('declared duration differs from actual final media')
    if item.get('source_sha256') != digest:
        raise ValueError('final media hash mismatch')
    for name in ('has_narration', 'has_video', 'has_subtitles'):
        if not isinstance(item.get(name), bool):
            raise ValueError(name + ' must be explicit boolean')
    if item['has_video'] != ('video' in stream_types):
        raise ValueError('declared video presence differs from actual streams')
    if item['has_narration'] and 'audio' not in stream_types:
        raise ValueError('narration declared but no audio stream')
    if 'subtitle' in stream_types and not item['has_subtitles']:
        raise ValueError('embedded subtitles cannot be declared absent')
    heard = item.get('heard_review', 'not_performed')
    if heard not in ('not_performed', 'passed', 'failed'):
        raise ValueError('invalid heard_review; local_pass is not listening')
    required = ['decode']
    if item['has_video']:
        required += ['visuals']
    if item['has_subtitles']:
        required += ['subtitle_sync']
    if item['has_narration']:
        required += ['asr_content', 'pronunciation_risk_scan', 'boundaries_pauses', 'tail', 'loudness_peak']
    checks = item.get('checks', {})
    if not isinstance(checks, dict):
        raise ValueError('checks must be an object')
    missing, blockers, coverage = [], [], {}
    records = {}
    expected_hash = hashlib.sha256(text_value(item.get('expected_text'), 'expected text').encode('utf-8')).hexdigest() if item['has_narration'] else None
    safe_asr = None
    automatic_checks = {'decode': {'status':'passed', 'source_sha256':digest, 'coverage':[[0,duration]], 'tool':'ffmpeg', 'execution':'executed_in_this_run'}, 'probe': {'duration_seconds':duration, 'stream_types':stream_types, 'execution':'executed_in_this_run'}}
    for name in required:
        if name == 'decode':
            coverage[name] = [[0,duration]]
            continue
        check = checks.get(name)
        if not bound(check, digest):
            missing.append(name + ':missing_or_wrong_version')
            continue
        text_value(check.get('tool'), 'check tool')
        record = evidence_record(check, name, digest, base)
        if record:
            records[name] = record
        if not record:
            missing.append(name + ':missing_structured_evidence')
        coverage[name] = check.get('coverage', [])
        if not covered(coverage[name], duration):
            missing.append(name + ':incomplete_coverage')
        if check.get('status') != 'passed':
            blockers.append(name + ':not_passed')
        if name == 'asr_content':
            asr = check.get('asr_source')
            if not isinstance(asr, dict) or asr.get('blind') is not True or not asr.get('model') or not asr.get('tool'):
                missing.append('asr_source:blind_tool_model_required')
            else:
                text_value(asr.get('tool'), 'ASR tool')
                text_value(asr.get('model'), 'ASR model')
                safe_asr = {key:asr[key] for key in ('tool', 'model', 'blind')}
            if not record or record.get('asr_source') != asr or not isinstance(record.get('asr_source'), dict) or record['asr_source'].get('blind') is not True or record.get('text_sha256') != expected_hash:
                missing.append('asr_content:artifact_text_or_source_mismatch')
            expected = text_value(item.get('expected_text'), 'expected text')
            expected_hash = hashlib.sha256(expected.encode('utf-8')).hexdigest()
            if check.get('text_sha256') != expected_hash:
                missing.append('asr_content:text_hash_mismatch')
    risks = item.get('risks', [])
    if not isinstance(risks, list) or any(not isinstance(r, dict) for r in risks):
        raise ValueError('risks must be an array')
    notes = item.get('pronunciation_notes', [])
    if not isinstance(notes, list):
        raise ValueError('pronunciation_notes must be an array')
    for note in notes:
        text_value(note, 'pronunciation note')
    content_type = item.get('content_type', 'prose')
    if content_type not in ('prose', 'poetry'):
        raise ValueError('invalid content_type')
    risks = list(risks)
    if item['has_narration']:
        scan = records.get('pronunciation_risk_scan', {})
        scanned_risks = scan.get('pronunciation_risks')
        if scan.get('text_sha256') != expected_hash or not isinstance(scanned_risks, list):
            missing.append('pronunciation_risk_scan:missing_text_bound_risk_inventory')
            scanned_risks = []
        for risk in scanned_risks:
            if not isinstance(risk, dict) or risk.get('kind') != 'pronunciation':
                raise ValueError('invalid pronunciation scan risk')
            text_value(risk.get('text'), 'risk word or phrase')
            text_value(risk.get('reason'), 'risk reason')
        risks.extend(scanned_risks)
        for note in notes:
            if not any(r.get('note') == note for r in scanned_risks):
                missing.append('pronunciation_notes:unlocalized_note')
    resolutions = item.get('resolutions', [])
    if not isinstance(resolutions, list) or any(not isinstance(r, dict) for r in resolutions):
        raise ValueError('resolutions must be object array')
    unresolved = []
    seen = set()
    for risk in risks:
        rid = text_value(risk.get('id'), 'risk ID')
        if risk.get('kind') not in ('pronunciation', 'naturalness', 'truncation', 'content', 'sync', 'visual', 'technical'):
            raise ValueError('unsupported risk kind')
        if rid in seen:
            raise ValueError('duplicate risk ID')
        seen.add(rid)
        span = interval(risk.get('interval'), duration)
        valid = False
        for resolution in resolutions:
            if resolution.get('risk_id') != rid:
                continue
            if not bound(resolution, digest):
                continue
            # Validate even rejected provider times; never clamp fabricated timestamps.
            times = interval(resolution.get('interval'), duration)
            if times[0] > span[0] or times[1] < span[1]:
                continue
            capability = resolution.get('capability')
            if risk.get('kind') in ('pronunciation', 'naturalness') and capability not in ('human_listening', 'audio_understanding', 'local_phonetic_analysis'):
                continue
            if capability not in ('human_listening', 'audio_understanding', 'local_phonetic_analysis', 'local_measurement', 'transcription'):
                continue
            if capability == 'audio_understanding':
                adapter = resolution.get('adapter', {})
                if not isinstance(adapter, dict) or adapter.get('verified') is not True or adapter.get('capability') != capability or not adapter.get('official_docs_url') or adapter.get('sample_verified') is not True:
                    continue
            if risk.get('kind') == 'naturalness' and capability == 'local_phonetic_analysis':
                continue
            if resolution.get('status') != 'resolved':
                continue
            proof = evidence_record(dict(resolution, coverage=[times]), 'risk_resolution', digest, base)
            if not proof or any(proof.get(key) != resolution.get(key) for key in ('risk_id', 'capability', 'interval', 'reviewer', 'evidence')) or proof.get('text_sha256') != expected_hash:
                continue
            if capability == 'local_phonetic_analysis':
                text_value(proof.get('acoustic_observations'), 'acoustic observations')
                text_value(proof.get('phoneme_findings'), 'phoneme findings')
                if proof.get('audio_analyzed') is not True:
                    continue
            text_value(resolution.get('reviewer'), 'reviewer')
            text_value(resolution.get('evidence'), 'resolution evidence')
            if resolution.get('status') == 'resolved':
                valid = True
        if not valid:
            unresolved.append({'id': rid, 'kind': risk.get('kind'), 'interval': span, 'text':risk.get('text'), 'reason':risk.get('reason')})
    if heard == 'failed':
        blockers.append('heard_review:failed')
    # A claimed full listening pass itself needs version-bound full coverage evidence.
    if heard == 'passed':
        listening = item.get('listening_evidence', {})
        if not isinstance(listening, dict):
            raise ValueError('listening evidence must be object')
        adapter = listening.get('adapter', {})
        if not isinstance(adapter, dict):
            raise ValueError('listening adapter must be object')
        substantiated = listening.get('status') == 'passed' and bool(listening.get('reviewer') and listening.get('evidence'))
        if listening.get('status') == 'failed':
            blockers.append('listening_evidence:failed')
            heard = 'failed'
        if substantiated:
            text_value(listening['reviewer'], 'listening reviewer')
            text_value(listening['evidence'], 'listening evidence')
            proof = evidence_record(listening, 'listening', digest, base)
            substantiated = bool(proof) and proof.get('status') == 'passed' and all(proof.get(key) == listening.get(key) for key in ('reviewer', 'evidence', 'capability'))
        cloud_ok = listening.get('capability') != 'audio_understanding' or (adapter.get('verified') is True and adapter.get('capability') == 'audio_understanding' and adapter.get('official_docs_url') and adapter.get('sample_verified') is True)
        if not substantiated or not cloud_ok or not bound(listening, digest) or listening.get('capability') not in ('human_listening', 'audio_understanding') or not covered(listening.get('coverage', []), duration):
            missing.append('heard_review:unsubstantiated')
            if heard != 'failed':
                heard = 'not_performed'
    stage = 'blocked' if missing or blockers else ('review_required' if unresolved else 'local_pass')
    return {'id': ident, 'source_sha256': digest, 'stage': stage, 'required_checks': required,
            'coverage': coverage, 'missing': missing, 'blockers': blockers, 'unresolved_risks': unresolved,
            'asr_source': safe_asr, 'heard_review': heard,
            'overall_pass': False, 'evidence_basis': 'probe_and_decode_executed;external_content_records_hash_verified_not_authenticated', 'automatic_checks': automatic_checks, 'external_checks': [x for x in required if x != 'decode'],
            'delivery_note': '本地检查通过；不等于完整听审通过。' if stage == 'local_pass' else '仍有缺项或未决疑点，尚未通过本地交付检查。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    src, out = pathlib.Path(args.manifest).resolve(), pathlib.Path(args.output).resolve()
    cfg = json.loads(src.read_text(encoding='utf-8-sig'))
    if not isinstance(cfg, dict):
        raise ValueError('manifest must be object')
    items = cfg.get('items')
    if not isinstance(items, list) or not items or any(not isinstance(i, dict) for i in items):
        raise ValueError('items must be nonempty')
    if out.exists() or out == src or any(isinstance(i.get('media'), str) and out == (src.parent / i['media']).resolve() for i in items):
        raise ValueError('output must be new and distinct from inputs')
    ids = [text_value(i.get('id'), 'item ID') for i in items]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate ID')
    results = []
    for item in items:
        try:
            results.append(decide(item, src.parent))
        except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
            results.append({'id': item['id'], 'stage': 'blocked', 'error_type': type(exc).__name__, 'error': 'Invalid or inaccessible evidence; no acceptance issued', 'overall_pass': False})
    with out.open('x', encoding='utf-8') as f:
        json.dump({'items': results, 'network_calls': 0, 'overall_pass': False}, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'output': str(out), 'stages': [r['stage'] for r in results]}))
    return 0 if all(r['stage'] == 'local_pass' for r in results) else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, TypeError, KeyError, OSError, OverflowError):
        print('Invalid manifest or output conflict; no acceptance issued', file=sys.stderr)
        sys.exit(1)
