"""
Values sitting exactly on a threshold, and one aggregation driven by an empty
input set. Each case is built so that a strict comparison in place of an
inclusive one, or a sum taken over the wrong row set, changes the verdict.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    MINIMUM_LEAD_DAYS,
    POST_EVALUATION_CLOCK,
    assert_case_weight,
    assert_caseload_summary,
    assert_timeline,
    assert_utilization_ratio,
    build_active_services,
    build_assessments_scheduled,
    create_child,
    create_coordinator,
    create_referral,
    create_transition_plan,
    factories,
    assign_coordinator,
    make_service_coordinator_headers,
    read_caseload_summary,
    read_child,
    read_coordinator,
    read_referral,
    read_timeline,
    read_transition_plan,
    set_clock,
    validate_error,
    validate_success,
)

# ─── The caseload ceiling met exactly ─────────────────────────────────

TIGHT_CEILING_POINTS = 3.00
PRE_PLAN_CASE_POINTS = 1.50

_SIBLING_CHILDREN = (
    {"first_name": "Ada", "last_name": "Nolan"},
    {"first_name": "Bram", "last_name": "Ostro"},
    {"first_name": "Cleo", "last_name": "Prine"},
)
_SIBLING_REFERRALS = (
    {
        "primary_referral_source": "PHYSICIAN",
        "presenting_concern": (
            "Expressive language delay noted at the 20-month well-child visit"
        ),
    },
    {
        "primary_referral_source": "PARENT",
        "presenting_concern": (
            "Parent reports the child is not yet walking independently"
        ),
    },
    {
        "primary_referral_source": "CHILD_CARE",
        "presenting_concern": (
            "Child care staff report limited peer interaction and few words"
        ),
    },
)


def _build_coordinator_at_half_capacity(api):
    """
    A coordinator whose ceiling is exactly two pre-plan cases wide, already
    carrying one of them, plus two more cases waiting in intake.
    """
    set_clock(api, "2026-03-02T09:00:00Z")
    coordinator_id = create_coordinator(
        api, max_weighted_caseload_points=TIGHT_CEILING_POINTS
    )
    referral_ids = []
    for child_overrides, referral_overrides in zip(
        _SIBLING_CHILDREN, _SIBLING_REFERRALS
    ):
        child_id = create_child(
            api, date_of_birth="2024-06-15", county_code="CNT_A", **child_overrides
        )
        referral_ids.append(
            create_referral(
                api,
                child_id,
                referral_received_date="2026-03-02",
                county_code="CNT_A",
                interpreter_required=False,
                **referral_overrides,
            )
        )
    assign_coordinator(api, referral_ids[0], coordinator_id)
    return coordinator_id, referral_ids


class TestCaseloadCeilingIsInclusive:
    """Landing on the ceiling is admitted; passing it by any amount is not."""

    def test_case_landing_exactly_on_the_ceiling_is_admitted(self, api):
        """
        The second pre-plan case takes the coordinator to precisely their
        ceiling, and the assignment must be accepted.

        PRD 3.2: "The capacity comparison is inclusive: a coordinator who would
        land exactly on their ceiling is eligible, and one who would exceed it by
        any amount is not."

        Design: Difficulty/boundary_precision_check/caseload_cap_exact_equality_admits_assignment
        """
        coordinator_id, referral_ids = _build_coordinator_at_half_capacity(api)

        before = read_coordinator(api, coordinator_id)
        assert_case_weight(before["weighted_caseload_points"], PRE_PLAN_CASE_POINTS)
        assert_utilization_ratio(before["utilization_ratio"], 0.5000)

        assigned = assign_coordinator(api, referral_ids[1], coordinator_id)
        assert assigned["status"] == "EVALUATION_PENDING"
        assert assigned["coordinator_id"] == coordinator_id
        assert_case_weight(assigned["case_weight_points"], PRE_PLAN_CASE_POINTS)

        coordinator = read_coordinator(api, coordinator_id)
        assert_case_weight(
            coordinator["weighted_caseload_points"], TIGHT_CEILING_POINTS
        )
        assert (
            coordinator["weighted_caseload_points"]
            == coordinator["max_weighted_caseload_points"]
        )
        assert_utilization_ratio(coordinator["utilization_ratio"], 1.0000)
        assert coordinator["active_case_count"] == 2

    def test_exact_equality_grades_as_at_cap_and_bars_the_next_case(self, api):
        """
        With points equal to the ceiling the posture is AT_CAP rather than
        NEAR_CAP or OVER, headroom is exactly zero, and a third case is refused
        without touching either row.

        PRD 3.2: "The posture is `OVER` when weighted points exceed the ceiling,
        `AT_CAP` when they equal it exactly, `NEAR_CAP` when neither of those
        holds but the utilization ratio is at least 0.9000, and `OPEN`
        otherwise — the tests are applied in that order, so an over-cap
        coordinator never reports `NEAR_CAP`."

        Design: Difficulty/boundary_precision_check/caseload_cap_exact_equality_admits_assignment
        """
        coordinator_id, referral_ids = _build_coordinator_at_half_capacity(api)
        assign_coordinator(api, referral_ids[1], coordinator_id)

        summary = read_caseload_summary(api, coordinator_id)
        assert_caseload_summary(
            summary,
            coordinator_id=coordinator_id,
            active_case_count=2,
            weighted_caseload_points=TIGHT_CEILING_POINTS,
            max_weighted_caseload_points=TIGHT_CEILING_POINTS,
            utilization_ratio=1.0000,
            caseload_posture="AT_CAP",
            headroom_points=0.00,
        )

        response = api.assign_coordinator(
            referral_ids[2],
            factories.assign_coordinator_payload(coordinator_id=coordinator_id),
            ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.CASELOAD_CAP_EXCEEDED.value, 409)

        refused = read_referral(api, referral_ids[2])
        assert refused["status"] == "INTAKE"
        assert refused["coordinator_id"] is None
        assert_case_weight(refused["case_weight_points"], 0.00)

        after = read_coordinator(api, coordinator_id)
        assert_case_weight(after["weighted_caseload_points"], TIGHT_CEILING_POINTS)
        assert after["active_case_count"] == 2


# ─── The 90-day notification lead straddled by one day ────────────────

TRANSITION_INTAKE_CLOCK = "2026-09-01T09:00:00Z"
TRANSITION_INTAKE_DATE = "2026-09-01"
NOTIFICATION_CLOCK = "2026-10-21T09:00:00Z"
TIMELY_NOTIFICATION_DATE = "2026-10-17"
LATE_NOTIFICATION_DATE = "2026-10-21"
LEA_CODE = "LEA_042"
TRANSITION_CASE_POINTS = 1.75

# Every date in the chain is pulled onto the September intake day so the two
# cases differ only in the child's date of birth.
_SEPTEMBER_CHAIN = {
    "clock": TRANSITION_INTAKE_CLOCK,
    "evaluation": {"scheduled_date": TRANSITION_INTAKE_DATE},
    "family_assessment": {"scheduled_date": TRANSITION_INTAKE_DATE},
    "completion_clock": TRANSITION_INTAKE_CLOCK,
    "evaluation_completion": {"completion_date": TRANSITION_INTAKE_DATE},
    "family_completion": {"completion_date": TRANSITION_INTAKE_DATE},
    "determination": {"determination_date": TRANSITION_INTAKE_DATE},
    "entry_outcomes": {
        "measurement_date": TRANSITION_INTAKE_DATE,
        "rating_social": 3,
        "rating_knowledge": 3,
        "rating_needs": 4,
    },
    "ifsp": {"meeting_date": TRANSITION_INTAKE_DATE},
    "consent": {"consent_signed_date": TRANSITION_INTAKE_DATE},
}


def _build_two_transition_cases(api):
    """
    Two live cases on one coordinator whose children turn three three days
    apart, each carrying a draft transition plan with the conference already
    held, read against a clock inside the transition window.
    """
    first = build_active_services(
        api,
        child={
            "first_name": "Ada",
            "last_name": "Nolan",
            "date_of_birth": "2024-01-15",
        },
        referral={
            "primary_referral_source": "PHYSICIAN",
            "referral_received_date": TRANSITION_INTAKE_DATE,
        },
        **_SEPTEMBER_CHAIN,
    )
    second = build_active_services(
        api,
        assign_coordinator_id=first.coordinator_id,
        child={
            "first_name": "Bram",
            "last_name": "Ostro",
            "date_of_birth": "2024-01-18",
        },
        referral={
            "primary_referral_source": "PARENT",
            "referral_received_date": TRANSITION_INTAKE_DATE,
            "presenting_concern": (
                "Parent reports few words and limited pretend play"
            ),
        },
        **_SEPTEMBER_CHAIN,
    )
    second.coordinator_id = first.coordinator_id

    set_clock(api, NOTIFICATION_CLOCK)
    first.clock = NOTIFICATION_CLOCK
    second.clock = NOTIFICATION_CLOCK
    for case in (first, second):
        case.transition_plan_id = create_transition_plan(
            api,
            case.ifsp_id,
            first.coordinator_id,
            "2026-11-15",
            conference_held_date="2026-10-15",
            transition_steps_count=3,
        )
    return first, second


def _notify(api, case, coordinator_id, notification_date):
    response = api.notify_lea(
        case.transition_plan_id,
        factories.notify_lea_payload(
            notification_date=notification_date,
            family_opt_out=False,
            lea_code=LEA_CODE,
        ),
        make_service_coordinator_headers(coordinator_id),
    )
    return validate_success(response, 200)


class TestNotificationLeadDayBoundary:
    """Ninety days is inside the obligation; eighty-nine is outside it."""

    def test_lead_of_exactly_ninety_days_is_timely(self, api):
        """
        A notification dated exactly 90 days before the child's third birthday
        grades TIMELY, because the comparison includes the boundary.

        PRD 3.9: "Both boundaries are inclusive on the timely side: a lead of
        exactly 90 days is `TIMELY` while 89 days is `LATE`, and a lead of
        exactly 270 days is `TIMELY` while 271 days is `EARLY`."

        Design: Difficulty/boundary_precision_check/lea_notification_lead_days_exactly_90_is_timely
        """
        first, _second = _build_two_transition_cases(api)

        notified = _notify(
            api, first, first.coordinator_id, TIMELY_NOTIFICATION_DATE
        )

        assert notified["notification_lead_days"] == MINIMUM_LEAD_DAYS
        assert notified["notification_compliance"] == "TIMELY"
        assert notified["status"] == "NOTIFIED"
        assert notified["lea_code"] == LEA_CODE
        assert notified["notification_date"] == TIMELY_NOTIFICATION_DATE
        assert read_child(api, first.child_id)["third_birthday_date"] == "2027-01-15"

    def test_lead_of_eighty_nine_days_is_late_yet_still_notifies(self, api):
        """
        One day short of the obligation the same request grades LATE, and the
        plan still reaches NOTIFIED — the verdict records the shortfall, it does
        not block the statutory act.

        PRD 3.9: "Given a non-negative lead, the verdict follows in this order:
        an opted-out plan is `WAIVED_OPT_OUT`; otherwise a lead of more than 270
        days is `EARLY`; otherwise a lead of at least 90 days is `TIMELY`;
        otherwise the notification is `LATE`."

        Design: Difficulty/boundary_precision_check/lea_notification_lead_days_exactly_90_is_timely
        """
        first, second = _build_two_transition_cases(api)

        late = _notify(api, second, first.coordinator_id, LATE_NOTIFICATION_DATE)

        assert late["notification_lead_days"] == MINIMUM_LEAD_DAYS - 1
        assert late["notification_compliance"] == "LATE"
        assert late["status"] == "NOTIFIED"
        assert read_child(api, second.child_id)["third_birthday_date"] == "2027-01-18"

        # The stored row agrees with the response on both derived fields.
        stored = read_transition_plan(api, second.transition_plan_id)
        assert stored["notification_lead_days"] == MINIMUM_LEAD_DAYS - 1
        assert stored["notification_compliance"] == "LATE"

        # Advancing the clock into the final six months lifted both cases off
        # the active base, which is what put them inside the notification window.
        for case in (first, second):
            assert_case_weight(
                read_referral(api, case.referral_id)["case_weight_points"],
                TRANSITION_CASE_POINTS,
            )
        coordinator = read_coordinator(api, first.coordinator_id)
        assert_case_weight(coordinator["weighted_caseload_points"], 3.50)
        assert_utilization_ratio(coordinator["utilization_ratio"], 0.2917)


# ─── An exclusion total summed over an empty row set ──────────────────

class TestExcludedDelayOverAnEmptySet:
    """No assessment has been completed, so nothing is excused."""

    def test_scheduled_assessments_contribute_no_excluded_days(self, api):
        """
        Two assessments exist but neither is completed, so the exclusion total
        is zero and the gross and net counts coincide.

        PRD 3.3: "Completing an assessment therefore reaches beyond the
        assessment row: the case's `excluded_delay_days` is recomputed as the sum
        of `family_unavailable_days` across every assessment on the case whose
        `status` is `COMPLETED`, and from that new figure the case's
        `gross_elapsed_days`, `net_elapsed_days` and `initial_timeline_status`
        are all recomputed in the same request."

        Design: Difficulty/boundary_precision_check/zero_excluded_delay_days_empty_assessment_set
        """
        case = build_assessments_scheduled(
            api,
            evaluation={"scheduled_date": "2026-03-24"},
            family_assessment={"scheduled_date": "2026-03-25"},
        )
        set_clock(api, POST_EVALUATION_CLOCK)

        compliance = read_timeline(api, case.referral_id)
        assert_timeline(
            compliance,
            statutory_deadline_date="2026-04-16",
            stop_date="2026-03-20",
            gross_elapsed_days=18,
            excluded_delay_days=0,
            net_elapsed_days=18,
            initial_timeline_status="IN_PROGRESS",
        )
        assert compliance["gross_elapsed_days"] == compliance["net_elapsed_days"]

        stored = read_referral(api, case.referral_id)
        assert stored["excluded_delay_days"] == 0
        assert stored["net_elapsed_days"] == 18

    def test_case_outside_active_services_reports_no_contact_obligation(self, api):
        """
        The same compliance read reports the monthly-contact picture, and a case
        that has not reached active services carries no obligation and no
        qualifying contact.

        PRD 3.9: "`monthly_contact_status` is `NOT_APPLICABLE` whenever the case
        is not in `ACTIVE_SERVICES`."

        Design: Difficulty/boundary_precision_check/zero_excluded_delay_days_empty_assessment_set
        """
        case = build_assessments_scheduled(
            api,
            evaluation={"scheduled_date": "2026-03-24"},
            family_assessment={"scheduled_date": "2026-03-25"},
        )
        set_clock(api, POST_EVALUATION_CLOCK)

        compliance = read_timeline(api, case.referral_id)
        assert compliance["referral_id"] == case.referral_id
        assert compliance["referral_received_date"] == "2026-03-02"
        assert compliance["monthly_contact_status"] == "NOT_APPLICABLE"
        assert compliance["last_qualifying_contact_date"] is None
        assert read_referral(api, case.referral_id)["status"] == "EVALUATION_PENDING"
