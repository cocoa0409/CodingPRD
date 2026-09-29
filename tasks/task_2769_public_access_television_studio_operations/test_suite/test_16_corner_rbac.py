"""RBAC corners: exclusive operations refuse every other role, shared ones accept each partner."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    FINANCE_HEADERS,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    make_producer_headers,
)

FABRICATED_PRODUCER = "00000000-0000-4000-8000-000000000001"
FABRICATED_PROGRAM = "00000000-0000-4000-8000-000000000005"
FABRICATED_CHANNEL = "00000000-0000-4000-8000-000000000007"
FABRICATED_RESERVATION = "00000000-0000-4000-8000-00000000000a"
FABRICATED_ASSESSMENT = "00000000-0000-4000-8000-00000000000b"
FABRICATED_ASSET = "00000000-0000-4000-8000-00000000000e"


def test_an_exclusive_operation_answers_on_role_before_it_resolves_its_path(client):
    """Eight single-role operations, eight wrong roles, eight 403s and never a 404.

    PRD 2.1: "When both headers are present but the named role is not one of the roles
    the target operation permits, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403). Role authorisation outranks payload validation: a wrong role submitting
    a malformed body receives 403, not 400."

    PRD 2.8: "**Role authorisation (priority 2)** — `ERR_FORBIDDEN_ROLE`, 403. Applies
    to every operation."

    PRD 2.8: "**Path existence (priority 4)** — the addressed entity's own not-found
    error, 404. Applies to every operation with a path parameter. Path identifiers are
    resolved left to right and the leftmost missing segment decides which error is
    reported."

    PRD 4: "Request bodies, response payloads and side effects are not restated here —
    they are specified in §2 and §3, and the table below is only a directory of methods,
    paths, purposes and authorised roles."

    Design: Corner/rbac/corner_rbac_exclusive_operations_denied_to_every_other_role
    """
    attempts = [
        (
            "POST /training-courses is the TrainingCoordinator's alone",
            client.create_training_course(
                f.training_course_payload(
                    course_code="TV-999",
                    title="Rogue Course",
                    grants_competency_codes=["STUDIO_FLOOR"],
                    seat_capacity=4,
                    session_start_at="2026-09-01T17:00:00Z",
                    session_end_at="2026-09-01T21:00:00Z",
                ),
                ADMIN_HEADERS,
            ),
        ),
        (
            "POST /programs/{id}/review-claim is the ContentReviewer's alone",
            client.claim_program_review(FABRICATED_PROGRAM, None, SCHEDULER_HEADERS),
        ),
        (
            "POST /playback-slots is the SchedulingCoordinator's alone",
            client.create_playback_slot(
                f.playback_slot_payload(FABRICATED_CHANNEL, FABRICATED_PROGRAM),
                REVIEWER_HEADERS,
            ),
        ),
        (
            "POST /reservations/{id}/confirm is the FacilitiesManager's alone",
            client.confirm_reservation(FABRICATED_RESERVATION, None, FINANCE_HEADERS),
        ),
        (
            "POST /damage-assessments/{id}/waive is the FinanceOfficer's alone",
            client.waive_damage_assessment(
                FABRICATED_ASSESSMENT,
                f.waiver_payload(waiver_reason="No"),
                FACILITIES_HEADERS,
            ),
        ),
        (
            "POST /funding-periods is the FinanceOfficer's alone",
            client.create_funding_period(
                f.funding_period_payload(
                    fiscal_year=2026,
                    quarter=1,
                    basis="ACCRUAL",
                    gross_franchise_fee_cents=100,
                    service_period_earned_cents=100,
                    remittance_received_cents=100,
                    capital_grant_cents=0,
                ),
                TRAINER_HEADERS,
            ),
        ),
        (
            "POST /producers is the CenterAdmin's alone",
            client.create_producer(
                f.producer_payload(legal_name="Rogue Entry", email="rogue@patv.example"),
                make_producer_headers(FABRICATED_PRODUCER),
            ),
        ),
        (
            "POST /archive-assets/{id}/purge is the CenterAdmin's alone",
            client.purge_archive_asset(FABRICATED_ASSET, None, SCHEDULER_HEADERS),
        ),
    ]
    assert len(attempts) == 8

    for label, response in attempts:
        assert response.status_code == 403, label
        a.error_of(response, e.ERR_FORBIDDEN_ROLE, 403)

    malformed_and_wrong_role = client.create_training_course(
        f.training_course_payload(tier="GOLD", seat_capacity=-4), ADMIN_HEADERS
    )

    a.error_of(malformed_and_wrong_role, e.ERR_FORBIDDEN_ROLE, 403)

    producers, _p_meta = a.assert_pagination_meta(client.list_producers(ADMIN_HEADERS), 0)
    assert producers == []
    courses, _c_meta = a.assert_pagination_meta(client.list_training_courses(ADMIN_HEADERS), 0)
    assert courses == []
    periods, _f_meta = a.assert_pagination_meta(client.list_funding_periods(ADMIN_HEADERS), 0)
    assert periods == []


def test_each_shared_operation_reaches_the_same_outcome_by_either_route(client):
    """Four operations name two roles apiece, and both routes land identically.

    PRD 3.1: "Either the producer themselves or a `TrainingCoordinator` may create an
    enrollment by supplying `producer_id` and `course_id`; when the acting role is
    `Producer` the `producer_id` must be the acting user's own."

    PRD 3.1: "Withdrawal is the producer's escape hatch, available to the enrollee or to
    a `TrainingCoordinator`, and it is bounded by time: the `ENROLLED → WITHDRAWN`
    transition is permitted only while the logical clock is strictly before the course's
    `session_start_at`."

    PRD 3.2: "Either the owning producer or a `SchedulingCoordinator` proposes one by
    supplying `producer_id`, a `title`, a `cadence` of `WEEKLY`, `BIWEEKLY` or
    `MONTHLY`, a `first_air_date` naming the historic anchor claimed for this series'
    own run, and optionally a `predecessor_series_id` identifying the earlier series
    this one continues."

    PRD 3.3: "Withdrawal is available to the producer themselves or to a `CenterAdmin`,
    requires a `withdrawn_reason`, and reaches further than any other single operation
    in the system."

    PRD 2.1: "Staff roles are exempt from this ownership rule; it constrains only
    `Producer`."

    Design: Corner/rbac/corner_rbac_shared_operations_accept_each_declared_role
    """
    first = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    second = fx.setup_active_producer(client, legal_name="Grace Hopper")
    course = fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )

    by_producer = a.created_of(
        client.create_course_enrollment(
            f.enrollment_payload(first["id"], course["id"]),
            make_producer_headers(first["id"]),
        )
    )
    by_coordinator = a.created_of(
        client.create_course_enrollment(
            f.enrollment_payload(second["id"], course["id"]), TRAINER_HEADERS
        )
    )

    assert by_producer["status"] == "ENROLLED"
    assert by_coordinator["status"] == "ENROLLED"
    assert by_coordinator["producer_id"] == second["id"]
    assert a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))["enrolled_count"] == 2

    producer_withdrawal = a.data_of(
        client.withdraw_enrollment(
            by_producer["id"], None, make_producer_headers(first["id"])
        )
    )
    coordinator_withdrawal = a.data_of(
        client.withdraw_enrollment(by_coordinator["id"], None, TRAINER_HEADERS)
    )

    assert producer_withdrawal["status"] == "WITHDRAWN"
    assert coordinator_withdrawal["status"] == "WITHDRAWN"
    assert a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))["enrolled_count"] == 0

    own_series = a.created_of(
        client.create_series(
            f.series_payload(first["id"], title="Harbor Nights", cadence="WEEKLY"),
            make_producer_headers(first["id"]),
        )
    )
    staff_series = a.created_of(
        client.create_series(
            f.series_payload(
                second["id"],
                title="City Council Digest",
                cadence="MONTHLY",
                first_air_date="2026-08-21T00:00:00Z",
            ),
            SCHEDULER_HEADERS,
        )
    )

    assert own_series["status"] == "PROPOSED"
    assert staff_series["status"] == "PROPOSED"
    assert staff_series["producer_id"] == second["id"]
    a.assert_field_absent_or_null(own_series, "seniority_at")
    a.assert_field_absent_or_null(staff_series, "seniority_at")

    own_program = a.created_of(
        client.create_program(
            f.program_payload(
                first["id"], title="Pilot One", runtime_seconds=900,
                is_live=False, required_crew_roles=[],
            ),
            make_producer_headers(first["id"]),
        )
    )
    other_program = a.created_of(
        client.create_program(
            f.program_payload(
                second["id"], title="Pilot Two", runtime_seconds=900,
                is_live=False, required_crew_roles=[],
            ),
            make_producer_headers(second["id"]),
        )
    )
    assert own_program["review_status"] == "DRAFT"
    assert other_program["review_status"] == "DRAFT"

    withdrawn_by_producer = a.data_of(
        client.withdraw_program(
            own_program["id"],
            f.program_withdraw_payload(withdrawn_reason="Producer pulled the pilot"),
            make_producer_headers(first["id"]),
        )
    )
    withdrawn_by_centre = a.data_of(
        client.withdraw_program(
            other_program["id"],
            f.program_withdraw_payload(withdrawn_reason="Centre withdrew the pilot"),
            ADMIN_HEADERS,
        )
    )

    assert withdrawn_by_producer["review_status"] == "WITHDRAWN"
    assert withdrawn_by_producer["withdrawn_reason"] == "Producer pulled the pilot"
    assert withdrawn_by_centre["review_status"] == "WITHDRAWN"
    assert withdrawn_by_centre["withdrawn_reason"] == "Centre withdrew the pilot"
