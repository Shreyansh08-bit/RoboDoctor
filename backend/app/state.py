"""Independent managed sessions, deterministic issue detection and stale-result guards."""
import copy
import re
import secrets
import time
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4
from pydantic import Field, field_validator
from app.models.schemas import DiagnoseRequest, DiagnoseResponse, StrictModel
ENV_KEYS = {'ROS_DISTRO','ROS_VERSION','ROS_DOMAIN_ID','AMENT_PREFIX_PATH','VIRTUAL_ENV','CONDA_DEFAULT_ENV'}
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
ACTIVE = {'UNOPENED','INVESTIGATING','DIAGNOSED','UNRESOLVED'}
def now(): return datetime.now(timezone.utc).isoformat()
class TerminalConnect(StrictModel):
    shell: str = Field(min_length=1,max_length=100)
    cwd: str = Field(max_length=1500)
class TerminalEvent(StrictModel):
    sequence: int = Field(ge=1)
    command: str = Field(min_length=1,max_length=4096)
    output: str = Field(default='',max_length=16000)
    stdout: str = Field(default='',max_length=16000)
    stderr: str = Field(default='',max_length=16000)
    exit_code: int | None = None
    state: str = Field(pattern='^(running|finished|cancelled)$')
    cwd: str = Field(default='',max_length=1500)
    environment: dict[str,str] = Field(default_factory=dict)
    @field_validator('environment')
    @classmethod
    def bounded_environment(cls,value):
        if any(k not in ENV_KEYS or len(v)>1500 for k,v in value.items()):
            raise ValueError('Only bounded diagnostic environment fields are allowed')
        return value
class WorkspaceState:
    def __init__(self):
        self.lock=RLock(); self.reset()
    def reset(self):
        with self.lock:
            self.revision=0; self.sessions={}; self.issues={}; self.selected_session=None
            self.latest=None; self.history=[]; self.blackboard=None; self.analyzing=False
            self.analyzing_sequence=None; self.focus_request=None
    @property
    def execution(self): return (self.sessions.get(self.selected_session) or {}).get('execution')
    def connect(self,shell,cwd):
        with self.lock:
            if len(self.sessions)>=32: raise ValueError('Maximum 32 sessions. Restart to clear archived sessions.')
            sid='session-'+uuid4().hex[:12]; token=secrets.token_urlsafe(32)
            self.sessions[sid]={'id':sid,'name':f'Terminal {len(self.sessions)+1:02d}','token':token,
                'last_seen':time.monotonic(),'shell':shell,'cwd':cwd,'execution':None,
                'recent_commands':[],'diagnosis':None,'diagnostic_log':[]}
            self.selected_session=sid; self.latest=None; self.revision+=1
            return token
    def session_for_token(self,token):
        return next((s for s in self.sessions.values() if token and s['token'] and secrets.compare_digest(s['token'],token)),None)
    def authorized(self,token): return bool(self.session_for_token(token))
    def touch(self,token):
        with self.lock:
            s=self.session_for_token(token)
            if not s: return False
            s['last_seen']=time.monotonic(); return True
    def disconnect(self,token):
        with self.lock:
            s=self.session_for_token(token)
            if not s: raise PermissionError('Unknown terminal session')
            s['token']=None; self.revision+=1
    def ingest(self,token,event):
        from app.diagnostics.blackboard import build_blackboard
        from app.service import healthy_diagnosis
        with self.lock:
            s=self.session_for_token(token)
            if not s or not self.touch(token): raise PermissionError('Managed terminal session is not authorized. Reconnect it.')
            old=s['execution']
            if old and (event.sequence<old['sequence'] or (event.sequence==old['sequence'] and old['state']!='running')):
                raise ValueError('Stale terminal event')
            if event.state=='finished' and event.exit_code is None: raise ValueError('Finished execution requires an exit code')
            e=event.model_dump()
            for k in ['output','stdout','stderr']: e[k]=ANSI.sub('',e[k]).replace('\x00','')[-12000:]
            if not e['output']: e['output']=(e['stdout']+'\n'+e['stderr']).strip()[-12000:]
            e.update(session_id=s['id'],timestamp=now())
            s['execution']=e; s['cwd']=event.cwd or s['cwd']; s['diagnosis']=None
            # A newly started command takes precedence over demos. Streaming updates
            # from another already-running session must not steal the selected issue.
            if not old or old['sequence'] != event.sequence:
                self.selected_session=s['id']
            if self.selected_session == s['id']:
                self.latest=None
            if event.state=='finished':
                s['recent_commands']=(s['recent_commands']+[event.command])[-5:]
                board=build_blackboard(DiagnoseRequest(text=e['output'] if e['output'].strip() else f'Exit code: {event.exit_code}'),e)
                error=event.exit_code!=0 or bool(board.patterns) or bool(re.search(r'Traceback \(most recent|\[ERROR\]|\berror:|\bfatal:|segmentation fault',e['output'],re.I))
                for issue in self.issues.values():
                    if issue['session_id']==s['id'] and issue['command']==event.command and issue['status'] in ACTIVE:
                        issue['status']='SUPERSEDED' if error else 'RESOLVED'
                if error:
                    iid=str(uuid4()); self.issues[iid]={'id':iid,**copy.deepcopy(e),'execution_sequence':event.sequence,
                        'status':'UNOPENED','diagnosis':None,'confidence':None,'investigation_state':'waiting',
                        'title':board.patterns[0].title if board.patterns else 'Command failed'}
                else:
                    healthy=DiagnoseResponse(diagnosis=healthy_diagnosis(e),findings=[],engine='observed',elapsed_ms=0,
                        status='healthy',session_id=s['id'],execution_sequence=event.sequence).model_dump()
                    s['diagnosis']=healthy
                    if self.selected_session == s['id']:
                        self.latest=healthy
                archived=[k for k,i in self.issues.items() if i['status'] not in ACTIVE]
                for k in archived[:-64]: del self.issues[k]
            self.revision+=1
    def select(self,sid,focus=False):
        with self.lock:
            if sid not in self.sessions: raise ValueError('Unknown terminal session')
            self.selected_session=sid; self.latest=self.sessions[sid]['diagnosis']
            if focus: self.focus_request={'id':str(uuid4()),'session_id':sid,'status':'requested'}
            self.revision+=1
    def remember(self,response,blackboard,expected_sequence=None,session_id=None,issue_id=None,expected_revision=None):
        with self.lock:
            sid=session_id or self.selected_session; s=self.sessions.get(sid); e=s['execution'] if s else None
            if expected_sequence is not None and (not e or e['sequence']!=expected_sequence or e['state']=='running'): return False
            response.session_id=sid if expected_sequence is not None else None
            response.execution_sequence=expected_sequence; response.issue_id=issue_id; data=response.model_dump()
            if expected_sequence is not None:
                s['diagnosis']=data
                if sid==self.selected_session: self.latest=data
            elif expected_revision is None or self.revision==expected_revision: self.latest=data
            self.blackboard=blackboard
            self.history.insert(0,{'id':str(uuid4()),'created_at':now(),'category':blackboard.language,**data})
            self.history=self.history[:12]
            if issue_id in self.issues:
                self.issues[issue_id].update(diagnosis=data,confidence=response.diagnosis.confidence,
                    status='UNRESOLVED' if response.diagnosis.confidence=='low' or response.status=='insufficient' else 'DIAGNOSED',investigation_state='complete')
            self.revision+=1; return True
    def snapshot(self):
        with self.lock:
            sessions=[{**{k:v for k,v in s.items() if k not in {'token','last_seen'}},'connected':bool(s['token'] and time.monotonic()-s['last_seen']<20)} for s in self.sessions.values()]
            terminal=next((s for s in sessions if s['id']==self.selected_session),{'connected':False,'shell':'','cwd':'','execution':None})
            issues=[i for i in self.issues.values() if i['status'] in ACTIVE]
            emotion='investigating' if self.analyzing else 'worried' if any(i['status']=='UNOPENED' for i in issues) else 'unresolved' if any(i['status']=='UNRESOLVED' for i in issues) else 'ready' if issues else 'healthy' if self.execution and self.execution['state']=='finished' else 'sleeping'
            return copy.deepcopy({'revision':self.revision,'analyzing':self.analyzing,'terminal':terminal,'sessions':sessions,
                'selected_session':self.selected_session,'issues':issues,'issue_count':len(issues),'emotion':emotion,
                'focus_request':self.focus_request,'latest':self.latest,'history':self.history})
workspace=WorkspaceState()
