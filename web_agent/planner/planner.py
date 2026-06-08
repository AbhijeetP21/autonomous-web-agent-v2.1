"""LLM planner: turn (goal, observation, history) into the next validated action."""

from __future__ import annotations

from pydantic import ValidationError

from web_agent.actions.schema import Decision, parse_decision
from web_agent.llm.base import LLMClient
from web_agent.perception.accessibility import Observation

SYSTEM_PROMPT = """\
You are an autonomous web agent. You are given a high-level GOAL and, at each step, a
reduced view of the current web page: a list of interactive elements, each with a numeric
id, a role, and an accessible name. You do NOT see raw HTML.

Choose exactly ONE next action by calling the `take_action` tool. Rules:
- Reference page elements only by the numeric id shown in the observation.
- Prefer the most direct action that makes progress. Do not repeat an action that already
  failed or had no effect — try a different element or approach instead.
- To enter text, use `type` with the element_id and the text. Set `submit: true` only if
  pressing Enter is needed.
- Call `finish` with success=true once the GOAL is clearly achieved (confirm via the page's
  headings/messages), or success=false if it is impossible. Provide a short summary.
- Use `ask_user` only if you genuinely cannot proceed without information from the user.
- Never navigate to a domain unrelated to the task.
Always include a brief `reasoning` explaining why this action advances the goal.\
"""


def build_user_prompt(
    goal: str, observation: Observation, history: list[str], steps_left: int
) -> str:
    parts = [f"GOAL: {goal}", ""]
    if history:
        parts.append("Actions so far (most recent last):")
        parts.extend(f"  {h}" for h in history[-10:])
        parts.append("")
    parts.append("CURRENT PAGE OBSERVATION:")
    parts.append(observation.to_prompt())
    parts.append("")
    parts.append(f"You have {steps_left} step(s) left in your budget.")
    parts.append("Call take_action with your reasoning and the single next action.")
    return "\n".join(parts)


class Planner:
    def __init__(self, client: LLMClient):
        self.client = client

    async def plan(
        self, goal: str, observation: Observation, history: list[str], steps_left: int
    ) -> Decision:
        user = build_user_prompt(goal, observation, history, steps_left)
        raw = await self.client.propose(SYSTEM_PROMPT, user)
        try:
            return parse_decision(raw)
        except ValidationError as e:
            # One corrective re-ask with the validation error fed back.
            correction = (
                f"\n\nYour previous response was invalid: {e}. "
                "Return a corrected take_action call with all required fields for the chosen type."
            )
            raw2 = await self.client.propose(SYSTEM_PROMPT, user + correction)
            return parse_decision(raw2)
