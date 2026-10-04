import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from app.ai.local import LocalAIError, diagnose
from app.diagnostics.fallback import fallback
from app.models.schemas import DiagnoseRequest
from app.settings import Settings


def invoke(content):
    class MockClient:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            assert url.startswith('http://127.0.0.1:')
            assert json['format']['properties']['summary']
            context = __import__('json').loads(json['messages'][1]['content'])
            assert 'diagnostic_blackboard' in context
            assert 'important_evidence' in context['diagnostic_blackboard']
            return httpx.Response(200, json={'message': {'content': content}},
                                  request=httpx.Request('POST', url))
    with patch('app.ai.local.httpx.AsyncClient', MockClient):
        return asyncio.run(diagnose(DiagnoseRequest(text='actual supplied line'), []))


def test_valid_structured_model_response():
    data = fallback([]).model_dump()
    data['evidence'] = ['actual supplied line']
    assert invoke(json.dumps(data)).evidence == ['actual supplied line']


@pytest.mark.parametrize('content', ['not json', '{}', '{"summary": "x"}'])
def test_invalid_model_response(content):
    with pytest.raises(LocalAIError, match='invalid structured output'):
        invoke(content)


def test_hallucinated_evidence_rejected():
    data = fallback([]).model_dump()
    data['evidence'] = ['invented robot output']
    with pytest.raises(LocalAIError, match='could not be verified'):
        invoke(json.dumps(data))


def test_empty_evidence_forces_insufficient_evidence():
    data = fallback([]).model_dump()
    data['summary'] = 'Overconfident diagnosis'
    data['confidence'] = 'high'
    result = invoke(json.dumps(data))
    assert result.summary == 'Insufficient evidence.'
    assert result.confidence == 'low'
    assert not result.root_causes


@pytest.mark.parametrize('url', ['https://api.example.com', 'http://192.168.1.1:11434',
                              'http://localhost:11434/path', 'http://user:pass@localhost:11434'])
def test_remote_model_endpoint_rejected(url):
    with pytest.raises(ValueError):
        Settings(ollama_base_url=url, _env_file=None)


def test_cloud_model_rejected():
    with pytest.raises(ValueError):
        Settings(model_name='qwen3:cloud', _env_file=None)
