"""
Two cross-cutting layers: the optimistic-concurrency guard on plan authoring,
and the deterministic coordinator selector that ranks on projected utilization.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_case_weight,
    assert_caseload_summary,
    assign_coordinator,
    build_assessments_completed,
    create_child,
    create_coordinator,
    create_referral,
    determine_eligibility,
    factories,
    read_caseload_summary,
    read_referral,
    record_entry_outcomes,
    referral_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DETERMINATION_DATE = "2026-03-20"
MEASUREMENT_DATE = "2026-03-20"
MEETING_DATE = "2026-03-20"


class TestStaleReferralVersion:

    def test_a_version_read_before_two_transitions_is_refused_then_refreshed(
        self, api
    ):
        """
        A referral version captured before the eligibility determination is two
        increments behind by the time the plan is authored, so authoring is refused
        with 412 and nothing is written. Re-reading the referral makes the identical
        payload succeed, which proves the guard is a version comparison and not a
        state or payload rule.

        PRD 2.6: "A `POST /ei/ifsps` request must carry `expected_referral_version`
        as a required, non-optional input field whose value is the `version` of the
        target `Referral` as the client last observed it."
        PRD 2.6: "If the referral's stored `version` no longer equals the submitted
        `expected_referral_version` at the moment the write would be applied, the
        request is rejected with `ERR_STALE_REFERRAL_VERSION` (HTTP 412): no `IFSP`
        row is created, no counter on any entity is touched, and the referral's own
        `version` is left unchanged."
        PRD 2.6: "Every request that mutates the referral aggregate advances
        `Referral.version` by 1 — coordinator assignment, eligibility determination,
        entry-outcome recording, case exit, and plan authoring itself."

        Design: Corner/complexity_layers/stale_expected_referral_version_is_rejected_then_accepted_after_a_refresh
        """
        case = build_assessments_completed(api)
        stale_version = referral_version(api, case.referral_id)

        determine_eligibility(
            api, case.referral_id, determination_date=DETERMINATION_DATE
        )
        record_entry_outcomes(
            api, case.referral_id, measurement_date=MEASUREMENT_DATE
        )

        stale_attempt = api.create_ifsp(
            factories.ifsp_payload(
                case.referral_id,
                case.coordinator_id,
                stale_version,
                meeting_date=MEETING_DATE,
            ),
            ADMIN_HEADERS,
        )
        validate_error(
            stale_attempt, ApiErrorId.STALE_REFERRAL_VERSION.value, 412
        )
        _, meta = validate_paginated(
            api.list_ifsps(ADMIN_HEADERS, {"referral_id": case.referral_id})
        )
        assert meta["total_count"] == 0
        blocked = read_referral(api, case.referral_id)
        assert blocked["status"] == "IFSP_PENDING"

        fresh_version = referral_version(api, case.referral_id)
        assert fresh_version > stale_version

        authored = validate_success(
            api.create_ifsp(
                factories.ifsp_payload(
                    case.referral_id,
                    case.coordinator_id,
                    fresh_version,
                    meeting_date=MEETING_DATE,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert authored["status"] == "DRAFT"
        assert authored["ifsp_type"] == "INITIAL"
        assert read_referral(api, case.referral_id)["version"] == fresh_version + 1


# ─── The selector walks its layers in order ───────────────────────────

INTAKE_CLOCK_FOR_SELECTION = "2026-03-02T09:00:00Z"
SMALL_CAP = 6.00
LARGE_CAP = 12.00
CHILD_A = {"first_name": "Ada", "last_name": "Nolan", "date_of_birth": "2024-06-15"}
CHILD_B = {"first_name": "Ben", "last_name": "Ito", "date_of_birth": "2024-07-01"}
CHILD_C = {"first_name": "Cara", "last_name": "Diaz", "date_of_birth": "2024-07-20"}
CHILD_D = {
    "first_name": "Diego",
    "last_name": "Marin",
    "date_of_birth": "2024-08-01",
    "primary_language": "ES",
}


class TestCoordinatorAutoSelection:

    def test_ranking_is_projected_utilization_then_created_at_after_filtering(
        self, api
    ):
        """
        Four auto-assignments walk the selector end to end: ranking is on the
        projected ratio and not on raw points, ties fall to the earlier row, and the
        language clause filters candidates before any ranking happens. The
        out-of-county coordinator has the lowest ratio throughout and is never
        chosen.

        PRD 3.2: "A coordinator is a candidate for a case when four clauses all
        hold: the coordinator's `status` is `ACTIVE`; the coordinator's `county_code`
        equals the referral's `county_code`; either the case does not require an
        interpreter, or the case's family `primary_language` appears in the
        coordinator's `language_codes`; and the coordinator's current
        `weighted_caseload_points` plus the case's projected `case_weight_points` is
        less than or equal to the coordinator's `max_weighted_caseload_points`."
        PRD 3.2: "Each candidate is ranked by its **projected utilization** — the
        coordinator's current `weighted_caseload_points` plus the case's projected
        weight, divided by that coordinator's `max_weighted_caseload_points`, rounded
        half up to four decimal places — and the candidate with the lowest projected
        utilization wins."
        PRD 3.2: "When two candidates tie on the rounded ratio, the earlier
        `created_at` wins."
        PRD 3.2: "A case in any pre-plan stage — `INTAKE`, `EVALUATION_PENDING`,
        `ELIGIBILITY_DETERMINED` or `IFSP_PENDING` — takes a base of 1.50 points,
        because pre-plan work is the heavier part of the job."
        PRD 3.2: "When the case's `interpreter_required` flag is true, add 0.50
        points."

        Design: Corner/complexity_layers/coordinator_selector_ranks_by_projected_utilization_then_created_at
        """
        set_clock(api, INTAKE_CLOCK_FOR_SELECTION)
        first = create_coordinator(
            api, full_name="Dana Reyes", max_weighted_caseload_points=SMALL_CAP
        )
        bilingual = create_coordinator(
            api,
            full_name="Sam Ortiz",
            language_codes=["EN", "ES"],
            max_weighted_caseload_points=SMALL_CAP,
        )
        roomiest = create_coordinator(
            api, full_name="Lee Park", max_weighted_caseload_points=LARGE_CAP
        )
        out_of_county = create_coordinator(
            api,
            full_name="Nia Bell",
            county_code="CNT_B",
            max_weighted_caseload_points=LARGE_CAP,
        )

        referrals = []
        for child, source, interpreter in (
            (CHILD_A, "PHYSICIAN", False),
            (CHILD_B, "PARENT", False),
            (CHILD_C, "CHILD_CARE", False),
            (CHILD_D, "HOSPITAL", True),
        ):
            child_id = create_child(api, **child)
            referrals.append(
                create_referral(
                    api,
                    child_id,
                    primary_referral_source=source,
                    interpreter_required=interpreter,
                )
            )

        lowest_ratio = assign_coordinator(api, referrals[0])
        assert lowest_ratio["coordinator_id"] == roomiest
        assert_case_weight(lowest_ratio["case_weight_points"], 1.50)

        three_way_tie = assign_coordinator(api, referrals[1])
        assert three_way_tie["coordinator_id"] == first

        two_way_tie = assign_coordinator(api, referrals[2])
        assert two_way_tie["coordinator_id"] == bilingual

        language_filtered = assign_coordinator(api, referrals[3])
        assert language_filtered["coordinator_id"] == bilingual
        assert_case_weight(language_filtered["case_weight_points"], 2.00)

        assert_caseload_summary(
            read_caseload_summary(api, bilingual),
            coordinator_id=bilingual,
            active_case_count=2,
            weighted_caseload_points=3.50,
            max_weighted_caseload_points=SMALL_CAP,
            utilization_ratio=0.5833,
            caseload_posture="OPEN",
            headroom_points=2.50,
        )
        assert_caseload_summary(
            read_caseload_summary(api, out_of_county),
            active_case_count=0,
            weighted_caseload_points=0.00,
            utilization_ratio=0.0000,
            caseload_posture="OPEN",
            headroom_points=LARGE_CAP,
        )
