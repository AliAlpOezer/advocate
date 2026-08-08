"""Settle one question: is `finish_reason='error'` per-key or upstream?

    py scripts/probe_key_rotation.py            # tier-1 model, all keys
    py scripts/probe_key_rotation.py --alt      # tier-2 model instead

Why this exists. `providers.py` rotates keys on 429 and on nothing else, and
that is deliberate: 5xx and timeouts advance the *tier* instead, because
"rotating keys against a saturated upstream just spends the pool to hit the same
wall". `finish_reason='error'` arrives as an HTTP 200 with a bad body, so it
lands in that middle bucket - and on 2026-08-07 the BMW draft died there having
tried key 1 of 7 on each of two tiers and no other key.

So the fix depends on a fact nobody has measured. If key 2 succeeds where key 1
returned `finish_reason='error'`, the failure is per-key and rotation is right.
If every key fails identically, the failure is NVIDIA-side capacity, the current
policy is correct, and the real fix is a different tier-1 model or the paid rung
- in which case "try all seven keys" would have made the drafter slower without
making it work.

Sends ONE short request per key, sequentially. Deliberately not concurrent: the
hypothesis under test is upstream saturation, and seven parallel requests would
manufacture exactly that.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://openrouter.ai/api/v1/chat/completions"
TIER1 = os.environ.get("ADVOCATE_DRAFT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
TIER2 = os.environ.get("ADVOCATE_DRAFT_MODEL_ALT", "nvidia/nemotron-3-super-120b-a12b:free")


def keys() -> list[tuple[str, str]]:
    """Same order and same names as providers.openrouter_keys(), so key N here is key N there."""
    found = []
    if os.environ.get("OPENROUTER_API_KEY"):
        found.append(("OPENROUTER_API_KEY", os.environ["OPENROUTER_API_KEY"]))
    for i in range(2, 8):
        name = f"OPENROUTER_API_KEY_{i}"
        if os.environ.get(name):
            found.append((name, os.environ[name]))
    return found


def probe(model: str, key: str) -> str:
    """One request. Returns a short verdict string for this key."""
    body = json.dumps({
        "model": model,
        # Short and trivial on purpose: a long generation has more ways to fail
        # and would blur the per-key/upstream distinction this is measuring.
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
        "max_tokens": 16,
    }).encode()
    req = urllib.request.Request(
        BASE, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as err:
        return f"HTTP {err.code}"
    except Exception as err:  # noqa: BLE001 - a probe reports, it does not raise
        return f"{type(err).__name__}: {err}"

    choice = (payload.get("choices") or [{}])[0]
    finish = choice.get("finish_reason")
    content = (choice.get("message") or {}).get("content") or ""
    if finish == "error":
        return "finish_reason=error"
    if not content.strip():
        return f"empty content (finish_reason={finish})"
    return f"OK ({content.strip()[:20]!r})"


def main() -> int:
    model = TIER2 if "--alt" in sys.argv else TIER1
    found = keys()
    if not found:
        print("No OPENROUTER_API_KEY* in the environment. On the box: "
              "set -a; . /etc/advocate-apply/daemon.env; set +a")
        return 2

    print(f"model : {model}\nkeys  : {len(found)}\n")
    results = []
    for n, (name, key) in enumerate(found, start=1):
        verdict = probe(model, key)
        results.append(verdict)
        print(f"  key {n}/{len(found)} ({name}): {verdict}")

    ok = [r for r in results if r.startswith("OK")]
    print()
    if ok and len(ok) < len(results):
        print("PER-KEY. Some keys work where others do not, so rotating on "
              "finish_reason='error' is the right fix - exhaust the keys inside a "
              "tier before dropping to the next.")
    elif not ok:
        print("UPSTREAM. Every key fails the same way, so the current policy is "
              "correct and rotating would only spend the pool. The fix is a "
              "different tier-1 model or the paid rung, NOT more keys.")
    else:
        print("INCONCLUSIVE - every key succeeded, so the failure was not "
              "reproduced. Re-run when the drafter is actually failing; a probe "
              "that cannot see the bug cannot classify it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
