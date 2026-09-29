"""Corner-case coverage for the §1.9 `calculations`, `endpoints` and
`consistency model` design sections.

Every test here is the translation of one instance of the corner design index;
the assertions are derived from PRD.md, which wins wherever the index and the
PRD disagree.
"""
import json

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, validate_error, validate_paginated, validate_success,
)

from test_helpers import (
    api_client, assertions as A, factories as F, fixtures as X,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_admin_headers, make_employer_admin_headers, make_merchant_headers,
    make_partner_manager_headers,
)
from test_helpers.types import (
    DisputeOutcome, EmploymentStatus, PerkCategory, PlacementTier, RegionCode,
    StatementBasis,
)

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


# ── calculations ────────────────────────────────────────────────────────────


def test_eligible_headcount_counts_only_the_in_window_eligible_rows():
    """A five-row roster yields eligible_headcount 4, never the declared 500.

    PRD: "The employer's `eligible_headcount` is the number of that employer's memberships that satisfy three conditions at once: `status` is `ELIGIBLE`, `employment_status` is `ACTIVE` or `LEAVE`, and the logical clock falls at or after `eligibility_valid_from` and strictly before `eligibility_valid_until`."

    Design: Corner/calculations/eligible_headcount_counts_only_in_window_eligible_rows
    """
    X.set_clock(CLOCK_EPOCH)
    employer = X.create_employer(
        name="Northwind Co", employee_count_declared=500,
        revenue_share_enabled=True, privacy_min_cohort_size=3,
    )
    assert employer["eligible_headcount"] == 0, "a fresh employer has no reach"
    X.brand_storefront(employer["id"], featured_categories=[PerkCategory.DINING])

    records = [
        F.eligibility_record("E-001"),
        F.eligibility_record("E-002"),
        F.eligibility_record("E-003", region_code=RegionCode.TX),
        F.eligibility_record("E-004", employment_status=EmploymentStatus.LEAVE),
        # E-005 is well formed but its window closes exactly at the clock.
        F.eligibility_record("E-005", eligibility_valid_until=CLOCK_EPOCH),
    ]
    batch = X.load_eligibility_file(employer["id"], records=records)
    assert batch["record_count"] == 5
    assert batch["invalid_record_count"] == 0
    assert batch["valid_record_count"] == 5
    assert X.validate_eligibility_file(batch["id"], employer["id"])["status"] == "VALIDATED"

    applied = X.apply_eligibility_file(batch["id"], employer["id"])
    assert applied["created_membership_count"] == 5

    reread = X.get_employer(employer["id"])
    # 3 ACTIVE + 1 LEAVE inside their windows = 4; E-005's window is half-open
    # so an eligibility_valid_until equal to the clock excludes it.
    assert reread["eligible_headcount"] == 4
    assert reread["employee_count_declared"] == 500
    assert reread["eligible_headcount"] != reread["employee_count_declared"]

    rows = X.list_memberships(employer["id"])
    assert len(rows) == 5
    assert rows[4]["external_employee_ref"] == "E-005"
    # The row is ELIGIBLE yet out of window: the two notions are distinct.
    assert rows[4]["status"] == "ELIGIBLE"


def test_accrual_and_cash_finalize_select_different_redemption_sets():
    """ACCRUAL settles all three verified lines, CASH only the fulfilled one.

    PRD: "Under `CASH`, the inclusion set is every redemption of that employer whose `verification_status` is `VERIFIED`, whose `fulfillment_status` is `FULFILLED`, and whose `fulfilled_at` falls at or after `period_start` and strictly before `period_end`; a verified-but-unfulfilled redemption is excluded even when its `verified_at` sits squarely inside the period, and a redemption verified in one period but fulfilled in the next belongs to the later one."

    Design: Corner/calculations/accrual_and_cash_statements_select_different_redemption_sets
    """
    X.set_clock(CLOCK_EPOCH)
    program = X.live_program(
        record_count=3, commission_rate_bps=1200, employer_revenue_share_bps=2500,
        revenue_share_enabled=True, offer_overrides={"min_spend_cents": 1000},
    )
    offer_id = program["offer"]["id"]
    merchant_id = program["merchant"]["id"]
    members = program["memberships"]

    # 8396 gross: discount 1679 (8396*2000/10000 = 1679.2 -> 1679),
    # net 6717, commission 806 (6717*1200/10000 = 806.04 -> 806),
    # employer share 202 (806*2500/10000 = 201.5 -> 202), provider net 604.
    red1 = X.verified_redemption(offer_id, members[0]["id"], merchant_id, 8396,
                                 intended_gross_amount_cents=8396)
    A.assert_line_economics(red1, 8396, 1679, 6717, 806, 202, 604)
    red2 = X.verified_redemption(offer_id, members[1]["id"], merchant_id, 8396,
                                 intended_gross_amount_cents=8396)
    assert red2["commission_amount_cents"] == 806
    assert red2["employer_share_cents"] == 202
    # 5000 gross: discount 1000, net 4000, commission 480, share 120.
    red3 = X.verified_redemption(offer_id, members[2]["id"], merchant_id, 5000)
    A.assert_line_economics(red3, 5000, 1000, 4000, 480, 120, 360)

    X.set_clock("2026-08-02T00:00:00Z")
    fulfilled = X.fulfill_redemption(red1["id"], merchant_id)
    A.assert_iso_equals(fulfilled["fulfilled_at"], "2026-08-02T00:00:00Z")

    accrual = X.create_statement(
        program["employer"]["id"], period_start=CLOCK_EPOCH,
        period_end="2026-09-01T00:00:00Z", basis=StatementBasis.ACCRUAL,
    )
    assert accrual["status"] == "DRAFT"
    assert accrual["gross_commission_cents"] == 0, "nothing is computed at creation"
    cash = X.create_statement(
        program["employer"]["id"], period_start=CLOCK_EPOCH,
        period_end="2026-09-01T00:00:00Z", basis=StatementBasis.CASH,
    )
    X.set_clock("2026-09-02T00:00:00Z")

    accrual_final = X.finalize_statement(accrual["id"])
    # 806 + 806 + 480 = 2092 commission; 202 + 202 + 120 = 524 share.
    A.assert_fields(accrual_final, {
        "status": "FINALIZED",
        "included_redemption_count": 3,
        "gross_commission_cents": 2092,
        "employer_share_cents": 524,
        "provider_retained_cents": 1568,
        "reversal_adjustment_cents": 0,
    }, "accrual statement")
    A.assert_iso_equals(accrual_final["finalized_at"], "2026-09-02T00:00:00Z")

    cash_final = X.finalize_statement(cash["id"])
    A.assert_fields(cash_final, {
        "status": "FINALIZED",
        "included_redemption_count": 1,
        "gross_commission_cents": 806,
        "employer_share_cents": 202,
        "provider_retained_cents": 604,
        "reversal_adjustment_cents": 0,
    }, "cash statement")

    # The CASH finalize counted red1 without restamping its statement_id.
    assert X.get_redemption(red1["id"])["statement_id"] == accrual["id"]
    red3_after = X.get_redemption(red3["id"])
    assert red3_after["statement_id"] == accrual["id"]
    assert red3_after["fulfilled_at"] is None


def test_dispute_response_deadline_is_the_one_hundred_twenty_hour_constant():
    """A dispute filed on 08-02 falls due on 08-07 and is default-judged there.

    PRD: "The new **Dispute** is created in `OPEN`; it copies `redemption_id` from the path, `raised_by_membership_id` and `merchant_id` from the redemption, sets `response_deadline_at` to the logical clock plus 120 hours, starts `info_request_count` at 0 and `default_judged` at false, and leaves `response_note`, `remedy_offered_cents`, `outcome_credit_cents` and `resolved_at` null."

    Design: Corner/calculations/dispute_response_deadline_uses_the_one_hundred_twenty_hour_constant
    """
    X.set_clock(CLOCK_EPOCH)
    program = X.live_program(record_count=1, revenue_share_enabled=True)
    merchant_id = program["merchant"]["id"]
    membership_id = program["memberships"][0]["id"]
    # 5000 gross: discount 1000, net 4000, commission 480, share 120.
    redemption = X.verified_redemption(
        program["offer"]["id"], membership_id, merchant_id, 5000
    )
    A.assert_line_economics(redemption, 5000, 1000, 4000, 480, 120, 360)

    X.set_clock("2026-08-02T00:00:00Z")
    dispute = X.file_dispute(redemption["id"], membership_id)
    A.assert_fields(dispute, {
        "status": "OPEN",
        "redemption_id": redemption["id"],
        "raised_by_membership_id": membership_id,
        "merchant_id": merchant_id,
        "info_request_count": 0,
        "default_judged": False,
    }, "dispute")
    A.assert_nulls(dispute, ["response_note", "remedy_offered_cents",
                            "outcome_credit_cents", "resolved_at"], "dispute")
    # 2026-08-02T00:00:00Z + 120 hours = five days later.
    A.assert_iso_equals(dispute["response_deadline_at"], "2026-08-07T00:00:00Z",
                        "response_deadline_at")
    assert X.get_redemption(redemption["id"])["fulfillment_status"] == "DISPUTED"

    # At the deadline instant the clock is no longer strictly before it.
    X.set_clock("2026-08-07T00:00:00Z")
    refused = api_client.respond_dispute(
        dispute["id"], F.dispute_response_payload(), make_merchant_headers(merchant_id)
    )
    validate_error(refused, ApiErrorId.DISPUTE_DEADLINE_PASSED)

    sweep = X.run_epoch()
    A.assert_sweep_counts(sweep, expired_offer_count=0, completed_slot_count=0,
                          voided_redemption_count=0, stale_employer_count=0,
                          default_judged_dispute_count=1)
    judged = X.get_dispute(dispute["id"])
    A.assert_fields(judged, {
        "status": "RESOLVED_MERCHANT_FAULT",
        "default_judged": True,
        "outcome_credit_cents": 0,
    }, "default-judged dispute")
    A.assert_iso_equals(judged["resolved_at"], "2026-08-07T00:00:00Z", "resolved_at")

    refunded = X.get_redemption(redemption["id"])
    A.assert_fields(refunded, {
        "verification_status": "VERIFIED",
        "fulfillment_status": "REFUNDED",
        "commission_amount_cents": 480,
    }, "refunded redemption")
    A.assert_iso_equals(refunded["refunded_at"], "2026-08-07T00:00:00Z", "refunded_at")

    merchant = X.get_merchant(merchant_id)
    A.assert_fields(merchant, {
        "fault_event_count": 1,
        # One fault 0 days old: 20 * 1.0 = 20, below the 40-point threshold.
        "fulfillment_failure_score": 20,
        "status": "ACTIVE",
        # 480 accrual less the 480 reversal.
        "accrued_commission_payable_cents": 0,
    }, "merchant after default judgment")

    A.assert_sweep_idle(X.run_epoch())


def test_screening_and_audit_variants_score_the_same_redemption_differently():
    """The 24-hour PENDING-only window and the 168-hour window disagree by design.

    PRD: "The prior count is the number of the **same membership's other** redemptions — the redemption being scored is always excluded — whose `created_at` falls at or after the instant one velocity window before the logical clock and strictly before the clock, and whose `verification_status` lies in the variant's status set."

    Design: Corner/calculations/screening_and_audit_variants_score_the_same_redemption_differently
    """
    X.set_clock(CLOCK_EPOCH)
    program = X.live_program(
        records=[F.eligibility_record(
            "E-001", employment_status=EmploymentStatus.LEAVE,
            eligibility_valid_from="2026-06-01T00:00:00Z",
        )],
        offer_overrides={"per_member_limit": 5, "min_spend_cents": 1000},
    )
    offer_id = program["offer"]["id"]
    merchant_id = program["merchant"]["id"]
    membership_id = program["memberships"][0]["id"]
    assert program["memberships"][0]["employment_status"] == "LEAVE"

    # Employment 15 (LEAVE), no priors, seasoning 0 (valid_from + 7d is past).
    first = X.create_redemption(offer_id, membership_id, intended_gross_amount_cents=5000)
    assert first["screening_risk_score"] == 15
    assert first["audit_risk_score"] is None
    # AUDIT adds amount floor(5000/10000) = 0 and merchant risk 0; still 15.
    first_verified = X.verify_redemption(first, merchant_id, 5000)
    assert first_verified["audit_risk_score"] == 15
    assert first_verified["screening_risk_score"] == 15

    # The prior must be created strictly before the clock, and the first
    # redemption was created at this very instant, so it counts for neither.
    second = X.create_redemption(offer_id, membership_id, intended_gross_amount_cents=5000)
    assert second["screening_risk_score"] == 15
    second_verified = X.verify_redemption(second, merchant_id, 5000)
    assert second_verified["audit_risk_score"] == 15

    X.set_clock("2026-08-03T00:00:00Z")
    # SCREENING looks back 24 hours: nothing was created on 08-02.
    third = X.create_redemption(offer_id, membership_id, intended_gross_amount_cents=5000)
    assert third["screening_risk_score"] == 15
    assert third["verification_status"] == "PENDING"

    X.set_clock("2026-08-03T12:00:00Z")
    # SCREENING: the PENDING third redemption is in the 24-hour window -> 15 + 8.
    fourth = X.create_redemption(offer_id, membership_id,
                                 intended_gross_amount_cents=100000)
    assert fourth["screening_risk_score"] == 23
    # AUDIT: 168-hour window catches the two VERIFIED plus the one PENDING
    # prior = 24 points, employment 15, amount floor(100000/10000) = 10 -> 49.
    fourth_verified = X.verify_redemption(fourth, merchant_id, 100000)
    A.assert_fields(fourth_verified, {
        "audit_risk_score": 49,
        "verification_status": "VERIFIED",
        "risk_block_reason": None,
        # The frozen SCREENING figure is never rewritten by verification.
        "screening_risk_score": 23,
    }, "fourth redemption")
    assert X.get_redemption(fourth["id"])["screening_risk_score"] == 23


def test_fault_score_decays_across_the_thirty_day_step_before_reinstatement():
    """Two faults score 40 and suspend; at 35 and 26 days old they score 30.

    PRD: "The factor is 1.0 when the age is 30 days or less, 0.5 when the age is between 31 and 90 days inclusive, and 0.0 when the age is 91 days or more."

    Design: Corner/calculations/fault_score_decays_across_the_thirty_day_step_before_reinstatement
    """
    X.set_clock(CLOCK_EPOCH)
    program = X.live_program(record_count=2, revenue_share_enabled=True)
    merchant_id = program["merchant"]["id"]
    offer_id = program["offer"]["id"]
    first_member, second_member = program["memberships"][0], program["memberships"][1]

    first = X.verified_redemption(offer_id, first_member["id"], merchant_id, 5000)
    first_dispute = X.file_dispute(first["id"], first_member["id"])
    resolved = X.resolve_dispute(first_dispute["id"], DisputeOutcome.MERCHANT_FAULT,
                                outcome_credit_cents=0)
    assert resolved["status"] == "RESOLVED_MERCHANT_FAULT"
    after_first = X.get_merchant(merchant_id)
    A.assert_fields(after_first, {
        "fault_event_count": 1,
        "fulfillment_failure_score": 20,  # 20 * 1.0, age 0 days
        "status": "ACTIVE",
        "suspended_at": None,
    }, "merchant after one fault")

    X.set_clock("2026-08-10T00:00:00Z")
    second = X.verified_redemption(offer_id, second_member["id"], merchant_id, 5000)
    # AUDIT merchant-risk term: the partner's score of 20 is at the 20 threshold.
    assert second["audit_risk_score"] == 10
    second_dispute = X.file_dispute(second["id"], second_member["id"])
    X.resolve_dispute(second_dispute["id"], DisputeOutcome.MERCHANT_FAULT,
                      outcome_credit_cents=0)

    suspended = X.get_merchant(merchant_id)
    A.assert_fields(suspended, {
        "fault_event_count": 2,
        # 20 * 1.0 (9 days) + 20 * 1.0 (0 days) = 40, which is the threshold.
        "fulfillment_failure_score": 40,
        "status": "SUSPENDED",
    }, "merchant after two faults")
    A.assert_iso_equals(suspended["suspended_at"], "2026-08-10T00:00:00Z", "suspended_at")
    paused = X.get_offer(offer_id, merchant_id=merchant_id)
    A.assert_fields(paused, {"status": "PAUSED", "paused_reason": "MERCHANT_SUSPENDED"},
                    "offer of a suspended partner")

    too_early = api_client.reinstate_merchant(merchant_id, make_admin_headers())
    validate_error(too_early, ApiErrorId.MERCHANT_SCORE_NOT_DECAYED)

    X.set_clock("2026-09-05T00:00:00Z")
    decayed = X.get_merchant(merchant_id)
    # The first fault is 35 days old (0.5 -> 10), the second 26 days (1.0 -> 20).
    A.assert_fields(decayed, {"fulfillment_failure_score": 30, "status": "SUSPENDED"},
                    "merchant read after decay")

    reinstated = validate_success(
        api_client.reinstate_merchant(merchant_id, make_admin_headers())
    )
    A.assert_fields(reinstated, {
        "status": "ACTIVE",
        "suspended_at": None,
        "fault_event_count": 2,
        "fulfillment_failure_score": 30,
    }, "reinstated merchant")
    # Reinstatement is not a rollback: the paused offer stays paused.
    A.assert_fields(X.get_offer(offer_id, merchant_id=merchant_id),
                    {"status": "PAUSED", "paused_reason": "MERCHANT_SUSPENDED"},
                    "offer after reinstatement")


def test_program_posture_replays_the_five_row_projection_table():
    """One employer walks every row of the posture table, FROZEN included.

    PRD: "If `storefront_status` is `SUSPENDED`, the posture is `FROZEN` — a suspension dominates even a perfectly healthy `SYNCED` integration."

    Design: Corner/calculations/program_posture_replays_the_five_row_projection_table
    """
    X.set_clock(CLOCK_EPOCH)
    employer = X.create_employer(employee_count_declared=400)
    A.assert_fields(employer, {
        "integration_status": "NOT_CONFIGURED",
        "storefront_status": "DRAFT",
        "program_posture": "SETUP",
        "eligible_headcount": 0,
        "last_sync_at": None,
    }, "new employer")

    branded = X.brand_storefront(employer["id"],
                                 featured_categories=[PerkCategory.DINING])
    A.assert_fields(branded, {"storefront_status": "BRANDED",
                              "program_posture": "SETUP"}, "branded employer")

    published = X.publish_storefront(employer["id"])
    # Row 5: PUBLISHED with an unconfigured feed is still SETUP.
    A.assert_fields(published, {"storefront_status": "PUBLISHED",
                                "integration_status": "NOT_CONFIGURED",
                                "program_posture": "SETUP"}, "published employer")

    batch = X.load_eligibility_file(employer["id"],
                                   records=F.eligibility_records(2))
    A.assert_fields(X.get_employer(employer["id"]),
                    {"integration_status": "FILE_RECEIVED",
                     "program_posture": "SETUP"}, "employer with a loaded batch")
    X.validate_eligibility_file(batch["id"], employer["id"])
    A.assert_fields(X.get_employer(employer["id"]),
                    {"integration_status": "VALIDATED",
                     "program_posture": "SETUP"}, "employer with a validated batch")

    X.apply_eligibility_file(batch["id"], employer["id"])
    live = X.get_employer(employer["id"])
    # Row 3: PUBLISHED plus SYNCED is the only LIVE combination.
    A.assert_fields(live, {"integration_status": "SYNCED",
                           "storefront_status": "PUBLISHED",
                           "program_posture": "LIVE",
                           "eligible_headcount": 2}, "synced employer")
    A.assert_iso_equals(live["last_sync_at"], CLOCK_EPOCH, "last_sync_at")

    frozen = X.suspend_storefront(employer["id"], suspension_reason="Audit hold")
    # Row 1 wins over row 3 even though the feed is still SYNCED.
    A.assert_fields(frozen, {"storefront_status": "SUSPENDED",
                             "integration_status": "SYNCED",
                             "program_posture": "FROZEN",
                             "suspension_reason": "Audit hold"}, "frozen employer")

    republished = X.publish_storefront(employer["id"])
    A.assert_fields(republished, {"storefront_status": "PUBLISHED",
                                  "program_posture": "LIVE",
                                  "suspension_reason": None}, "republished employer")

    # last_sync_at plus 45 days is 2026-09-15, so the sweep bites on 09-16.
    X.set_clock("2026-09-16T00:00:00Z")
    A.assert_sweep_counts(X.run_epoch(), stale_employer_count=1)
    stale = X.get_employer(employer["id"])
    # Row 4: PUBLISHED plus STALE is RESTRICTED.
    A.assert_fields(stale, {"integration_status": "STALE",
                            "storefront_status": "PUBLISHED",
                            "program_posture": "RESTRICTED"}, "stale employer")


# ── endpoints ───────────────────────────────────────────────────────────────


def test_merchant_patch_replaces_the_region_list_and_leaves_the_rest_alone():
    """PATCH rewrites contact_email and region_codes wholesale, nothing else.

    PRD: "Later on, the same `PartnerManager` may amend a partner's `contact_email` or `region_codes`; shrinking the footprint is allowed and never retro-invalidates agreements or offers that were created while the wider footprint was in force."

    Design: Corner/endpoints/merchant_crud_creates_reads_lists_and_patches_the_two_mutable_fields
    """
    X.set_clock(CLOCK_EPOCH)
    merchant = X.create_merchant(region_codes=[RegionCode.CA, RegionCode.TX])
    A.assert_merchant_shape(merchant)
    A.assert_fields(merchant, {
        "legal_name": "Bistro Uno",
        "contact_email": "deals@bistrouno.example",
        "primary_category": "DINING",
        "region_codes": ["CA", "TX"],
        "status": "PROSPECT",
        "fault_event_count": 0,
        "fulfillment_failure_score": 0,
        "accrued_commission_payable_cents": 0,
        "active_agreement_count": 0,
        "suspended_at": None,
        "version": 1,
    }, "new merchant")
    other = X.create_merchant(
        legal_name="Zen Spa", contact_email="hello@zenspa.example",
        primary_category=PerkCategory.WELLNESS, region_codes=[RegionCode.NY],
    )

    assert X.get_merchant(merchant["id"])["region_codes"] == ["CA", "TX"]

    rows, meta = validate_paginated(api_client.list_merchants(
        make_partner_manager_headers(),
        params={"primary_category": "DINING", "status": "PROSPECT"},
    ))
    A.assert_pagination_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [merchant["id"]]
    # `region_code` matches on membership of the partner's list, not equality.
    tx_rows, tx_meta = validate_paginated(api_client.list_merchants(
        make_partner_manager_headers(), params={"region_code": "TX"},
    ))
    A.assert_pagination_meta(tx_meta, total_count=1)
    assert tx_rows[0]["id"] == merchant["id"]
    assert other["id"] not in [row["id"] for row in tx_rows]

    patched = validate_success(api_client.update_merchant(
        merchant["id"],
        F.merchant_update_payload(contact_email="ops@bistrouno.example",
                                  region_codes=[RegionCode.CA, RegionCode.NY]),
        make_partner_manager_headers(),
    ))
    A.assert_fields(patched, {
        "contact_email": "ops@bistrouno.example",
        # The list is replaced wholesale rather than merged, so TX is gone.
        "region_codes": ["CA", "NY"],
        "legal_name": "Bistro Uno",
        "primary_category": "DINING",
        "status": "PROSPECT",
        "version": 2,
    }, "patched merchant")

    self_read = X.get_merchant(merchant["id"], make_merchant_headers(merchant["id"]))
    A.assert_fields(self_read, {
        "contact_email": "ops@bistrouno.example",
        "region_codes": ["CA", "NY"],
        "version": 2,
    }, "merchant self-read")


def test_offer_resume_is_refused_once_the_window_has_closed():
    """Resume works mid-window and is refused at window_end, which then expires.

    PRD: "Only the owning `Merchant` may resume, moving the offer `PAUSED → ACTIVE` and clearing `paused_reason`, and resumption is the most heavily guarded transition on the offer: it requires the partner's `status` to be `ACTIVE`, the governing agreement's `status` to be `ACTIVE`, and the offer's `window_end` to be strictly after the logical clock."

    Design: Corner/endpoints/offer_resume_is_conditional_on_the_window_still_being_open
    """
    X.set_clock(CLOCK_EPOCH)
    partner = X.active_partner()
    merchant_id = partner["merchant"]["id"]
    offer = X.approved_offer(partner["agreement"]["id"], merchant_id,
                             window_end="2026-09-01T00:00:00Z")
    A.assert_fields(offer, {"status": "ACTIVE", "paused_reason": None,
                            "expired_at": None}, "approved offer")

    X.set_clock("2026-08-05T00:00:00Z")
    paused = X.pause_offer(offer["id"], merchant_id,
                          paused_reason="Kitchen refurbishment")
    A.assert_fields(paused, {"status": "PAUSED",
                             "paused_reason": "Kitchen refurbishment"}, "paused offer")

    X.set_clock("2026-08-06T00:00:00Z")
    resumed = validate_success(
        api_client.resume_offer(offer["id"], make_merchant_headers(merchant_id))
    )
    A.assert_fields(resumed, {"status": "ACTIVE", "paused_reason": None},
                    "resumed offer")

    X.pause_offer(offer["id"], merchant_id, paused_reason="Second refurbishment")
    # window_end must be strictly after the clock, and here it equals it.
    X.set_clock("2026-09-01T00:00:00Z")
    refused = api_client.resume_offer(offer["id"], make_merchant_headers(merchant_id))
    validate_error(refused, ApiErrorId.OFFER_INVALID_STATE)
    A.assert_fields(X.get_offer(offer["id"], merchant_id=merchant_id),
                    {"status": "PAUSED", "paused_reason": "Second refurbishment"},
                    "offer after the refused resume")

    A.assert_sweep_counts(X.run_epoch(), expired_offer_count=1)
    expired = X.get_offer(offer["id"], merchant_id=merchant_id)
    assert expired["status"] == "EXPIRED"
    A.assert_iso_equals(expired["expired_at"], "2026-09-01T00:00:00Z", "expired_at")


def test_engagement_report_suppresses_the_thin_category_row_but_still_totals_it():
    """A 2-redeemer WELLNESS row is withheld while the totals still count it.

    PRD: "When a row's cohort metric is strictly below the applicable floor, the row is suppressed: `suppressed` is true and `redemption_count`, `discount_amount_cents` and the cohort metric are all reported as null."

    Design: Corner/endpoints/engagement_report_suppresses_the_thin_category_row_but_still_totals_it
    """
    X.set_clock(CLOCK_EPOCH)
    dining = X.active_partner()
    wellness = X.active_partner(
        merchant_overrides={"legal_name": "Zen Spa",
                            "contact_email": "hello@zenspa.example",
                            "primary_category": PerkCategory.WELLNESS},
        category=PerkCategory.WELLNESS,
    )
    program = X.live_employer(
        record_count=3, privacy_min_cohort_size=3, revenue_share_enabled=True,
        featured_categories=["DINING", "WELLNESS"],
    )
    employer_id = program["employer"]["id"]
    members = program["memberships"]
    dining_offer = X.approved_offer(dining["agreement"]["id"],
                                   dining["merchant"]["id"], min_spend_cents=1000)
    wellness_offer = X.approved_offer(wellness["agreement"]["id"],
                                     wellness["merchant"]["id"],
                                     title="Sixty minute massage",
                                     min_spend_cents=1000)
    assert dining_offer["category"] == "DINING"
    assert wellness_offer["category"] == "WELLNESS"

    X.set_clock("2026-08-10T00:00:00Z")
    for member in members:
        # 5000 at 2,000 bps: 1000 off each, three distinct redeemers.
        X.verified_redemption(dining_offer["id"], member["id"],
                             dining["merchant"]["id"], 5000)
    for member in members[:2]:
        # 4000 at 2,000 bps: 800 off each, only two distinct redeemers.
        X.verified_redemption(wellness_offer["id"], member["id"],
                             wellness["merchant"]["id"], 4000,
                             intended_gross_amount_cents=4000)

    report = validate_success(api_client.get_engagement_report(
        employer_id, make_employer_admin_headers(employer_id), params=F.report_params()
    ))
    A.assert_fields(report, {
        "employer_id": employer_id,
        "privacy_min_cohort_size": 3,
        "suppressed_category_count": 1,
        # Totals span every redemption in the window, suppressed rows included.
        "total_redemption_count": 5,
        "total_discount_amount_cents": 4600,  # 3 * 1000 + 2 * 800
        "total_distinct_redeemer_count": 3,
    }, "engagement report")

    rows = report["category_rows"]
    assert [row["category"] for row in rows] == ["DINING", "WELLNESS"]
    A.assert_ordered_by(rows, "category")
    A.assert_row_visible(A.category_row(report, "DINING"), "distinct_redeemer_count",
                        redemption_count=3, discount_amount_cents=3000, cohort_value=3)
    # 2 distinct redeemers is strictly below the floor of 3.
    A.assert_row_suppressed(A.category_row(report, "WELLNESS"),
                            "distinct_redeemer_count")

    body = json.dumps(report)
    assert "Northwind Logistics" not in body, "the report must not name the employer"
    for member in members:
        assert member["id"] not in body, "the report must not expose a membership id"
        assert member["external_employee_ref"] not in body


def test_placement_slot_prices_itself_from_the_agreement_and_the_employer():
    """A 2-day STANDARD run on a 2-person storefront costs exactly the base.

    PRD: "The inputs are the governing agreement's `placement_fee_base_cents` (a per-day base rate), the slot's own run bounds, and the employer's `eligible_headcount` read at the moment of reservation."

    Design: Corner/endpoints/placement_slot_links_an_offer_to_an_employer_and_prices_itself_from_both
    """
    X.set_clock(CLOCK_EPOCH)
    partner = X.active_partner(placement_fee_base_cents=36000)
    merchant_id = partner["merchant"]["id"]
    program = X.live_employer(record_count=2, employee_count_declared=900)
    employer_id = program["employer"]["id"]
    assert program["employer"]["eligible_headcount"] == 2
    offer = X.approved_offer(partner["agreement"]["id"], merchant_id)

    # Band 2 of §2.9: a referenced row that does not exist loses to nothing.
    missing = api_client.reserve_placement_slot(
        offer["id"],
        F.slot_payload(offer["version"], NON_EXISTENT_UUID,
                       placement_tier=PlacementTier.STANDARD,
                       slot_window_start="2026-09-01T00:00:00Z",
                       slot_window_end="2026-09-03T00:00:00Z"),
        make_merchant_headers(merchant_id),
    )
    validate_error(missing, ApiErrorId.EMPLOYER_NOT_FOUND)

    slot = X.reserve_slot(offer, employer_id, merchant_id,
                         placement_tier=PlacementTier.STANDARD,
                         slot_window_start="2026-09-01T00:00:00Z",
                         slot_window_end="2026-09-03T00:00:00Z")
    A.assert_placement_slot_shape(slot)
    A.assert_fields(slot, {
        "offer_id": offer["id"],
        "employer_id": employer_id,
        "placement_tier": "STANDARD",
        "status": "RESERVED",
        "confirmed_at": None,
        "released_at": None,
        "release_reason": None,
    }, "reserved slot")
    # 2 days * 36,000 = 72,000 base; headcount 2 is in the "3 or fewer" tier so
    # the surcharge is 0 bps; a gross of 72,000 is below 100,000 so the volume
    # discount is 0 bps; the fee is therefore the bare base.
    A.assert_placement_fee_breakdown(slot, 2, 72000, 0, 0, 72000, 0, 0, 72000)
    # Nothing is billed until a PartnerManager confirms the slot.
    assert X.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 0

    by_employer, employer_meta = validate_paginated(api_client.list_placement_slots(
        make_partner_manager_headers(),
        params={"employer_id": employer_id, "placement_tier": "STANDARD"},
    ))
    A.assert_pagination_meta(employer_meta, total_count=1)
    assert by_employer[0]["id"] == slot["id"]
    by_offer, offer_meta = validate_paginated(api_client.list_placement_slots(
        make_partner_manager_headers(),
        params={"offer_id": offer["id"], "status": "RESERVED"},
    ))
    A.assert_pagination_meta(offer_meta, total_count=1)
    assert by_offer[0]["id"] == slot["id"]


def test_eligibility_batch_skips_the_bad_record_and_tallies_the_second_pass():
    """A 500-bps batch validates, and the next batch suspends the absent rows.

    PRD: "Any membership of this employer whose `external_employee_ref` is **absent** from the batch and whose `status` is `ELIGIBLE` is moved `ELIGIBLE → SUSPENDED`; conversely a membership currently `SUSPENDED` whose `external_employee_ref` reappears in a batch with `employment_status` of `ACTIVE` or `LEAVE` is restored `SUSPENDED → ELIGIBLE`."

    Design: Corner/endpoints/eligibility_batch_skips_the_bad_record_and_reports_three_counters_on_the_second_pass
    """
    X.set_clock(CLOCK_EPOCH)
    employer = X.create_employer()
    employer_id = employer["id"]

    first_records = [F.eligibility_record(f"E-{index:03d}") for index in range(1, 20)]
    # E-020 carries a region outside the five-region set: one invalid record.
    first_records.append(F.eligibility_record("E-020", region_code="ZZ"))
    first = X.load_eligibility_file(employer_id, records=first_records)
    A.assert_fields(first, {
        "status": "RECEIVED",
        "record_count": 20,
        "invalid_record_count": 1,
        "valid_record_count": 19,
        "created_membership_count": 0,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
    }, "first batch")
    # 1 * 10,000 / 20 = exactly 500 bps, and the boundary validates.
    assert X.validate_eligibility_file(first["id"], employer_id)["status"] == "VALIDATED"
    applied = X.apply_eligibility_file(first["id"], employer_id)
    A.assert_fields(applied, {
        "status": "APPLIED",
        "created_membership_count": 19,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
    }, "first batch applied")
    A.assert_iso_equals(applied["applied_at"], CLOCK_EPOCH, "applied_at")
    A.assert_fields(X.get_employer(employer_id), {
        "integration_status": "SYNCED",
        "eligible_headcount": 19,
    }, "employer after the first batch")

    X.set_clock("2026-08-15T00:00:00Z")
    second_records = [F.eligibility_record(f"E-{index:03d}") for index in range(1, 9)]
    second_records[4] = F.eligibility_record(
        "E-005", employment_status=EmploymentStatus.TERMINATED
    )
    second_records.append(F.eligibility_record("E-021"))
    second_records.append(F.eligibility_record("E-022"))
    second = X.load_eligibility_file(employer_id, records=second_records,
                                    checksum="sha256:feed-0002")
    A.assert_fields(second, {"record_count": 10, "invalid_record_count": 0,
                             "valid_record_count": 10}, "second batch")
    assert X.get_employer(employer_id)["integration_status"] == "FILE_RECEIVED"
    X.validate_eligibility_file(second["id"], employer_id)
    second_applied = X.apply_eligibility_file(second["id"], employer_id)
    A.assert_fields(second_applied, {
        "status": "APPLIED",
        "created_membership_count": 2,   # E-021 and E-022
        "updated_membership_count": 8,   # E-001 through E-008
        "suspended_membership_count": 11,  # E-009 through E-019
    }, "second batch applied")

    # 7 rewritten ACTIVE rows plus the 2 new rows; E-005 is now TERMINATED and
    # E-009 through E-019 are SUSPENDED, so neither group counts.
    A.assert_fields(X.get_employer(employer_id), {
        "eligible_headcount": 9,
        "integration_status": "SYNCED",
    }, "employer after the second batch")

    suspended_rows, suspended_meta = validate_paginated(api_client.list_memberships(
        make_employer_admin_headers(employer_id),
        params={"employer_id": employer_id, "status": "SUSPENDED", "limit": 100},
    ))
    A.assert_pagination_meta(suspended_meta, total_count=11)
    assert len(suspended_rows) == 11
    roster, roster_meta = validate_paginated(api_client.list_memberships(
        make_employer_admin_headers(employer_id),
        params={"employer_id": employer_id, "limit": 100},
    ))
    # The invalid record never became a membership, so the roster is 19 + 2.
    A.assert_pagination_meta(roster_meta, total_count=21)
    assert len(roster) == 21


# ── consistency model ───────────────────────────────────────────────────────


def test_every_derived_field_is_visible_in_the_response_that_changed_it():
    """Apply and publish report the recomputed headcount and posture inline.

    PRD: "When an operation changes a row whose state other rows depend on, every dependent row is brought into line inside the same request, and each row the server touches has its own `updated_at` refreshed and its own `version` incremented by 1 — including rows the client never named."

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response_that_changed_it
    """
    X.set_clock(CLOCK_EPOCH)
    partner = X.active_partner()
    merchant_id = partner["merchant"]["id"]
    offer = X.approved_offer(partner["agreement"]["id"], merchant_id,
                            inventory_limit=5, min_spend_cents=1000)
    A.assert_fields(offer, {"inventory_reserved": 0, "inventory_redeemed": 0,
                            "sold_out": False}, "approved offer")

    employer = X.create_employer(revenue_share_enabled=True, privacy_min_cohort_size=3)
    employer_id = employer["id"]
    A.assert_version_is(employer, 1, "new employer")
    X.brand_storefront(employer_id, featured_categories=["DINING"])
    batch = X.load_eligibility_file(
        employer_id,
        records=[F.eligibility_record("E-001"), F.eligibility_record("E-002")],
    )
    A.assert_version_is(batch, 1, "loaded batch")
    X.validate_eligibility_file(batch["id"], employer_id)

    applied = X.apply_eligibility_file(batch["id"], employer_id)
    # The applying response already carries every tally it computed.
    A.assert_fields(applied, {
        "status": "APPLIED",
        "created_membership_count": 2,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
        "version": 3,  # created, validated, applied
    }, "applied batch")
    A.assert_iso_equals(applied["applied_at"], CLOCK_EPOCH, "applied_at")

    synced = X.get_employer(employer_id)
    A.assert_fields(synced, {
        "integration_status": "SYNCED",
        "eligible_headcount": 2,
        # The storefront dimension moved not at all.
        "storefront_status": "BRANDED",
        "program_posture": "SETUP",
        "version": 5,  # created, branded, loaded, validated, applied
    }, "employer after applying")
    A.assert_iso_equals(synced["last_sync_at"], CLOCK_EPOCH, "last_sync_at")

    published = X.publish_storefront(employer_id)
    # The posture flip is visible in the very response that caused it.
    A.assert_fields(published, {
        "storefront_status": "PUBLISHED",
        "program_posture": "LIVE",
        "eligible_headcount": 2,
        "version": 6,
    }, "published employer")

    rows, meta = validate_paginated(api_client.list_memberships(
        make_employer_admin_headers(employer_id),
        params={"employer_id": employer_id, "limit": 100},
    ))
    A.assert_pagination_meta(meta, total_count=2)
    A.assert_membership_shape(rows[0])
    A.assert_fields(rows[0], {
        "employer_id": employer_id,
        "external_employee_ref": "E-001",
        "status": "ELIGIBLE",
        "employment_status": "ACTIVE",
        "source_file_id": batch["id"],
        "version": 1,
    }, "first membership")

    redemption = X.create_redemption(offer["id"], rows[0]["id"],
                                    intended_gross_amount_cents=5000)
    A.assert_redemption_shape(redemption)
    A.assert_fields(redemption, {
        "employer_id": employer_id,
        "merchant_id": merchant_id,
        "offer_id": offer["id"],
        "membership_id": rows[0]["id"],
        "verification_status": "PENDING",
        "fulfillment_status": "AWAITING",
        "statement_id": None,
        "gross_amount_cents": None,
    }, "new redemption")
    # created_at plus 72 hours, read straight out of the creation response.
    A.assert_iso_equals(redemption["verification_expires_at"],
                        "2026-08-04T00:00:00Z", "verification_expires_at")

    reserved = X.get_offer(offer["id"], merchant_id=merchant_id)
    A.assert_fields(reserved, {
        "inventory_reserved": 1,
        "inventory_redeemed": 0,
        "sold_out": False,
    }, "offer after one reservation")
