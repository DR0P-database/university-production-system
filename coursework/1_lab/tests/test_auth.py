import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import create_client_assertion, issue_user_token, verify_user_token, verify_service_token, issue_service_token, ReplayStore
from app.config import ReportError
from app.gateway import create_app


def client(settings):
    return TestClient(create_app(settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'results':[]})),base_url='http://report')))


def test_login_and_only_required_swagger_endpoints(settings, passwords):
    c=client(settings)
    r=c.post('/auth/token',data={'username':'admin','password':passwords['admin']})
    assert r.status_code==200
    assert r.headers['Cache-Control']=='no-store'
    assert verify_user_token(r.json()['access_token'],settings.user_public_key_file.read_text())['sub']=='admin'
    spec=c.get('/openapi.json').json()['paths']
    assert set(spec) == {
        '/auth/token',
        '/api/v1/reports/attendance',
        '/api/v1/reports/classroom-capacity',
        '/api/v1/reports/group-lecture-hours',
    }
    assert {x['name'] for x in spec['/api/v1/reports/attendance']['get']['parameters']}=={'term','date_from','date_to'}


def test_wrong_password_and_missing_token(settings):
    c=client(settings)
    assert c.post('/auth/token',data={'username':'admin','password':'bad'}).status_code==401
    assert c.get('/api/v1/reports/attendance',params={'term':'слово','date_from':'2026-09-07','date_to':'2026-12-27'}).status_code==401


def test_private_key_exchange_and_replay(settings,keys):
    c=client(settings)
    assertion=create_client_assertion('gateway',(keys/'gateway_client_private.pem').read_text())
    form={'grant_type':'client_credentials','client_id':'gateway','client_assertion_type':'urn:ietf:params:oauth:client-assertion-type:jwt-bearer','client_assertion':assertion,'audience':'report-service','scope':'lab1:read'}
    response=c.post('/auth/service-token',data=form);assert response.status_code==200
    verify_service_token(response.json()['access_token'],settings.service_issuer_public_key_file.read_text(),'report-service','lab1:read',['gateway'])
    assert c.post('/auth/service-token',data=form).status_code==401
    # Replay survives another app/SQLite connection.
    assert client(settings).post('/auth/service-token',data=form).status_code==401


def test_forbidden_service_scope(settings,keys):
    c=client(settings)
    form={'grant_type':'client_credentials','client_id':'gateway','client_assertion_type':'urn:ietf:params:oauth:client-assertion-type:jwt-bearer','client_assertion':create_client_assertion('gateway',(keys/'gateway_client_private.pem').read_text()),'audience':'gateway-internal','scope':'dataset:state:update'}
    assert c.post('/auth/service-token',data=form).status_code==403


@pytest.mark.parametrize('change',[{'aud':'wrong'},{'token_use':'service'},{'exp':int(time.time())-100},{'scope':[]},{'sub':7}])
def test_bad_user_claims_rejected(settings,change):
    token=issue_user_token('admin',['lab1:read'],settings.user_issuer_private_key_file.read_text())
    claims=jwt.decode(token,options={'verify_signature':False});claims.update(change)
    bad=jwt.encode(claims,settings.user_issuer_private_key_file.read_text(),algorithm='RS256')
    with pytest.raises(ReportError):verify_user_token(bad,settings.user_public_key_file.read_text())


def test_user_token_cannot_be_service(settings):
    token=issue_user_token('admin',['lab1:read'],settings.user_issuer_private_key_file.read_text())
    with pytest.raises(ReportError):verify_service_token(token,settings.service_issuer_public_key_file.read_text(),'report-service','lab1:read',['gateway'])
