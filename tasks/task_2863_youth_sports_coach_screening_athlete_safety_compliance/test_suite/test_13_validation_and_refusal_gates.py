"""Input rules, cross-aggregate scope rules and the windows that open on a schedule.

The tests here take one gate at a time and prove three things about it: that the
violating request is refused with the catalogued error, that nothing was written
on the way out, and that the corrected request succeeds against the identical
setup.  Where two gates fire at once the order of refusal of PRD 2.8 decides
which error the caller hears.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_counters,
    assert_instant_equals,
    assert_money_equals,
    assert_pagination_meta,
    assert_state,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
BETA_BLADES = {
    "name": "Beta Blades",
    "state_code": "NV",
    "roster_size_attested": 2,
    "minor_athlete_program": True,
    "initial_escrow_cents": 100000,
}
THIN_ICE = {
    "name": "Thin Ice Skating",
    "state_code": "MN",
    "roster_size_attested": 2,
    "minor_athlete_program": True,
    "initial_escrow_cents": 1000,
}
SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    "pass_score": 80,
}


def _epoch(api: ApiClient) -> None:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))


def _club(api: ApiClient, payload: Dict[str, Any] = ALPHA_AQUATICS) -> Dict[str, Any]:
    return get_success_data(api.charter_club(payload, NGB_ADMIN_HEADERS), 201)


def _member(
    api: ApiClient,
    club_id: str,
    name: str,
    email: str,
    dob: str,
    role_type: str = "VOLUNTEER",
    contact: bool = False,
    codes: Iterable[str] = ("CA",),
) -> Dict[str, Any]:
    return get_success_data(
        api.register_member(
            {
                "club_id": club_id,
                "full_name": name,
                "email": email,
                "role_type": role_type,
                "has_minor_athlete_contact": contact,
                "date_of_birth": dob,
                "jurisdiction_codes": list(codes),
            },
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _live_club_version(api: ApiClient, club_id: str) -> int:
    return get_success_data(
        api.get_club(club_id, make_club_admin_headers(club_id))
    )["version"]


def _live_member_version(api: ApiClient, member_id: str, headers: Dict[str, str]) -> int:
    return get_success_data(api.get_member(member_id, headers))["version"]


def _clear_screening(api: ApiClient, club_id: str, member_id: str) -> None:
    """Order, return and adjudicate CLEAR so the member reaches CLEARED (PRD 3.3)."""
    headers = make_club_admin_headers(club_id)
    order = get_success_data(
        api.order_screening(
            member_id,
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club_id),
            },
            headers,
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )


def _complete_ss101(api: ApiClient, club_id: str, member_id: str, score: int) -> None:
    """Assign SS101 and carry it to COMPLETED so training_status is CURRENT (PRD 3.4)."""
    headers = make_club_admin_headers(club_id)
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": member_id,
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], headers))
    get_success_data(api.complete_training(assignment["id"], {"score": score}, headers))


def test_an_underfunded_escrow_refuses_the_order_and_funding_it_lets_the_same_call_through(
    api: ApiClient,
) -> None:
    """A club holding 1000 cents cannot buy a 2500-cent screen, and the refusal moves no money.

    PRD 2.8 says:
    "The club's `escrow_balance_cents` covers the computed charge — otherwise `ERR_ESCROW_INSUFFICIENT`."

    PRD 3.1 says:
    "Screening is prepaid. Adding money to the escrow is the only action in the platform that raises `total_funded_cents`, a lifetime total that never decreases: a caller supplies `amount_cents`, a positive whole number of cents, and both `escrow_balance_cents` and `total_funded_cents` rise by that amount while the club's `version` advances by one."

    PRD 3.2 says:
    "Before the order is written, six conditions must hold: the chartering club's posture must not be `FROZEN`; the member's screening dimension must currently be `UNSCREENED`, `CLEARED`, or `EXPIRED`; the member must not be `DISQUALIFIED`, which is a terminal state from which no new screen may ever be ordered and which is refused with `ERR_MEMBER_DISQUALIFIED`; no other screening order for that member may currently be in status `ORDERED` or `RESULT_RETURNED`, since a second in-flight screen would double-debit the escrow; the pinned club version must match; and the club's `escrow_balance_cents` must be at least the charge the platform is about to compute, failing which the order is refused with `ERR_ESCROW_INSUFFICIENT`."
    "The escrow check is the very last gate in the entire order of refusal, so a request that is both unfunded and unsafe always reports the safety problem."
    "Step one takes the tier base fee: 2,500 cents for `TIER_1`, 4,800 cents for `TIER_2`, and 9,200 cents for `TIER_3`."

    Design: Corner/validations/escrow_shortfall_blocks_the_order_until_the_club_funds_it
    """
    _epoch(api)
    club = _club(api, THIN_ICE)
    headers = make_club_admin_headers(club["id"])
    member = _member(
        api,
        club["id"],
        "Ez Ives",
        "ez.ives@thinice.test",
        "1996-12-18",
        codes=("MN",),
    )
    assert_state(member, "required_tier", "TIER_1")

    pinned = _live_club_version(api, club["id"])
    validate_error(
        api.order_screening(
            member["id"],
            {"expedited": False, "expected_club_version": pinned},
            headers,
        ),
        ApiErrorId.ESCROW_INSUFFICIENT,
        409,
    )
    unmoved = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(unmoved, "escrow_balance_cents", 1000)
    assert_money_equals(unmoved, "total_funded_cents", 1000)
    assert unmoved["version"] == pinned, (
        f"the refused order must not touch the club: {unmoved['version']} != {pinned}"
    )

    funded = validate_success(
        api.fund_escrow(club["id"], {"amount_cents": 5000}, headers)
    )
    assert_money_equals(funded, "escrow_balance_cents", 6000)
    assert_money_equals(funded, "total_funded_cents", 6000)

    order = validate_success(
        api.order_screening(
            member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )
    assert_money_equals(order, "charged_cents", 2500)

    after = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(after, "escrow_balance_cents", 3500)
    assert_money_equals(after, "total_funded_cents", 6000)
    assert_state(
        validate_success(api.get_member(member["id"], headers)),
        "screening_status",
        "SCREENING_ORDERED",
    )


def test_the_renewal_window_is_shut_one_second_early_and_open_on_the_ninetieth_day(
    api: ApiClient,
) -> None:
    """An eligible_through of 2027-08-01 opens the window at exactly 2027-05-03T00:00:00Z.

    PRD 2.5 says:
    "An `NgbAdmin` may reposition the clock to any instant by supplying `to_iso8601`; the response reports the resulting `current_utc`."
    "Day arithmetic anywhere in this document adds exact multiples of 24 hours, and all instants are ISO 8601 UTC with three fractional digits."

    PRD 2.8 says:
    "The renewal window is open — otherwise `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    PRD 3.5 says:
    "The club's own administrator renews it, supplying a single input, the boolean `attestation_signed`, which must be true."
    "Renewal is available from `membership_status` of `LAPSED`, closing the `ACTIVE → LAPSED → ACTIVE` cycle, and also from `ACTIVE` as an early renewal that leaves the status `ACTIVE` — the self-loop is what makes the renewal window observable at all."
    "The window opens 90 days before the member's `eligible_through`: the logical clock must have reached or passed `eligible_through` minus 90 days."
    "A renewal attempted while the clock is still strictly before that instant, or one whose `attestation_signed` is false, is refused with `ERR_RENEWAL_WINDOW_NOT_OPEN` — and because the window check sits below the state check in the order of refusal, a still-`ACTIVE` member renewed too early reports the window error rather than an invalid-state error."
    "A successful renewal sets `membership_status` to `ACTIVE` and `last_renewed_at` to the logical clock, re-runs the risk score so `risk_points` and `required_tier` reflect any history accumulated since registration, re-runs the audit-snapshot projection and re-stamps `eligible_through`, re-derives `records_retained_through` and `contact_eligibility`, and advances the member's `version` by one."

    Design: Corner/validations/renewal_window_opens_exactly_ninety_days_before_eligible_through
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(api, club["id"], "Rae Wynn", "rae.wynn@alpha.test", "1990-01-19")
    _clear_screening(api, club["id"], member["id"])
    _complete_ss101(api, club["id"], member["id"], 95)

    ready = validate_success(api.get_member(member["id"], headers))
    assert_instant_equals(ready["eligible_through"], "2027-08-01T00:00:00.000Z")
    assert_state(ready, "membership_status", "ACTIVE")
    assert ready["last_renewed_at"] is None, (
        f"nothing has renewed this membership yet: {ready['last_renewed_at']!r}"
    )

    # 2027-08-01 minus 90 exact days is 2027-05-03T00:00:00Z.
    get_success_data(api.set_clock("2027-05-02T23:59:59Z", NGB_ADMIN_HEADERS))
    validate_error(
        api.renew_membership(member["id"], {"attestation_signed": True}, headers),
        ApiErrorId.RENEWAL_WINDOW_NOT_OPEN,
        409,
    )
    refused = validate_success(api.get_member(member["id"], headers))
    assert refused["last_renewed_at"] is None, (
        f"the refused renewal stamped a date: {refused['last_renewed_at']!r}"
    )
    assert_state(refused, "membership_status", "ACTIVE")

    get_success_data(api.set_clock("2027-05-03T00:00:00Z", NGB_ADMIN_HEADERS))
    renewed = validate_success(
        api.renew_membership(member["id"], {"attestation_signed": True}, headers)
    )
    assert_state(renewed, "membership_status", "ACTIVE")
    assert_instant_equals(renewed["last_renewed_at"], "2027-05-03T00:00:00.000Z")
    assert_instant_equals(renewed["eligible_through"], "2027-08-01T00:00:00.000Z")


def test_an_email_already_used_at_another_club_is_a_duplicate_whatever_its_letter_case(
    api: ApiClient,
) -> None:
    """Member email is a governing-body-wide case-insensitive key, and course code is a global one.

    PRD 2.8 says:
    "Uniqueness holds: a member's `email` is unique across the entire governing body compared case-insensitively (`ERR_DUPLICATE_MEMBER_EMAIL`), and a course's `code` is unique across all courses (`ERR_DUPLICATE_COURSE_CODE`)."

    PRD 3.1 says:
    "Registration is blocked at a club whose posture is `FROZEN`, and a duplicate email is refused with `ERR_DUPLICATE_MEMBER_EMAIL`."

    PRD 3.4 says:
    "A course carries a `code` that is its natural key — 3 to 20 characters of uppercase letters, digits, and hyphens, globally unique, with a collision refused as `ERR_DUPLICATE_COURSE_CODE` — a human-readable `title`, a `validity_days` figure between 1 and 3,650 stating how long a completion of that course stays current, a `delivery_mode` of either `ONLINE` or `IN_PERSON`, a `required_for_tiers` list naming which screening tiers must hold this course before athlete contact (a non-empty duplicate-free subset of `TIER_1`, `TIER_2`, and `TIER_3`), and a `pass_score` between 0 and 100 that defaults to 80."
    "Completion requires status `IN_PROGRESS` and a `score` between 0 and 100 that reaches or exceeds the referenced course's `pass_score`; a score below the pass mark is not a completion."
    "The assignment moves `IN_PROGRESS → COMPLETED`, stamping `completed_at` from the clock, the submitted `score`, and `expires_at` as `completed_at` plus that course's `validity_days`."

    PRD 2.3 says:
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true exactly when rows remain beyond the current window."

    Design: Corner/validations/member_email_uniqueness_is_case_insensitive_and_crosses_clubs
    """
    _epoch(api)
    alpha = _club(api)
    beta = _club(api, BETA_BLADES)
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    _member(api, alpha["id"], "Ida Stern", "ida.stern@alpha.test", "1991-01-07")

    # The same address at a different club, differing only in case.
    validate_error(
        api.register_member(
            {
                "club_id": beta["id"],
                "full_name": "Ida Stern",
                "email": "IDA.STERN@Alpha.Test",
                "role_type": "CHAPERONE",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1991-01-07",
                "jurisdiction_codes": ["NV"],
            },
            make_club_admin_headers(beta["id"]),
        ),
        ApiErrorId.DUPLICATE_MEMBER_EMAIL,
        409,
    )
    # The same natural key with an entirely different body is still a collision.
    validate_error(
        api.publish_course(
            {
                "code": "SS101",
                "title": "Abuse Prevention Core (revised)",
                "validity_days": 730,
                "delivery_mode": "IN_PERSON",
                "required_for_tiers": ["TIER_3"],
                "pass_score": 90,
            },
            NGB_ADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_COURSE_CODE,
        409,
    )

    beta_headers = make_club_admin_headers(beta["id"])
    second = validate_success(
        api.register_member(
            {
                "club_id": beta["id"],
                "full_name": "Ida Stern",
                "email": "ida.stern@betablades.test",
                "role_type": "CHAPERONE",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1991-01-07",
                "jurisdiction_codes": ["NV"],
            },
            beta_headers,
        ),
        201,
    )
    assert second["club_id"] == beta["id"], (
        f"the second registration belongs to Beta Blades: {second['club_id']}"
    )

    # The refused publication left SS101 alone: a score of 85 still passes the
    # original 80 mark, and the completion expires 365 days on, not 730.
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": second["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            beta_headers,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], beta_headers))
    completed = validate_success(
        api.complete_training(assignment["id"], {"score": 85}, beta_headers)
    )
    assert_instant_equals(completed["expires_at"], "2027-08-01T00:00:00.000Z")

    rows, meta = validate_paginated(api.list_club_members(beta["id"], beta_headers))
    assert_pagination_meta(meta, total=1, limit=10, offset=0)
    assert [row["id"] for row in rows] == [second["id"]], (
        f"Beta Blades holds exactly one member: {[row['id'] for row in rows]}"
    )


def test_private_messaging_and_an_uncopied_parent_are_both_refused_on_the_same_placement(
    api: ApiClient,
) -> None:
    """Only the group channel with a parent copy clears both conditional clauses of the policy.

    PRD 2.8 says:
    "The electronic-communication policy is satisfied — otherwise `ERR_ELECTRONIC_COMM_NOT_PERMITTED`."

    PRD 3.6 says:
    "A new placement is written in status `PENDING`, with `activated_at`, `eligibility_snapshot_version`, and `suspended_reason` all null and `electronic_comm_authorized` false, and the club's `restricted_member_count` and `compliance_posture` are re-derived."
    "The club administrator activates the placement supplying only `expected_member_version`, and six conditions must hold: the placement must be in status `PENDING`, else `ERR_COACH_ASSIGNMENT_INVALID_STATE`; the pinned member version must match, else `ERR_STALE_MEMBER_VERSION`; the placement's club must be at posture `OPEN`, so both `RESTRICTED` and `FROZEN` block activation; the member must not be `DISQUALIFIED`; the member must be under no permanent and no active restriction, else `ERR_CONTACT_NOT_PERMITTED`; and the member's `screening_status` must be `CLEARED` and `training_status` must be `CURRENT`, reported as `ERR_SCREENING_NOT_CURRENT` and `ERR_TRAINING_NOT_CURRENT` respectively."
    "Four conditions must all hold, and any failure is reported as `ERR_ELECTRONIC_COMM_NOT_PERMITTED`: the placement must be in status `ACTIVE`; the member's `contact_eligibility` must be `ELIGIBLE`; whenever the governing club's `minor_athlete_program` is true, `channel_kind` must be anything other than `PRIVATE_DIRECT_MESSAGE`, because one-to-one private messaging with minor athletes is prohibited outright; and whenever the member's `has_minor_athlete_contact` is true, `parent_copy_required` must be true."
    "On success the placement records `electronic_comm_authorized` as true along with the supplied `electronic_comm_channel_kind` and `parent_copy_required`."

    PRD 3.1 says:
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    "The score selects a screening tier and writes it to `required_tier`: a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`."

    Design: Corner/validations/electronic_communication_authorization_enforces_channel_and_parent_copy
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(
        api,
        club["id"],
        "Eve Chase",
        "eve.chase@alpha.test",
        "1987-02-20",
        role_type="CHAPERONE",
        contact=True,
    )
    # 25 for the chaperone role plus 25 for minor-athlete contact.
    assert_counters(member, risk_points=50)
    assert_state(member, "required_tier", "TIER_2")
    _clear_screening(api, club["id"], member["id"])
    _complete_ss101(api, club["id"], member["id"], 91)

    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": "Age Group Squad",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-05-31T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    assert placement["electronic_comm_authorized"] is False, (
        f"a new placement authorizes nothing: {placement['electronic_comm_authorized']!r}"
    )
    ready = validate_success(api.get_member(member["id"], headers))
    assert_state(ready, "contact_eligibility", "ELIGIBLE")
    activated = get_success_data(
        api.activate_coach_assignment(
            placement["id"], {"expected_member_version": ready["version"]}, headers
        )
    )
    assert_state(activated, "status", "ACTIVE")

    # The club runs a minor-athlete program, so one-to-one messaging is out.
    validate_error(
        api.authorize_electronic_communication(
            placement["id"],
            {"channel_kind": "PRIVATE_DIRECT_MESSAGE", "parent_copy_required": True},
            headers,
        ),
        ApiErrorId.ELECTRONIC_COMM_NOT_PERMITTED,
        409,
    )
    # This member has minor-athlete contact, so a parent must be copied.
    validate_error(
        api.authorize_electronic_communication(
            placement["id"],
            {"channel_kind": "GROUP_EMAIL", "parent_copy_required": False},
            headers,
        ),
        ApiErrorId.ELECTRONIC_COMM_NOT_PERMITTED,
        409,
    )
    still_closed = validate_success(api.get_coach_assignment(placement["id"], headers))
    assert still_closed["electronic_comm_authorized"] is False, (
        "a refused authorization must not flip the flag: "
        f"{still_closed['electronic_comm_authorized']!r}"
    )
    assert still_closed["electronic_comm_channel_kind"] is None, (
        f"no channel was stored: {still_closed['electronic_comm_channel_kind']!r}"
    )

    authorized = validate_success(
        api.authorize_electronic_communication(
            placement["id"],
            {"channel_kind": "GROUP_EMAIL", "parent_copy_required": True},
            headers,
        )
    )
    assert authorized["electronic_comm_authorized"] is True, (
        f"the compliant channel is authorized: {authorized['electronic_comm_authorized']!r}"
    )
    assert_state(authorized, "electronic_comm_channel_kind", "GROUP_EMAIL")
    assert authorized["parent_copy_required"] is True, (
        f"the parent copy flag is retained: {authorized['parent_copy_required']!r}"
    )


def test_a_wrongly_scoped_paused_body_reports_the_scope_mismatch_and_not_the_pause(
    api: ApiClient,
) -> None:
    """Scope sits above intake in the order of refusal, so the body that trips both reports scope.

    PRD 2.8 says:
    "The case's `allegation_category` falls within the target body's `scope_categories` — otherwise `ERR_BODY_SCOPE_MISMATCH`."
    "The target body's `intake_status` is `ACCEPTING` — otherwise `ERR_BODY_INTAKE_PAUSED`."
    "Because many operations are guarded by several rules at once, the platform evaluates its checks in one fixed order and reports **the first failure only**."

    PRD 3.8 says:
    "A body carries its `name`, a `scope_categories` list naming the allegation categories it accepts — a non-empty duplicate-free subset of `SEXUAL_MISCONDUCT`, `PHYSICAL_ABUSE`, `EMOTIONAL_MISCONDUCT`, `POLICY_VIOLATION`, and `FAILURE_TO_REPORT` — an `intake_status` of either `ACCEPTING` or `PAUSED` that defaults to `ACCEPTING`, and a `max_open_cases` ceiling of at least one."
    "Its `open_case_count` starts at zero and is maintained by the platform as the number of cases currently sitting in status `ROUTED` against that body."
    "An officer routes the case by naming an `investigating_body_id`, and three checks run in order: the case's `allegation_category` must appear in that body's `scope_categories`, else `ERR_BODY_SCOPE_MISMATCH`; the body's `intake_status` must be `ACCEPTING`, else `ERR_BODY_INTAKE_PAUSED`; and the body's `open_case_count` must be strictly below its `max_open_cases`, else `ERR_BODY_CASELOAD_EXCEEDED`."
    "Routing moves the case `INTAKE_REVIEW → ROUTED`, stamps `investigating_body_id` and `routed_at` from the clock, and increments both the body's `open_case_count` and its `version` by one."

    Design: Corner/validations/routing_reports_body_scope_before_intake_pause
    """
    _epoch(api)
    club = _club(api)
    member = _member(
        api,
        club["id"],
        "Bo Reid",
        "bo.reid@alpha.test",
        "1986-03-21",
        role_type="ASSISTANT_COACH",
        contact=True,
    )
    wrong = get_success_data(
        api.register_investigating_body(
            {
                "name": "Physical Abuse Panel",
                "scope_categories": ["PHYSICAL_ABUSE"],
                "max_open_cases": 5,
                "intake_status": "PAUSED",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    paused = get_success_data(
        api.register_investigating_body(
            {
                "name": "Conduct Panel East",
                "scope_categories": ["EMOTIONAL_MISCONDUCT"],
                "max_open_cases": 5,
                "intake_status": "PAUSED",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    accepting = get_success_data(
        api.register_investigating_body(
            {
                "name": "Conduct Panel West",
                "scope_categories": ["EMOTIONAL_MISCONDUCT"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "EMOTIONAL_MISCONDUCT",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "raised voice and belittling remarks at practice",
                "occurred_at": "2026-07-31T23:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )

    # This body is both wrongly scoped and paused; scope is checked first.
    validate_error(
        api.route_case(
            case["id"],
            {"investigating_body_id": wrong["id"]},
            OFFICER_INTAKE_HEADERS,
        ),
        ApiErrorId.BODY_SCOPE_MISMATCH,
        409,
    )
    validate_error(
        api.route_case(
            case["id"],
            {"investigating_body_id": paused["id"]},
            OFFICER_INTAKE_HEADERS,
        ),
        ApiErrorId.BODY_INTAKE_PAUSED,
        409,
    )

    routed = validate_success(
        api.route_case(
            case["id"],
            {"investigating_body_id": accepting["id"]},
            OFFICER_INTAKE_HEADERS,
        )
    )
    assert_state(routed, "status", "ROUTED")
    assert routed["investigating_body_id"] == accepting["id"], (
        f"the case names the accepting body: {routed['investigating_body_id']}"
    )
    assert_instant_equals(routed["routed_at"], "2026-08-01T00:00:00.000Z")

    assert_counters(
        validate_success(api.get_investigating_body(accepting["id"], NGB_ADMIN_HEADERS)),
        open_case_count=1,
    )
    for refused in (wrong, paused):
        assert_counters(
            validate_success(
                api.get_investigating_body(refused["id"], NGB_ADMIN_HEADERS)
            ),
            open_case_count=0,
        )


def test_a_resolvable_id_from_outside_the_parents_scope_is_a_scope_violation_not_a_miss(
    api: ApiClient,
) -> None:
    """Both ids below exist, and both are still refused because they sit outside their parent.

    PRD 2.8 says:
    "Every id or natural key named in the body resolves — a `club_id`, a `member_id`, an `investigating_body_id`, each entry of `sampled_member_ids`, and a `course_code` against a published course — otherwise `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_INVESTIGATING_BODY_NOT_FOUND`, or `ERR_TRAINING_COURSE_NOT_FOUND`."
    "Cross-aggregate referential rules hold: an interim measure's `member_id` equals the case's `reported_member_id`, every entry of an audit's `sampled_member_ids` is a member of the audited club, and a finding's `member_id`, when supplied, is one of that audit's sampled members — otherwise `ERR_CLUB_SCOPE_VIOLATION`."

    PRD 3.8 says:
    "An officer imposes one against an open case, supplying the `member_id` — which must equal the case's `reported_member_id`, else `ERR_CLUB_SCOPE_VIOLATION` — the `measure_kind`, which is one of `NO_CONTACT_DIRECTIVE`, `TEMPORARY_SUSPENSION`, or `SUPERVISED_CONTACT_ONLY`, the inclusive `effective_from` instant, an optional `effective_to` inclusive end (omitting it means the restriction is open-ended, and when present it must be at or after `effective_from`), and the `expected_member_version` of §2.6."

    PRD 3.9 says:
    "The sample list holds between zero and fifty entries with no duplicates, and every entry must be a member of the audited club — a foreign member in the sample is refused with `ERR_CLUB_SCOPE_VIOLATION`, and an id that matches no member at all with `ERR_MEMBER_NOT_FOUND`."

    PRD 3.1 says:
    "Otherwise the value is `RESTRICTED` when any interim measure against the member stands in status `ACTIVE`, or when the screening dimension is `UNSCREENED`, `SCREENING_ORDERED`, `FLAGGED`, or `EXPIRED`, or when `training_status` is `NEVER` or `LAPSED`."

    Design: Corner/validations/body_referenced_ids_must_stay_inside_their_parents_scope
    """
    _epoch(api)
    alpha = _club(api)
    beta = _club(api, BETA_BLADES)
    alpha_headers = make_club_admin_headers(alpha["id"])
    reported = _member(
        api,
        alpha["id"],
        "Sam One",
        "sam.one@alpha.test",
        "1985-04-22",
        role_type="OFFICIAL",
        contact=True,
    )
    bystander = _member(
        api,
        alpha["id"],
        "Sam Two",
        "sam.two@alpha.test",
        "1985-05-23",
        role_type="OFFICIAL",
        contact=True,
    )
    foreign = _member(
        api,
        beta["id"],
        "Sam Three",
        "sam.three@beta.test",
        "1985-06-24",
        role_type="OFFICIAL",
        contact=True,
        codes=("NV",),
    )
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Policy Panel",
                "scope_categories": ["POLICY_VIOLATION"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": alpha["id"],
                "reported_member_id": reported["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "travel policy breach reported the same evening",
                "occurred_at": "2026-07-31T23:30:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    get_success_data(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        )
    )

    # A real member of the same club, but not the one this case names.
    validate_error(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": bystander["id"],
                "measure_kind": "NO_CONTACT_DIRECTIVE",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-01T00:00:00Z",
                "expected_member_version": _live_member_version(
                    api, bystander["id"], alpha_headers
                ),
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        ApiErrorId.CLUB_SCOPE_VIOLATION,
        403,
    )
    # A real member, but of a different club than the one under audit.
    validate_error(
        api.open_club_audit(
            {
                "club_id": alpha["id"],
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-06-30T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": [reported["id"], foreign["id"]],
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        ApiErrorId.CLUB_SCOPE_VIOLATION,
        403,
    )

    _, measures = validate_paginated(
        api.list_interim_measures(NGB_ADMIN_HEADERS, case_id=case["id"])
    )
    assert_pagination_meta(measures, total=0, limit=10, offset=0)
    _, audits = validate_paginated(
        api.list_audits_of_club(alpha["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_pagination_meta(audits, total=0, limit=10, offset=0)
    assert_state(
        validate_success(api.get_member(bystander["id"], alpha_headers)),
        "contact_eligibility",
        "RESTRICTED",
    )


def test_a_disqualified_member_is_turned_away_from_training_placement_and_lodging_alike(
    api: ApiClient,
) -> None:
    """Priority 13 is a subject-state gate, so all three creations report the disqualification.

    PRD 2.8 says:
    "The subject member's `screening_status` is not `DISQUALIFIED` — otherwise `ERR_MEMBER_DISQUALIFIED`."

    PRD 3.3 says:
    "On `DISQUALIFYING_RECORD` the order becomes `ADJUDICATED` with `adjudicated_at` stamped and `expires_at` left null, the member's screening dimension moves `FLAGGED → DISQUALIFIED` with `screening_expires_at` cleared to null, and `contact_eligibility` is set to `PROHIBITED`."
    "`DISQUALIFIED` is terminal on the screening dimension and `REVOKED` is terminal on the membership dimension: no later action returns the individual to service."

    PRD 3.4 says:
    "An assignment may not be created against a member whose screening dimension is `DISQUALIFIED`."

    PRD 3.6 says:
    "Creation is blocked at a `FROZEN` club, blocked for a `DISQUALIFIED` member, and blocked for a member under any permanent restriction with `ERR_CONTACT_NOT_PERMITTED`."

    PRD 3.7 says:
    "Bookings are made by the club administrator against a club that is not `FROZEN`, for a member who is not `DISQUALIFIED` and who is under no permanent or active restriction."

    PRD 2.9 says:
    "`restricted_member_count` counts the distinct members who hold a coach placement at this club in status `ACTIVE` or `SUSPENDED` and whose `contact_eligibility` is `RESTRICTED` or `PROHIBITED`."

    Design: Corner/validations/disqualified_member_is_refused_training_placement_and_lodging
    """
    _epoch(api)
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(api, club["id"], "Dez Zane", "dez.zane@alpha.test", "1984-07-25")
    order = get_success_data(
        api.order_screening(
            member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"],
            {"vendor_disposition": "RECORD_FOUND"},
            SCREENING_VENDOR_HEADERS,
        )
    )
    adjudicated = get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {
                "disposition": "DISQUALIFYING_RECORD",
                "rationale": "conviction appears on the disqualifying criteria list",
            },
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    assert_state(adjudicated, "disposition", "DISQUALIFYING_RECORD")

    # This member holds no placement, so the club itself is untouched: the
    # refusals below cannot be coming from a posture gate.
    standing = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_state(standing, "compliance_posture", "OPEN")
    assert_counters(standing, restricted_member_count=0)

    validate_error(
        api.assign_training(
            {
                "member_id": member["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            headers,
        ),
        ApiErrorId.MEMBER_DISQUALIFIED,
        409,
    )
    validate_error(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": "Novice Group",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-05-31T00:00:00Z",
            },
            headers,
        ),
        ApiErrorId.MEMBER_DISQUALIFIED,
        409,
    )
    validate_error(
        api.book_room_stay(
            club["id"],
            {
                "occupant_kind": "ADULT_MEMBER",
                "member_id": member["id"],
                "trip_label": "FALL_TRIP",
                "room_number": "301",
                "check_in": "2026-10-01T15:00:00Z",
                "check_out": "2026-10-03T11:00:00Z",
            },
            headers,
        ),
        ApiErrorId.MEMBER_DISQUALIFIED,
        409,
    )

    final = validate_success(api.get_member(member["id"], headers))
    assert_state(final, "screening_status", "DISQUALIFIED")
    assert_state(final, "contact_eligibility", "PROHIBITED")
    assert final["screening_expires_at"] is None, (
        f"disqualification clears the horizon: {final['screening_expires_at']!r}"
    )
    _, meta = validate_paginated(
        api.list_member_screening_orders(member["id"], headers)
    )
    assert_pagination_meta(meta, total=1, limit=10, offset=0)
