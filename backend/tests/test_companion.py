from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.diagnostics.blackboard import build_blackboard
from app.main import app
from app.models.schemas import DiagnoseRequest
from app.state import workspace
from companion.session import ShellSession

client = TestClient(app)


def connect():
    response = client.post('/api/terminal/connect', json={'shell': 'test-shell', 'cwd': '/robot'})
    assert response.status_code == 200
    return {'X-RoboDoctor-Session': response.json()['token']}


def captured(headers, command, output, code, sequence=1, state='finished'):
    return client.post('/api/terminal/event', headers=headers, json={
        'sequence': sequence, 'command': command, 'output': output, 'exit_code': code,
        'state': state, 'cwd': '/robot', 'environment': {'ROS_DISTRO': 'humble'}})


def test_latest_success_ignores_old_failure_and_never_calls_ai():
    headers = connect()
    captured(headers, 'python broken.py', 'ValueError: invalid value', 1)
    assert client.post('/api/terminal/diagnose?mode=rules').json()['status'] == 'problem'
    captured(headers, 'python robot.py', 'Robot initialized successfully.\nConnected to controller.\nMission started.', 0, 2)
    with patch('app.service.diagnose', side_effect=AssertionError('Healthy runs must not invoke AI')):
        result = client.post('/api/terminal/diagnose').json()
    assert result['status'] == 'healthy'
    assert result['diagnosis']['summary'] == '✓ Everything looks good.'
    assert not result['diagnosis']['commands']
    snapshot = client.get('/api/workspace').json()
    assert snapshot['latest']['status'] == 'healthy'
    assert len(snapshot['history']) == 2
    assert 'token' not in snapshot['terminal']


@pytest.mark.parametrize('output,code,expected', [
    ('ModuleNotFoundError: No module named serial', 1, 'python_module'),
    ('SyntaxError: expected colon', 1, 'python_syntax'),
    ('TypeError: unsupported operand', 1, 'python_runtime'),
    ('NameError: name robot is not defined', 1, 'python_runtime'),
    ('No executable found', 1, 'executable'),
    ('Failed   <<< robot_driver [exited with code 1]', 1, 'build'),
    ('[ERROR] Motor startup failed', 0, 'execution'),
    ('Silent failure', 4, 'execution'),
])
def test_managed_failures(output, code, expected):
    headers = connect()
    assert captured(headers, 'python robot.py', output, code).status_code == 200
    result = client.post('/api/terminal/diagnose?mode=rules').json()
    assert result['status'] == 'problem'
    assert expected in {f['code'] for f in result['findings']}


def test_running_cancelled_empty_and_untrusted_events():
    assert client.post('/api/terminal/diagnose').status_code == 409
    assert captured({}, 'echo hello', 'hello', 0).status_code == 401
    headers = connect()
    assert captured(headers, 'python robot.py', '', None, state='running').status_code == 200
    assert client.post('/api/terminal/diagnose').status_code == 409
    assert captured(headers, 'python robot.py', 'Stopped by user', 130, state='cancelled').status_code == 200
    result = client.post('/api/terminal/diagnose').json()
    assert result['diagnosis']['summary'] == 'Execution stopped.'
    assert result['engine'] == 'observed'
    assert captured(headers, 'old', '', 0).status_code == 409


def test_capture_does_not_execute_command(tmp_path):
    headers = connect()
    target = tmp_path / 'not-created.txt'
    with patch('subprocess.Popen', side_effect=AssertionError('Backend must never start a command')):
        response = captured(headers, f'echo unsafe > {target}', 'plain data', 0)
        assert response.status_code == 200
        assert client.post('/api/terminal/diagnose').status_code == 200
    assert not target.exists()


def test_session_disconnect_and_origin_isolation():
    headers = connect()
    assert client.get('/api/workspace').json()['terminal']['connected']
    assert client.post('/api/terminal/heartbeat', headers=headers).status_code == 200
    assert client.post('/api/terminal/disconnect', headers=headers).status_code == 200
    assert not client.get('/api/workspace').json()['terminal']['connected']
    assert client.get('/api/workspace', headers={'Origin': 'https://untrusted.example'}).status_code == 403


def test_blackboard_bounded_context_and_environment():
    request = DiagnoseRequest(text='ordinary output\n' * 2000 + 'ModuleNotFoundError: No module named serial')
    board = build_blackboard(request, {'exit_code': 1, 'environment': {'ROS_DISTRO': 'humble'}, 'state': 'finished'})
    assert board.language == 'python'
    assert board.ros2['ROS_DISTRO'] == 'humble'
    assert sum(len(source['content']) for source in board.relevant_sources) <= 14000
    assert 'ModuleNotFoundError: No module named serial' in board.important_evidence


def test_ros_detection_classifies_package_traceback():
    board = build_blackboard(DiagnoseRequest(text='PackageNotFoundError: missing_demo'))
    assert board.language == 'ros2'
    assert 'package' in board.error_types


def test_history_bounded_and_no_success_guessing():
    for _ in range(15):
        response = client.post('/api/diagnose', json={'text': 'looks okay', 'mode': 'rules'})
        assert response.json()['status'] == 'insufficient'
    assert len(client.get('/api/workspace').json()['history']) == 12


def test_slow_result_cannot_overwrite_newer_run():
    headers = connect()
    captured(headers, 'one', 'first', 1)
    sequence = workspace.execution['sequence']
    captured(headers, 'two', 'second', 0, 2)
    from app.diagnostics.fallback import fallback
    from app.models.schemas import DiagnoseResponse
    board = build_blackboard(DiagnoseRequest(text='first'))
    result = DiagnoseResponse(diagnosis=fallback([]), findings=[], engine='rules', elapsed_ms=0)
    assert not workspace.remember(result, board, sequence)


def test_real_persistent_shell_success_failure_environment_and_cwd(tmp_path):
    session = ShellSession(tmp_path)
    try:
        assert session.execute('python -c "print(123)"')['exit_code'] == 0
        failure = session.execute('python -c "raise ValueError(\'bad value\')"')
        assert failure['exit_code'] != 0
        assert 'ValueError: bad value' in failure['output']
        env_command = "$env:ROS_DISTRO='humble'" if session.windows else 'export ROS_DISTRO=humble'
        session.execute(env_command)
        result = session.execute('python -c "print(456)"')
        assert result['exit_code'] == 0
        assert result['environment']['ROS_DISTRO'] == 'humble'
        assert Path(result['cwd']).resolve() == tmp_path.resolve()
    finally:
        session.close()
