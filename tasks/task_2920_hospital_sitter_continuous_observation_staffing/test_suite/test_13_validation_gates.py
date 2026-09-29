"""
Validation breadth: the volunteer risk bar on both sides, the two whole-minute
break boundaries, the cross-unit float code, the handoff episode linkage, the
aggregate budget ceiling, the restricted-unit agency block, and the dependency
ordering that lets an unresolvable body FK outrank the competency floor.
"""

from test_helpers import (
    HTTP_CREATED,
    HTTP_NOT_FOUND,
    HTTP_PAYMENT_REQUIRED,
    HTTP_UNPROCESSABLE,
    ObservationApiClient,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_fields,
    assert_row_count,
    exactly_one,
    final_segment_rows,
)
from test_helpers.constants import (
    COMPETENCY_ADVANCED,
    COMPETENCY_NOT_TRAINED,
    COST_POSTED,
    DOC_HANDOFF_DRAFTED,
    DOC_PENDING,
    ENTRY_KIND_PROVISIONAL,
    ERR_BREAK_NOT_YET_ELIGIBLE,
    ERR_BREAK_TOO_SHORT,
    ERR_FLOAT_AUTHORIZATION_MISSING,
    ERR_HANDOFF_ORDER_MISMATCH,
    ERR_ORDER_NOT_FOUND,
    ERR_UNIT_BUDGET_EXCEEDED,
    ERR_UNIT_RESTRICTED_AGENCY_BLOCKED,
    ERR_VOLUNTEER_NOT_ELIGIBLE,
    HANDOFF_DRAFTED,
    ORDER_ACTIVE,
    ORDER_LAPSED,
    POOL_AGENCY,
    POOL_INTERNAL_FLOAT,
    POOL_VOLUNTEER,
    RESTRICTION_BUDGET_THRESHOLD_REACHED,
    RESTRICTION_OBSERVATION_ORDER_LAPSED,
    RISK_ELOPEMENT,
    RISK_FALL,
    RISK_SELF_HARM,
    STAFF_AVAILABLE,
    UNIT_OPEN,
    UNIT_RESTRICTED,
    WATCH_ON_BREAK,
    WATCH_ON_WATCH,
    WATCH_SCHEDULED,
)
from test_helpers.factories import assignment_payload, handoff_payload
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    assignment_handoffs,
    make_assignment,
    make_order,
    make_patient,
    make_reassessment,
    make_staff,
    make_unit,
    order_assignments,
    read_assignment,
    read_handoff,
    read_order,
    read_staff,
    read_unit,
    start_watch_at,
    unit_cost_entries,
    unit_head,
)
from test_helpers.test_users import COORDINATOR, make_sitter_headers

NON_EXISTENT_ORDER_ID = "00000000-0000-0000-0000-0000000000ff"
CERT_VALID = "2027-01-01T00:00:00Z"


class TestVolunteerEligibilityBar:
    """
    One and the same volunteer is barred from an ELOPEMENT order and welcome on a
    FALL-only one, so the gate is proved to key on the order's risk set.
    """

    def test_a_volunteer_is_refused_on_an_order_carrying_elopement_risk(
        self, api: ObservationApiClient
    ) -> None:
        """
        The volunteer clears certification, competency and suspension, so the only
        rule left to fire is the volunteer bar; the refusal must leave the order
        version, the ledger and the observer row exactly as they were.

        PRD 3.4: "And trained volunteers are deliberately kept away from the two
        highest-stakes criteria: an observer whose `source_pool` is `VOLUNTEER` may not be
        assigned to an order whose `risk_categories` include `SELF_HARM` or `ELOPEMENT`,
        and an attempt is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE`."
        PRD 2.8: "One consequence follows directly and is intentional: because a successful
        schedule increments the order's `version` by 1, replaying the identical request
        with the same `expected_order_version` fails the second time with
        `ERR_STALE_ORDER_VERSION`."

        Design: Corner/validations/volunteer_pool_is_barred_from_an_elopement_risk_order
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C25",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Twentyfive",
        )
        patient = make_patient(
            api,
            unit["id"],
            mrn="MRN-C2501",
            full_name="Volunteer Patient One",
            age_years=60,
        )
        volunteer = make_staff(
            api,
            unit["id"],
            full_name="Trained Volunteer",
            source_pool=POOL_VOLUNTEER,
            hourly_rate_cents=0,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL, RISK_ELOPEMENT],
            clinical_rationale="Wandering with unsteady gait",
        )

        validate_error(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    volunteer["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    order["version"],
                ),
                COORDINATOR,
            ),
            ERR_VOLUNTEER_NOT_ELIGIBLE,
            HTTP_UNPROCESSABLE,
        )

        assert_fields(
            read_order(api, order["id"]),
            label="order after the refused volunteer create",
            version=order["version"],
            status=ORDER_ACTIVE,
        )
        assert_row_count(
            order_assignments(api, order["id"]), 0, "assignments on the elopement order"
        )
        assert unit_head(api, unit["id"]) == 0, "a refused create must post nothing"
        assert_fields(
            read_staff(api, volunteer["id"]),
            label="volunteer after the refusal",
            status=STAFF_AVAILABLE,
            last_shift_end_at=None,
            version=volunteer["version"],
        )

    def test_the_same_volunteer_is_scheduled_on_a_fall_only_order_at_zero_cost(
        self, api: ObservationApiClient
    ) -> None:
        """
        The VOLUNTEER multiplier of 0.00 drives the provisional figure to exactly 0,
        and a real ledger row is still written for it — the entry count goes to 1
        while the unit's head stays at 0.

        PRD 3.4: "It bills the entire scheduled window at the observer's base rate scaled
        by their pool: the observer's `hourly_rate_cents` is multiplied by
        `scheduled_minutes` divided by 60, and that product is multiplied by the pool
        multiplier — 1.00 for `INTERNAL_FLOAT`, 1.45 for `AGENCY`, and 0.00 for
        `VOLUNTEER`, whose labor is donated and therefore free."
        PRD 3.4: "The new assignment lands with `watch_status` at `SCHEDULED` and
        `documentation_status` at `PENDING`, with `scheduled_minutes` derived as the whole
        minutes between `shift_start_at` and `shift_end_at`, and with `final_cost_cents`,
        `current_segment_started_at`, `break_started_at`, `completion_reason` and
        `voided_at` all null and `watch_segment_count` and `watched_minutes` both 0."
        PRD 3.4: "The row copies the `unit_id` from the unit occupied by the patient of the
        assignment's order, records the `assignment_id` it bills, carries the provisional
        figure as `amount_cents`, opens in `status` `POSTED` with `posted_at` stamped from
        the logical clock and `reversed_at` null, freezes the observer's `source_pool` as
        of this moment, sets `night_differential_applied` to `false`, and leaves both
        `segment_index` and `segment_minutes` null because a provisional row bills no
        particular segment."
        PRD 3.4: "The observer's `last_shift_end_at` is recomputed as well, but the
        observer's `status` is explicitly not changed by scheduling."

        Design: Corner/validations/volunteer_on_a_fall_only_order_is_scheduled_at_zero_cost
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C26",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Twentysix",
        )
        patient = make_patient(
            api,
            unit["id"],
            mrn="MRN-C2601",
            full_name="Volunteer Patient Two",
            age_years=60,
        )
        volunteer = make_staff(
            api,
            unit["id"],
            full_name="Trained Volunteer Two",
            source_pool=POOL_VOLUNTEER,
            hourly_rate_cents=0,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions only",
        )

        created = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    volunteer["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    order["version"],
                ),
                COORDINATOR,
            ),
            expected_status=HTTP_CREATED,
        )
        assert_fields(
            created,
            label="donated volunteer watch",
            watch_status=WATCH_SCHEDULED,
            documentation_status=DOC_PENDING,
            scheduled_minutes=480,
            provisional_cost_cents=0,
            final_cost_cents=None,
            current_segment_started_at=None,
            break_started_at=None,
            completion_reason=None,
            voided_at=None,
            watch_segment_count=0,
            watched_minutes=0,
        )

        rows = assignment_cost_entries(api, created["id"])
        assert_row_count(rows, 1, "ledger rows for the donated watch")
        assert_fields(
            rows[0],
            label="donated provisional row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            status=COST_POSTED,
            amount_cents=0,
            source_pool=POOL_VOLUNTEER,
            segment_index=None,
            segment_minutes=None,
            night_differential_applied=False,
            reversed_at=None,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="unit carrying only donated labor",
            observed_cost_to_date_cents=0,
            status=UNIT_OPEN,
        )
        assert_fields(
            read_staff(api, volunteer["id"]),
            label="volunteer after scheduling",
            last_shift_end_at="2026-08-01T16:00:00.000Z",
            status=STAFF_AVAILABLE,
        )


class TestBreakMinuteBoundaries:
    """Both break thresholds probed one minute short and then exactly on the mark."""

    def test_break_start_and_break_end_are_both_inclusive_whole_minute_gates(
        self, api: ObservationApiClient
    ) -> None:
        """
        Break relief at 119 elapsed minutes is refused and at exactly 120 succeeds,
        closing and billing precisely those 120 minutes; returning after 14 minutes of
        break is refused and after exactly 15 succeeds, writing no ledger row at all.

        PRD 3.5: "Advancing `ON_WATCH → ON_BREAK` requires that at least 120 whole minutes
        — two full hours — have elapsed on the currently open segment since
        `current_segment_started_at`; an earlier attempt is rejected with
        `ERR_BREAK_NOT_YET_ELIGIBLE`."
        PRD 3.5: "The open segment is closed at the current logical clock and one
        `CostEntry` of `entry_kind` `FINAL_SEGMENT` is posted for it, carrying
        `segment_index` set to the assignment's `watch_segment_count` plus 1 (so segment
        ordinals are 1-based and strictly increasing) and `segment_minutes` set to the
        whole minutes of the segment just closed."
        PRD 3.5: "`break_started_at` is stamped and `current_segment_started_at` is cleared
        to null."
        PRD 3.5: "Four derived figures are then recomputed: the assignment's
        `watch_segment_count`, which is the number of that assignment's `FINAL_SEGMENT`
        ledger rows still in `status` `POSTED`; the assignment's `watched_minutes`, which is
        the sum of `segment_minutes` across those same rows; the observer's
        `total_watch_minutes`; and the unit's `observed_cost_to_date_cents`."
        PRD 3.5: "For a segment, the whole minutes it lasted are divided by 60 and
        multiplied by the observer's `hourly_rate_cents`, then by the pool multiplier (1.00
        for `INTERNAL_FLOAT`, 1.45 for `AGENCY`, 0.00 for `VOLUNTEER`), then by the night
        differential of 1.15 when that segment qualifies as a night segment and by 1.00 when
        it does not."
        PRD 3.5: "Returning from relief advances `ON_BREAK → ON_WATCH` and requires that at
        least 15 whole minutes of break have elapsed since `break_started_at`; an earlier
        return is rejected with `ERR_BREAK_TOO_SHORT`."
        PRD 3.5: "It stamps a fresh `current_segment_started_at`, clears `break_started_at`
        to null, and advances the assignment's `version` by 1."
        PRD 3.5: "No ledger row whatsoever is written for a break — **break minutes are
        never billed**, which is exactly why the watch is modelled as a series of closed
        segments rather than as one continuous span."

        Design: Corner/validations/break_eligibility_and_minimum_break_are_both_whole_minute_boundaries
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C27",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Twentyseven",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C2701", full_name="Break Patient", age_years=60
        )
        sitter = make_staff(
            api,
            unit["id"],
            full_name="Break Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions, day watch",
        )
        assignment = make_assignment(
            api,
            order["id"],
            sitter["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
            order["version"],
        )
        start_watch_at(api, assignment["id"], sitter["id"], "2026-08-01T08:00:00Z")
        sitter_headers = make_sitter_headers(sitter["id"])

        advance_clock(api, "2026-08-01T09:59:00Z")
        validate_error(
            api.break_start(assignment["id"], sitter_headers),
            ERR_BREAK_NOT_YET_ELIGIBLE,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_assignment(api, assignment["id"]),
            label="watch at 119 elapsed minutes",
            watch_status=WATCH_ON_WATCH,
            break_started_at=None,
            current_segment_started_at="2026-08-01T08:00:00.000Z",
            watch_segment_count=0,
            watched_minutes=0,
        )
        assert_row_count(
            assignment_cost_entries(api, assignment["id"]),
            1,
            "ledger rows before any break",
        )

        advance_clock(api, "2026-08-01T10:00:00Z")
        on_break = validate_success(api.break_start(assignment["id"], sitter_headers))
        assert_fields(
            on_break,
            label="watch at exactly 120 elapsed minutes",
            watch_status=WATCH_ON_BREAK,
            break_started_at="2026-08-01T10:00:00.000Z",
            current_segment_started_at=None,
            watch_segment_count=1,
            watched_minutes=120,
        )
        segments = final_segment_rows(assignment_cost_entries(api, assignment["id"]))
        assert_row_count(segments, 1, "closed segments after the break started")
        assert_fields(
            segments[0],
            label="first closed segment",
            amount_cents=4000,
            segment_index=1,
            segment_minutes=120,
            night_differential_applied=False,
            status=COST_POSTED,
        )
        assert unit_head(api, unit["id"]) == 20000, "16000 provisional plus a 4000 segment"
        assert_fields(
            read_staff(api, sitter["id"]),
            label="sitter after the first closed segment",
            total_watch_minutes=120,
        )

        advance_clock(api, "2026-08-01T10:14:00Z")
        validate_error(
            api.break_end(assignment["id"], sitter_headers),
            ERR_BREAK_TOO_SHORT,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_assignment(api, assignment["id"]),
            label="watch after a 14-minute break",
            watch_status=WATCH_ON_BREAK,
            break_started_at="2026-08-01T10:00:00.000Z",
            current_segment_started_at=None,
        )

        advance_clock(api, "2026-08-01T10:15:00Z")
        back_on_watch = validate_success(api.break_end(assignment["id"], sitter_headers))
        assert_fields(
            back_on_watch,
            label="watch after exactly 15 minutes of break",
            watch_status=WATCH_ON_WATCH,
            current_segment_started_at="2026-08-01T10:15:00.000Z",
            break_started_at=None,
            watch_segment_count=1,
            watched_minutes=120,
        )
        assert_row_count(
            assignment_cost_entries(api, assignment["id"]),
            2,
            "ledger rows after the break ended",
        )
        assert unit_head(api, unit["id"]) == 20000, "break minutes are never billed"


class TestCrossUnitFloatAuthorization:
    """The identical payload shape is legal for a home sitter and illegal for a float."""

    def test_only_the_floated_sitter_needs_a_float_authorization_code(
        self, api: ObservationApiClient
    ) -> None:
        """
        Three creates on one order show the rule off (home-unit sitter, no code), on
        (floated sitter, no code) and satisfied (floated sitter with a code); because the
        refusal bumped nothing, the third create replays the second's order version, and
        both charges land on the patient's unit rather than the sitter's home unit.

        PRD 3.4: "When the observer's `home_unit_id` differs from the `unit_id` of the unit
        the order's patient occupies, the payload's `float_authorization_code` must be
        present and non-empty; omitting it, or supplying an empty string, is rejected with
        `ERR_FLOAT_AUTHORIZATION_MISSING`."
        PRD 3.4: "When the observer is based on the patient's own unit the code is not
        required and may be omitted."
        PRD 3.4: "The row copies the `unit_id` from the unit occupied by the patient of the
        assignment's order, records the `assignment_id` it bills, carries the provisional
        figure as `amount_cents`, opens in `status` `POSTED` with `posted_at` stamped from
        the logical clock and `reversed_at` null, freezes the observer's `source_pool` as
        of this moment, sets `night_differential_applied` to `false`, and leaves both
        `segment_index` and `segment_minutes` null because a provisional row bills no
        particular segment."
        PRD 2.8: "One consequence follows directly and is intentional: because a successful
        schedule increments the order's `version` by 1, replaying the identical request
        with the same `expected_order_version` fails the second time with
        `ERR_STALE_ORDER_VERSION`."

        Design: Corner/validations/float_authorization_is_demanded_only_for_a_cross_unit_sitter
        """
        patient_unit = make_unit(
            api,
            unit_code="UNIT-C28",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Twentyeight",
        )
        home_unit = make_unit(
            api,
            unit_code="UNIT-C29",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Twentynine",
        )
        patient = make_patient(
            api,
            patient_unit["id"],
            mrn="MRN-C2801",
            full_name="Float Patient",
            age_years=60,
        )
        home_sitter = make_staff(
            api,
            patient_unit["id"],
            full_name="Home Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        floated_sitter = make_staff(
            api,
            home_unit["id"],
            full_name="Floated Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions, cross-unit coverage",
        )

        home_watch = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    home_sitter["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    order["version"],
                ),
                COORDINATOR,
            ),
            expected_status=HTTP_CREATED,
        )
        assert home_watch["provisional_cost_cents"] == 16000

        version_after_first = read_order(api, order["id"])["version"]
        validate_error(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    floated_sitter["id"],
                    "2026-08-01T16:00:00Z",
                    "2026-08-02T00:00:00Z",
                    version_after_first,
                ),
                COORDINATOR,
            ),
            ERR_FLOAT_AUTHORIZATION_MISSING,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="order after the uncoded float attempt",
            version=version_after_first,
        )

        floated_watch = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    floated_sitter["id"],
                    "2026-08-01T16:00:00Z",
                    "2026-08-02T00:00:00Z",
                    version_after_first,
                    float_authorization_code="FLOAT-7788",
                ),
                COORDINATOR,
            ),
            expected_status=HTTP_CREATED,
        )
        assert floated_watch["provisional_cost_cents"] == 16000

        assert_fields(
            read_unit(api, patient_unit["id"]),
            label="patient's unit",
            observed_cost_to_date_cents=32000,
            status=UNIT_OPEN,
        )
        assert_fields(
            read_unit(api, home_unit["id"]),
            label="floated sitter's home unit",
            observed_cost_to_date_cents=0,
        )
        assert_row_count(
            order_assignments(api, order["id"]), 2, "watches accepted on the order"
        )


class TestHandoffEpisodeLinkage:
    """The incoming watch must belong to the very order the outgoing watch covers."""

    def test_a_cross_order_successor_is_refused_and_the_same_order_pair_is_accepted(
        self, api: ObservationApiClient
    ) -> None:
        """
        An incoming watch drawn from a second patient's order is refused even though it
        is a perfectly good SCHEDULED watch, and the refusal leaves the outgoing watch's
        documentation dimension at PENDING with no handoff record at all; the same-order
        successor is then accepted and moves only the documentation dimension.

        PRD 3.6: "The outgoing assignment's `watch_status` must be `ON_WATCH` or `ON_BREAK`
        — one cannot hand off a watch that has not started or has already ended."
        PRD 3.6: "And the two must be watches on the same episode: the incoming assignment's
        `order_id` must equal the outgoing assignment's `order_id`, and the two assignment
        identifiers must differ, with either failure rejected as
        `ERR_HANDOFF_ORDER_MISMATCH`."
        PRD 3.6: "A successful draft creates a handoff record whose `documentation_state` is
        `DRAFTED`, with `countersigned_by_staff_id` and `countersigned_at` both null, and
        moves the outgoing assignment `PENDING → HANDOFF_DRAFTED` while leaving its
        `watch_status` completely untouched; the assignment's `version` advances by 1."

        Design: Corner/validations/handoff_incoming_watch_must_sit_on_the_outgoing_watchs_order
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C30",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirty",
        )
        patient_a = make_patient(
            api, unit["id"], mrn="MRN-C3001", full_name="Handoff Patient A", age_years=60
        )
        patient_b = make_patient(
            api, unit["id"], mrn="MRN-C3002", full_name="Handoff Patient B", age_years=60
        )
        sitters = {}
        for key, name in (
            ("out", "Outgoing Sitter"),
            ("in", "Incoming Sitter"),
            ("other", "Other Order Sitter"),
        ):
            sitters[key] = make_staff(
                api,
                unit["id"],
                full_name=name,
                source_pool=POOL_INTERNAL_FLOAT,
                hourly_rate_cents=2000,
                competency_level=COMPETENCY_ADVANCED,
                deescalation_cert_expires_on=CERT_VALID,
            )
        order_a = make_order(
            api,
            patient_a["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Handoff order A",
        )
        order_b = make_order(
            api,
            patient_b["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Handoff order B",
        )
        outgoing = make_assignment(
            api,
            order_a["id"],
            sitters["out"]["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        incoming = make_assignment(
            api,
            order_a["id"],
            sitters["in"]["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-02T00:00:00Z",
        )
        unrelated = make_assignment(
            api,
            order_b["id"],
            sitters["other"]["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        start_watch_at(api, outgoing["id"], sitters["out"]["id"], "2026-08-01T08:00:00Z")
        outgoing_headers = make_sitter_headers(sitters["out"]["id"])

        validate_error(
            api.create_handoff(
                handoff_payload(
                    outgoing["id"], unrelated["id"], behavior_summary="Calm, redirectable"
                ),
                outgoing_headers,
            ),
            ERR_HANDOFF_ORDER_MISMATCH,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_assignment(api, outgoing["id"]),
            label="outgoing watch after the cross-order draft",
            documentation_status=DOC_PENDING,
            watch_status=WATCH_ON_WATCH,
        )
        assert_row_count(
            assignment_handoffs(api, outgoing["id"]), 0, "handoffs after the refusal"
        )

        drafted = validate_success(
            api.create_handoff(
                handoff_payload(
                    outgoing["id"], incoming["id"], behavior_summary="Calm, redirectable"
                ),
                outgoing_headers,
            ),
            expected_status=HTTP_CREATED,
        )
        assert_fields(
            drafted,
            label="accepted handoff record",
            documentation_state=HANDOFF_DRAFTED,
            countersigned_by_staff_id=None,
            countersigned_at=None,
            outgoing_assignment_id=outgoing["id"],
            incoming_assignment_id=incoming["id"],
        )
        assert_fields(
            read_assignment(api, outgoing["id"]),
            label="outgoing watch after the accepted draft",
            documentation_status=DOC_HANDOFF_DRAFTED,
            watch_status=WATCH_ON_WATCH,
        )
        assert_fields(
            read_handoff(api, drafted["id"]),
            label="handoff read back",
            outgoing_assignment_id=outgoing["id"],
            incoming_assignment_id=incoming["id"],
        )


class TestAggregateBudgetCeiling:
    """Each candidate is affordable alone; only the running head makes one illegal."""

    def test_the_second_watch_breaches_the_budget_and_a_smaller_third_lands_on_it(
        self, api: ObservationApiClient
    ) -> None:
        """
        Against a 30000-cent budget the first 16000 watch is accepted, an identically
        priced second is refused as a fiscal breach that writes nothing at all, and a
        seven-hour 14000 watch is then accepted because 30000 exactly equals the budget
        — the same request flipping the unit to RESTRICTED.

        PRD 3.4: "First, the candidate watch is costed provisionally, and the unit's current
        `observed_cost_to_date_cents` plus that `provisional_cost_cents` must not exceed the
        unit's `observation_cost_budget_cents`."
        PRD 3.4: "The comparison is generous at the boundary — a total that lands exactly on
        the budget is accepted, and only a total strictly greater than the budget is
        rejected, with `ERR_UNIT_BUDGET_EXCEEDED` and HTTP 402."
        PRD 3.4: "The unit's `observed_cost_to_date_cents` is then recomputed over the posted
        set, and if the recomputed head has reached or passed `observation_cost_budget_cents`
        the unit transitions `OPEN → RESTRICTED` with `restriction_reason` set to
        `BUDGET_THRESHOLD_REACHED` — the threshold is inclusive, so a head exactly equal to
        the budget restricts the unit."
        PRD 2.8: "One consequence follows directly and is intentional: because a successful
        schedule increments the order's `version` by 1, replaying the identical request
        with the same `expected_order_version` fails the second time with
        `ERR_STALE_ORDER_VERSION`."

        Design: Corner/validations/individually_affordable_watches_collectively_exhaust_the_unit_budget
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C31",
            budget_cents=30000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtyone",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C3101", full_name="Budget Patient", age_years=60
        )
        sitters = [
            make_staff(
                api,
                unit["id"],
                full_name=name,
                source_pool=POOL_INTERNAL_FLOAT,
                hourly_rate_cents=2000,
                competency_level=COMPETENCY_ADVANCED,
                deescalation_cert_expires_on=CERT_VALID,
            )
            for name in ("Budget Sitter One", "Budget Sitter Two", "Budget Sitter Three")
        ]
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Budget-constrained fall watch",
        )

        first = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    sitters[0]["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    order["version"],
                ),
                COORDINATOR,
            ),
            expected_status=HTTP_CREATED,
        )
        assert first["provisional_cost_cents"] == 16000
        assert_fields(
            read_unit(api, unit["id"]),
            label="unit after the affordable first watch",
            observed_cost_to_date_cents=16000,
            status=UNIT_OPEN,
            restriction_reason=None,
        )

        version_after_first = read_order(api, order["id"])["version"]
        validate_error(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    sitters[1]["id"],
                    "2026-08-01T16:00:00Z",
                    "2026-08-02T00:00:00Z",
                    version_after_first,
                ),
                COORDINATOR,
            ),
            ERR_UNIT_BUDGET_EXCEEDED,
            HTTP_PAYMENT_REQUIRED,
        )
        assert unit_head(api, unit["id"]) == 16000, "the refused watch posted nothing"
        assert_row_count(
            unit_cost_entries(api, unit["id"]), 1, "ledger rows after the fiscal refusal"
        )
        assert_fields(
            read_order(api, order["id"]),
            label="order after the fiscal refusal",
            version=version_after_first,
        )

        third = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    sitters[2]["id"],
                    "2026-08-01T16:00:00Z",
                    "2026-08-01T23:00:00Z",
                    version_after_first,
                ),
                COORDINATOR,
            ),
            expected_status=HTTP_CREATED,
        )
        assert_fields(
            third,
            label="seven-hour watch landing exactly on the budget",
            scheduled_minutes=420,
            provisional_cost_cents=14000,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="unit with its head exactly on the budget",
            observed_cost_to_date_cents=30000,
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_BUDGET_THRESHOLD_REACHED,
        )
        assert_fields(
            read_assignment(api, first["id"]),
            label="first watch, untouched by the later creates",
            watch_status=WATCH_SCHEDULED,
            documentation_status=DOC_PENDING,
            provisional_cost_cents=16000,
        )


class TestRestrictedUnitAgencyBlock:
    """A non-fiscal restriction blocks agency labor while internal float still passes."""

    def test_a_lapse_restricted_unit_refuses_agency_labor_and_accepts_internal_float(
        self, api: ObservationApiClient
    ) -> None:
        """
        The restriction is manufactured by a lapsed order rather than by spending, so
        the ledger head is 0 against a 250000 budget and the agency block is the only
        possible reason for the 402; the very next create, identical except for the
        observer's pool, is accepted and the post does not clear the restriction.

        PRD 3.3: "An order in `REASSESSMENT_DUE` transitions `REASSESSMENT_DUE → LAPSED` when
        the new clock value is greater than or equal to its `next_reassessment_due_at`
        advanced by the 6-hour reassessment grace period — inclusive, so the instant exactly
        6 hours past due already lapses."
        PRD 3.3: "The clock response reports the instant now in force as `current_utc`,
        together with `orders_marked_reassessment_due` and `orders_lapsed` as counts of what
        the sweep did."
        PRD 3.3: "Alongside those hops, the unit occupied by the lapsed order's patient is
        driven to `RESTRICTED` with `restriction_reason` set to `OBSERVATION_ORDER_LAPSED`; a
        unit already `RESTRICTED` is left as it is, and this step is then a no-op."
        PRD 3.4: "Second, a unit whose posture is `RESTRICTED` may not take on new agency
        labor at all: an observer whose `source_pool` is `AGENCY` is refused with
        `ERR_UNIT_RESTRICTED_AGENCY_BLOCKED`, also HTTP 402, while `INTERNAL_FLOAT` and
        `VOLUNTEER` observers remain schedulable on a restricted unit."
        PRD 3.5: "The only operation that lifts a restriction is the cost close described in
        §3.9."

        Design: Corner/validations/restricted_unit_refuses_agency_labor_but_still_accepts_internal_float
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C32",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtytwo",
        )
        lapsing_patient = make_patient(
            api, unit["id"], mrn="MRN-C3201", full_name="Lapsing Patient", age_years=60
        )
        surviving_patient = make_patient(
            api, unit["id"], mrn="MRN-C3202", full_name="Surviving Patient", age_years=60
        )
        agency_sitter = make_staff(
            api,
            unit["id"],
            full_name="Restricted Agency Sitter",
            source_pool=POOL_AGENCY,
            hourly_rate_cents=2500,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        float_sitter = make_staff(
            api,
            unit["id"],
            full_name="Restricted Float Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        lapsing_order = make_order(
            api,
            lapsing_patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Order that will lapse",
        )
        surviving_order = make_order(
            api,
            surviving_patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Order that will be reassessed on time",
        )

        first_sweep = advance_clock(api, "2026-08-02T00:00:00Z")
        assert_fields(
            first_sweep,
            label="sweep at the shared due instant",
            orders_marked_reassessment_due=2,
            orders_lapsed=0,
        )
        make_reassessment(api, surviving_order["id"], [RISK_FALL])

        second_sweep = advance_clock(api, "2026-08-02T06:00:01Z")
        assert_fields(
            second_sweep,
            label="sweep one second past the grace period",
            orders_marked_reassessment_due=0,
            orders_lapsed=1,
        )
        assert_fields(
            read_order(api, lapsing_order["id"]),
            label="neglected order",
            status=ORDER_LAPSED,
        )
        assert_fields(
            read_order(api, surviving_order["id"]),
            label="reassessed order",
            status=ORDER_ACTIVE,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="unit restricted by the lapse",
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_OBSERVATION_ORDER_LAPSED,
            observed_cost_to_date_cents=0,
        )

        surviving_version = read_order(api, surviving_order["id"])["version"]
        validate_error(
            api.create_assignment(
                assignment_payload(
                    surviving_order["id"],
                    agency_sitter["id"],
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T16:00:00Z",
                    surviving_version,
                ),
                COORDINATOR,
            ),
            ERR_UNIT_RESTRICTED_AGENCY_BLOCKED,
            HTTP_PAYMENT_REQUIRED,
        )

        accepted = validate_success(
            api.create_assignment(
                assignment_payload(
                    surviving_order["id"],
                    float_sitter["id"],
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T16:00:00Z",
                    surviving_version,
                ),
                COORDINATOR,
            ),
            expected_status=HTTP_CREATED,
        )
        assert accepted["provisional_cost_cents"] == 16000
        assert_fields(
            read_unit(api, unit["id"]),
            label="restricted unit after taking internal float",
            observed_cost_to_date_cents=16000,
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_OBSERVATION_ORDER_LAPSED,
        )
        rows = order_assignments(api, surviving_order["id"])
        assert_row_count(rows, 1, "watches accepted on the surviving order")
        exactly_one(rows, id=accepted["id"])


class TestUnresolvableOrderShortCircuit:
    """A body FK that resolves to nothing outranks both concurrency and competency."""

    def test_an_unknown_order_id_reports_the_404_and_never_the_version_or_competency_error(
        self, api: ObservationApiClient
    ) -> None:
        """
        One request violates three rules at once — an `order_id` naming no row, a version
        token belonging to a different order, and a NOT_TRAINED observer — and the answer
        must be the body-FK 404, because the competency floor is defined against the
        order's risk categories and cannot be evaluated until that reference resolves.

        PRD 2.6: "They form a single ordered ladder, and the server evaluates them in
        ascending order and returns the **first** failure it reaches, so a request that
        violates several rules always surfaces the earliest one."
        PRD 2.6: "Existence of body foreign-key references, in the endpoint's declared field
        order — the corresponding 404."
        PRD 2.6: "Optimistic concurrency on the observation order — `ERR_STALE_ORDER_VERSION`."
        PRD 2.6: "Competency floor — `ERR_COMPETENCY_INSUFFICIENT`."
        PRD 2.5: "Creating a patient resolves `unit_id`; registering staff resolves
        `home_unit_id`; writing an order resolves `patient_id`; scheduling a watch resolves
        `order_id` and then `staff_id`; opening a console resolves `observer_staff_id`;
        admitting a feed resolves `station_id` and then `order_id`; drafting a handoff
        resolves `outgoing_assignment_id` and then `incoming_assignment_id`; reporting a
        safety event resolves `order_id` and then, when supplied, `assignment_id`."
        PRD 2.5: "Each unresolvable reference raises the 404 for its own entity type."
        PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/validations/unresolvable_order_fk_short_circuits_the_competency_check
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C33",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtythree",
        )
        untrained = make_staff(
            api,
            unit["id"],
            full_name="Untrained Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_NOT_TRAINED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        decoy_patient = make_patient(
            api, unit["id"], mrn="MRN-C3301", full_name="Decoy Patient", age_years=60
        )
        decoy_order = make_order(
            api,
            decoy_patient["id"],
            risk_categories=[RISK_SELF_HARM],
            clinical_rationale="Decoy order supplying a live version token",
        )

        response = api.create_assignment(
            assignment_payload(
                NON_EXISTENT_ORDER_ID,
                untrained["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T16:00:00Z",
                decoy_order["version"],
            ),
            COORDINATOR,
        )
        validate_error(response, ERR_ORDER_NOT_FOUND, HTTP_NOT_FOUND)
        body = response.json()
        assert body["response_type"] == "error"
        assert_envelope_meta(body)

        assert_fields(
            read_unit(api, unit["id"]),
            label="unit after the unresolvable create",
            observed_cost_to_date_cents=0,
        )
        assert_row_count(
            unit_cost_entries(api, unit["id"]), 0, "ledger rows after the 404"
        )
        assert_fields(
            read_staff(api, untrained["id"]),
            label="untrained observer, untouched",
            status=STAFF_AVAILABLE,
            last_shift_end_at=None,
            version=untrained["version"],
        )
