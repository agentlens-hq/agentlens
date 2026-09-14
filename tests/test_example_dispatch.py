import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import openai

from examples import anthropic_broken_agent, openai_broken_agent


class ExampleDispatch(unittest.TestCase):
    def test_openai_real_object_dispatches_selected_tool_and_arguments(self):
        client = MagicMock()
        call = openai.types.chat.ChatCompletionMessageFunctionToolCall(id='id', type='function', function={'name': 'query_db', 'arguments': '{"query":"customer C17"}'})
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])
        with patch('openai.OpenAI', return_value=client), patch.object(openai_broken_agent, 'dispatch_tool', return_value={'status': 'success'}) as dispatch, patch.object(openai_broken_agent.agentlens, 'record_tool_result'):
            openai_broken_agent.run_agent.__wrapped__('task')
        dispatch.assert_called_once_with('query_db', {'query': 'customer C17'})

    def test_anthropic_real_object_dispatches_selected_tool(self):
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[anthropic.types.ToolUseBlock(type='tool_use', id='id', name='query_db', input={'query': 'customer C17'})])
        with patch('anthropic.Anthropic', return_value=client), patch.object(anthropic_broken_agent, 'dispatch_tool', return_value={'status': 'success'}) as dispatch, patch.object(anthropic_broken_agent.agentlens, 'record_tool_result'):
            anthropic_broken_agent.run_agent.__wrapped__('task')
        dispatch.assert_called_once_with('query_db', {'query': 'customer C17'})
