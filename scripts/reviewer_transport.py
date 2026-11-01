#!/usr/bin/env python3
"""Optional one-shot SiliconFlow transport; disabled unless explicitly authorized."""
import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from audit_audio import reject_credentials
from plan_adapter import text_value, finite_number
from reviewer_adapter import build_request, validate_response
from staged_review import media_facts

ENDPOINT = 'https://api.siliconflow.cn/v1/chat/completions'
MAX_RESPONSE_BYTES = 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(ENDPOINT, code, 'redirect rejected', {}, None)


def send_http(request):
    # No redirects and no retries; never forward Authorization to a different host.
    opener = urllib.request.build_opener(NoRedirect())
    return opener.open(request, timeout=60)


def finite_nonnegative(value):
    return finite_number(value) and value >= 0


def reject_response_echo(value, credential, audio_payload, depth=0):
    """Scan both JSON layers, all keys/values, and decoded escape spellings."""
    if depth > 64:
        raise ValueError('response nesting limit exceeded')
    if isinstance(value, dict):
        for key, child in value.items():
            reject_response_echo(key, credential, audio_payload, depth+1)
            reject_response_echo(child, credential, audio_payload, depth+1)
    elif isinstance(value, list):
        for child in value:
            reject_response_echo(child, credential, audio_payload, depth+1)
    elif isinstance(value, str):
        normalized = value.replace('\\/', '/')
        # Provider content is JSON inside JSON. Inspect escaped forms before parsing too.
        for _ in range(4):
            decoded = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), normalized)
            if decoded == normalized:
                break
            normalized = decoded
        if credential in normalized or audio_payload in normalized or 'base64,' in normalized.lower():
            raise ValueError('sensitive response content rejected')


def execute_review(config, context, clip, source, execute=False):
    """The caller must have actual upload/payment authority; booleans are records, not grants."""
    if not isinstance(config, dict) or not isinstance(context, dict):
        raise ValueError('config and context must be objects')
    reject_credentials(config)
    reject_credentials(context)
    if execute is not True or config.get('execution_enabled') is not True:
        raise ValueError('execution disabled')
    if config.get('provider') != 'siliconflow' or config.get('endpoint', ENDPOINT) != ENDPOINT:
        raise ValueError('only fixed official endpoint supported')
    for flag in ('model_verified', 'audio_input_verified', 'pricing_verified', 'upload_authorized', 'payment_authorized'):
        if config.get(flag) is not True:
            raise ValueError('required verification or authorization missing')
    for field in ('model', 'verification_date', 'pricing_checked_at', 'approval_reference', 'official_docs_url'):
        text_value(config.get(field), 'required configuration')
    if not config['official_docs_url'].startswith('https://docs.siliconflow.cn/'):
        raise ValueError('official documentation reference required')
    pricing = config.get('pricing', {})
    if not isinstance(pricing, dict) or pricing.get('currency') not in ('CNY', 'USD'):
        raise ValueError('explicit pricing currency required')
    for field in ('input_per_million', 'output_per_million', 'audio_units_per_second'):
        if not finite_nonnegative(pricing.get(field)):
            raise ValueError('verified finite pricing required')
    if (pricing['input_per_million'] == 0 or pricing['output_per_million'] == 0) and config.get('free_tariff_verified') is not True:
        raise ValueError('zero pricing requires verified free tariff')
    if pricing['audio_units_per_second'] <= 0:
        raise ValueError('verified positive audio metering rate required')
    budget = config.get('remaining_budget')
    output_limit = config.get('output_limit')
    if not finite_nonnegative(budget) or isinstance(output_limit, bool) or not isinstance(output_limit, int) or not 1 <= output_limit <= 4096:
        raise ValueError('budget and bounded output token limit required')
    clip_bytes = pathlib.Path(clip).read_bytes()
    source_bytes = pathlib.Path(source).read_bytes()
    clip_hash = hashlib.sha256(clip_bytes).hexdigest()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if context.get('clip_sha256') != clip_hash or context.get('source_sha256') != source_hash:
        raise ValueError('source or clip hash mismatch')
    if config.get('approved_clip_sha256') != clip_hash or config.get('approved_source_sha256') != source_hash:
        raise ValueError('authorization must bind this source and clip')
    if not finite_nonnegative(context.get('source_duration_seconds')):
        raise ValueError('finite source duration required')
    duration, streams = media_facts(pathlib.Path(source))
    if 'audio' not in streams or abs(duration-context.get('source_duration_seconds', -1)) > 0.001:
        raise ValueError('source duration or audio stream mismatch')
    built = build_request(config, clip_bytes, context)
    payload, receipt = built['request'], built['receipt']
    # Conservative text upper bound: UTF-8 bytes plus protocol overhead, not transcript hints.
    text = payload['messages'][0]['content'][1]['text']
    input_tokens = math.ceil(receipt['clip_duration_seconds'] * pricing['audio_units_per_second']) + len(text.encode('utf-8')) + 1024
    maximum_cost = (input_tokens * pricing['input_per_million'] + output_limit * pricing['output_per_million']) / 1_000_000
    if maximum_cost > budget:
        raise ValueError('estimated maximum request cost exceeds remaining budget')
    payload['max_tokens'] = output_limit
    # Only read existing environment credentials after all authorization/input preflight.
    credential = os.environ.get('SILICONFLOW_API_KEY')
    if not credential or '\n' in credential or '\r' in credential:
        raise ValueError('required environment credential unavailable')
    audio_payload = payload['messages'][0]['content'][0]['audio_url']['url'].split(',', 1)[1]
    reject_response_echo(config, credential, audio_payload)
    reject_response_echo(context, credential, audio_payload)
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + credential, 'Content-Type':'application/json'}, method='POST')
    safe = {'source_sha256':source_hash, 'clip_sha256':clip_hash, 'risk_id':context['risk_id'],
            'model':config['model'], 'network_attempts':1, 'automatic_retries':0,
            'estimated_request_cost':maximum_cost, 'cost_note':'Conservative estimate, not a verified billed cap; actual usage and billing must be reconciled', 'currency':pricing['currency'],
            'stage':'review_required', 'heard_review':'not_performed', 'live_quality_validated':False}
    try:
        with send_http(request) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return dict(safe, status='invalid_response', error='response exceeded size limit')
    except urllib.error.HTTPError as exc:
        return dict(safe, status='http_error', http_status=exc.code, error='request failed; provider body withheld; do not retry automatically')
    except Exception:
        # Only the attempted HTTP open/read/context boundary; never echo raw exceptions.
        # BaseException (including KeyboardInterrupt) and independent preflight stay outside.
        return dict(safe, status='outcome_unknown', error='delivery or completion unknown; verify before any new attempt')
    try:
        audio_payload = payload['messages'][0]['content'][0]['audio_url']['url'].split(',', 1)[1]
        reject_response_echo(raw.decode('utf-8'), credential, audio_payload)
        envelope = json.loads(raw)
        reject_response_echo(envelope, credential, audio_payload)
        content = envelope['choices'][0]['message']['content']
        if not isinstance(content, str):
            raise ValueError('structured review text required')
        reject_response_echo(content, credential, audio_payload)
        parsed = json.loads(content)
        reject_response_echo(parsed, credential, audio_payload)
        result = validate_response(parsed, receipt)
        reject_response_echo(result, credential, audio_payload)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        return dict(safe, status='invalid_response', error='unusable or out-of-bounds evidence; response body withheld')
    return dict(safe, status='candidate_received', review=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'context', 'clip', 'source', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    paths = {name:pathlib.Path(getattr(args, name)).resolve() for name in ('config', 'context', 'clip', 'source', 'output')}
    out = paths['output']
    if out.exists() or out in [paths[n] for n in ('config', 'context', 'clip', 'source')]:
        raise ValueError('output must be a new file distinct from inputs')
    if not out.parent.is_dir() or not os.access(out.parent, os.W_OK):
        raise ValueError('output directory unavailable')
    config = json.loads(paths['config'].read_text(encoding='utf-8-sig'))
    context = json.loads(paths['context'].read_text(encoding='utf-8-sig'))
    result = execute_review(config, context, paths['clip'], paths['source'], args.execute)
    with out.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'status':result['status'], 'stage':result['stage'], 'network_attempts':1}))
    return 0 if result['status'] == 'candidate_received' else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        print('Preflight or output failed; no acceptance issued. Raw details withheld.', file=sys.stderr)
        sys.exit(1)
