import copy, hashlib, json, os, subprocess, sys, tempfile, unittest, wave, struct
from pathlib import Path
from plan_adapter import plan

ROOT=Path(__file__).resolve().parent

def adapter():
    return {'name':'mock','verified':True,'fields':{'voice':{'type':'string'},'speed':{'type':'number','min':.25,'max':4},'response_format':{'type':'string','enum':['wav','mp3']},'gain':{'type':'number','min':-10,'max':10},'sample_rate':{'type':'number','enum':[24000,44100]},'prompt':{'type':'string'}},'prompt':{'mode':'field','field':'prompt','sample_verified':True}}
def manifest():return {'segments':[{'id':'s01','text':'露从今夜白。','intent':'平静叙述','request':{'voice':'v','speed':1.0}}]}

class PlannerTests(unittest.TestCase):
    def test_unsupported_intent_retained(self):
        a=adapter();a['prompt']={'mode':'none'};r=plan(manifest(),a)['segments'][0];self.assertEqual(r['dropped'][0]['value'],'平静叙述');self.assertEqual(r['intent_record'],'平静叙述');self.assertNotIn('prompt',r['request'])
    def test_intent_prompt_conflict(self):
        m=manifest();m['segments'][0]['request']['prompt']='explicit';self.assertRaises(ValueError,plan,m,adapter())
    def test_bad_hash(self):
        m=manifest();m['segments'][0]['text_sha256']='deadbeef';self.assertRaises(ValueError,plan,m,adapter())
    def test_correct_hash(self):
        m=manifest();m['segments'][0]['text_sha256']=hashlib.sha256(m['segments'][0]['text'].encode()).hexdigest();self.assertEqual(plan(m,adapter())['segments'][0]['text_sha256'],m['segments'][0]['text_sha256'])
    def test_empty_or_whitespace(self):
        for t in ('','   '):
            m=manifest();m['segments'][0]['text']=t;self.assertRaises(ValueError,plan,m,adapter())
    def test_speed_values(self):
        for v in (100,-1,'fast',True,float('nan')):
            m=manifest();m['segments'][0]['request']['speed']=v;self.assertRaises(ValueError,plan,m,adapter())
    def test_format_enum(self):
        m=manifest();m['segments'][0]['request']['response_format']='exe';self.assertRaises(ValueError,plan,m,adapter())
    def test_model_object(self):
        a=adapter();a['fields']['model']={'type':'string'};m=manifest();m['segments'][0]['request']['model']={};self.assertRaises(ValueError,plan,m,a)
    def test_extended_capabilities(self):
        m=manifest();m['segments'][0]['request'].update({'gain':0,'sample_rate':44100,'response_format':'wav'});r=plan(m,adapter());self.assertEqual(r['segments'][0]['request']['sample_rate'],44100)
    def test_brackets_are_text(self):
        m=manifest();m['segments'][0]['intent']='保留[参考]的语气';self.assertEqual(plan(m,adapter())['segments'][0]['request']['prompt'],m['segments'][0]['intent'])
    def test_long_ordinary_word(self):
        m=manifest();m['segments'][0]['text']='supercalifragilisticexpialidocious';self.assertEqual(plan(m,adapter())['segments'][0]['text'],m['segments'][0]['text'])
    def test_ordinary_sensitive_words(self):
        for text in ('Here is the secret: stay calm.','He was the bearer of bad news.','A desk-mounted-lamp is lit.'):
            m=manifest();m['segments'][0]['text']=text;self.assertEqual(plan(m,adapter())['segments'][0]['text'],text)
    def test_secret_not_echoed(self):
        m=manifest();m['segments'][0]['intent']='password=SuperSecretValue'
        with self.assertRaises(ValueError) as e:plan(m,adapter())
        self.assertNotIn('SuperSecretValue',str(e.exception))
    def test_sample_required(self):
        a=adapter();a['prompt']['sample_verified']=False;self.assertRaises(ValueError,plan,manifest(),a)
    def test_embedded_mode(self):
        a=adapter();a['prompt']={'mode':'embedded','separator':'<example-separator>','sample_verified':True};m=manifest();s=copy.deepcopy(m);r=plan(m,a)['segments'][0];self.assertEqual(m,s);self.assertTrue(r['request']['text'].endswith(s['segments'][0]['text']));self.assertEqual(r['id'],'s01')
    def test_no_mutation_when_switching(self):
        m=manifest();before=copy.deepcopy(m);a=adapter();b=adapter();b['fields']={};b['prompt']={'mode':'none'};x=plan(m,a);y=plan(m,b);self.assertEqual(m,before);self.assertEqual(x['segments'][0]['text_sha256'],y['segments'][0]['text_sha256']);self.assertEqual(x['segments'][0]['id'],y['segments'][0]['id'])
    def test_dropped_field_value_and_reason(self):
        m=manifest();m['segments'][0]['request']['unknown']='hello';d=plan(m,adapter())['segments'][0]['dropped'];self.assertIn({'field':'unknown','value':'hello','reason':'unsupported'},d)
    def test_credential_rejected(self):
        for k,v in [('api_key','x'),('other','Bearer abcdefghijklmnopqrst'),('misc','xoxb-123456789abcdef')]:
            m=manifest();m['segments'][0]['request'][k]=v;self.assertRaises(ValueError,plan,m,adapter())
    def test_secret_intent_rejected(self):
        m=manifest();m['segments'][0]['intent']='password=SuperSecretValue';self.assertRaises(ValueError,plan,m,adapter())
    def test_adapter_name_secret_rejected(self):
        a=adapter();a['name']='Bearer abcdefghijklmnopqrst';self.assertRaises(ValueError,plan,manifest(),a)
    def test_unsupported_nonfinite_rejected(self):
        m=manifest();m['segments'][0]['request']['other']=float('nan');self.assertRaises(ValueError,plan,m,adapter())
    def test_unverified_tags_rejected(self):
        m=manifest();m['segments'][0]['text']='<speak>hello</speak>';self.assertRaises(ValueError,plan,m,adapter())
        m=manifest();m['segments'][0].pop('intent');m['segments'][0]['request']['prompt']='<bad>x</bad>';self.assertRaises(ValueError,plan,m,adapter())
    def test_invalid_capability_range(self):
        a=adapter();a['fields']['speed']['min']='slow';self.assertRaisesRegex(ValueError,'invalid min',plan,manifest(),a)
    def test_unused_invalid_schema_rejected(self):
        for spec in ({'type':'string','enum':'wav'},{'type':'number','enum':[True]},{'type':'string','min':1},{'type':'number','enum':['wrong']}):
            a=adapter();a['fields']['unused']=spec;self.assertRaises(ValueError,plan,manifest(),a)
    def test_unknown_adapter(self):
        a=adapter();a['verified']=False;self.assertRaises(ValueError,plan,manifest(),a)
    def test_nonobject_empty_duplicate(self):
        for x in ([],['x'],[{'id':'a','text':'x'},{'id':'a','text':'y'}]):self.assertRaises(ValueError,plan,{'segments':x},adapter())
    def test_no_network_or_authorization(self):
        x=plan(manifest(),adapter());self.assertEqual(x['network_calls'],0);self.assertFalse(x['execution_authorized'])

class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.d=Path(self.temp.name);self.m=self.d/'manifest.json';self.a=self.d/'adapter.json';self.out=self.d/'out.json';self.m.write_text(json.dumps(manifest()),encoding='utf8');self.a.write_text(json.dumps(adapter()),encoding='utf8')
    def tearDown(self):self.temp.cleanup()
    def call_plan(self,*extra):return subprocess.run([sys.executable,str(ROOT/'plan_adapter.py'),'--manifest',str(self.m),'--adapter',str(self.a),'--output',str(self.out),*extra],capture_output=True,text=True,encoding='utf8',errors='replace',env={**os.environ,'PYTHONUTF8':'1'})
    def test_dry_no_write(self):self.assertEqual(self.call_plan('--dry-run').returncode,0);self.assertFalse(self.out.exists())
    def test_no_overwrite(self):self.out.write_text('KEEP');self.assertNotEqual(self.call_plan().returncode,0);self.assertEqual(self.out.read_text(),'KEEP')
    def test_real_plan(self):self.assertEqual(self.call_plan().returncode,0);self.assertTrue(json.loads(self.out.read_text(encoding='utf8'))['plan_only'])
    def make_wave(self,name,amplitude):
        p=self.d/name
        with wave.open(str(p),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(struct.pack('<h',amplitude)*16000)
        return p
    def run_audit(self,cfg,*more):
        self.m.write_text(json.dumps(cfg),encoding='utf8');return subprocess.run([sys.executable,str(ROOT/'audit_audio.py'),'--manifest',str(self.m),'--output',str(self.out),*more],capture_output=True,text=True,encoding='utf8',errors='replace',env={**os.environ,'PYTHONUTF8':'1'})
    def test_audit_multi_peak_tail(self):
        f=self.make_wave('tone.wav',30000);r=self.run_audit({'items':[{'id':'one','audio':str(f)},{'id':'two','audio':str(f)}],'thresholds':{'true_peak_limit_dbtp':-20,'tail_rms_threshold_dbfs':-35}});self.assertEqual(r.returncode,0,r.stderr);v=json.loads(self.out.read_text(encoding='utf8'));self.assertEqual([x['id'] for x in v['items']],['one','two']);self.assertTrue(v['items'][0]['true_peak_exceeds_limit']);self.assertTrue(v['items'][0]['tail_active_risk_candidate']);self.assertFalse(v['overall_pass'])
    def test_audit_invalid_file_reports(self):
        f=self.d/'invalid';f.write_bytes(b'not audio');r=self.run_audit({'items':[{'id':'x','audio':str(f)}]});self.assertEqual(r.returncode,2);d=json.loads(self.out.read_text(encoding='utf8'));self.assertEqual(d['items'][0]['id'],'x');self.assertIn('ffprobe failed',d['items'][0]['error'])
    def test_audit_dry_and_overwrite(self):
        f=self.make_wave('tone.wav',1);cfg={'items':[{'id':'s','audio':str(f)}]};self.assertEqual(self.run_audit(cfg,'--dry-run').returncode,0);self.assertFalse(self.out.exists());self.out.write_text('KEEP');self.assertNotEqual(self.run_audit(cfg).returncode,0);self.assertEqual(self.out.read_text(),'KEEP')
    def test_audit_invalid_structure(self):
        for cfg in ({'items':[]},{'items':['x']},{'items':[{'id':'a','audio':'missing'},{'id':'a','audio':'missing'}]}):self.assertNotEqual(self.run_audit(cfg).returncode,0)
    def test_dry_missing_media_structural(self):
        r=self.run_audit({'items':[{'id':'a','audio':'missing.wav'}]},'--dry-run');self.assertEqual(r.returncode,0);d=json.loads(r.stdout);self.assertFalse(d['items'][0]['media_exists']);self.assertFalse(d['items'][0]['media_tested']);self.assertFalse(self.out.exists())
    def test_good_bad_good(self):
        good=self.make_wave('good.wav',1000);bad=self.d/'bad.wav';bad.write_bytes(b'broken');r=self.run_audit({'items':[{'id':'a','audio':str(good)},{'id':'b','audio':str(bad)},{'id':'c','audio':str(good)}]});self.assertEqual(r.returncode,2);d=json.loads(self.out.read_text(encoding='utf8'));self.assertEqual(d['status'],'partial');self.assertEqual([x['status'] for x in d['items']],['success','error','success']);self.assertEqual(d['items'][1]['id'],'b');self.assertFalse(d['overall_pass'])
    def test_multiple_failures_and_missing(self):
        bad=self.d/'bad.wav';bad.write_bytes(b'broken');r=self.run_audit({'items':[{'id':'a','audio':str(bad)},{'id':'b','audio':str(self.d/'missing')}]});self.assertEqual(r.returncode,2);d=json.loads(self.out.read_text(encoding='utf8'));self.assertEqual(d['status'],'failed');self.assertEqual([x['id'] for x in d['items']],['a','b'])
    def test_missing_tool_is_item_error(self):
        f=self.make_wave('good.wav',1000);r=self.run_audit({'items':[{'id':'x','audio':str(f)}]},'--ffprobe',str(self.d/'no-such-ffprobe'));self.assertEqual(r.returncode,2);self.assertEqual(json.loads(self.out.read_text(encoding='utf8'))['items'][0]['status'],'error')
    def test_audio_as_output_rejected(self):
        f=self.make_wave('good.wav',1000);self.m.write_text(json.dumps({'items':[{'id':'x','audio':str(f)}]}),encoding='utf8');before=f.read_bytes();r=subprocess.run([sys.executable,str(ROOT/'audit_audio.py'),'--manifest',str(self.m),'--output',str(f)],capture_output=True);self.assertNotEqual(r.returncode,0);self.assertEqual(f.read_bytes(),before)
    def test_silent_audio_is_reported(self):
        f=self.make_wave('silent.wav',0);r=self.run_audit({'items':[{'id':'silent','audio':str(f)}]});self.assertEqual(r.returncode,0,r.stderr);result=json.loads(self.out.read_text(encoding='utf8'));self.assertTrue(result['items'][0]['silent_audio']);self.assertIsNone(result['items'][0]['true_peak_dbtp']);self.assertFalse(result['overall_pass'])
    def test_audit_preserves_asr_for_manual_review(self):
        f=self.make_wave('tone.wav',1000);r=self.run_audit({'items':[{'id':'x','audio':str(f),'expected_text':'hello','asr_text':'bye'}]});self.assertEqual(r.returncode,0,r.stderr);item=json.loads(self.out.read_text(encoding='utf8'))['items'][0];self.assertEqual(item['expected_text'],'hello');self.assertEqual(item['asr_text'],'bye');self.assertEqual(item['asr_differences'],'manual_review_required')
if __name__=='__main__':unittest.main()
