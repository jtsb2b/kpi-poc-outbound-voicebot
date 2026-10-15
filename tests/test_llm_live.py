"""Opt-in: scripted scenarios through the real self-hosted LLM. Run with LIVE_LLM=1 (uses quota)."""

import os
from typing import Any

import pytest

from kpi_voicebot.campaigns import get_profile
from kpi_voicebot.config import get_settings
from kpi_voicebot.llm import LLMClient
from kpi_voicebot.llm_interpreter import LLMInterpreter
from kpi_voicebot.simulator import build_engine, get_scenario, run_script
from tests.test_scenarios import RecordingSink, check_expectations

LIVE_SCENARIOS = ["survey_contextual", "pa_human_session", "pa_discrepancy", "pa_callback", "pa_wrong_person"]

pytestmark = pytest.mark.skipif(os.environ.get("LIVE_LLM") != "1", reason="set LIVE_LLM=1 to call the real LLM")


@pytest.mark.parametrize("scenario_id", LIVE_SCENARIOS)
async def test_scenario_with_live_llm(scenario_id: str) -> None:
    scenario: Any = get_scenario(scenario_id)
    profile = get_profile(scenario.profile)
    assert profile is not None
    engine = build_engine(scenario.campaign, profile.case, "สมชาย ใจดี")
    client = LLMClient(get_settings())
    try:
        interpreter = LLMInterpreter(client)
        sink = RecordingSink()
        await run_script(engine, scenario.customer, sink, interpreter=interpreter)
    finally:
        await client.aclose()
    check_expectations(scenario, engine, sink)
