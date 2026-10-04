import httpx

API_URL = 'http://127.0.0.1:8000/api'
WORKSPACE_URL = 'http://127.0.0.1:5173/?source=companion'


class BackendClient:
    def __init__(self):
        self.token = None

    def request(self, method, path, payload=None, timeout=5):
        headers = {'X-RoboDoctor-Session': self.token} if self.token else {}
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.request(method, API_URL + path, json=payload, headers=headers)
        if not response.is_success:
            try:
                message = response.json().get('detail', f'HTTP {response.status_code}')
            except ValueError:
                message = f'HTTP {response.status_code}'
            raise RuntimeError(str(message))
        return response.json()

    def connect(self, shell, cwd):
        self.token = self.request('POST', '/terminal/connect', {'shell': shell, 'cwd': cwd})['token']

    def disconnect(self):
        try:
            if self.token:
                self.request('POST', '/terminal/disconnect')
        finally:
            self.token = None
