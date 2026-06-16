"""Job-market data layer — PUBLIC sources only. No login, no credentials, EVER.

Ported from the verified TS sources.ts.
No proxy/UA rotation, no CAPTCHA solving. On 429/999 we back off, never evade.
Each source function is what a per-source graph node calls — the node sees only
its own raw HTML/JSON, keeping the orchestrator's context clean.
"""

from __future__ import annotations

import html
import re
import time

import httpx
from pydantic import BaseModel

UA = {"User-Agent": "personal-job-research"}
_TIMEOUT = httpx.Timeout(20.0)


class Job(BaseModel):
    source: str
    job_id: str | None = None
    title: str
    company: str = ""
    location: str = ""
    remote: bool | None = None
    tags: list[str] = []
    url: str | None = None


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def fetch_arbeitnow() -> list[Job]:
    with httpx.Client(timeout=_TIMEOUT) as c:
        res = c.get("https://www.arbeitnow.com/api/job-board-api")
        res.raise_for_status()
        data = res.json().get("data", [])
    return [
        Job(
            source="arbeitnow",
            title=j.get("title", ""),
            company=j.get("company_name", ""),
            location=j.get("location", ""),
            remote=j.get("remote"),
            tags=j.get("tags") or [],
            url=j.get("url"),
        )
        for j in data
    ]


def _parse_linkedin_cards(html_text: str) -> list[Job]:
    cards: list[Job] = []
    for b in re.split(r"<li[\s>]", html_text)[1:]:
        job_id = (re.search(r'data-entity-urn="urn:li:jobPosting:(\d+)"', b) or [None, None])[1]
        title = (re.search(r'base-search-card__title"[^>]*>(.*?)<\/', b, re.S) or [None, None])[1]
        company = (re.search(r'base-search-card__subtitle".*?>(.*?)<\/', b, re.S) or [None, None])[1]
        location = (re.search(r'job-search-card__location"[^>]*>(.*?)<\/', b, re.S) or [None, None])[1]
        if job_id or title:
            cards.append(
                Job(
                    source="linkedin-guest",
                    job_id=job_id,
                    title=_clean(title),
                    company=_clean(company),
                    location=_clean(location),
                    url=f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else None,
                )
            )
    return cards


def search_linkedin_guest(keywords: str, location: str, geo_id: str, pages: int = 1) -> list[Job]:
    out: list[Job] = []
    with httpx.Client(timeout=_TIMEOUT, headers=UA) as c:
        for p in range(pages):
            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                f"keywords={httpx.QueryParams({'k': keywords})['k']}"
                f"&location={httpx.QueryParams({'k': location})['k']}"
                + (f"&geoId={geo_id}" if geo_id else "")
                + f"&start={p * 25}"
            )
            res = c.get(url)
            if res.status_code in (429, 999):
                print(f"⚠️  LinkedIn rate-limited (HTTP {res.status_code}). Backing off — not evading.")
                break
            if res.status_code >= 400:
                print(f"⚠️  LinkedIn HTTP {res.status_code}")
                break
            out.extend(_parse_linkedin_cards(res.text))
            time.sleep(2.5)
    return out


def fetch_description(job_id: str) -> str:
    """Fetch a single posting's description text from the PUBLIC guest endpoint (no auth)."""
    with httpx.Client(timeout=_TIMEOUT, headers=UA) as c:
        res = c.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    if res.status_code >= 400:
        return ""
    m = re.search(r"show-more-less-html__markup[^>]*>(.*?)<\/div>", res.text, re.S)
    return _clean(m.group(1) if m else res.text)[:6000]


def dedupe(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    out: list[Job] = []
    for j in jobs:
        key = f"{j.title.lower()}|{j.company.lower()}"
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


_AIISH = re.compile(r"a\.?i\b|ml\b|machine learning|llm|genai|nlp|data scien", re.I)


def is_aiish(j: Job) -> bool:
    return bool(_AIISH.search(f"{j.title} {' '.join(j.tags)}"))
