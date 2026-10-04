"""Persistent user-driven shell. No API route or diagnosis can execute a command."""
import json
import os
import queue
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import tempfile
from pathlib import Path
from uuid import uuid4

ENV_KEYS = ('ROS_DISTRO', 'ROS_VERSION', 'ROS_DOMAIN_ID', 'AMENT_PREFIX_PATH', 'VIRTUAL_ENV', 'CONDA_DEFAULT_ENV')


class ShellSession:
    def __init__(self, cwd=None):
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.windows = os.name == 'nt'
        self.shell = (shutil.which('pwsh') or shutil.which('powershell')) if self.windows else shutil.which('bash')
        if not self.shell:
            raise RuntimeError('PowerShell (Windows) or Bash (Ubuntu) is required for the managed terminal.')
        self.process = None
        self.lines = queue.Queue(maxsize=256)
        self.sequence = 0
        self.start()

    def start(self):
        self.lines = queue.Queue(maxsize=256)
        args = [self.shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '-'] if self.windows else [self.shell, '--noprofile', '--norc']
        kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if self.windows else {'start_new_session': True}
        env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'NO_COLOR': '1', 'TERM': 'dumb'}
        self.process = subprocess.Popen(args, cwd=self.cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace', bufsize=1, **kwargs)
        output_queue, process = self.lines, self.process

        def read():
            try:
                for line in process.stdout:
                    output_queue.put(line)
            finally:
                output_queue.put(None)
        threading.Thread(target=read, daemon=True).start()

    def script(self, command, marker):
        if self.windows:
            fields = ';'.join(f"{key}=[string]$env:{key}" for key in ENV_KEYS)
            return (f"$global:LASTEXITCODE=0; {command}; $__rd_ok=$?; $__rd_ec=$global:LASTEXITCODE; "
                    "if ($__rd_ec -ne 0) {$__rd_code=$__rd_ec} elseif ($__rd_ok) {$__rd_code=0} else {$__rd_code=1}; "
                    f"$__rd_env=@{{{fields}}}; $__rd_meta=@{{exit_code=$__rd_code;cwd=(Get-Location).Path;environment=$__rd_env}} | ConvertTo-Json -Compress; "
                    f'Write-Output ("`n{marker}:" + $__rd_meta)\n')
        code = "import os,json; print(json.dumps({'cwd':os.getcwd(),'environment':{k:os.environ.get(k,'') for k in " + repr(ENV_KEYS) + "}}))"
        return (f"{command}\n__rd_code=$?\n__rd_meta=$({shlex.quote(sys.executable)} -c {shlex.quote(code)})\n"
                f"printf '\\n{marker}:%s:%s\\n' \"$__rd_code\" \"$__rd_meta\"\n")

    def execute(self, command, on_output=None):
        if not command.strip() or '\n' in command or '\r' in command or len(command) > 4096:
            raise ValueError('Enter one complete command, at most 4,096 characters.')
        if not self.process or self.process.poll() is not None:
            self.start()
        self.sequence += 1
        marker = '__ROBODOCTOR_' + uuid4().hex
        process, output_queue = self.process, self.lines
        capture = tempfile.NamedTemporaryFile(prefix='robodoctor-stderr-', delete=False)
        stderr_path = capture.name
        capture.close()
        redirected = (". { " + command + " } 2> '" + stderr_path.replace("'", "''") + "'") if self.windows else ('{ ' + command + '; } 2> ' + shlex.quote(stderr_path))
        process.stdin.write(self.script(redirected, marker))
        process.stdin.flush()
        output = ''
        while True:
            line = output_queue.get()
            if line is None:
                code = process.wait()
                Path(stderr_path).unlink(missing_ok=True)
                return {'command': command, 'output': output[-12000:], 'exit_code': code if code else 1,
                        'state': 'cancelled' if code else 'finished', 'sequence': self.sequence,
                        'cwd': self.cwd, 'environment': {}}
            if marker + ':' in line:
                metadata = line.split(marker + ':', 1)[1].strip()
                if self.windows:
                    data = json.loads(metadata)
                else:
                    exit_code, metadata = metadata.split(':', 1)
                    data = {**json.loads(metadata), 'exit_code': int(exit_code)}
                self.cwd = data['cwd']
                data['environment'] = {key: str(value)[:1500] for key, value in data['environment'].items() if value}
                with open(stderr_path, 'rb') as capture:
                    bom = capture.read(2)
                    capture.seek(0, 2)
                    capture.seek(max(0, capture.tell()-24000))
                    raw = capture.read(24000)
                stderr = raw.decode('utf-16-le' if bom == b'\xff\xfe' else 'utf-8', 'replace').lstrip('\ufeff')[-12000:]
                Path(stderr_path).unlink(missing_ok=True)
                if stderr and on_output:
                    on_output(stderr, (output + stderr)[-12000:])
                return {'command': command, 'output': (output + stderr)[-12000:], 'stdout': output[-12000:], 'stderr': stderr, 'sequence': self.sequence,
                        'state': 'finished', **data}
            output = (output + line)[-12000:]
            if on_output:
                on_output(line, output)

    def close(self):
        process = self.process
        if not process or process.poll() is not None:
            return
        if self.windows:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if not self.windows:
                os.killpg(process.pid, signal.SIGKILL)
            process.kill()
