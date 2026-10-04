from types import SimpleNamespace
from unittest.mock import patch
import queue
import time
import pytest
from companion.desktop import Companion

class Client:
    def __init__(self,issues): self.issues=issues; self.calls=[]
    def request(self,method,path,**kwargs):
        self.calls.append((method,path))
        return {'issues':self.issues} if path=='/workspace' else {}
def robot(issues):
    return SimpleNamespace(busy=False,client=Client(issues),events=queue.Queue())
@pytest.mark.parametrize('count',[0,1,3])
def test_double_click_routes_only_one_issue(count):
    issues=[{'id':f'issue-{i}','session_id':f'session-{i}'} for i in range(count)]
    companion=robot(issues)
    with patch('companion.desktop.webbrowser.open',return_value=True) as browser:
        Companion.open_workspace(companion)
        deadline=time.monotonic()+2
        while companion.events.empty() and time.monotonic()<deadline: time.sleep(.01)
        assert companion.events.get(timeout=1)[0]=='finished'
    calls=companion.client.calls
    if count==1:
        assert ('POST','/sessions/session-0/select') in calls
        assert ('POST','/issues/issue-0/open') in calls
        assert '?session=session-0' in browser.call_args.args[0]
    else:
        assert not any('/open' in path for method,path in calls)
        assert '?source=companion' in browser.call_args.args[0]

def test_busy_companion_does_not_duplicate():
    companion=robot([{'id':'one','session_id':'s'}]);companion.busy=True
    Companion.open_workspace(companion)
    assert not companion.client.calls
