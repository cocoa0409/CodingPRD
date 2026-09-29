"""Corner tests for the `validations` section of the corner design index.

Every test here translates one instance of
`SCAFFOLD_CORNER_DESIGN.yaml → scaffold_corner_design → validations` and cites
the PRD sentence that fixes the asserted outcome.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, validate_error, validate_paginated, validate_success,
)

from test_helpers import (
    ApiErrorId, api_client, assert_iso_equals, assert_ledger_nets_to_zero,
    assert_ledger_signature, assert_line_economics, assert_pagination_meta,
    make_admin_headers, make_employee_headers, make_employer_admin_headers,
    make_merchant_headers, make_partner_manager_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.types import (
    DiscountType, DisputeOutcome, DisputeReason, EmploymentStatus,
    FulfillmentStatus, IntegrationStatus, LedgerEntryType, MembershipStatus,
    OfferStatus, PerkCategory, ProgramPosture, RegionCode, StatementBasis,
    StatementStatus, StorefrontStatus, VerificationStatus, VoidReason,
)

# ── Local setup helpers (this file only) ────────────────────────────────────


def _program(record_count=1, offer_overrides=None, **kwargs):
    """An `ACTIVE` partner, a `LIVE` employer and one `ACTIVE` offer.

    The offer carries a `min_spend_cents` floor of 1,000 so the minimum-spend
    rule of PRD §3.7 is exercisable.
    """
    overrides = {"min_spend_cents": 1000}
    overrides.update(offer_overrides or {})
    return fx.live_program(record_count=record_count, offer_overrides=overrides, **kwargs)


def _verify_line(program, membership_id, gross_amount_cents=5000):
    """Reserve then verify one redemption, returning `(created, verified)`."""
    created = fx.create_redemption(program["offer"]["id"], membership_id)
    verified = fx.verify_redemption(
        created, program["merchant"]["id"], gross_amount_cents
    )
    return created, verified


def _open_dispute_on_verified_line():
    """A verified 5,000-cent line whose employee files a dispute on 2026-08-02."""
    program = _program(record_count=1)
    membership_id = program["memberships"][0]["id"]
    created, verified = _verify_line(program, membership_id)
    fx.set_clock("2026-08-02T00:00:00Z")
    dispute = fx.file_dispute(
        created["id"], membership_id, reason=DisputeReason.NOT_HONORED,
        description="The counter refused to apply the discount.",
    )
    return {
        "program": program,
        "membership_id": membership_id,
        "redemption": verified,
        "redemption_id": created["id"],
        "dispute": dispute,
    }


# ── Corner/validations: offer drafting shape, window and region rules ────────


def test_offer_draft_with_equal_window_bounds_is_refused():
    """A draft whose `window_end` equals its `window_start` is refused.

    PRD: "Separately, `window_end` must be strictly after `window_start` or the draft is refused with `ERR_INVALID_WINDOW`, and `region_codes` must be non-empty and a subset of the partner's own `region_codes` or the draft is refused with `ERR_REGION_NOT_COVERED`."

    Design: Corner/validations/offer_creation_rejects_a_degenerate_window_a_mismatched_discount_shape_and_an_uncovered_region
    """
    partner = fx.active_partner()
    merchant_id = partner["merchant"]["id"]

    response = api_client.create_offer(
        F.offer_payload(
            partner["agreement"]["id"],
            title="Zero length window",
            min_spend_cents=1000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-01T00:00:00Z",
        ),
        make_merchant_headers(merchant_id),
    )
    validate_error(response, ApiErrorId.INVALID_WINDOW)

    rows, meta = validate_paginated(
        api_client.list_offers(
            make_merchant_headers(merchant_id),
            params={"agreement_id": partner["agreement"]["id"]},
        )
    )
    assert meta["total_count"] == 0, "a refused draft must not create an offer row"
    assert rows == []


def test_percent_offer_naming_a_cent_value_is_a_discount_shape_mismatch():
    """A `PERCENT` draft that also names `discount_value_cents` is refused.

    PRD: "Any other combination — a percentage offer with no basis-point value, a percentage offer that also names a cent value, a fixed offer with no cent value, or a fixed offer that also names a basis-point value — is refused with `ERR_DISCOUNT_SHAPE_MISMATCH`."

    Design: Corner/validations/offer_creation_rejects_a_degenerate_window_a_mismatched_discount_shape_and_an_uncovered_region
    """
    partner = fx.active_partner()
    merchant_id = partner["merchant"]["id"]

    response = api_client.create_offer(
        F.offer_payload(
            partner["agreement"]["id"],
            title="Percent with a cents value",
            discount_type=DiscountType.PERCENT,
            discount_value_bps=2000,
            discount_value_cents=800,
            min_spend_cents=1000,
        ),
        make_merchant_headers(merchant_id),
    )
    validate_error(response, ApiErrorId.DISCOUNT_SHAPE_MISMATCH)


def test_offer_region_outside_the_partner_footprint_is_refused():
    """`region_codes` must be a subset of the partner's own footprint.

    PRD: "Separately, `window_end` must be strictly after `window_start` or the draft is refused with `ERR_INVALID_WINDOW`, and `region_codes` must be non-empty and a subset of the partner's own `region_codes` or the draft is refused with `ERR_REGION_NOT_COVERED`."

    Design: Corner/validations/offer_creation_rejects_a_degenerate_window_a_mismatched_discount_shape_and_an_uncovered_region
    """
    partner = fx.active_partner(merchant_overrides={"region_codes": [RegionCode.CA]})
    merchant_id = partner["merchant"]["id"]
    agreement_id = partner["agreement"]["id"]

    refused = api_client.create_offer(
        F.offer_payload(
            agreement_id,
            title="Texas only deal",
            min_spend_cents=1000,
            region_codes=[RegionCode.TX],
        ),
        make_merchant_headers(merchant_id),
    )
    validate_error(refused, ApiErrorId.REGION_NOT_COVERED)

    accepted = api_client.create_offer(
        F.offer_payload(
            agreement_id,
            title="20 percent off dinner",
            min_spend_cents=1000,
            region_codes=[RegionCode.CA],
        ),
        make_merchant_headers(merchant_id),
    )
    offer = validate_success(accepted, expected_status=201)
    assert offer["status"] == OfferStatus.DRAFT.value
    assert offer["category"] == PerkCategory.DINING.value

    _, meta = validate_paginated(
        api_client.list_offers(
            make_merchant_headers(merchant_id),
            params={"agreement_id": agreement_id},
        )
    )
    assert meta["total_count"] == 1, "only the well-formed draft created a row"


# ── Corner/validations: eligibility batches and pagination bounds ────────────


def test_eligibility_batch_repeating_an_employee_ref_is_refused():
    """Two records sharing an `external_employee_ref` sink the whole batch.

    PRD: "No two elements of one batch may share an `external_employee_ref`; a collision is refused with `ERR_DUPLICATE_EMPLOYEE_REF`."

    Design: Corner/validations/eligibility_batch_rejects_duplicate_refs_and_listing_rejects_out_of_range_pagination
    """
    employer = fx.create_employer()
    employer_id = employer["id"]
    branded = fx.brand_storefront(employer_id)

    response = api_client.create_eligibility_file(
        employer_id,
        F.eligibility_file_payload(
            branded["version"],
            records=[
                F.eligibility_record("E-001"),
                F.eligibility_record(
                    "E-001", employment_status=EmploymentStatus.LEAVE
                ),
            ],
        ),
        make_employer_admin_headers(employer_id),
    )
    validate_error(response, ApiErrorId.DUPLICATE_EMPLOYEE_REF)

    after = fx.get_employer(employer_id)
    assert after["integration_status"] == IntegrationStatus.NOT_CONFIGURED.value
    assert after["version"] == branded["version"], (
        "a refused batch must not bump the employer's version"
    )
    _, meta = validate_paginated(
        api_client.list_eligibility_files(
            employer_id, make_employer_admin_headers(employer_id)
        )
    )
    assert meta["total_count"] == 0, "a refused batch must not create a file row"


def test_membership_listing_rejects_pagination_outside_its_bounds():
    """`limit` 0, `limit` 101 and a negative `offset` are all refused.

    PRD: "A `limit` outside the range 1 through 100 inclusive, a negative `offset`, or a non-integer value supplied for either one is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/eligibility_batch_rejects_duplicate_refs_and_listing_rejects_out_of_range_pagination
    """
    employer = fx.create_employer()
    employer_id = employer["id"]
    fx.brand_storefront(employer_id)
    headers = make_employer_admin_headers(employer_id)

    for params in (
        {"employer_id": employer_id, "limit": 0},
        {"employer_id": employer_id, "limit": 101},
        {"employer_id": employer_id, "offset": -1},
    ):
        validate_error(
            api_client.list_memberships(headers, params=params),
            ApiErrorId.INVALID_PAGINATION,
        )

    rows, meta = validate_paginated(
        api_client.list_memberships(
            headers, params={"employer_id": employer_id, "limit": 100, "offset": 0}
        )
    )
    assert rows == []
    assert_pagination_meta(meta, limit=100, offset=0, total_count=0, has_more=False)


# ── Corner/validations: one live lane per partner, category and region ───────


def test_second_agreement_in_an_open_lane_is_refused_while_another_region_opens():
    """A duplicate partner/category/region lane is refused; a new region is not.

    PRD: "Only one live lane may exist per partner, category and region combination: if an agreement already exists for that same triple in any of `DRAFT`, `PROVIDER_PROPOSED`, `MERCHANT_COUNTERED`, `ACCEPTED` or `ACTIVE`, the request is refused with `ERR_DUPLICATE_AGREEMENT`."

    Design: Corner/validations/second_agreement_in_the_same_lane_is_rejected_while_the_first_is_open
    """
    merchant = fx.create_merchant(region_codes=[RegionCode.CA, RegionCode.TX])
    merchant_id = merchant["id"]
    first = fx.create_agreement(
        merchant_id, category=PerkCategory.DINING, region_code=RegionCode.CA
    )
    assert first["status"] == "DRAFT"

    duplicate = api_client.create_agreement(
        F.agreement_payload(
            merchant_id, category=PerkCategory.DINING, region_code=RegionCode.CA
        ),
        make_partner_manager_headers(),
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_AGREEMENT)

    other_region = api_client.create_agreement(
        F.agreement_payload(
            merchant_id, category=PerkCategory.DINING, region_code=RegionCode.TX
        ),
        make_partner_manager_headers(),
    )
    opened = validate_success(other_region, expected_status=201)
    assert opened["region_code"] == RegionCode.TX.value
    assert opened["status"] == "DRAFT"

    _, meta = validate_paginated(
        api_client.list_agreements(
            make_partner_manager_headers(), params={"merchant_id": merchant_id}
        )
    )
    assert meta["total_count"] == 2, "only the two distinct lanes exist"


# ── Corner/validations: goodwill credit against the net charge ───────────────


def test_goodwill_credit_above_the_net_charge_is_refused_and_the_boundary_resolves():
    """A credit of `net_charged_cents` + 1 is refused; the exact net resolves.

    PRD: "A `MERCHANT_FAULT` resolution first checks the money: the requested `outcome_credit_cents` must be less than or equal to the redemption's `net_charged_cents`, or the resolution is refused with `ERR_CREDIT_EXCEEDS_NET` — the platform may not hand back more than the employee actually paid."

    Design: Corner/validations/goodwill_credit_equal_to_the_net_charge_resolves_while_one_cent_more_is_refused
    """
    setup = _open_dispute_on_verified_line()
    program = setup["program"]
    dispute_id = setup["dispute"]["id"]
    redemption_id = setup["redemption_id"]
    merchant_id = program["merchant"]["id"]
    employer_id = program["employer"]["id"]

    assert_line_economics(
        setup["redemption"], gross_amount_cents=5000, discount_amount_cents=1000,
        net_charged_cents=4000, commission_amount_cents=480,
        employer_share_cents=120, provider_net_cents=360,
    )
    fx.respond_dispute(
        dispute_id, merchant_id,
        response_note="Our terminal misfired that evening.",
        remedy_offered_cents=500,
    )

    refused = api_client.resolve_dispute(
        dispute_id,
        F.resolve_payload(DisputeOutcome.MERCHANT_FAULT, outcome_credit_cents=4001),
        make_admin_headers(),
    )
    validate_error(refused, ApiErrorId.CREDIT_EXCEEDS_NET)

    held = fx.get_dispute(dispute_id)
    assert held["status"] == "MERCHANT_RESPONDED"
    assert held["outcome_credit_cents"] is None

    resolved = fx.resolve_dispute(
        dispute_id, DisputeOutcome.MERCHANT_FAULT, outcome_credit_cents=4000
    )
    assert resolved["status"] == "RESOLVED_MERCHANT_FAULT"
    assert resolved["outcome_credit_cents"] == 4000
    assert resolved["default_judged"] is False

    redemption = fx.get_redemption(redemption_id)
    assert redemption["fulfillment_status"] == FulfillmentStatus.REFUNDED.value
    assert_iso_equals(
        redemption["refunded_at"], "2026-08-02T00:00:00Z", "redemption.refunded_at"
    )

    rows, meta = validate_paginated(
        api_client.list_redemption_ledger_entries(
            redemption_id, make_admin_headers(), params={"limit": 100}
        )
    )
    assert meta["total_count"] == 6
    assert_ledger_signature(rows, [
        (LedgerEntryType.COMMISSION_ACCRUAL.value, 480),
        (LedgerEntryType.EMPLOYER_SHARE.value, -120),
        (LedgerEntryType.COMMISSION_REVERSAL.value, -480),
        (LedgerEntryType.EMPLOYER_SHARE_REVERSAL.value, 120),
        (LedgerEntryType.DISPUTE_CREDIT.value, -4000),
        (LedgerEntryType.DISPUTE_CREDIT_RECOVERY.value, 4000),
    ])
    assert_ledger_nets_to_zero(rows)

    assert fx.get_merchant(merchant_id)["accrued_commission_payable_cents"] == 4000
    assert fx.get_employer(employer_id)["accrued_share_cents"] == 0


# ── Corner/validations: employer privacy on redemption and dispute reads ─────


def test_employer_admin_redemption_and_dispute_reads_are_privacy_restricted():
    """An `EmployerAdmin` may read neither a redemption, the collection, nor a dispute.

    PRD: "An `EmployerAdmin` is refused outright — with `ERR_PRIVACY_RESTRICTED` — when it asks for an individual redemption by identifier, when it asks for the redemption collection at all, or when it asks for an individual dispute by identifier."

    Design: Corner/validations/employer_admin_redemption_read_returns_403_privacy_even_for_an_absent_id
    """
    employer = fx.create_employer()
    headers = make_employer_admin_headers(employer["id"])

    validate_error(
        api_client.get_redemption(NON_EXISTENT_UUID, headers),
        ApiErrorId.PRIVACY_RESTRICTED,
    )
    validate_error(
        api_client.list_redemptions(headers), ApiErrorId.PRIVACY_RESTRICTED
    )
    validate_error(
        api_client.get_dispute(NON_EXISTENT_UUID, headers),
        ApiErrorId.PRIVACY_RESTRICTED,
    )


def test_privacy_refusal_hides_whether_the_redemption_exists():
    """The privacy refusal is decided before existence, unlike a `PlatformAdmin` read.

    PRD: "This refusal is evaluated **before** existence is checked, precisely so that a probing employer cannot distinguish a redemption that exists from one that does not."

    Design: Corner/validations/employer_admin_redemption_read_returns_403_privacy_even_for_an_absent_id
    """
    program = _program(record_count=1)
    employer_id = program["employer"]["id"]
    created, _ = _verify_line(program, program["memberships"][0]["id"])

    employer_headers = make_employer_admin_headers(employer_id)
    validate_error(
        api_client.get_redemption(created["id"], employer_headers),
        ApiErrorId.PRIVACY_RESTRICTED,
    )
    validate_error(
        api_client.get_redemption(NON_EXISTENT_UUID, employer_headers),
        ApiErrorId.PRIVACY_RESTRICTED,
    )
    validate_error(
        api_client.get_redemption(NON_EXISTENT_UUID, make_admin_headers()),
        ApiErrorId.REDEMPTION_NOT_FOUND,
    )


def _member(memberships, external_employee_ref):
    """The membership row carrying `external_employee_ref`."""
    for membership in memberships:
        if membership["external_employee_ref"] == external_employee_ref:
            return membership
    raise AssertionError(
        f"no membership for {external_employee_ref!r}; got "
        f"{[m['external_employee_ref'] for m in memberships]}"
    )


# ── Corner/validations: the reservation check sequence ───────────────────────


def test_reservation_reads_posture_then_membership_status_then_region():
    """A `SETUP` programme, a revoked member and an uncovered region each stop reservation.

    PRD: "Reservation performs exactly this sequence of checks, in this order, stopping at the first failure: the acting or referenced partner must not be `SUSPENDED` or `TERMINATED` (`ERR_MERCHANT_SUSPENDED`); the redeeming membership's `status` must be `ELIGIBLE` and its `employment_status` must not be `TERMINATED` (`ERR_MEMBERSHIP_NOT_ELIGIBLE`); the employer's `program_posture` must not be `SETUP` (`ERR_PROGRAM_NOT_LIVE`), must not be `FROZEN` (`ERR_PROGRAM_FROZEN`) and must not be `RESTRICTED` (`ERR_PROGRAM_RESTRICTED`), so only a `LIVE` programme accepts a new reservation; the membership's `region_code` must be a member of the offer's `region_codes` (`ERR_REGION_NOT_COVERED`); the logical clock must fall at or after the offer's `window_start` and strictly before its `window_end` (`ERR_OFFER_WINDOW_CLOSED`); the clock must likewise fall at or after the membership's `eligibility_valid_from` and strictly before its `eligibility_valid_until` (`ERR_MEMBERSHIP_WINDOW_CLOSED`); the offer must not be sold out, meaning that if `inventory_limit` is not null the sum of `inventory_reserved` and `inventory_redeemed` must be strictly below it (`ERR_OFFER_SOLD_OUT`); and the membership must not already hold `per_member_limit` redemptions on this same offer counting only those whose `verification_status` is `PENDING` or `VERIFIED` (`ERR_PER_MEMBER_LIMIT`)."

    Design: Corner/validations/redemption_creation_reads_the_employer_posture_the_membership_status_and_the_region_overlap
    """
    partner = fx.active_partner()
    merchant_id = partner["merchant"]["id"]
    employer = fx.create_employer(employee_count_declared=3)
    employer_id = employer["id"]
    fx.brand_storefront(employer_id, featured_categories=[PerkCategory.DINING.value])
    fx.sync_eligibility(employer_id, records=[
        F.eligibility_record("E-001"),
        F.eligibility_record("E-002"),
        F.eligibility_record("E-003", region_code=RegionCode.TX),
    ])
    offer = fx.approved_offer(
        partner["agreement"]["id"], merchant_id,
        region_codes=[RegionCode.CA], min_spend_cents=1000,
    )
    memberships = fx.list_memberships(employer_id)
    member_one = _member(memberships, "E-001")
    member_two = _member(memberships, "E-002")
    member_three = _member(memberships, "E-003")

    staged = fx.get_employer(employer_id)
    assert staged["storefront_status"] == StorefrontStatus.BRANDED.value
    assert staged["integration_status"] == IntegrationStatus.SYNCED.value
    assert staged["program_posture"] == ProgramPosture.SETUP.value

    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer["id"], member_one["id"]),
            make_employee_headers(member_one["id"]),
        ),
        ApiErrorId.PROGRAM_NOT_LIVE,
    )

    published = fx.publish_storefront(employer_id)
    assert published["program_posture"] == ProgramPosture.LIVE.value

    revoked = fx.set_employment_status(
        member_one["id"], employer_id, EmploymentStatus.TERMINATED
    )
    assert revoked["status"] == MembershipStatus.REVOKED.value
    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer["id"], member_one["id"]),
            make_employee_headers(member_one["id"]),
        ),
        ApiErrorId.MEMBERSHIP_NOT_ELIGIBLE,
    )

    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer["id"], member_three["id"]),
            make_employee_headers(member_three["id"]),
        ),
        ApiErrorId.REGION_NOT_COVERED,
    )

    accepted = validate_success(
        api_client.create_redemption(
            F.redemption_payload(offer["id"], member_two["id"]),
            make_employee_headers(member_two["id"]),
        ),
        expected_status=201,
    )
    assert accepted["verification_status"] == VerificationStatus.PENDING.value
    assert accepted["fulfillment_status"] == FulfillmentStatus.AWAITING.value
    assert accepted["employer_id"] == employer_id
    assert accepted["merchant_id"] == merchant_id

    assert fx.get_offer(offer["id"])["inventory_reserved"] == 1


def test_membership_and_offer_windows_close_on_their_exclusive_upper_bound():
    """A window whose upper bound equals the clock is already closed.

    PRD: "Reservation performs exactly this sequence of checks, in this order, stopping at the first failure: the acting or referenced partner must not be `SUSPENDED` or `TERMINATED` (`ERR_MERCHANT_SUSPENDED`); the redeeming membership's `status` must be `ELIGIBLE` and its `employment_status` must not be `TERMINATED` (`ERR_MEMBERSHIP_NOT_ELIGIBLE`); the employer's `program_posture` must not be `SETUP` (`ERR_PROGRAM_NOT_LIVE`), must not be `FROZEN` (`ERR_PROGRAM_FROZEN`) and must not be `RESTRICTED` (`ERR_PROGRAM_RESTRICTED`), so only a `LIVE` programme accepts a new reservation; the membership's `region_code` must be a member of the offer's `region_codes` (`ERR_REGION_NOT_COVERED`); the logical clock must fall at or after the offer's `window_start` and strictly before its `window_end` (`ERR_OFFER_WINDOW_CLOSED`); the clock must likewise fall at or after the membership's `eligibility_valid_from` and strictly before its `eligibility_valid_until` (`ERR_MEMBERSHIP_WINDOW_CLOSED`); the offer must not be sold out, meaning that if `inventory_limit` is not null the sum of `inventory_reserved` and `inventory_redeemed` must be strictly below it (`ERR_OFFER_SOLD_OUT`); and the membership must not already hold `per_member_limit` redemptions on this same offer counting only those whose `verification_status` is `PENDING` or `VERIFIED` (`ERR_PER_MEMBER_LIMIT`)."

    Design: Corner/validations/membership_and_offer_windows_close_on_their_exclusive_upper_bound
    """
    program = _program(
        offer_overrides={"window_end": "2026-09-01T00:00:00Z"},
        records=[
            F.eligibility_record(
                "E-001", eligibility_valid_until="2026-08-20T00:00:00Z"
            ),
            F.eligibility_record("E-002"),
        ],
    )
    offer_id = program["offer"]["id"]
    employer_id = program["employer"]["id"]
    member_one = _member(program["memberships"], "E-001")
    member_two = _member(program["memberships"], "E-002")

    fx.set_clock("2026-08-20T00:00:00Z")
    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer_id, member_one["id"]),
            make_employee_headers(member_one["id"]),
        ),
        ApiErrorId.MEMBERSHIP_WINDOW_CLOSED,
    )
    reserved = validate_success(
        api_client.create_redemption(
            F.redemption_payload(offer_id, member_two["id"]),
            make_employee_headers(member_two["id"]),
        ),
        expected_status=201,
    )
    assert_iso_equals(
        reserved["created_at"], "2026-08-20T00:00:00Z", "redemption.created_at"
    )

    fx.set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer_id, member_two["id"]),
            make_employee_headers(member_two["id"]),
        ),
        ApiErrorId.OFFER_WINDOW_CLOSED,
    )

    offer = fx.get_offer(offer_id)
    assert offer["status"] == OfferStatus.ACTIVE.value
    assert offer["inventory_reserved"] == 1
    assert fx.get_employer(employer_id)["eligible_headcount"] == 1


def test_per_member_limit_counts_only_pending_and_verified_redemptions():
    """A voided redemption frees the member's single slot on the offer.

    PRD: "Reservation performs exactly this sequence of checks, in this order, stopping at the first failure: the acting or referenced partner must not be `SUSPENDED` or `TERMINATED` (`ERR_MERCHANT_SUSPENDED`); the redeeming membership's `status` must be `ELIGIBLE` and its `employment_status` must not be `TERMINATED` (`ERR_MEMBERSHIP_NOT_ELIGIBLE`); the employer's `program_posture` must not be `SETUP` (`ERR_PROGRAM_NOT_LIVE`), must not be `FROZEN` (`ERR_PROGRAM_FROZEN`) and must not be `RESTRICTED` (`ERR_PROGRAM_RESTRICTED`), so only a `LIVE` programme accepts a new reservation; the membership's `region_code` must be a member of the offer's `region_codes` (`ERR_REGION_NOT_COVERED`); the logical clock must fall at or after the offer's `window_start` and strictly before its `window_end` (`ERR_OFFER_WINDOW_CLOSED`); the clock must likewise fall at or after the membership's `eligibility_valid_from` and strictly before its `eligibility_valid_until` (`ERR_MEMBERSHIP_WINDOW_CLOSED`); the offer must not be sold out, meaning that if `inventory_limit` is not null the sum of `inventory_reserved` and `inventory_redeemed` must be strictly below it (`ERR_OFFER_SOLD_OUT`); and the membership must not already hold `per_member_limit` redemptions on this same offer counting only those whose `verification_status` is `PENDING` or `VERIFIED` (`ERR_PER_MEMBER_LIMIT`)."

    Design: Corner/validations/per_member_limit_counts_only_live_redemptions_of_that_membership
    """
    program = _program(record_count=1)
    offer_id = program["offer"]["id"]
    membership_id = program["memberships"][0]["id"]
    assert program["offer"]["per_member_limit"] == 1

    first = fx.create_redemption(offer_id, membership_id)
    assert first["verification_status"] == VerificationStatus.PENDING.value

    validate_error(
        api_client.create_redemption(
            F.redemption_payload(offer_id, membership_id),
            make_employee_headers(membership_id),
        ),
        ApiErrorId.PER_MEMBER_LIMIT,
    )

    voided = fx.void_redemption(first["id"], membership_id=membership_id)
    assert voided["verification_status"] == VerificationStatus.VOID.value
    assert voided["void_reason"] == VoidReason.MEMBER_CANCELLED.value

    third = validate_success(
        api_client.create_redemption(
            F.redemption_payload(offer_id, membership_id),
            make_employee_headers(membership_id),
        ),
        expected_status=201,
    )
    assert third["verification_status"] == VerificationStatus.PENDING.value

    offer = fx.get_offer(offer_id)
    assert offer["inventory_reserved"] == 1
    assert offer["inventory_redeemed"] == 0


def _two_verified_lines():
    """Two 5,000-cent verified lines, one on 2026-08-01 and one on 2026-08-15."""
    program = _program(record_count=2)
    member_one = _member(program["memberships"], "EMP-0001")
    member_two = _member(program["memberships"], "EMP-0002")
    first_created, first = _verify_line(program, member_one["id"])
    fx.set_clock("2026-08-15T00:00:00Z")
    second_created, second = _verify_line(program, member_two["id"])
    return {
        "program": program,
        "members": (member_one, member_two),
        "first": first,
        "first_id": first_created["id"],
        "second": second,
        "second_id": second_created["id"],
    }


# ── Corner/validations: exclusive filing and period boundaries ───────────────


def test_dispute_filing_closes_exactly_thirty_days_after_verification():
    """A filing at `verified_at` plus 30 days is already too late.

    PRD: "The redemption's `verification_status` must be `VERIFIED` — a `PENDING`, `FAILED` or `VOID` redemption has no fulfilment to dispute — and the logical clock must be strictly earlier than `verified_at` plus 30 days, or the filing is refused with `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Corner/validations/dispute_filing_window_and_statement_period_boundaries_are_both_exclusive
    """
    setup = _two_verified_lines()
    member_one, member_two = setup["members"]
    assert_iso_equals(
        setup["first"]["verified_at"], "2026-08-01T00:00:00Z", "verified_at"
    )

    fx.set_clock("2026-08-31T00:00:00Z")
    validate_error(
        api_client.create_dispute(
            setup["first_id"], F.dispute_payload(reason=DisputeReason.NOT_HONORED),
            make_employee_headers(member_one["id"]),
        ),
        ApiErrorId.DISPUTE_WINDOW_CLOSED,
    )

    filed = validate_success(
        api_client.create_dispute(
            setup["second_id"], F.dispute_payload(reason=DisputeReason.NOT_HONORED),
            make_employee_headers(member_two["id"]),
        ),
        expected_status=201,
    )
    assert filed["status"] == "OPEN"
    assert_iso_equals(
        filed["response_deadline_at"], "2026-09-05T00:00:00Z",
        "dispute.response_deadline_at",
    )


def test_statement_finalization_waits_for_the_period_end_to_pass():
    """A period is closed only strictly after its `period_end`.

    PRD: "The period must also be closed: the `period_end` must lie strictly in the past relative to the logical clock, and while the clock is at or before `period_end` the call is refused with `ERR_PERIOD_NOT_CLOSED`."

    Design: Corner/validations/dispute_filing_window_and_statement_period_boundaries_are_both_exclusive
    """
    setup = _two_verified_lines()
    employer_id = setup["program"]["employer"]["id"]

    fx.set_clock("2026-08-31T00:00:00Z")
    statement = fx.create_statement(
        employer_id, period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z", basis=StatementBasis.ACCRUAL,
    )
    validate_error(
        api_client.finalize_statement(statement["id"], make_partner_manager_headers()),
        ApiErrorId.PERIOD_NOT_CLOSED,
    )

    fx.set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api_client.finalize_statement(statement["id"], make_partner_manager_headers()),
        ApiErrorId.PERIOD_NOT_CLOSED,
    )

    fx.set_clock("2026-09-02T00:00:00Z")
    finalized = fx.finalize_statement(statement["id"])
    assert finalized["status"] == StatementStatus.FINALIZED.value
    assert finalized["included_redemption_count"] == 2
    assert finalized["gross_commission_cents"] == 960
    assert finalized["employer_share_cents"] == 240
    assert finalized["provider_retained_cents"] == 720


# ── Corner/validations: the category coverage floor ──────────────────────────


def test_category_coverage_floor_counts_active_agreements_across_partners():
    """The floor looks at the whole category/region lane, not at one partner.

    PRD: "Termination is refused with `ERR_CATEGORY_COVERAGE_FLOOR` when, after this agreement leaves `ACTIVE`, the number of remaining `ACTIVE` agreements for the same `category` and `region_code` pair would be zero **and** at least one employer still depends on that pairing — meaning an employer whose `program_posture` is `LIVE`, whose `region_code` equals the agreement's region, and whose `featured_categories` list contains the agreement's category."

    Design: Corner/validations/category_coverage_floor_counts_agreements_across_merchants
    """
    employer = fx.live_employer(record_count=1)
    employer_id = employer["employer"]["id"]
    assert employer["employer"]["program_posture"] == ProgramPosture.LIVE.value

    partner_a = fx.active_partner(
        merchant_overrides={
            "legal_name": "Alpha Diner",
            "contact_email": "deals@alphadiner.example",
        }
    )
    agreement_a = partner_a["agreement"]["id"]

    validate_error(
        api_client.terminate_agreement(
            agreement_a, F.terminate_payload(terminated_reason="PARTNER_EXIT"),
            make_partner_manager_headers(),
        ),
        ApiErrorId.CATEGORY_COVERAGE_FLOOR,
    )

    partner_b = fx.active_partner(
        merchant_overrides={
            "legal_name": "Beta Bistro",
            "contact_email": "deals@betabistro.example",
        }
    )
    agreement_b = partner_b["agreement"]["id"]

    terminated_a = validate_success(
        api_client.terminate_agreement(
            agreement_a, F.terminate_payload(terminated_reason="PARTNER_EXIT"),
            make_partner_manager_headers(),
        )
    )
    assert terminated_a["status"] == "TERMINATED"

    validate_error(
        api_client.terminate_agreement(
            agreement_b, F.terminate_payload(terminated_reason="PARTNER_EXIT"),
            make_partner_manager_headers(),
        ),
        ApiErrorId.CATEGORY_COVERAGE_FLOOR,
    )

    frozen = fx.suspend_storefront(employer_id)
    assert frozen["program_posture"] == ProgramPosture.FROZEN.value

    terminated_b = validate_success(
        api_client.terminate_agreement(
            agreement_b, F.terminate_payload(terminated_reason="PARTNER_EXIT"),
            make_partner_manager_headers(),
        )
    )
    assert terminated_b["status"] == "TERMINATED"
    assert terminated_b["terminated_reason"] == "PARTNER_EXIT"


# ── Corner/validations: the employer revenue-share flag ──────────────────────


def test_employer_share_is_zero_when_revenue_share_is_disabled():
    """A disabled flag zeroes the share line even with a negotiated share rate.

    PRD: "`employer_share_cents` is 0 whenever the employer's `revenue_share_enabled` is false, regardless of what the agreement's `employer_revenue_share_bps` says."

    Design: Corner/validations/employer_revenue_share_flag_decides_whether_the_share_line_exists
    """
    program = _program(record_count=2, revenue_share_enabled=False)
    assert program["agreement"]["employer_revenue_share_bps"] == 2500
    membership_id = _member(program["memberships"], "EMP-0001")["id"]

    created, verified = _verify_line(program, membership_id, 8396)
    assert_line_economics(
        verified, gross_amount_cents=8396, discount_amount_cents=1679,
        net_charged_cents=6717, commission_amount_cents=806,
        employer_share_cents=0, provider_net_cents=806,
    )

    rows, meta = validate_paginated(
        api_client.list_redemption_ledger_entries(
            created["id"], make_admin_headers(), params={"limit": 100}
        )
    )
    assert meta["total_count"] == 1
    assert_ledger_signature(rows, [(LedgerEntryType.COMMISSION_ACCRUAL.value, 806)])
    assert fx.get_employer(program["employer"]["id"])["accrued_share_cents"] == 0


def test_enabling_revenue_share_leaves_an_already_verified_line_untouched():
    """The flag is read at verification, so flipping it is not retroactive.

    PRD: "An `EmployerAdmin` or a `PlatformAdmin` may later adjust `revenue_share_enabled`, `privacy_min_cohort_size` and `employee_count_declared`; because `revenue_share_enabled` is read at verification time, flipping it never rewrites the `employer_share_cents` of a redemption that has already been verified."

    Design: Corner/validations/employer_revenue_share_flag_decides_whether_the_share_line_exists
    """
    program = _program(record_count=2, revenue_share_enabled=False)
    employer_id = program["employer"]["id"]
    first_member = _member(program["memberships"], "EMP-0001")["id"]
    second_member = _member(program["memberships"], "EMP-0002")["id"]

    first_created, _ = _verify_line(program, first_member, 8396)

    enabled = validate_success(
        api_client.update_employer(
            employer_id,
            F.employer_update_payload(revenue_share_enabled=True),
            make_employer_admin_headers(employer_id),
        )
    )
    assert enabled["revenue_share_enabled"] is True

    _, second = _verify_line(program, second_member, 8396)
    assert_line_economics(
        second, gross_amount_cents=8396, discount_amount_cents=1679,
        net_charged_cents=6717, commission_amount_cents=806,
        employer_share_cents=202, provider_net_cents=604,
    )
    assert fx.get_employer(employer_id)["accrued_share_cents"] == 202

    first = fx.get_redemption(first_created["id"])
    assert first["employer_share_cents"] == 0
    assert first["provider_net_cents"] == 806


# ── Corner/validations: information requests on a dispute ────────────────────


def test_each_information_request_extends_the_deadline_from_the_clock():
    """Each request restamps `response_deadline_at` at the clock plus 120 hours.

    PRD: "The request moves the dispute `MERCHANT_RESPONDED → INFO_REQUESTED`, raises `info_request_count` by 1, extends `response_deadline_at` to the logical clock plus a fresh 120 hours, and increments `version`."

    Design: Corner/validations/dispute_information_requests_are_capped_at_two_and_each_one_extends_the_deadline
    """
    setup = _open_dispute_on_verified_line()
    dispute_id = setup["dispute"]["id"]
    merchant_id = setup["program"]["merchant"]["id"]
    assert_iso_equals(
        setup["dispute"]["response_deadline_at"], "2026-08-07T00:00:00Z",
        "dispute.response_deadline_at",
    )

    responded = fx.respond_dispute(dispute_id, merchant_id)
    assert responded["status"] == "MERCHANT_RESPONDED"

    fx.set_clock("2026-08-03T00:00:00Z")
    first_request = fx.request_dispute_info(dispute_id)
    assert first_request["status"] == "INFO_REQUESTED"
    assert first_request["info_request_count"] == 1
    assert_iso_equals(
        first_request["response_deadline_at"], "2026-08-08T00:00:00Z",
        "dispute.response_deadline_at",
    )

    fx.respond_dispute(dispute_id, merchant_id)
    fx.set_clock("2026-08-04T00:00:00Z")
    second_request = fx.request_dispute_info(dispute_id)
    assert second_request["status"] == "INFO_REQUESTED"
    assert second_request["info_request_count"] == 2
    assert_iso_equals(
        second_request["response_deadline_at"], "2026-08-09T00:00:00Z",
        "dispute.response_deadline_at",
    )


def test_third_information_request_is_refused_and_the_dispute_resolves_as_it_stands():
    """Two information requests exhaust the allowance.

    PRD: "When `info_request_count` has already reached 2 a third request is refused with `ERR_MAX_INFO_REQUESTS`, and the dispute must then be resolved on the record as it stands."

    Design: Corner/validations/dispute_information_requests_are_capped_at_two_and_each_one_extends_the_deadline
    """
    setup = _open_dispute_on_verified_line()
    dispute_id = setup["dispute"]["id"]
    merchant_id = setup["program"]["merchant"]["id"]
    redemption_id = setup["redemption_id"]

    fx.respond_dispute(dispute_id, merchant_id)
    fx.set_clock("2026-08-03T00:00:00Z")
    fx.request_dispute_info(dispute_id)
    fx.respond_dispute(dispute_id, merchant_id)
    fx.set_clock("2026-08-04T00:00:00Z")
    fx.request_dispute_info(dispute_id)
    responded = fx.respond_dispute(dispute_id, merchant_id)
    assert responded["status"] == "MERCHANT_RESPONDED"
    assert responded["info_request_count"] == 2

    validate_error(
        api_client.request_dispute_info(dispute_id, make_admin_headers()),
        ApiErrorId.MAX_INFO_REQUESTS,
    )

    resolved = fx.resolve_dispute(dispute_id, DisputeOutcome.NO_FAULT)
    assert resolved["status"] == "RESOLVED_NO_FAULT"
    assert resolved["outcome_credit_cents"] == 0
    assert resolved["default_judged"] is False

    redemption = fx.get_redemption(redemption_id)
    assert redemption["fulfillment_status"] == FulfillmentStatus.FULFILLED.value
    assert_iso_equals(
        redemption["fulfilled_at"], "2026-08-04T00:00:00Z", "redemption.fulfilled_at"
    )

    merchant = fx.get_merchant(merchant_id)
    assert merchant["fault_event_count"] == 0
    assert merchant["accrued_commission_payable_cents"] == 480

    _, meta = validate_paginated(
        api_client.list_redemption_ledger_entries(
            redemption_id, make_admin_headers(), params={"limit": 100}
        )
    )
    assert meta["total_count"] == 2, "a NO_FAULT resolution writes no ledger entry"


# ── Corner/validations: the verification check order ─────────────────────────


def test_verification_reports_minimum_spend_before_an_invalid_token():
    """An undershooting ticket with a wrong token fails on the minimum spend.

    PRD: "The minimum-spend check runs **before** the verification-token check, so a verification request that both undershoots the offer's minimum and carries a wrong token fails with `ERR_MIN_SPEND_NOT_MET`."

    Design: Corner/validations/verification_checks_minimum_spend_before_the_token_and_the_token_before_the_audit_score
    """
    program = _program(record_count=1)
    membership_id = program["memberships"][0]["id"]
    merchant_id = program["merchant"]["id"]
    created = fx.create_redemption(program["offer"]["id"], membership_id)
    assert created["screening_risk_score"] == 0

    validate_error(
        api_client.verify_redemption(
            created["id"], F.verify_payload("not-the-minted-token", 500),
            make_merchant_headers(merchant_id),
        ),
        ApiErrorId.MIN_SPEND_NOT_MET,
    )

    held = fx.get_redemption(created["id"])
    assert held["verification_status"] == VerificationStatus.PENDING.value
    assert held["audit_risk_score"] is None


def test_verification_reports_an_invalid_token_before_scoring_the_audit():
    """A wrong token stops verification before the fraud score is recomputed.

    PRD: "The verified ticket is below the offer's minimum spend (`ERR_MIN_SPEND_NOT_MET`); then the echoed verification token does not match (`ERR_VERIFICATION_TOKEN_INVALID`); then the audit fraud score is at or above its block threshold (`ERR_FRAUD_RISK_BLOCKED`); then a goodwill credit exceeds the redemption's net charge (`ERR_CREDIT_EXCEEDS_NET`); then exclusivity is requested without negotiated exclusivity terms (`ERR_EXCLUSIVITY_TERMS_MISSING`)."

    Design: Corner/validations/verification_checks_minimum_spend_before_the_token_and_the_token_before_the_audit_score
    """
    program = _program(record_count=1)
    membership_id = program["memberships"][0]["id"]
    merchant_id = program["merchant"]["id"]
    created = fx.create_redemption(program["offer"]["id"], membership_id)

    validate_error(
        api_client.verify_redemption(
            created["id"], F.verify_payload("not-the-minted-token", 5000),
            make_merchant_headers(merchant_id),
        ),
        ApiErrorId.VERIFICATION_TOKEN_INVALID,
    )
    held = fx.get_redemption(created["id"])
    assert held["verification_status"] == VerificationStatus.PENDING.value
    assert held["audit_risk_score"] is None

    verified = fx.verify_redemption(created, merchant_id, 5000)
    assert verified["verification_status"] == VerificationStatus.VERIFIED.value
    assert verified["gross_amount_cents"] == 5000
    assert verified["commission_amount_cents"] == 480
    assert verified["audit_risk_score"] == 0
