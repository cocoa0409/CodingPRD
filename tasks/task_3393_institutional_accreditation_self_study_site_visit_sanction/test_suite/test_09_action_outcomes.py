"""Action outcomes: disclosure ladder, terminal effectuation, candidacy gate,
and the institution's two independent standing dimensions."""
from test_helpers import (
    ApiErrorId,
    CANDIDACY_PAST_EXPIRY_ISO,
    advance_outcome,
    create_review_cycle,
    get_institution,
    list_cycle_outcomes,
    set_logical_clock,
    setup_accredited_institution,
    setup_decided_cycle,
    setup_panel_band_sanction,
    validate_error,
    validate_success,
)


def test_outcome_disclosure_stamps_before_effectuation(api, staff_headers):
    """PRD section 3.8: "Every commission action is born as an `ActionOutcome` in `DRAFTED` status and walks a fixed publication ladder — `DRAFTED` → `DISCLOSED` → `EFFECTIVE` — one step per advance by `CommissionStaff`, with `EFFECTIVE` terminal for the ladder itself."
    PRD section 3.8: "Disclosure is mandatory for every action, reaffirmation and denial included: the step into `DISCLOSED` stamps the generated public notice onto `public_disclosure_text` and records `disclosed_at` on the logical clock."

    Design: Corner/endpoints/outcome_disclosure_stamps_before_effectuation_mutates
    """
    ctx = setup_decided_cycle()
    institution_id = ctx["institution"]["id"]
    outcome_id = ctx["outcome"]["id"]

    disclosed_response = api.advance_action_outcome(outcome_id, {}, staff_headers)
    disclosed = validate_success(disclosed_response)
    assert disclosed["status"] == "DISCLOSED"
    assert disclosed["disclosed_at"] is not None
    assert isinstance(disclosed["public_disclosure_text"], str)
    assert disclosed["public_disclosure_text"].strip()
    assert get_institution(institution_id)["accreditation_status"] == "CANDIDATE"

    effective_response = api.advance_action_outcome(outcome_id, {}, staff_headers)
    effective = validate_success(effective_response)
    assert effective["status"] == "EFFECTIVE"
    assert effective["effective_at"] is not None
    assert get_institution(institution_id)["accreditation_status"] == "ACCREDITED"


def test_effective_outcome_rejects_further_advance(api, staff_headers):
    """PRD section 3.8: "Every commission action is born as an `ActionOutcome` in `DRAFTED` status and walks a fixed publication ladder — `DRAFTED` → `DISCLOSED` → `EFFECTIVE` — one step per advance by `CommissionStaff`, with `EFFECTIVE` terminal for the ladder itself."

    Design: Corner/state_machines/outcome_effective_advance_rejected
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]
    outcome_id = ctx["outcome"]["id"]
    version_before = get_institution(institution_id)["version"]

    response = api.advance_action_outcome(outcome_id, {}, staff_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    institution = get_institution(institution_id)
    assert institution["accreditation_status"] == "ACCREDITED"
    assert institution["version"] == version_before


def test_grant_after_candidacy_expiry_rejected(api, staff_headers):
    """PRD section 3.8: "A `GRANT_INITIAL` is gated on the candidacy clock — if the logical clock has passed `candidacy_expires_at`, the advance is rejected with `ERR_CANDIDACY_EXPIRED` (HTTP 409) — and otherwise promotes the institution from `CANDIDATE` to `ACCREDITED`, stamping `accredited_since`."

    Design: Corner/validations/candidacy_expired_blocks_grant_effectuation
    """
    ctx = setup_decided_cycle()
    institution_id = ctx["institution"]["id"]
    outcome_id = ctx["outcome"]["id"]

    set_logical_clock(CANDIDACY_PAST_EXPIRY_ISO)
    disclosed_response = api.advance_action_outcome(outcome_id, {}, staff_headers)
    assert validate_success(disclosed_response)["status"] == "DISCLOSED"

    blocked = api.advance_action_outcome(outcome_id, {}, staff_headers)
    validate_error(blocked, ApiErrorId.ERR_CANDIDACY_EXPIRED)

    outcomes = list_cycle_outcomes(ctx["cycle"]["id"])
    assert outcomes[0]["status"] == "DISCLOSED"
    assert get_institution(institution_id)["accreditation_status"] == "CANDIDATE"


def test_accreditation_and_sanction_dimensions_evolve_independently(api):
    """PRD section 2.9: "An institution can be `ACCREDITED` while simultaneously under `PROBATION`; a sanction does not rewrite accreditation history, and a reaffirmation does not erase a sanction."
    PRD section 3.3: "An `INITIAL_ACCREDITATION` cycle requires the institution to be a `CANDIDATE`; a `REAFFIRMATION` cycle requires it to be `ACCREDITED`; a mismatch between the requested cycle type and the institution's standing is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/institution_parallel_dimensions_evolve_independently
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]
    after_grant = get_institution(institution_id)
    assert after_grant["accreditation_status"] == "ACCREDITED"
    assert after_grant["sanction_status"] == "NONE"
    assert ctx["cycle"]["status"] == "CLOSED"

    result = setup_panel_band_sanction(institution_id)
    assert result["report"]["status"] == "FLAGGED_PANEL"

    sanctioned = get_institution(institution_id)
    assert sanctioned["accreditation_status"] == "ACCREDITED"
    assert sanctioned["sanction_status"] == "NOTICE"
    assert sanctioned["latest_cfi_band"] == "PANEL"

    reaffirmation = create_review_cycle(institution_id, "REAFFIRMATION")
    assert reaffirmation["status"] == "SCHEDULED"
    assert reaffirmation["cycle_type"] == "REAFFIRMATION"
