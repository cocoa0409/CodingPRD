"""Cross-episode accounting: duty separation and idempotency (log only)."""

from db import STORE
from errors import ApiError

GATED_UTILIZATION_STEPS = {"assessment_cosign", "concurrent_review", "medical_cosign"}
GATED_DIRECTOR_STEPS = {"admit", "complete_treatment", "discharge", "submit_for_cosign"}


def record_utilization_step(episode, step, user_id):
    """Log a gated UtilizationReviewer step against an episode."""
    if not user_id:
        return
    STORE.dos_log.setdefault(episode["id"], set()).add(user_id)


def assert_segregation(episode, user_id):
    """A ClinicalDirector who already performed a gated utilization step on
    this episode may not perform a gated director step. Reported before any
    existence check on the request."""
    if not user_id:
        return
    performers = STORE.dos_log.get(episode["id"])
    if performers and user_id in performers:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")


def record_so_step(episode, step, user_id):
    """Best-effort clinical-director action log (used by cross-facing reads)."""
    if not user_id:
        return
    STORE.so_consumed.setdefault(episode["id"], set()).add(user_id)