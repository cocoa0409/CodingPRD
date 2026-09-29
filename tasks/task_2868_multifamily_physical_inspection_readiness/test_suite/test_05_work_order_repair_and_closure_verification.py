"""The repair loop: completing a work order, then verifying its closure.

Repair and verification are independent dimensions, and the verifier must never
be the same principal who claimed the repair.
"""

from test_helpers import (
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_property_state,
    assert_sweep_counters,
    assert_two_decimals,
    assert_work_order_dimensions,
    constants as K,
    factories as F,
    fixtures as X,
)
from test_helpers.test_users import (
    MAINTENANCE_TECHNICIAN_ID,
    QUALITY_ASSURANCE_REVIEWER_ALT_ID,
    QUALITY_ASSURANCE_REVIEWER_ID,
    make_maintenance_technician_headers,
    make_quality_assurance_reviewer_headers,
)

TECHNICIAN = make_maintenance_technician_headers()
REVIEWER = make_quality_assurance_reviewer_headers()
ALT_REVIEWER = make_quality_assurance_reviewer_headers(
    QUALITY_ASSURANCE_REVIEWER_ALT_ID
)
CEDAR_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 1,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
MAPLE_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
FIRST_COMPLETED_AT = "2026-08-04T10:00:00.000Z"
FAILED_VERIFIED_AT = "2026-08-05T11:00:00.000Z"
SECOND_COMPLETED_AT = "2026-08-06T12:00:00.000Z"
PASSED_VERIFIED_AT = "2026-08-07T13:00:00.000Z"
LT_OBSERVED_AT = "2026-08-03T09:00:00.000Z"
SEV_OBSERVED_AT = "2026-08-03T10:00:00.000Z"
SEV_ROUTINE_DUE_AT = "2026-09-02T10:00:00.000Z"
CASCADE_DRAWN_AT = "2026-08-03T12:00:00.000Z"
LT_COMPLETED_AT = "2026-08-03T15:00:00.000Z"
LT_VERIFIED_AT = "2026-08-03T18:00:00.000Z"
SECOND_OBSERVED_AT = "2026-08-03T09:30:00.000Z"
FIRST_CLOSE_AT = "2026-08-06T09:00:00.000Z"
SECOND_CLOSE_AT = "2026-08-06T10:00:00.000Z"
DIRECT_CORRECTED_AT = "2026-08-03T12:00:00.000Z"
DIRECT_VERIFIED_AT = "2026-08-03T15:00:00.000Z"
LT_DUE_AT = "2026-08-04T09:00:00.000Z"


def _rejected_then_repaired(api):
    """A work order completed, FAILED by the owner, and completed again."""
    bundle = X.sweep_lifecycle(
        api,
        "SEV_WINDOW",
        K.MAPLE_COURT,
        MAPLE_UNIT,
        observed_at=LT_OBSERVED_AT,
    )
    X.completed_work_order(
        api,
        bundle["work_order_id"],
        TECHNICIAN,
        completed_at=FIRST_COMPLETED_AT,
        resolution_note="Sash replaced",
    )
    bundle["rejected"] = assert_ok(
        api.verify_work_order_closure(
            bundle["work_order_id"],
            F.verify_closure_payload("FAILED", verified_at=FAILED_VERIFIED_AT),
            bundle["owner_headers"],
        )
    )
    return bundle


def _cascade_c_setup(api):
    """Two findings, a drawn sample, and the repaired life-threatening order."""
    bundle = X.sweep_lifecycle(
        api,
        "LT_GAS",
        K.MAPLE_COURT,
        MAPLE_UNIT,
        observed_at=LT_OBSERVED_AT,
    )
    bundle["work_order_lt_id"] = bundle["work_order_id"]
    bundle["deficiency_lt_id"] = bundle["deficiency_id"]

    severe = X.record_finding(
        api,
        bundle["property_id"],
        bundle["sweep_id"],
        X.read_sweep(api, bundle["sweep_id"])["version"],
        bundle["definition_ids"]["SEV_WINDOW"],
        sorted(bundle["unit_ids"].items())[0][1],
        "UNIT",
        observed_at=SEV_OBSERVED_AT,
    )
    bundle["work_order_sev_id"] = severe["work_order_id"]
    bundle["deficiency_sev_id"] = severe["deficiency_id"]

    inspection = assert_created(
        api.create_inspection(
            F.inspection_payload(bundle["property_id"], bundle["standard_id"]),
            X.INSPECTOR,
        )
    )
    assert_ok(
        api.draw_sample(
            inspection["id"],
            F.draw_sample_payload(drawn_at=CASCADE_DRAWN_AT),
            X.INSPECTOR,
        )
    )
    X.completed_work_order(
        api,
        bundle["work_order_lt_id"],
        TECHNICIAN,
        completed_at=LT_COMPLETED_AT,
        resolution_note="Flexible connector replaced and leak-tested",
    )
    return bundle


class TestRepairRecording:
    """Only the maintenance technician may claim a repair."""

    def test_the_technician_completes_the_work_order_it_owns(self, api):
        """The completion stamps the acting principal onto the row.

        PRD: "The transition sets `completed_at`, records the acting `X-User-ID`
        as `completed_by_user_id`, stores the `resolution_note`, and moves
        `repair_status` `OPEN -> REPAIRED` while leaving `verification_status`
        untouched."

        Design: Corner/rbac/maintenance_technician_can_complete_the_work_order_it_exclusively_owns
        """
        bundle = X.sweep_lifecycle(api, "SEV_WINDOW", K.CEDAR_WALK, CEDAR_UNIT)

        response = api.complete_work_order(
            bundle["work_order_id"],
            F.work_order_complete_payload(
                completed_at=K.WORK_ORDER_COMPLETED_AT,
                resolution_note="Sash mechanism replaced",
            ),
            TECHNICIAN,
        )

        work_order = assert_ok(response)
        assert_work_order_dimensions(work_order, "REPAIRED", "UNVERIFIED")
        assert_instant(
            work_order["completed_at"], K.WORK_ORDER_COMPLETED_AT, "completed_at"
        )
        assert_fields(
            work_order, completed_by_user_id=MAINTENANCE_TECHNICIAN_ID
        )
        assert_two_decimals(
            X.read_sweep(api, bundle["sweep_id"])["closure_verified_rate"],
            0.00,
            "closure_verified_rate",
        )
        assert_fields(
            X.read_deficiency(api, bundle["deficiency_id"]), status="CORRECTED"
        )

    def test_the_property_owner_may_not_complete_a_work_order(self, api):
        """Completion is the technician's endpoint alone.

        PRD: "If the headers are well-formed but the declared role is not listed
        among the roles authorised for the target endpoint, the request is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/completing_a_work_order_as_property_owner_returns_unauthorized
        """
        bundle = X.sweep_lifecycle(api, "SEV_WINDOW", K.CEDAR_WALK, CEDAR_UNIT)

        response = api.complete_work_order(
            bundle["work_order_id"],
            F.work_order_complete_payload(
                completed_at=K.WORK_ORDER_COMPLETED_AT,
                resolution_note="Owner tried to sign it off",
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.UNAUTHORIZED)
        work_order = X.read_work_order(api, bundle["work_order_id"])
        assert_fields(work_order, repair_status="OPEN")
        assert_null(work_order, "completed_at", "completed_by_user_id")


class TestClosureVerificationGates:
    """Verification demands a repaired row and an independent verifier."""

    def test_verifying_an_unrepaired_work_order_is_rejected(self, api):
        """A work order still OPEN cannot be verified.

        PRD: "The work order's `repair_status` must be `REPAIRED` and its
        `verification_status` must be `UNVERIFIED` or `REJECTED`; and the acting
        `X-User-ID` must differ from the stored `completed_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD: "anything else is rejected with `ERR_WORK_ORDER_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/errors/verifying_closure_of_an_unrepaired_work_order_is_rejected_as_invalid_state
        """
        bundle = X.sweep_lifecycle(api, "SEV_WINDOW", K.CEDAR_WALK, CEDAR_UNIT)

        response = api.verify_work_order_closure(
            bundle["work_order_id"],
            F.verify_closure_payload(
                "PASSED", verified_at=K.WORK_ORDER_VERIFIED_AT
            ),
            REVIEWER,
        )

        assert_error(response, ApiErrorId.WORK_ORDER_INVALID_STATE)
        work_order = X.read_work_order(api, bundle["work_order_id"])
        assert_work_order_dimensions(work_order, "OPEN", "UNVERIFIED")
        assert_null(work_order, "verified_at")
        sweep = X.read_sweep(api, bundle["sweep_id"])
        assert_two_decimals(
            sweep["closure_verified_rate"], 0.00, "closure_verified_rate"
        )
        assert_integer(
            sweep["generated_work_order_count"],
            1,
            "generated_work_order_count",
        )

    def test_verifying_under_the_completer_user_id_is_rejected(self, api):
        """The principal who claimed the repair cannot sign it off.

        PRD: "the acting `X-User-ID` must differ from the stored
        `completed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/verifying_closure_under_the_completer_user_id_is_rejected_by_segregation_of_duties
        """
        bundle = X.sweep_lifecycle(api, "SEV_WINDOW", K.CEDAR_WALK, CEDAR_UNIT)
        completed = X.completed_work_order(
            api,
            bundle["work_order_id"],
            make_maintenance_technician_headers(QUALITY_ASSURANCE_REVIEWER_ID),
            completed_at=K.WORK_ORDER_COMPLETED_AT,
        )
        assert_fields(
            completed,
            completed_by_user_id=QUALITY_ASSURANCE_REVIEWER_ID,
            repair_status="REPAIRED",
        )

        response = api.verify_work_order_closure(
            bundle["work_order_id"],
            F.verify_closure_payload(
                "PASSED", verified_at=K.WORK_ORDER_VERIFIED_AT
            ),
            REVIEWER,
        )

        assert_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)
        blocked = X.read_work_order(api, bundle["work_order_id"])
        assert_fields(blocked, verification_status="UNVERIFIED")
        assert_null(blocked, "verified_at")
        assert_two_decimals(
            X.read_sweep(api, bundle["sweep_id"])["closure_verified_rate"],
            0.00,
            "closure_verified_rate",
        )

        retried = assert_ok(
            api.verify_work_order_closure(
                bundle["work_order_id"],
                F.verify_closure_payload(
                    "PASSED", verified_at=K.WORK_ORDER_VERIFIED_AT
                ),
                ALT_REVIEWER,
            )
        )

        assert_fields(
            retried,
            verification_status="VERIFIED",
            verified_by_user_id=QUALITY_ASSURANCE_REVIEWER_ALT_ID,
        )
        assert_two_decimals(
            X.read_sweep(api, bundle["sweep_id"])["closure_verified_rate"],
            100.00,
            "closure_verified_rate",
        )


class TestTheRepairLoop:
    """A rejected closure returns the row to an open, completable position."""

    def test_a_failed_verification_reopens_the_repair_dimension(self, api):
        """FAILED rejects the verification and unwinds the repair claim.

        PRD: "The repair dimension is reopened: `repair_status` returns
        `REPAIRED -> OPEN` and both `completed_at` and `completed_by_user_id` are
        cleared to null, which frees the work order to be completed again"

        Design: Difficulty/non_linear_state_machine/work_order_rejected_verification_reopens_repair_dimension_then_passes
        """
        bundle = X.sweep_lifecycle(
            api, "SEV_WINDOW", K.MAPLE_COURT, MAPLE_UNIT, observed_at=LT_OBSERVED_AT
        )
        X.completed_work_order(
            api,
            bundle["work_order_id"],
            TECHNICIAN,
            completed_at=FIRST_COMPLETED_AT,
            resolution_note="Sash replaced",
        )

        response = api.verify_work_order_closure(
            bundle["work_order_id"],
            F.verify_closure_payload("FAILED", verified_at=FAILED_VERIFIED_AT),
            bundle["owner_headers"],
        )

        rejected = assert_ok(response)
        assert_work_order_dimensions(rejected, "OPEN", "REJECTED")
        assert_integer(rejected["rejection_count"], 1, "rejection_count")
        assert_null(rejected, "completed_at", "completed_by_user_id")
        assert_instant(
            rejected["verified_at"], FAILED_VERIFIED_AT, "verified_at"
        )
        assert_fields(rejected, verified_by_user_id=bundle["property_id"])
        deficiency = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(deficiency, status="OPEN")
        assert_null(deficiency, "corrected_at")
        sweep = X.read_sweep(api, bundle["sweep_id"])
        assert_sweep_counters(sweep, 1, 0, 0, 0, 0.00)

    def test_the_second_completion_then_passes_verification(self, api):
        """The row visits REPAIRED twice and settles at rejection_count 1.

        PRD: "This is the repair loop: a rejected closure returns the work order
        to an open, unverified-eligible position, and the complete-then-verify
        pair may repeat without limit."

        Design: Difficulty/non_linear_state_machine/work_order_rejected_verification_reopens_repair_dimension_then_passes
        """
        bundle = _rejected_then_repaired(api)
        X.completed_work_order(
            api,
            bundle["work_order_id"],
            TECHNICIAN,
            completed_at=SECOND_COMPLETED_AT,
            resolution_note="Sash re-shimmed and balance replaced",
        )

        response = api.verify_work_order_closure(
            bundle["work_order_id"],
            F.verify_closure_payload("PASSED", verified_at=PASSED_VERIFIED_AT),
            bundle["owner_headers"],
        )

        work_order = assert_ok(response)
        assert_work_order_dimensions(work_order, "REPAIRED", "VERIFIED")
        assert_integer(work_order["rejection_count"], 1, "rejection_count")
        assert_instant(
            work_order["completed_at"], SECOND_COMPLETED_AT, "completed_at"
        )
        assert_instant(
            work_order["verified_at"], PASSED_VERIFIED_AT, "verified_at"
        )
        assert_fields(
            work_order,
            completed_by_user_id=MAINTENANCE_TECHNICIAN_ID,
            verified_by_user_id=bundle["property_id"],
        )
        deficiency = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(deficiency, status="VERIFIED")
        assert_instant(
            deficiency["corrected_at"], SECOND_COMPLETED_AT, "corrected_at"
        )
        assert_instant(
            deficiency["verified_at"], PASSED_VERIFIED_AT, "verified_at"
        )
        sweep = X.read_sweep(api, bundle["sweep_id"])
        assert_sweep_counters(sweep, 1, 1, 0, 0, 100.00)
        assert_integer(
            sweep["open_work_order_count"], 0, "open_work_order_count"
        )


class TestVerifiedClosureCascade:
    """One PASSED verification walks all four links of §3.3."""

    def test_a_verified_closure_clears_the_life_threatening_counters(self, api):
        """Links one to three: the order, its deficiency, then the property.

        PRD: "Third, because that deficiency has left the `OPEN`-or-`OVERDUE`
        population, the property recomputes `open_life_threatening_count`,
        `overdue_life_threatening_count` and `open_severe_count` and re-derives
        `readiness_posture`."

        Design: Difficulty/transitive_cascade/cascade_c_verified_closure_demotes_unrelated_urgent_work_order
        """
        bundle = _cascade_c_setup(api)

        response = api.verify_work_order_closure(
            bundle["work_order_lt_id"],
            F.verify_closure_payload("PASSED", verified_at=LT_VERIFIED_AT),
            REVIEWER,
        )

        work_order = assert_ok(response)
        assert_fields(
            work_order,
            verification_status="VERIFIED",
            verified_by_user_id=QUALITY_ASSURANCE_REVIEWER_ID,
        )
        deficiency = X.read_deficiency(api, bundle["deficiency_lt_id"])
        assert_fields(deficiency, status="VERIFIED")
        assert_instant(
            deficiency["corrected_at"], LT_COMPLETED_AT, "corrected_at"
        )
        assert_instant(
            deficiency["verified_at"], LT_VERIFIED_AT, "verified_at"
        )
        assert_property_state(
            X.read_property(api, bundle["property_id"]), "READY", 0, 0, 1
        )

    def test_a_verified_closure_demotes_an_unrelated_urgent_work_order(self, api):
        """Link four reaches a work order this request never named.

        PRD: "Fourth, the posture value produced by the third link is inspected:
        when it is neither `RESTRICTED` nor `FROZEN`, every work order on that
        property whose `repair_status` is `OPEN` and whose `priority_tier` is
        `URGENT` is demoted to `ROUTINE` and has its `due_at` pushed 24 hours
        later, and every sweep owning such a work order recomputes
        `urgent_work_order_count`."

        The unrelated SEVERE order is already back on `ROUTINE` before the
        verification runs, because the completion bubbled the life-threatening
        deficiency `OPEN -> CORRECTED` and the posture "is re-derived from the
        property's live deficiency population every time a deficiency is created,
        changes status, is voided, or is swept up by a clock advance" (PRD 2.8),
        which fired the demotion then. What this test pins is that link four
        judges "on the posture as it stands after the third link, not on whether
        this request is the one that changed it": the verification re-runs the
        demotion sweep, finds nothing left to demote, and leaves the unrelated
        order on `ROUTINE` at its original deadline - proving the escalate/demote
        pair of PRD 2.9 is exactly symmetric rather than drifting `due_at` by a
        further 24 hours on the second pass.

        Design: Difficulty/transitive_cascade/cascade_c_verified_closure_demotes_unrelated_urgent_work_order
        """
        bundle = _cascade_c_setup(api)
        demoted = X.read_work_order(api, bundle["work_order_sev_id"])
        assert_fields(demoted, priority_tier="ROUTINE", repair_status="OPEN")
        assert_instant(demoted["due_at"], SEV_ROUTINE_DUE_AT, "due_at")

        response = api.verify_work_order_closure(
            bundle["work_order_lt_id"],
            F.verify_closure_payload("PASSED", verified_at=LT_VERIFIED_AT),
            REVIEWER,
        )

        assert_ok(response)
        untouched = X.read_work_order(api, bundle["work_order_sev_id"])
        assert_fields(untouched, repair_status="OPEN", priority_tier="ROUTINE")
        assert_instant(untouched["due_at"], SEV_ROUTINE_DUE_AT, "due_at")
        sweep = X.read_sweep(api, bundle["sweep_id"])
        # The life-threatening order is still counted as urgent: the completion
        # narrative recomputes only `open_work_order_count` and
        # `closure_verified_rate`, so `OPEN -> REPAIRED` cannot move
        # `urgent_work_order_count`, while voiding does recompute it - which pins
        # the predicate at `priority_tier` URGENT among non-`VOID` rows.
        assert_sweep_counters(sweep, 2, 1, 0, 1, 50.00)


def _two_severe_findings(api):
    """A sweep at 50.00 percent: one verified order and one untouched order."""
    bundle = X.sweep_lifecycle(
        api,
        "SEV_WINDOW",
        K.CEDAR_WALK,
        CEDAR_UNIT,
        observed_at=K.SWEEP_OBSERVED_AT_1,
    )
    bundle["first_work_order_id"] = bundle["work_order_id"]
    bundle["first_deficiency_id"] = bundle["deficiency_id"]

    second = X.record_finding(
        api,
        bundle["property_id"],
        bundle["sweep_id"],
        X.read_sweep(api, bundle["sweep_id"])["version"],
        bundle["definition_ids"]["SEV_WINDOW"],
        sorted(bundle["unit_ids"].items())[0][1],
        "UNIT",
        observed_at=SECOND_OBSERVED_AT,
    )
    bundle["second_work_order_id"] = second["work_order_id"]
    bundle["second_deficiency_id"] = second["deficiency_id"]

    X.completed_work_order(
        api,
        bundle["first_work_order_id"],
        TECHNICIAN,
        completed_at=K.WORK_ORDER_COMPLETED_AT,
        resolution_note="Sash replaced and tested",
    )
    assert_ok(
        api.verify_work_order_closure(
            bundle["first_work_order_id"],
            F.verify_closure_payload(
                "PASSED", verified_at=K.WORK_ORDER_VERIFIED_AT
            ),
            REVIEWER,
        )
    )
    return bundle


def _corrected_life_threatening(api):
    """A life-threatening finding the owner has already claimed as corrected."""
    bundle = X.sweep_lifecycle(
        api,
        "LT_GAS",
        K.CEDAR_WALK,
        CEDAR_UNIT,
        definition_codes=("LT_GAS",),
        observed_at=LT_OBSERVED_AT,
    )
    assert_property_state(
        X.read_property(api, bundle["property_id"]), "RESTRICTED", 1, 0, 0
    )
    assert_ok(
        api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=DIRECT_CORRECTED_AT,
                note="Union replaced, leak test passed",
            ),
            bundle["owner_headers"],
        )
    )
    corrected = X.read_property(api, bundle["property_id"])
    assert_property_state(corrected, "READY", 0, 0, 0)
    bundle["property_version_after_correction"] = corrected["version"]
    return bundle


class TestVoidingCompensatesTheClosureGate:
    """Voiding an order raised in error is how a sweep recovers its rate."""

    def test_the_closure_rate_floor_blocks_the_first_close(self, api):
        """One verified order out of two leaves the sweep at 50.00 percent.

        PRD: "From `IN_PROGRESS` it moves `IN_PROGRESS -> CLOSED`, but only if
        `closure_verified_rate` is at least 90.00 - measured on the rounded
        value, and inclusive at the boundary, so a rate of exactly `90.00`
        closes - otherwise the request is rejected with
        `ERR_SWEEP_CLOSURE_RATE_TOO_LOW` (HTTP 409)."

        Design: Difficulty/compensating_invariant/voiding_an_unverified_work_order_compensates_the_sweep_closure_gate
        """
        bundle = _two_severe_findings(api)
        before = X.read_sweep(api, bundle["sweep_id"])
        assert_two_decimals(
            before["closure_verified_rate"], 50.00, "closure_verified_rate"
        )
        assert_integer(
            before["generated_work_order_count"],
            2,
            "generated_work_order_count",
        )

        response = api.close_sweep(
            bundle["sweep_id"],
            F.sweep_close_payload(closed_at=FIRST_CLOSE_AT),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.SWEEP_CLOSURE_RATE_TOO_LOW)
        blocked = X.read_sweep(api, bundle["sweep_id"])
        assert_fields(blocked, status="IN_PROGRESS")
        assert_null(blocked, "closed_at")
        assert_null(
            X.read_property(api, bundle["property_id"]), "last_sweep_closed_at"
        )

    def test_voiding_the_unverified_work_order_lets_the_sweep_close(self, api):
        """The void retires the second order and lifts the rate to 100.00.

        PRD: "If no non-`VOID` work order remains against the linked deficiency,
        that deficiency transitions to `VOIDED` and its `points_deducted` is set
        to `0.00`."

        Design: Difficulty/compensating_invariant/voiding_an_unverified_work_order_compensates_the_sweep_closure_gate
        """
        bundle = _two_severe_findings(api)
        assert_error(
            api.close_sweep(
                bundle["sweep_id"],
                F.sweep_close_payload(closed_at=FIRST_CLOSE_AT),
                bundle["owner_headers"],
            ),
            ApiErrorId.SWEEP_CLOSURE_RATE_TOO_LOW,
        )

        voided = assert_ok(
            api.void_work_order(
                bundle["second_work_order_id"],
                F.void_payload(
                    void_reason="Duplicate of the first finding; raised in error"
                ),
                bundle["owner_headers"],
            )
        )
        assert_fields(voided, repair_status="VOID")

        closed = assert_ok(
            api.close_sweep(
                bundle["sweep_id"],
                F.sweep_close_payload(closed_at=SECOND_CLOSE_AT),
                bundle["owner_headers"],
            )
        )

        assert_fields(closed, status="CLOSED")
        assert_instant(closed["closed_at"], SECOND_CLOSE_AT, "closed_at")
        assert_sweep_counters(closed, 2, 1, 1, 0, 100.00)
        assert_integer(
            closed["open_work_order_count"], 0, "open_work_order_count"
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_instant(
            owning_property["last_sweep_closed_at"],
            SECOND_CLOSE_AT,
            "last_sweep_closed_at",
        )
        assert_property_state(owning_property, "READY", 0, 0, 0)
        second = X.read_deficiency(api, bundle["second_deficiency_id"])
        assert_fields(second, status="VOIDED")
        assert_two_decimals(second["points_deducted"], 0.00, "points_deducted")
        first = X.read_deficiency(api, bundle["first_deficiency_id"])
        assert_fields(first, status="VERIFIED")
        assert_two_decimals(first["points_deducted"], 16.00, "points_deducted")


class TestFailedDeficiencyVerification:
    """A failed verification unwinds the correction without moving the deadline."""

    def test_a_failed_verification_reopens_the_deficiency_without_extending_it(
        self, api
    ):
        """The row returns to OPEN and keeps its original 24-hour deadline.

        PRD: "On `FAILED` it moves `CORRECTED -> OPEN` and `corrected_at` is
        cleared to null; crucially, `correction_due_at` is **not** extended, so a
        failed verification can leave a deficiency immediately eligible to tip
        overdue."

        Design: Difficulty/compensating_invariant/failed_verification_restores_the_life_threatening_counters_without_drift
        """
        bundle = _corrected_life_threatening(api)

        response = api.record_verification(
            bundle["deficiency_id"],
            F.deficiency_verification_payload(
                "FAILED",
                verified_at=DIRECT_VERIFIED_AT,
                note="Fitting still weeping under pressure",
            ),
            X.INSPECTOR,
        )

        deficiency = assert_ok(response)
        assert_fields(deficiency, status="OPEN")
        assert_null(deficiency, "corrected_at")
        assert_instant(
            deficiency["correction_due_at"], LT_DUE_AT, "correction_due_at"
        )
        assert_two_decimals(
            deficiency["points_deducted"], 36.00, "points_deducted"
        )

    def test_a_failed_verification_restores_the_property_counters(self, api):
        """The counters return to their pre-correction values, once only.

        PRD: "Both branches make the property recompute its three deficiency
        counters and re-derive `readiness_posture`, and both increment the
        `version` of the deficiency and of the property by 1."

        Design: Difficulty/compensating_invariant/failed_verification_restores_the_life_threatening_counters_without_drift
        """
        bundle = _corrected_life_threatening(api)

        response = api.record_verification(
            bundle["deficiency_id"],
            F.deficiency_verification_payload(
                "FAILED",
                verified_at=DIRECT_VERIFIED_AT,
                note="Fitting still weeping under pressure",
            ),
            X.INSPECTOR,
        )

        assert_ok(response)
        restored = X.read_property(api, bundle["property_id"])
        assert_property_state(restored, "RESTRICTED", 1, 0, 0)
        assert_integer(
            restored["version"],
            bundle["property_version_after_correction"] + 1,
            "version",
        )
        work_order = X.read_work_order(api, bundle["work_order_id"])
        assert_fields(work_order, repair_status="OPEN")
        assert_null(work_order, "completed_at")
