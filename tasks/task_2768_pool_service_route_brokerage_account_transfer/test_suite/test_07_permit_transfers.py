"""Permit filings, denials, retries and reciprocity waivers (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_buyer_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

BROKER = TEST_USERS["broker_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
DENIAL_CODE = "INCOMPLETE_PACKET"


class TestFilingRetryAndTerminality:
    def test_the_retry_edge_exists_only_through_denied_and_counts_every_attempt(self, api):
        """One permit row is driven through apply, denial, re-apply and approval; each of the three
        endpoints refuses from the states it does not declare, the attempt counter climbs, the
        window is recomputed from the new filing date, and the refusal's reason code survives the
        retry.

        PRD §3.7: "apply against anything but `NOT_STARTED` or `DENIED`, decide against anything but
        `APPLIED`, waive against anything but `NOT_STARTED` — the answer is
        `ERR_LICENSE_TRANSFER_NOT_PENDING`."
        PRD §3.7: "the transfer moves to `APPLIED`, the date is stored, `attempt_count` increments
        by one, and `processing_window_end` is computed as `applied_on` advanced by the state
        profile's `transfer_processing_days`."
        PRD §3.7: "on the retry edge out of `DENIED` the `denial_reason_code` of the refusal is
        retained, so the history of why the state said no is not erased by trying again."
        PRD §3.7: "`APPROVED` is absorbing and ends the permit's story".

        Design: Corner/endpoints/denied_permit_transfer_can_be_reapplied_but_an_approved_one_cannot
        """
        ctx = fx.nv_deal_route(api, region_code="LV-SOUTH", stop_after="accepted", waive=False)
        transfer_id = ctx.transfer["id"]
        buyer_headers = make_buyer_headers(ctx.buyer["id"])
        assert ctx.transfer["status"] == "NOT_STARTED"
        assert ctx.transfer["permit_type"] == "BUSINESS_TAX"

        applied = validate_success(
            api.apply_license_transfer(
                transfer_id, f.apply_license_transfer_payload("2026-08-01"), buyer_headers
            )
        )
        assert applied["status"] == "APPLIED"
        assert applied["applied_on"] == "2026-08-01"
        assert applied["processing_window_end"] == "2026-08-11"
        assert applied["attempt_count"] == 1

        validate_error(
            api.apply_license_transfer(
                transfer_id, f.apply_license_transfer_payload("2026-08-02"), buyer_headers
            ),
            ApiErrorId.ERR_LICENSE_TRANSFER_NOT_PENDING,
            409,
        )
        validate_error(
            api.waive_license_transfer(transfer_id, f.waive_license_transfer_payload(), BROKER),
            ApiErrorId.ERR_LICENSE_TRANSFER_NOT_PENDING,
            409,
        )

        denied = validate_success(
            api.decide_license_transfer(
                transfer_id,
                f.decide_license_transfer_payload(
                    "DENY", "2026-08-05", denial_reason_code=DENIAL_CODE
                ),
                ADMIN,
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["decided_on"] == "2026-08-05"
        assert denied["denial_reason_code"] == DENIAL_CODE

        validate_error(
            api.decide_license_transfer(
                transfer_id, f.decide_license_transfer_payload("APPROVE", "2026-08-06"), ADMIN
            ),
            ApiErrorId.ERR_LICENSE_TRANSFER_NOT_PENDING,
            409,
        )

        retried = validate_success(
            api.apply_license_transfer(
                transfer_id, f.apply_license_transfer_payload("2026-08-18"), buyer_headers
            )
        )
        assert retried["status"] == "APPLIED"
        assert retried["attempt_count"] == 2
        assert retried["applied_on"] == "2026-08-18"
        assert retried["processing_window_end"] == "2026-08-28"
        assert retried["denial_reason_code"] == DENIAL_CODE

        approved = validate_success(
            api.decide_license_transfer(
                transfer_id, f.decide_license_transfer_payload("APPROVE", "2026-08-18"), ADMIN
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_on"] == "2026-08-18"

        validate_error(
            api.apply_license_transfer(
                transfer_id, f.apply_license_transfer_payload("2026-09-10"), buyer_headers
            ),
            ApiErrorId.ERR_LICENSE_TRANSFER_NOT_PENDING,
            409,
        )


def two_reciprocity_deals(api):
    """Two NV deals accepted for two buyers licensed in different home states."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    profile = fx.seed_nv_profile(api)
    seller = fx.seed_seller(api)
    reciprocal = fx.seed_buyer(api, state_code="AZ", prequalified_amount_cents=30000000)
    foreign = fx.seed_buyer(api, state_code="UT", prequalified_amount_cents=30000000)
    first = fx.nv_deal_route(
        api, region_code="REC-01", stop_after="accepted",
        profile=profile, seller=seller, buyer=reciprocal,
    )
    second = fx.nv_deal_route(
        api, region_code="REC-02", stop_after="accepted",
        profile=profile, seller=seller, buyer=foreign,
    )
    assert profile["reciprocity_states"] == ["AZ"]
    return first, second


def two_az_accepted_deals(api):
    """One AZ buyer holding two accepted deals, so two sibling permit rows share a resource key."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.seed_az_profile(api)
    seller = fx.seed_seller(api)
    buyer = fx.qualified_buyer(api)
    deals = []
    for region in ("WIN-01", "WIN-02"):
        listing = fx.seed_listing(
            api, seller["id"], region_code=region, listed_mrr_cents=20000,
            listed_account_count=1, asking_price_cents=200000,
        )
        account = fx.add_account(
            api, listing["id"], customer_ref=f"{region}-S1", monthly_service_fee_cents=20000,
            avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0,
        )
        fx.add_billing_months(
            api, account["id"], billed_service_cents=20000, billed_chemical_cents=0,
            billed_repair_cents=0, collected_cents=20000,
        )
        fx.verify_account(api, account["id"])
        fx.create_valuation(api, listing["id"], "LISTED_BASIS")
        fx.publish_listing(api, listing["id"])
        deal = fx.open_deal(
            api, listing["id"], buyer, offer_price_cents=180000, down_payment_cents=60000,
            note_principal_cents=120000,
        )
        deals.append(fx.accept_deal(api, deal["id"], seller, 90))
    return buyer, deals


class TestWaivabilityLivesOnTwoOtherRecords:
    def test_the_reciprocal_buyers_permit_is_waived_without_ever_being_filed(self, api):
        """Nothing about the transfer itself decides this: the row is a plain `NOT_STARTED`
        `BUSINESS_TAX` filing against the NV regime, and it clears only because the buyer is `LICENSED`
        in a state NV recognises. The waiver is not an application, so no date and no attempt is
        recorded, and the derived basis names the buyer's own state rather than the string sent in.

        PRD §3.7: "Two conditions must hold, both of them entirely about other entities: the buyer's
        `license_status` must be exactly `LICENSED`, and the buyer's own `state_code` must be a member
        of the state profile's `reciprocity_states` list."
        PRD §3.7: "On success the transfer moves to `WAIVED`, which is absorbing, and its
        `waiver_basis` is recorded as the string `RECIPROCITY_` immediately followed by the buyer's
        `state_code` ... Any `waiver_basis` value supplied in the request is replaced by that derived
        string."
        PRD §3.7: "A waiver is only available from `NOT_STARTED` — a filed application must be seen
        through, not waived around."

        Design: Difficulty/cross_entity_state_dependency/license_waiver_depends_on_buyer_state_and_profile_reciprocity
        """
        reciprocal, foreign = two_reciprocity_deals(api)
        waivable = reciprocal.transfer
        blocked = foreign.transfer
        assert waivable["status"] == "NOT_STARTED"
        assert blocked["status"] == "NOT_STARTED"
        assert waivable["permit_type"] == "BUSINESS_TAX"
        assert blocked["permit_type"] == "BUSINESS_TAX"
        assert waivable["state_profile_id"] == blocked["state_profile_id"]

        waived = validate_success(
            api.waive_license_transfer(waivable["id"], f.waive_license_transfer_payload(), BROKER)
        )
        assert waived["status"] == "WAIVED"
        assert waived["waiver_basis"] == "RECIPROCITY_AZ"
        assert waived["applied_on"] is None
        assert waived["attempt_count"] == 0
        assert waived["decided_on"] is None

        validate_error(
            api.waive_license_transfer(waived["id"], f.waive_license_transfer_payload(), BROKER),
            ApiErrorId.ERR_LICENSE_TRANSFER_NOT_PENDING,
            409,
        )
        unchanged = validate_success(api.get_license_transfer(waived["id"], BROKER))
        assert unchanged["waiver_basis"] == "RECIPROCITY_AZ"
        assert unchanged["attempt_count"] == 0

    def test_the_locally_identical_row_of_a_foreign_buyer_is_refused_and_must_be_filed(self, api):
        """The second row differs from the first in nothing of its own — same permit type, same regime,
        same `NOT_STARTED` status — and is refused because Utah is not on NV's list; the deal it belongs
        to is untouched, and the ordinary filing route still delivers the permit.

        PRD §3.7: "If either fails, the answer is `ERR_RECIPROCITY_NOT_AVAILABLE`. Note that this makes
        a permit's waivability depend on two fields of two other records while nothing about the
        transfer itself changes"
        PRD §3.7: "the transfer moves to `APPLIED`, the date is stored, `attempt_count` increments by
        one, and `processing_window_end` is computed as `applied_on` advanced by the state profile's
        `transfer_processing_days`."
        PRD §3.7: "`APPROVE` moves the transfer to `APPROVED` and writes `decided_on`, leaving
        `denial_reason_code` untouched."

        Design: Difficulty/cross_entity_state_dependency/license_waiver_depends_on_buyer_state_and_profile_reciprocity
        """
        reciprocal, foreign = two_reciprocity_deals(api)
        blocked = foreign.transfer

        validate_error(
            api.waive_license_transfer(blocked["id"], f.waive_license_transfer_payload(), BROKER),
            ApiErrorId.ERR_RECIPROCITY_NOT_AVAILABLE,
            422,
        )
        refused = validate_success(api.get_license_transfer(blocked["id"], BROKER))
        assert refused["status"] == "NOT_STARTED"
        assert refused["waiver_basis"] is None
        assert refused["attempt_count"] == 0
        assert refused["permit_type"] == reciprocal.transfer["permit_type"]

        deal = validate_success(api.get_deal(foreign.deal["id"], BROKER))
        assert deal["status"] == "ACCEPTED"

        applied = validate_success(
            api.apply_license_transfer(
                blocked["id"], f.apply_license_transfer_payload("2026-08-01"),
                make_buyer_headers(foreign.buyer["id"]),
            )
        )
        assert applied["status"] == "APPLIED"
        assert applied["applied_on"] == "2026-08-01"
        assert applied["processing_window_end"] == "2026-08-11"
        assert applied["attempt_count"] == 1

        approved = validate_success(
            api.decide_license_transfer(
                blocked["id"], f.decide_license_transfer_payload("APPROVE", "2026-08-05"), ADMIN
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_on"] == "2026-08-05"
        assert approved["waiver_basis"] is None


class TestTheFilingWindowIsClosedAndCarriesACoolingOffGap:
    def test_a_filing_that_starts_on_the_incumbents_last_day_collides(self, api):
        """The incumbent window runs from 2026-08-01 to 2026-08-22 inclusive, and a sibling filing that
        opens on that very last day is refused — the opposite convention from listing exclusivity, where
        starting on the incumbent's end date is allowed. The refusal writes nothing at all.

        PRD §3.7: "That window is *closed*: the last day is inside it, so a regulator's window opened
        on a given day and running fourteen processing days covers both the opening day and the
        fourteenth day."
        PRD §3.7: "Because the interval is closed, two windows that merely touch at an endpoint **do**
        conflict, in deliberate contrast with the listing exclusivity rule of §3.2 where adjacency is
        permitted."
        PRD §3.7: "Filings for the same buyer, the same state and the same `permit_type` may not be in
        flight at once".

        Design: Difficulty/resource_temporal_overlap/license_application_closed_window_plus_cooling_off_gap
        """
        buyer, deals = two_az_accepted_deals(api)
        buyer_headers = make_buyer_headers(buyer["id"])
        incumbent = fx.transfer_for_permit(api, deals[0]["id"], "PESTICIDE_APPLICATOR")
        sibling = fx.transfer_for_permit(api, deals[1]["id"], "PESTICIDE_APPLICATOR")

        filed = validate_success(
            api.apply_license_transfer(
                incumbent["id"], f.apply_license_transfer_payload("2026-08-01"), buyer_headers
            )
        )
        assert filed["status"] == "APPLIED"
        assert filed["applied_on"] == "2026-08-01"
        assert filed["processing_window_end"] == "2026-08-22"
        assert filed["attempt_count"] == 1

        validate_error(
            api.apply_license_transfer(
                sibling["id"], f.apply_license_transfer_payload("2026-08-22"), buyer_headers
            ),
            ApiErrorId.ERR_LICENSE_WINDOW_CONFLICT,
            409,
        )
        untouched = validate_success(api.get_license_transfer(sibling["id"], BROKER))
        assert untouched["status"] == "NOT_STARTED"
        assert untouched["applied_on"] is None
        assert untouched["processing_window_end"] is None
        assert untouched["attempt_count"] == 0

        incumbent_after = validate_success(api.get_license_transfer(incumbent["id"], BROKER))
        assert incumbent_after["status"] == "APPLIED"
        assert incumbent_after["processing_window_end"] == "2026-08-22"

    def test_thirteen_days_of_gap_is_refused_and_exactly_fourteen_is_allowed(self, api):
        """The boundary is not the incumbent's window end but fourteen days past it: a filing on
        2026-09-04 leaves a gap of thirteen days and is refused, and the very next day is accepted with
        its own window recomputed from the new filing date.

        PRD §3.7: "the state also imposes a `cooling_off_days` buffer between them ... a new filing's
        window must neither overlap the window of any other non-`CANCELLED` transfer for that same
        buyer, state and permit type, nor sit within `cooling_off_days` of it."
        PRD §3.7: "Measured as a gap, a fresh filing separated from a prior window by
        `cooling_off_days` minus one day conflicts, while a gap of exactly `cooling_off_days` is
        allowed. A conflict is `ERR_LICENSE_WINDOW_CONFLICT`."
        PRD §3.7: "`processing_window_end` is computed as `applied_on` advanced by the state profile's
        `transfer_processing_days`."

        Design: Difficulty/resource_temporal_overlap/license_application_closed_window_plus_cooling_off_gap
        """
        buyer, deals = two_az_accepted_deals(api)
        buyer_headers = make_buyer_headers(buyer["id"])
        incumbent = fx.transfer_for_permit(api, deals[0]["id"], "PESTICIDE_APPLICATOR")
        sibling = fx.transfer_for_permit(api, deals[1]["id"], "PESTICIDE_APPLICATOR")

        validate_success(
            api.apply_license_transfer(
                incumbent["id"], f.apply_license_transfer_payload("2026-08-01"), buyer_headers
            )
        )

        validate_error(
            api.apply_license_transfer(
                sibling["id"], f.apply_license_transfer_payload("2026-09-04"), buyer_headers
            ),
            ApiErrorId.ERR_LICENSE_WINDOW_CONFLICT,
            409,
        )
        still_idle = validate_success(api.get_license_transfer(sibling["id"], BROKER))
        assert still_idle["status"] == "NOT_STARTED"
        assert still_idle["attempt_count"] == 0

        accepted = validate_success(
            api.apply_license_transfer(
                sibling["id"], f.apply_license_transfer_payload("2026-09-05"), buyer_headers
            )
        )
        assert accepted["status"] == "APPLIED"
        assert accepted["applied_on"] == "2026-09-05"
        assert accepted["processing_window_end"] == "2026-09-26"
        assert accepted["attempt_count"] == 1

        incumbent_after = validate_success(api.get_license_transfer(incumbent["id"], BROKER))
        assert incumbent_after["status"] == "APPLIED"
        assert incumbent_after["applied_on"] == "2026-08-01"
        assert incumbent_after["processing_window_end"] == "2026-08-22"
        assert incumbent_after["attempt_count"] == 1
