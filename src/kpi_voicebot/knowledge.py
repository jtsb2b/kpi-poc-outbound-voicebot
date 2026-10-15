"""Approved knowledge the LLM may draw on when it words a turn or answers a question.

One Markdown file shared by every campaign (company, the AI caller, what the call can and cannot
do, how to talk on the phone) plus one per campaign (purpose, flow, product or survey, approved
FAQ). They are written from the approved campaign wording and FAQ, never from anywhere else, and
carry no customer data: each call's own values come from the engine's fact sheet.

The text is the same for every call of a campaign, so it sits at the very start of the prompt,
where the gateway can reuse it (prefix caching) instead of reading it again on every turn.
"""

from functools import cache
from importlib import resources

from kpi_voicebot.models import CampaignId


@cache
def knowledge(campaign: CampaignId | str) -> str:
    folder = resources.files("kpi_voicebot.campaigns") / "knowledge"
    parts = [(folder / "common.th.md").read_text("utf-8"), (folder / f"{campaign}.th.md").read_text("utf-8")]
    text = "\n\n".join(p.strip() for p in parts)
    if not text:
        raise RuntimeError(f"knowledge base for {campaign} is empty")
    return text
