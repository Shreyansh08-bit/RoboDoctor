import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.local import model_status
from app.service import analyze_evidence
from app.models.schemas import DiagnoseRequest, DiagnoseResponse
from app.state import TerminalConnect, TerminalEvent, workspace

app = FastAPI(title='RoboDoctor', version='1.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
ai_lock = asyncio.Lock()


@app.middleware('http')
async def limit_body(request: Request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in {'http://localhost:5173', 'http://127.0.0.1:5173'}:
        return JSONResponse(status_code=403, content={'detail': 'Only the local RoboDoctor workspace may access this API'})
    if request.method == 'POST':
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 400_000:
                return JSONResponse(status_code=413, content={'detail': 'Request exceeds 400 KB'})
        request._body = bytes(body)
    return await call_next(request)


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'ai': await model_status(), 'terminal': workspace.snapshot()['terminal']['connected']}


@app.get('/api/examples')
def examples():
    return json.loads((Path(__file__).resolve().parents[2] / 'examples' / 'scenarios.json').read_text(encoding='utf-8'))


@app.post('/api/examples/{example_id}/diagnose', response_model=DiagnoseResponse)
async def analyze_example(example_id: str, mode: str = 'auto'):
    if mode not in {'auto', 'rules'}:
        raise HTTPException(422, 'Choose auto or rules mode')
    example = next((item for item in examples() if item['id'] == example_id), None)
    if not example:
        raise HTTPException(404, 'Unknown example')
    execution = None
    if 'exit_code' in example:
        execution = {'sequence': None, 'command': 'python robot.py (built-in example)',
                     'exit_code': example['exit_code'], 'state': 'finished', 'environment': {}, 'cwd': 'example'}
    return await run_diagnosis(DiagnoseRequest(text=example['text'], mode=mode), execution)


@app.post('/api/diagnose', response_model=DiagnoseResponse)
async def analyze(request: DiagnoseRequest):
    return await run_diagnosis(request)


async def run_diagnosis(request, execution=None):
    if ai_lock.locked():
        raise HTTPException(429, 'A diagnosis is already running. Try again when it finishes.')
    async with ai_lock:
        workspace.analyzing = True
        workspace.revision += 1
        try:
            history = [item['diagnosis']['summary'] for item in workspace.history[:3]]
            response, board = await analyze_evidence(request, execution, history)
            sequence = execution['sequence'] if execution else None
            if not workspace.remember(response, board, sequence):
                raise HTTPException(409, 'A newer terminal command completed. Analyze that run instead.')
            return response
        finally:
            workspace.analyzing = False
            workspace.revision += 1


@app.get('/api/workspace')
def workspace_snapshot():
    return workspace.snapshot()


@app.post('/api/terminal/connect')
def terminal_connect(request: TerminalConnect):
    try:
        return {'token': workspace.connect(request.shell, request.cwd)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/terminal/heartbeat')
def terminal_heartbeat(x_robodoctor_session: str = Header(default='')):
    if not workspace.touch(x_robodoctor_session):
        raise HTTPException(401, 'Terminal session expired. Reconnect.')
    return {'status': 'connected'}


@app.post('/api/terminal/disconnect')
def terminal_disconnect(x_robodoctor_session: str = Header(default='')):
    with workspace.lock:
        if not workspace.authorized(x_robodoctor_session):
            raise HTTPException(401, 'Unknown terminal session')
        workspace.token = None
        workspace.revision += 1
    return {'status': 'disconnected'}


@app.post('/api/terminal/event')
def terminal_event(request: TerminalEvent, x_robodoctor_session: str = Header(default='')):
    try:
        workspace.ingest(x_robodoctor_session, request)
        return {'status': 'captured', 'sequence': request.sequence}
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/terminal/diagnose', response_model=DiagnoseResponse)
async def terminal_diagnose(mode: str = 'auto'):
    if mode not in {'auto', 'rules'}:
        raise HTTPException(422, 'Choose auto or rules mode')
    execution = workspace.snapshot()['terminal']['execution']
    if not execution:
        raise HTTPException(409, 'No managed terminal output yet. Run a command in the RoboDoctor terminal.')
    if execution['state'] == 'running':
        raise HTTPException(409, 'The terminal command is still running. Finish or stop it before diagnosing.')
    text = f"$ {execution['command']}\n{execution['output']}\nExit code: {execution['exit_code']}"
    return await run_diagnosis(DiagnoseRequest(text=text, mode=mode), execution)
