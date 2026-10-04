"""Transparency seals: award levels, renewal fees, lapse and revocation."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_license,
    add_officers,
    add_program,
    assert_same_instant,
    award_seal,
    create_license,
    create_org,
    get_license,
    get_org,
    make_organization_user_headers,
    make_verifier_headers,
    replace_demographics,
    scenario_cascade,
    scenario_health_alliance,
    scenario_meridian,
    seal_by_id,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    verify_org,
    CLOCK_2027_12_01,
    CLOCK_2027_09_16,
)


def test_lapsed_seal_is_terminal_and_cannot_be_renewed(api):
    """PRD §2.4: "A seal whose `expires_on` plus 90 days is behind the current
    clock is already `LAPSED` and is treated as such by any rule that inspects it."
    PRD §3.7: "when the logical clock advances past `expires_on` plus 90 days, an
    `ACTIVE` seal moves to `LAPSED` and the owning organization's
    `transparency_seal_level` returns to `NONE` with `seal_expires_on` set to null."

    Design: Corner/state_machines/lapsed_seal_is_terminal_and_cannot_be_renewed
    """
    set_clock()
    org = scenario_cascade()
    seal = award_seal(org["id"])
    assert_same_instant(seal["expires_on"], "2027-09-01T00:00:00Z",
                        field="seal.expires_on")

    set_clock(CLOCK_2027_12_01)

    first = api.renew_seal(seal["id"], make_verifier_headers())
    assert first.status_code == 409, f"Expected 409, got {first.status_code}: {first.text}"
    # The PRD names ERR_SEAL_LAPSED for a renewal arriving 91+ days late, and it
    # also declares the seal already LAPSED once the clock passes expires_on + 90
    # days, so either the temporal gate or the state gate may report first.
    validate_error_is_one_of(first, ["ERR_SEAL_LAPSED", "ERR_INVALID_STATE"])

    after = seal_by_id(org["id"], seal["id"])
    assert after["status"] == "LAPSED"
    assert after["renewal_attempt_count"] in (0, 1), (
        "the counter is incremented by every renewal attempt, but the automatic "
        "time-based lapse is not itself an attempt"
    )

    refreshed = get_org(org["id"])
    assert refreshed["transparency_seal_level"] == "NONE"
    assert refreshed.get("seal_expires_on") is None

    second = api.renew_seal(seal["id"], make_verifier_headers())
    assert second.status_code == 409, f"Expected 409, got {second.status_code}: {second.text}"
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)


def test_one_clock_advance_expires_a_license_and_lapses_a_seal_together(api):
    """PRD §2.4: "Advancing the clock re-evaluates every date-sensitive rule
    against the new instant — seal expiry and lapse, license term windows, renewal
    windows and correction timestamps all move together."
    PRD §3.9: "A license expires automatically when the logical clock reaches
    `term_end`".

    Design: Corner/cross_cutting_layers/one_clock_advance_expires_a_license_and_lapses_a_seal_together
    """
    set_clock()
    org = scenario_cascade()
    seal = award_seal(org["id"])
    license_ = create_license(org["id"], tier="RESEARCHER",
                              term_start="2026-09-01T00:00:00Z",
                              term_end="2027-09-01T00:00:00Z")
    activated = activate_license(license_["id"], org["id"])
    assert activated["status"] == "ACTIVE"

    set_clock(CLOCK_2027_12_01)

    expired = get_license(license_["id"], org["id"])
    assert expired["status"] == "EXPIRED"

    lapsed = seal_by_id(org["id"], seal["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["renewal_attempt_count"] == 0, (
        "the lapse is a system transition, not a failed renewal"
    )

    refreshed = get_org(org["id"])
    assert refreshed["active_license_count"] == 0
    assert refreshed["transparency_seal_level"] == "NONE"
    assert refreshed.get("seal_expires_on") is None


def test_seal_award_below_the_disclosure_floor_returns_seal_disclosure_insufficient(api):
    """PRD §3.7: "the organization's `disclosure_pct` must be at least 0.50; a
    lower value is refused with `ERR_SEAL_DISCLOSURE_INSUFFICIENT` (HTTP 422). The
    third gate is the floor, and it is absolute: an organization that discloses
    less than half of the weighted profile can hold no seal at any level."

    Design: Corner/validations/seal_award_below_the_disclosure_floor_returns_seal_disclosure_insufficient
    """
    set_clock()
    org = create_org("Willow Creek Collective", "900100200", state_code="IL")
    add_program(org["id"], program_name="Mentoring Core", subject_code="B82",
                disclosure_level="PUBLIC")
    add_officers(org["id"], 3)
    verify_org(org["id"], "DOCUMENT_VERIFIED", 1)

    # PROGRAMS 0.15 + LEADERSHIP 0.20 + GOVERNANCE 0.10 = 0.4500, below the floor.
    active = get_org(org["id"])
    assert active["profile_status"] == "ACTIVE"
    assert active["disclosure_pct"] == pytest.approx(0.4500, abs=1e-6)

    resp = api.award_seal(org["id"], make_verifier_headers())
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_SEAL_DISCLOSURE_INSUFFICIENT.value)

    rows, _ = validate_paginated(api.list_seals(org["id"], make_verifier_headers()))
    assert rows == [], "No seal may be created below the disclosure floor"
    assert get_org(org["id"])["transparency_seal_level"] == "NONE"


def test_organization_user_role_cannot_award_a_transparency_seal(api):
    """PRD §2.1: "If the headers are well formed but the named role is not in the
    endpoint's authorized role list, the request is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/organization_user_role_cannot_award_a_transparency_seal
    """
    set_clock()
    org = scenario_cascade()
    assert get_org(org["id"])["disclosure_pct"] >= 0.50

    resp = api.award_seal(org["id"], make_organization_user_headers(org["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert err["error_id"] != "ERR_SEAL_DISCLOSURE_INSUFFICIENT", (
        "authorization precedes the disclosure floor"
    )

    rows, _ = validate_paginated(api.list_seals(org["id"], make_verifier_headers()))
    assert rows == []


# ---------------------------------------------------------------------------
# Nested min() seal award (difficulty instance)
# ---------------------------------------------------------------------------

def test_seal_level_is_capped_by_verification_standing_at_gold(api):
    """PRD §3.7: "One at `DOCUMENT_VERIFIED` is capped at `GOLD`."
    PRD §3.7: "The awarded level is the lower-ranked of the base level and the cap
    level, where the ranking runs `BRONZE` below `SILVER` below `GOLD` below
    `PLATINUM`."

    Design: Difficulty/combinatorial_formula/seal_level_nested_min_of_disclosure_base_and_verification_cap
    """
    set_clock()
    org = scenario_meridian(verify_level="DOCUMENT_VERIFIED")

    resp = api.award_seal(org["id"], make_verifier_headers())
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    seal = validate_success(resp, 201)

    assert seal["level"] == "GOLD", (
        "disclosure 0.9000 and two verified filings push the base level to "
        "PLATINUM, but the DOCUMENT_VERIFIED cap holds the award at GOLD"
    )
    assert seal["disclosure_pct_at_award"] == pytest.approx(0.9000, abs=1e-6)
    assert_same_instant(seal["expires_on"], "2027-09-01T00:00:00Z",
                        field="seal.expires_on")
    assert_same_instant(seal["renewal_window_opens_on"], "2027-07-03T00:00:00Z",
                        field="seal.renewal_window_opens_on")
    assert seal["status"] == "ACTIVE"
    assert seal["renewal_attempt_count"] == 0
    assert get_org(org["id"])["transparency_seal_level"] == "GOLD"


def test_seal_level_inputs_are_the_disclosure_measure_and_the_verified_filings(api):
    """PRD §3.7: "A `disclosure_pct` of at least 0.90 together with a verified
    filing count of at least 2 yields `PLATINUM`."
    PRD §3.7: "Finally, if the leadership verification percentage is below 0.50,
    the level is lowered once more to `SILVER` if it currently ranks above `SILVER`."

    Design: Difficulty/combinatorial_formula/seal_level_nested_min_of_disclosure_base_and_verification_cap
    """
    set_clock()
    org = scenario_meridian(verify_level="DOCUMENT_VERIFIED")
    assert org["disclosure_pct"] == pytest.approx(0.9000, abs=1e-6), (
        "the base level's PLATINUM disclosure gate is satisfied"
    )
    assert org["verification_level"] == "DOCUMENT_VERIFIED"

    leadership, _ = validate_paginated(
        api.list_leadership_members(org["id"], make_verifier_headers()))
    assert len(leadership) == 3
    assert all(member["is_verified"] is True for member in leadership), (
        "every ACTIVE leader is verified, so the leadership floor is not what binds"
    )

    seal = award_seal(org["id"])
    assert seal["level"] == "GOLD"
    assert seal["level"] != "PLATINUM", "the verification cap is the binding constraint"


# ---------------------------------------------------------------------------
# Pinned renewal-fee step order (difficulty instance)
# ---------------------------------------------------------------------------

def test_seal_renewal_fee_uses_the_pre_renewal_expiry_for_days_late(api):
    """PRD §3.7: "A `GOLD` seal renewed 15 days late pays a base of 75000 cents
    plus a tier-1 late fee of 7500 cents, for a renewal fee of 82500 cents."
    PRD §3.7: "the counter is incremented by every attempt, successful or rejected,
    and its value at the moment of the decision is its pre-increment value, so the
    increment is a consequence of the decision and never an input to it."

    Design: Difficulty/combinatorial_formula/seal_renewal_fee_uses_pre_renewal_expiry_in_pinned_step_order
    """
    set_clock()
    org = scenario_meridian(verify_level="DOCUMENT_VERIFIED")
    seal = award_seal(org["id"])
    assert_same_instant(seal["expires_on"], "2027-09-01T00:00:00Z",
                        field="seal.expires_on")

    set_clock(CLOCK_2027_09_16)
    renewed = validate_success(api.renew_seal(seal["id"], make_verifier_headers()), 200)

    assert renewed["last_renewal_fee_cents"] == 82500, (
        "75000 base + 10% tier-1 late fee on the frozen GOLD level"
    )
    assert renewed["renewal_attempt_count"] == 1
    assert renewed["level"] == "GOLD"


def test_second_seal_renewal_is_free_of_late_fees_because_expiry_already_moved(api):
    """PRD §3.7: "In every other branch the renewal succeeds: `last_renewal_fee_cents`
    is set to the computed renewal fee, `expires_on` is set to the current
    logical-clock instant plus 365 days, `renewal_window_opens_on` is set to that
    new `expires_on` minus 60 days, the level is not re-evaluated and
    `disclosure_pct_at_award` is not refreshed".

    Design: Difficulty/combinatorial_formula/seal_renewal_fee_uses_pre_renewal_expiry_in_pinned_step_order
    """
    set_clock()
    org = scenario_meridian(verify_level="DOCUMENT_VERIFIED")
    seal = award_seal(org["id"])
    set_clock(CLOCK_2027_09_16)
    validate_success(api.renew_seal(seal["id"], make_verifier_headers()), 200)

    after_first = seal_by_id(org["id"], seal["id"])
    assert_same_instant(after_first["expires_on"], "2028-09-15T00:00:00Z",
                        field="seal.expires_on")
    assert_same_instant(after_first["renewal_window_opens_on"], "2028-07-17T00:00:00Z",
                        field="seal.renewal_window_opens_on")

    renewed = validate_success(api.renew_seal(seal["id"], make_verifier_headers()), 200)
    assert renewed["last_renewal_fee_cents"] == 75000, (
        "expires_on has already moved into the future, so days_late is zero and "
        "the bare GOLD base fee is charged"
    )
    assert renewed["renewal_attempt_count"] == 2
    assert renewed["level"] == "GOLD", "renewal never re-evaluates the level"


# ---------------------------------------------------------------------------
# Disclosure boundary at exactly 0.9000 (difficulty instance)
# ---------------------------------------------------------------------------

def test_seal_award_at_exactly_zero_point_nine_zero_is_platinum(api):
    """PRD §3.7: "A `disclosure_pct` of at least 0.90 together with a verified
    filing count of at least 2 yields `PLATINUM`."

    Design: Difficulty/boundary_precision_check/seal_award_disclosure_pct_boundary_at_exactly_0_9000
    """
    set_clock()
    org = scenario_health_alliance(
        legal_name="Cedarline Health Alliance", ein="606060606", ntee_code="E30",
        mission_statement="Rural health access across the Green Mountains.")
    assert org["disclosure_pct"] == pytest.approx(0.9000, abs=1e-6)
    assert org["verification_level"] == "INDEPENDENTLY_AUDITED"

    seal = award_seal(org["id"])
    assert seal["level"] == "PLATINUM", (
        "0.9000 satisfies the inclusive >= 0.90 gate"
    )
    assert seal["disclosure_pct_at_award"] == pytest.approx(0.9000, abs=1e-6)


def test_seal_award_at_zero_point_eight_five_zero_is_gold(api):
    """PRD §3.2: "the same organization with its governance dimension reduced to
    the 0.5 rung and its demographics withheld lands at 0.8500. Those two values
    straddle the `PLATINUM` disclosure threshold".
    PRD §3.7: "Failing that, a `disclosure_pct` of at least 0.75 together with a
    verified filing count of at least 1 yields `GOLD`."

    Design: Difficulty/boundary_precision_check/seal_award_disclosure_pct_boundary_at_exactly_0_9000
    """
    set_clock()
    org = scenario_health_alliance(
        legal_name="Fernwood Health Alliance", ein="707070707", ntee_code=None,
        mission_statement="Community health outreach in the Northeast Kingdom.")
    assert org["disclosure_pct"] == pytest.approx(0.8500, abs=1e-6)

    seal = award_seal(org["id"])
    assert seal["level"] == "GOLD", "0.8500 does not reach the 0.90 PLATINUM gate"
    assert seal["disclosure_pct_at_award"] == pytest.approx(0.8500, abs=1e-6)


# ---------------------------------------------------------------------------
# Demographic replacement cascading into seal revocation (difficulty instance)
# ---------------------------------------------------------------------------

def test_demographic_replacement_revokes_the_platinum_seal(api):
    """PRD §3.7: "A seal is also revoked when the organization's `disclosure_pct`
    falls below the disclosure floor of that seal's own level, where the floors are
    0.50 for `BRONZE` and `SILVER`, 0.75 for `GOLD`, and 0.90 for `PLATINUM`."
    PRD §3.7: "Revocation moves the seal's own `status` to `REVOKED`, sets the
    organization's `transparency_seal_level` to `NONE` and `seal_expires_on` to
    null, and increments the seal's `version` and the organization's `version` by 1."

    Design: Difficulty/transitive_cascade/demographics_replacement_cascades_four_hops_to_seal_revocation
    """
    set_clock()
    org = scenario_meridian(verify_level="INDEPENDENTLY_AUDITED")
    seal = award_seal(org["id"])
    assert seal["level"] == "PLATINUM"

    version_before = get_org(org["id"])["version"]
    patched = replace_demographics(org["id"], [{
        "category": "AGE_BAND", "value_code": "AGE_35_44",
        "disclosure_level": "RESTRICTED", "fiscal_year": 2025}])
    assert patched["version"] == version_before + 2, (
        "the PATCH advances the version once and the seal revocation it triggers "
        "advances it again, and the response already reflects the recomputed "
        "state (PRD §2.11)"
    )

    revoked = seal_by_id(org["id"], seal["id"])
    assert revoked["level"] == "PLATINUM", "the level is frozen at award"
    assert revoked["status"] == "REVOKED"

    after = get_org(org["id"])
    assert after["transparency_seal_level"] == "NONE"
    assert after.get("seal_expires_on") is None
    assert after["version"] == version_before + 2, (
        "the PATCH and the cascade's seal revocation each advance the organization"
    )


def test_demographic_replacement_moves_disclosure_pct_from_9000_to_8250(api):
    """PRD §3.1: "when the patch carries a `demographic_records` array, the
    organization's entire existing demographic set is deleted and one
    `DemographicRecord` row is created for each element of the array."
    PRD §3.2: "The `DEMOGRAPHICS` dimension scores 1.0 when at least one
    demographic record is `PUBLIC`, 0.5 when demographic rows exist and none is
    public, and 0.0 when none exists."

    Design: Difficulty/transitive_cascade/demographics_replacement_cascades_four_hops_to_seal_revocation
    """
    set_clock()
    org = scenario_meridian(verify_level="INDEPENDENTLY_AUDITED")
    award_seal(org["id"])
    assert get_org(org["id"])["disclosure_pct"] == pytest.approx(0.9000, abs=1e-6)

    replace_demographics(org["id"], [{
        "category": "AGE_BAND", "value_code": "AGE_35_44",
        "disclosure_level": "RESTRICTED", "fiscal_year": 2025}])

    rows, meta = validate_paginated(
        api.list_demographic_records(org["id"], make_verifier_headers()))
    assert len(rows) == 1, "the replacement deletes the previous set"
    assert rows[0]["disclosure_level"] == "RESTRICTED"

    after = get_org(org["id"])
    assert after["disclosure_pct"] == pytest.approx(0.8250, abs=1e-6), (
        "the DEMOGRAPHICS dimension drops from 1.0 to its 0.5 rung"
    )
