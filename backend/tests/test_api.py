import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai.local import LocalAIError
from app.diagnostics.fallback import fallback
from app.main import app

client = TestClient(app)
MISSING = '$ ros2 topic info /cmd_vel\nPublisher count: 0\nSubscription count: 1'


def test_rules_diagnosis():
    response = client.post('/api/diagnose', json={'text': MISSING, 'mode': 'rules'})
    assert response.status_code == 200
    data = response.json()
    assert data['engine'] == 'rules'
    assert data['findings'][0]['code'] == 'cmd_vel'
    assert 'Publisher count: 0' in data['diagnosis']['evidence']
    assert data['diagnosis']['commands']


def test_ai_success_path():
    async def fake_ai(request, findings, blackboard):
        return fallback(findings)
    with patch('app.service.diagnose', fake_ai):
        data = client.post('/api/diagnose', json={'text': MISSING}).json()
    assert data['engine'] == 'local-ai'
    assert data['model']
    assert data['notice'] is None


def test_ai_unavailable_fallback():
    async def broken_ai(request, findings, blackboard):
        raise LocalAIError('Cannot reach Ollama.')
    with patch('app.service.diagnose', broken_ai):
        response = client.post('/api/diagnose', json={'text': MISSING})
    assert response.status_code == 200
    assert response.json()['engine'] == 'rules'
    assert 'Cannot reach Ollama' in response.json()['notice']


def test_insufficient_evidence():
    data = client.post('/api/diagnose', json={'text': 'My robot is broken', 'mode': 'rules'}).json()
    assert data['diagnosis']['summary'] == 'Insufficient evidence.'
    assert data['diagnosis']['confidence'] == 'low'


def test_invalid_requests():
    for body in [{}, {'text': 'x' * 60001}, {'files': [{'name': 'x.exe', 'content': 'abc'}]},
                 {'files': [{'name': 'x.txt', 'content': '\x00'}]},
                 {'files': [{'name': 'x.log', 'content': 'x' * 32001}]},
                 {'text': 'x', 'mode': 'cloud'}, {'text': 'x', 'unexpected': True}]:
        assert client.post('/api/diagnose', json=body).status_code == 422
    assert client.post('/api/diagnose', content='x' * 400001).status_code == 413


def test_upload_filename_sanitization():
    response = client.post('/api/diagnose', json={
        'files': [{'name': '../../robot.log', 'content': 'No executable found'}], 'mode': 'rules'})
    assert response.status_code == 200
    assert response.json()['findings'][0]['source'] == 'robot.log'


def test_all_examples():
    response = client.get('/api/examples')
    assert response.status_code == 200
    examples = response.json()
    assert len(examples) == 11
    for example in examples:
        response = client.post(f"/api/examples/{example['id']}/diagnose?mode=rules")
        assert response.status_code == 200
        if example['id'] == 'healthy_run':
            assert response.json()['status'] == 'healthy'
        else:
            assert response.json()['findings'], example['id']


def test_health_without_ollama():
    async def offline():
        return {'available': False, 'model': 'test', 'message': 'offline'}
    with patch('app.main.model_status', offline):
        response = client.get('/api/health')
    assert response.json()['status'] == 'ok'
    assert response.json()['ai']['available'] is False
