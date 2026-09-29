"""Vision model abstraction.

THIS FILE IS THE SOVEREIGNTY ANSWER.

Every vision call in the system goes through this interface. Swapping to a
locally hosted open-weight model for an air-gapped or data-residency
constrained deployment means adding one implementation here and changing one
environment variable. Nothing else in the pipeline moves.

What would degrade in that deployment, stated honestly: fine-grained part
identification. A smaller local model is likely to confuse adjacent panels
and specific trim parts more often. That shows up as lower per-item
confidence, which the composite score already consumes, which narrows the
band of claims that can be handled without an adjuster. The system degrades
gracefully into more human review rather than into wrong answers.

Everything downstream of this interface — costing, ADAS intersection,
confidence arithmetic, routing, the audit trail — is already deterministic
and local. No part of it depends on a hosted service.
"""

from abc import ABC, abstractmethod

from pipeline.models import ClaimContext, Photo


class VLMProvider(ABC):
    """Two calls, deliberately separate.

    Coverage is checked BEFORE damage is assessed, because assessing damage
    from photos already judged inadequate would produce a confident answer
    built on bad evidence. That is the failure mode this whole product is
    trying to avoid.
    """

    name: str = "base"
    is_live: bool = False

    @abstractmethod
    def assess_coverage(
        self,
        photos: list[Photo],
        ctx: ClaimContext,
        panel_vocabulary: list[str],
    ) -> dict:
        """Judge whether the submission is adequate to assess.

        Returns:
            {
              "panels_visible": [str],      # from panel_vocabulary
              "missing":        [str],      # specific, actionable asks
              "unfixable":      str | "",   # key from evidence.UNFIXABLE
              "coverage_score": float,      # 0-1
              "notes":          str,
            }
        """

    @abstractmethod
    def assess_damage(
        self,
        photos: list[Photo],
        ctx: ClaimContext,
        panel_vocabulary: list[str],
    ) -> dict:
        """Produce repair line items with reasoning and per-item confidence.

        Returns:
            {
              "line_items": [
                 {"operation","part","panel","damage_type",
                  "severity","reasoning","confidence"}
              ],
              "damage_panels": [str],
              "notes": str,
            }
        """


def get_provider(name: str) -> VLMProvider:
    """Factory. The only place a provider is chosen."""
    if name == "anthropic":
        from providers.vlm_anthropic import AnthropicVLM
        return AnthropicVLM()
    if name == "mock":
        from providers.vlm_mock import MockVLM
        return MockVLM()
    raise ValueError(
        f"Unknown VLM provider '{name}'. Set VLM_PROVIDER to 'mock' or 'anthropic'."
    )
