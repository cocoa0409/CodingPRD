"""Entity shapes, registration defaults, derived fields and the existence ladder.

This file covers the parts of the contract that are visible on a single row: the
values a registration derives immediately (PRD §3.1), the server-minted identity,
timestamp and version properties every resource carries (PRD §2.4), the
request-shape rung of the refusal ladder (PRD §2.5 rung 3), the body-level foreign
key rung (PRD §2.5 rung 5), the per-entity not-found vocabulary (PRD §2.5), the
pagination contract on a list endpoint (PRD §2.3), and the service line that joins
a plan, a provider and a delivery site (PRD §3.8).
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_child,
    assert_contains_id,
    assert_domain_assessment,
    assert_fields_absent,
    assert_instant,
    assert_ordered_by_created_at,
    assert_page_meta,
    assert_provider,
    assert_referral,
    assert_screening_event,
    assert_service_line,
    assert_subset,
)
from test_helpers.constants import (  # noqa: E402
    DEFAULT_MAX_EVALUATION_CASELOAD,
    DEFAULT_MAX_INTERPRETER_ASSIGNMENTS,
    DEFAULT_MAX_WEEKLY_SERVICE_MINUTES,
    INITIAL_LOGICAL_CLOCK,
    MISSING_UUID,
    anniversary,
    expected_kindergarten_eligibility_date,
    ts,
)
from test_helpers.test_users import TEST_USERS  # noqa: E402

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]
DISTRICT_ADMIN = TEST_USERS["district_admin_headers"]

# A rendered timestamp carrying exactly three fractional-second digits (PRD §2.4).
_THREE_DIGIT_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _assert_three_fractional_digits(value, label):
    """A server-rendered timestamp uses exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _THREE_DIGIT_UTC.match(value), (
        f"{label} must be an ISO 8601 UTC timestamp with exactly three "
        f"fractional-second digits and a trailing Z, got {value!r}"
    )


# ---------------------------------------------------------------------- children
def test_child_registration_returns_every_derived_field(api):
    """PRD §3.1: "Registration derives four values immediately. `interpreter_required`
    is set true exactly when `primary_language_code` is not `en`. `third_birthday` is
    the child's date of birth advanced by three years under the anniversary
    convention of §2.8, and it is the anchor of the Part B deadline cap."
    PRD §3.1: "`kindergarten_eligibility_date` is computed by first advancing the date
    of birth by five years to obtain the fifth birthday, then taking September 1 of
    the year in which that fifth birthday falls: if the fifth birthday is on or before
    that September 1, the eligibility date is that same September 1; otherwise it is
    September 1 of the following year."
    PRD §3.1: "Finally, the child's derived `status` is initialised to
    `NO_ACTIVE_REFERRAL`."
    PRD §3.1: "`part_c_enrolled` states whether the child is currently served under
    early intervention and defaults to false."
    PRD §2.4: "Every resource also carries `created_at` and `updated_at`, both ISO 8601
    UTC timestamps rendered with exactly three fractional-second digits, and an integer
    `version` that begins at 1 when the record is created and increases by exactly 1 on
    every mutation of that record."

    Design: Corner/entities/child_creation_returns_system_and_computed_fields
    """
    date_of_birth = "2023-11-01"
    payload = f.child_payload(
        first_name="Ana",
        last_name="Reyes",
        date_of_birth=date_of_birth,
        guardian_full_name="Marta Reyes",
        district_of_residence="D-01",
        primary_language_code="es",
    )

    child = validate_success(api.create_child(payload, COORDINATOR), 201)

    assert_child(child, expected_version=1)
    assert_subset(
        child,
        {
            "first_name": "Ana",
            "last_name": "Reyes",
            "date_of_birth": date_of_birth,
            "guardian_full_name": "Marta Reyes",
            "district_of_residence": "D-01",
            "primary_language_code": "es",
            "third_birthday": anniversary(date_of_birth, 3),
            "kindergarten_eligibility_date": expected_kindergarten_eligibility_date(
                date_of_birth
            ),
            "interpreter_required": True,
            "part_c_enrolled": False,
            "status": "NO_ACTIVE_REFERRAL",
        },
    )
    assert child["third_birthday"] == "2026-11-01", (
        f"third_birthday: expected 2026-11-01, got {child['third_birthday']!r}"
    )
    assert child["kindergarten_eligibility_date"] == "2029-09-01", (
        "kindergarten_eligibility_date: expected 2029-09-01, got "
        f"{child['kindergarten_eligibility_date']!r}"
    )
    assert_fields_absent(child, "part_c_exit_date")


# --------------------------------------------------------------------- providers
def test_provider_registration_applies_documented_defaults(api):
    """PRD §3.1: "an optional `languages` list of two-letter codes the provider can
    deliver service or interpretation in, defaulting to a single entry of `en`; and an
    optional `status` of `ACTIVE`, `ON_LEAVE` or `INACTIVE`, defaulting to `ACTIVE`."
    PRD §3.1: "Three optional ceilings may be set at registration:
    `max_weekly_service_minutes`, a hard ceiling on assigned weekly minutes that must be
    a non-negative multiple of 5 and defaults to 1500 — that is, twenty-five hours a
    week; `max_evaluation_caseload`, a non-negative ceiling on concurrently open
    evaluation cases, defaulting to 12; and `max_weekly_interpreter_assignments`, a
    non-negative ceiling on open interpreter assignments that defaults to 0 and is only
    meaningful for a provider whose discipline is `INTERPRETER` — which means that an
    interpreter registered without an explicit ceiling can be named on no notices at all."
    PRD §3.1: "It also initialises both capacity dimensions to their empty state:
    `direct_weekly_service_minutes`, `travel_overhead_minutes` and
    `assigned_weekly_service_minutes` all at 0 with `service_capacity_posture` at
    `OPEN`, and `active_evaluation_count` at 0 with `evaluation_intake_posture` at
    `OPEN`, alongside `assigned_interpreter_assignment_count` at 0."

    Design: Corner/entities/provider_defaults_apply_when_optional_caps_are_omitted
    """
    payload = f.provider_payload(
        full_name="Dana Chair",
        discipline="SCHOOL_PSYCHOLOGIST",
        home_region_code="R-1",
    )
    assert "languages" not in payload, "the probe must omit every optional input"
    assert "status" not in payload, "the probe must omit every optional input"

    provider = validate_success(api.create_provider(payload, DISTRICT_ADMIN), 201)

    assert_provider(provider, expected_version=1)
    assert_subset(
        provider,
        {
            "full_name": "Dana Chair",
            "discipline": "SCHOOL_PSYCHOLOGIST",
            "home_region_code": "R-1",
            "status": "ACTIVE",
            "languages": ["en"],
            "max_weekly_service_minutes": DEFAULT_MAX_WEEKLY_SERVICE_MINUTES,
            "max_evaluation_caseload": DEFAULT_MAX_EVALUATION_CASELOAD,
            "max_weekly_interpreter_assignments": DEFAULT_MAX_INTERPRETER_ASSIGNMENTS,
            "direct_weekly_service_minutes": 0,
            "travel_overhead_minutes": 0,
            "assigned_weekly_service_minutes": 0,
            "service_capacity_posture": "OPEN",
            "active_evaluation_count": 0,
            "evaluation_intake_posture": "OPEN",
            "assigned_interpreter_assignment_count": 0,
        },
    )


def test_provider_chair_eligibility_is_derived_from_discipline(api):
    """PRD §3.1: "Registration derives `is_evaluation_chair_eligible` as true exactly
    when the provider's `discipline` is `SCHOOL_PSYCHOLOGIST` or `ECSE_TEACHER`, and
    false for every other discipline."

    Design: Corner/entities/provider_defaults_apply_when_optional_caps_are_omitted
    """
    psychologist = validate_success(
        api.create_provider(
            f.provider_payload(
                full_name="Dana Chair", discipline="SCHOOL_PSYCHOLOGIST"
            ),
            DISTRICT_ADMIN,
        ),
        201,
    )
    ecse_teacher = validate_success(
        api.create_provider(
            f.provider_payload(full_name="Eli ECSE", discipline="ECSE_TEACHER"),
            DISTRICT_ADMIN,
        ),
        201,
    )
    speech_pathologist = validate_success(
        api.create_provider(
            f.provider_payload(full_name="Iris SLP", discipline="SLP"), DISTRICT_ADMIN
        ),
        201,
    )

    assert psychologist["is_evaluation_chair_eligible"] is True, (
        "a SCHOOL_PSYCHOLOGIST must be chair-eligible, got "
        f"{psychologist['is_evaluation_chair_eligible']!r}"
    )
    assert ecse_teacher["is_evaluation_chair_eligible"] is True, (
        "an ECSE_TEACHER must be chair-eligible, got "
        f"{ecse_teacher['is_evaluation_chair_eligible']!r}"
    )
    assert speech_pathologist["is_evaluation_chair_eligible"] is False, (
        "an SLP must not be chair-eligible, got "
        f"{speech_pathologist['is_evaluation_chair_eligible']!r}"
    )


# --------------------------------------------------------------------- referrals
def test_single_referral_read_returns_stored_and_computed_fields(api):
    """PRD §3.3: "`received_at` is never supplied by the caller — the system stamps it
    from the logical clock at the instant of intake, and it is that instant that fixes
    the child's age at referral."
    PRD §3.3: "From `received_at` and the child's `date_of_birth` the system computes
    `age_months_at_referral` as whole completed months, and from that number it selects
    the statutory timeline that will govern the referral, recorded as
    `eligibility_pathway`."
    PRD §3.3: "Within it, a child whose `part_c_enrolled` is true and who is no more
    than 35 completed months old takes the `PART_C_TRANSITION_DEADLINE` pathway — the
    one whose deadline is truncated by the third birthday — while everyone else,
    including an early-intervention child who has already reached 36 months, takes the
    `STANDARD_60_DAY` pathway."
    PRD §3.3: "`intake_status` tracks the intake workflow and runs `RECEIVED`,
    `CONSENT_PENDING`, `EVALUATION_AUTHORIZED`, `DECLINED`, `WITHDRAWN` and
    `SUPERSEDED`, initialised to `RECEIVED`, with `DECLINED`, `WITHDRAWN` and
    `SUPERSEDED` terminal."
    PRD §3.3: "`consent_status` tracks the parental consent position and runs
    `NOT_REQUESTED`, `REQUESTED`, `GRANTED`, `REFUSED` and `REVOKED`, initialised to
    `NOT_REQUESTED`, with `REFUSED` and `REVOKED` terminal."
    PRD §3.3: "until consent is granted, `evaluation_due_date` is absent, and a referral
    without a granted consent is excluded from every compliance aggregate."

    Design: Corner/entities/referral_read_back_returns_stored_and_computed_fields
    """
    child = fx.register_child_aged(api, 36, primary_language_code="en")
    created = validate_success(
        api.create_referral(
            f.pediatrician_referral_payload(
                child["id"], referring_provider_npi="1234567893"
            ),
            COORDINATOR,
        ),
        201,
    )

    referral = validate_success(api.get_referral(created["id"], COORDINATOR))

    assert_referral(referral, expected_version=1)
    assert_instant(referral["received_at"], INITIAL_LOGICAL_CLOCK, "received_at")
    assert_subset(
        referral,
        {
            "id": created["id"],
            "child_id": child["id"],
            "source": "PEDIATRICIAN",
            "referring_provider_npi": "1234567893",
            "age_months_at_referral": 36,
            "eligibility_pathway": "STANDARD_60_DAY",
            "intake_status": "RECEIVED",
            "consent_status": "NOT_REQUESTED",
        },
    )
    assert_fields_absent(
        referral,
        "originating_screening_slot_id",
        "consent_granted_at",
        "evaluation_due_date",
        "superseded_by_referral_id",
    )


# --------------------------------------------------- child's derived-field surface
def test_child_derived_fields_follow_their_declared_inputs(api):
    """PRD §3.1: "`interpreter_required` is set true exactly when
    `primary_language_code` is not `en`."
    PRD §3.1: "`third_birthday` is the child's date of birth advanced by three years
    under the anniversary convention of §2.8, and it is the anchor of the Part B
    deadline cap."
    PRD §3.1: "Finally, the child's derived `status` is initialised to
    `NO_ACTIVE_REFERRAL`."
    PRD §3.9: "Finally, a child's own `status` is never written by a client; it is
    derived on every referral, evaluation-case and service-plan write that touches the
    child, by a ladder of clauses evaluated top to bottom in which the **first**
    matching clause wins."

    Design: Corner/entities/computed_child_fields_are_derived_and_never_client_writable
    """
    created = validate_success(
        api.create_child(
            f.child_payload(
                date_of_birth="2023-11-01",
                primary_language_code="ht",
                part_c_enrolled=True,
                part_c_exit_date="2026-11-01",
            ),
            COORDINATOR,
        ),
        201,
    )

    child = validate_success(api.get_child(created["id"], COORDINATOR))

    assert_child(child, expected_version=1)
    assert_subset(
        child,
        {
            "primary_language_code": "ht",
            "interpreter_required": True,
            "third_birthday": "2026-11-01",
            "kindergarten_eligibility_date": "2029-09-01",
            "part_c_enrolled": True,
            "part_c_exit_date": "2026-11-01",
            "status": "NO_ACTIVE_REFERRAL",
        },
    )


def test_child_status_is_rederived_when_a_referral_is_created(api):
    """PRD §3.9: "Otherwise, if the child has any referral whose `intake_status` is
    `RECEIVED`, `CONSENT_PENDING` or `EVALUATION_AUTHORIZED`, the status is `REFERRED`."
    PRD §3.3: "After intake the child's own derived `status` is re-evaluated and, in the
    ordinary case, becomes `REFERRED`."
    PRD §3.3: "Within it, a child whose `part_c_enrolled` is true and who is no more
    than 35 completed months old takes the `PART_C_TRANSITION_DEADLINE` pathway — the
    one whose deadline is truncated by the third birthday — while everyone else,
    including an early-intervention child who has already reached 36 months, takes the
    `STANDARD_60_DAY` pathway."

    Design: Corner/entities/computed_child_fields_are_derived_and_never_client_writable
    """
    child = validate_success(
        api.create_child(
            f.child_payload(
                date_of_birth="2023-11-01",
                primary_language_code="ht",
                part_c_enrolled=True,
                part_c_exit_date="2026-11-01",
            ),
            COORDINATOR,
        ),
        201,
    )
    assert child["status"] == "NO_ACTIVE_REFERRAL", (
        f"a freshly registered child must read NO_ACTIVE_REFERRAL, got {child['status']!r}"
    )

    referral = validate_success(
        api.create_referral(
            f.referral_payload(child["id"], source="PART_C_TRANSITION"), COORDINATOR
        ),
        201,
    )
    assert_subset(
        referral,
        {
            "age_months_at_referral": 33,
            "eligibility_pathway": "PART_C_TRANSITION_DEADLINE",
            "intake_status": "RECEIVED",
        },
    )

    # No write was ever addressed to the child; its status is derived on read.
    reread = validate_success(api.get_child(child["id"], COORDINATOR))
    assert reread["status"] == "REFERRED", (
        f"child status after intake: expected REFERRED, got {reread['status']!r}"
    )
    assert reread["interpreter_required"] is True, (
        "interpreter_required must still follow primary_language_code, got "
        f"{reread['interpreter_required']!r}"
    )
    assert reread["third_birthday"] == "2026-11-01", (
        f"third_birthday must still be derived from date_of_birth, got {reread['third_birthday']!r}"
    )


# -------------------------------------------------------------- screening events
def test_screening_event_system_fields_are_server_minted(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id` in UUID form,
    with no type prefix and no client control over its value."
    PRD §2.4: "Every resource also carries `created_at` and `updated_at`, both ISO 8601
    UTC timestamps rendered with exactly three fractional-second digits, and an integer
    `version` that begins at 1 when the record is created and increases by exactly 1 on
    every mutation of that record."
    PRD §3.2: "A new event opens at `SCHEDULED` and advances through the coordinator's
    status endpoint, which takes a single `target_status` input."
    PRD §3.2: "On creation the system computes `effective_slot_capacity` as the lesser of
    the declared `slot_capacity` and the number of whole appointments the window can
    physically hold — that is, the whole number of minutes between `window_start_utc` and
    `window_end_utc` divided by `slot_length_minutes` and truncated downward, never
    rounded up."
    PRD §3.2: "The live counter `booked_slot_count` is the number of this event's
    appointments whose status is `BOOKED`, `ATTENDED` or `NO_SHOW`; cancelled
    appointments are excluded and free their capacity again."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/screening_event_system_fields_are_server_minted
    """
    site = fx.register_site(api, screening_host_approved=True, status="ACTIVE")

    # A three-hour window with thirty-minute appointments physically holds six, so the
    # declared capacity of four is the binding figure.
    response = api.create_screening_event(
        f.screening_event_payload(
            site["id"],
            event_label="August Child Find",
            window_start_utc=ts("2026-08-20T09:00:00Z"),
            window_end_utc=ts("2026-08-20T12:00:00Z"),
            slot_capacity=4,
            slot_length_minutes=30,
        ),
        COORDINATOR,
    )
    event = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single created resource is an object envelope, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert body["meta"]["api_request_timestamp"].strip(), (
        "api_request_timestamp must be present and non-empty"
    )

    assert_screening_event(event, expected_version=1)
    _assert_three_fractional_digits(event["created_at"], "created_at")
    _assert_three_fractional_digits(event["updated_at"], "updated_at")
    assert_subset(
        event,
        {
            "site_id": site["id"],
            "event_label": "August Child Find",
            "slot_capacity": 4,
            "slot_length_minutes": 30,
            "effective_slot_capacity": 4,
            "booked_slot_count": 0,
            "status": "SCHEDULED",
        },
    )


# -------------------------------------------------------------------- list windows
def test_domain_assessment_listing_paginates_within_one_case(api):
    """PRD §2.3: "List results are always ordered by `created_at` ascending — oldest
    record first — and no endpoint offers an alternative sort. When a list endpoint
    responds, its `meta` object carries the four pagination fields `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the size of the filtered result
    set before the page window is applied and `has_more` is true exactly when records
    remain beyond the current window."
    PRD §3.5: "Assessments can be listed and filtered by `evaluation_case_id`,
    `evaluator_provider_id`, `assessment_site_id`, `domain`, `method` and `status`."

    Design: Corner/entities/domain_assessment_listing_filters_by_case_and_paginates
    """
    case_id = _case_with_five_scheduled_assessments(api)["case_id"]

    first_page, first_meta = validate_paginated(
        api.list_domain_assessments(
            COORDINATOR, {"evaluation_case_id": case_id, "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, f"limit=2 must return two rows, got {len(first_page)}"
    assert_page_meta(
        first_meta,
        expected_limit=2,
        expected_offset=0,
        expected_total=5,
        expected_has_more=True,
    )
    assert_ordered_by_created_at(first_page)

    last_page, last_meta = validate_paginated(
        api.list_domain_assessments(
            COORDINATOR, {"evaluation_case_id": case_id, "limit": 2, "offset": 4}
        )
    )
    assert len(last_page) == 1, (
        f"offset=4 of five rows must return one row, got {len(last_page)}"
    )
    assert_page_meta(
        last_meta,
        expected_limit=2,
        expected_offset=4,
        expected_total=5,
        expected_has_more=False,
    )


def test_domain_assessment_listing_narrows_total_count_by_domain(api):
    """PRD §2.3: "When a list endpoint responds, its `meta` object carries the four
    pagination fields `limit`, `offset`, `total_count` and `has_more`, where
    `total_count` is the size of the filtered result set before the page window is
    applied and `has_more` is true exactly when records remain beyond the current
    window."
    PRD §3.5: "Assessments can be listed and filtered by `evaluation_case_id`,
    `evaluator_provider_id`, `assessment_site_id`, `domain`, `method` and `status`."

    Design: Corner/entities/domain_assessment_listing_filters_by_case_and_paginates
    """
    context = _case_with_five_scheduled_assessments(api)

    rows, meta = validate_paginated(
        api.list_domain_assessments(
            COORDINATOR,
            {"evaluation_case_id": context["case_id"], "domain": "ADAPTIVE"},
        )
    )

    assert_page_meta(meta, expected_total=1, expected_has_more=False)
    assert len(rows) == 1, f"the ADAPTIVE filter must return one row, got {len(rows)}"
    assert rows[0]["id"] == context["assessments"]["ADAPTIVE"]["id"], (
        f"expected the ADAPTIVE assessment, got {rows[0]['id']!r}"
    )
    assert rows[0]["domain"] == "ADAPTIVE", (
        f"the filtered row must carry domain ADAPTIVE, got {rows[0]['domain']!r}"
    )
    assert_domain_assessment(rows[0])


def _case_with_five_scheduled_assessments(api):
    """One consent-granted evaluation case carrying one SCHEDULED assessment per domain.

    Each domain is given its own evaluator of an eligible discipline and its own
    non-overlapping window, so no duplicate-domain or evaluator-conflict rule bites.
    """
    context = fx.setup_case(api)
    evaluators = fx.register_domain_evaluators(api)
    assessments = {}
    for domain, evaluator in evaluators.items():
        assessments[domain] = fx.schedule_assessment(
            api,
            context["case"]["id"],
            evaluator["id"],
            domain=domain,
            window_start_utc=fx.DOMAIN_WINDOW_STARTS[domain],
        )
    return {
        "case_id": context["case"]["id"],
        "evaluators": evaluators,
        "assessments": assessments,
    }


# ------------------------------------------------------------ the existence ladder
NOT_FOUND_READS = [
    ("get_child", ApiErrorId.ERR_CHILD_NOT_FOUND),
    ("get_community_site", ApiErrorId.ERR_COMMUNITY_SITE_NOT_FOUND),
    ("get_provider", ApiErrorId.ERR_PROVIDER_NOT_FOUND),
    ("get_screening_event", ApiErrorId.ERR_SCREENING_EVENT_NOT_FOUND),
    ("get_screening_slot", ApiErrorId.ERR_SCREENING_SLOT_NOT_FOUND),
    ("get_referral", ApiErrorId.ERR_REFERRAL_NOT_FOUND),
    ("get_consent_record", ApiErrorId.ERR_CONSENT_RECORD_NOT_FOUND),
    ("get_evaluation_case", ApiErrorId.ERR_EVALUATION_CASE_NOT_FOUND),
    ("get_domain_assessment", ApiErrorId.ERR_DOMAIN_ASSESSMENT_NOT_FOUND),
    ("get_service_plan", ApiErrorId.ERR_SERVICE_PLAN_NOT_FOUND),
    ("get_service_line", ApiErrorId.ERR_SERVICE_LINE_NOT_FOUND),
]


@pytest.mark.parametrize(
    "read_method,expected_error",
    NOT_FOUND_READS,
    ids=[method for method, _ in NOT_FOUND_READS],
)
def test_unknown_id_returns_the_entity_specific_not_found_error(
    api, read_method, expected_error
):
    """PRD §2.5: "Each entity has its own not-found code, all of them HTTP 404:
    `ERR_CHILD_NOT_FOUND`, `ERR_COMMUNITY_SITE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_SCREENING_EVENT_NOT_FOUND`, `ERR_SCREENING_SLOT_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_CONSENT_RECORD_NOT_FOUND`,
    `ERR_EVALUATION_CASE_NOT_FOUND`, `ERR_DOMAIN_ASSESSMENT_NOT_FOUND`,
    `ERR_SERVICE_PLAN_NOT_FOUND` and `ERR_SERVICE_LINE_NOT_FOUND`."
    PRD §2.5: "Every identifier appearing as a path segment resolves to an existing row
    of the expected entity, on every endpoint that has a path parameter, using the
    entity-specific 404 code above."

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_error
    """
    response = getattr(api, read_method)(MISSING_UUID, COORDINATOR)

    validate_error(response, expected_error.value)
    assert response.json()["response_type"] == "error", (
        "a refusal must use the error envelope, got "
        f"{response.json()['response_type']!r}"
    )


# ------------------------------------------------------- request-shape: omissions
CHILD_REQUIRED_FIELDS = [
    "first_name",
    "last_name",
    "date_of_birth",
    "guardian_full_name",
    "district_of_residence",
]


@pytest.mark.parametrize("omitted", CHILD_REQUIRED_FIELDS)
def test_child_registration_missing_required_field_is_rejected(api, omitted):
    """PRD §3.1: "A `ChildFindCoordinator` (or a `DistrictAdmin`) registers one by
    supplying `first_name` and `last_name`, each non-empty and at most 80 characters; a
    `date_of_birth` as a plain calendar date in year-month-day form, which must fall
    strictly before the logical clock's current date; the `guardian_full_name` of the
    parent or guardian holding educational rights, non-empty; and a
    `district_of_residence` code, non-empty and at most 20 characters, because the child
    find obligation follows residence rather than enrolment."
    PRD §2.5: "Request-shape validation on every request: the body parses, every required
    input field is present, and every supplied field matches its declared type,
    enumeration and range."

    Design: Corner/entities/missing_required_input_field_is_rejected_before_any_row_is_created
    """
    payload = f.child_payload(**{omitted: ...})
    assert omitted not in payload, f"{omitted} must be absent from the probe payload"

    response = api.create_child(payload, COORDINATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_children(COORDINATOR))
    assert meta["total_count"] == 0, (
        f"a rejected registration must leave no child behind, got {meta['total_count']}"
    )


PROVIDER_REQUIRED_FIELDS = ["full_name", "discipline", "home_region_code"]


@pytest.mark.parametrize("omitted", PROVIDER_REQUIRED_FIELDS)
def test_provider_registration_missing_required_field_is_rejected(api, omitted):
    """PRD §3.1: "A `Provider` record carries a `full_name`; a `discipline` drawn from
    `SCHOOL_PSYCHOLOGIST`, `SLP`, `OT`, `PT`, `ECSE_TEACHER`, `SOCIAL_WORKER` and
    `INTERPRETER`; a `home_region_code` naming where the provider is based (non-empty, at
    most 20 characters); an optional `languages` list of two-letter codes the provider can
    deliver service or interpretation in, defaulting to a single entry of `en`; and an
    optional `status` of `ACTIVE`, `ON_LEAVE` or `INACTIVE`, defaulting to `ACTIVE`."
    PRD §2.5: "Request-shape validation on every request: the body parses, every required
    input field is present, and every supplied field matches its declared type,
    enumeration and range."

    Design: Corner/entities/missing_required_input_field_is_rejected_before_any_row_is_created
    """
    payload = f.provider_payload(**{omitted: ...})
    assert omitted not in payload, f"{omitted} must be absent from the probe payload"

    response = api.create_provider(payload, DISTRICT_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_providers(DISTRICT_ADMIN))
    assert meta["total_count"] == 0, (
        f"a rejected registration must leave no provider behind, got {meta['total_count']}"
    )


# ------------------------------------------- request-shape: enums, ranges, windows
def test_unrecognised_assessment_method_is_rejected_and_a_valid_one_is_accepted(api):
    """PRD §3.5: "Scheduling a developmental-domain assessment is done by the chair or
    by a coordinator, naming the `evaluator_provider_id` who will administer it, the
    `domain` being assessed from `COGNITIVE`, `COMMUNICATION`, `PHYSICAL_MOTOR`,
    `SOCIAL_EMOTIONAL` and `ADAPTIVE`, the `method` from `STANDARDIZED`, `PLAY_BASED`,
    `OBSERVATION` and `PARENT_REPORT`."
    PRD §2.5: "every supplied field matches its declared type, enumeration and range
    ... Violations are `ERR_INVALID_REQUEST` (400)."
    PRD §3.5: "The first assessment scheduled on a case moves the case
    `PLANNED → IN_PROGRESS`."

    Design: Corner/entities/bad_enums_and_off_increment_numbers_are_rejected
    """
    context = fx.setup_case(api)
    case_id = context["case"]["id"]
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")

    rejected = api.schedule_domain_assessment(
        case_id,
        f.domain_assessment_payload(
            evaluator["id"], domain="COGNITIVE", method="GUESSWORK"
        ),
        COORDINATOR,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = fx.listing(
        api, "list_domain_assessments", COORDINATOR, evaluation_case_id=case_id
    )
    assert meta["total_count"] == 0, (
        "a refused schedule must leave the case with no assessments, got "
        f"{meta['total_count']}"
    )
    assert fx.read_case(api, case_id)["status"] == "PLANNED", (
        "a refused schedule must not move the case out of PLANNED"
    )

    accepted = validate_success(
        api.schedule_domain_assessment(
            case_id,
            f.domain_assessment_payload(
                evaluator["id"], domain="COGNITIVE", method="STANDARDIZED"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_domain_assessment(accepted, expected_version=1)
    assert accepted["method"] == "STANDARDIZED", (
        f"the accepted method must be stored verbatim, got {accepted['method']!r}"
    )
    assert accepted["status"] == "SCHEDULED", (
        f"a scheduled assessment is written at SCHEDULED, got {accepted['status']!r}"
    )
    assert fx.read_case(api, case_id)["status"] == "IN_PROGRESS", (
        "the first assessment on a case moves it from PLANNED to IN_PROGRESS"
    )

    _, meta = fx.listing(
        api, "list_domain_assessments", COORDINATOR, evaluation_case_id=case_id
    )
    assert meta["total_count"] == 1, (
        f"exactly one assessment must have been written, got {meta['total_count']}"
    )


def test_assessment_window_must_end_strictly_after_it_starts(api):
    """PRD §3.5: "the evaluator's occupation window as `window_start_utc` (inclusive)
    and `window_end_utc` (exclusive), both ISO 8601 UTC with three fractional digits and
    the end strictly after the start."
    PRD §2.5: "This step also covers pagination bounds, ISO 8601 parseability,
    `weekly_minutes` being a multiple of 5 within 5 through 600 inclusive, and
    `window_end_utc` falling strictly after `window_start_utc`. Violations are
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/bad_enums_and_off_increment_numbers_are_rejected
    """
    context = fx.setup_case(api)
    case_id = context["case"]["id"]
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")
    instant = ts("2026-08-05T09:00:00Z")

    response = api.schedule_domain_assessment(
        case_id,
        f.domain_assessment_payload(
            evaluator["id"],
            domain="COGNITIVE",
            window_start_utc=instant,
            window_end_utc=instant,
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = fx.listing(
        api, "list_domain_assessments", COORDINATOR, evaluation_case_id=case_id
    )
    assert meta["total_count"] == 0, (
        "a zero-length window must leave no assessment behind, got "
        f"{meta['total_count']}"
    )


def test_service_line_weekly_minutes_off_the_five_minute_increment_is_rejected(api):
    """PRD §3.8: "the `weekly_minutes` of direct service, which must be a multiple of 5
    between 5 and 600 inclusive."
    PRD §2.5: "This step also covers pagination bounds, ISO 8601 parseability,
    `weekly_minutes` being a multiple of 5 within 5 through 600 inclusive, and
    `window_end_utc` falling strictly after `window_start_utc`. Violations are
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/bad_enums_and_off_increment_numbers_are_rejected
    """
    context = fx.setup_draft_plan(api)
    plan_id = context["plan"]["id"]

    response = api.add_service_line(
        plan_id,
        f.service_line_payload(discipline="SLP", weekly_minutes=97, delivery_model="DIRECT"),
        PLACEMENT,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = fx.listing(api, "list_service_lines", PLACEMENT, service_plan_id=plan_id)
    assert meta["total_count"] == 0, (
        f"a refused line must not be written, got {meta['total_count']}"
    )
    assert fx.read_plan(api, plan_id)["assigned_weekly_minutes"] == 0, (
        "a refused line must not move the plan's assigned minutes"
    )


# ------------------------------------------------- body foreign keys must resolve
def test_referral_intake_rejects_an_unknown_child_in_the_body(api):
    """PRD §2.5: "Every foreign key supplied in a request body resolves to an existing
    row, checked after all path identifiers and in the order the endpoint declares its
    inputs, again with the entity-specific 404 code. This applies to screening-event
    creation, slot booking, referral intake, consent-request issuance, evaluation-case
    opening, domain-assessment scheduling, service-plan creation, service-line creation
    and service-line staffing."

    Design: Corner/entities/body_level_foreign_keys_must_exist_before_the_row_is_created
    """
    response = api.create_referral(f.referral_payload(MISSING_UUID), COORDINATOR)

    validate_error(response, ApiErrorId.ERR_CHILD_NOT_FOUND.value)

    _, meta = fx.listing(api, "list_referrals", COORDINATOR)
    assert meta["total_count"] == 0, (
        f"an unresolvable child must leave no referral behind, got {meta['total_count']}"
    )


def test_screening_event_creation_rejects_an_unknown_host_site_in_the_body(api):
    """PRD §3.2: "A `ChildFindCoordinator` schedules a screening event — a community
    child find day — by naming the host `site_id`."
    PRD §2.5: "Every foreign key supplied in a request body resolves to an existing row,
    checked after all path identifiers and in the order the endpoint declares its inputs,
    again with the entity-specific 404 code. This applies to screening-event creation
    ..."

    Design: Corner/entities/body_level_foreign_keys_must_exist_before_the_row_is_created
    """
    response = api.create_screening_event(
        f.screening_event_payload(MISSING_UUID), COORDINATOR
    )

    validate_error(response, ApiErrorId.ERR_COMMUNITY_SITE_NOT_FOUND.value)

    _, meta = fx.listing(api, "list_screening_events", COORDINATOR)
    assert meta["total_count"] == 0, (
        f"an unresolvable host site must leave no event behind, got {meta['total_count']}"
    )


def test_case_opening_rejects_an_unknown_chair_provider_in_the_body(api):
    """PRD §3.4: "With consent granted, a `ChildFindCoordinator` opens the evaluation by
    naming a `chair_provider_id`."
    PRD §2.5: "Every foreign key supplied in a request body resolves to an existing row,
    checked after all path identifiers and in the order the endpoint declares its inputs,
    again with the entity-specific 404 code. This applies to ... evaluation-case
    opening ..."
    The existence rule sits above chair eligibility, above concurrency and above every
    state precondition in the ladder, so an unresolvable provider is the reported fault.

    Design: Corner/entities/body_level_foreign_keys_must_exist_before_the_row_is_created
    """
    granted = fx.setup_referral_with_granted_consent(api)

    response = api.open_evaluation_case(
        granted["referral"]["id"], f.evaluation_case_payload(MISSING_UUID), COORDINATOR
    )

    validate_error(response, ApiErrorId.ERR_PROVIDER_NOT_FOUND.value)

    _, meta = fx.listing(api, "list_evaluation_cases", COORDINATOR)
    assert meta["total_count"] == 0, (
        f"an unresolvable chair must leave no case behind, got {meta['total_count']}"
    )


# ------------------------------------ the service line as a three-way junction row
def _staffed_line_delivered_away_from_the_seat_site(api):
    """A community-preschool plan whose only line is delivered at a partner site.

    The plan holds the IEP seat at one site while the itinerant provider delivers the
    minutes at a second, which is exactly the split PRD §3.8 permits.
    """
    seat_site = fx.register_site(api)
    delivery_site = fx.register_site(api)
    context = fx.setup_draft_plan(
        api, setting="COMMUNITY_PRESCHOOL", community_site_id=seat_site["id"]
    )
    provider = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=400
    )
    line = fx.add_line(
        api,
        context["plan"]["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
    )
    line = fx.staff_line(
        api, line["id"], provider["id"], delivery_site_id=delivery_site["id"]
    )
    return {
        "seat_site": seat_site,
        "delivery_site": delivery_site,
        "plan": fx.read_plan(api, context["plan"]["id"]),
        "provider": provider,
        "line": fx.read_line(api, line["id"]),
    }


def test_service_line_joins_its_plan_its_provider_and_its_delivery_site(api):
    """PRD §3.8: "Staffing a line is the placement office's exclusive act. It names the
    `provider_id` who will deliver the minutes, the `expected_provider_version` of §2.6,
    and optionally a `delivery_site_id` saying where the minutes are actually delivered —
    an itinerant provider may serve a child at a partner site rather than the site
    holding the IEP seat."
    PRD §3.8: "A successful staffing moves the line `PROPOSED → STAFFED` or
    `UNSTAFFED → STAFFED`, sets `provider_id` to the named provider and
    `delivery_site_id` to the supplied or defaulted location."

    Design: Corner/entities/service_line_is_the_junction_of_plan_provider_and_delivery_site
    """
    context = _staffed_line_delivered_away_from_the_seat_site(api)
    line = context["line"]

    assert_service_line(line, expected_version=2)
    assert_subset(
        line,
        {
            "service_plan_id": context["plan"]["id"],
            "provider_id": context["provider"]["id"],
            "delivery_site_id": context["delivery_site"]["id"],
            "discipline": "SLP",
            "weekly_minutes": 150,
            "delivery_model": "DIRECT",
            "status": "STAFFED",
        },
    )
    assert context["plan"]["community_site_id"] == context["seat_site"]["id"], (
        "the plan still holds its IEP seat at the site named on determination"
    )
    assert line["delivery_site_id"] != context["plan"]["community_site_id"], (
        "the line's delivery location is its own field, not a copy of the plan's site"
    )


def test_service_line_listing_filters_on_each_of_its_three_references(api):
    """PRD §3.8: "Lines can be listed and filtered by `service_plan_id`, `provider_id`,
    `delivery_site_id`, `discipline`, `delivery_model` and `status`."
    PRD §2.3: "`total_count` is the size of the filtered set before the page window is
    applied."

    Design: Corner/entities/service_line_is_the_junction_of_plan_provider_and_delivery_site
    """
    context = _staffed_line_delivered_away_from_the_seat_site(api)
    line_id = context["line"]["id"]

    by_plan, plan_meta = fx.listing(
        api, "list_service_lines", PLACEMENT, service_plan_id=context["plan"]["id"]
    )
    assert plan_meta["total_count"] == 1, (
        f"the plan owns exactly one line, got {plan_meta['total_count']}"
    )
    assert_contains_id(by_plan, line_id)

    by_provider, provider_meta = fx.listing(
        api, "list_service_lines", PLACEMENT, provider_id=context["provider"]["id"]
    )
    assert provider_meta["total_count"] == 1, (
        f"the staffed provider names exactly one line, got {provider_meta['total_count']}"
    )
    assert_contains_id(by_provider, line_id)

    by_delivery_site, delivery_meta = fx.listing(
        api,
        "list_service_lines",
        PLACEMENT,
        delivery_site_id=context["delivery_site"]["id"],
    )
    assert delivery_meta["total_count"] == 1, (
        "the delivery site carries exactly one line, got "
        f"{delivery_meta['total_count']}"
    )
    assert_contains_id(by_delivery_site, line_id)

    _, seat_meta = fx.listing(
        api, "list_service_lines", PLACEMENT, delivery_site_id=context["seat_site"]["id"]
    )
    assert seat_meta["total_count"] == 0, (
        "no minutes are delivered at the seat site, so the filter selects nothing, got "
        f"{seat_meta['total_count']}"
    )
