"""Real asynchronous job lifecycle with disposable progress and mocked provider."""
import asyncio
import json

import pytest

from pth_corpus.assessment import AssessmentError, AssessmentService, normalize_result
from pth_corpus.reading_coach import ReadingCoach, nasal_feedback, nasal_final_evidence
from test_assessment import wav, settings

TARGET = {"position": 1, "text": "民", "pinyin": "mín", "final": "in"}


@pytest.mark.parametrize("final,phones", [
    ("ian", ["x", "i4", "an"]), ("uan", ["ch", "u1", "an"]),
    ("üan", ["y", "v2", "an"]), ("üan", ["y", "u:2", "an"]),
    ("iang", ["j", "i1", "ang"]), ("uang", ["w", "u1", "ang"]),
    ("uen", ["u1", "en"]), ("un", ["u1", "en"]),
    ("ueng", ["u1", "eng"]), ("iong", ["i1", "ong"]),
    ("ian", ["ian4"]), ("in", ["in1"]),
])
def test_medial_and_nasal_components_match_without_inventing_a_mean(final, phones):
    rows=[{"phone":p,"accuracy":5 if i<len(phones)-1 else 94,"tag":0} for i,p in enumerate(phones)]
    evidence=nasal_final_evidence(rows,final)
    assert evidence is not None and evidence["accuracy"]==94
    assert evidence["components"][-1]["phone"]==phones[-1]


@pytest.mark.parametrize("phones", [
    ["i1", "ang"], ["i1", "x", "an"], ["i1", "an", "ian"], ["i1"],
])
def test_mapping_does_not_guess_through_wrong_tails_gaps_or_duplicates(phones):
    assert nasal_final_evidence([{"phone":p,"accuracy":99,"tag":0} for p in phones],"ian") is None


def test_missing_medial_does_not_become_a_complete_final():
    phones=[{"phone":"i4","accuracy":None,"tag":2},{"phone":"an","accuracy":95,"tag":0}]
    assert nasal_final_evidence(phones,"ian") is None

def result(score=40, onset=99):
    return normalize_result({"PronCompletion": 1, "Words": [
        {"Word":"人","MatchTag":0,"PhoneInfos":[{"Phone":"en2","PronAccuracy":99}]},
        {"Word":"民","MatchTag":0,"PronAccuracy":30,"PhoneInfos":[
            {"Phone":"m","PronAccuracy":onset},{"Phone":"in2","PronAccuracy":score}]}]})


def test_only_expected_final_scores_drive_suggestions():
    assert nasal_feedback("人民",[TARGET],result(95,10))[0]["practice"] is False
    row=nasal_feedback("人民",[TARGET],result())[0]
    assert row["practice"] and row["accuracy"]==40 and row["diagnosis"] is None
    assert nasal_feedback("人民",[TARGET],{"status":"ok","words":[{"text":"人民","accuracy":20}]})==[]
    assert nasal_feedback("民"*31,[TARGET],result())==[]


@pytest.mark.parametrize("change",["missing","reorder","duplicate_phone","missing_phone","tag","other_final"])
def test_ambiguous_or_unavailable_evidence_is_not_a_nasal_mistake(change):
    r=result()
    if change=="missing":r["words"].pop(0)
    if change=="reorder":r["words"].reverse()
    if change=="duplicate_phone":r["words"][1]["phones"].append(r["words"][1]["phones"][1])
    if change=="missing_phone":r["words"][1].pop("phones")
    if change=="tag":r["words"][1]["tag"]=3
    if change=="other_final":r["words"][1]["phones"][1]["phone"]="ing2"
    assert nasal_feedback("人民",[TARGET],r)==[]


def test_repeated_characters_keep_context_position():
    r=result();r["words"][0]["text"]="民"
    target={**TARGET,"position":0}
    r["words"][0]["phones"][0]["phone"]="in2"
    hints=nasal_feedback("民民",[target,TARGET],r)
    assert [h["position"] for h in hints]==[0,1]
    assert [h["practice"] for h in hints]==[False,True]


def test_background_return_dedup_restart_and_later_success(tmp_path,monkeypatch):
    async def run():
        service=AssessmentService(tmp_path);monkeypatch.setattr(service,"settings",settings)
        coach=ReadingCoach(service,tmp_path/"isolated",nasal_review_enabled=True)
        unblock=asyncio.Event();calls=[]
        async def provider(*args):
            calls.append(1);await unblock.wait();return result(40 if len(calls)<3 else 95)
        monkeypatch.setattr("pth_corpus.assessment.evaluate",provider)
        def submit(attempt,session="session-one",pass_no=1):
            return coach.submit(attempt_id=attempt,session_id=session,kind="sentence",reference_id="s1",
                                text="人民",targets=[TARGET],audio=wav(),pass_no=pass_no)
        assert submit("attempt-one")["status"]=="pending"
        assert coach.summary("session-one")["pending"]==1
        assert submit("attempt-one")["status"]=="pending" # durable identity
        assert len(coach.tasks)==1
        unblock.set();await asyncio.gather(*coach.tasks)
        assert coach.summary("session-one")["weak"][0]["sessions"]==1
        submit("attempt-two",pass_no=2);await asyncio.gather(*coach.tasks)
        assert coach.weak_items()[0]["sessions"]==1 # two passes are not two independent rounds
        submit("attempt-new","session-two");await asyncio.gather(*coach.tasks)
        assert coach.weak_items()==[] # a later valid successful observation resolves the hint
        assert service.units_used()==3
        restarted=ReadingCoach(service,tmp_path/"isolated")
        assert restarted.summary("session-one")["assessed"]==2
        assert submit("attempt-one")["status"]=="ok"
        assert service.units_used()==3
        assert not list((tmp_path/"isolated").rglob("*.wav"))
    asyncio.run(run())


def test_silence_invalid_identity_and_interrupted_jobs(tmp_path,monkeypatch):
    async def run():
        service=AssessmentService(tmp_path);monkeypatch.setattr(service,"settings",settings)
        coach=ReadingCoach(service,tmp_path/"progress")
        kwargs=dict(attempt_id="attempt-one",session_id="session-one",kind="word",reference_id="w1",text="人民",targets=[TARGET],pass_no=1)
        with pytest.raises(AssessmentError):coach.submit(**kwargs,audio=wav(True))
        assert coach.records()==[] and service.units_used()==0
        async def provider(*args):await asyncio.Event().wait()
        monkeypatch.setattr("pth_corpus.assessment.evaluate",provider)
        coach.submit(**kwargs,audio=wav())
        await asyncio.sleep(0)
        await coach.shutdown()
        assert coach.summary("session-one")["unavailable"]==1
        assert coach.summary("session-one")["weak"]==[]
        with pytest.raises(AssessmentError):coach.submit(**{**kwargs,"session_id":"session-two"},audio=wav())
        assert not list((tmp_path/"progress").rglob("*.wav"))
    asyncio.run(run())


def test_startup_marks_pending_without_resending(tmp_path):
    service=AssessmentService(tmp_path);coach=ReadingCoach(service,tmp_path)
    coach.save({"attempt_id":"attempt-one","session_id":"session-one","created":1,"status":"pending","feedback":[]})
    restarted=ReadingCoach(service,tmp_path)
    assert restarted.records()[0]["status"]=="interrupted"
    assert restarted.summary("session-one")["pending"]==0
    assert service.units_used()==0


def test_production_gate_never_turns_unvalidated_scores_into_weak_items(tmp_path):
    coach=ReadingCoach(AssessmentService(tmp_path),tmp_path)
    coach.save({"attempt_id":"attempt-one","session_id":"session-one","kind":"sentence",
                "reference_id":"s1","text":"人民","created":1,"status":"ok",
                "feedback":[{**TARGET,"accuracy":20,"practice":True}]})
    summary=coach.summary("session-one")
    assert summary["target_observations"]==1 and summary["weak"]==[]
    assert summary["diagnostics_ready"] is False


def test_api_accepts_without_waiting_persists_and_validates_reference(tmp_path,monkeypatch):
    import time
    from test_prototype_app import _make_fixture, _build_item
    _,client,_=_make_fixture(tmp_path,items=[_build_item('t1-00001',['r','m'],word='人民',finals=['en','in'])])
    monkeypatch.setattr(client.app.state.assessment,'settings',settings)
    async def provider(*args):await asyncio.sleep(.15);return result()
    monkeypatch.setattr('pth_corpus.assessment.evaluate',provider)
    params=dict(attempt_id='attempt-one',session_id='session-one',pass_no=1)
    with client:
        url='/api/reading/attempts/word/t1-00001'
        response=client.post(url,params=params,content=wav())
        assert response.status_code==202 and response.json()['status']=='pending'
        assert client.get('/api/reading/session/session-one').json()['pending']==1
        assert client.post(url,params=params,content=wav()).json()['status'] in ('pending','ok')
        for _ in range(100):
            summary=client.get('/api/reading/session/session-one').json()
            if not summary['pending']:break
            time.sleep(.01)
        assert summary['assessed']==1 and summary['target_observations']==2
        assert not summary['weak'] and not summary['diagnostics_ready']
        review=client.get('/api/reading/review').json()
        assert review['sessions'][0]['assessed']==1 and review['weak']==[]
        assert client.app.state.assessment.units_used()==1
        assert client.post('/api/sentence/session',json={'count':10,'review':True}).status_code==409
        assert client.post('/api/reading/attempts/word/unknown',params=params,content=wav()).status_code==404
        assert client.get('/api/reading/session/bad').status_code==400
        assert client.post(url,params={**params,'attempt_id':'bad'},content=wav()).status_code==400
        silent=client.post(url,params={**params,'attempt_id':'silent-one'},content=wav(True)).json()
        assert silent['status']=='no_speech'
        assert client.get('/api/reading/session/session-one').json()['submitted']==1
    files=list(client.app.state.runtime.prototype_dir.rglob('reading/attempts/*.json'))
    assert len(files)==1 and files[0].stat().st_mode & 0o777==0o600


def test_incomplete_content_resolves_when_a_later_reading_is_complete(tmp_path):
    coach=ReadingCoach(AssessmentService(tmp_path),tmp_path)
    base={"session_id":"session-one","kind":"word","reference_id":"w1","text":"人民","status":"ok","feedback":[]}
    coach.save({**base,"attempt_id":"attempt-one","created":1,"completion":40})
    assert coach.summary('session-one')['retry_items']==[{'reference_id':'w1','kind':'word','text':'人民'}]
    coach.save({**base,"session_id":"session-two","attempt_id":"attempt-two","created":2,"completion":100})
    assert coach.retry_items()==[]
