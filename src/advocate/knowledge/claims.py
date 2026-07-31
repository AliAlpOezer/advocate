"""The claim store: every factual sentence a generated document may contain.

The system's one architectural constraint is that the generator never writes
facts - it selects claim IDs and writes connective prose around them. This
module defines what a claim is, which makes that constraint checkable instead
of aspirational.

Two things here differ deliberately from `docs/context/advocate-system-concept.md`,
because reading the real dossier showed the sketched schema could not express it:

1.  **No `text_de` / `text_en` on the claim.** Every language-specific rendering
    lives in `Phrasing`, including the forbidden ones. The dossier is full of
    rules like "say 'familiar with', not 'read'" and "never write 'Travelling
    Salesman Problem'" which attach to claims that *are* assertable - a
    `never_claim` flag cannot express them, and a free-text field invites the
    drafter to paraphrase its way around them. One mechanism, not two.

2.  **`verification` is separate from `grade`.** How well evidenced a claim is
    and where the evidence came from are independent. "Top 5 state high school"
    is self-reported with no ranking body yet usable; scikit-learn is
    well-documented coursework that must never be presented as experience.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

CLAIM_ID = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")


class Grade(StrEnum):
    """How strong the evidence is. Drives whether a claim may be asserted at all."""

    STRONG = "strong"
    MODERATE = "moderate"
    COURSEWORK = "coursework"
    #: Never assert, under any circumstance. Azure, Kubernetes, "5 years of DS".
    GAP = "gap"
    #: Not checkable, so not graded - dossier section 10. May colour tone only.
    UNGRADED = "ungraded"


class Verification(StrEnum):
    """Where the evidence came from. Orthogonal to `Grade`."""

    #: Read out of source code, git history or a repository on disk.
    SOURCE_VERIFIED = "source_verified"
    #: A degree certificate, award, transcript or published record.
    DOCUMENT_VERIFIED = "document_verified"
    #: Alp's own account, elicited in interview. Real, but uncorroborated.
    SELF_REPORTED = "self_reported"


class Kind(StrEnum):
    PERSONAL = "personal"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    PROJECT = "project"
    SKILL = "skill"
    ACHIEVEMENT = "achievement"
    CERTIFICATION = "certification"
    #: How to position him - the argument, not the fact. Dossier section 8.
    POSITIONING = "positioning"
    #: Character and motivation. Dossier section 10 - ungraded by default.
    DISPOSITION = "disposition"


class Surface(StrEnum):
    """Which document a claim may appear in.

    The dossier is explicit that this is not uniform: section 10 material "may
    never appear in a CV as a skill" but may inform a cover letter's tone, and
    coursework-graded skills "never in a core-skills line".
    """

    CV = "cv"
    COVER_LETTER = "cover_letter"
    PROJECT_LIST = "project_list"
    #: Safe to say out loud if asked, but not to write unprompted.
    INTERVIEW = "interview"
    #: May influence register and word choice. May never be asserted.
    TONE = "tone"


class PhrasingKind(StrEnum):
    #: Must be used verbatim when this claim is asserted.
    REQUIRED = "required"
    #: The curated wording. Drafter should use it; deviation is allowed.
    PREFERRED = "preferred"
    #: Must never appear in any document, whether or not the claim is cited.
    FORBIDDEN = "forbidden"


class Status(StrEnum):
    ACTIVE = "active"
    #: Kept on purpose. A withdrawn claim records a conclusion that was reached
    #: and then refuted, so nothing re-derives it. Same job as decisions.md.
    WITHDRAWN = "withdrawn"


class Metric(BaseModel):
    """A number that must survive drafting unchanged.

    `value` is a string, not a float, because the dossier's real metrics are
    "3,156", "1.7", "35/35", "~4,800" and "3 years 4 months". Keeping the
    curated literal is what lets the grounding check assert that every number in
    a drafted sentence appears verbatim in a cited claim.
    """

    key: str
    value: str
    unit: str | None = None
    approximate: bool = False
    note: str | None = None


class Phrasing(BaseModel):
    """A language-specific rule about how a claim may or may not be written.

    A phrasing with no `claim_id` is a global rule: forbidden wording that must
    not appear in any document regardless of which claims were cited.
    """

    claim_id: str | None = None
    lang: str = Field(pattern="^(de|en)$")
    kind: PhrasingKind
    text: str
    reason: str | None = None


class Claim(BaseModel):
    id: str
    kind: Kind
    grade: Grade
    verification: Verification
    status: Status = Status.ACTIVE

    #: What the claim is, in English, for a human or model to read. Never copied
    #: into a document verbatim - that is what `Phrasing` is for.
    statement: str

    #: Which documents this may appear in. Required, with no default: an
    #: unstated surface would silently mean "anywhere".
    surfaces: list[Surface]

    tags: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)

    #: Empty means universally applicable. A non-empty list restricts the claim
    #: to those employers - dossier section 8b exists solely because SSI-specific
    #: reasoning must not transfer to an unrelated AI/ML application.
    audience_scope: list[str] = Field(default_factory=list)

    #: Claim IDs that must be cited alongside this one. Dossier section 10.3:
    #: the fast-learning claim may be made only "paired with at least two" of
    #: three named artifacts, because unpaired it carries no information.
    requires_claims: list[str] = Field(default_factory=list)
    min_supporting: int | None = None

    period_start: date | None = None
    period_end: date | None = None

    #: Where the evidence lives - a repo path, a file, "elicited 2026-07-29".
    source: str | None = None
    verified_at: date | None = None

    #: Claim IDs this replaces. The superseded rows stay, marked WITHDRAWN.
    supersedes: list[str] = Field(default_factory=list)
    note: str | None = None

    @field_validator("id")
    @classmethod
    def _dotted_slug(cls, v: str) -> str:
        if not CLAIM_ID.match(v):
            raise ValueError(f"claim id must be a dotted lowercase slug, got {v!r}")
        return v

    @model_validator(mode="after")
    def _gap_is_never_assertable(self) -> Claim:
        if self.grade is Grade.GAP and self.surfaces:
            raise ValueError(
                f"{self.id}: a gap-graded claim must have no surfaces - it may "
                "never be asserted. Record the forbidden wording as a FORBIDDEN "
                "phrasing instead."
            )
        if self.grade is Grade.UNGRADED and set(self.surfaces) - {Surface.TONE, Surface.INTERVIEW}:
            raise ValueError(
                f"{self.id}: ungraded material is not checkable, so it may only "
                "reach TONE or INTERVIEW surfaces."
            )
        return self

    @model_validator(mode="after")
    def _pairing_is_satisfiable(self) -> Claim:
        if self.min_supporting is not None:
            if not self.requires_claims:
                raise ValueError(f"{self.id}: min_supporting set with no requires_claims")
            if self.min_supporting > len(self.requires_claims):
                raise ValueError(
                    f"{self.id}: min_supporting={self.min_supporting} exceeds the "
                    f"{len(self.requires_claims)} supporting claims listed"
                )
        return self
