import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
TARGET=Path(os.environ.get('AUDIT_TARGET',ROOT/'audit_audio.py'))
spec=importlib.util.spec_from_file_location('audit_target',TARGET)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class AuditRegressionTests(unittest.TestCase):
    def test_huge_threshold_rejected(self):
        with self.assertRaises(ValueError):audit.number(10**400, "threshold")

    def test_no_raw_tool_stderr(self):
        from types import SimpleNamespace
        with patch.object(audit.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='password:DummyCredential123456')):
            with self.assertRaises(RuntimeError) as cm:audit.run(['ffprobe','test'])
        self.assertNotIn('DummyCredential',str(cm.exception))
    def test_credential_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest.json'
            for text in ['api_key:DummyCredential123456','token=DummyCredential123456']:
                p.write_text(json.dumps({'items':[{'id':'a','audio':'unused.wav','expected_text':text}]}))
                with self.assertRaises(ValueError) as cm:audit.load_manifest(p)
                self.assertNotIn('DummyCredential',str(cm.exception))
    def test_plain_english_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';p.write_text(json.dumps({'items':[{'id':'a','audio':'unused.wav','expected_text':'Here is the secret: stay calm.'}]}))
            self.assertEqual(len(audit.load_manifest(p)[0]),1)
    def test_decode_state_survives_later_failure(self):
        state={'decode_ok':None}
        def run(args):
            if args[0]=='ffprobe':return json.dumps({'format':{'duration':1}}),''
            if '-xerror' in args:return '', ''
            raise RuntimeError('analysis failed')
        with patch.object(audit,'run',side_effect=run):
            with self.assertRaises(RuntimeError):audit.audit('a',Path('not-read.wav'),'not_performed',None,None,-1,-35,'ffmpeg','ffprobe',state)
        self.assertTrue(state['decode_ok'])
    def test_decode_failure_false(self):
        state={'decode_ok':None}
        with patch.object(audit,'run',side_effect=[(json.dumps({'format':{'duration':1}}),''),RuntimeError('decode failed')]):
            with self.assertRaises(RuntimeError):audit.audit('a',Path('not-read.wav'),'not_performed',None,None,-1,-35,'ffmpeg','ffprobe',state)
        self.assertIs(state['decode_ok'],False)
    def test_preflight_once(self):
        with patch.object(audit.shutil,'which',side_effect=lambda name:name),patch.object(audit,'run',return_value=('version','')) as run:
            self.assertIsNone(audit.preflight('ffmpeg','ffprobe'))
            self.assertEqual(run.call_count,2)
    def test_missing_tool_batch_reports_unknown_decode(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);m=d/'manifest.json';o=d/'report.json'
            m.write_text(json.dumps({'items':[{'id':i,'audio':'missing.wav'} for i in ['a','b','c']]}))
            with patch.object(sys,'argv',['audit','--manifest',str(m),'--output',str(o),'--ffmpeg','definitely-nonexistent-ffmpeg']),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:audit.main()
            self.assertEqual(cm.exception.code,2)
            report=json.loads(o.read_text());self.assertEqual(len(report['items']),3)
            self.assertTrue(all(x['decode_ok'] is None for x in report['items']))
            self.assertEqual(report['preflight']['status'],'failed')

if __name__=='__main__':unittest.main()
