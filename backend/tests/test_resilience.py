from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_malformed_terminal_control_sequences_are_bounded_and_normalized():
    token = client.post('/api/terminal/connect', json={'shell': 'test', 'cwd': '/workspace'}).json()['token']
    raw = 'normal output\n' * 900 + '\x1b[31mValueError: malformed input\x1b[0m\x00'
    response = client.post('/api/terminal/event', headers={'X-RoboDoctor-Session': token}, json={
        'sequence': 1, 'command': 'python demo.py', 'output': raw, 'exit_code': 1,
        'state': 'finished', 'cwd': '/workspace', 'environment': {}})
    assert response.status_code == 200
    output = client.get('/api/workspace').json()['terminal']['execution']['output']
    assert len(output) <= 12000
    assert '\x00' not in output and '\x1b' not in output
    result = client.post('/api/terminal/diagnose?mode=rules').json()
    assert result['status'] == 'problem'
    assert 'ValueError: malformed input' in result['diagnosis']['evidence']


def test_unstructured_paste_and_empty_terminal_do_not_invent_health():
    assert client.post('/api/terminal/diagnose').status_code == 409
    result = client.post('/api/diagnose', json={'text': '%%% <script>alert(1)</script> ???', 'mode': 'rules'}).json()
    assert result['status'] == 'insufficient'
    assert result['diagnosis']['confidence'] == 'low'


def test_rules_and_healthy_execution_need_no_ollama_connection():
    with patch('app.service.diagnose', side_effect=AssertionError('No local inference needed')):
        response = client.post('/api/diagnose', json={'text': 'SyntaxError: invalid syntax', 'mode': 'rules'})
        assert response.json()['status'] == 'problem'
        assert client.post('/api/examples/healthy_run/diagnose').json()['status'] == 'healthy'
