import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from plan_adapter import plan, reject_credentials

DUMMY='Bearer DUMMYabcdefghijklmnop'
def manifest():return {'segments':[{'id':'a','text':'Ordinary English sentence.','request':{}}]}
def adapter():return {'name':'offline','verified':True,'fields':{},'prompt':{'mode':'none'}}

class PlannerCredentialKeyTests(unittest.TestCase):
    def assert_rejected_without_echo(self,m,a):
        with self.assertRaises(ValueError) as error:plan(m,a)
        self.assertNotIn('DUMMY',str(error.exception))
    def test_dropped_request_key(self):
        m=manifest();m['segments'][0]['request'][DUMMY]='ordinary';self.assert_rejected_without_echo(m,adapter())
    def test_adapter_constraint_error_key(self):
        a=adapter();a['fields'][DUMMY]={'type':'number','min':'bad'};self.assert_rejected_without_echo(manifest(),a)
    def test_unused_nested_keys_and_values(self):
        for payload in ({DUMMY:'ordinary'},{'ordinary':[{'deeper':DUMMY}]}):
            m=manifest();m['unused']=payload;self.assert_rejected_without_echo(m,adapter())
    def test_colon_equal_key(self):
        for key in ('token:DummyCredential123456','api_key=DummyCredential123456'):
            m=manifest();m['segments'][0]['request'][key]='ordinary';self.assert_rejected_without_echo(m,adapter())
    def test_plain_english_key(self):
        m=manifest();key='He was the bearer of bad news.';m['segments'][0]['request'][key]='ordinary'
        self.assertEqual(plan(m,adapter())['segments'][0]['dropped'][0]['field'],key)
    def test_composite_keys_nested_all_value_types(self):
        keys=('access_token','refresh-token','CLIENT_SECRET','api.key','private key','AccessToken','AWS_SECRET_ACCESS_KEY','ssh_private_key')
        for key in keys:
            for value in ('DUMMY-not-a-real-key', 1, True, None, [], {}):
                with self.subTest(key=key, value_type=type(value).__name__):
                    with self.assertRaises(ValueError) as error:reject_credentials({'metadata':[{'nested':{key:value}}]})
                    self.assertNotIn('DUMMY',str(error.exception))
                    self.assertNotIn(key,str(error.exception))
    def test_plain_english_metadata_keys(self):
        for key in ('How to refresh a token', 'The private key lesson', 'Here is the secret: stay calm.', 'tokenization_notes'):
            reject_credentials({key:'ordinary English'})
    def test_huge_numeric_inputs(self):
        huge=10**1000
        a=adapter();a['fields']['speed']={'type':'number'}
        m=manifest();m['segments'][0]['request']['speed']=huge
        self.assert_rejected_without_echo(m,a)
        for spec in ({'type':'number','min':huge},{'type':'number','enum':[huge]}):
            a=adapter();a['fields']['speed']=spec;self.assert_rejected_without_echo(manifest(),a)

    def test_cli_key_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);m=manifest();m['segments'][0]['request'][DUMMY]='ordinary'
            (d/'manifest.json').write_text(json.dumps(m));(d/'adapter.json').write_text(json.dumps(adapter()))
            p=subprocess.run([sys.executable,str(Path(__file__).with_name('plan_adapter.py')),'--manifest',str(d/'manifest.json'),'--adapter',str(d/'adapter.json'),'--output',str(d/'out.json')],capture_output=True,text=True)
            self.assertEqual(p.returncode,1);self.assertFalse((d/'out.json').exists());self.assertNotIn('DUMMY',p.stdout+p.stderr)

if __name__=='__main__':unittest.main()
