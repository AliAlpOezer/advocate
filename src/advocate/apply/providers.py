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
import queue
import re
import threading
import time
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, BaseMessage

# Free-tier OpenRouter measured 53s for a four-turn tool loop on 2026-08-06, but
# those turns were a few hundred bytes each. The two drafting stages emit a whole
# document body - roughly 5k tokens - so the bound has to cover generation at a
# free route's throughput, not just a handshake. 900s is about 6 tokens/second:
# generous enough not to kill a slow but working draft, tight enough that a stage
# gives up long before the driver kills the whole run.
TURN_TIMEOUT_SECONDS = int(os.environ.get("ADVOCATE_TURN_TIMEOUT_SECONDS", "900"))

# Both drafting models are reasoning models and both declare `reasoning` in their
# supported parameters, so effort is a lever available here. It is **off by
# default**: the run that first drafted an application end to end ran at the
# provider's default, and grounding against a 330-line dossier is the one thing
# worth spending latency on. `minimal` is the knob to reach for if turn latency
# becomes the binding constraint - the 2026-08-06 OpenCode probe ran it (as
# `--variant minimal`) and grounding held, but that was a three-claim toy.
REASONING_EFFORT = os.environ.get("ADVOCATE_REASONING_EFFORT", "")


def _call_with_deadline(call, seconds: int):
    """Run `call` on a daemon thread and give up on it after `seconds`.

    `ChatOpenAI(timeout=...)` is not a wall-clock bound on this route. Measured
    2026-08-07: a drafting turn ran past 20 minutes against a client configured
    for 600s, and the run the day before spent 53,893 seconds without a single
    turn completing. An HTTP read timeout is reset by anything arriving on the
    socket, so a provider that trickles or keeps the connection alive while it
    thinks is never late by that definition - and the only remaining bound was
    the driver killing the whole subprocess, which loses every stage at once.

    The thread is abandoned rather than cancelled, because a blocking socket read
    cannot be interrupted from outside. It is a daemon, so it cannot hold the
    process open, and the run is a oneshot: one leaked thread costs a socket for
    the rest of a run that is already failing over.
    """
    box: queue.Queue = queue.Queue(maxsize=1)

    def work() -> None:
        try:
            box.put(("ok", call()))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            box.put(("error", exc))

    threading.Thread(target=work, daemon=True).start()
    try:
        kind, value = box.get(timeout=seconds)
    except queue.Empty:
        raise TimeoutError(
            f"no reply after {seconds}s (the client's own timeout does not bound this)"
        ) from None
    if kind == "error":
        raise value
    return value


RATE_LIMITED = re.compile(
    r"\b429\b|rate[ _-]?limit|too many requests|resource[ _-]?exhausted|quota", re.I
)
FATAL_FOR_TIER = re.compile(
    r"\b40[0134]\b|unauthori[sz]ed|invalid[ _-]api[ _-]key|no such model|unknown model|"
    r"model[ _-]not[ _-]found|insufficient credits",
    re.I,
)


ANTHROPIC_MODEL = os.environ.get("ADVOCATE_ESCALATION_MODEL", "claude-opus-5")


@dataclass(frozen=True)
class Tier:
    """One rung of the chain: a provider, a model, and the keys to try on it."""

    id: str
    model: str
    keys: tuple[str, ...]
    base_url: str = "https://openrouter.ai/api/v1"
    # Which client to build. "openrouter" is the OpenAI-compatible route every
    # free tier uses; "anthropic" is the paid escalation rung and is a different
    # SDK, a different message shape and a different billing model, so it is
    # named rather than inferred from the base_url.
    provider: str = "openrouter"


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


def openrouter_tier(model: str) -> Tier:
    """One OpenRouter rung on `model`, sharing the same key pool as the rest."""
    return Tier("openrouter-stage", model, openrouter_keys())


def preferred_tier(model: str) -> Tier:
    """The rung a stage's own `model` runs on - OpenRouter unless told otherwise.

    A stage preference used to imply OpenRouter, because that is where every free
    route lives. `deepseek-v4-pro` broke that assumption: it is reached through
    Alibaba Model Studio's OpenAI-compatible endpoint with its own key, and
    routing it to OpenRouter would send a model id that host has never heard of.

    The endpoint is named explicitly rather than inferred from the model id. The
    tempting discriminator - OpenRouter ids contain a `/` and Alibaba's do not -
    is exactly the kind of silent inference this pipeline has been burned by
    before: it works until a vendor ships an id shaped the other way, and then it
    fails as a confusing 404 rather than as a misconfiguration. These two names
    mirror `probe_claims_request.py`'s `--base-url` and `--key-env` on purpose, so
    the route that was measured is literally the route that gets deployed.

    Both variables must be set together. Setting only one is a misconfiguration
    that would otherwise degrade into "silently used OpenRouter instead", so it
    raises.
    """
    base_url = os.environ.get("ADVOCATE_STAGE_BASE_URL", "").strip()
    key_env = os.environ.get("ADVOCATE_STAGE_KEY_ENV", "").strip()
    if not base_url and not key_env:
        return openrouter_tier(model)
    if not (base_url and key_env):
        raise RuntimeError(
            "ADVOCATE_STAGE_BASE_URL and ADVOCATE_STAGE_KEY_ENV must be set together; "
            f"got base_url={base_url!r} key_env={key_env!r}"
        )
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise RuntimeError(
            f"ADVOCATE_STAGE_KEY_ENV names {key_env!r}, but that variable is empty or unset"
        )
    return Tier("stage-endpoint", model, (key,), base_url=base_url)


def anthropic_tier() -> Tier | None:
    """The escalation rung, or None when there is no key to reach it with.

    Returning None rather than raising is deliberate: a missing Anthropic key
    should degrade a revision to "redrafted on the free chain", which is worse
    than asked for but still an application. Refusing to run would leave the
    record stuck at a tier nothing can serve.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    return Tier("anthropic", ANTHROPIC_MODEL, (key,), base_url="", provider="anthropic")


def default_chain(escalate: int = 0) -> list[Tier]:
    """Smartest first. A tier is only reached when the one above cannot produce a turn.

    Nemotron 3 Ultra leads on measured evidence rather than reputation: it drove a
    four-turn file-tool loop correctly in 53s on OpenRouter, and its free route
    carries a 1M context - larger than the paid one - so the whole dossier fits.
    Set `ADVOCATE_DRAFT_MODEL` to the same id without `:free` to run it paid; that
    is the intended move once OpenRouter credit exists, and nothing else changes.

    **The second tier is no longer minimax.** `minimax/minimax-m3:free` was the
    standing alternative from the 2026-08-06 probe, and on 2026-08-07 it answered
    404: "This model is unavailable for free. The paid version is available now."
    OpenRouter's catalogue has no free minimax variant at all any more, so the
    fallback was a dead id the chain could only discover by spending a tier on it.

    Its replacement is the largest free model left that declares tool support and
    holds the ~25k-token preloaded corpus with room to work. It is the same family
    as tier 1, which costs the "genuinely different model" property minimax had -
    a shared upstream can fail for both. That is accepted rather than solved: the
    alternatives are materially smaller, and this fallback exists to survive a rate
    limit, not to be a second opinion on German prose.

    **`escalate > 0` puts the paid Anthropic rung on top**, which is what Alp
    taps Revise for. It is deliberately *only* reachable that way:

      - It is metered API billing, not the subscription that funds everything
        else here, so it must never be arrived at by accident.
      - It must not be a fallback for a provider error. A 502 from NVIDIA means
        retry the free chain, not spend money - the failure has nothing to do
        with the model's ability and everything to do with someone's capacity.
        So it is prepended to the chain rather than appended to it: a run that
        starts on Anthropic can fall back to free, and a run that starts free
        can never fall *up*.

    The free rungs stay underneath even on an escalated run, which is what makes
    a missing or exhausted Anthropic key degrade to a worse draft rather than to
    no draft.
    """
    keys = openrouter_keys()
    free = [
        Tier("openrouter", os.environ.get(
            "ADVOCATE_DRAFT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"), keys),
        Tier("openrouter-alt", os.environ.get(
            "ADVOCATE_DRAFT_MODEL_ALT", "nvidia/nemotron-3-super-120b-a12b:free"), keys),
    ]
    if escalate <= 0:
        return free
    paid = anthropic_tier()
    return ([paid] if paid else []) + free


def _cacheable(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Mark the system prompt as a cache breakpoint, for Anthropic rungs only.

    The preloaded corpus - SKILL.md, the dossier, claims.yaml - is about 85 KB,
    it is byte-identical on every turn of a stage and identical again across
    every application, and each turn re-sends all of it. Cached reads are a small
    fraction of the input price, so on the paid rung this is the difference
    between paying for the dossier once per stage and paying for it once per
    turn.

    Two properties make it work, and both are properties of *where* the marker
    goes rather than of the marker itself. Caching is a prefix match, so the
    stable bytes have to come first and everything volatile - the stage's task,
    the revision reason, the conversation so far - has to come after the
    breakpoint. That is exactly the message order the pipeline already builds, so
    the only thing needed here is to mark the boundary.

    Deliberately the default 5-minute TTL and no beta headers. A 1-hour TTL costs
    a larger write premium and would need one; the win being captured is the
    within-stage one, where turns are seconds apart. If a stage ever routinely
    idles longer than that between turns, the TTL is the lever - measure first.

    Non-system messages pass through untouched, and a system message that is
    already in block form is left alone rather than rewritten.
    """
    from langchain_core.messages import SystemMessage

    out: list[AnyMessage] = []
    marked = False
    for message in messages:
        if not marked and isinstance(message, SystemMessage) and isinstance(message.content, str):
            out.append(
                SystemMessage(
                    content=[
                        {
                            "type": "text",
                            "text": message.content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                )
            )
            marked = True
            continue
        out.append(message)
    return out


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
        """The default tool set. Stages pass their own to `invoke` instead."""
        self._tools = tools
        return self

    def _client(self, tier: Tier, key: str | None, tools: list) -> BaseChatModel:
        if tier.provider == "anthropic":
            return self._anthropic_client(tier, key, tools)

        from langchain_openai import ChatOpenAI

        effort = REASONING_EFFORT
        model = ChatOpenAI(
            model=tier.model,
            temperature=self.temperature,
            base_url=tier.base_url,
            api_key=key or "unset",
            timeout=TURN_TIMEOUT_SECONDS,
            max_retries=0,  # retries are this class's job, and they are classified
            # OpenRouter's own shape, passed through rather than translated, so
            # what is sent is what its docs describe. Both drafting models declare
            # `reasoning` in supported_parameters.
            extra_body={"reasoning": {"effort": effort}} if effort else {},
        )
        return model.bind_tools(tools) if tools else model

    def _anthropic_client(self, tier: Tier, key: str | None, tools: list) -> BaseChatModel:
        """The escalation rung. Three things here are deliberate and easy to undo by accident.

        **No `temperature`.** Opus 5 rejects it, along with `top_p` and `top_k`,
        with a 400. `ChainedChat.temperature` exists for the OpenRouter rungs and
        is simply not forwarded here.

        **No `thinking` and no effort parameter.** On Opus 5 thinking is on by
        default and effort defaults to `high`, so the configuration Alp asked for
        - Opus 5, high effort - is the one you get by passing neither. That is
        also why nothing here guesses at the shape of an effort argument: the
        only reason to add one later is to reach `xhigh`, and that is worth
        verifying against the installed client rather than assuming.

        **`max_tokens` is generous.** A drafting stage emits a whole document
        body, and this ceiling covers thinking *and* the answer together - a
        limit sized for the answer alone truncates mid-document, which reads as
        a bad draft rather than as a configuration mistake.
        """
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(
            model=tier.model,
            api_key=key,
            max_tokens=16000,
            timeout=TURN_TIMEOUT_SECONDS,
            max_retries=0,  # classified and retried here, same as the other rungs
        )
        return model.bind_tools(tools) if tools else model

    def _chain_for(self, prefer: str | None) -> list[Tier]:
        """The chain for one call, with a stage's own route in front of the free rungs.

        `prefer` exists because the pipeline's stages are not interchangeable
        workloads and measurement said so. On 2026-08-08 the `claims` request was
        replayed against tier 1 twelve times: 0 of 6 produced a usable turn at
        full size, one reply truncated mid-JSON at 12,265 characters while
        delivering a large tool-call argument, and the same request without tools
        completed normally at 8,462 tokens. The route can generate the content and
        cannot deliver it through a tool call, and no request-level lever moved it
        - not reasoning effort, not disabling reasoning, not a reasoning cap, not
        dropping a document, not cutting the tool set.

        Order matters twice here:

          - **An escalation still wins.** A paid rung is only ever reached because
            Alp tapped Revise, and a stage preference must not displace what he
            asked and paid for.
          - **The standard free chain stays underneath.** The preference is a
            better first guess for this one stage, not a claim that it is more
            reliable, so a stage whose own route is rate limited still falls back
            to the chain every other stage uses rather than failing outright.
        """
        if not prefer:
            return self.tiers
        paid = [t for t in self.tiers if t.provider == "anthropic"]
        free = [t for t in self.tiers if t.provider != "anthropic"]
        return paid + [preferred_tier(prefer)] + [t for t in free if t.model != prefer]

    def invoke(self, messages: list[AnyMessage], tools: list | None = None,
               prefer: str | None = None) -> BaseMessage:
        """One assistant turn, or an exception once every tier is spent.

        `tools` is per call rather than bound once, because each stage of the
        pipeline offers a different set - the stage that writes the CV has no way
        to write the cover letter, and that is enforced by what it is handed.

        `prefer` names a model to try ahead of the free chain for this call; see
        `_chain_for`.

        **There is deliberately no `tool_choice` here.** Forcing the call was tried
        and is measurably harmful on this model - see the note in `graph.py`.
        """
        bound = self._tools if tools is None else tools
        last_error: Exception | None = None

        for tier in self._chain_for(prefer):
            keys: tuple[str | None, ...] = tier.keys or (None,)
            rotations = 0
            retried_transient = False

            while rotations < len(keys):
                index = (self.cursor + rotations) % len(keys)
                label = f"{tier.id}[key {index + 1}/{len(keys)}] {tier.model}"
                try:
                    client = self._client(tier, keys[index], bound)
                    payload = _cacheable(messages) if tier.provider == "anthropic" else messages
                    reply = _call_with_deadline(
                        lambda: client.invoke(payload), TURN_TIMEOUT_SECONDS
                    )
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

                # A 200 response is not a turn. Measured 2026-08-07 by replaying
                # the claims stage's exact request: `finish_reason: "error"`,
                # 2,464 completion tokens all of them reasoning, no content and no
                # tool call - an upstream failure delivered inside a successful
                # HTTP response. Accepting it burned five turns a run and looked
                # exactly like a model refusing to work, which is the same shape
                # of bug as OpenCode exiting 0 on a stream error. It is a provider
                # failure and is classified as one, so the chain falls over
                # instead of nudging a model that never got the request.
                finish = (getattr(reply, "response_metadata", None) or {}).get("finish_reason")
                usable = bool(getattr(reply, "tool_calls", None)) or bool(
                    str(getattr(reply, "content", "") or "").strip()
                )
                if finish == "error" or not usable:
                    last_error = RuntimeError(
                        f"unusable reply: finish_reason={finish!r}, no content and no tool call"
                    )
                    if not retried_transient:
                        retried_transient = True
                        self.attempts.append(f"{label}: {last_error}, retrying once")
                        time.sleep(5)
                        continue
                    self.attempts.append(f"{label}: {last_error} again, next tier")
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
