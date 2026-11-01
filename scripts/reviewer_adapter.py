"""Offline audio-understanding request/response contract. No HTTP client or paid calls."""
import base64
import hashlib
import io
import wave
from audit_audio import reject_credentials
from plan_adapter import text_value
from staged_review import interval


def build_request(config, clip_bytes, context):
    """Build only; caller must separately obtain upload/payment authorization before sending."""
    reject_credentials(config)
    reject_credentials(context)
    if config.get('capability') != 'audio_understanding' or config.get('request_planning_enabled') is not True:
        raise ValueError('audio-understanding request planning disabled')
    model = text_value(config.get('model'), 'explicit model')
    text_value(config.get('official_docs_url'), 'official docs URL')
    span = interval(context.get('source_interval'), context.get('source_duration_seconds'))
    limit = config.get('max_clip_seconds')
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 < limit <= 60 or span[1]-span[0] > limit:
        raise ValueError('short clip limit required/exceeded')
    text_value(context.get('risk_id'), 'risk ID')
    text_value(context.get('source_sha256'), 'source hash')
    with wave.open(io.BytesIO(clip_bytes), 'rb') as wav:
        duration = wav.getnframes()/wav.getframerate()
    if abs(duration-(span[1]-span[0])) > 0.05:
        raise ValueError('clip duration differs from source interval')
    question = text_value(context.get('question'), 'review question')
    prompt = ('Review only this audio clip for the stated uncertainty. Do not infer sound from spelling. '
              'Return JSON {findings:[{status:clear|issue|uncertain, interval:[start,end], evidence:string}]}; '
              'times are seconds relative to this clip. If uncertain say uncertain; never invent times. Question: ' + question)
    return {'request': {'model': model, 'messages': [{'role':'user','content':[
        {'type':'audio_url','audio_url':{'url':'data:audio/wav;base64,'+base64.b64encode(clip_bytes).decode()}},
        {'type':'text','text':prompt}]}]},
        'receipt': {'risk_id':context['risk_id'], 'source_sha256':context['source_sha256'],
                    'source_interval':span, 'source_duration_seconds':context['source_duration_seconds'], 'clip_sha256':hashlib.sha256(clip_bytes).hexdigest(),
                    'clip_duration_seconds':duration, 'capability':'audio_understanding',
                    'validation_status':'docs-supported/offline-tested/not-live-validated',
                    'execution_authorized':False, 'network_calls':0}}


def validate_response(response, receipt):
    """Validate parsed response, retaining uncertainty; never emit a listening pass."""
    reject_credentials(response)
    source_span = interval(receipt.get('source_interval'), receipt.get('source_duration_seconds'))
    if abs(receipt['clip_duration_seconds']-(source_span[1]-source_span[0])) > 0.05:
        raise ValueError('receipt duration mismatch')
    if not isinstance(response, dict) or not isinstance(response.get('findings'), list) or not response['findings']:
        raise ValueError('nonempty structured findings required; transcription text is not a review')
    results = []
    for finding in response['findings']:
        if not isinstance(finding, dict):
            raise ValueError('finding must be object')
        span = interval(finding.get('interval'), receipt['clip_duration_seconds'])
        status = finding.get('status')
        if status not in ('clear', 'issue', 'uncertain'):
            raise ValueError('invalid finding status')
        evidence = text_value(finding.get('evidence'), 'audio evidence')
        offset = receipt['source_interval'][0]
        mapped = [offset+span[0], offset+span[1]]
        interval(mapped, receipt['source_duration_seconds'])
        if mapped[0] < source_span[0] or mapped[1] > source_span[1]:
            raise ValueError('finding exceeds exact source clip interval')
        results.append({'status':status, 'clip_interval':span,
                        'source_interval':[offset+span[0],offset+span[1]], 'evidence':evidence})
    return {'findings':results, 'source_sha256':receipt['source_sha256'],
            'clip_sha256':receipt['clip_sha256'], 'risk_id':receipt['risk_id'],
            'stage':'review_required', 'heard_review':'not_performed',
            'note':'Candidate evidence only; response schema validation is not verified listening.'}
