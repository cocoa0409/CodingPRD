"""Endpoint behaviour, identity and role gating, and optimistic concurrency.

Four concerns share this file because they all turn on the ordered refusal ladder
of PRD §2.5. The endpoint group covers the provider amendment that re-derives both
capacity postures, the referral a ``REFER`` screening outcome opens by itself, and
the composition of referral list filters with pagination. The identity group covers
the 401 that precedes everything else and the 403 that outranks body validation.
The ownership group covers the guardian, assigned-evaluator and case-chair checks.
The concurrency group covers the three expected-version inputs of PRD §2.6 and the
immediate visibility of every cascade described in PRD §2.9.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_date_equals,
    assert_instant,
    assert_page_meta,
    assert_ordered_by_created_at,
    assert_provider_minute_ledger,
    assert_version_incremented,
)
from test_helpers.constants import (
    INITIAL_LOGICAL_CLOCK,
    MISSING_UUID,
    plus_minutes,
    ts,
)
from test_helpers.test_users import (
    TEST_USERS,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_chair_headers,
    make_evaluator_headers,
    make_headers,
    make_parent_headers,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]
DISTRICT_ADMIN = TEST_USERS["district_admin_headers"]


# --------------------------------------------------------------- local setup helpers
def _draft_plan_with_two_slp_lines(api, max_weekly_service_minutes: int = 400):
    """A DRAFT itinerant plan carrying two PROPOSED SLP lines of 150 and 100 minutes.

    Both lines are delivered at the district centre, so the provider's travel
    calculation sees a single distinct location.
    """
    context = fx.setup_draft_plan(api, setting="ITINERANT_ONLY")
    context["provider"] = fx.register_provider(
        api,
        discipline="SLP",
        max_weekly_service_minutes=max_weekly_service_minutes,
    )
    context["first_line"] = fx.add_line(
        api,
        context["plan"]["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
    )
    context["second_line"] = fx.add_line(
        api,
        context["plan"]["id"],
        discipline="SLP",
        weekly_minutes=100,
        delivery_model="DIRECT",
    )
    return context


def _event_with_two_booked_children(api):
    """An OPEN event with thirty-minute appointments and two children booked into it."""
    event = fx.create_open_screening_event(
        api,
        slot_capacity=4,
        slot_length_minutes=30,
        window_start_utc=ts("2026-08-10T09:00:00Z"),
        window_end_utc=ts("2026-08-10T12:00:00Z"),
    )
    first_child = fx.register_child(api)
    second_child = fx.register_child(api)
    first_slot = fx.book_slot(
        api, event, first_child["id"], slot_start_utc="2026-08-10T09:00:00Z"
    )
    event = fx.read_event(api, event["id"])
    second_slot = fx.book_slot(
        api, event, second_child["id"], slot_start_utc="2026-08-10T09:30:00Z"
    )
    return {
        "event": fx.read_event(api, event["id"]),
        "first_child": first_child,
        "second_child": second_child,
        "first_slot": first_slot,
        "second_slot": second_slot,
    }


def _three_referrals_one_awaiting_consent(api):
    """Three referred children; the third has a notice out, so it left RECEIVED."""
    first_child = fx.register_child(api)
    first = fx.create_referral(
        api, first_child["id"], source="PEDIATRICIAN", referring_provider_npi="1234567893"
    )
    second_child = fx.register_child(api)
    second = fx.create_referral(api, second_child["id"], source="PARENT")
    third_child = fx.register_child(api)
    third = fx.create_referral(api, third_child["id"], source="SCHOOL")
    fx.issue_evaluation_notice(api, third["id"])
    return {
        "children": [first_child, second_child, third_child],
        "referrals": [first, second, third],
    }


def _two_families_with_a_pending_notice(api):
    """Two unrelated families; family A holds a PENDING evaluation-consent notice."""
    child_a = fx.register_child(api)
    referral_a = fx.create_referral(api, child_a["id"])
    consent_a = fx.issue_evaluation_notice(api, referral_a["id"])
    child_b = fx.register_child(api)
    referral_b = fx.create_referral(api, child_b["id"])
    return {
        "child_a": child_a,
        "referral_a": referral_a,
        "consent_a": consent_a,
        "child_b": child_b,
        "referral_b": referral_b,
    }


def _case_with_two_scheduled_assessments(api):
    """One open case holding a COMMUNICATION and a SOCIAL_EMOTIONAL assessment."""
    context = fx.setup_case(api)
    ecse = fx.register_provider(api, discipline="ECSE_TEACHER")
    social_worker = fx.register_provider(api, discipline="SOCIAL_WORKER")
    context["ecse"] = ecse
    context["social_worker"] = social_worker
    context["communication"] = fx.schedule_assessment(
        api,
        context["case"]["id"],
        ecse["id"],
        domain="COMMUNICATION",
        method="STANDARDIZED",
        window_start_utc=fx.DOMAIN_WINDOW_STARTS["COMMUNICATION"],
    )
    context["social_emotional"] = fx.schedule_assessment(
        api,
        context["case"]["id"],
        social_worker["id"],
        domain="SOCIAL_EMOTIONAL",
        method="STANDARDIZED",
        window_start_utc=fx.DOMAIN_WINDOW_STARTS["SOCIAL_EMOTIONAL"],
    )
    return context


def _cancelled_case(api, chair=None):
    """A case cancelled by the cascade a revoked evaluation consent starts."""
    context = fx.setup_case(api, chair=chair)
    fx.decide_consent(api, context["consent"]["id"], "REVOKED")
    context["case"] = fx.read_case(api, context["case"]["id"])
    return context


# ============================================================ provider amendment
def test_amending_the_service_ceiling_rederives_the_service_capacity_posture(api):
    """PRD §3.1: "any such amendment re-derives both capacity postures against the
    new ceilings and increments the provider's `version`".

    PRD §3.8 fixes what is re-derived: "it reads `AT_CAPACITY` when
    `assigned_weekly_service_minutes` has reached or passed
    `max_weekly_service_minutes`, `NEAR_CAPACITY` when the ratio of assigned minutes
    to the ceiling has reached eight tenths, and `OPEN` otherwise". The amendment
    touches no service line, so the 150 direct minutes and the 10 travel minutes the
    single district-centre location draws stay exactly where they were and only the
    denominator moves: 160 against 400 is `OPEN`, 160 against 200 is exactly eight
    tenths and therefore `NEAR_CAPACITY`, and 160 against 160 has reached the ceiling
    and is therefore `AT_CAPACITY`.

    Design: Corner/endpoints/patching_a_provider_rederives_both_postures_and_bumps_its_version
    """
    context = _draft_plan_with_two_slp_lines(api, max_weekly_service_minutes=400)
    provider_id = context["provider"]["id"]
    fx.staff_line(api, context["first_line"]["id"], provider_id)

    staffed = fx.read_provider(api, provider_id)
    assert_provider_minute_ledger(staffed, 150, 10, 160, "OPEN")

    near = fx.patch_provider(api, provider_id, max_weekly_service_minutes=200)
    assert near["max_weekly_service_minutes"] == 200
    assert_provider_minute_ledger(near, 150, 10, 160, "NEAR_CAPACITY")

    at_capacity = fx.patch_provider(api, provider_id, max_weekly_service_minutes=160)
    assert at_capacity["max_weekly_service_minutes"] == 160
    assert_provider_minute_ledger(at_capacity, 150, 10, 160, "AT_CAPACITY")


def test_amending_the_caseload_ceiling_rederives_the_evaluation_intake_posture(api):
    """PRD §3.1: "any such amendment re-derives both capacity postures against the
    new ceilings and increments the provider's `version`".

    PRD §3.5 fixes the second posture: "it reads `AT_CAPACITY` when the count has
    reached or passed `max_evaluation_caseload`, and `OPEN` otherwise". A chair
    holding one `PLANNED` case is `OPEN` under the default ceiling, reaches its
    ceiling the moment the ceiling is amended down to one, and returns to `OPEN` when
    the ceiling is raised again — the count itself never moves.

    Design: Corner/endpoints/patching_a_provider_rederives_both_postures_and_bumps_its_version
    """
    context = fx.setup_case(api)
    chair = fx.read_provider(api, context["chair"]["id"])
    assert chair["active_evaluation_count"] == 1
    assert chair["evaluation_intake_posture"] == "OPEN"

    at_capacity = fx.patch_provider(api, chair["id"], max_evaluation_caseload=1)
    assert at_capacity["max_evaluation_caseload"] == 1
    assert at_capacity["active_evaluation_count"] == 1
    assert at_capacity["evaluation_intake_posture"] == "AT_CAPACITY"
    assert_version_incremented(chair, at_capacity)

    reopened = fx.patch_provider(api, chair["id"], max_evaluation_caseload=3)
    assert reopened["evaluation_intake_posture"] == "OPEN"
    assert_version_incremented(at_capacity, reopened)


def test_placing_a_provider_on_leave_bumps_the_version_that_a_later_staffing_replays(api):
    """PRD §3.1: "A `DistrictAdmin` may later amend a provider's `status`,
    `languages`, `max_weekly_service_minutes`, `max_evaluation_caseload` or
    `max_weekly_interpreter_assignments` — this is how a provider is placed
    `ON_LEAVE` — and any such amendment re-derives both capacity postures against the
    new ceilings and increments the provider's `version`".

    Because the amendment moves the version, a staffing request still carrying the
    version observed before it is stale, and PRD §2.6 pins which refusal wins: the
    three expected-version checks are "consulted at rung 10 of the ladder — after
    every authorisation and existence rule, and before every state, temporal,
    structural and capacity rule", while `ERR_PROVIDER_NOT_ACTIVE` sits at rung 18 of
    PRD §2.5. So a stale staffing aimed at an `ON_LEAVE` provider answers 412 and not
    the provider-status error, and the line it names stays `PROPOSED`.

    Design: Corner/endpoints/patching_a_provider_rederives_both_postures_and_bumps_its_version
    """
    context = _draft_plan_with_two_slp_lines(api, max_weekly_service_minutes=400)
    provider_id = context["provider"]["id"]
    fx.staff_line(api, context["first_line"]["id"], provider_id)
    before = fx.read_provider(api, provider_id)
    stale_version = before["version"]

    on_leave = fx.patch_provider(
        api, provider_id, status="ON_LEAVE", max_weekly_service_minutes=1500
    )
    assert on_leave["status"] == "ON_LEAVE"
    assert_provider_minute_ledger(on_leave, 150, 10, 160, "OPEN")
    assert_version_incremented(before, on_leave)

    refused = api.staff_service_line(
        context["second_line"]["id"],
        f.staffing_payload(provider_id, stale_version),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_PROVIDER_VERSION.value)
    assert fx.read_line(api, context["second_line"]["id"])["status"] == "PROPOSED"
    assert_provider_minute_ledger(fx.read_provider(api, provider_id), 150, 10, 160)


# ==================================================== screening outcome side effect
def test_an_attended_refer_outcome_opens_a_screening_sourced_referral(api):
    """PRD §3.2: "When an appointment is recorded as `ATTENDED` with a
    `screening_result` of `REFER`, the system itself opens a referral for that
    appointment's child, with `source` set to `SCREENING`,
    `originating_screening_slot_id` set to the appointment, and `received_at` stamped
    from the logical clock." PRD §3.2 also fixes how it is found: "Nothing in the
    response body of the outcome call names the new referral; it is discoverable by
    filtering referrals on `originating_screening_slot_id`."

    That referral "runs the whole intake derivation of §3.3", so its dimensions start
    where PRD §3.3 initialises them — `intake_status` "initialised to `RECEIVED`" and
    `consent_status` "initialised to `NOT_REQUESTED`" — and a 33-month child who is
    not enrolled in early intervention takes "the `STANDARD_60_DAY` pathway". PRD §3.9
    then reads the child as `REFERRED`, since it "has any referral whose
    `intake_status` is `RECEIVED`, `CONSENT_PENDING` or `EVALUATION_AUTHORIZED`".

    Design: Corner/endpoints/an_attended_refer_outcome_opens_a_screening_sourced_referral
    """
    context = _event_with_two_booked_children(api)
    outcome = fx.record_outcome(api, context["first_slot"]["id"], "ATTENDED", "REFER")
    assert outcome["status"] == "ATTENDED"
    assert outcome["screening_result"] == "REFER"

    data, meta = validate_paginated(
        api.list_referrals(
            COORDINATOR,
            {"originating_screening_slot_id": context["first_slot"]["id"]},
        )
    )
    assert_page_meta(meta, expected_total=1, expected_has_more=False)
    assert len(data) == 1
    referral = data[0]
    assert referral["child_id"] == context["first_child"]["id"]
    assert referral["source"] == "SCREENING"
    assert referral["originating_screening_slot_id"] == context["first_slot"]["id"]
    assert referral["intake_status"] == "RECEIVED"
    assert referral["consent_status"] == "NOT_REQUESTED"
    assert referral["eligibility_pathway"] == "STANDARD_60_DAY"
    assert_instant(referral["received_at"], INITIAL_LOGICAL_CLOCK, "referral.received_at")

    assert fx.read_child(api, context["first_child"]["id"])["status"] == "REFERRED"


def test_an_attended_pass_outcome_opens_no_referral_at_all(api):
    """PRD §3.2 conditions the whole side effect on one result: "When an appointment
    is recorded as `ATTENDED` with a `screening_result` of `REFER`, the system itself
    opens a referral for that appointment's child".

    A `PASS` outcome therefore leaves the referral world untouched — nothing is
    discoverable under "filtering referrals on `originating_screening_slot_id`" — and
    the screened child keeps the status PRD §3.9 gives a child with no referral at
    all: "Failing all of those, the status is `NO_ACTIVE_REFERRAL`." The appointment
    itself still counts, because PRD §3.2 defines `booked_slot_count` as "the number
    of this event's appointments whose status is `BOOKED`, `ATTENDED` or `NO_SHOW`".

    Design: Corner/endpoints/an_attended_refer_outcome_opens_a_screening_sourced_referral
    """
    context = _event_with_two_booked_children(api)
    fx.record_outcome(api, context["first_slot"]["id"], "ATTENDED", "REFER")
    passed = fx.record_outcome(api, context["second_slot"]["id"], "ATTENDED", "PASS")
    assert passed["status"] == "ATTENDED"
    assert passed["screening_result"] == "PASS"

    data, meta = validate_paginated(
        api.list_referrals(
            COORDINATOR,
            {"originating_screening_slot_id": context["second_slot"]["id"]},
        )
    )
    assert_page_meta(meta, expected_total=0, expected_has_more=False)
    assert data == []

    assert fx.read_child(api, context["second_child"]["id"])["status"] == "NO_ACTIVE_REFERRAL"

    event = fx.read_event(api, context["event"]["id"])
    assert event["booked_slot_count"] == 2
    assert event["effective_slot_capacity"] == 4


# ===================================================== referral list composition
def test_the_intake_status_filter_reports_its_own_total_across_two_pages(api):
    """PRD §3.3: "Referrals can be listed and filtered by `child_id`, by
    `originating_screening_slot_id`, by `superseded_by_referral_id`, by `source`, by
    `eligibility_pathway`, by `consent_status` and by `intake_status`."

    PRD §2.3 pins how that filter composes with the page window: `total_count` "is the
    size of the filtered result set before the page window is applied and `has_more`
    is true exactly when records remain beyond the current window", and "List results
    are always ordered by `created_at` ascending". Of three referrals one has left
    `RECEIVED` for `CONSENT_PENDING`, so the filtered set is two: page one of one
    record reports a total of two with more to come, and page two reports the same
    total with nothing left beyond it.

    Design: Corner/endpoints/referral_list_filters_compose_with_pagination_and_total_count
    """
    context = _three_referrals_one_awaiting_consent(api)
    first, second, _third = context["referrals"]

    page_one, meta_one = validate_paginated(
        api.list_referrals(
            COORDINATOR, {"intake_status": "RECEIVED", "limit": 1, "offset": 0}
        )
    )
    assert_page_meta(meta_one, 1, 0, 2, True)
    assert len(page_one) == 1
    assert page_one[0]["id"] == first["id"]

    page_two, meta_two = validate_paginated(
        api.list_referrals(
            COORDINATOR, {"intake_status": "RECEIVED", "limit": 1, "offset": 1}
        )
    )
    assert_page_meta(meta_two, 1, 1, 2, False)
    assert len(page_two) == 1
    assert page_two[0]["id"] == second["id"]
    assert_ordered_by_created_at(page_one + page_two)


def test_a_child_filter_narrows_the_total_and_an_unmatched_source_filter_empties_it(api):
    """PRD §3.3 lists the referral filters, among them "by `child_id`" and "by
    `source`", and PRD §2.3 defines `total_count` as "the size of the filtered result
    set before the page window is applied".

    The narrowest filter therefore reports one, the referral it returns is the one that
    has already moved to `CONSENT_PENDING`, a `source` no referral in the set carries
    reports zero, and the unfiltered listing reports all three.

    Design: Corner/endpoints/referral_list_filters_compose_with_pagination_and_total_count
    """
    context = _three_referrals_one_awaiting_consent(api)
    third_child = context["children"][2]
    third = context["referrals"][2]

    by_child, child_meta = validate_paginated(
        api.list_referrals(COORDINATOR, {"child_id": third_child["id"]})
    )
    assert_page_meta(child_meta, expected_total=1, expected_has_more=False)
    assert len(by_child) == 1
    assert by_child[0]["id"] == third["id"]
    assert by_child[0]["intake_status"] == "CONSENT_PENDING"
    assert by_child[0]["consent_status"] == "REQUESTED"

    absent, absent_meta = validate_paginated(
        api.list_referrals(COORDINATOR, {"source": "PART_C_TRANSITION"})
    )
    assert_page_meta(absent_meta, expected_total=0, expected_has_more=False)
    assert absent == []

    every, every_meta = validate_paginated(api.list_referrals(COORDINATOR, {"limit": 100}))
    assert_page_meta(every_meta, 100, 0, 3, False)
    assert len(every) == 3
    assert_ordered_by_created_at(every)


# ================================================================ identity gating
IDENTITY_HEADERS = [
    pytest.param(headers_with_empty_user_id, id="empty-identity"),
    pytest.param(headers_without_user_id, id="absent-identity"),
]


@pytest.mark.parametrize("build_headers", IDENTITY_HEADERS)
def test_a_request_without_an_identity_is_rejected_on_an_existing_row(api, build_headers):
    """PRD §2.1: "A request with a missing or empty `X-User-ID` is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)".

    PRD §2.5 places that check at rung 1 of the ladder, and the row the request names
    exists and is readable to a properly identified caller, so nothing but the missing
    identity can explain the refusal.

    Design: Corner/errors/an_empty_identity_header_is_rejected_before_existence_and_schema
    """
    child = fx.register_child(api)

    validate_error(
        api.get_child(child["id"], build_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    readable = validate_success(api.get_child(child["id"], COORDINATOR))
    assert readable["id"] == child["id"]


@pytest.mark.parametrize("build_headers", IDENTITY_HEADERS)
def test_a_request_without_an_identity_outranks_the_existence_check(api, build_headers):
    """PRD §2.1: "this check precedes everything else including path resolution, so a
    request with no identity header aimed at a nonexistent path still answers 401
    rather than 404".

    The identifier used here is syntactically valid and matches no row, so a properly
    identified caller would be told 404; without an identity the caller learns nothing
    about existence.

    Design: Corner/errors/an_empty_identity_header_is_rejected_before_existence_and_schema
    """
    validate_error(
        api.get_child(MISSING_UUID, build_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    validate_error(
        api.get_child(MISSING_UUID, COORDINATOR),
        ApiErrorId.ERR_CHILD_NOT_FOUND.value,
    )


@pytest.mark.parametrize("build_headers", IDENTITY_HEADERS)
def test_a_request_without_an_identity_outranks_request_shape_validation(api, build_headers):
    """PRD §2.1 puts the identity check ahead of "everything else", and PRD §2.5 orders
    the ladder so that rung 1's `ERR_UNAUTHENTICATED` is consulted before rung 3's
    request-shape validation, under the rule that "the **first** rule that a request
    violates determines the response".

    The body below omits `last_name`, which PRD §3.1 requires on registration, so the
    very same body answers 400 once an identity is supplied and 401 while it is not.

    Design: Corner/errors/an_empty_identity_header_is_rejected_before_existence_and_schema
    """
    malformed = f.child_payload(last_name=...)

    validate_error(
        api.create_child(malformed, build_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    validate_error(
        api.create_child(malformed, COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(api.list_children(COORDINATOR, {}))
    assert_page_meta(meta, expected_total=0, expected_has_more=False)


# ==================================================================== role gating
def test_a_recognised_but_unauthorised_role_cannot_register_a_provider(api):
    """PRD §2.1: "A request whose `X-User-Role` is absent, is not one of the six
    recognised role names, or is a recognised name that the target endpoint does not
    authorise, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    PRD §3.1 authorises exactly one role here: "Only a `DistrictAdmin` may register
    staff." A `PlacementAdministrator` is a recognised role that this endpoint does not
    authorise, and no provider row appears as a result.

    Design: Corner/rbac/a_forbidden_or_unrecognised_role_is_rejected_before_the_body_is_parsed
    """
    validate_error(
        api.create_provider(f.provider_payload(), PLACEMENT),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    _, meta = validate_paginated(api.list_providers(DISTRICT_ADMIN, {}))
    assert_page_meta(meta, expected_total=0, expected_has_more=False)


def test_an_unrecognised_role_string_cannot_register_a_provider(api):
    """PRD §2.1: a role that "is not one of the six recognised role names" is
    "rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)", and "an unrecognised role string
    and a recognised-but-unauthorised role are deliberately indistinguishable to the
    caller".

    Design: Corner/rbac/a_forbidden_or_unrecognised_role_is_rejected_before_the_body_is_parsed
    """
    validate_error(
        api.create_provider(f.provider_payload(), make_headers("SuperUser", "op-1")),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_a_request_carrying_no_role_at_all_cannot_register_a_provider(api):
    """PRD §2.1: "A request whose `X-User-Role` is absent ... is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    The identity header is present and non-empty, so rung 1 of PRD §2.5 is satisfied
    and the absent role is the only thing left to refuse.

    Design: Corner/rbac/a_forbidden_or_unrecognised_role_is_rejected_before_the_body_is_parsed
    """
    validate_error(
        api.create_provider(f.provider_payload(), headers_without_role()),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_a_forbidden_role_is_refused_before_its_malformed_body_is_parsed(api):
    """PRD §2.1: an unauthorised role and a malformed body together resolve one way —
    role gating and unrecognised roles "both outrank body validation, so a forbidden
    role submitting a malformed payload still receives 403".

    The body omits `full_name`, which PRD §3.1 requires of a provider record, so the
    identical body answers `ERR_INVALID_REQUEST` at rung 3 of PRD §2.5 once the
    authorised role is used, and `ERR_FORBIDDEN_ROLE` at rung 2 while it is not.

    Design: Corner/rbac/a_forbidden_or_unrecognised_role_is_rejected_before_the_body_is_parsed
    """
    malformed = f.provider_payload(full_name=...)

    validate_error(
        api.create_provider(malformed, PLACEMENT),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_provider(malformed, make_headers("SuperUser", "op-1")),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_provider(malformed, DISTRICT_ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    created = validate_success(
        api.create_provider(f.provider_payload(discipline="SLP"), DISTRICT_ADMIN), 201
    )
    assert created["discipline"] == "SLP"
    _, meta = validate_paginated(api.list_providers(DISTRICT_ADMIN, {}))
    assert_page_meta(meta, expected_total=1, expected_has_more=False)


def test_a_parent_is_not_among_the_roles_that_may_list_community_sites(api):
    """PRD §2.1: a role that "is a recognised name that the target endpoint does not
    authorise, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    PRD §4 authorises the community-site listing for `ChildFindCoordinator`,
    `EvaluationChair`, `PlacementAdministrator` and `DistrictAdmin` only; `Parent` is a
    recognised role that this endpoint leaves out, and the refusal comes at rung 2 of
    PRD §2.5 without any reference to which family the caller belongs to.

    Design: Corner/rbac/a_forbidden_or_unrecognised_role_is_rejected_before_the_body_is_parsed
    """
    fx.register_site(api)
    child = fx.register_child(api)

    validate_error(
        api.list_community_sites(make_parent_headers(child["id"]), {}),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.list_community_sites(TEST_USERS["parent_headers"], {}),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


# ============================================================= guardian ownership
def test_a_parent_cannot_read_another_familys_child(api):
    """PRD §2.5 rung 6: "when the caller's role is `Parent`, `X-User-ID` must equal the
    `id` of the `Child` that the target row belongs to, else `ERR_NOT_CHILD_GUARDIAN`
    (403). This guards the single-child read, the single-referral read, the referral
    compliance view, the single-service-plan read, and the consent-decision write."

    Design: Corner/rbac/a_parent_cannot_reach_another_familys_child_referral_or_consent
    """
    context = _two_families_with_a_pending_notice(api)
    other_family = make_parent_headers(context["child_b"]["id"])

    validate_error(
        api.get_child(context["child_a"]["id"], other_family),
        ApiErrorId.ERR_NOT_CHILD_GUARDIAN.value,
    )


def test_a_parent_cannot_read_another_familys_referral_or_compliance_view(api):
    """PRD §2.5 rung 6 guards "the single-referral read, the referral compliance view"
    with the same rule: the `Parent` caller's `X-User-ID` "must equal the `id` of the
    `Child` that the target row belongs to, else `ERR_NOT_CHILD_GUARDIAN` (403)".

    Design: Corner/rbac/a_parent_cannot_reach_another_familys_child_referral_or_consent
    """
    context = _two_families_with_a_pending_notice(api)
    other_family = make_parent_headers(context["child_b"]["id"])

    validate_error(
        api.get_referral(context["referral_a"]["id"], other_family),
        ApiErrorId.ERR_NOT_CHILD_GUARDIAN.value,
    )
    validate_error(
        api.get_referral_timeline(context["referral_a"]["id"], other_family),
        ApiErrorId.ERR_NOT_CHILD_GUARDIAN.value,
    )


def test_a_parent_cannot_decide_another_familys_consent_record(api):
    """PRD §2.5 rung 6 guards "the consent-decision write" as well, refusing a `Parent`
    whose `X-User-ID` is not "the `id` of the `Child` that the target row belongs to"
    with `ERR_NOT_CHILD_GUARDIAN` (403).

    The refusal leaves both dimensions of PRD §3.4 untouched: the record's `decision`
    is still where issuance left it and the referral's `consent_status` is still
    `REQUESTED`, because only "a decision on the referral's evaluation-consent record"
    moves it on.

    Design: Corner/rbac/a_parent_cannot_reach_another_familys_child_referral_or_consent
    """
    context = _two_families_with_a_pending_notice(api)
    other_family = make_parent_headers(context["child_b"]["id"])

    validate_error(
        api.record_consent_decision(
            context["consent_a"]["id"], f.consent_decision_payload("GRANTED"), other_family
        ),
        ApiErrorId.ERR_NOT_CHILD_GUARDIAN.value,
    )

    assert fx.read_consent(api, context["consent_a"]["id"])["decision"] == "PENDING"
    referral = fx.read_referral(api, context["referral_a"]["id"])
    assert referral["consent_status"] == "REQUESTED"
    assert referral["intake_status"] == "CONSENT_PENDING"


def test_a_parent_probing_a_child_that_does_not_exist_learns_only_that(api):
    """PRD §2.5 rung 6: "Because it runs after existence, a `Parent` probing another
    family learns 403 for rows that exist and 404 for rows that do not."

    Design: Corner/rbac/a_parent_cannot_reach_another_familys_child_referral_or_consent
    """
    context = _two_families_with_a_pending_notice(api)
    other_family = make_parent_headers(context["child_b"]["id"])

    validate_error(
        api.get_child(MISSING_UUID, other_family),
        ApiErrorId.ERR_CHILD_NOT_FOUND.value,
    )
    validate_error(
        api.get_child(context["child_a"]["id"], other_family),
        ApiErrorId.ERR_NOT_CHILD_GUARDIAN.value,
    )


def test_a_parent_reaches_its_own_family_freely(api):
    """PRD §2.5 rung 6 refuses a `Parent` only when `X-User-ID` differs from "the `id`
    of the `Child` that the target row belongs to"; a matching identity passes the
    rung, so the same reads that were refused for the other family succeed here.

    Design: Corner/rbac/a_parent_cannot_reach_another_familys_child_referral_or_consent
    """
    context = _two_families_with_a_pending_notice(api)
    own_family = make_parent_headers(context["child_a"]["id"])

    child = validate_success(api.get_child(context["child_a"]["id"], own_family))
    assert child["id"] == context["child_a"]["id"]

    referral = validate_success(api.get_referral(context["referral_a"]["id"], own_family))
    assert referral["child_id"] == context["child_a"]["id"]


# =================================================== assigned-evaluator ownership
def test_an_evaluator_cannot_complete_another_evaluators_assessment(api):
    """PRD §2.5 rung 7: "when the caller's role is `Evaluator`, `X-User-ID` must equal
    the target assessment's `evaluator_provider_id`, else `ERR_NOT_ASSIGNED_EVALUATOR`
    (403). This guards assessment completion and assessment invalidation."

    The refused assessment stays exactly where PRD §3.5 wrote it: "A scheduled
    assessment is written at `SCHEDULED`".

    Design: Corner/rbac/an_evaluator_cannot_complete_or_invalidate_another_evaluators_assessment
    """
    context = _case_with_two_scheduled_assessments(api)
    intruder = make_evaluator_headers(context["social_worker"]["id"])

    validate_error(
        api.complete_domain_assessment(
            context["communication"]["id"], f.assessment_completion_payload(22), intruder
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_EVALUATOR.value,
    )
    assert fx.read_assessment(api, context["communication"]["id"])["status"] == "SCHEDULED"


def test_an_evaluator_cannot_invalidate_another_evaluators_assessment(api):
    """PRD §2.5 rung 7 guards invalidation with the same rule: an `Evaluator` whose
    `X-User-ID` does not equal "the target assessment's `evaluator_provider_id`" is
    refused with `ERR_NOT_ASSIGNED_EVALUATOR` (403).

    Design: Corner/rbac/an_evaluator_cannot_complete_or_invalidate_another_evaluators_assessment
    """
    context = _case_with_two_scheduled_assessments(api)
    intruder = make_evaluator_headers(context["social_worker"]["id"])

    validate_error(
        api.invalidate_domain_assessment(
            context["communication"]["id"], f.assessment_invalidation_payload(), intruder
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_EVALUATOR.value,
    )
    assert fx.read_assessment(api, context["communication"]["id"])["status"] == "SCHEDULED"


def test_the_case_chair_may_complete_an_assessment_it_did_not_administer(api):
    """PRD §2.5 rung 7: "The chair of the same case is separately authorised on both of
    those endpoints and does not pass through this rule."

    The chair's identity matches no `evaluator_provider_id` on the case, yet the
    completion succeeds where the same call from a different evaluator was refused.

    Design: Corner/rbac/an_evaluator_cannot_complete_or_invalidate_another_evaluators_assessment
    """
    context = _case_with_two_scheduled_assessments(api)

    completed = validate_success(
        api.complete_domain_assessment(
            context["communication"]["id"],
            f.assessment_completion_payload(22),
            make_chair_headers(context["chair"]["id"]),
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["evaluator_provider_id"] == context["ecse"]["id"]


def test_an_evaluator_completing_its_own_assessment_advances_the_case_count(api):
    """PRD §2.5 rung 7 admits the `Evaluator` whose `X-User-ID` equals "the target
    assessment's `evaluator_provider_id`", and PRD §3.6 defines what the case then
    shows: "`completed_domain_count` is the number of **distinct** `domain` values
    among the completed assessments."

    One assessment is completed by the chair and the other by its own assigned
    evaluator, so two distinct domains stand `COMPLETED`.

    Design: Corner/rbac/an_evaluator_cannot_complete_or_invalidate_another_evaluators_assessment
    """
    context = _case_with_two_scheduled_assessments(api)
    validate_success(
        api.complete_domain_assessment(
            context["communication"]["id"],
            f.assessment_completion_payload(22),
            make_chair_headers(context["chair"]["id"]),
        )
    )

    own = fx.complete_assessment(
        api, context["social_emotional"]["id"], context["social_worker"]["id"], 22
    )
    assert own["status"] == "COMPLETED"

    case = fx.read_case(api, context["case"]["id"])
    assert case["completed_domain_count"] == 2
    assert case["status"] == "IN_PROGRESS"


# ================================================================ chair ownership
def test_a_provider_who_is_not_the_chair_cannot_draft_the_report(api):
    """PRD §2.5 rung 8: "when the caller's role is `EvaluationChair`, `X-User-ID` must
    equal the target case's `chair_provider_id`, else `ERR_NOT_CASE_CHAIR` (403). This
    guards domain-assessment scheduling, report drafting, determination, assessment
    completion and assessment invalidation."

    The case is otherwise perfectly ready to draft — PRD §3.7 requires "all five
    distinct domains to stand `COMPLETED`" and they do — so only the caller's identity
    can explain the refusal, and the case keeps its status.

    Design: Corner/rbac/a_provider_who_is_not_the_chair_cannot_act_on_the_case
    """
    context = fx.setup_case_with_five_completed_domains(api)
    outsider = fx.register_provider(api, discipline="ECSE_TEACHER")

    validate_error(
        api.draft_report(
            context["case"]["id"], f.report_payload(), make_chair_headers(outsider["id"])
        ),
        ApiErrorId.ERR_NOT_CASE_CHAIR.value,
    )
    assert fx.read_case(api, context["case"]["id"])["status"] == "DOMAINS_COMPLETE"


def test_a_provider_who_is_not_the_chair_cannot_schedule_a_domain_assessment(api):
    """PRD §2.5 rung 8 guards "domain-assessment scheduling" with the same identity
    rule, refusing an `EvaluationChair` whose `X-User-ID` does not equal "the target
    case's `chair_provider_id`" with `ERR_NOT_CASE_CHAIR` (403).

    The evaluator named in the body exists and is of a discipline PRD §3.5 allows for
    the domain, so the request clears every rung above rung 8.

    Design: Corner/rbac/a_provider_who_is_not_the_chair_cannot_act_on_the_case
    """
    context = fx.setup_case(api)
    outsider = fx.register_provider(api, discipline="ECSE_TEACHER")
    evaluator = fx.register_provider(api, discipline="SCHOOL_PSYCHOLOGIST")

    validate_error(
        api.schedule_domain_assessment(
            context["case"]["id"],
            f.domain_assessment_payload(
                evaluator["id"],
                domain="COGNITIVE",
                window_start_utc=fx.DOMAIN_WINDOW_STARTS["COGNITIVE"],
            ),
            make_chair_headers(outsider["id"]),
        ),
        ApiErrorId.ERR_NOT_CASE_CHAIR.value,
    )
    assert fx.assessments_for_case(api, context["case"]["id"]) == []
    assert fx.read_case(api, context["case"]["id"])["status"] == "PLANNED"


def test_the_wrong_chair_on_a_cancelled_case_sees_the_identity_error_not_the_state_error(api):
    """PRD §2.5 rung 8: "Chair identity is checked before any state or capacity rule,
    so the wrong chair acting on an already-cancelled case sees 403 and not a state
    error."

    Design: Corner/rbac/a_provider_who_is_not_the_chair_cannot_act_on_the_case
    """
    context = _cancelled_case(api)
    assert context["case"]["status"] == "CANCELLED"
    outsider = fx.register_provider(api, discipline="ECSE_TEACHER")

    validate_error(
        api.draft_report(
            context["case"]["id"], f.report_payload(), make_chair_headers(outsider["id"])
        ),
        ApiErrorId.ERR_NOT_CASE_CHAIR.value,
    )


def test_the_rightful_chair_on_a_cancelled_case_sees_the_state_error(api):
    """PRD §3.7: "drafting from any status other than `DOMAINS_COMPLETE` or
    `REVISIONS_REQUESTED` is refused with `ERR_INVALID_CASE_STATE`".

    PRD §2.5 places the own-state rule at rung 11 and the domains-complete requirement
    at rung 25, and "the **first** rule that a request violates determines the
    response, and no later rule is consulted" — so the rightful chair of a `CANCELLED`
    case is answered on state, which is also the difference the wrong chair never gets
    to see.

    Design: Corner/rbac/a_provider_who_is_not_the_chair_cannot_act_on_the_case
    """
    context = _cancelled_case(api)

    validate_error(
        api.draft_report(
            context["case"]["id"],
            f.report_payload(),
            make_chair_headers(context["chair"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_CASE_STATE.value,
    )


def test_the_rightful_chair_drafts_the_report_the_outsider_could_not(api):
    """PRD §2.5 rung 8 admits the `EvaluationChair` whose `X-User-ID` equals "the target
    case's `chair_provider_id`", and PRD §3.7 then moves the case: drafting is legal
    from `DOMAINS_COMPLETE`, and the case advances to `REPORT_DRAFTED`.

    Design: Corner/rbac/a_provider_who_is_not_the_chair_cannot_act_on_the_case
    """
    context = fx.setup_case_with_five_completed_domains(api)

    drafted = validate_success(
        api.draft_report(
            context["case"]["id"],
            f.report_payload(),
            make_chair_headers(context["chair"]["id"]),
        )
    )
    assert drafted["status"] == "REPORT_DRAFTED"
    assert drafted["chair_provider_id"] == context["chair"]["id"]


# ====================================================== stale screening event version
def _open_event_for_two_bookings(api):
    """An OPEN event holding four thirty-minute places in a three-hour window."""
    return fx.create_open_screening_event(
        api,
        slot_capacity=4,
        slot_length_minutes=30,
        window_start_utc=ts("2026-08-20T09:00:00Z"),
        window_end_utc=ts("2026-08-20T12:00:00Z"),
    )


def test_a_replayed_screening_event_version_blocks_the_second_booking(api):
    """PRD §2.6: "Booking a screening slot requires
    `expected_screening_event_version`, carrying the client's last observed `version`
    of the parent `ScreeningEvent`. If it does not equal that event's current
    `version`, the booking is rejected with `ERR_STALE_SCREENING_EVENT_VERSION`
    (HTTP 412)."

    PRD §3.2 explains why nothing else catches it: the first booking "recomputes the
    parent event's `booked_slot_count`, and increments the parent event's `version`",
    while capacity is untouched — one place of four is taken — so "because a further
    booking is perfectly legitimate whenever capacity remains, no state precondition
    would have caught it". The refused booking leaves the counter alone.

    Design: Corner/cross_cutting_complexity_layers/stale_screening_event_version_blocks_the_second_booking_until_reread
    """
    event = _open_event_for_two_bookings(api)
    stale_version = event["version"]
    first_child = fx.register_child(api)
    second_child = fx.register_child(api)

    fx.book_slot(api, event, first_child["id"], slot_start_utc="2026-08-20T09:00:00Z")

    refused = api.book_screening_slot(
        event["id"],
        f.slot_booking_payload(
            second_child["id"], stale_version, slot_start_utc="2026-08-20T09:30:00Z"
        ),
        COORDINATOR,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_SCREENING_EVENT_VERSION.value)

    reread = fx.read_event(api, event["id"])
    assert reread["booked_slot_count"] == 1
    assert reread["effective_slot_capacity"] == 4
    assert reread["version"] != stale_version

    _, meta = validate_paginated(
        api.list_screening_slots(COORDINATOR, {"screening_event_id": event["id"]})
    )
    assert_page_meta(meta, expected_total=1, expected_has_more=False)


def test_rereading_the_screening_event_lets_the_refused_booking_through(api):
    """PRD §2.6: the booking is refused only when the submitted version "does not
    equal that event's current `version`" — so the very same booking, resubmitted
    against the version the event has now, is accepted.

    PRD §3.2 fixes the rest: "A successful booking creates the appointment at
    `BOOKED`, recomputes the parent event's `booked_slot_count`, and increments the
    parent event's `version`", and "The appointment's `slot_end_utc` is derived, never
    supplied: it is `slot_start_utc` advanced by the parent event's
    `slot_length_minutes`."

    Design: Corner/cross_cutting_complexity_layers/stale_screening_event_version_blocks_the_second_booking_until_reread
    """
    event = _open_event_for_two_bookings(api)
    stale_version = event["version"]
    first_child = fx.register_child(api)
    second_child = fx.register_child(api)
    fx.book_slot(api, event, first_child["id"], slot_start_utc="2026-08-20T09:00:00Z")
    validate_error(
        api.book_screening_slot(
            event["id"],
            f.slot_booking_payload(
                second_child["id"], stale_version, slot_start_utc="2026-08-20T09:30:00Z"
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_STALE_SCREENING_EVENT_VERSION.value,
    )

    current = fx.read_event(api, event["id"])
    accepted = validate_success(
        api.book_screening_slot(
            event["id"],
            f.slot_booking_payload(
                second_child["id"], current["version"], slot_start_utc="2026-08-20T09:30:00Z"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert accepted["status"] == "BOOKED"
    assert accepted["child_id"] == second_child["id"]
    assert_instant(
        accepted["slot_end_utc"],
        plus_minutes("2026-08-20T09:30:00Z", 30),
        "slot.slot_end_utc",
    )

    after = fx.read_event(api, event["id"])
    assert after["booked_slot_count"] == 2
    assert after["effective_slot_capacity"] == 4

    _, meta = validate_paginated(
        api.list_screening_slots(COORDINATOR, {"screening_event_id": event["id"]})
    )
    assert_page_meta(meta, expected_total=2, expected_has_more=False)


# ==================================================== stale evaluation case version
def _case_ready_for_determination(api):
    """A case at REPORT_DRAFTED, plus the site a community placement would name."""
    site = fx.register_site(api)
    context = fx.setup_case_with_five_completed_domains(api)
    context["site"] = site
    context["case"] = fx.draft_report(
        api, context["case"]["id"], context["chair"]["id"]
    )
    return context


def test_a_replayed_evaluation_case_version_blocks_the_second_determination(api):
    """PRD §2.6: "Recording an eligibility determination requires
    `expected_evaluation_case_version`, carrying the client's last observed `version`
    of the parent `EvaluationCase`. A mismatch with the case's current `version` is
    rejected with `ERR_STALE_EVALUATION_CASE_VERSION` (HTTP 412)."

    A second determination is not itself illegal — PRD §2.6 calls it "legitimate
    product behaviour — it supersedes the earlier draft plan" — so the version check is
    the only thing that can refuse the replay, and the draft plan the first
    determination created stays at `DRAFT` rather than being superseded.

    Design: Corner/cross_cutting_complexity_layers/stale_evaluation_case_version_blocks_a_second_determination
    """
    context = _case_ready_for_determination(api)
    case_id = context["case"]["id"]
    stale_version = context["case"]["version"]

    first_plan = fx.determine_eligible(
        api,
        case_id,
        setting="COMMUNITY_PRESCHOOL",
        expected_version=stale_version,
        community_site_id=context["site"]["id"],
    )
    assert first_plan["status"] == "DRAFT"

    refused = api.determine_eligibility(
        case_id,
        f.eligible_determination_payload(stale_version, setting="ITINERANT_ONLY"),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_EVALUATION_CASE_VERSION.value)

    assert fx.read_plan(api, first_plan["id"])["status"] == "DRAFT"
    assert len(fx.plans_for_case(api, case_id)) == 1

    case = fx.read_case(api, case_id)
    assert case["status"] == "ELIGIBILITY_DETERMINED"
    assert case["version"] != stale_version


def test_rereading_the_case_lets_the_second_determination_supersede_the_draft(api):
    """PRD §2.6 refuses only a version that mismatches "the case's current `version`",
    so the replay succeeds once the case is re-read.

    PRD §3.7 then fixes the cascade: "A second determination on a case already at
    `ELIGIBILITY_DETERMINED` is a self-loop on that status: it requires a matching
    `expected_evaluation_case_version`, and it requires the plan already on the case to
    be at `DRAFT` ... The existing draft plan then moves `DRAFT → SUPERSEDED`, every
    service line belonging to it moves to `DISCONTINUED` ..., a fresh plan is created
    at `DRAFT`, and the case's `version` increments again."

    Design: Corner/cross_cutting_complexity_layers/stale_evaluation_case_version_blocks_a_second_determination
    """
    context = _case_ready_for_determination(api)
    case_id = context["case"]["id"]
    stale_version = context["case"]["version"]

    first_plan = fx.determine_eligible(
        api,
        case_id,
        setting="COMMUNITY_PRESCHOOL",
        expected_version=stale_version,
        community_site_id=context["site"]["id"],
    )
    validate_error(
        api.determine_eligibility(
            case_id,
            f.eligible_determination_payload(stale_version, setting="ITINERANT_ONLY"),
            PLACEMENT,
        ),
        ApiErrorId.ERR_STALE_EVALUATION_CASE_VERSION.value,
    )

    current = fx.read_case(api, case_id)
    second_plan = validate_success(
        api.determine_eligibility(
            case_id,
            f.eligible_determination_payload(current["version"], setting="ITINERANT_ONLY"),
            PLACEMENT,
        ),
        201,
    )
    assert second_plan["id"] != first_plan["id"]
    assert second_plan["status"] == "DRAFT"
    assert second_plan["setting"] == "ITINERANT_ONLY"
    assert second_plan.get("community_site_id") is None

    assert fx.read_plan(api, first_plan["id"])["status"] == "SUPERSEDED"
    assert fx.read_case(api, case_id)["version"] != current["version"]


# =========================================================== stale provider version
def test_a_replayed_provider_version_blocks_the_second_staffing(api):
    """PRD §2.6: "Staffing a service line requires `expected_provider_version`,
    carrying the client's last observed `version` of the `Provider` being staffed. A
    mismatch with that provider's current `version` is rejected with
    `ERR_STALE_PROVIDER_VERSION` (HTTP 412)."

    The second line is legitimate on every other count — PRD §2.6 notes that "Staffing
    a further line to the same provider is legitimate whenever the minute ceiling still
    holds, so nothing in the line's own lifecycle would reject it" — and 160 assigned
    minutes of a 400-minute ceiling leaves ample room. The refused line stays where PRD
    §3.8 leaves an unstaffed line, and the provider's figures still describe the one
    staffed line alone: 150 direct minutes at a single location draw 5 percent, which
    is 7.5, "rounded up once to the next multiple of five" to give 10.

    Design: Corner/cross_cutting_complexity_layers/stale_provider_version_blocks_a_second_staffing_of_the_same_provider
    """
    context = _draft_plan_with_two_slp_lines(api, max_weekly_service_minutes=400)
    provider_id = context["provider"]["id"]
    stale_version = context["provider"]["version"]

    staffed = fx.staff_line(api, context["first_line"]["id"], provider_id, stale_version)
    assert staffed["status"] == "STAFFED"
    assert staffed["provider_id"] == provider_id

    refused = api.staff_service_line(
        context["second_line"]["id"],
        f.staffing_payload(provider_id, stale_version),
        PLACEMENT,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_PROVIDER_VERSION.value)

    second = fx.read_line(api, context["second_line"]["id"])
    assert second["status"] == "PROPOSED"
    assert second.get("provider_id") is None

    caseload = fx.read_caseload(api, provider_id)
    assert_provider_minute_ledger(caseload, 150, 10, 160, "OPEN")
    assert caseload["distinct_site_count"] == 1
    assert caseload["max_weekly_service_minutes"] == 400


def test_rereading_the_provider_lets_the_second_staffing_through(api):
    """PRD §2.6 refuses only a version that mismatches "that provider's current
    `version`", so the same staffing succeeds once the provider is re-read.

    PRD §3.8 then fixes the recomputed ledger: `direct_weekly_service_minutes` is "the
    sum of `weekly_minutes` over every line that names that provider, stands at
    `STAFFED`, and belongs to a plan whose status is `DRAFT`,
    `PENDING_PARENT_CONSENT` or `ACTIVE`" — 150 plus 100 — while
    `travel_overhead_minutes` is "the direct total multiplied by the chosen
    percentage, plus 15 minutes for each location beyond the first, with that
    **whole** expression rounded up once to the next multiple of five". Both lines are
    delivered at the district centre, so there is one location and no per-location
    addition: 250 minutes falls in the tier "300 minutes or fewer", 5 percent of 250 is
    12.5, and that rounds up to 15, for 265 assigned minutes against a 400-minute
    ceiling.

    Design: Corner/cross_cutting_complexity_layers/stale_provider_version_blocks_a_second_staffing_of_the_same_provider
    """
    context = _draft_plan_with_two_slp_lines(api, max_weekly_service_minutes=400)
    provider_id = context["provider"]["id"]
    stale_version = context["provider"]["version"]
    fx.staff_line(api, context["first_line"]["id"], provider_id, stale_version)
    validate_error(
        api.staff_service_line(
            context["second_line"]["id"],
            f.staffing_payload(provider_id, stale_version),
            PLACEMENT,
        ),
        ApiErrorId.ERR_STALE_PROVIDER_VERSION.value,
    )

    current = fx.read_provider(api, provider_id)
    accepted = fx.staff_line(
        api, context["second_line"]["id"], provider_id, current["version"]
    )
    assert accepted["status"] == "STAFFED"
    assert accepted["provider_id"] == provider_id

    caseload = fx.read_caseload(api, provider_id)
    assert_provider_minute_ledger(caseload, 250, 15, 265, "OPEN")
    assert caseload["distinct_site_count"] == 1
    assert caseload["provider_id"] == provider_id


# ============================================== cascades visible in the same response
def test_a_granted_consent_is_visible_on_the_referral_and_the_child_at_once(api):
    """PRD §2.9: "every affected child is transitioned in the same request, and every
    rollup derived from those children is recomputed in the same request".

    PRD §3.4 fixes the decision response itself — "Every accepted decision stamps
    `decided_at` from the logical clock" — and the cascade it drives: "`PENDING →
    GRANTED` moves the referral's `intake_status` `CONSENT_PENDING →
    EVALUATION_AUTHORIZED` and its `consent_status` `REQUESTED → GRANTED`, sets
    `consent_granted_at` to the logical clock, and computes and pins
    `evaluation_due_date` exactly as §3.3 describes." PRD §3.3's pinned rule "takes the
    calendar date of `consent_granted_at` and adds 60 calendar days, weekends and
    holidays included", which from 2026-08-01 lands on 2026-09-30 and, for the
    `STANDARD_60_DAY` pathway, "stands uncapped". PRD §3.9 then reads the child as
    `REFERRED` on the strength of an `EVALUATION_AUTHORIZED` referral.

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response_that_caused_it
    """
    child = fx.register_child(api)
    referral = fx.create_referral(api, child["id"])
    consent = fx.issue_evaluation_notice(api, referral["id"])

    granted = validate_success(
        api.record_consent_decision(
            consent["id"],
            f.consent_decision_payload("GRANTED"),
            make_parent_headers(child["id"]),
        )
    )
    assert granted["decision"] == "GRANTED"
    assert_instant(granted["decided_at"], INITIAL_LOGICAL_CLOCK, "consent.decided_at")

    after = fx.read_referral(api, referral["id"])
    assert after["intake_status"] == "EVALUATION_AUTHORIZED"
    assert after["consent_status"] == "GRANTED"
    assert after["eligibility_pathway"] == "STANDARD_60_DAY"
    assert_instant(
        after["consent_granted_at"], INITIAL_LOGICAL_CLOCK, "referral.consent_granted_at"
    )
    assert_date_equals(after["evaluation_due_date"], "2026-09-30", "evaluation_due_date")

    assert fx.read_child(api, child["id"])["status"] == "REFERRED"


def test_opening_a_case_is_visible_on_the_chair_and_the_child_at_once(api):
    """PRD §3.5: "A new case is written at `PLANNED` with `revision_round` at 0 and
    `required_domain_count` fixed by the system at 5", it "denormalises `due_date` from
    the referral's `evaluation_due_date`", and "Opening the case recomputes the chair's
    evaluation rollups, computes `timeline_compliance` against the logical clock, and
    re-derives the child's own `status` to `IN_EVALUATION`."

    PRD §2.9 requires those rollups "in the same request", so the chair's caseload view
    already counts the case: PRD §3.5 defines `active_evaluation_count` as "the number
    of evaluation cases that provider chairs whose `status` is one of the five
    non-terminal values", and `evaluation_intake_posture` "reads `AT_CAPACITY` when the
    count has reached or passed `max_evaluation_caseload`, and `OPEN` otherwise". With
    60 days to the deadline, PRD §3.5's compliance bands give `ON_TIME`, since
    "anything larger" than 10 days remaining is on time.

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response_that_caused_it
    """
    granted = fx.setup_referral_with_granted_consent(api)
    chair = fx.register_chair(api)

    case = fx.open_case(api, granted["referral"]["id"], chair["id"])
    assert case["status"] == "PLANNED"
    assert case["revision_round"] == 0
    assert case["required_domain_count"] == 5
    assert case["child_id"] == granted["child"]["id"]
    assert_date_equals(case["due_date"], "2026-09-30", "case.due_date")
    assert case["timeline_compliance"] == "ON_TIME"

    caseload = fx.read_caseload(api, chair["id"])
    assert caseload["active_evaluation_count"] == 1
    assert caseload["evaluation_intake_posture"] == "OPEN"

    assert fx.read_child(api, granted["child"]["id"])["status"] == "IN_EVALUATION"
