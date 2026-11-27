from types import SimpleNamespace

import httpx
import pytest

from app.config import SearchParams, ReportError
from app.report import create_report, MaterialSearch, build_validated_card
from app.dataset import DemoParams, build_demo_dataset, validate_against_ddl_invariants


@pytest.mark.parametrize('word',[' ', '***'])
def test_one_word_only(word):
    with pytest.raises(ValueError):SearchParams(term=word,date_from='2026-09-07',date_to='2026-12-27')


def test_date_order():
    with pytest.raises(ValueError):SearchParams(term='слово',date_from='2026-12-27',date_to='2026-09-07')


def test_simple_search_has_one_request():
    requests=[]
    def handle(r):
        requests.append(r)
        return httpx.Response(200,json={'hits':{'total':{'relation':'eq','value':1},'hits':[{'_source':{'id':1,'lecture_id':9,'course_id':2}}]}})
    search=MaterialSearch('http://es',client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert search.search('слово')==[{'id':1,'lecture_id':9,'course_id':2}]
    assert len(requests)==1 and requests[0].url.path.endswith('/_search')


@pytest.mark.parametrize('payload',[{'timed_out':True},{'hits':{'total':{'relation':'eq','value':10001},'hits':[]}}])
def test_search_never_returns_partial_ranking(payload):
    search=MaterialSearch('http://es',client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))))
    with pytest.raises(ReportError):search.search('слово')


STUDENT={'id':26,'group_id':1,'record_book':'26Д0026','last_name':'Иванов','first_name':'Иван','patronymic':None,'email':'','phone':'123','enrollment_date':'2023-09-01','status':'active'}


def test_redis_nullable_values_and_stale_card():
    raw={k:'' if v is None else str(v) for k,v in STUDENT.items()}
    assert build_validated_card(raw,'26Д0026',STUDENT)==STUDENT
    raw['phone']=''
    with pytest.raises(ReportError) as e:build_validated_card(raw,'26Д0026',STUDENT)
    assert e.value.status==409


def test_search_accepts_phrase():
    params = SearchParams(term="  реляционная модель  ", date_from="2026-09-07",
                          date_to="2026-12-27")
    assert params.term == "реляционная модель"


def test_data_matches_pr3_and_is_deterministic():
    a=build_demo_dataset(DemoParams());b=build_demo_dataset(DemoParams())
    validate_against_ddl_invariants(a)
    assert a.students==b.students and len(a.students)==104
    assert len(a.attendance)==2912


def test_four_steps_and_redis_output():
    calls=[]
    params=SearchParams(term='слово',date_from='2026-09-07',date_to='2026-12-27')
    def search(word):calls.append('es');return [{'lecture_id':9}]
    def graph(*args):calls.append('neo4j');return {'schedule':[],'members':[]}
    def sql(*args):calls.append('pg');return {'results':[{'student_pg':STUDENT,'attendance_percentage':0,'present_count':0,'expected_count':2}]}
    def cards(*args):calls.append('redis');return {'26Д0026':STUDENT.copy()}
    result=create_report(params,SimpleNamespace(search=search),SimpleNamespace(fetch_selection=graph),SimpleNamespace(report=sql),SimpleNamespace(fetch_validated_cards=cards))
    assert calls==['es','neo4j','pg','redis']
    assert result['results'][0]['student']==STUDENT
    assert set(result)=={'term','period','results'}


@pytest.mark.parametrize('failure',[{'graph_missing_members':[26]},{'incomplete_students':[26]}])
def test_inconsistent_data_fails_before_reading_cards(failure):
    args=(SearchParams(term='слово',date_from='2026-09-07',date_to='2026-12-27'),SimpleNamespace(search=lambda w:[]),SimpleNamespace(fetch_selection=lambda *a:{}),SimpleNamespace(report=lambda *a:failure),None)
    with pytest.raises(ReportError) as e:create_report(*args)
    assert e.value.status==409
