"""The drafting failover chain.

This is the part the OpenCode harness could not do. There, a provider failure
arrived as text inside a subprocess's log while the process itself exited 0, so
`runDrafter()` declared success before it ever looked; the chain below it -
key rotation, the Zen fallback, NIM - was unreachable in practice. Two live
runs on 2026-08-06 died that way, one on a 502 and one on a 504, each after
200-310 seconds, each having made no tool calls at all.

Here a provider failure is an exception with a status code, classified once and
acted on. The important consequence is not tidier code: because the chain lives
*inside* the conversation, a provider that dies on turn four rotates and the run
continues from turn four, instead of losing the whole draft.

Rotation policy, refining the rule recorded in advocate-data's apply-send-loop.md
("rotation fires on 429 and on nothing else"). That rule was right about its
target - a bad key or a wrong model id fails identically on all seven, so
rotating would turn one clear failure into seven slow ones and bury the reason.
It did not have a case for what actually happened:

  - rate limited (429, quota, resource exhausted) -> rotate to the next key. Per
    key allowance, exactly as decided.
  - transient upstream (5xx, timeouts, provider_unavailable) -> retry once on the
    same key, then advance to the next tier. Both failures seen on 2026-08-06
    were NVIDIA-side capacity, not per-key: `Worker local total request limit
    reached (33/32)` and `Upstream idle timeout exceeded`. Rotating keys against
    a saturated upstream just spends the pool to hit the same wall.
  - auth, unknown model, bad request (401/403/404/400) -> abandon the tier
    immediately without touching another key. This is the case Alp's rule was
    protecting, and it is preserved exactly.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, BaseMessage

# Free-tier OpenRouter measured 53s for a four-turn tool loop on 2026-08-06.
# A single turn taking more than this is a stuck upstream, not a slow model.
TURN_TIMEOUT_SECONDS = 300

RATE_LIMITED = re.compile(
    r"\b429\b|rate[ _-]?limit|too many requests|resource[ _-]?exhausted|quota", re.I
)
FATAL_FOR_TIER = re.compile(
    r"\b40[0134]\b|unauthori[sz]ed|invalid[ _-]api[ _-]key|no such model|unknown model|"
    r"model[ _-]not[ _-]found|insufficient credits",
    re.I,
)


@dataclass(frozen=True)
class Tier:
    """One rung of the chain: a provider, a model, and the keys to try on it."""

    id: str
    model: str
    keys: tuple[str, ...]
    base_url: str = "https://openrouter.ai/api/v1"


def openrouter_keys() -> tuple[str, ...]:
    """The seven keys, in a fixed order so a rotation cursor means the same thing twice."""
    keys = []
    first = os.environ.get("OPENROUTER_API_KEY")
    if first:
        keys.append(first)
    for i in range(2, 8):
        key = os.environ.get(f"OPENROUTER_API_KEY_{i}")
        if key:
            keys.append(key)
    return tuple(keys)


def default_chain() -> list[Tier]:
    """Smartest first. A tier is only reached when the one above cannot produce a turn.

    Nemotron 3 Ultra leads on measured evidence rather than reputation: it drove a
    four-turn file-tool loop correctly in 53s on OpenRouter, and its free route
    carries a 1M context - larger than the paid one - so the whole dossier fits.
    minimax-m3 is the standing alternative recorded from the 2026-08-06 probe,
    where it was clean on the German grounding task with the best idiom of the
    field, and it is a genuinely different model rather than another route to the
    same upstream that failed today.
    """
    keys = openrouter_keys()
    return [
        Tier("openrouter", os.environ.get(
            "ADVOCATE_DRAFT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"), keys),
        Tier("openrouter-alt", os.environ.get(
            "ADVOCATE_DRAFT_MODEL_ALT", "minimax/minimax-m3:free"), keys),
    ]


@dataclass
class ChainedChat:
    """A chat model that walks the chain on failure and reports what it walked.

    Deliberately not a LangChain Runnable with `.with_fallbacks()`. That would
    handle tier fallback but not per-key rotation inside a tier, and it would not
    give the loop the attempt log, which is the thing whose absence made the
    previous harness's failures invisible.
    """

    tiers: list[Tier]
    temperature: float = 0.2
    attempts: list[str] = field(default_factory=list)
    cursor: int = 0
    _tools: list = field(default_factory=list)

    def bind_tools(self, tools: list) -> "ChainedChat":
        self._tools = tools
        return self

    def _client(self, tier: Tier, key: str | None) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=tier.model,
            temperature=self.temperature,
            base_url=tier.base_url,
            api_key=key or "unset",
            timeout=TURN_TIMEOUT_SECONDS,
            max_retries=0,  # retries are this class's job, and they are classified
        )
        return model.bind_tools(self._tools) if self._tools else model

    def invoke(self, messages: list[AnyMessage]) -> BaseMessage:
        """One assistant turn, or an exception once every tier is spent."""
        last_error: Exception | None = None

        for tier in self.tiers:
            keys: tuple[str | None, ...] = tier.keys or (None,)
            rotations = 0
            retried_transient = False

            while rotations < len(keys):
                index = (self.cursor + rotations) % len(keys)
                label = f"{tier.id}[key {index + 1}/{len(keys)}] {tier.model}"
                try:
                    reply = self._client(tier, keys[index]).invoke(messages)
                except Exception as exc:  # noqa: BLE001 - classified immediately below
                    text = f"{exc}"
                    last_error = exc

                    if FATAL_FOR_TIER.search(text):
                        self.attempts.append(f"{label}: fatal for this tier ({text[:160]})")
                        break

                    if RATE_LIMITED.search(text):
                        self.attempts.append(f"{label}: rate limited, rotating key")
                        rotations += 1
                        continue

                    if not retried_transient:
                        # One retry, because the two failures seen on 2026-08-06
                        # were momentary upstream capacity. A short pause, since
                        # retrying a saturated worker instantly just fails again.
                        retried_transient = True
                        self.attempts.append(f"{label}: transient ({text[:160]}), retrying once")
                        time.sleep(5)
                        continue

                    self.attempts.append(f"{label}: transient again ({text[:160]}), next tier")
                    break

                # Success. Stick to this key: the pool is consumed in order rather
                # than round-robined onto keys whose daily allowance is spent.
                self.cursor = index
                if rotations or retried_transient:
                    self.attempts.append(f"{label}: ok after fallback")
                return reply

        raise RuntimeError(
            "every tier in the drafting chain failed: " + "; ".join(self.attempts)
        ) from last_error
