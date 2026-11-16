"""Verify remote-dispatch wiring without AWS or real grading logic."""
import asyncio
import io
import json

import pytest

import invoke_runtime
import runtime


class RuntimeClient:
    def __init__(self, corrupt=None):
        self.corrupt = corrupt

    def invoke_agent_runtime(self, **kwargs):
        result = asyncio.run(runtime.execute_evaluator(json.loads(kwargs['payload'])))
        if self.corrupt:
            result[self.corrupt] = 'unexpected'
        return {'ResponseMetadata': {'HTTPStatusCode': 200},
                'contentType': 'application/json',
                'response': io.BytesIO(json.dumps(result).encode())}


@pytest.mark.parametrize('evaluator', ['rules', 'factcheck', 'judge', 'pairwise'])
def test_client_dispatches_expected_file(evaluator):
    result = invoke_runtime.invoke_evaluator(RuntimeClient(), 'test-runtime', evaluator)
    assert result['stdout'].startswith('Hello World')
    assert runtime.SCRIPTS[evaluator] in result['stdout']


@pytest.mark.parametrize('field', ['request_id', 'script_sha256'])
def test_client_rejects_mismatched_response(field):
    with pytest.raises(RuntimeError, match='does not match'):
        invoke_runtime.invoke_evaluator(RuntimeClient(field), 'test-runtime', 'rules')


def test_runtime_rejects_arbitrary_file():
    with pytest.raises(ValueError, match='Unknown evaluator'):
        asyncio.run(runtime.execute_evaluator({'evaluator': '../other.py', 'request_id': 'test'}))
