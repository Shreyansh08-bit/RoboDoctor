import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.ai.local import model_status
from app.settings import settings


@pytest.mark.parametrize('installed,models,expected', [
    (False, None, (False, False, False)),
    (True, None, (True, False, False)),
    (True, [], (True, True, False)),
    (False, [settings.model_name], (True, True, True)),
])
def test_separate_runtime_and_model_status(installed, models, expected):
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            if models is None:
                raise httpx.ConnectError('offline')
            return httpx.Response(200, json={'models': [{'name': name} for name in models]},
                                  request=httpx.Request('GET', url))
    with patch('app.ai.local.shutil.which', return_value='ollama' if installed else None), \
         patch('app.ai.local.Path.is_file', return_value=False), \
         patch('app.ai.local.httpx.AsyncClient', Client):
        status = asyncio.run(model_status())
    assert (status['installed'], status['reachable'], status['model_available']) == expected
    assert status['available'] == expected[2]
    assert status['message']
