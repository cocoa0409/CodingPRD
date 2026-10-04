"""Verification advancement, the completeness ledger and the disclosure measure."""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    ApiErrorId,
    add_advisory_members,
    add_leader,
    add_officers,
    add_program,
    create_org,
    get_org,
    make_verifier_headers,
    scenario_bright_futures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_verifying_a_profile_the_same_operator_last_edited_returns_segregation_of_duties(api):
    """PRD §2.6: "On verification of an organization profile, the acting
    `X-User-ID` must differ from the organization's `last_profile_editor_user_id`
    — the identifier of the actor that created or last patched the profile — and a
    request from the same actor is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.3: "The second gate is the step rule: `target_level` must be exactly the
    next level above the current `verification_level`".

    Design: Corner/validations/verifying_a_profile_the_same_operator_last_edited_returns_segregation_of_duties
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL",
                     ntee_code="B82",
                     mission_statement="Mentoring for first-generation students.")
    add_program(org["id"], program_name="Mentoring Core", subject_code="B82",
                disclosure_level="PUBLIC")
    add_officers(org["id"], 3)

    same_operator = api.verify_organization(
        org["id"], {"target_level": "DOCUMENT_VERIFIED", "evidence_count": 1},
        make_verifier_headers(ADMIN_USER_ID))
    assert same_operator.status_code == 403, (
        f"Expected 403, got {same_operator.status_code}: {same_operator.text}"
    )
    err = validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert err["error_id"] != "ERR_PROFILE_INCOMPLETE", (
        "the segregation gate is checked before the score gate"
    )

    unchanged = get_org(org["id"])
    assert unchanged["profile_status"] == "DRAFT"
    assert unchanged["verification_level"] == "SELF_REPORTED"

    skip_step = api.verify_organization(
        org["id"], {"target_level": "INDEPENDENTLY_AUDITED", "evidence_count": 1},
        make_verifier_headers())
    assert skip_step.status_code == 409, (
        f"Expected 409, got {skip_step.status_code}: {skip_step.text}"
    )
    validate_error(skip_step, ApiErrorId.ERR_VERIFICATION_STEP_INVALID.value)


def test_provisional_completeness_leadership_and_governance_dimensions_score_zero_without_officers(api):
    """PRD §3.2: "The `LEADERSHIP` dimension counts `ACTIVE` leadership members:
    no rows scores 0.0; three or more officers (`is_officer` true) scores 1.0; one
    or two officers scores 0.5; otherwise 0.0."
    PRD §3.2: "The `GOVERNANCE` dimension counts `ACTIVE` leadership members who
    are officers: three or more independents scores 1.0, one or two scores 0.5,
    none scores 0.0."

    Design: Corner/calculations/provisional_completeness_leadership_and_governance_dimensions_score_zero_without_officers
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL",
                     ntee_code="B82",
                     mission_statement="Mentoring for first-generation students.")
    add_program(org["id"], program_name="Mentoring Core", subject_code="B82",
                disclosure_level="PUBLIC")
    add_advisory_members(org["id"], 3)

    after = get_org(org["id"])
    assert after["provisional_completeness_score"] == 25, (
        "PROGRAMS 0.15 + MISSION 0.10 only — no officer row exists"
    )
    assert after["disclosure_pct"] == pytest.approx(0.4500, abs=1e-6), (
        "PROGRAMS 0.15 + LEADERSHIP 0.20 + MISSION 0.10, with GOVERNANCE at 0.0"
    )
    assert after["verification_level"] == "SELF_REPORTED"
    assert after["profile_completeness_score"] == after["provisional_completeness_score"]


def test_disclosure_pct_governance_dimension_needs_an_independent_public_officer(api):
    """PRD §3.2: "The `GOVERNANCE` dimension scores 1.0 when at least one `ACTIVE`
    leadership member is both independent and `PUBLIC`, 0.5 when at least one
    `ACTIVE` officer row exists, and 0.0 otherwise."

    Design: Corner/calculations/disclosure_pct_governance_dimension_needs_an_independent_public_officer
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL",
                     ntee_code="B82",
                     mission_statement="Mentoring for first-generation students.")
    add_program(org["id"], program_name="Mentoring Core", subject_code="B82",
                disclosure_level="PUBLIC")
    add_leader(org["id"], full_name="Quinn Alder", office_title="Board Chair",
               is_officer=True, is_independent=False, disclosure_level="PUBLIC")

    before = get_org(org["id"])
    assert before["disclosure_pct"] == pytest.approx(0.5000, abs=1e-6), (
        "PROGRAMS 0.15 + LEADERSHIP 0.20 + MISSION 0.10 + GOVERNANCE 0.5 * 0.10"
    )

    add_leader(org["id"], full_name="Rex Amari", office_title="Audit Chair",
               is_officer=True, is_independent=True, disclosure_level="PUBLIC")

    after = get_org(org["id"])
    assert after["disclosure_pct"] == pytest.approx(0.5500, abs=1e-6)
    assert round(after["disclosure_pct"] - before["disclosure_pct"], 4) == 0.0500, (
        "the delta is exactly the GOVERNANCE weight times the 0.5 step"
    )


# ---------------------------------------------------------------------------
# Published completeness switching variant on verification (difficulty instance)
# ---------------------------------------------------------------------------

def test_published_completeness_switches_to_the_verified_variant_on_verification(api):
    """PRD §3.2: "The published value, `profile_completeness_score`, is the
    verified score when the organization's `verification_level` is
    `DOCUMENT_VERIFIED` or `INDEPENDENTLY_AUDITED`, and the provisional score while
    the organization remains `SELF_REPORTED`."
    PRD §3.2: "An organization that advances from `SELF_REPORTED` to
    `DOCUMENT_VERIFIED` therefore watches `profile_completeness_score` drop from
    100 to 50 without a single underlying row changing."

    Design: Difficulty/dual_variant_calc/org_published_completeness_switches_variant_on_verification
    """
    set_clock()
    org, filing = scenario_bright_futures()
    assert org["profile_completeness_score"] == 100, (
        "the self-reported variant scores every dimension at 1.0"
    )

    resp = api.verify_organization(
        org["id"], {"target_level": "DOCUMENT_VERIFIED", "evidence_count": 2},
        make_verifier_headers())
    verified = validate_success(resp, 200)

    assert verified["profile_status"] == "ACTIVE"
    assert verified["provisional_completeness_score"] == 100
    assert verified["verified_completeness_score"] == 88, (
        "FINANCES falls to its 0.5 rung because the filing is not is_verified"
    )
    assert verified["profile_completeness_score"] == 88
    assert verified["profile_completeness_score"] != verified["provisional_completeness_score"]


def test_verification_sweeps_existing_rows_and_flips_the_published_score(api):
    """PRD §3.3: "every `Program`, `LeadershipMember` and `DemographicRecord` row
    that existed before the call has its `is_verified` flag set to true, and
    `ntee_code_verified` is set to true."
    PRD §3.2: "`MISSION` scores 1.0 only when the `mission_statement` is non-empty,
    `ntee_code` is non-null, and `ntee_code_verified` is true".

    Design: Difficulty/dual_variant_calc/org_published_completeness_switches_variant_on_verification
    """
    set_clock()
    org, filing = scenario_bright_futures()
    before = get_org(org["id"])
    assert before["ntee_code_verified"] is False

    verified = validate_success(api.verify_organization(
        org["id"], {"target_level": "DOCUMENT_VERIFIED", "evidence_count": 2},
        make_verifier_headers()), 200)

    assert verified["verification_level"] == "DOCUMENT_VERIFIED"
    assert verified["ntee_code_verified"] is True
    assert verified["verification_evidence_count"] == 2
    assert verified["profile_completeness_score"] == verified["verified_completeness_score"]

    programs, _ = validate_paginated(
        api.list_programs(org["id"], make_verifier_headers()))
    assert all(row["is_verified"] is True for row in programs)
    leadership, _ = validate_paginated(
        api.list_leadership_members(org["id"], make_verifier_headers()))
    assert len(leadership) == 3
    assert all(row["is_verified"] is True for row in leadership)
    demographics, _ = validate_paginated(
        api.list_demographic_records(org["id"], make_verifier_headers()))
    assert len(demographics) == 1
    assert demographics[0]["is_verified"] is True
