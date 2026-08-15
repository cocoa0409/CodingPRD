"""Violations and civil penalties: demand vs final accrual variants, marginal
tiers, the assessed-value cap, court escalation, and after-the-fact
legalization gates (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equal,
    create_notice_issued_violation,
    create_owner,
    create_property,
    create_violation,
    get_property,
    get_violation,
    issue_notice,
    make_applicant_headers,
    set_clock,
    setup_after_the_fact_pending,
    validate_error,
    validate_success,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestPenaltyDemandProjectionVsFinalAccrual:
    def test_demand_letter_projects_thirty_day_cure(self, api):
        """PRD §3.8: "Issuing the formal notice moves the case from `OPEN` to
        `NOTICE_ISSUED`, stamps `notice_issued_at` with the logical clock, and
        computes the `demand_letter_amount_cents`: the demand variant of the
        civil penalty, projecting the accrual if the owner cures within the
        thirty-day cure window by taking the stop date as `notice_issued_at`
        plus thirty days."
        PRD §3.8: "The first thirty days accrue at 10,000 cents per day; days
        thirty-one through sixty accrue at 20,000 cents per day; and every day
        from the sixty-first onward accrues at 50,000 cents per day."

        Design: Difficulty/dual_variant_calc/penalty_demand_projection_vs_final_accrual
        """
        set_clock("2026-08-01T00:00:00Z")
        owner = create_owner()
        prop = create_property(owner["id"], assessed_value_cents=10_000_000)
        violation = create_violation(prop["id"])

        noticed = validate_success(api.issue_notice(violation["id"], OFFICER))
        assert noticed["status"] == "NOTICE_ISSUED"
        assert_instant_equal(
            noticed["notice_issued_at"], "2026-08-01T00:00:00Z", "notice_issued_at"
        )
        # Demand variant: 30 days x 10000; cap is 1000000 and not reached.
        assert noticed["demand_letter_amount_cents"] == 300000

    def test_final_penalty_accrues_marginal_tiers(self, api):
        """PRD §3.8: "The first thirty days accrue at 10,000 cents per day;
        days thirty-one through sixty accrue at 20,000 cents per day; and every
        day from the sixty-first onward accrues at 50,000 cents per day."
        PRD §3.8: "Verification stamps `compliance_verified_at` with the
        logical clock, computes `final_penalty_cents` as the final variant of
        the penalty with the accrual stop at that verification instant, sets
        `penalty_capped`, decrements the property's `open_violation_count` by
        one, and recomputes `compliance_posture`."

        Design: Difficulty/dual_variant_calc/penalty_demand_projection_vs_final_accrual
        """
        set_clock("2026-08-01T00:00:00Z")
        owner = create_owner()
        prop = create_property(owner["id"], assessed_value_cents=10_000_000)
        violation = create_violation(prop["id"])
        noticed = issue_notice(violation["id"])
        demand = noticed["demand_letter_amount_cents"]

        set_clock("2026-09-15T00:00:00Z")  # 45 whole days after the notice
        verified = validate_success(api.verify_compliance(violation["id"], OFFICER))
        assert verified["status"] == "COMPLIANCE_VERIFIED"
        # 30 x 10000 + 15 x 20000 = 600000, under the 1000000 cap.
        assert verified["final_penalty_cents"] == 600000
        assert verified["penalty_capped"] is False
        assert demand == 300000
        assert verified["final_penalty_cents"] != demand, (
            "the demand and final variants price the same violation differently"
        )

        prop_after = get_property(prop["id"])
        assert prop_after["open_violation_count"] == 0
        assert prop_after["compliance_posture"] == "CLEAR"


def test_penalty_tier_day_thirty_one_boundary(api):
    """PRD §3.8: "The first thirty days accrue at 10,000 cents per day; days
    thirty-one through sixty accrue at 20,000 cents per day; and every day from
    the sixty-first onward accrues at 50,000 cents per day."
    PRD §3.8: "The civil penalty itself accrues daily on whole days, measured
    from the notice instant to the applicable stop date; partial days do not
    count."

    Design: Corner/calculations/penalty_tier_day_31_boundary
    """
    set_clock("2026-08-01T00:00:00Z")
    owner = create_owner()
    prop = create_property(owner["id"], assessed_value_cents=10_000_000)
    violation = create_notice_issued_violation(prop["id"])

    set_clock("2026-09-01T00:00:00Z")  # exactly 31 whole days after the notice
    verified = validate_success(api.verify_compliance(violation["id"], OFFICER))
    # 30 x 10000 + 1 x 20000 = 320000: one day into the second marginal tier.
    assert verified["final_penalty_cents"] == 320000


def test_penalty_cap_binds_at_ten_percent_assessed(api):
    """PRD §3.8: "The cap is ten percent of the property's
    `assessed_value_cents`, rounded half-up to a whole cent."
    PRD §3.8: "The assessed penalty is the lesser of the raw accrual and the
    cap, and `penalty_capped` is true exactly when the raw accrual strictly
    exceeds the cap — when the two are equal, the cap did not limit anything
    and the flag is false."

    Design: Corner/calculations/penalty_cap_binds_at_ten_percent_assessed
    """
    set_clock("2026-08-01T00:00:00Z")
    owner = create_owner()
    prop = create_property(owner["id"], assessed_value_cents=2_000_000)
    violation = create_violation(prop["id"])

    noticed = validate_success(api.issue_notice(violation["id"], OFFICER))
    # Raw projection 300000, cap round_half_up(0.10 * 2000000) = 200000.
    assert noticed["demand_letter_amount_cents"] == 200000

    set_clock("2026-09-15T00:00:00Z")  # raw final accrual would be 600000
    verified = validate_success(api.verify_compliance(violation["id"], OFFICER))
    assert verified["final_penalty_cents"] == 200000
    assert verified["penalty_capped"] is True


def test_court_referral_threshold_sixty_days(api):
    """PRD §3.8: "Escalation is the second shape: an officer refers a
    `NOTICE_ISSUED` case to court, but only once more than sixty whole days
    have elapsed since `notice_issued_at`; at sixty days or fewer the referral
    is rejected with `ERR_ESCALATION_THRESHOLD_NOT_MET`. A successful referral
    moves the case to `COURT_REFERRAL` and stamps `referred_at`."

    Design: Corner/validations/escalation_threshold_day_60_rejected_day_61_allowed
    """
    set_clock("2026-08-01T00:00:00Z")
    owner = create_owner()
    prop = create_property(owner["id"], assessed_value_cents=9_000_000)
    violation = create_notice_issued_violation(prop["id"])

    set_clock("2026-09-30T00:00:00Z")  # exactly 60 whole days
    blocked = api.refer_court(violation["id"], OFFICER)
    validate_error(blocked, ApiErrorId.ERR_ESCALATION_THRESHOLD_NOT_MET)

    set_clock("2026-10-01T00:00:00Z")  # 61 whole days
    referred = validate_success(api.refer_court(violation["id"], OFFICER))
    assert referred["status"] == "COURT_REFERRAL"
    assert_instant_equal(referred["referred_at"], "2026-10-01T00:00:00Z", "referred_at")


def test_after_the_fact_requires_notice_issued(api):
    """PRD §3.8: "the submission requires the violation to be in
    `NOTICE_ISSUED` status — anything else is rejected with
    `ERR_VIOLATION_NOT_UNDER_NOTICE` — and the violation's property must be the
    application's `property_id`, or the submission is rejected with
    `ERR_VIOLATION_PROPERTY_MISMATCH`."

    Design: Corner/validations/after_the_fact_requires_notice_issued
    """
    owner = create_owner()
    prop = create_property(owner["id"])
    violation = create_violation(prop["id"])  # still OPEN; notice never issued

    response = api.create_application(
        {
            "property_id": prop["id"],
            "owner_id": owner["id"],
            "application_type": "ADDITION",
            "is_visible_from_public_way": True,
            "after_the_fact": True,
            "violation_id": violation["id"],
            "work_items": [work_item("ADDITION", "deck", 300000)],
        },
        make_applicant_headers(owner["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VIOLATION_NOT_UNDER_NOTICE)


def test_after_the_fact_property_mismatch_rejected(api):
    """PRD §3.8: "the submission requires the violation to be in
    `NOTICE_ISSUED` status — anything else is rejected with
    `ERR_VIOLATION_NOT_UNDER_NOTICE` — and the violation's property must be the
    application's `property_id`, or the submission is rejected with
    `ERR_VIOLATION_PROPERTY_MISMATCH`."

    Design: Corner/validations/after_the_fact_property_mismatch_rejected
    """
    owner = create_owner()
    prop1 = create_property(owner["id"])
    prop2 = create_property(owner["id"])
    violation = create_notice_issued_violation(prop1["id"])

    response = api.create_application(
        {
            "property_id": prop2["id"],
            "owner_id": owner["id"],
            "application_type": "ADDITION",
            "is_visible_from_public_way": True,
            "after_the_fact": True,
            "violation_id": violation["id"],
            "work_items": [work_item("ADDITION", "deck", 300000)],
        },
        make_applicant_headers(owner["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VIOLATION_PROPERTY_MISMATCH)


class TestVerifyBlockedByUnapprovedAfterTheFact:
    def test_verify_compliance_blocked_by_unapproved_after_the_fact(self, api):
        """PRD §3.8: "from `AFTER_THE_FACT_PENDING` it is permitted only when
        the linked application has reached an approval terminal state —
        `APPROVED`, `APPROVED_WITH_CONDITIONS`, or `APPROVED_ON_APPEAL` — and
        is otherwise rejected with `ERR_LINKED_APPLICATION_NOT_APPROVED`."
        PRD §3.8: "A successful after-the-fact submission immediately flips the
        violation from `NOTICE_ISSUED` to `AFTER_THE_FACT_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/violation_blocked_by_unapproved_after_the_fact
        """
        ctx = setup_after_the_fact_pending()  # application sits UNDER_STAFF_REVIEW
        assert ctx["violation"]["status"] == "AFTER_THE_FACT_PENDING"

        response = api.verify_compliance(ctx["violation"]["id"], OFFICER)
        validate_error(response, ApiErrorId.ERR_LINKED_APPLICATION_NOT_APPROVED)

    def test_blocked_verify_leaves_violation_and_property_counters(self, api):
        """PRD §3.8: "from `AFTER_THE_FACT_PENDING` it is permitted only when
        the linked application has reached an approval terminal state —
        `APPROVED`, `APPROVED_WITH_CONDITIONS`, or `APPROVED_ON_APPEAL` — and
        is otherwise rejected with `ERR_LINKED_APPLICATION_NOT_APPROVED`."
        PRD §2.10: "every such cascade commits atomically within the triggering request: there is no eventual-consistency window in which a client could observe a decision without its hearing mirror, a demolition approval without its delay window, or a violation resolution without its property counter adjustment."

        Design: Difficulty/cross_entity_state_dependency/violation_blocked_by_unapproved_after_the_fact
        """
        ctx = setup_after_the_fact_pending()
        validate_error(
            api.verify_compliance(ctx["violation"]["id"], OFFICER),
            ApiErrorId.ERR_LINKED_APPLICATION_NOT_APPROVED,
        )

        violation = get_violation(ctx["violation"]["id"])
        assert violation["status"] == "AFTER_THE_FACT_PENDING"
        prop = get_property(ctx["property"]["id"])
        assert prop["open_violation_count"] == 1
        assert prop["compliance_posture"] == "UNDER_ENFORCEMENT"
