"""Data structures passed between pipeline stages.

Deliberately plain dataclasses. Every stage takes and returns one of these,
so each stage can be tested, replaced or inspected on its own.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

@dataclass
class ClaimContext:
    """Structured claim data. In production this comes from the carrier's
    policy administration and claims systems. Here it is stubbed from a
    local JSON fixture — see data/policies.json.
    """
    claim_id: str
    loss_date: datetime
    policy_in_force: bool
    coverage_applies: bool
    deductible: float
    injury_reported: bool
    vehicle_count: int
    liability_disputed: bool
    open_siu_flag: bool
    obvious_total_loss: bool
    vehicle_year: int
    vehicle_make: str
    vehicle_model: str
    # True when the reviewer uploaded their own photographs. The mock
    # provider consults this: a script written for a demo claim must not
    # be applied to a photograph it has never seen. Defaulted, so it has to
    # come after every required field.
    user_supplied_photos: bool = False
    # Which submission this is. The mock consults it so a claim can behave
    # differently on a resubmission, which is what the re-request loop is for.
    attempt: int = 1
    # What the policyholder said happened and where, at first notice of loss.
    # It sets the scope of the photo check: the photographs are judged against
    # the reported damage, not against the whole vehicle.
    loss_description: str = ""

    @property
    def vehicle_label(self) -> str:
        return f"{self.vehicle_year} {self.vehicle_make} {self.vehicle_model}"


@dataclass
class Photo:
    """One submitted image, annotated as it moves through the pipeline."""
    filename: str
    path: str

    # Stage 1a: deterministic quality signals
    width: int = 0
    height: int = 0
    sharpness: float = 0.0          # variance of Laplacian, higher is sharper
    brightness: float = 0.0         # mean luminance, 0-255
    quality_issues: list[str] = field(default_factory=list)

    # Stage 1b: authenticity signals
    exif_present: bool = False
    capture_time: Optional[datetime] = None
    device: Optional[str] = None
    editing_software: Optional[str] = None
    c2pa_present: bool = False
    perceptual_hash: str = ""
    authenticity_flags: list[str] = field(default_factory=list)

    @property
    def quality_ok(self) -> bool:
        return not self.quality_issues


# --------------------------------------------------------------------------
# Stage outputs
# --------------------------------------------------------------------------

@dataclass
class LineItem:
    """One row of a repair estimate, in the form the industry already uses."""
    operation: str        # replace | repair | refinish | R&I | blend
    part: str
    panel: str            # maps to the ADAS zone table
    damage_type: str
    severity: str         # light | moderate | heavy
    reasoning: str        # why the model believes this operation is needed
    confidence: float     # 0-1, as reported by the assessment stage
    price: Optional[float] = None
    priced: bool = False  # did the costing stage find a price for this?


@dataclass
class HiddenDamageCandidate:
    """Something history suggests may be behind the visible damage.

    STUBBED: in production this is a retrieval over the carrier's historical
    claims. Here it is a small rules table. The interface is final; only the
    body of comparables.lookup() changes when real data is connected.
    """
    part: str
    rationale: str
    observed_rate: Optional[float] = None   # None while stubbed


@dataclass
class Assessment:
    line_items: list[LineItem] = field(default_factory=list)
    damage_panels: list[str] = field(default_factory=list)
    adas_zones_involved: list[str] = field(default_factory=list)
    hidden_damage: list[HiddenDamageCandidate] = field(default_factory=list)
    model_notes: str = ""

    @property
    def estimate_total(self) -> float:
        return round(sum(li.price or 0.0 for li in self.line_items), 2)


@dataclass
class ConfidenceBreakdown:
    """Composite confidence. Every input is measurable; the combination is
    deterministic arithmetic so it is auditable and tunable by the carrier.
    """
    evidence_coverage: float = 0.0
    retrieval_density: float = 0.0
    cross_stage_agreement: float = 0.0
    adas_penalty: float = 0.0          # subtracted, not multiplied
    authenticity_penalty: float = 0.0  # likewise. Exposed so the UI can show
                                       # it: a penalty visible only inside an
                                       # expander makes the summary arithmetic
                                       # look wrong.
    line_item_floor: float = 0.0       # lowest per-item confidence
    claim_confidence: float = 0.0
    explanation: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """What the reviewer is shown, and why."""
    tier: str                 # not_processed | verify | starting_point | low_confidence
    headline: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class EvidenceVerdict:
    """Outcome of the evidence sufficiency stage."""
    status: str               # sufficient | re_request | escalate
    missing: list[str] = field(default_factory=list)
    instruction: str = ""     # customer-facing text when status == re_request
    escalation_reason: str = ""
    coverage_score: float = 0.0


@dataclass
class ClaimResult:
    """Everything produced for one claim. This is what the UI renders and
    what would be written to the audit trail.
    """
    context: ClaimContext
    photos: list[Photo] = field(default_factory=list)
    gate_passed: bool = True
    gate_reasons: list[str] = field(default_factory=list)
    evidence: Optional[EvidenceVerdict] = None
    assessment: Optional[Assessment] = None
    confidence: Optional[ConfidenceBreakdown] = None
    decision: Optional[Decision] = None
    attempt: int = 1
