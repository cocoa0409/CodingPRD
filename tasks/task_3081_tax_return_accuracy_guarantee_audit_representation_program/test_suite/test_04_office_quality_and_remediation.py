"""Office quality close: score boundaries, posture recomputation, close-period
monotonicity, probation cascades into preparer suspension and filing blocks,
and the remediation lifecycle's parallel dimensions.
"""
from test_helpers import (
    TEST_USERS,
    create_client,
    create_office,
    create_preparer,
    create_remediation_payload,
    create_return,
    get_success_data,
    make_preparer_headers,
    quality_close,
    set_clock,
    setup_filed_return,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestQualityScoreThresholdBoundaries:
    def test_score_80_boundary_is_ok(self, api):
        """PRD §3.8: "Posture thresholds are pinned with at-least semantics: a
        score of at least 80 leaves or moves the office to `OK`; a score of at
        least 60 but below 80 yields `WATCH`; below 60 yields `PROBATION`."
        PRD §3.8: "The `quality_score` starts from 100, subtracts the defect
        rate weighted four hundredfold and the claim rate weighted
        three hundredfold, rounds half-up to an integer, and clamps into the
        inclusive range 0 to 100."

        10 defects over 200 examined is a 0.05 defect rate: 100 - 400 * 0.05
        = 80 exactly, which meets the at-least-80 threshold.

        Design: Difficulty/boundary_precision_check/quality_score_threshold_boundaries
        """
        office = create_office()
        snap = quality_close(office["id"], period_month="2026-09",
                             returns_examined=200, returns_with_defects=10)
        assert snap["quality_score"] == 80
        assert snap["posture_after"] == "OK"
        after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert after["posture"] == "OK"

    def test_score_79_just_below_boundary_is_watch(self, api):
        """PRD §3.8: "a score of at least 80 leaves or moves the office to
        `OK`; a score of at least 60 but below 80 yields `WATCH`; below 60
        yields `PROBATION`."

        21 defects over 400 examined is a 0.0525 defect rate: 100 - 400 *
        0.0525 = 79, below the OK threshold.

        Design: Difficulty/boundary_precision_check/quality_score_threshold_boundaries
        """
        office = create_office()
        snap = quality_close(office["id"], period_month="2026-09",
                             returns_examined=400, returns_with_defects=21)
        assert snap["quality_score"] == 79
        assert snap["posture_after"] == "WATCH"
        after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert after["posture"] == "WATCH"


class TestRemediationPeriodRegression:
    def test_equal_and_earlier_periods_rejected(self, api):
        """PRD §3.8: "Periods must move strictly forward: a `period_month`
        that does not lexicographically exceed the office's
        `last_close_period` is rejected with `ERR_CLOSE_PERIOD_REGRESSION`
        (HTTP 422); a null `last_close_period` accepts any first period."

        Repeating the just-closed period and closing an earlier one are both
        rejected.

        Design: Difficulty/resource_temporal_overlap/remediation_period_regression
        """
        office = create_office()
        quality_close(office["id"], period_month="2026-09", returns_examined=10,
                      returns_with_defects=1)
        res_equal = api.quality_close_office(
            office["id"], {"period_month": "2026-09", "returns_examined": 10,
                           "returns_with_defects": 1}, OM)
        validate_error(res_equal, "ERR_CLOSE_PERIOD_REGRESSION")
        res_earlier = api.quality_close_office(
            office["id"], {"period_month": "2026-08", "returns_examined": 10,
                           "returns_with_defects": 1}, OM)
        validate_error(res_earlier, "ERR_CLOSE_PERIOD_REGRESSION")

    def test_next_period_accepted_and_recorded(self, api):
        """PRD §3.8: "Periods must move strictly forward: a `period_month`
        that does not lexicographically exceed the office's
        `last_close_period` is rejected with `ERR_CLOSE_PERIOD_REGRESSION`
        (HTTP 422); a null `last_close_period` accepts any first period."
        PRD §3.8: "Each close that changes posture bumps the office's
        `version`, refreshes `last_close_period`".

        The lexicographically greater period is accepted and becomes the
        office's last closed period.

        Design: Difficulty/resource_temporal_overlap/remediation_period_regression
        """
        office = create_office()
        quality_close(office["id"], period_month="2026-09", returns_examined=10,
                      returns_with_defects=1)
        snap = quality_close(office["id"], period_month="2026-10", returns_examined=10,
                             returns_with_defects=1)
        assert snap["period_month"] == "2026-10"
        after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert after["last_close_period"] == "2026-10"


class TestProbationCloseSuspensionCascade:
    def test_probation_suspends_overdue_preparer_and_blocks_filing(self, api):
        """PRD §3.8: "Probation carries a personnel consequence: when a close
        lands the office in `PROBATION`, every preparer of that office holding
        an `OPEN` remediation whose `due_at` is earlier than the logical clock
        has their `credential_status` flipped to `SUSPENDED` (with a preparer
        `version` bump), which immediately blocks filing under their name per
        §3.2."
        PRD §2.8: "State preconditions on the target resource come fourth
        (`ERR_INVALID_STATE`)".

        Defect rate 0.25 scores 0 (< 60) -> PROBATION -> the overdue
        preparer is suspended -> their return cannot be filed.

        Design: Difficulty/transitive_cascade/probation_close_suspension_cascade
        """
        office = create_office()
        preparer = create_preparer(office["id"])
        client = create_client()
        ret = create_return(client["id"], office["id"], preparer["id"], components=["1040_SIMPLE"])
        get_success_data(api.create_remediation(
            create_remediation_payload(preparer["id"], due_at="2026-09-05T00:00:00Z"), OM))
        set_clock("2026-09-10T00:00:00Z")
        quality_close(office["id"], period_month="2026-09", returns_examined=100,
                      returns_with_defects=25)
        office_after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert office_after["posture"] == "PROBATION"
        prep_after = validate_success(api.get_preparer(preparer["id"], OM), 200)
        assert prep_after["credential_status"] == "SUSPENDED"
        res = api.file_return(ret["id"], OM)
        validate_error(res, "ERR_INVALID_STATE")

    def test_probation_requires_score_below_60(self, api):
        """PRD §3.8: "a score of at least 80 leaves or moves the office to
        `OK`; a score of at least 60 but below 80 yields `WATCH`; below 60
        yields `PROBATION`."
        PRD §3.8: "when a close lands the office in `PROBATION`, every
        preparer of that office holding an `OPEN` remediation whose `due_at`
        is earlier than the logical clock has their `credential_status`
        flipped to `SUSPENDED`".

        A WATCH close (score 79) does NOT suspend the overdue-remediation
        preparer — the personnel consequence is specific to PROBATION.

        Design: Difficulty/transitive_cascade/probation_close_suspension_cascade
        """
        office = create_office()
        preparer = create_preparer(office["id"])
        get_success_data(api.create_remediation(
            create_remediation_payload(preparer["id"], due_at="2026-09-05T00:00:00Z"), OM))
        set_clock("2026-09-10T00:00:00Z")
        quality_close(office["id"], period_month="2026-09", returns_examined=400,
                      returns_with_defects=21)
        office_after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert office_after["posture"] == "WATCH"
        prep_after = validate_success(api.get_preparer(preparer["id"], OM), 200)
        assert prep_after["credential_status"] == "ACTIVE"


class TestPreparerParallelDimensions:
    def test_second_remediation_autocloses_first_and_leaves_suspension(self, api):
        """PRD §3.8: "If that preparer already has an `OPEN` remediation, the
        existing one auto-completes on the spot — its `completed_at` is
        stamped with the logical clock and its status becomes `COMPLETED`,
        cascading the preparer's `remediation_status` momentarily to
        `COMPLETED` — before the new `OPEN` remediation sets it back to
        `ACTIVE`; the preparer ends the operation in `ACTIVE` either way."
        PRD §3.8: "The two preparer dimensions stay independent throughout: a
        suspension from the quality close changes `credential_status` without
        touching `remediation_status`, and remediation activity never alters
        `credential_status`."

        After a probation suspension, a second remediation auto-closes the
        first and reactivates remediation_status while credential_status stays
        SUSPENDED.

        Design: Difficulty/non_linear_state_machine/preparer_parallel_dimensions
        """
        office = create_office()
        preparer = create_preparer(office["id"])
        rm1 = get_success_data(api.create_remediation(
            create_remediation_payload(preparer["id"], due_at="2026-09-05T00:00:00Z"), OM))
        set_clock("2026-09-10T00:00:00Z")
        quality_close(office["id"], period_month="2026-09", returns_examined=100,
                      returns_with_defects=25)
        get_success_data(api.create_remediation(
            create_remediation_payload(preparer["id"], due_at="2026-12-01T00:00:00Z"), OM))
        rm1_after = validate_success(api.get_remediation(rm1["id"], OM), 200)
        assert rm1_after["status"] == "COMPLETED"
        prep_after = validate_success(api.get_preparer(preparer["id"], OM), 200)
        assert prep_after["remediation_status"] == "ACTIVE"
        assert prep_after["credential_status"] == "SUSPENDED"
        office_after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert office_after["posture"] == "PROBATION"

    def test_opening_remediation_flips_remediation_status_not_credential(self, api):
        """PRD §3.8: "An `OfficeManager` opens a remediation action for a
        preparer with `preparer_id` and a `due_at` deadline; opening one flips
        the preparer's `remediation_status` from `NONE` or `COMPLETED` to
        `ACTIVE`."
        PRD §3.1: "A new preparer's `credential_status` starts as `ACTIVE` and
        their `remediation_status` starts as `NONE`; these are two parallel
        dimensions that evolve independently and never block each other's
        transitions."

        Design: Difficulty/non_linear_state_machine/preparer_parallel_dimensions
        """
        office = create_office()
        preparer = create_preparer(office["id"])
        assert preparer["remediation_status"] == "NONE"
        assert preparer["credential_status"] == "ACTIVE"
        get_success_data(api.create_remediation(
            create_remediation_payload(preparer["id"], due_at="2027-01-01T00:00:00Z"), OM))
        prep_after = validate_success(api.get_preparer(preparer["id"], OM), 200)
        assert prep_after["remediation_status"] == "ACTIVE"
        assert prep_after["credential_status"] == "ACTIVE"


class TestRemediationOverdueCannotComplete:
    def test_overdue_completion_rejected(self, api):
        """PRD §3.8: "The preparer — and only that preparer, by entity-backed
        identity — completes their own open remediation, which requires the
        logical clock to be at or before `due_at`; a completion attempted
        after the deadline is rejected with `ERR_REMEDIATION_OVERDUE` (HTTP
        422)".

        Design: Corner/validations/remediation_overdue_cannot_complete
        """
        office = create_office()
        preparer = create_preparer(office["id"])
        rm = get_success_data(api.create_remediation(
            create_remediation_payload(preparer["id"], due_at="2026-09-05T00:00:00Z"), OM))
        set_clock("2026-09-10T00:00:00Z")
        res = api.complete_remediation(rm["id"], make_preparer_headers(preparer["id"]))
        validate_error(res, "ERR_REMEDIATION_OVERDUE")
        after = validate_success(api.get_remediation(rm["id"], OM), 200)
        assert after["status"] == "OPEN"


class TestProbationBlocksProductSale:
    def test_sale_blocked_under_probation_then_allowed_after_recovery(self, api):
        """PRD §3.3: "A product sale attempted for a return of an office whose
        posture is `PROBATION` is rejected with `ERR_OFFICE_POSTURE_BLOCKED`
        (HTTP 409)."
        PRD §3.8: "a score of at least 80 leaves or moves the office to `OK`".

        Defect rate 0.25 scores 0 -> PROBATION blocks the sale; a clean close
        (score 100) restores OK and the same sale succeeds.

        Design: Corner/validations/probation_blocks_product_sale
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"], product_tier=None)
        office = ctx["office"]
        quality_close(office["id"], period_month="2026-09", returns_examined=100,
                      returns_with_defects=25)
        res = api.create_product({"return_id": ctx["tax_return"]["id"], "tier": "STANDARD"}, OM)
        validate_error(res, "ERR_OFFICE_POSTURE_BLOCKED")
        quality_close(office["id"], period_month="2026-10", returns_examined=100,
                      returns_with_defects=0)
        office_after = validate_success(api.get_office(office["id"], ADMIN), 200)
        assert office_after["posture"] == "OK"
        product = validate_success(
            api.create_product({"return_id": ctx["tax_return"]["id"], "tier": "STANDARD"}, OM), 201)
        assert product["status"] == "ACTIVE"
