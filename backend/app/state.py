"""Shared process-local state for the browser, launcher and managed terminal."""
import re
import secrets
import time
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from pydantic import Field, field_validator

from app.models.schemas import DiagnoseResponse, StrictModel

ENV_KEYS = {'ROS_DISTRO', 'ROS_VERSION', 'ROS_DOMAIN_ID', 'AMENT_PREFIX_PATH', 'VIRTUAL_ENV', 'CONDA_DEFAULT_ENV'}
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


class TerminalConnect(StrictModel):
    shell: str = Field(min_length=1, max_length=100)
    cwd: str = Field(max_length=1500)


class TerminalEvent(StrictModel):
    sequence: int = Field(ge=1)
    command: str = Field(min_length=1, max_length=4096)
    output: str = Field(default='', max_length=16000)
    exit_code: int | None = None
    state: str = Field(pattern='^(running|finished|cancelled)$')
    cwd: str = Field(default='', max_length=1500)
    environment: dict[str, str] = Field(default_factory=dict)

    @field_validator('environment')
    @classmethod
    def bounded_environment(cls, value):
        if any(key not in ENV_KEYS or len(item) > 1500 for key, item in value.items()):
            raise ValueError('Only bounded diagnostic environment fields are allowed')
        return value


class WorkspaceState:
    def __init__(self):
        self.lock = RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.revision = 0
            self.token = None
            self.last_seen = 0.0
            self.shell = ''
            self.cwd = ''
            self.execution = None
            self.latest = None
            self.history = []
            self.blackboard = None
            self.analyzing = False
            self.analyzing_sequence = None

    def connect(self, shell, cwd):
        with self.lock:
            if self.token and time.monotonic() - self.last_seen < 20:
                raise ValueError('A managed terminal is already connected. Close it before connecting another.')
            self.token = secrets.token_urlsafe(32)
            self.last_seen = time.monotonic()
            self.shell, self.cwd = shell, cwd
            self.execution = None
            self.revision += 1
            return self.token

    def authorized(self, token):
        return bool(self.token and token and secrets.compare_digest(self.token, token))

    def touch(self, token):
        with self.lock:
            if not self.authorized(token):
                return False
            self.last_seen = time.monotonic()
            return True

    def ingest(self, token, event: TerminalEvent):
        with self.lock:
            if not self.touch(token):
                raise PermissionError('Managed terminal session is not authorized. Reconnect it.')
            old = self.execution
            if old and (event.sequence < old['sequence'] or
                        (event.sequence == old['sequence'] and old['state'] != 'running')):
                raise ValueError('Stale terminal event')
            if event.state == 'finished' and event.exit_code is None:
                raise ValueError('Finished execution requires an exit code')
            self.execution = event.model_dump()
            self.execution['output'] = ANSI.sub('', event.output).replace('\x00', '')[-12000:]
            self.cwd = event.cwd or self.cwd
            self.latest = None
            self.revision += 1

    def remember(self, response: DiagnoseResponse, blackboard, expected_sequence=None):
        with self.lock:
            # Don't replace a newer terminal run with a slow result for an older run.
            if expected_sequence is not None and (not self.execution or self.execution['sequence'] != expected_sequence):
                return False
            self.latest = response.model_dump()
            self.blackboard = blackboard
            self.history.insert(0, {'id': str(uuid4()), 'created_at': datetime.now(timezone.utc).isoformat(),
                                   'category': blackboard.language, **self.latest})
            self.history = self.history[:12]
            self.revision += 1
            return True

    def snapshot(self):
        with self.lock:
            return {'revision': self.revision, 'analyzing': self.analyzing,
                    'terminal': {'connected': bool(self.token and time.monotonic() - self.last_seen < 20),
                                 'shell': self.shell, 'cwd': self.cwd, 'execution': self.execution},
                    'latest': self.latest,
                    'history': self.history}


workspace = WorkspaceState()
