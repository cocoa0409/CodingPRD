"""Volunteer credential pipeline: defaults and parallel dimensions (PRD §3.2)."""
from test_helpers import (
    PARTNER_MGR,
    ApiErrorId,
    api_client,
    assert_volunteer,
    credential_event,
    get_volunteer,
    make_partner,
    make_volunteer,
    validate_success,
    volunteer_payload,
)


def test_volunteer_create_applies_system_defaults(api):
    """PRD §3.2: "A new volunteer starts with `screening_status` INITIATED,
    `training_status` NOT_STARTED, and `engagement_status` ACTIVE, and both
    expiry fields — `screening_expires_on` and `training_expires_on` — are
    null until armed."
    PRD §3.2: "A volunteer's computed `eligible` flag is true exactly when
    screening is CLEARED, training is COMPLETED, engagement is ACTIVE, and the
    recruiting partner's `status` is ACTIVE — all four conjuncts, no partial
    credit."

    Design: Corner/entities/corner_volunteer_create_applies_system_defaults
    """
    partner = make_partner(activate=False)
    resp = api_client.create_volunteer(
        volunteer_payload(partner["id"], full_name="Vol One", email="vol1@acme.example"),
        PARTNER_MGR,
    )
    data = validate_success(resp, 201)
    assert_volunteer(data)
    assert data["screening_status"] == "INITIATED"
    assert data["training_status"] == "NOT_STARTED"
    assert data["engagement_status"] == "ACTIVE"
    assert data["screening_expires_on"] is None
    assert data["training_expires_on"] is None
    assert data["hours_contributed"] == 0
    assert data["eligible"] is False


def _volunteer_flagged_with_completed_training():
    """vol1: TRAINING BEGIN -> SCREENING FLAG -> TRAINING COMPLETE, so
    screening sits FLAGGED while training is COMPLETED."""
    partner = make_partner(activate=True)
    volunteer = make_volunteer(partner["id"], credentialed=False)
    credential_event(volunteer["id"], "TRAINING", "BEGIN")
    credential_event(volunteer["id"], "SCREENING", "FLAG")
    credential_event(volunteer["id"], "TRAINING", "COMPLETE")
    return volunteer


def test_volunteer_parallel_dimensions_move_independently(api):
    """PRD §3.2: "These are three parallel dimensions, not a single ladder: a
    training BEGIN or COMPLETE is legal while screening sits FLAGGED, and a
    screening event never touches training."
    PRD §3.2: "A volunteer's computed `eligible` flag is true exactly when
    screening is CLEARED, training is COMPLETED, engagement is ACTIVE, and the
    recruiting partner's `status` is ACTIVE — all four conjuncts, no partial
    credit."

    Design: Difficulty/non_linear_state_machine/volunteer_parallel_dimensions_flag_reinitiate_cycle
    """
    volunteer = _volunteer_flagged_with_completed_training()
    mid = get_volunteer(volunteer["id"])
    assert mid["screening_status"] == "FLAGGED"
    assert mid["training_status"] == "COMPLETED", "training advanced while screening was FLAGGED"
    assert mid["engagement_status"] == "ACTIVE"
    assert mid["eligible"] is False, "FLAGGED screening blocks the conjunction"


def test_volunteer_screening_reinitiate_then_clear_restores_eligibility(api):
    """PRD §3.2: "For kind SCREENING: CLEAR moves INITIATED to CLEARED and arms
    `screening_expires_on` to the logical clock's current instant plus 365
    days; FLAG moves INITIATED to FLAGGED; REINITIATE moves FLAGGED back to
    INITIATED, and likewise moves EXPIRED back to INITIATED — both
    re-initiation branches clear `screening_expires_on` to null."

    Design: Difficulty/non_linear_state_machine/volunteer_parallel_dimensions_flag_reinitiate_cycle
    """
    volunteer = _volunteer_flagged_with_completed_training()
    reinit = credential_event(volunteer["id"], "SCREENING", "REINITIATE")
    assert reinit["screening_status"] == "INITIATED"
    assert reinit["screening_expires_on"] is None, "re-initiation clears the armed expiry"

    cleared = credential_event(volunteer["id"], "SCREENING", "CLEAR")
    assert cleared["screening_status"] == "CLEARED"
    # logical clock is still the default 2026-09-01; +365 days lands on 2027-09-01
    assert cleared["screening_expires_on"] is not None
    assert cleared["screening_expires_on"].startswith("2027-09-01"), (
        f"expiry armed to clock + 365 days, got {cleared['screening_expires_on']}"
    )
    final = get_volunteer(volunteer["id"])
    assert final["eligible"] is True, "CLEARED x COMPLETED x ACTIVE x partner ACTIVE"
