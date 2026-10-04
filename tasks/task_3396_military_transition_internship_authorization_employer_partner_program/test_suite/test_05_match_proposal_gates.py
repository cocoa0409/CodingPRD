"""Match proposal gates: the nested-min duration gate, validation priority
pairs, cross-entity state gates, and the skills/location constraints."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures,
    make_employer_rep_headers,
)
from test_helpers.test_users import PROGRAM_OFFICE_HEADERS


def _proposal(api, app_id, opening_id, employer_id, start, end):
    """POST a match proposal, re-reading the opening for a fresh OCC version."""
    opening = fixtures.get_opening(api, opening_id)
    payload = factories.create_match_payload(app_id, opening_id, opening["version"], start, end)
    return api.create_match(payload, make_employer_rep_headers(employer_id))


def _two_installation_world(api):
    """inst caps duration at 120; inst2 at 60. m2 (home inst2, separation
    2027-02-28 = 180 days out) and m3 (home inst, separation 2027-01-15) each
    hold an APPROVED application. Employer is AUTHORIZED with a capacity-2
    REMOTE opening."""
    inst = fixtures.create_installation(api)
    inst2 = fixtures.create_installation(
        api, name="Fort Bragg", command_code="FORSCOM", region_code="R2",
        max_internship_duration_days=60, appeal_window_days=7,
    )
    m2 = fixtures.create_member(api, inst2["id"], full_name="Ben Cole", separation_date="2027-02-28")
    m3 = fixtures.create_member(api, inst["id"], full_name="Cara Diaz", service_branch="NAVY",
                                pay_grade="E6", separation_date="2027-01-15")
    app_b = fixtures.approve_application(api, fixtures.submit_application(api, m2["id"])["id"])
    app_c = fixtures.approve_application(api, fixtures.submit_application(api, m3["id"])["id"])
    eo = fixtures.setup_employer_with_opening(api, capacity=2)
    return inst, inst2, m2, m3, app_b, app_c, eo.employer, eo.opening


def test_duration_gate_separation_headroom_binds(api):
    """PRD §3.4: "Finally the duration must not exceed the effective maximum, which
    is the smaller of two numbers: the governing installation's
    `max_internship_duration_days`, and the separation headroom — the whole days
    from `start_date` to the member's `separation_date` minus the 7-day
    `SEPARATION_BUFFER_DAYS` buffer."
    PRD §3.4: "Exceeding that nested-min cap is `ERR_DURATION_EXCEEDS_POLICY`;
    a duration exactly equal to the cap passes, because both bounds of the duration
    gate are inclusive."

    m3's 50-day proposal (2026-12-01 -> 2027-01-20) faces headroom
    (2027-01-15 - 2026-12-01) - 7 = 38 < 50, so the headroom input of the nested
    min binds.

    Design: Difficulty/combinatorial_formula/match_duration_gate_nested_min_branch
    """
    _, _, _, _, _, app_c, employer, opening = _two_installation_world(api)
    resp = _proposal(api, app_c["id"], opening["id"], employer["id"], "2026-12-01", "2027-01-20")
    validate_error(resp, ApiErrorId.ERR_DURATION_EXCEEDS_POLICY)


def test_duration_gate_policy_cap_binds_and_inclusive_bound(api):
    """PRD §3.4: "Exceeding that nested-min cap is `ERR_DURATION_EXCEEDS_POLICY`;
    a duration exactly equal to the cap passes, because both bounds of the duration
    gate are inclusive."

    m2's 90-day proposal faces min(policy 60, headroom 143) = 60 < 90, so the
    policy input binds; the 60-day proposal equals the cap and is accepted.

    Design: Difficulty/combinatorial_formula/match_duration_gate_nested_min_branch
    """
    _, _, _, _, app_b, _, employer, opening = _two_installation_world(api)
    created_version = opening["version"]

    too_long = _proposal(api, app_b["id"], opening["id"], employer["id"], "2026-10-01", "2026-12-30")
    validate_error(too_long, ApiErrorId.ERR_DURATION_EXCEEDS_POLICY)

    after_reject = fixtures.get_opening(api, opening["id"])
    assert after_reject["version"] == created_version and after_reject["filled_count"] == 0, (
        "a rejected proposal must leave the opening untouched"
    )

    accepted = _proposal(api, app_b["id"], opening["id"], employer["id"], "2026-10-01", "2026-11-30")
    match = validate_success(accepted, 201)
    assert match["match_status"] == "PROPOSED", "60 == min(60, 143) passes (inclusive bound)"


def _submitted_app_world(api):
    """Member (separation 2027-01-15) with an undecided application; AUTHORIZED
    employer with a capacity-1 opening."""
    w = fixtures.setup_member_with_application(api, approve=False)
    eo = fixtures.setup_employer_with_opening(api, capacity=1)
    return w, eo.employer, eo.opening


def test_match_create_state_beats_temporal(api):
    """PRD §3.4: "Beyond the universal checks, the gates fire in this pinned order:
    body foreign keys exist in declared input order — the application first
    (`ERR_APPLICATION_NOT_FOUND`), then the opening (`ERR_OPENING_NOT_FOUND`); the
    opening's version matches (`ERR_STALE_VERSION`); the caller owns the opening's
    employer (`ERR_FORBIDDEN_OWNERSHIP`); the application is `APPROVED`
    (`ERR_APPLICATION_NOT_APPROVED`); the opening is `OPEN` (`ERR_OPENING_NOT_OPEN`);
    the employer is `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`); the applicant
    member is `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."
    PRD §2.7 ranks the application-state check (rung 12) ahead of the match date
    gates (rung 18), so the 111-day proposal against a SUBMITTED application
    reports the state error, not the duration error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_match_create
    """
    w, employer, opening = _submitted_app_world(api)
    resp = _proposal(api, w.application["id"], opening["id"], employer["id"], "2026-10-01", "2027-01-20")
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)


def test_match_create_rejection_leaves_no_trace(api):
    """PRD §3.4: "Beyond the universal checks, the gates fire in this pinned order:
    body foreign keys exist in declared input order — the application first
    (`ERR_APPLICATION_NOT_FOUND`), then the opening (`ERR_OPENING_NOT_FOUND`); the
    opening's version matches (`ERR_STALE_VERSION`); the caller owns the opening's
    employer (`ERR_FORBIDDEN_OWNERSHIP`); the application is `APPROVED`
    (`ERR_APPLICATION_NOT_APPROVED`); the opening is `OPEN` (`ERR_OPENING_NOT_OPEN`);
    the employer is `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`); the applicant
    member is `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."
    A rejected proposal persists nothing: no match is listed for the application
    and the opening's version and filled ledger stay put.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_match_create
    """
    w, employer, opening = _submitted_app_world(api)
    _proposal(api, w.application["id"], opening["id"], employer["id"], "2026-10-01", "2027-01-20")

    data, meta = validate_paginated(
        api.list_matches(PROGRAM_OFFICE_HEADERS, params={"internship_application_id": w.application["id"]})
    )
    assert data == [] and meta["total_count"] == 0
    after = fixtures.get_opening(api, opening["id"])
    assert after["version"] == opening["version"]
    assert after["filled_count"] == 0


def _denied_app_world(api):
    """Member (separation 2027-01-15) whose application was DENIED; AUTHORIZED
    employer with a real capacity-1 opening."""
    w = fixtures.setup_member_with_application(api, approve=False)
    fixtures.deny_application(api, w.application["id"], reason="Manning requirements")
    eo = fixtures.setup_employer_with_opening(api, capacity=1)
    return w, eo.employer, eo.opening


def test_match_create_existence_beats_state(api):
    """PRD §3.4: "Beyond the universal checks, the gates fire in this pinned order:
    body foreign keys exist in declared input order — the application first
    (`ERR_APPLICATION_NOT_FOUND`), then the opening (`ERR_OPENING_NOT_FOUND`); the
    opening's version matches (`ERR_STALE_VERSION`); the caller owns the opening's
    employer (`ERR_FORBIDDEN_OWNERSHIP`); the application is `APPROVED`
    (`ERR_APPLICATION_NOT_APPROVED`); the opening is `OPEN` (`ERR_OPENING_NOT_OPEN`);
    the employer is `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`); the applicant
    member is `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."

    A proposal naming a DENIED application and a nonexistent opening surfaces the
    404, not the application-state 409.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_match_create
    """
    w, employer, opening = _denied_app_world(api)
    payload = factories.create_match_payload(
        w.application["id"], NON_EXISTENT_UUID, opening["version"], "2026-10-01", "2026-10-31"
    )
    resp = api.create_match(payload, make_employer_rep_headers(employer["id"]))
    validate_error(resp, ApiErrorId.ERR_OPENING_NOT_FOUND)


def test_match_create_not_found_leaves_no_trace(api):
    """PRD §2.7: "Ids supplied in the request body exist, validated in the body's
    declared input order — on a match proposal, `internship_application_id` first,
    then `employer_opening_id` — with the same resource-specific 404 family."
    The 404 rejection writes nothing: the denied application is untouched and no
    match exists for it.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_match_create
    """
    w, employer, opening = _denied_app_world(api)
    payload = factories.create_match_payload(
        w.application["id"], NON_EXISTENT_UUID, opening["version"], "2026-10-01", "2026-10-31"
    )
    api.create_match(payload, make_employer_rep_headers(employer["id"]))

    data, meta = validate_paginated(
        api.list_matches(PROGRAM_OFFICE_HEADERS, params={"internship_application_id": w.application["id"]})
    )
    assert data == [] and meta["total_count"] == 0
    assert fixtures.get_application(api, w.application["id"])["status"] == "DENIED"


def test_match_creation_blocked_while_application_submitted(api):
    """PRD §3.4: "Beyond the universal checks, the gates fire in this pinned order:
    body foreign keys exist in declared input order — the application first
    (`ERR_APPLICATION_NOT_FOUND`), then the opening (`ERR_OPENING_NOT_FOUND`); the
    opening's version matches (`ERR_STALE_VERSION`); the caller owns the opening's
    employer (`ERR_FORBIDDEN_OWNERSHIP`); the application is `APPROVED`
    (`ERR_APPLICATION_NOT_APPROVED`); the opening is `OPEN` (`ERR_OPENING_NOT_OPEN`);
    the employer is `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`); the applicant
    member is `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."

    Design: Difficulty/cross_entity_state_dependency/match_creation_requires_approved_application
    """
    w, employer, opening = _submitted_app_world(api)
    resp = _proposal(api, w.application["id"], opening["id"], employer["id"], "2026-10-01", "2026-10-31")
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_APPROVED)
    assert fixtures.get_opening(api, opening["id"])["version"] == opening["version"]


def test_match_creation_succeeds_after_commander_approval(api):
    """PRD §3.4: "A created match starts with `match_status` set to `PROPOSED` and
    `plan_status` set to `PLAN_DRAFT` — two parallel dimensions on one row."
    The byte-identical proposal that failed against SUBMITTED succeeds once the
    commander approves.

    Design: Difficulty/cross_entity_state_dependency/match_creation_requires_approved_application
    """
    w, employer, opening = _submitted_app_world(api)
    fixtures.approve_application(api, w.application["id"])
    resp = _proposal(api, w.application["id"], opening["id"], employer["id"], "2026-10-01", "2026-10-31")
    match = validate_success(resp, 201)
    assert match["match_status"] == "PROPOSED"
    assert match["plan_status"] == "PLAN_DRAFT"


def _suspended_employer_world(api):
    """A PROPOSED match with a PLAN_APPROVED plan whose employer is then suspended
    by a FAIL review."""
    ns = fixtures.setup_match(api, advance_to="plan_approved")
    fixtures.review_employer(api, ns.employer["id"], "FAIL", "documentation lapse")
    return ns


def test_match_approval_blocked_while_employer_suspended(api):
    """PRD §3.5: "Approval requires the match to be `PROPOSED`
    (`ERR_MATCH_NOT_PROPOSED`), the plan to be `PLAN_APPROVED`
    (`ERR_PLAN_NOT_APPROVED`) — a cross-dimension gate on the same row, tying the
    two parallel state machines together — the employer to be `AUTHORIZED`
    (`ERR_EMPLOYER_NOT_AUTHORIZED`), and the member to still be `ACTIVE_DUTY`
    (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."

    Design: Difficulty/cross_entity_state_dependency/match_approval_requires_authorized_employer
    """
    ns = _suspended_employer_world(api)
    resp = api.installation_decision(
        ns.match["id"], factories.installation_decision_payload("APPROVE"),
        fixtures.make_installation_authority_headers("auth-1"),
    )
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_AUTHORIZED)
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "PROPOSED"


def test_match_approval_succeeds_after_remediation(api):
    """PRD §3.3: "PASS is accepted while the employer is `AUTHORIZED`, `SUSPENDED`,
    or `AUTHORIZATION_LAPSED`; it (re-)moves the employer to `AUTHORIZED`, restamps
    `authorized_at`, and refreshes `next_review_due_date` to the clock date plus
    180 days."
    PRD §3.5: "Approval moves `match_status` to `INSTALLATION_APPROVED` and stamps
    `installation_decision_by` with the authority's `X-User-ID` and
    `installation_decision_reason` with the reason."

    Design: Difficulty/cross_entity_state_dependency/match_approval_requires_authorized_employer
    """
    ns = _suspended_employer_world(api)
    fixtures.review_employer(api, ns.employer["id"], "PASS", "remediated")
    decided = fixtures.installation_decision(api, ns.match["id"], "APPROVE")
    assert decided["match_status"] == "INSTALLATION_APPROVED"


def test_match_temporal_input_gates(api):
    """PRD §3.4: "The duration in whole days — `end_date` minus `start_date`, with
    `end_date` treated as an exclusive bound — must be at least the 30-day minimum
    (`MIN_INTERNSHIP_DURATION_DAYS`), else `ERR_DURATION_BELOW_MINIMUM`."
    PRD §3.4: "A `start_date` earlier than the logical clock date is rejected with
    `ERR_START_DATE_IN_PAST`."
    PRD §2.7 pins the date-gate order: "`ERR_START_DATE_IN_PAST`, then
    `ERR_DURATION_BELOW_MINIMUM`, then `ERR_DURATION_EXCEEDS_POLICY`".

    Design: Corner/validations/match_temporal_input_gates
    """
    w = fixtures.setup_member_with_application(api)
    eo = fixtures.setup_employer_with_opening(api, capacity=2)
    employer, opening = eo.employer, eo.opening

    too_short = _proposal(api, w.application["id"], opening["id"], employer["id"],
                          "2026-10-01", "2026-10-21")
    validate_error(too_short, ApiErrorId.ERR_DURATION_BELOW_MINIMUM)

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    past_start = _proposal(api, w.application["id"], opening["id"], employer["id"],
                           "2026-10-01", "2026-10-31")
    validate_error(past_start, ApiErrorId.ERR_START_DATE_IN_PAST)

    after = fixtures.get_opening(api, opening["id"])
    assert after["version"] == opening["version"] and after["filled_count"] == 0


def test_skills_subset_enforced(api):
    """PRD §3.4: "The member's `skills` must be a superset of the opening's
    `required_skills`, else `ERR_SKILLS_MISMATCH`."

    Design: Corner/validations/skills_subset_enforced
    """
    w = fixtures.setup_member_with_application(api, member_overrides={"skills": ["LOGISTICS"]})
    employer = fixtures.create_authorized_employer(api)
    opening = fixtures.create_opening(
        api, employer["id"], title="CDL Driver Intern", required_skills=["LOGISTICS", "CDL"]
    )

    missing = _proposal(api, w.application["id"], opening["id"], employer["id"],
                        "2026-10-01", "2026-10-31")
    validate_error(missing, ApiErrorId.ERR_SKILLS_MISMATCH)

    fixtures.patch_member(api, w.member["id"], skills=["LOGISTICS", "CDL"])
    accepted = _proposal(api, w.application["id"], opening["id"], employer["id"],
                         "2026-10-01", "2026-10-31")
    match = validate_success(accepted, 201)
    assert match["match_status"] == "PROPOSED"


def test_location_constraint_on_site_region(api):
    """PRD §3.4: "For an `ON_SITE` opening, the opening's `region_code` must equal
    the member's home installation `region_code`, else
    `ERR_LOCATION_CONSTRAINT_VIOLATION`; `REMOTE` openings impose no region
    constraint."

    Design: Corner/validations/location_constraint_on_site_region
    """
    w = fixtures.setup_member_with_application(api)  # home installation region R1
    employer = fixtures.create_authorized_employer(api)
    onsite = fixtures.create_opening(
        api, employer["id"], title="Depot Intern (onsite)", location_type="ON_SITE", region_code="R2"
    )
    remote = fixtures.create_opening(api, employer["id"], title="Remote Analyst Intern")

    wrong_region = _proposal(api, w.application["id"], onsite["id"], employer["id"],
                             "2026-10-01", "2026-10-31")
    validate_error(wrong_region, ApiErrorId.ERR_LOCATION_CONSTRAINT_VIOLATION)

    accepted = _proposal(api, w.application["id"], remote["id"], employer["id"],
                         "2026-10-01", "2026-10-31")
    match = validate_success(accepted, 201)
    assert match["match_status"] == "PROPOSED"
