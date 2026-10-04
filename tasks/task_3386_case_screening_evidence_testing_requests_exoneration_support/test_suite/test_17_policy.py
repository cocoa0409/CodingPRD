"""Policy initiatives: the pattern-evidence threshold on SUBMIT_DRAFT is
inclusive at exactly 3 qualifying cases."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_policy_initiative,
    create_jurisdiction,
    list_rows,
    policy_advance_payload,
    setup_case_with_destroyed_evidence,
    setup_policy_initiative,
    validate_error,
    validate_ok,
)

POLICY = TEST_USERS["policy_director_headers"]


def _jurisdiction_with_researching_initiative():
    jurisdiction = create_jurisdiction(state_code="VA", name="Virginia")
    initiative = setup_policy_initiative(
        jurisdiction["id"],
        topic="EVIDENCE_PRESERVATION",
        title="Statutory retention duties",
        begin_research=True,
    )
    assert initiative["status"] == "RESEARCHING"
    return jurisdiction, initiative


def _pattern_count(api, jurisdiction_id):
    data, _ = list_rows(api.list_jurisdiction_policy_initiatives(jurisdiction_id, POLICY))
    assert len(data) == 1
    return data[0]["pattern_case_count"]


def test_policy_draft_with_two_qualifying_cases_rejected(api):
    """PRD section 3.9: "submitting a draft moves `RESEARCHING` to `DRAFTED`
    and is gated on evidence — `pattern_case_count` must be at least 3, the
    pattern threshold, else `ERR_INSUFFICIENT_PATTERN_EVIDENCE` (HTTP 409)".

    Design: Difficulty/boundary_precision_check/policy_draft_threshold_exactly_three_passes
    """
    jurisdiction, initiative = _jurisdiction_with_researching_initiative()
    setup_case_with_destroyed_evidence(
        jurisdiction_id=jurisdiction["id"],
        client_overrides={"full_name": "Case One Client"},
        intake_overrides={"conviction_summary": "Case one"},
    )
    setup_case_with_destroyed_evidence(
        jurisdiction_id=jurisdiction["id"],
        client_overrides={"full_name": "Case Two Client"},
        intake_overrides={"conviction_summary": "Case two"},
    )
    assert _pattern_count(api, jurisdiction["id"]) == 2

    resp = api.advance_policy_initiative(
        initiative["id"], policy_advance_payload("SUBMIT_DRAFT"), POLICY
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PATTERN_EVIDENCE)


def test_policy_draft_with_exactly_three_qualifying_cases_passes(api):
    """PRD section 3.9: "`pattern_case_count` must be at least 3, the pattern
    threshold, else `ERR_INSUFFICIENT_PATTERN_EVIDENCE` (HTTP 409)" — the
    at-least bound is inclusive.
    PRD section 3.9: "for `EVIDENCE_PRESERVATION`, a case whose
    `destroyed_evidence_count` is at least 1".

    Design: Difficulty/boundary_precision_check/policy_draft_threshold_exactly_three_passes
    """
    jurisdiction, initiative = _jurisdiction_with_researching_initiative()
    for i in (1, 2, 3):
        setup_case_with_destroyed_evidence(
            jurisdiction_id=jurisdiction["id"],
            client_overrides={"full_name": f"Case {i} Client"},
            intake_overrides={"conviction_summary": f"Case {i}"},
        )
    assert _pattern_count(api, jurisdiction["id"]) == 3

    data = validate_ok(
        api.advance_policy_initiative(
            initiative["id"], policy_advance_payload("SUBMIT_DRAFT"), POLICY
        )
    )
    assert data["status"] == "DRAFTED"
