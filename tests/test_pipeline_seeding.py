"""Tests for transcript seeding in the agent pipeline."""

import unittest

from review_bot.agents import SUB_AGENTS, critic_agent_def
from review_bot.orchestration.pipeline import run_agent_pipeline


class _FakeResult:
    def __init__(self, output, messages):
        self.output = output
        self._messages = messages

    def all_messages(self):
        return self._messages


class _FakeReport:
    def __init__(self, name):
        self.name = name
        self.findings = []

    def model_dump_json(self):
        return '{"agent": "%s"}' % self.name


class _FakeFinalResult:
    critical_line_comments = []


class _FakeAgent:
    def __init__(self, name):
        self.name = name
        self.calls = []
        self.last_output = None

    async def run(self, prompt, deps=None, usage_limits=None, message_history=None):
        self.calls.append(
            {
                "prompt": prompt,
                "message_history": message_history,
                "deps": deps,
            }
        )
        output = _FakeFinalResult() if self.name == "critic" else _FakeReport(self.name)
        self.last_output = output
        return _FakeResult(
            output=output,
            messages=[f"{self.name}-msg-{len(self.calls)}"],
        )


class _FakeRequest:
    def description(self):
        return "A fake MR description."


class TestRunAgentPipelineSeeding(unittest.IsolatedAsyncioTestCase):
    def _agents(self):
        names = [a.name for a in SUB_AGENTS] + [critic_agent_def.name]
        return {f"{name}_agent": _FakeAgent(name) for name in names}

    async def test_judgment_agents_seeded_with_context_transcript(self):
        agents = self._agents()
        base_prompt = "BASE"
        result = await run_agent_pipeline(
            agents=agents,
            secure_base_prompt=base_prompt,
            mr_request=_FakeRequest(),
            container_manager=object(),
            vector_index=object(),
        )
        critic_output = agents["critic_agent"].last_output

        context_call = agents["context_agent"].calls[0]
        self.assertEqual(
            context_call["prompt"], base_prompt + SUB_AGENTS[0].specialty_prompt
        )
        self.assertIsNone(context_call["message_history"])

        context_messages = ["context-msg-1"]
        for agent_def in SUB_AGENTS[1:]:
            call = agents[f"{agent_def.name}_agent"].calls[0]
            self.assertEqual(call["prompt"], agent_def.specialty_prompt)
            self.assertEqual(call["message_history"], context_messages)
            self.assertEqual(call["deps"].agent_name, agent_def.name)

        critic_call = agents["critic_agent"].calls[0]
        self.assertTrue(critic_call["prompt"].startswith(base_prompt))
        self.assertIsNone(critic_call["message_history"])

        self.assertEqual(result, critic_output)


if __name__ == "__main__":
    unittest.main()
