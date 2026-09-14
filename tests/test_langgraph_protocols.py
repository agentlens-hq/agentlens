import asyncio
import unittest

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agentlens_sdk import collector as c
from agentlens_sdk.langgraph import patch_langgraph


class State(TypedDict):
    value: int


def graph():
    builder = StateGraph(State)
    builder.add_node('increment', lambda state: {'value': state['value'] + 1})
    builder.add_edge(START, 'increment')
    builder.add_edge('increment', END)
    return builder.compile()


class LangGraphProtocols(unittest.TestCase):
    def setUp(self):
        self.token = c._current_run.set(c.start_run())
        patch_langgraph()

    def tearDown(self):
        c._current_run.reset(self.token)

    def test_invoke_aggregate_and_updates_nodes(self):
        app = graph()
        self.assertEqual(app.invoke({'value': 1}), {'value': 2})
        self.assertEqual(list(app.stream({'value': 1}, stream_mode='updates')), [{'increment': {'value': 2}}])
        nodes = [s['tool_name'] for s in c.current_run()['spans'] if s['type'] == 'langgraph_node']
        self.assertEqual(nodes, ['increment'])

    def test_values_do_not_invent_node_names(self):
        list(graph().stream({'value': 1}, stream_mode='values'))
        self.assertEqual([s for s in c.current_run()['spans'] if s['type'] == 'langgraph_node'], [])

    def test_async_and_configured_wrapper(self):
        async def work():
            app = graph().with_config({'tags': ['test']})
            self.assertEqual(await app.ainvoke({'value': 1}), {'value': 2})
            self.assertEqual(len([x async for x in app.astream({'value': 1}, stream_mode='updates')]), 1)
        asyncio.run(work())
        self.assertTrue(any(s['type'] == 'langgraph_node' for s in c.current_run()['spans']))
