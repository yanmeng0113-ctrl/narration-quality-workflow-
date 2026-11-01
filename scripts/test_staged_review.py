import copy
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import wave
from plan_adapter import plan
from staged_review import decide


class StagedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        with wave.open(str(self.base / 'final.bin'), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(b'\0' * 32000)
        self.sha = hashlib.sha256((self.base / 'final.bin').read_bytes()).hexdigest()
        self.item = {'id': 'stable-01', 'media': 'final.bin', 'source_sha256': self.sha,
                     'duration_seconds': 2, 'has_narration': True, 'has_video': False,
                     'has_subtitles': True, 'expected_text': 'Hello world', 'checks': {},
                     'pronunciation_notes': [], 'risks': []}
        for name in ['decode', 'visuals', 'subtitle_sync', 'asr_content', 'pronunciation_risk_scan', 'boundaries_pauses', 'tail', 'loudness_peak']:
            self.item['checks'][name] = {'source_sha256': self.sha, 'tool': 'test-only synthetic evidence', 'coverage': [[0, 2]], 'status': 'passed'}
        self.item['checks']['asr_content'].update({'asr_source': {'tool': 'test', 'model': 'synthetic', 'blind': True}, 'text_sha256': hashlib.sha256(b'Hello world').hexdigest()})
        for name, check in self.item['checks'].items():
            record = dict(check, check_name=name, tool_version='test-1', method='synthetic test attestation', details='not real content review')
            if name == 'pronunciation_risk_scan':
                record.update(text_sha256=hashlib.sha256(b'Hello world').hexdigest(), pronunciation_risks=[])
            raw = json.dumps(record).encode()
            (self.base / (name+'.json')).write_bytes(raw)
            check['evidence_ref'] = {'path':name+'.json', 'sha256':hashlib.sha256(raw).hexdigest()}


    def save_record(self, target, record, name):
        raw=json.dumps(record).encode();(self.base/name).write_bytes(raw)
        target['evidence_ref']={'path':name,'sha256':hashlib.sha256(raw).hexdigest()}

    def save_scan(self, risks):
        check=self.item['checks']['pronunciation_risk_scan']
        record=json.loads((self.base/'pronunciation_risk_scan.json').read_text())
        record['pronunciation_risks']=risks
        self.save_record(check,record,'pronunciation_risk_scan.json')

    def test_changed_text_invalidates_asr_artifact(self):
        self.item['expected_text']='Completely different script'
        self.item['checks']['asr_content']['text_sha256']=hashlib.sha256(self.item['expected_text'].encode()).hexdigest()
        self.assertEqual(self.decision()['stage'],'blocked')

    def test_changed_asr_source_invalidates_artifact(self):
        self.item['checks']['asr_content']['asr_source']['model']='different model'
        self.assertEqual(self.decision()['stage'],'blocked')

    def test_bare_resolution_cannot_resolve(self):
        r=self.resolution();del r['evidence_ref']
        self.assertEqual(self.decision()['stage'],'review_required')

    def test_local_phonetic_evidence_resolves_local_risk(self):
        r=self.resolution('local_phonetic_analysis')
        record=json.loads((self.base/'resolution.json').read_text())
        record.update(audio_analyzed=True,acoustic_observations='synthetic local acoustic analysis',phoneme_findings='synthetic phoneme observation')
        self.save_record(r,record,'resolution.json')
        self.assertEqual(self.decision()['stage'],'local_pass')

    def test_positive_full_listening_record(self):
        self.item['heard_review']='passed'
        listening={'source_sha256':self.sha,'coverage':[[0,2]],'capability':'human_listening','reviewer':'test','evidence':'synthetic full record','status':'passed'}
        record=dict(listening,check_name='listening',tool='test',tool_version='1',method='synthetic',details='synthetic')
        self.save_record(listening,record,'listening.json');self.item['listening_evidence']=listening
        result=self.decision();self.assertEqual(result['stage'],'local_pass');self.assertEqual(result['heard_review'],'passed')

    def test_poetry_localized_risk_not_whole_track(self):
        self.item['content_type']='poetry'
        self.save_scan([{'id':'word-01','kind':'pronunciation','interval':[0.5,1], 'text':'重','reason':'polyphone context'}])
        result=self.decision();self.assertEqual(result['stage'],'review_required')
        self.assertEqual(result['unresolved_risks'][0]['interval'],[0.5,1])

    def test_resolution_artifact_fields_bound(self):
        r=self.resolution()
        original=json.loads((self.base/'resolution.json').read_text())
        for field,value in [('risk_id','other'),('capability','transcription'),('interval',[0,1]),('status','failed'),('text_sha256','0'*64)]:
            record=dict(original);record[field]=value
            self.save_record(r,record,'resolution.json')
            self.assertEqual(self.decision()['stage'],'review_required')

    def test_all_nonpassing_listening_statuses_rejected(self):
        self.item['heard_review']='passed'
        for status in ('failed','skipped','unknown',False,None):
            listening={'source_sha256':self.sha,'coverage':[[0,2]],'capability':'human_listening','reviewer':'test','evidence':'fixture','status':status}
            record=dict(listening,check_name='listening',tool='test',tool_version='1',method='fixture',details='fixture')
            self.save_record(listening,record,'listening.json');self.item['listening_evidence']=listening
            result=self.decision()
            self.assertEqual(result['stage'],'blocked');self.assertNotEqual(result['heard_review'],'passed')

    def test_nonpassing_check_and_resolution_statuses_rejected(self):
        for status in ('failed','skipped','unknown',False,None):
            self.item['checks']['tail']['status']=status
            self.assertEqual(self.decision()['stage'],'blocked')
        self.item['checks']['tail']['status']='passed'
        r=self.resolution()
        for status in ('failed','skipped','unknown',False,None):
            r['status']=status
            self.assertEqual(self.decision()['stage'],'review_required')

    def test_huge_duration_partial_batch(self):
        bad=copy.deepcopy(self.item);bad.update(id='huge',duration_seconds=10**400)
        good2=copy.deepcopy(self.item);good2['id']='good2'
        src=self.base/'huge.json';out=self.base/'huge-out.json'
        src.write_text(json.dumps({'items':[self.item,bad,good2]}))
        p=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('staged_review.py')),'--manifest',str(src),'--output',str(out)],capture_output=True,text=True)
        self.assertEqual(p.returncode,2);self.assertNotIn('Traceback',p.stderr)
        self.assertEqual([r['stage'] for r in json.loads(out.read_text())['items']],['local_pass','blocked','local_pass'])

    def test_huge_duration_rejected(self):
        self.item['duration_seconds']=10**400
        with self.assertRaises(ValueError):self.decision()

    def test_nested_access_token_not_echoed(self):
        self.item['checks']['asr_content']['asr_source']['access_token']='DUMMY-not-a-real-key'
        with self.assertRaises(ValueError) as caught:self.decision()
        self.assertNotIn('DUMMY',str(caught.exception))

    def test_asr_output_allowlist(self):
        self.item['checks']['asr_content']['asr_source']['harmless_extra']='not copied'
        result=self.decision()
        self.assertNotIn('harmless_extra',result['asr_source'])

    def decision(self):
        return decide(self.item, self.base)

    def test_actual_duration_rejects_short_claim(self):
        self.item['duration_seconds'] = 0.1
        self.item['checks']['decode']['coverage'] = [[0,0.1]]
        with self.assertRaises(ValueError): self.decision()

    def test_external_check_needs_artifact(self):
        del self.item['checks']['tail']['evidence_ref']
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_minimal_human_listening_not_accepted(self):
        self.item['heard_review'] = 'passed'
        self.item['listening_evidence'] = {'source_sha256':self.sha,'coverage':[[0,2]],'capability':'human_listening'}
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_malformed_media_partial_batch(self):
        bad=copy.deepcopy(self.item);bad.update(id='bad',media=123)
        good2=copy.deepcopy(self.item);good2['id']='good2'
        src=self.base/'batch.json';out=self.base/'out.json'
        src.write_text(json.dumps({'items':[self.item,bad,good2]}))
        cmd=[sys.executable,str(pathlib.Path(__file__).with_name('staged_review.py')),'--manifest',str(src),'--output',str(out)]
        self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,2)
        self.assertEqual([r['stage'] for r in json.loads(out.read_text())['items']],['local_pass','blocked','local_pass'])

    def test_complete_local_distinct_from_listening(self):
        r = self.decision()
        self.assertEqual(r['stage'], 'local_pass')
        self.assertEqual(r['heard_review'], 'not_performed')
        self.assertFalse(r['overall_pass'])

    def test_missing_coverage(self):
        self.item['checks']['tail']['coverage'] = [[0, 1]]
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_wrong_source_hash(self):
        self.item['source_sha256'] = '0' * 64
        with self.assertRaises(ValueError): self.decision()

    def test_old_check_hash(self):
        self.item['checks']['tail']['source_sha256'] = '0' * 64
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_invalid_timing(self):
        for value in ([[0, 3]], [[-1, 2]], [[1, 0]], [[0, float('nan')]]):
            self.item['checks']['tail']['coverage'] = value
            with self.assertRaises(ValueError): self.decision()

    def test_malformed_asr_check(self):
        self.item['checks']['asr_content'] = 'bad'
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_asr_tool_model_must_be_text(self):
        for name in ('tool', 'model'):
            original = self.item['checks']['asr_content']['asr_source'][name]
            for bad in (123, {'name':'not text'}):
                self.item['checks']['asr_content']['asr_source'][name] = bad
                with self.assertRaises(ValueError): self.decision()
            self.item['checks']['asr_content']['asr_source'][name] = original

    def test_missing_asr_source(self):
        del self.item['checks']['asr_content']['asr_source']
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_non_narrated_video(self):
        self.item.update(has_narration=False, has_subtitles=False, has_video=True)
        video = self.base / 'silent.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=16x16:d=2:r=1','-c:v','mpeg4',str(video)],check=True)
        self.item['media'] = 'silent.mp4'
        self.item['source_sha256'] = hashlib.sha256(video.read_bytes()).hexdigest()
        for name,check in self.item['checks'].items():
            check['source_sha256'] = self.item['source_sha256']
            record = dict(check, check_name=name, tool_version='test-1', method='synthetic', details='synthetic video')
            raw=json.dumps(record).encode();(self.base/(name+'.json')).write_bytes(raw)
            check['evidence_ref']={'path':name+'.json','sha256':hashlib.sha256(raw).hexdigest()}
        self.item['checks'] = {k:v for k,v in self.item['checks'].items() if k in ('decode', 'visuals')}
        self.assertEqual(self.decision()['stage'], 'local_pass')

    def test_no_evidence_no_pass(self):
        self.item['checks'] = {}
        self.assertEqual(self.decision()['stage'], 'blocked')

    def test_pronunciation_and_poetry(self):
        self.item['pronunciation_notes'] = ['重: expected chong']
        self.assertEqual(self.decision()['stage'], 'blocked')
        self.assertEqual(self.decision()['unresolved_risks'], [])
        self.item['pronunciation_notes'] = []
        self.item['content_type'] = 'poetry'
        self.assertEqual(self.decision()['stage'], 'local_pass')
        self.assertEqual(self.decision()['unresolved_risks'], [])

    def resolution(self, capability='human_listening'):
        self.item['pronunciation_notes'] = ['重: chong']
        self.item['resolutions'] = [{'risk_id':'pronunciation', 'source_sha256':self.sha,
            'interval':[0,2], 'capability':capability, 'reviewer':'test-reviewer',
            'evidence':'synthetic fixture; not an actual listening result', 'status':'resolved'}]
        risk={'id':'pronunciation','kind':'pronunciation','interval':[0.5,1], 'text':'重','reason':'context-dependent reading', 'note':'重: chong'}
        self.save_scan([risk])
        result=self.item['resolutions'][0]
        proof=dict(result,check_name='risk_resolution',tool='test',tool_version='1',method='synthetic',details='synthetic',coverage=[result['interval']],text_sha256=hashlib.sha256(b'Hello world').hexdigest())
        self.save_record(result,proof,'resolution.json')
        return result

    def test_asr_cannot_resolve_pronunciation(self):
        self.resolution('transcription')
        self.assertEqual(self.decision()['stage'], 'review_required')

    def test_old_resolution_not_reused(self):
        self.resolution()['source_sha256'] = '0'*64
        self.assertEqual(self.decision()['stage'], 'review_required')

    def test_explicit_listening_resolution(self):
        self.resolution()
        self.assertEqual(self.decision()['stage'], 'local_pass')

    def test_string_verification_rejected(self):
        r = self.resolution('audio_understanding')
        r['adapter'] = {'verified':True, 'capability':'audio_understanding', 'official_docs_url':'https://example.invalid', 'sample_verified':'no'}
        self.assertEqual(self.decision()['stage'], 'review_required')

    def test_malformed_risk(self):
        self.item['risks'] = ['malformed']
        with self.assertRaises(ValueError): self.decision()

    def test_unverified_cloud_not_accepted(self):
        self.resolution('audio_understanding')
        self.assertEqual(self.decision()['stage'], 'review_required')

    def test_cloud_out_of_bounds(self):
        self.resolution('audio_understanding')['interval'] = [0, 200]
        with self.assertRaises(ValueError): self.decision()

    def test_false_full_listening_claim(self):
        self.item['heard_review'] = 'passed'
        self.assertEqual(self.decision()['stage'], 'blocked')
        self.item['heard_review'] = 'local_pass'
        with self.assertRaises(ValueError): self.decision()

    def test_cli_partial_and_no_overwrite(self):
        bad = copy.deepcopy(self.item); bad['id']='bad'; bad['source_sha256']='0'*64
        good2 = copy.deepcopy(self.item); good2['id']='good2'
        manifest=self.base/'manifest.json'; out=self.base/'report.json'
        manifest.write_text(json.dumps({'items':[self.item,bad,good2]}))
        cmd=[sys.executable,str(pathlib.Path(__file__).with_name('staged_review.py')),'--manifest',str(manifest),'--output',str(out)]
        p=subprocess.run(cmd,capture_output=True); self.assertEqual(p.returncode,2)
        self.assertEqual([r['stage'] for r in json.loads(out.read_text())['items']],['local_pass','blocked','local_pass'])
        before=out.read_bytes(); self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,1)
        self.assertEqual(before,out.read_bytes())


class PlannerRegressions(unittest.TestCase):
    def test_credentials_and_english(self):
        adapter={'name':'offline','verified':True,'fields':{}}
        for assignment in ('api_key: DUMMYabcdefghijklmnop', 'token=DUMMYabcdefghijklmnop', 'password: "DUMMYabcdefghijklmnop"'):
            with self.assertRaises(ValueError) as caught:
                plan({'segments':[{'id':'s','text':assignment}]},adapter)
            self.assertNotIn('DUMMY',str(caught.exception))
        r=plan({'segments':[{'id':'s','text':'The secret of good narration is clear speech.', 'pronunciation_notes':['重: chong'], 'content_type':'poetry'}]},adapter)
        self.assertEqual(r['segments'][0]['pronunciation_notes'], ['重: chong'])
        self.assertTrue(r['segments'][0]['pronunciation_review_required'])


if __name__=='__main__': unittest.main()
