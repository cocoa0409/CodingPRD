"""Money and date arithmetic of the utility service line warranty programme.

Every calculation here is an integer-cent or whole-day computation whose exact
result the PRD states: the renewal notice tiers and their rounded percentage, the
two cancellation settlement variants, the mail-drop suppression and capacity
partition, the contractor selection score and its tie-break, the benefit
waterfall against a single pool, the regulator response window and its escalation
grace, the eligibility ladder, and the response deadline that is stamped once.

Rounding is asserted exactly where the PRD puts it: half up for the proration
shares, for the bill-insert credit and for the two derived two-decimal numbers,
and floored for capacity headroom, the rate score and ``days_overdue``. Every
test pins the logical clock inside the window its calculation reads.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_DENIAL_REASON_UNSUPPORTED,
    ERR_INSUFFICIENT_RENEWAL_NOTICE,
    ERR_NO_ELIGIBLE_CONTRACTOR,
    ERR_PER_OCCURRENCE_CAP_EXHAUSTED,
    ERR_RATE_FILING_REQUIRED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_date_only,
    assert_drop_counts_agree,
    assert_drop_summary_shape,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_instant_format,
    assert_ledger_amounts,
    assert_list_envelope,
    assert_nightly_names,
    assert_nulls,
    assert_refused,
    entries_of_type,
)
from test_helpers.constants import (
    CANCELLATION_FEE_CENTS,
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    COVERAGE_EFFECTIVE_AT,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    REGULATORY_AFFAIRS,
)

# ── Private helpers ──
#
# A renewal notice, unlike the nine record-minting endpoints, settles a policy
# that already exists, so it answers 200 rather than 201. These two helpers post
# it directly so that the accepted and the refused arm of a tier boundary can be
# asserted from the same call site.


def _renewal_notice_response(api, enrollment_id, new_price_cents,
                             renewal_effective_date, expected_enrollment_version):
    payload = factories.renewal_notice_payload(
        new_price_cents, renewal_effective_date, expected_enrollment_version
    )
    return api.create_renewal_notice(enrollment_id, payload, BILLING_OPS)


def _issue_renewal_notice(api, enrollment_id, new_price_cents,
                          renewal_effective_date, expected_enrollment_version):
    response = _renewal_notice_response(
        api, enrollment_id, new_price_cents, renewal_effective_date,
        expected_enrollment_version,
    )
    return validate_success(response, 200)


def _active_policy(api, product_overrides=None, partner_overrides=None,
                   premises_overrides=None, **enrollment_overrides):
    """A partner, product, address and one policy whose coverage has activated."""
    world = fixtures.partner_product_premises(
        api, partner_overrides, product_overrides, premises_overrides
    )
    world = fixtures.enrolled_premises(api, world, **enrollment_overrides)
    return fixtures.activate_coverage(api, world)


class TestRenewalNoticePricing:
    """The percentage change, its rounding, the notice tiers and the filing gate."""

    def test_ten_percent_change_needs_thirty_days_and_the_boundary_is_inclusive(self, api):
        """A change of exactly 10.00 percent sits in the 30-day tier, and a lead
        time of exactly 30 days is compliant while 29 days is not.

        PRD: "With a `renewal_effective_date` of 2027-08-05, a notice issued while the clock reads 2027-07-06 offers exactly 30 days and is accepted; issued one day later, on 2027-07-07, it offers 29 days and is refused with `ERR_INSUFFICIENT_RENEWAL_NOTICE`."

        Design: Corner/calculations/renewal_notice_tier_boundary_at_exactly_ten_percent
        """
        world = fixtures.partner_product_premises(
            api, product_overrides={"monthly_price_cents": 1000}
        )
        world = fixtures.enrolled_premises(api, world, prepaid_amount_cents=None)
        premises_b = fixtures.create_unique_premises(api, world["partner_id"])
        enrollment_b = fixtures.create_enrollment(
            api, premises_b["id"], world["product_id"], premises_b["version"],
            prepaid_amount_cents=None,
        )
        world = fixtures.activate_coverage(api, world)
        enrollment_b = fixtures.refresh_enrollment(api, enrollment_b["id"])
        assert world["enrollment"]["monthly_price_cents"] == 1000
        assert world["enrollment"]["coverage_status"] == "ACTIVE"
        assert enrollment_b["coverage_status"] == "ACTIVE"

        # Exactly 30 days of lead time on a 10.00 percent change: accepted.
        fixtures.set_clock(api, "2027-07-06T00:00:00.000Z")
        accepted = _issue_renewal_notice(
            api, world["enrollment_id"], 1100, "2027-08-05",
            world["enrollment_version"],
        )
        assert_fields(accepted, {
            "renewal_price_cents": 1100,
            "renewal_effective_date": "2027-08-05",
            "renewal_notice_status": "SENT",
            "monthly_price_cents": 1000,
            "version": world["enrollment_version"] + 1,
        })
        assert_instant(accepted["renewal_notice_sent_at"], "2027-07-06T00:00:00.000Z",
                       "renewal_notice_sent_at")
        assert_instant_format(accepted["renewal_notice_sent_at"], "renewal_notice_sent_at")
        assert_date_only(accepted["renewal_effective_date"], "renewal_effective_date")

        # One day later the very same change offers only 29 days: refused.
        fixtures.set_clock(api, "2027-07-07T00:00:00.000Z")
        refused = _renewal_notice_response(
            api, enrollment_b["id"], 1100, "2027-08-05", enrollment_b["version"]
        )
        assert_refused(refused, ERR_INSUFFICIENT_RENEWAL_NOTICE, 422)

        untouched = fixtures.refresh_enrollment(api, enrollment_b["id"])
        assert untouched["renewal_notice_status"] == "NONE"
        assert untouched.get("renewal_price_cents") is None
        assert untouched["version"] == enrollment_b["version"]

    def test_rate_filing_gate_refuses_thirty_percent_even_with_sixty_days_notice(self, api):
        """Above 25 percent a filing partner cannot notice the increase at all,
        while a change of exactly 25.00 percent clears the same gate.

        PRD: "When the partner's `rate_filing_required` is true and the percentage change exceeds 25 percent, the notice is refused with `ERR_RATE_FILING_REQUIRED` **even when the lead time would have satisfied the 60-day tier** — the state filing that such an increase demands is outside this system, so the increase simply cannot be noticed here."

        Design: Corner/calculations/rate_filing_gate_rejects_thirty_percent_even_with_sixty_days_notice
        """
        world = _active_policy(
            api,
            product_overrides={"monthly_price_cents": 1000},
            partner_overrides={"rate_filing_required": True},
            prepaid_amount_cents=None,
        )
        # 2027-06-06 to 2027-08-05 is 60 whole days, which satisfies every tier.
        fixtures.set_clock(api, "2027-06-06T00:00:00.000Z")

        refused = _renewal_notice_response(
            api, world["enrollment_id"], 1300, "2027-08-05", world["enrollment_version"]
        )
        assert_refused(refused, ERR_RATE_FILING_REQUIRED, 422)
        untouched = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert untouched["renewal_notice_status"] == "NONE"
        assert untouched["version"] == world["enrollment_version"]

        # 1250 is a change of exactly 25.00 percent, which does not exceed 25.
        accepted = _issue_renewal_notice(
            api, world["enrollment_id"], 1250, "2027-08-05", world["enrollment_version"]
        )
        assert_fields(accepted, {
            "renewal_price_cents": 1250,
            "renewal_notice_status": "SENT",
            "version": world["enrollment_version"] + 1,
        })

    def test_price_change_percentage_is_rounded_before_the_tier_is_chosen(self, api):
        """2499 to 2749 rounds to 10.00 and lands in the 30-day tier; 2499 to
        2750 rounds to 10.04 and needs 45 days that the same clock cannot offer.

        PRD: "The percentage change is the new price minus the in-force `monthly_price_cents`, divided by that in-force price, multiplied by 100, and rounded half up to two fractional digits."

        Design: Corner/calculations/price_change_pct_is_rounded_before_the_tier_lookup
        """
        world = _active_policy(api, prepaid_amount_cents=None)
        assert world["enrollment"]["monthly_price_cents"] == 2499

        # 2027-07-06 to 2027-08-05 offers exactly 30 days of lead time.
        fixtures.set_clock(api, "2027-07-06T00:00:00.000Z")

        # 251/2499 is 10.0440...  percent, which rounds to 10.04 and needs 45 days.
        refused = _renewal_notice_response(
            api, world["enrollment_id"], 2750, "2027-08-05", world["enrollment_version"]
        )
        assert_refused(refused, ERR_INSUFFICIENT_RENEWAL_NOTICE, 422)
        untouched = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert untouched["renewal_notice_status"] == "NONE"
        assert untouched["version"] == world["enrollment_version"]

        # 250/2499 is 10.0040... percent, which rounds to 10.00 and needs 30.
        accepted = _issue_renewal_notice(
            api, world["enrollment_id"], 2749, "2027-08-05", world["enrollment_version"]
        )
        assert_fields(accepted, {
            "renewal_price_cents": 2749,
            "renewal_effective_date": "2027-08-05",
            "renewal_notice_status": "SENT",
            "version": world["enrollment_version"] + 1,
        })
        assert_instant(accepted["renewal_notice_sent_at"], "2027-07-06T00:00:00.000Z",
                       "renewal_notice_sent_at")


class TestCancellationSettlement:
    """The bill-insert settlement credits the remainder of the final month only."""

    def test_bill_insert_cancellation_credits_only_the_final_month_remainder(self, api):
        """A BILL_INSERT policy cancelled effective 2026-11-18 gives back 1083
        cents of November and nothing else, plus the 2500 free-look fee.

        PRD: "Under `BILL_INSERT` over the identical dates, the remaining days are 30 minus 18 plus 1, or 13, and `credit_cents` is 2499 multiplied by 13 divided by 30, rounded half up, or 1083."

        Design: Corner/calculations/bill_insert_cancellation_credits_only_the_final_month_remainder
        """
        world = fixtures.partner_product_premises(api)
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_bill_insert_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"]
        )
        assert_fields(enrollment, {
            "billing_mode": "BILL_INSERT",
            "monthly_price_cents": 2499,
            "prepaid_amount_cents": 0,
            "term_start": "2026-08-05",
            "term_end": "2027-08-05",
            "billing_status": "CURRENT",
            "coverage_status": "PENDING_WAITING_PERIOD",
        })
        assert_instant(enrollment["coverage_effective_at"], COVERAGE_EFFECTIVE_AT,
                       "coverage_effective_at")

        world["enrollment_id"] = enrollment["id"]
        world["enrollment_version"] = enrollment["version"]
        world = fixtures.activate_coverage(api, world)
        assert world["enrollment"]["coverage_status"] == "ACTIVE"
        version_before = world["enrollment"]["version"]

        # The clock sits on the cancellation date so that the final billed month
        # the credit is computed from is the month the clock is reading.
        fixtures.set_clock(api, "2026-11-18T00:00:00.000Z")
        settled = fixtures.cancel_enrollment(api, enrollment["id"], "2026-11-18")

        assert_fields(settled, {
            "cancellation_effective_date": "2026-11-18",
            "cancellation_reason": "CUSTOMER_REQUEST",
            "credit_cents": 1083,
            "refund_cents": 0,
            "cancellation_fee_cents": CANCELLATION_FEE_CENTS,
            "coverage_status": "CANCELLED",
            "billing_status": "CREDIT_ISSUED",
            "premium_refunded_cents": 1083,
            "premium_collected_cents": CANCELLATION_FEE_CENTS,
            "version": version_before + 1,
        })
        for field in ("credit_cents", "refund_cents", "cancellation_fee_cents",
                      "premium_refunded_cents", "premium_collected_cents"):
            assert_cents(settled[field], field)
        assert_date_only(settled["cancellation_effective_date"], "cancellation_effective_date")

        rows = fixtures.ledger_entries(api, enrollment_id=enrollment["id"])
        assert len(rows) == 2, f"expected exactly two cash rows, got {rows}"
        assert_ledger_amounts(entries_of_type(rows, "PRORATION_CREDIT"), [-1083])
        assert_ledger_amounts(entries_of_type(rows, "CANCELLATION_FEE"),
                              [CANCELLATION_FEE_CENTS])
        for row in rows:
            assert row["ledger_kind"] == "CASH", f"expected a cash row, got {row!r}"
            assert row["cap_year_start"] is None, "a cash row carries no cap_year_start"


class TestMailDropPartition:
    """Suppression precedence screens every address before capacity is applied."""

    def test_suppression_precedence_and_quantity_cap_partition_the_file(self, api):
        """Seven addresses split into two mailed, four rule suppressions taken in
        precedence order, and one capacity suppression beyond the approved two.

        PRD: "The order, highest precedence first, is: `DNM_REQUEST` when the address has `do_not_mail` set to true; then `BAD_ADDRESS` when its `address_status` is `BAD`; then `REGULATOR_COMPLAINT_OPEN` when its `regulator_hold` is true; then `ACTIVE_ENROLLMENT` when the address already holds an enrollment on this campaign's own product whose coverage is `PENDING_WAITING_PERIOD`, `ACTIVE` or `SUSPENDED_NONPAY`; then `OPEN_APPEAL` when any enrollment of the address carries a retention hold; then `CONTACT_FREQUENCY_CAP` when its `mail_count_current_year` has reached or exceeded the partner's `max_mailings_per_year`; and last `OWNERSHIP_INELIGIBLE` when the product's `required_owned_segment` is absent from the address's `owned_segments`."

        Design: Corner/calculations/suppression_precedence_and_quantity_cap_partition_the_partner_file
        """
        world = fixtures.active_partner_with_product(
            api, partner_overrides={"min_days_between_drops": 1, "max_mailings_per_year": 4}
        )
        partner_id = world["partner_id"]
        product_id = world["product_id"]

        enrolled = fixtures.create_premises(api, partner_id, street_address="10 Alder St")
        dnm_and_bad = fixtures.create_premises(
            api, partner_id, street_address="11 Alder St",
            do_not_mail=True, address_status="BAD",
        )
        bad_only = fixtures.create_premises(
            api, partner_id, street_address="12 Alder St", address_status="BAD"
        )
        wrong_segment = fixtures.create_premises(
            api, partner_id, street_address="13 Alder St",
            owned_segments=["WATER_METER_TO_HOME"],
        )
        survivor_one = fixtures.create_premises(api, partner_id, street_address="14 Alder St")
        survivor_two = fixtures.create_premises(api, partner_id, street_address="15 Alder St")
        capped = fixtures.create_premises(api, partner_id, street_address="16 Alder St")

        # A live policy on this campaign's own product is the ACTIVE_ENROLLMENT arm.
        fixtures.create_enrollment(
            api, enrolled["id"], product_id, enrolled["version"], prepaid_amount_cents=None
        )

        campaign = fixtures.create_campaign(
            api, partner_id, product_id, drop_date="2026-08-02", requested_quantity=10
        )
        fixtures.submit_campaign(api, campaign["id"])
        approved = fixtures.approve_campaign(api, campaign["id"], partner_id,
                                             approved_quantity=2)
        assert approved["approved_quantity"] == 2

        # The clock must have reached the drop date before the drop is legal.
        fixtures.set_clock(api, "2026-08-05T00:00:00.000Z")
        summary = fixtures.mail_drop(api, campaign["id"])

        assert_drop_summary_shape(summary)
        assert_drop_counts_agree(summary)
        assert_fields(summary, {
            "campaign_id": campaign["id"],
            "status": "MAILED",
            "mailed_count": 2,
            "suppressed_count": 5,
        })
        assert summary["mailed_premises_ids"] == [survivor_one["id"], survivor_two["id"]], (
            "the survivors are mailed in created_at ascending order until the "
            f"approved quantity is filled, got {summary['mailed_premises_ids']}"
        )
        assert summary["suppressed_by_reason"] == {
            "DNM_REQUEST": 1,
            "BAD_ADDRESS": 1,
            "ACTIVE_ENROLLMENT": 1,
            "OWNERSHIP_INELIGIBLE": 1,
            "QUANTITY_CAP": 1,
        }, (
            "every reason that fired appears once and reasons with a count of zero "
            f"are omitted, got {summary['suppressed_by_reason']}"
        )

        expected_traces = {
            dnm_and_bad["id"]: "DNM_REQUEST",
            bad_only["id"]: "BAD_ADDRESS",
            enrolled["id"]: "ACTIVE_ENROLLMENT",
            wrong_segment["id"]: "OWNERSHIP_INELIGIBLE",
            capped["id"]: "QUANTITY_CAP",
        }
        for premises_id, reason in expected_traces.items():
            row = validate_success(api.get_premises(premises_id, MARKETING_OPS))
            assert_fields(row, {
                "last_mail_decision": "SUPPRESSED",
                "last_mail_suppression_reason": reason,
            })
            assert row["last_mailed_campaign_id"] is None, (
                "a suppressed address was never mailed by this campaign"
            )

        for premises_id in (survivor_one["id"], survivor_two["id"]):
            row = validate_success(api.get_premises(premises_id, MARKETING_OPS))
            assert_fields(row, {
                "last_mail_decision": "MAILED",
                "last_mailed_campaign_id": campaign["id"],
                "mail_count_current_year": 1,
            })
            assert_nulls(row, ["last_mail_suppression_reason"])

        # The two campaign-scoped reasons never enter the standing vocabulary.
        for premises_id in (enrolled["id"], wrong_segment["id"]):
            row = validate_success(api.get_premises(premises_id, MARKETING_OPS))
            assert_fields(row, {"suppression_reason": "NONE", "suppressed": False})

        # A suppressed address was not mailed, so its yearly tally stays at zero.
        row = validate_success(api.get_premises(bad_only["id"], MARKETING_OPS))
        assert_fields(row, {"mail_count_current_year": 0, "suppression_reason": "BAD_ADDRESS",
                            "suppressed": True})

        dropped = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert_fields(dropped, {"status": "MAILED", "mailed_count": 2, "suppressed_count": 5})
        assert_instant(dropped["mail_dropped_at"], "2026-08-05T00:00:00.000Z",
                       "mail_dropped_at")


class TestContractorSelection:
    """The eligibility filter, the empty pool and the urgency-weighted score."""

    def test_selection_pool_excludes_state_certification_licence_and_permit_failures(self, api):
        """Four of five contractors fail one filter condition each, and the sole
        survivor is scored 0.45/0.35/0.20 on 60, a floored headroom of 100 and a
        floored rate component of 0.

        PRD: "A contractor qualifies only when **all** of the following hold: `status` is `ACTIVE`, so both `PROBATION` and `SUSPENDED` are excluded; `license_expires_on` is strictly later than the logical clock's calendar date, so a licence expiring today is already unusable; the claim's `line_type` appears in `line_types_certified`; the contractor's `state_code` equals the state code of the premises reached through the claim's enrollment; `open_dispatch_count` is strictly less than `max_open_dispatches`; and, when the product's `permit_covered` is true, `permit_pull_authorized` is true."

        Design: Corner/calculations/selection_pool_excludes_state_certification_licence_and_permit_failures
        """
        world = _active_policy(api)
        assert world["product"]["permit_covered"] is True
        assert world["premises"]["state_code"] == "OR"

        out_of_state = fixtures.create_unique_contractor(api, state_code="WA")
        wrong_line = fixtures.create_unique_contractor(
            api, line_types_certified=["SEWER_LATERAL"]
        )
        # The clock reads 2026-09-10, so a licence expiring 2026-09-01 is gone.
        lapsed_licence = fixtures.create_unique_contractor(
            api, license_expires_on="2026-09-01"
        )
        no_permit = fixtures.create_unique_contractor(api, permit_pull_authorized=False)
        eligible = fixtures.create_unique_contractor(
            api, sla_compliance_pct=60, hourly_rate_cents=20000, max_open_dispatches=5,
            permit_pull_authorized=True,
        )

        # The candidate pool is observable: the line-type filter matches when the
        # value is a member of line_types_certified, so only the sewer-only
        # contractor drops out of this view, in created_at ascending order.
        rows, meta = assert_list_envelope(
            api.list_contractors(OPERATIONS_ADMIN,
                                 params={"line_type": "WATER_SERVICE_LINE"}),
            expected_total=4,
        )
        assert_ids_in_order(rows, [out_of_state["id"], lapsed_licence["id"],
                                   no_permit["id"], eligible["id"]])
        assert wrong_line["id"] not in [row["id"] for row in rows]

        claim = fixtures.file_claim(api, world["enrollment_id"], urgency="URGENT")
        approved = fixtures.approve_claim(api, claim["id"])
        assert approved["status"] == "APPROVED"

        dispatch = validate_success(
            api.create_dispatch(
                claim["id"],
                factories.dispatch_payload(approved["version"], fixtures.DEFAULT_WINDOW_START),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert dispatch["contractor_id"] == eligible["id"], (
            "the only contractor passing every condition must be selected"
        )
        assert dispatch["selection_mode"] == "AUTOMATIC"
        # 0.45*60 + 0.35*100 + 0.20*max(0, 100 - floor(20000/200)) = 27 + 35 + 0
        assert dispatch["selection_score"] == pytest.approx(62.00, abs=0.01)
        # 6 hours for a water service line at 20000 an hour plus 120000 materials.
        assert dispatch["estimated_benefit_cents"] == 240000
        assert_cents(dispatch["estimated_benefit_cents"], "estimated_benefit_cents")
        assert dispatch["status"] == "ASSIGNED"

        rows, meta = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim["id"]}),
            expected_total=1,
        )
        assert_ids_in_order(rows, [dispatch["id"]])

        chosen = fixtures.refresh_contractor(api, eligible["id"])
        assert chosen["open_dispatch_count"] == 1
        for loser in (out_of_state, wrong_line, lapsed_licence, no_permit):
            assert fixtures.refresh_contractor(api, loser["id"])["open_dispatch_count"] == 0

    def test_automatic_dispatch_with_an_empty_pool_returns_no_eligible_contractor(self, api):
        """The only contractor in the network is out of state, so the selector
        refuses rather than relaxing the state condition.

        PRD: "If the filter empties the pool, the request is refused with `ERR_NO_ELIGIBLE_CONTRACTOR` — the selector **never** relaxes a condition to find someone."

        Design: Corner/calculations/automatic_dispatch_with_an_empty_pool_returns_no_eligible_contractor
        """
        world = _active_policy(api)
        out_of_state = fixtures.create_unique_contractor(api, state_code="WA")

        claim = fixtures.file_claim(api, world["enrollment_id"], urgency="URGENT")
        approved = fixtures.approve_claim(api, claim["id"])

        refused = api.create_dispatch(
            claim["id"],
            factories.dispatch_payload(approved["version"], fixtures.DEFAULT_WINDOW_START),
            OPERATIONS_ADMIN,
        )
        assert_refused(refused, ERR_NO_ELIGIBLE_CONTRACTOR, 422)

        # A refused request mutates nothing on either side of the selection.
        still_approved = fixtures.refresh_claim(api, claim["id"])
        assert_fields(still_approved, {"status": "APPROVED", "version": approved["version"]})
        rows, meta = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim["id"]}),
            expected_total=0,
        )
        assert rows == []
        assert fixtures.refresh_contractor(api, out_of_state["id"])["open_dispatch_count"] == 0
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_reserved_cents"] == 0

    def test_selection_score_tie_is_broken_by_the_cheaper_hourly_rate(self, api):
        """Two candidates score 80.50 apiece, and the later-created but cheaper
        one wins because the rate tie-break outranks created_at.

        PRD: "Ties are broken deterministically: highest `selection_score` first, then the lower `hourly_rate_cents`, then the earlier `created_at`."

        Design: Corner/calculations/selection_score_tie_is_broken_by_the_cheaper_hourly_rate
        """
        world = _active_policy(api)

        # 0.45*74 + 0.35*100 + 0.20*(100 - floor(7800/200)) = 33.3 + 35 + 12.2
        dearer = fixtures.create_unique_contractor(
            api, sla_compliance_pct=74, hourly_rate_cents=7800, max_open_dispatches=5
        )
        # 0.45*70 + 0.35*100 + 0.20*(100 - floor(6000/200)) = 31.5 + 35 + 14.0
        cheaper = fixtures.create_unique_contractor(
            api, sla_compliance_pct=70, hourly_rate_cents=6000, max_open_dispatches=5
        )

        claim = fixtures.file_claim(api, world["enrollment_id"], urgency="URGENT")
        approved = fixtures.approve_claim(api, claim["id"])

        dispatch = validate_success(
            api.create_dispatch(
                claim["id"],
                factories.dispatch_payload(approved["version"], fixtures.DEFAULT_WINDOW_START),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert dispatch["contractor_id"] == cheaper["id"], (
            "on an exact score tie the lower hourly_rate_cents wins, even though "
            "the dearer candidate has the earlier created_at"
        )
        assert dispatch["selection_score"] == pytest.approx(80.50, abs=0.01)
        assert dispatch["selection_mode"] == "AUTOMATIC"
        # 6 hours at 6000 plus 120000 materials, well under the 800000 pool.
        assert dispatch["estimated_benefit_cents"] == 156000

        assert fixtures.refresh_contractor(api, cheaper["id"])["open_dispatch_count"] == 1
        assert fixtures.refresh_contractor(api, dearer["id"])["open_dispatch_count"] == 0
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_reserved_cents"] == 156000


class TestBenefitWaterfall:
    """The four buckets, the trimmed lines and the pool the recurrence chain shares."""

    def test_waterfall_skips_the_permit_bucket_and_caps_restoration_at_the_allowance(self, api):
        """A product that does not cover permits pays 0 into the permit bucket
        and trims 300000 of hardscape down to the 250000 allowance, so a 630000
        invoice settles at 550000 with 80000 left to the homeowner.

        PRD: "The covered permit is `permit_fee_cents` when the product's `permit_covered` is true, and 0 otherwise."

        Design: Corner/calculations/waterfall_skips_the_permit_bucket_and_caps_restoration_at_the_allowance
        """
        world = _active_policy(api, product_overrides={
            "permit_covered": False,
            "restoration_covered_scope": "FULL_HARDSCAPE",
            "per_occurrence_cap_cents": 800000,
            "annual_cap_cents": 1000000,
        })
        contractor = fixtures.create_contractor(api)

        claim = fixtures.file_claim(api, world["enrollment_id"], urgency="URGENT")
        approved = fixtures.approve_claim(api, claim["id"])
        dispatch = fixtures.dispatch_claim(api, claim["id"], approved["version"])
        # The provisional reservation has no permit or restoration component:
        # 6 hours for a water service line at 18000 plus 120000 of materials.
        assert dispatch["estimated_benefit_cents"] == 228000

        fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
        fixtures.arrive_dispatch(api, dispatch["id"], contractor["id"])
        completed = fixtures.complete_dispatch(
            api, dispatch["id"], contractor["id"], 260000, 40000,
            permit_number="OR-PERMIT-3391",
            permit_fee_cents=30000,
            restoration_cents=300000,
            restoration_scope="FULL_HARDSCAPE",
        )

        assert_fields(completed, {
            "status": "COMPLETED",
            "invoice_total_cents": 630000,
            "benefit_paid_cents": 550000,
            "customer_responsibility_cents": 80000,
        })
        for field in ("invoice_total_cents", "benefit_paid_cents",
                      "customer_responsibility_cents"):
            assert_cents(completed[field], field)

        settled_claim = fixtures.refresh_claim(api, claim["id"])
        assert_fields(settled_claim, {
            "status": "PAID",
            "benefit_paid_cents": 550000,
            "occurrence_used_cents": 550000,
        })

        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(enrollment, {
            "annual_benefit_used_cents": 550000,
            "annual_benefit_reserved_cents": 0,
            "cap_status": "WITHIN_CAP",
            "cap_year_start": "2026-08-05",
        })

        rows = fixtures.ledger_entries(api, enrollment_id=world["enrollment_id"],
                                       ledger_kind="BENEFIT")
        assert_ledger_amounts(rows, [550000])
        assert rows[0]["entry_type"] == "BENEFIT_CHARGE"
        assert rows[0]["cap_year_start"] == "2026-08-05"

    def test_occurrence_pool_is_shared_across_the_recurrence_chain(self, api):
        """A first claim consumes the whole 300000 per-occurrence allowance, so
        the linked recurrence cannot be dispatched at all.

        PRD: "Before any of this, the occurrence pool is checked: a claim whose occurrence group has already consumed its entire per-occurrence allowance cannot be worked at all and is refused with `ERR_PER_OCCURRENCE_CAP_EXHAUSTED`."

        Design: Corner/calculations/occurrence_pool_is_shared_across_the_recurrence_chain
        """
        world = _active_policy(api, product_overrides={
            "per_occurrence_cap_cents": 300000,
            "annual_cap_cents": 1000000,
            "permit_covered": False,
            "restoration_covered_scope": "NONE",
        })
        contractor = fixtures.create_contractor(api)

        claim_a = fixtures.file_claim(api, world["enrollment_id"], urgency="URGENT")
        assert claim_a["occurrence_root_claim_id"] == claim_a["id"], (
            "a claim filed with no link is the root of its own occurrence group"
        )
        assert claim_a["eligibility_assessment"] == "ELIGIBLE"
        approved_a = fixtures.approve_claim(api, claim_a["id"])
        dispatch_a = fixtures.dispatch_claim(api, claim_a["id"], approved_a["version"])
        assert dispatch_a["estimated_benefit_cents"] == 228000

        fixtures.accept_dispatch(api, dispatch_a["id"], contractor["id"])
        fixtures.arrive_dispatch(api, dispatch_a["id"], contractor["id"])
        completed = fixtures.complete_dispatch(
            api, dispatch_a["id"], contractor["id"], 400000, 0,
            permit_fee_cents=0, restoration_cents=0, restoration_scope="NONE",
        )
        # The pool is the smaller of 300000 occurrence room and 1000000 annual
        # room, and labour alone exhausts it, so every later bucket gets nothing.
        assert_fields(completed, {
            "invoice_total_cents": 400000,
            "benefit_paid_cents": 300000,
            "customer_responsibility_cents": 100000,
        })

        # The recurrence joins the earlier claim's group and inherits its usage.
        fixtures.set_clock(api, "2026-09-11T08:00:00.000Z")
        claim_b = fixtures.file_claim(
            api, world["enrollment_id"], urgency="URGENT",
            recurrence_of_claim_id=claim_a["id"],
        )
        assert claim_b["occurrence_root_claim_id"] == claim_a["id"]
        assert claim_b["eligibility_assessment"] == "ELIGIBLE"
        assert claim_b["occurrence_used_cents"] == 300000, (
            "occurrence_used_cents sums the benefit paid across every claim "
            "sharing the same occurrence_root_claim_id"
        )
        approved_b = fixtures.approve_claim(api, claim_b["id"])
        assert approved_b["status"] == "APPROVED"

        refused = api.create_dispatch(
            claim_b["id"],
            factories.dispatch_payload(approved_b["version"], "2026-09-12T09:00:00.000Z"),
            OPERATIONS_ADMIN,
        )
        assert_refused(refused, ERR_PER_OCCURRENCE_CAP_EXHAUSTED, 422)

        rows, meta = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim_b["id"]}),
            expected_total=0,
        )
        assert rows == []
        assert fixtures.refresh_claim(api, claim_b["id"])["status"] == "APPROVED"

        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(enrollment, {
            "annual_benefit_used_cents": 300000,
            "annual_benefit_reserved_cents": 0,
            "cap_status": "WITHIN_CAP",
        })


class TestRegulatorResponseDeadlines:
    """The expedited window is a floor, and escalation waits five whole days."""

    def test_expedited_floor_collapses_a_bbb_deadline_from_twenty_one_to_five_days(self, api):
        """Citing a DENIED claim collapses the BBB window from 21 days to 5, while
        an uncited BBB complaint keeps 21 and an uncited PUC complaint keeps 10.

        PRD: "When the complaint cites a claim that is currently `DENIED` or `APPEAL_UPHELD_DENIAL`, the window becomes the **lesser** of the base days and 5 — the expedited path is a floor rather than a per-regulator subtraction, so a `BBB` complaint about a denied claim collapses from 21 days to 5 exactly as a `PUC` complaint collapses from 10 to 5."

        Design: Corner/calculations/expedited_response_floor_collapses_a_bbb_deadline_from_twenty_one_to_five_days
        """
        world = _active_policy(api)
        # A CURB_STOP boundary does not cover an inside-the-home failure.
        claim = fixtures.file_claim(api, world["enrollment_id"],
                                    defect_location="INSIDE_HOME")
        assert claim["eligibility_assessment"] == "OWNERSHIP_INELIGIBLE"
        denied = fixtures.deny_claim(api, claim["id"],
                                     denial_reason="OWNERSHIP_INELIGIBLE")
        assert denied["status"] == "DENIED"

        fixtures.set_clock(api, "2026-09-20T00:00:00.000Z")

        expedited = fixtures.create_complaint(
            api, world["partner_id"], regulator="BBB", claim_id=claim["id"]
        )
        assert_fields(expedited, {
            "regulator": "BBB",
            "claim_id": claim["id"],
            "status": "OPEN",
            "escalation_count": 0,
            "days_overdue": 0,
            "version": 1,
        })
        assert_instant(expedited["received_at"], "2026-09-20T00:00:00.000Z", "received_at")
        assert_instant(expedited["response_due_at"], "2026-09-25T00:00:00.000Z",
                       "response_due_at")
        assert_instant_format(expedited["response_due_at"], "response_due_at")
        assert_nulls(expedited, ["responded_at"])

        uncited_bbb = fixtures.create_complaint(api, world["partner_id"], regulator="BBB")
        assert_instant(uncited_bbb["response_due_at"], "2026-10-11T00:00:00.000Z",
                       "response_due_at")

        uncited_puc = fixtures.create_complaint(api, world["partner_id"], regulator="PUC")
        assert_instant(uncited_puc["response_due_at"], "2026-09-30T00:00:00.000Z",
                       "response_due_at")

        # The regulator's citation also reopens the claim it named.
        reopened = fixtures.refresh_claim(api, claim["id"])
        assert_fields(reopened, {
            "status": "APPEAL_OPEN",
            "appeal_source": "REGULATOR",
            "appeal_count": 1,
        })
        assert_instant(reopened["appeal_opened_at"], "2026-09-20T00:00:00.000Z",
                       "appeal_opened_at")

    def test_complaint_escalates_only_after_the_five_day_grace_period(self, api):
        """The run that arrives on the due date only marks the complaint OVERDUE;
        four days later nothing moves, and on the fifth day it escalates.

        PRD: "Every complaint in `OPEN` whose `response_due_at` has arrived moves `OPEN → OVERDUE` with `days_overdue` recomputed, and every complaint already `OVERDUE` whose `days_overdue` has reached 5 moves `OVERDUE → ESCALATED` with `escalation_count` incremented."

        Design: Corner/calculations/complaint_escalates_only_after_the_five_day_grace_period
        """
        world = fixtures.active_partner_with_product(api)
        fixtures.set_clock(api, "2026-09-20T00:00:00.000Z")
        complaint = fixtures.create_complaint(api, world["partner_id"], regulator="PUC")
        assert_instant(complaint["response_due_at"], "2026-09-30T00:00:00.000Z",
                       "response_due_at")
        assert_fields(complaint, {"status": "OPEN", "days_overdue": 0, "version": 1,
                                  "escalation_count": 0})

        # The comparison is inclusive, so the run on the due date marks it overdue.
        fixtures.set_clock(api, "2026-09-30T00:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert_nightly_names(report, "overdue_complaint_ids", [complaint["id"]])
        assert_nightly_names(report, "escalated_complaint_ids", [])
        overdue = fixtures.refresh_complaint(api, complaint["id"])
        assert_fields(overdue, {
            "status": "OVERDUE",
            "days_overdue": 0,
            "escalation_count": 0,
            "version": 2,
        })

        # Four whole days past due is still inside the grace period.
        fixtures.set_clock(api, "2026-10-04T00:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert_nightly_names(report, "overdue_complaint_ids", [])
        assert_nightly_names(report, "escalated_complaint_ids", [])
        waiting = fixtures.refresh_complaint(api, complaint["id"])
        assert_fields(waiting, {
            "status": "OVERDUE",
            "days_overdue": 4,
            "escalation_count": 0,
            "version": 2,
        })

        # The fifth whole day reaches the threshold.
        fixtures.set_clock(api, "2026-10-05T00:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert_nightly_names(report, "escalated_complaint_ids", [complaint["id"]])
        assert_nightly_names(report, "overdue_complaint_ids", [])
        escalated = fixtures.refresh_complaint(api, complaint["id"])
        assert_fields(escalated, {
            "status": "ESCALATED",
            "days_overdue": 5,
            "escalation_count": 1,
            "version": 3,
        })

        rows, meta = assert_list_envelope(
            api.list_complaints(REGULATORY_AFFAIRS, params={"status": "ESCALATED"}),
            expected_total=1,
        )
        assert_ids_in_order(rows, [complaint["id"]])
        rows, meta = assert_list_envelope(
            api.list_complaints(REGULATORY_AFFAIRS, params={"status": "OVERDUE"}),
            expected_total=0,
        )
        assert rows == []


class TestEligibilityLadder:
    """One reason is recorded, and it is the first failing rung of a pinned order."""

    def test_eligibility_ladder_reports_ownership_before_pre_existing(self, api):
        """An inside-the-home failure on a known-defect address inside the waiting
        period fails three rungs at once and reports only the highest of them.

        PRD: "The verdict is the **first failing check in a pinned order**, and the order matters because a claim can fail several checks at once while only one reason is recorded."

        Design: Corner/calculations/eligibility_ladder_reports_ownership_before_pre_existing
        """
        world = fixtures.partner_product_premises(
            api,
            premises_overrides={"known_defect_reported_at": "2026-08-01T00:00:00.000Z"},
        )
        world = fixtures.enrolled_premises(api, world)
        enrollment = world["enrollment"]
        assert_instant(enrollment["enrollment_date"], CLOCK_ENROLLMENT_DAY,
                       "enrollment_date")
        assert_instant_format(enrollment["enrollment_date"], "enrollment_date")
        assert_instant(enrollment["coverage_effective_at"], COVERAGE_EFFECTIVE_AT,
                       "coverage_effective_at")
        assert enrollment["coverage_status"] == "PENDING_WAITING_PERIOD"

        # Rung two beats rungs three and four, all three of which are failing.
        outside_boundary = fixtures.file_claim(
            api, world["enrollment_id"], defect_location="INSIDE_HOME"
        )
        assert outside_boundary["eligibility_assessment"] == "OWNERSHIP_INELIGIBLE", (
            "ownership is checked before the pre-existing defect and the waiting "
            "period, so it is the reason that is recorded"
        )

        # Inside the covered boundary, rung three beats rung four.
        known_defect = fixtures.file_claim(
            api, world["enrollment_id"], defect_location="CURB_STOP_TO_METER"
        )
        assert known_defect["eligibility_assessment"] == "PRE_EXISTING", (
            "a defect reported before the enrollment_date outranks the waiting period"
        )
        assert_fields(known_defect, {"status": "TRIAGE", "version": 1, "appeal_count": 0})
        assert known_defect.get("denial_reason") is None

        # The recorded denial reason may not contradict that assessment.
        refused = api.triage_claim(
            known_defect["id"],
            factories.triage_denial_payload("WAITING_PERIOD"),
            CLAIMS_ADJUSTER,
        )
        assert_refused(refused, ERR_DENIAL_REASON_UNSUPPORTED, 422)
        untouched = fixtures.refresh_claim(api, known_defect["id"])
        assert_fields(untouched, {"status": "TRIAGE", "version": 1})
        assert untouched.get("denial_reason") is None

        denied = fixtures.deny_claim(api, known_defect["id"],
                                     denial_reason="PRE_EXISTING")
        assert_fields(denied, {
            "status": "DENIED",
            "denial_reason": "PRE_EXISTING",
            "version": 2,
        })
        assert_instant(denied["denied_at"], CLOCK_ENROLLMENT_DAY, "denied_at")

        # The other claim's verdict is re-derived on every read and is unchanged.
        rechecked = fixtures.refresh_claim(api, outside_boundary["id"])
        assert rechecked["eligibility_assessment"] == "OWNERSHIP_INELIGIBLE"


class TestResponseSlaDeadline:
    """The response deadline is stamped once and a supersede inherits it."""

    def test_sla_deadline_is_stamped_once_and_inherited_by_the_supersede(self, api):
        """An EMERGENCY claim reported at 08:00 carries a 12:00 deadline, the
        11:30 supersede inherits it unchanged, and the run at exactly 12:00
        breaches the new dispatch.

        PRD: "Every later dispatch on the claim, **including one created through `supersedes_dispatch_id`, inherits that instant unchanged**: re-dispatching a stalled job never buys the network more time."

        Design: Corner/calculations/sla_deadline_is_stamped_once_and_inherited_by_the_supersede
        """
        world = _active_policy(api)
        # Alder: sla 92, 18000 an hour. 0.70*92 + 0.25*100 + 0.05*10 = 89.90.
        best_record = fixtures.create_contractor(api)
        # Cheaper: sla 70, 6000 an hour. 0.70*70 + 0.25*100 + 0.05*70 = 77.50.
        cheaper = fixtures.create_unique_contractor(
            api, sla_compliance_pct=70, hourly_rate_cents=6000, max_open_dispatches=5
        )

        claim = fixtures.file_claim(api, world["enrollment_id"], urgency="EMERGENCY")
        assert_instant(claim["reported_at"], CLOCK_COVERAGE_ACTIVE, "reported_at")
        approved = fixtures.approve_claim(api, claim["id"])

        first = fixtures.dispatch_claim(api, claim["id"], approved["version"],
                                        window_start="2026-09-11T09:00:00.000Z")
        assert first["contractor_id"] == best_record["id"], (
            "under the emergency weights reliability dominates the same pool"
        )
        assert first["selection_score"] == pytest.approx(89.90, abs=0.01)
        assert_instant(first["assigned_at"], CLOCK_COVERAGE_ACTIVE, "assigned_at")
        assert_instant(first["window_end"], "2026-09-11T13:00:00.000Z", "window_end")
        assert_instant(first["sla_deadline_at"], "2026-09-10T12:00:00.000Z",
                       "sla_deadline_at")
        assert_instant_format(first["sla_deadline_at"], "sla_deadline_at")

        dispatched_claim = fixtures.refresh_claim(api, claim["id"])
        assert_fields(dispatched_claim, {
            "status": "DISPATCHED",
            "version": approved["version"] + 1,
        })
        assert_instant(dispatched_claim["sla_deadline_at"], "2026-09-10T12:00:00.000Z",
                       "sla_deadline_at")

        # Thirty minutes before the deadline the job is redispatched.
        fixtures.set_clock(api, "2026-09-10T11:30:00.000Z")
        second = fixtures.dispatch_claim_to(
            api, claim["id"], dispatched_claim["version"], cheaper["id"],
            window_start="2026-09-11T09:00:00.000Z",
            supersedes_dispatch_id=first["id"],
        )
        assert_instant(second["sla_deadline_at"], "2026-09-10T12:00:00.000Z",
                       "sla_deadline_at")
        assert_instant(second["assigned_at"], "2026-09-10T11:30:00.000Z", "assigned_at")
        assert_fields(second, {
            "status": "ASSIGNED",
            "selection_mode": "MANUAL",
            "contractor_id": cheaper["id"],
            "supersedes_dispatch_id": first["id"],
            "estimated_benefit_cents": 156000,
        })
        assert second["selection_score"] == pytest.approx(77.50, abs=0.01)

        superseded = fixtures.refresh_dispatch(api, first["id"])
        assert_fields(superseded, {
            "status": "SUPERSEDED",
            "cancellation_reason": "SUPERSEDED_BY_REDISPATCH",
        })
        assert_instant(superseded["sla_deadline_at"], "2026-09-10T12:00:00.000Z",
                       "sla_deadline_at")
        assert fixtures.refresh_contractor(api, best_record["id"])["open_dispatch_count"] == 0
        assert fixtures.refresh_contractor(api, cheaper["id"])["open_dispatch_count"] == 1
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_reserved_cents"] == 156000

        # The inherited deadline is reached exactly, and the comparison is inclusive.
        fixtures.set_clock(api, "2026-09-10T12:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert_nightly_names(report, "sla_breached_dispatch_ids", [second["id"]])
        assert_nightly_names(report, "probated_contractor_ids", [])
        assert_nightly_names(report, "cancelled_dispatch_ids", [])

        breached = fixtures.refresh_dispatch(api, second["id"])
        assert breached["status"] == "SLA_BREACHED"
        assert breached.get("cancellation_reason") is None
        breaching_contractor = fixtures.refresh_contractor(api, cheaper["id"])
        assert_fields(breaching_contractor, {
            "sla_breach_count": 1,
            "status": "ACTIVE",
            "open_dispatch_count": 0,
        })
        assert fixtures.refresh_claim(api, claim["id"])["status"] == "DISPATCHED"
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_reserved_cents"] == 0
