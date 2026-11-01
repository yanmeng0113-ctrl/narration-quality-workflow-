import io
import unittest
import wave
from reviewer_adapter import build_request, validate_response


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        buf=io.BytesIO()
        with wave.open(buf,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0'*16000)
        self.wav=buf.getvalue()
        self.cfg={'capability':'audio_understanding','request_planning_enabled':True,'model':'explicit-test-model','official_docs_url':'https://example.invalid/test-only','max_clip_seconds':5}
        self.ctx={'risk_id':'p1','source_sha256':'a'*64,'source_interval':[10,11],'source_duration_seconds':30,'question':'Is the ending clipped?'}

    def test_default_disabled(self):
        self.cfg['request_planning_enabled']=False
        with self.assertRaises(ValueError):build_request(self.cfg,self.wav,self.ctx)

    def test_transcription_not_audio_understanding(self):
        self.cfg['capability']='transcription'
        with self.assertRaises(ValueError):build_request(self.cfg,self.wav,self.ctx)

    def test_offline_payload_and_mapping(self):
        result=build_request(self.cfg,self.wav,self.ctx)
        self.assertEqual(result['receipt']['network_calls'],0)
        self.assertFalse(result['receipt']['execution_authorized'])
        self.assertEqual(result['request']['messages'][0]['content'][0]['type'],'audio_url')
        response=validate_response({'findings':[{'status':'uncertain','interval':[0,1],'evidence':'synthetic'}]},result['receipt'])
        self.assertEqual(response['findings'][0]['source_interval'],[10,11])
        self.assertEqual(response['stage'],'review_required')

    def test_response_outside_clip_even_inside_full_media(self):
        result=build_request(self.cfg,self.wav,self.ctx)
        with self.assertRaises(ValueError):validate_response({'findings':[{'status':'clear','interval':[0,2],'evidence':'synthetic'}]},result['receipt'])
        with self.assertRaises(ValueError):validate_response({'text':'transcription only'},result['receipt'])

    def test_mapping_rejects_duration_tolerance_overrun(self):
        self.ctx['source_interval']=[0,0.96]
        self.ctx['source_duration_seconds']=0.96
        result=build_request(self.cfg,self.wav,self.ctx)
        with self.assertRaises(ValueError):validate_response({'findings':[{'status':'clear','interval':[0,1],'evidence':'synthetic'}]},result['receipt'])

    def test_invalid_receipt(self):
        result=build_request(self.cfg,self.wav,self.ctx)
        result['receipt']['source_interval']=[100,101]
        with self.assertRaises(ValueError):validate_response({'findings':[{'status':'clear','interval':[0,1],'evidence':'synthetic'}]},result['receipt'])

    def test_malformed_finding(self):
        result=build_request(self.cfg,self.wav,self.ctx)
        with self.assertRaises(ValueError):validate_response({'findings':['bad']},result['receipt'])

    def test_clip_duration_mismatch(self):
        self.ctx['source_interval']=[10,12]
        with self.assertRaises(ValueError):build_request(self.cfg,self.wav,self.ctx)
