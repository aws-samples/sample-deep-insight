"""Verify one remote invocation runs all evaluators sequentially without AWS."""
import asyncio
import io
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

import invoke_runtime
import runtime


class RuntimeClient:
    def __init__(self, mutate=None, streaming=False):
        self.mutate = mutate
        self.streaming = streaming
        self.calls = []
        self.body = None

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        context = SimpleNamespace(session_id=kwargs['runtimeSessionId'])

        async def dispatch():
            return [event async for event in runtime.invoke(json.loads(kwargs['payload']), context)]

        events = asyncio.run(dispatch())
        assert len(events) == 1
        result = events[0]
        if self.mutate:
            self.mutate(result)
        if self.streaming:
            data = b'data: ' + json.dumps(result).encode() + b'\n\n'
            self.body = io.BytesIO(data)
            self.body.iter_lines = lambda **_: data.splitlines()
        else:
            self.body = io.BytesIO(json.dumps(result).encode())
        return {'ResponseMetadata': {'HTTPStatusCode': 200},
                'contentType': 'text/event-stream' if self.streaming else 'application/json',
                'response': self.body}


@pytest.mark.parametrize('streaming', [False, True])
def test_one_invocation_runs_all_four_in_order(streaming):
    client = RuntimeClient(streaming=streaming)
    result = invoke_runtime.invoke_evaluators(client, 'test-runtime')
    assert len(client.calls) == 1
    assert client.body.closed
    assert [r['evaluator'] for r in result['results']] == ['rules', 'factcheck', 'judge', 'pairwise']
    for evaluation, script in zip(result['results'], runtime.SCRIPTS.values()):
        assert evaluation['stdout'].startswith('Hello World')
        assert evaluation['script'] == script
        assert script in evaluation['stdout']
    for previous, current in zip(result['results'], result['results'][1:]):
        assert datetime.fromisoformat(previous['completed_at']) <= datetime.fromisoformat(current['started_at'])


@pytest.mark.parametrize('field', ['request_id', 'runtime_session_id', 'execution_environment'])
def test_client_rejects_mismatched_batch(field):
    client = RuntimeClient(lambda result: result.update({field: 'unexpected'}))
    with pytest.raises(RuntimeError, match='does not match'):
        invoke_runtime.invoke_evaluators(client, 'test-runtime')
    assert client.body.closed


@pytest.mark.parametrize('field', ['request_id', 'runtime_session_id', 'script', 'script_sha256'])
def test_client_rejects_mismatched_evaluator(field):
    client = RuntimeClient(lambda result: result['results'][2].update({field: 'unexpected'}))
    with pytest.raises(RuntimeError, match='does not match evaluator judge'):
        invoke_runtime.invoke_evaluators(client, 'test-runtime')


@pytest.mark.parametrize('mutate', [
    lambda result: result['results'].pop(),
    lambda result: result['results'].reverse(),
    lambda result: result['results'].__setitem__(1, result['results'][0]),
])
def test_client_rejects_missing_reordered_or_duplicate_results(mutate):
    with pytest.raises(RuntimeError):
        invoke_runtime.invoke_evaluators(RuntimeClient(mutate), 'test-runtime')


@pytest.mark.parametrize(('field', 'value', 'message'), [
    ('returncode', 1, 'judge failed'),
    ('stdout', '', 'judge did not print Hello World'),
])
def test_client_rejects_unsuccessful_evaluator(field, value, message):
    client = RuntimeClient(lambda result: result['results'][2].update({field: value}))
    with pytest.raises(RuntimeError, match=message):
        invoke_runtime.invoke_evaluators(client, 'test-runtime')


@pytest.mark.parametrize('timeout', [False, True])
def test_runtime_continues_in_order_after_failure(monkeypatch, timeout):
    executions = []
    active = False

    async def create_process(*args, **kwargs):
        nonlocal active
        assert not active, 'evaluators must not overlap'
        active = True
        name = args[1].rsplit('/', 1)[-1]
        executions.append(name)

        class Process:
            returncode = 1 if name == 'factcheck.py' else 0
            attempts = 0

            def kill(self):
                self.returncode = -9

            async def communicate(self):
                nonlocal active
                self.attempts += 1
                if timeout and name == 'factcheck.py' and self.attempts == 1:
                    raise asyncio.TimeoutError
                await asyncio.sleep(0)
                active = False
                return b'Hello World', b''

        return Process()

    monkeypatch.setattr(runtime.asyncio, 'create_subprocess_exec', create_process)
    result = asyncio.run(runtime.execute_evaluators({
        'evaluators': list(runtime.SCRIPTS), 'request_id': 'test',
    }))
    assert executions == ['rules.py', 'factcheck.py', 'judge.py', 'pairwise.py']
    assert result['results'][1]['returncode'] != 0
    if timeout:
        assert 'exceeded 30 seconds' in result['results'][1]['stderr']


@pytest.mark.parametrize('evaluators', [[], ['../other.py'], ['rules'],
                                        ['pairwise', 'judge', 'factcheck', 'rules']])
def test_runtime_rejects_invalid_batch(evaluators):
    with pytest.raises(ValueError, match='Expected all four evaluators in order'):
        asyncio.run(runtime.execute_evaluators({'evaluators': evaluators, 'request_id': 'test'}))


def test_runtime_rejects_arbitrary_file():
    with pytest.raises(ValueError, match='Unknown evaluator'):
        asyncio.run(runtime.execute_evaluator({'evaluator': '../other.py', 'request_id': 'test'}))
