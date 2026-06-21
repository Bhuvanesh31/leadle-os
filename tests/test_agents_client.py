import pytest

from dashboard.agents._client import validate_no_hallucinated_numbers


def test_validator_passes_when_all_numbers_in_input():
    input_text = "5 rotting deals worth $19,500, 73 stalled leads"
    output_text = "5 deals stalling, $19.5K at risk, 73 leads waiting"
    # Should pass — every output number ($19.5K → 19500) appears in input.
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


def test_validator_rejects_hallucinated_number():
    input_text = "5 rotting deals worth $19,500"
    output_text = "5 deals worth $25,000 at risk"
    # 25000 is not in input
    assert validate_no_hallucinated_numbers(input_text, output_text) is False


def test_validator_accepts_paraphrased_with_same_value():
    input_text = "Pipeline coverage is 0.52x"
    output_text = "Coverage at 0.52x — well below target"
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


def test_validator_normalizes_k_suffix():
    input_text = "$19500"
    output_text = "$19.5K is at risk"
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


def test_validator_normalizes_commas():
    input_text = "12000 in revenue"
    output_text = "$12,000 in revenue"
    assert validate_no_hallucinated_numbers(input_text, output_text) is True


from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from dashboard.agents._client import run_agent  # noqa: E402


@pytest.mark.asyncio
async def test_run_agent_returns_parsed_on_clean_response():
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text='{"headline": "ok", "value": 5}')]
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    out = await run_agent(
        model="claude-sonnet-4-5",
        role_prompt="Return JSON.",
        json_schema_description="{headline: str, value: int}",
        input_payload={"value": 5},
        fallback_factory=lambda p: {"headline": "fallback"},
        client=mock_client,
    )
    assert out["degraded"] is False
    assert out["headline"] == "ok"


@pytest.mark.asyncio
async def test_run_agent_falls_back_on_hallucinated_number():
    mock_client = MagicMock()
    mock_msg = MagicMock()
    # Output number 999 not in input (input has 5)
    mock_msg.content = [MagicMock(text='{"headline": "999 rotting deals"}')]
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    out = await run_agent(
        model="claude-sonnet-4-5",
        role_prompt="Return JSON.",
        json_schema_description="{headline: str}",
        input_payload={"rotting_deals": 5},
        fallback_factory=lambda p: {"headline": "fallback"},
        client=mock_client,
    )
    assert out["degraded"] is True
    assert out["headline"] == "fallback"
