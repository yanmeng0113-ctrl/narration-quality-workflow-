import copy
import contextlib
import http.client
import base64
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
import urllib.error
import wave
from unittest.mock import patch
import reviewer_transport as transport


class TransportTests(unittest.TestCase):
    def test_deep_json_response_is_safe_invalid_response(self):
        deep='['*1100+'0'+']'*1100
        responses=[deep.encode(),json.dumps({'choices':[{'message':{'content':deep}}]}).encode()]
        for raw in responses:
            with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy-never-print'}),patch.object(transport,'send_http',return_value=io.BytesIO(raw)) as send:
                result=self.run_review();self.assertEqual(result['status'],'invalid_response')
                self.assertEqual(result['network_attempts'],1);self.assertEqual(send.call_count,1)
                self.assertNotIn('dummy-never-print',json.dumps(result))

    def test_response_nesting_limit_before_python_recursion(self):
        value='ordinary'
        for _ in range(65):value={'nested':value}
        with self.assertRaises(ValueError):transport.reject_response_echo(value,'dummy','audio-payload')

    def test_open_http_exception_is_sanitized_unknown(self):
        for error in (http.client.BadStatusLine('dummy-never-print'), RuntimeError('dummy-never-print')):
            with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy-never-print'}),patch.object(transport,'send_http',side_effect=error) as send:
                result=self.run_review()
                self.assertEqual(result['status'],'outcome_unknown');self.assertEqual(result['network_attempts'],1)
                self.assertEqual(result['automatic_retries'],0);self.assertEqual(send.call_count,1)
                self.assertNotIn('dummy-never-print',json.dumps(result))

    def test_read_incomplete_is_sanitized_unknown(self):
        class BrokenRead(io.BytesIO):
            def read(self, *args):raise http.client.IncompleteRead(b'dummy-never-print',100)
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy-never-print'}),patch.object(transport,'send_http',return_value=BrokenRead()) as send:
            result=self.run_review()
            self.assertEqual(result['status'],'outcome_unknown');self.assertEqual(send.call_count,1)
            self.assertNotIn('dummy-never-print',json.dumps(result))

    def test_transport_keyboard_interrupt_not_swallowed(self):
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy'}),patch.object(transport,'send_http',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.run_review()

    def test_cli_http_exceptions_write_safe_receipt(self):
        class BrokenRead(io.BytesIO):
            def read(self, *args):raise http.client.IncompleteRead(b'dummy-never-print',100)
        cfg=self.path.parent/'config.json';cfg.write_text(json.dumps(self.config))
        ctx=self.path.parent/'context.json';ctx.write_text(json.dumps(self.context))
        for index,kind in enumerate(('open','read','deep')):
            out=self.path.parent/('output-%s.json'%index)
            argv=['reviewer_transport.py','--config',str(cfg),'--context',str(ctx),'--clip',str(self.path),'--source',str(self.path),'--output',str(out),'--execute']
            stdout,stderr=io.StringIO(),io.StringIO()
            kwargs={'side_effect':http.client.BadStatusLine('dummy-never-print')} if kind=='open' else {'return_value':BrokenRead() if kind=='read' else io.BytesIO(('['*1100+'0'+']'*1100).encode())}
            with patch.object(sys,'argv',argv),patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy-never-print'}),patch.object(transport,'send_http',**kwargs) as send,contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                self.assertEqual(transport.main(),2)
            record=json.loads(out.read_text());self.assertEqual(record['status'],'invalid_response' if kind=='deep' else 'outcome_unknown');self.assertEqual(send.call_count,1)
            combined=stdout.getvalue()+stderr.getvalue()+out.read_text()
            self.assertNotIn('dummy-never-print',combined);self.assertNotIn('Traceback',combined)

    def test_actual_credential_in_metadata_rejected_before_network(self):
        self.config['model']='dummy-never-print'
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy-never-print'}),patch.object(transport,'send_http') as send:
            with self.assertRaises(ValueError) as caught:self.run_review()
            self.assertNotIn('dummy-never-print',str(caught.exception));send.assert_not_called()

    def test_huge_numeric_preflight(self):
        for field in ('remaining_budget',):
            self.config[field]=10**400
            with patch.object(transport,'send_http') as send:
                with self.assertRaises(ValueError):self.run_review()
                send.assert_not_called()
        self.config['remaining_budget']=1
        self.context['source_duration_seconds']=10**400
        with patch.object(transport,'send_http') as send:
            with self.assertRaises(ValueError):self.run_review()
            send.assert_not_called()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=pathlib.Path(self.temp.name)/'clip.wav'
        with wave.open(str(self.path),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0'*16000)
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.config={'provider':'siliconflow','execution_enabled':True,'request_planning_enabled':True,
            'capability':'audio_understanding','model':'explicit-test-model','model_verified':True,
            'audio_input_verified':True,'pricing_verified':True,'upload_authorized':True,'payment_authorized':True,
            'verification_date':'2026-11-01','pricing_checked_at':'2026-11-01','approval_reference':'test-only mock approval',
            'official_docs_url':'https://docs.siliconflow.cn/docs/userguide/capabilities/multimodal-vision',
            'pricing':{'currency':'CNY','input_per_million':1,'output_per_million':1,'audio_units_per_second':13},
            'remaining_budget':1,'output_limit':512,'max_clip_seconds':5,
            'approved_clip_sha256':digest,'approved_source_sha256':digest}
        self.context={'source_sha256':digest,'clip_sha256':digest,'source_interval':[0,1],
            'source_duration_seconds':1,'risk_id':'risk-1','question':'Check the ending.'}
        self.response={'choices':[{'message':{'content':json.dumps({'findings':[{'status':'uncertain','interval':[0,1],'evidence':'mock fixture only'}]})}}]}

    def run_review(self):
        return transport.execute_review(self.config,self.context,self.path,self.path,execute=True)

    def test_default_disabled_before_credential(self):
        with patch.object(transport.os.environ,'get') as env, patch.object(transport,'send_http') as send:
            with self.assertRaises(ValueError):transport.execute_review(self.config,self.context,self.path,self.path)
            env.assert_not_called();send.assert_not_called()

    def test_preflight_authorization_pricing_and_hash(self):
        baseline=copy.deepcopy(self.config)
        for field in ('model_verified','audio_input_verified','pricing_verified','upload_authorized','payment_authorized'):
            self.config=copy.deepcopy(baseline);self.config[field]=False
            with patch.object(transport.os.environ,'get') as env, patch.object(transport,'send_http') as send:
                with self.assertRaises(ValueError):self.run_review()
                env.assert_not_called();send.assert_not_called()
        self.config=copy.deepcopy(baseline);self.config['remaining_budget']=0
        with patch.object(transport,'send_http') as send:
            with self.assertRaises(ValueError):self.run_review()
            send.assert_not_called()
        self.config=copy.deepcopy(baseline);self.context['clip_sha256']='0'*64
        with self.assertRaises(ValueError):self.run_review()

    def test_malformed_and_missing_pricing_fail_closed(self):
        for cfg,ctx in (([],self.context),(self.config,[])):
            with patch.object(transport.os.environ,'get') as env,patch.object(transport,'send_http') as send:
                with self.assertRaises(ValueError):transport.execute_review(cfg,ctx,self.path,self.path,True)
                env.assert_not_called();send.assert_not_called()
        for pricing in ({}, {'currency':'CNY','input_per_million':0,'output_per_million':0,'audio_units_per_second':13}):
            self.config['pricing']=pricing
            with patch.object(transport.os.environ,'get') as env,patch.object(transport,'send_http') as send:
                with self.assertRaises(ValueError):self.run_review()
                env.assert_not_called();send.assert_not_called()

    def test_success_candidate_not_pass(self):
        raw=json.dumps(self.response).encode()
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy-never-print'}), patch.object(transport,'send_http',return_value=io.BytesIO(raw)) as send:
            result=self.run_review()
            self.assertEqual(result['status'],'candidate_received')
            self.assertEqual(result['stage'],'review_required')
            self.assertEqual(result['heard_review'],'not_performed')
            self.assertNotIn('dummy-never-print',json.dumps(result))
            self.assertNotIn('base64',json.dumps(result))
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0].full_url,transport.ENDPOINT)

    def test_http_failure_no_response_echo_or_retry(self):
        error=urllib.error.HTTPError(transport.ENDPOINT,429,'dummy-secret',{},None)
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy'}), patch.object(transport,'send_http',side_effect=error) as send:
            result=self.run_review()
            self.assertEqual(result['status'],'http_error');self.assertEqual(send.call_count,1)
            self.assertNotIn('dummy-secret',json.dumps(result))

    def test_unknown_outcome_no_retry(self):
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy'}), patch.object(transport,'send_http',side_effect=TimeoutError('do not echo')) as send:
            result=self.run_review()
            self.assertEqual(result['status'],'outcome_unknown');self.assertEqual(send.call_count,1)
            self.assertNotIn('do not echo',json.dumps(result))

    def test_out_of_bounds_response(self):
        self.response['choices'][0]['message']['content']=json.dumps({'findings':[{'status':'clear','interval':[0,2],'evidence':'mock'}]})
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy'}), patch.object(transport,'send_http',return_value=io.BytesIO(json.dumps(self.response).encode())):
            result=self.run_review();self.assertEqual(result['status'],'invalid_response')

    def test_sensitive_response_not_echoed(self):
        self.response['choices'][0]['message']['content']=json.dumps({'findings':[{'status':'clear','interval':[0,1],'evidence':'data:audio/wav;base64,abc'}]})
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy'}), patch.object(transport,'send_http',return_value=io.BytesIO(json.dumps(self.response).encode())):
            result=self.run_review();self.assertEqual(result['status'],'invalid_response')
            self.assertNotIn('base64',json.dumps(result))

    def test_unicode_escaped_secret_in_nested_keys_and_values(self):
        secret='dummy-never-print'
        encoded=''.join('\\u%04x' % ord(c) for c in secret)
        for extra in ({'nested':{'key':secret}}, {'nested':{secret:'ordinary'}}):
            content={'findings':[{'status':'clear','interval':[0,1],'evidence':'mock'}], **extra}
            serialized=json.dumps(content).replace(secret,encoded)
            response={'choices':[{'message':{'content':serialized}}]}
            with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':secret}), patch.object(transport,'send_http',return_value=io.BytesIO(json.dumps(response).encode())):
                result=self.run_review()
                self.assertEqual(result['status'],'invalid_response')
                self.assertNotIn(secret,json.dumps(result))

    def test_unicode_escaped_secret_in_evidence_not_echoed(self):
        secret='dummy-never-print'
        encoded=''.join('\\u%04x' % ord(c) for c in secret)
        content=json.dumps({'findings':[{'status':'clear','interval':[0,1],'evidence':secret}]}).replace(secret,encoded)
        response={'choices':[{'message':{'content':content}}]}
        with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':secret}), patch.object(transport,'send_http',return_value=io.BytesIO(json.dumps(response).encode())):
            result=self.run_review()
            self.assertEqual(result['status'],'invalid_response')
            self.assertNotIn(secret,json.dumps(result))

    def test_encoded_audio_payload_not_echoed(self):
        payload=base64.b64encode(self.path.read_bytes()).decode()
        for value in (payload, 'data:audio/wav;base64,'+payload):
            encoded=''.join('\\u%04x' % ord(c) for c in value)
            content=json.dumps({'findings':[{'status':'clear','interval':[0,1],'evidence':value}]}).replace(value,encoded)
            response={'choices':[{'message':{'content':content}}]}
            with patch.dict(transport.os.environ,{'SILICONFLOW_API_KEY':'dummy'}), patch.object(transport,'send_http',return_value=io.BytesIO(json.dumps(response).encode())):
                result=self.run_review()
                self.assertEqual(result['status'],'invalid_response')
                self.assertNotIn(payload,json.dumps(result))

    def test_cli_no_overwrite_before_network(self):
        out=self.path.parent/'output.json';out.write_text('original')
        cfg=self.path.parent/'config.json';cfg.write_text(json.dumps(self.config))
        ctx=self.path.parent/'context.json';ctx.write_text(json.dumps(self.context))
        argv=['reviewer_transport.py','--config',str(cfg),'--context',str(ctx),'--clip',str(self.path),'--source',str(self.path),'--output',str(out),'--execute']
        with patch.object(sys,'argv',argv),patch.object(transport,'send_http') as send:
            with self.assertRaises(ValueError):transport.main()
            send.assert_not_called();self.assertEqual(out.read_text(),'original')

    def test_unofficial_endpoint_rejected(self):
        self.config['endpoint']='https://example.invalid/chat'
        with patch.object(transport,'send_http') as send:
            with self.assertRaises(ValueError):self.run_review()
            send.assert_not_called()

    def test_redirect_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):
            transport.NoRedirect().redirect_request(None,None,302,'found',{},'https://example.invalid')


if __name__=='__main__':unittest.main()
