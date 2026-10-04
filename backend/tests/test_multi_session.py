import asyncio
from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.state import workspace
from app.diagnostics.investigation import approved, collect, investigate, MAX_ROUNDS
from app.diagnostics.fallback import fallback
from app.diagnostics.blackboard import build_blackboard
from app.models.schemas import DiagnoseRequest, DiagnoseResponse
client=TestClient(app)
def connect():
    data=client.post('/api/terminal/connect',json={'shell':'test','cwd':'.'}).json()
    return data,{'X-RoboDoctor-Session':data['token']}
def emit(headers,command='python robot.py',output='ModuleNotFoundError: No module named nonexistent_package',code=1,seq=1,state='finished'):
    return client.post('/api/terminal/event',headers=headers,json={'sequence':seq,'command':command,'output':output,'exit_code':code,'state':state,'cwd':'.','environment':{}})
def snapshot(): return client.get('/api/workspace').json()
def test_three_sessions_isolation_and_no_automatic_inference():
    sessions=[connect() for _ in range(3)]
    assert len({s[0]['session_id'] for s in sessions})==3
    with patch('app.service.diagnose',side_effect=AssertionError('Detection must not infer')):
        emit(sessions[0][1],output='ok',code=0)
        emit(sessions[1][1],output='',code=None,state='running')
        emit(sessions[2][1])
    state=snapshot()
    assert [s['execution']['state'] for s in state['sessions']]==['finished','running','finished']
    assert state['issues'][0]['session_id']==sessions[2][0]['session_id']
    assert state['emotion']=='worried'
    assert all('token' not in s for s in state['sessions'])
def test_multiple_issues_only_selected_one_is_diagnosed_and_cached():
    a,ha=connect();b,hb=connect();emit(ha,output='No executable found',command='ros2 run turtlesim nonexistent_node');emit(hb)
    before=snapshot(); assert before['issue_count']==2
    issue=next(i for i in before['issues'] if i['session_id']==b['session_id'])
    result=client.post(f"/api/issues/{issue['id']}/open?mode=rules").json()
    assert result['session_id']==b['session_id'] and result['execution_sequence']==1
    assert 'nonexistent_package' in '\n'.join(result['diagnosis']['evidence'])
    state=snapshot(); assert state['issues'][0]['status']=='UNOPENED'; assert state['issues'][1]['status']=='DIAGNOSED'
    assert state['focus_request']['session_id']==b['session_id']
    with patch('app.service.analyze_evidence',side_effect=AssertionError('Already diagnosed')):
        assert client.post(f"/api/issues/{issue['id']}/open").status_code==200
    assert len(snapshot()['history'])==1

def test_successful_rerun_resolves_only_its_session_and_command():
    a,ha=connect();b,hb=connect();emit(ha);emit(hb)
    emit(ha,output='ok',code=0,seq=2)
    assert snapshot()['issue_count']==1 and snapshot()['issues'][0]['session_id']==b['session_id']
    emit(hb,output='ok',code=0,seq=2)
    assert snapshot()['issue_count']==0 and snapshot()['emotion']=='healthy'
    assert all(i['status']=='RESOLVED' for i in workspace.issues.values())

def test_same_sequence_in_different_session_does_not_overwrite():
    a,ha=connect();b,hb=connect();emit(ha);emit(hb)
    request=DiagnoseRequest(text='ModuleNotFoundError: No module named a')
    board=build_blackboard(request)
    response=DiagnoseResponse(diagnosis=fallback(board.patterns),findings=board.patterns,engine='rules',elapsed_ms=0)
    assert workspace.remember(response,board,1,a['session_id'])
    assert snapshot()['latest'] is None
    emit(ha,seq=2,output='ok',code=0)
    assert not workspace.remember(response,board,1,a['session_id'])

def test_slow_example_is_history_only_after_real_execution():
    _,headers=connect();revision=workspace.revision
    emit(headers,output='ok',code=0)
    board=build_blackboard(DiagnoseRequest(text="Package 'fake_robot' not found"))
    result=DiagnoseResponse(diagnosis=fallback(board.patterns),findings=board.patterns,engine='rules',elapsed_ms=0)
    workspace.remember(result,board,expected_revision=revision)
    assert snapshot()['latest']['status']=='healthy'
    assert 'fake_robot' in str(snapshot()['history'])

@pytest.mark.parametrize('command',['rm -rf /','sudo ls','pip install foo','git checkout main','git reset --hard','git clean -f','ros2 topic pub /cmd_vel X','python -c "print(1)"','ls > x','pwd; rm x','which ../x','git status --porcelain=foo','ros2 pkg prefix --help','git log -n 999','ls\nshutdown'])
def test_dangerous_commands_rejected(command):
    with pytest.raises(ValueError): approved(command)
@pytest.mark.parametrize('command',['pwd','ls','which python','python --version','python3 --version','pip list','pip show numpy','ros2 pkg list','ros2 pkg prefix turtlesim','ros2 node list','ros2 topic list','ros2 service list','ros2 action list','ros2 doctor','ros2 interface show std_msgs/msg/String','git status','git branch','git log -n 3'])
def test_allowlist(command): assert approved(command)

def test_real_read_only_probe(tmp_path):
    (tmp_path/'evidence.txt').write_text('unchanged')
    assert collect('pwd',str(tmp_path),{})['output']==str(tmp_path.resolve())
    assert 'evidence.txt' in collect('ls',str(tmp_path),{})['output']
    assert collect('python --version',str(tmp_path),{})['exit_code']==0
    assert (tmp_path/'evidence.txt').read_text()=='unchanged'

def test_bounded_investigation_and_rejection():
    data,h=connect();emit(h);issue=snapshot()['issues'][0];execution=snapshot()['sessions'][0]['execution']
    with patch('app.diagnostics.investigation.plan',AsyncMock(side_effect=['pwd','ls','python --version','git status'])) as planner, patch('app.diagnostics.investigation.collect',return_value={'command':'pwd','output':'evidence','exit_code':0}) as runner:
        asyncio.run(investigate(execution,issue['id']))
    assert planner.call_count==MAX_ROUNDS and runner.call_count==MAX_ROUNDS
    with patch('app.diagnostics.investigation.plan',AsyncMock(return_value='rm anything')),patch('app.diagnostics.investigation.collect') as runner:
        asyncio.run(investigate(execution,issue['id']))
    runner.assert_not_called(); assert snapshot()['sessions'][0]['diagnostic_log'][0]['rejected']

def test_automatic_open_starts_investigation_and_associates_evidence():
    data,h=connect();emit(h);issue=snapshot()['issues'][0]
    with patch('app.diagnostics.investigation.plan',AsyncMock(return_value='pwd')),patch('app.service.diagnose',AsyncMock(side_effect=lambda r,f,b:fallback(f))) as model:
        result=client.post(f"/api/issues/{issue['id']}/open").json()
    assert model.call_count==1 and result['issue_id']==issue['id']
    assert snapshot()['sessions'][0]['diagnostic_log'][0]['command']=='pwd'

def test_zero_exit_error_and_sleeping_state():
    assert snapshot()['emotion']=='sleeping'
    _,h=connect();emit(h,output='[ERROR] controller died',code=0)
    assert snapshot()['issue_count']==1

def test_new_execution_during_investigation_never_commits():
    data,h=connect();emit(h);issue=snapshot()['issues'][0]
    async def model(request,findings,board):
        emit(h,output='success',code=0,seq=2)
        return fallback(findings)
    with patch('app.diagnostics.investigation.plan',AsyncMock(return_value='')),patch('app.service.diagnose',model):
        result=client.post(f"/api/issues/{issue['id']}/open")
    assert result.status_code==409 and snapshot()['latest']['status']=='healthy'
    assert snapshot()['issue_count']==0

def test_silent_whitespace_command_is_healthy():
    _,headers=connect()
    assert emit(headers,command='set environment',output='\n',code=0).status_code==200
    assert snapshot()['latest']['status']=='healthy' and snapshot()['issue_count']==0

def test_missing_ollama_open_falls_back_without_probes():
    from app.ai.local import LocalAIError
    import httpx
    _,headers=connect();emit(headers);issue=snapshot()['issues'][0]
    with patch('app.diagnostics.investigation.plan',AsyncMock(side_effect=httpx.ConnectError('Offline'))),patch('app.diagnostics.investigation.collect') as runner,patch('app.service.diagnose',AsyncMock(side_effect=LocalAIError('Cannot reach Ollama'))):
        result=client.post(f"/api/issues/{issue['id']}/open").json()
    assert result['engine']=='rules' and 'Cannot reach Ollama' in result['notice']
    runner.assert_not_called()

def test_low_confidence_emotion_is_unresolved():
    _,h=connect();emit(h);issue=snapshot()['issues'][0]
    async def low(request,findings,board):
        result=fallback(findings);result.confidence='low';return result
    with patch('app.diagnostics.investigation.plan',AsyncMock(return_value='')),patch('app.service.diagnose',low):
        assert client.post(f"/api/issues/{issue['id']}/open").status_code==200
    assert snapshot()['emotion']=='unresolved' and snapshot()['issues'][0]['status']=='UNRESOLVED'

def test_real_stream_capture_is_separate(tmp_path):
    from companion.session import ShellSession
    session=ShellSession(tmp_path)
    try:
        result=session.execute('python -c "import sys; print(123); print(456, file=sys.stderr)"')
        assert result['exit_code']==0
        assert '123' in result['stdout'] and '456' not in result['stdout']
        assert '456' in result['stderr'] and '123' not in result['stderr']
        assert '123' in result['output'] and '456' in result['output']
    finally:session.close()

def test_background_streaming_and_completion_do_not_steal_selected_issue():
    a,ha=connect();b,hb=connect()
    emit(ha,command='long command',output='',code=None,state='running')
    emit(hb)
    issue=snapshot()['issues'][0]
    assert client.post(f"/api/issues/{issue['id']}/open?mode=rules").status_code==200
    emit(ha,command='long command',output='progress',code=None,state='running')
    assert snapshot()['selected_session']==b['session_id']
    emit(ha,command='long command',output='done',code=0)
    assert snapshot()['latest']['session_id']==b['session_id']
    assert snapshot()['latest']['status']=='problem'
    assert snapshot()['sessions'][0]['diagnosis']['status']=='healthy'
