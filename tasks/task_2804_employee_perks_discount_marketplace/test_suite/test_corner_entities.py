"""Entity-level corner tests for the Employee Perks & Discount Marketplace API.

Every test here translates one instance of the `entities` section of
SCAFFOLD_CORNER_DESIGN.yaml.  The harness restarts the server before each test,
so every test starts from an empty database with the logical clock at its
documented default of 2026-08-01T00:00:00Z (PRD §2.4).
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, is_valid_uuid, validate_error, validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId, api_client, constants as C, factories as F, fixtures,
)
from test_helpers.assertions import (
    assert_agreement_shape, assert_eligibility_file_shape, assert_employer_shape,
    assert_fields, assert_iso_equals, assert_membership_shape,
    assert_merchant_shape, assert_negotiation_round_shape, assert_nulls,
    assert_offer_shape, assert_ordered_by, assert_pagination_meta,
)
from test_helpers.factories import OMIT
from test_helpers.test_users import (
    make_admin_headers, make_employer_admin_headers, make_merchant_headers,
    make_partner_manager_headers,
)
from test_helpers.time_utils import iso_equal, plus_hours
from test_helpers.types import (
    AgreementStatus, EligibilityFileStatus, IntegrationStatus, MerchantStatus,
    OfferStatus, PerkCategory, ProgramPosture, ProposerRole, RegionCode,
    StorefrontStatus,
)

CLIENT_SUPPLIED_ID = "11111111-1111-4111-8111-111111111111"


def _merchant_count(headers=None):
    """`meta.total_count` of the merchant collection."""
    rows, meta = validate_paginated(
        api_client.list_merchants(headers or make_partner_manager_headers())
    )
    return meta["total_count"]


def _employer_count():
    rows, meta = validate_paginated(api_client.list_employers(make_admin_headers()))
    return meta["total_count"]


# ── entities / merchant_creation_returns_prospect_defaults_and_version_one ───


def test_merchant_creation_returns_prospect_with_every_counter_at_zero():
    """Registering a partner returns a PROSPECT row whose four counters are 0.

    PRD: "A newly registered partner begins in `PROSPECT` with `fault_event_count`, `fulfillment_failure_score`, `accrued_commission_payable_cents` and `active_agreement_count` all at 0, and with `suspended_at` null."

    Design: Corner/entities/merchant_creation_returns_prospect_defaults_and_version_one
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_merchant(
        F.merchant_payload(
            legal_name="Bistro Uno",
            contact_email="ops@bistrouno.example",
            primary_category=PerkCategory.DINING,
            region_codes=[RegionCode.CA],
        ),
        make_partner_manager_headers(),
    )
    merchant = validate_success(response, expected_status=201)

    assert_merchant_shape(merchant)
    assert_fields(merchant, {
        "status": MerchantStatus.PROSPECT.value,
        "fault_event_count": 0,
        "fulfillment_failure_score": 0,
        "accrued_commission_payable_cents": 0,
        "active_agreement_count": 0,
        "legal_name": "Bistro Uno",
        "contact_email": "ops@bistrouno.example",
        "primary_category": PerkCategory.DINING.value,
        "region_codes": [RegionCode.CA.value],
    }, "merchant")
    assert_nulls(merchant, ["suspended_at"], "merchant")
    assert_iso_equals(merchant["created_at"], C.DEFAULT_CLOCK, "merchant.created_at")
    assert_iso_equals(merchant["updated_at"], C.DEFAULT_CLOCK, "merchant.updated_at")


def test_merchant_creation_starts_the_row_at_version_one():
    """The first write of a merchant row leaves `version` at 1.

    PRD: "**`version`** (integer): a monotonically increasing integer that is incremented by exactly 1 on every mutation of the row."

    Design: Corner/entities/merchant_creation_returns_prospect_defaults_and_version_one
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_merchant(
        F.merchant_payload(legal_name="Bistro Uno"), make_partner_manager_headers()
    )
    merchant = validate_success(response, expected_status=201)

    assert merchant["version"] == 1, (
        f"a freshly created merchant must read version 1, got {merchant['version']}"
    )


# ── entities / merchant_retrieval_returns_the_stored_row_unchanged ───────────


def test_merchant_retrieval_returns_the_created_row_without_mutating_it():
    """Reading a merchant recomputes the decay score but writes nothing.

    PRD: "Reading a merchant recomputes `fulfillment_failure_score` against the current clock, so decay is observable without any write occurring."

    Design: Corner/entities/merchant_retrieval_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    created = fixtures.create_merchant(
        legal_name="Bistro Uno",
        contact_email="ops@bistrouno.example",
        primary_category=PerkCategory.DINING,
        region_codes=[RegionCode.CA],
    )

    response = api_client.get_merchant(created["id"], make_admin_headers())
    read = validate_success(response)

    assert_merchant_shape(read)
    assert_fields(read, {
        "id": created["id"],
        "primary_category": PerkCategory.DINING.value,
        "status": MerchantStatus.PROSPECT.value,
        "fulfillment_failure_score": 0,
        "version": created["version"],
    }, "merchant")
    assert iso_equal(read["updated_at"], created["updated_at"]), (
        "a read must not refresh updated_at: "
        f"{created['updated_at']!r} became {read['updated_at']!r}"
    )


# ── entities / merchant_listing_paginates_with_total_count_and_has_more ──────


def _three_merchants_one_hour_apart():
    """Bistro Uno (DINING/CA), Cafe Duo (DINING/CA) and Deli Tres (WELLNESS/TX).

    Each row is written at a distinct logical instant so that the documented
    `created_at` ascending order of PRD §2.3 is unambiguous.
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    first = fixtures.create_merchant(
        legal_name="Bistro Uno", contact_email="ops@bistrouno.example",
        primary_category=PerkCategory.DINING, region_codes=[RegionCode.CA],
    )
    fixtures.set_clock(plus_hours(C.DEFAULT_CLOCK, 1))
    second = fixtures.create_merchant(
        legal_name="Cafe Duo", contact_email="ops@cafeduo.example",
        primary_category=PerkCategory.DINING, region_codes=[RegionCode.CA],
    )
    fixtures.set_clock(plus_hours(C.DEFAULT_CLOCK, 2))
    third = fixtures.create_merchant(
        legal_name="Deli Tres", contact_email="ops@delitres.example",
        primary_category=PerkCategory.WELLNESS, region_codes=[RegionCode.TX],
    )
    return first, second, third


def test_merchant_listing_pages_with_total_count_and_has_more():
    """Two pages over three merchants carry the four pagination fields in meta.

    PRD: "For a list response, `response_type` is `"array"`, `data` is the bare JSON array of resource objects — so the first element is addressed as `$.data[0]` — and the four pagination fields `limit`, `offset`, `total_count` and `has_more` all appear inside `meta` alongside the request identifiers."

    Design: Corner/entities/merchant_listing_paginates_with_total_count_and_has_more
    """
    first, second, third = _three_merchants_one_hour_apart()

    page_one, meta_one = validate_paginated(
        api_client.list_merchants(
            make_partner_manager_headers(), params={"limit": 2, "offset": 0}
        )
    )
    assert len(page_one) == 2, f"limit=2 must return 2 rows, got {len(page_one)}"
    assert_pagination_meta(meta_one, limit=2, offset=0, total_count=3, has_more=True)

    page_two, meta_two = validate_paginated(
        api_client.list_merchants(
            make_partner_manager_headers(), params={"limit": 2, "offset": 2}
        )
    )
    assert len(page_two) == 1, f"the tail page must hold 1 row, got {len(page_two)}"
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)
    assert page_two[0]["id"] == third["id"]


def test_merchant_listing_is_ordered_by_created_at_ascending():
    """The merchant collection defaults to `created_at` ascending order.

    PRD: "Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order."

    Design: Corner/entities/merchant_listing_paginates_with_total_count_and_has_more
    """
    first, second, third = _three_merchants_one_hour_apart()

    rows, meta = validate_paginated(
        api_client.list_merchants(
            make_partner_manager_headers(), params={"limit": C.MAX_PAGE_LIMIT}
        )
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]
    assert_ordered_by(rows, "created_at")


def test_merchant_listing_filters_by_primary_category():
    """A `primary_category` filter narrows both the rows and `total_count`.

    PRD: "Partner listings may be narrowed by `status`, by `primary_category`, and by `region_code` — the last of which matches on membership of the partner's `region_codes` rather than on equality."

    Design: Corner/entities/merchant_listing_paginates_with_total_count_and_has_more
    """
    first, second, third = _three_merchants_one_hour_apart()

    rows, meta = validate_paginated(
        api_client.list_merchants(
            make_partner_manager_headers(),
            params={"primary_category": PerkCategory.WELLNESS.value},
        )
    )
    assert meta["total_count"] == 1, (
        f"one merchant is WELLNESS, got total_count {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [third["id"]]


# ── entities / absent_ids_return_each_entity_own_not_found_code ──────────────


def test_absent_path_ids_return_each_entity_own_not_found_code():
    """Eleven detail reads of one absent uuid each answer that entity's own 404.

    PRD: "**Existence.** Any path identifier or body foreign key that names no row, with the entity's own not-found code."

    Design: Corner/entities/absent_ids_return_each_entity_own_not_found_code
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    headers = make_admin_headers()

    validate_error(
        api_client.get_merchant(NON_EXISTENT_UUID, headers),
        ApiErrorId.MERCHANT_NOT_FOUND,
    )
    validate_error(
        api_client.get_agreement(NON_EXISTENT_UUID, headers),
        ApiErrorId.AGREEMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_employer(NON_EXISTENT_UUID, headers),
        ApiErrorId.EMPLOYER_NOT_FOUND,
    )
    validate_error(
        api_client.get_eligibility_file(NON_EXISTENT_UUID, headers),
        ApiErrorId.ELIGIBILITY_FILE_NOT_FOUND,
    )
    validate_error(
        api_client.get_membership(NON_EXISTENT_UUID, headers),
        ApiErrorId.MEMBERSHIP_NOT_FOUND,
    )
    validate_error(
        api_client.get_offer(NON_EXISTENT_UUID, headers),
        ApiErrorId.OFFER_NOT_FOUND,
    )
    validate_error(
        api_client.get_placement_slot(NON_EXISTENT_UUID, headers),
        ApiErrorId.PLACEMENT_SLOT_NOT_FOUND,
    )
    validate_error(
        api_client.get_redemption(NON_EXISTENT_UUID, headers),
        ApiErrorId.REDEMPTION_NOT_FOUND,
    )
    validate_error(
        api_client.get_dispute(NON_EXISTENT_UUID, headers),
        ApiErrorId.DISPUTE_NOT_FOUND,
    )
    validate_error(
        api_client.get_statement(NON_EXISTENT_UUID, headers),
        ApiErrorId.STATEMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_ledger_entry(NON_EXISTENT_UUID, headers),
        ApiErrorId.LEDGER_ENTRY_NOT_FOUND,
    )


# ── entities /
# merchant_creation_missing_required_primary_category_returns_validation_error ─


def test_merchant_creation_without_primary_category_is_rejected():
    """Omitting the required `primary_category` fails schema validation.

    PRD: "**Schema.** A required input field missing, null, blank, of the wrong type or outside its documented range (`ERR_VALIDATION`); then an enum-typed input carrying a value outside its permitted set (`ERR_INVALID_ENUM_VALUE`); then bad pagination parameters (`ERR_INVALID_PAGINATION`); then an interval whose end is at or before its start (`ERR_INVALID_WINDOW`); then a discount shape that contradicts its declared type (`ERR_DISCOUNT_SHAPE_MISMATCH`); then a region outside the merchant's footprint (`ERR_REGION_NOT_COVERED`); then two eligibility records sharing one employee reference (`ERR_DUPLICATE_EMPLOYEE_REF`)."

    Design: Corner/entities/merchant_creation_missing_required_primary_category_returns_validation_error
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_merchant(
        F.merchant_payload(
            legal_name="Bistro Uno",
            contact_email="ops@bistrouno.example",
            primary_category=OMIT,
            region_codes=[RegionCode.CA],
        ),
        make_partner_manager_headers(),
    )
    validate_error(response, ApiErrorId.VALIDATION)

    assert _merchant_count() == 0, "a refused registration must create no merchant"


def test_merchant_creation_with_an_empty_region_list_is_rejected():
    """An empty `region_codes` array breaks the non-empty footprint rule.

    PRD: "The region list must be non-empty and must not repeat a region."

    Design: Corner/entities/merchant_creation_missing_required_primary_category_returns_validation_error
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_merchant(
        F.merchant_payload(
            legal_name="Bistro Uno",
            contact_email="ops@bistrouno.example",
            primary_category=PerkCategory.DINING,
            region_codes=[],
        ),
        make_partner_manager_headers(),
    )
    validate_error(response, ApiErrorId.VALIDATION)

    assert _merchant_count() == 0, "a refused registration must create no merchant"


def test_merchant_creation_with_an_email_lacking_an_at_sign_is_rejected():
    """A `contact_email` without an `@` character is not a valid input.

    PRD: "A `PartnerManager` opens the commercial funnel by registering a merchant partner, supplying the partner's `legal_name` (between 1 and 200 characters), a `contact_email` for negotiation correspondence (which must contain an `@` character), the head-line `primary_category` the partner is being recruited for, and the `region_codes` the partner can actually fulfil in."

    Design: Corner/entities/merchant_creation_missing_required_primary_category_returns_validation_error
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_merchant(
        F.merchant_payload(
            legal_name="Bistro Uno",
            contact_email="no-at-sign.example",
            primary_category=PerkCategory.DINING,
            region_codes=[RegionCode.CA],
        ),
        make_partner_manager_headers(),
    )
    validate_error(response, ApiErrorId.VALIDATION)

    assert _merchant_count() == 0, "a refused registration must create no merchant"


# ── entities /
# employer_and_agreement_defaults_apply_when_optional_inputs_are_omitted ──────


def test_employer_creation_defaults_revenue_share_off_and_cohort_size_eight():
    """Omitting both optional settings yields false and a cohort floor of 8.

    PRD: "Two further settings may be supplied at registration or amended afterwards: `revenue_share_enabled`, which defaults to false, and `privacy_min_cohort_size`, which defaults to 8 and accepts any integer from 2 through 25 inclusive."

    Design: Corner/entities/employer_and_agreement_defaults_apply_when_optional_inputs_are_omitted
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_employer(
        F.employer_payload(
            name="Northwind Co", region_code=RegionCode.CA, employee_count_declared=40
        ),
        make_admin_headers(),
    )
    employer = validate_success(response, expected_status=201)

    assert employer["revenue_share_enabled"] is False, (
        f"revenue_share_enabled must default to false, got "
        f"{employer['revenue_share_enabled']!r}"
    )
    assert employer["privacy_min_cohort_size"] == C.DEFAULT_PRIVACY_MIN_COHORT_SIZE, (
        "privacy_min_cohort_size must default to 8, got "
        f"{employer['privacy_min_cohort_size']!r}"
    )


def test_employer_creation_starts_not_configured_draft_and_setup():
    """A new employer starts on both dimensions at their initial states.

    PRD: "A new employer starts with `integration_status` at `NOT_CONFIGURED`, `storefront_status` at `DRAFT` and the derived `program_posture` at `SETUP`; `brand_color_hex`, `logo_url`, `hero_headline`, `featured_categories`, `last_sync_at` and `suspension_reason` are all null, and `eligible_headcount` and `accrued_share_cents` are both 0."

    Design: Corner/entities/employer_and_agreement_defaults_apply_when_optional_inputs_are_omitted
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_employer(
        F.employer_payload(
            name="Northwind Co", region_code=RegionCode.CA, employee_count_declared=40
        ),
        make_admin_headers(),
    )
    employer = validate_success(response, expected_status=201)

    assert_employer_shape(employer)
    assert_fields(employer, {
        "integration_status": IntegrationStatus.NOT_CONFIGURED.value,
        "storefront_status": StorefrontStatus.DRAFT.value,
        "program_posture": ProgramPosture.SETUP.value,
        "eligible_headcount": 0,
        "accrued_share_cents": 0,
    }, "employer")
    assert_nulls(employer, [
        "brand_color_hex", "logo_url", "hero_headline", "featured_categories",
        "last_sync_at", "suspension_reason",
    ], "employer")


def test_agreement_creation_defaults_exclusivity_requested_to_false():
    """An agreement opened without `exclusivity_requested` is not exclusive.

    PRD: "Commercial terms live on a **PartnerAgreement**, and a `PartnerManager` opens one by naming the `merchant_id`, the `category` the agreement will cover, and the single `region_code` it applies to, optionally setting `exclusivity_requested` to true (it defaults to false)."

    Design: Corner/entities/employer_and_agreement_defaults_apply_when_optional_inputs_are_omitted
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant(
        legal_name="Bistro Uno", primary_category=PerkCategory.DINING,
        region_codes=[RegionCode.CA],
    )

    response = api_client.create_agreement(
        F.agreement_payload(
            merchant["id"], category=PerkCategory.DINING,
            region_code=RegionCode.CA, exclusivity_requested=OMIT,
        ),
        make_partner_manager_headers(),
    )
    agreement = validate_success(response, expected_status=201)

    assert agreement["exclusivity_requested"] is False, (
        "exclusivity_requested must default to false, got "
        f"{agreement['exclusivity_requested']!r}"
    )


def test_fresh_agreement_starts_in_draft_with_null_standing_terms():
    """A newly opened agreement is DRAFT with no negotiated term yet.

    PRD: "A fresh agreement starts in `DRAFT` with `round_count` at 0 and every standing term — `commission_rate_bps`, `placement_fee_base_cents`, `employer_revenue_share_bps`, `exclusivity_window_start` and `exclusivity_window_end` — null, with `exclusivity_granted` false and with `accepted_by_role`, `activated_at` and `terminated_reason` all null."

    Design: Corner/entities/employer_and_agreement_defaults_apply_when_optional_inputs_are_omitted
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant(
        legal_name="Bistro Uno", primary_category=PerkCategory.DINING,
        region_codes=[RegionCode.CA],
    )

    response = api_client.create_agreement(
        F.agreement_payload(
            merchant["id"], category=PerkCategory.DINING, region_code=RegionCode.CA
        ),
        make_partner_manager_headers(),
    )
    agreement = validate_success(response, expected_status=201)

    assert_agreement_shape(agreement)
    assert_fields(agreement, {
        "merchant_id": merchant["id"],
        "status": AgreementStatus.DRAFT.value,
        "round_count": 0,
        "exclusivity_granted": False,
    }, "agreement")
    assert_nulls(agreement, [
        "commission_rate_bps", "placement_fee_base_cents",
        "employer_revenue_share_bps", "exclusivity_window_start",
        "exclusivity_window_end", "accepted_by_role", "activated_at",
        "terminated_reason",
    ], "agreement")


# ── entities /
# offer_merchant_id_and_category_are_computed_from_the_agreement_input_ignored ─


def test_offer_copies_merchant_and_category_from_its_agreement():
    """A drafted offer takes merchant and category from the agreement it names.

    PRD: "The offer's `merchant_id` and `category` are **copied from the referenced agreement** at creation and any client-supplied value for either is ignored; `category` is never rewritten thereafter, and neither is `merchant_id`."

    Design: Corner/entities/offer_merchant_id_and_category_are_computed_from_the_agreement_input_ignored
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    partner = fixtures.active_partner()
    merchant_id = partner["merchant"]["id"]
    agreement = partner["agreement"]
    other = fixtures.create_merchant(
        legal_name="Cafe Duo", contact_email="ops@cafeduo.example",
        primary_category=PerkCategory.WELLNESS, region_codes=[RegionCode.CA],
    )

    response = api_client.create_offer(
        F.offer_payload(
            agreement["id"],
            merchant_id=other["id"],
            category=PerkCategory.WELLNESS,
            title="20 percent off dinner",
            region_codes=[RegionCode.CA],
        ),
        make_merchant_headers(merchant_id),
    )
    offer = validate_success(response, expected_status=201)

    assert offer["merchant_id"] == merchant_id, (
        "the offer must carry the agreement's merchant, not the one in the payload"
    )
    assert offer["merchant_id"] != other["id"]
    assert offer["category"] == PerkCategory.DINING.value, (
        "the offer must carry the agreement's DINING category, not the payload's "
        f"WELLNESS, got {offer['category']!r}"
    )
    assert offer["agreement_id"] == agreement["id"]


def test_new_offer_lands_in_draft_with_empty_inventory_counts():
    """A drafted offer is DRAFT, not sold out and has nothing reserved.

    PRD: "A new offer lands in `DRAFT` with `inventory_reserved` and `inventory_redeemed` at 0, `sold_out` false, and `review_note`, `paused_reason` and `expired_at` all null."

    Design: Corner/entities/offer_merchant_id_and_category_are_computed_from_the_agreement_input_ignored
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    partner = fixtures.active_partner()

    response = api_client.create_offer(
        F.offer_payload(partner["agreement"]["id"], region_codes=[RegionCode.CA]),
        make_merchant_headers(partner["merchant"]["id"]),
    )
    offer = validate_success(response, expected_status=201)

    assert_offer_shape(offer)
    assert_fields(offer, {
        "status": OfferStatus.DRAFT.value,
        "inventory_reserved": 0,
        "inventory_redeemed": 0,
        "sold_out": False,
    }, "offer")
    assert_nulls(offer, ["review_note", "paused_reason", "expired_at"], "offer")


def test_offer_optional_inputs_default_to_zero_spend_and_one_per_member():
    """Omitted offer options mean no spend floor, no ceiling and one per member.

    PRD: "Optionally it supplies a `min_spend_cents` floor (defaulting to 0, accepted from 0 through 1,000,000), an `inventory_limit` (accepted from 1 through 1,000,000, or null to mean unlimited), and a `per_member_limit` (defaulting to 1, accepted from 1 through 50)."

    Design: Corner/entities/offer_merchant_id_and_category_are_computed_from_the_agreement_input_ignored
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    partner = fixtures.active_partner()

    response = api_client.create_offer(
        F.offer_payload(partner["agreement"]["id"], region_codes=[RegionCode.CA]),
        make_merchant_headers(partner["merchant"]["id"]),
    )
    offer = validate_success(response, expected_status=201)

    assert offer["min_spend_cents"] == C.DEFAULT_MIN_SPEND_CENTS, (
        f"min_spend_cents must default to 0, got {offer['min_spend_cents']!r}"
    )
    assert offer["per_member_limit"] == C.DEFAULT_PER_MEMBER_LIMIT, (
        f"per_member_limit must default to 1, got {offer['per_member_limit']!r}"
    )
    assert offer["inventory_limit"] is None, (
        f"an omitted inventory_limit means unlimited, got {offer['inventory_limit']!r}"
    )


# ── entities /
# employer_creation_ignores_client_supplied_id_and_version_input_ignored ──────


def test_employer_creation_mints_its_own_uuid_ignoring_a_client_supplied_id():
    """The server mints the employer `id` and discards the one in the payload.

    PRD: "**`id`** (string): a server-minted UUID. It carries no type prefix and no domain-flavoured decoration."

    Design: Corner/entities/employer_creation_ignores_client_supplied_id_and_version_input_ignored
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_employer(
        F.employer_payload(
            name="Northwind Co", region_code=RegionCode.CA,
            employee_count_declared=5, id=CLIENT_SUPPLIED_ID,
        ),
        make_admin_headers(),
    )
    employer = validate_success(response, expected_status=201)

    assert employer["id"] != CLIENT_SUPPLIED_ID, (
        "the client-supplied id must be ignored, not stored"
    )
    assert is_valid_uuid(employer["id"]), (
        f"the minted id must be a bare UUID, got {employer['id']!r}"
    )
    validate_success(api_client.get_employer(employer["id"], make_admin_headers()))
    validate_error(
        api_client.get_employer(CLIENT_SUPPLIED_ID, make_admin_headers()),
        ApiErrorId.EMPLOYER_NOT_FOUND,
    )


def test_employer_creation_stamps_created_at_from_the_logical_clock():
    """`created_at` comes from the logical clock, never from the request body.

    PRD: "**`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock when the row is first written."

    Design: Corner/entities/employer_creation_ignores_client_supplied_id_and_version_input_ignored
    """
    clock = "2026-08-09T13:45:30Z"
    fixtures.set_clock(clock)

    response = api_client.create_employer(
        F.employer_payload(
            name="Northwind Co", region_code=RegionCode.CA,
            employee_count_declared=5, created_at="2020-01-01T00:00:00Z",
        ),
        make_admin_headers(),
    )
    employer = validate_success(response, expected_status=201)

    assert_iso_equals(employer["created_at"], clock, "employer.created_at")
    assert_iso_equals(employer["updated_at"], clock, "employer.updated_at")


def test_employer_creation_ignores_a_client_supplied_version():
    """`version` is server-managed, so a payload version is discarded.

    PRD: "**`version`** (integer): a monotonically increasing integer that is incremented by exactly 1 on every mutation of the row."

    Design: Corner/entities/employer_creation_ignores_client_supplied_id_and_version_input_ignored
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_employer(
        F.employer_payload(
            name="Northwind Co", region_code=RegionCode.CA,
            employee_count_declared=5, version=77,
        ),
        make_admin_headers(),
    )
    employer = validate_success(response, expected_status=201)

    assert employer["version"] == 1, (
        f"a freshly created employer must read version 1, got {employer['version']}"
    )


def test_employer_creation_ignores_a_client_supplied_storefront_status():
    """A payload that claims PUBLISHED still creates a DRAFT storefront.

    PRD: "A new employer starts with `integration_status` at `NOT_CONFIGURED`, `storefront_status` at `DRAFT` and the derived `program_posture` at `SETUP`; `brand_color_hex`, `logo_url`, `hero_headline`, `featured_categories`, `last_sync_at` and `suspension_reason` are all null, and `eligible_headcount` and `accrued_share_cents` are both 0."

    Design: Corner/entities/employer_creation_ignores_client_supplied_id_and_version_input_ignored
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    response = api_client.create_employer(
        F.employer_payload(
            name="Northwind Co", region_code=RegionCode.CA,
            employee_count_declared=5,
            storefront_status=StorefrontStatus.PUBLISHED,
            integration_status=IntegrationStatus.SYNCED,
            program_posture=ProgramPosture.LIVE,
        ),
        make_admin_headers(),
    )
    employer = validate_success(response, expected_status=201)

    assert_fields(employer, {
        "storefront_status": StorefrontStatus.DRAFT.value,
        "integration_status": IntegrationStatus.NOT_CONFIGURED.value,
        "program_posture": ProgramPosture.SETUP.value,
    }, "employer")


# ── entities / enum_members_and_numeric_ranges_are_constrained_on_create ──────


def test_merchant_creation_rejects_values_outside_the_permitted_enums():
    """A bogus category or region code is an enum violation, not a validation one.

    PRD: "**Schema.** A required input field missing, null, blank, of the wrong type or outside its documented range (`ERR_VALIDATION`); then an enum-typed input carrying a value outside its permitted set (`ERR_INVALID_ENUM_VALUE`); then bad pagination parameters (`ERR_INVALID_PAGINATION`); then an interval whose end is at or before its start (`ERR_INVALID_WINDOW`); then a discount shape that contradicts its declared type (`ERR_DISCOUNT_SHAPE_MISMATCH`); then a region outside the merchant's footprint (`ERR_REGION_NOT_COVERED`); then two eligibility records sharing one employee reference (`ERR_DUPLICATE_EMPLOYEE_REF`)."

    Design: Corner/entities/enum_members_and_numeric_ranges_are_constrained_on_create
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    validate_error(
        api_client.create_merchant(
            F.merchant_payload(primary_category="SPACE_TRAVEL"),
            make_partner_manager_headers(),
        ),
        ApiErrorId.INVALID_ENUM_VALUE,
    )
    validate_error(
        api_client.create_merchant(
            F.merchant_payload(region_codes=["ZZ"]), make_partner_manager_headers()
        ),
        ApiErrorId.INVALID_ENUM_VALUE,
    )

    assert _merchant_count() == 0, "a rejected registration must not persist a merchant"


def test_employer_creation_rejects_numbers_outside_their_documented_ranges():
    """A cohort floor or headcount outside its range is a validation failure.

    PRD: "**Schema.** A required input field missing, null, blank, of the wrong type or outside its documented range (`ERR_VALIDATION`); then an enum-typed input carrying a value outside its permitted set (`ERR_INVALID_ENUM_VALUE`); then bad pagination parameters (`ERR_INVALID_PAGINATION`); then an interval whose end is at or before its start (`ERR_INVALID_WINDOW`); then a discount shape that contradicts its declared type (`ERR_DISCOUNT_SHAPE_MISMATCH`); then a region outside the merchant's footprint (`ERR_REGION_NOT_COVERED`); then two eligibility records sharing one employee reference (`ERR_DUPLICATE_EMPLOYEE_REF`)."

    Design: Corner/entities/enum_members_and_numeric_ranges_are_constrained_on_create
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    validate_error(
        api_client.create_employer(
            F.employer_payload(employee_count_declared=0), make_admin_headers()
        ),
        ApiErrorId.VALIDATION,
    )
    validate_error(
        api_client.create_employer(
            F.employer_payload(
                employee_count_declared=C.MAX_EMPLOYEE_COUNT_DECLARED + 1
            ),
            make_admin_headers(),
        ),
        ApiErrorId.VALIDATION,
    )
    validate_error(
        api_client.create_employer(
            F.employer_payload(
                privacy_min_cohort_size=C.MIN_PRIVACY_MIN_COHORT_SIZE - 1
            ),
            make_admin_headers(),
        ),
        ApiErrorId.VALIDATION,
    )
    validate_error(
        api_client.create_employer(
            F.employer_payload(
                privacy_min_cohort_size=C.MAX_PRIVACY_MIN_COHORT_SIZE + 1
            ),
            make_admin_headers(),
        ),
        ApiErrorId.VALIDATION,
    )

    assert _employer_count() == 0, "a rejected registration must not persist an employer"


# ── entities /
# negotiation_round_is_immutable_with_no_version_and_no_write_endpoint ────────


def test_negotiation_round_exposes_no_updated_at_and_no_version():
    """A round is an immutable fact, so it carries only `id` and `created_at`.

    PRD: "A negotiation round carries only `id` and `created_at`: rounds are immutable historical facts, so they have no `updated_at` and no `version`."

    Design: Corner/entities/negotiation_round_is_immutable_with_no_version_and_no_write_endpoint
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant()
    agreement = fixtures.create_agreement(merchant["id"])
    fixtures.propose_round(agreement, note="Opening terms")

    rows, _meta = validate_paginated(
        api_client.list_negotiation_rounds(
            agreement["id"], make_partner_manager_headers()
        )
    )

    assert len(rows) == 1, f"expected the one filed round, got {len(rows)}"
    assert_negotiation_round_shape(rows[0])
    assert "updated_at" not in rows[0], "a round must not expose updated_at"
    assert "version" not in rows[0], "a round must not expose version"


def test_first_negotiation_round_is_numbered_one_and_credited_to_the_partner_manager():
    """The opening round is round 1 and is attributed to `PARTNER_MANAGER`.

    PRD: "Each accepted proposal writes a new round whose `agreement_id` points at the agreement, whose `round_number` is the previous highest round number plus one — the first round is numbered 1 — and whose `proposer_role` is recorded as `PARTNER_MANAGER`."

    Design: Corner/entities/negotiation_round_is_immutable_with_no_version_and_no_write_endpoint
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant()
    agreement = fixtures.create_agreement(merchant["id"])
    fixtures.propose_round(agreement, note="Opening terms")

    rows, _meta = validate_paginated(
        api_client.list_negotiation_rounds(
            agreement["id"], make_partner_manager_headers()
        )
    )

    assert_fields(rows[0], {
        "agreement_id": agreement["id"],
        "round_number": 1,
        "proposer_role": ProposerRole.PARTNER_MANAGER.value,
    }, "negotiation round")


# ── entities /
# eligibility_file_and_membership_rows_belong_only_to_their_parent_employer ────


def test_eligibility_batch_records_its_parent_employer_and_starts_in_received():
    """A loaded batch names the employer it was loaded against and tallies nothing.

    PRD: "The batch itself is created in `RECEIVED` with its `employer_id` set, with `rejection_reason` and `applied_at` null, with `created_membership_count`, `updated_membership_count` and `suspended_membership_count` all 0, and with its three record tallies computed immediately."

    Design: Corner/entities/eligibility_file_and_membership_rows_belong_only_to_their_parent_employer
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    employer_a = fixtures.create_employer(name="Alpha Freight")
    employer_b = fixtures.create_employer(name="Beta Foods")

    batch = fixtures.load_eligibility_file(
        employer_a["id"], records=F.eligibility_records(2)
    )

    assert_eligibility_file_shape(batch)
    assert_fields(batch, {
        "employer_id": employer_a["id"],
        "status": EligibilityFileStatus.RECEIVED.value,
        "created_membership_count": 0,
        "updated_membership_count": 0,
        "suspended_membership_count": 0,
        "record_count": 2,
        "valid_record_count": 2,
        "invalid_record_count": 0,
    }, "eligibility file")
    assert_nulls(batch, ["rejection_reason", "applied_at"], "eligibility file")
    assert batch["employer_id"] != employer_b["id"], (
        "the batch must not be attributed to the other employer"
    )


def test_the_same_employee_ref_under_two_employers_yields_two_memberships():
    """`external_employee_ref` joins within one employer only, never across two.

    PRD: "Application walks the valid records **in `records` array order** and, for each one, either creates a new **EmployeeMembership** or rewrites the existing membership that already carries that `external_employee_ref` for this employer."

    Design: Corner/entities/eligibility_file_and_membership_rows_belong_only_to_their_parent_employer
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    employer_a = fixtures.create_employer(name="Alpha Freight")
    employer_b = fixtures.create_employer(name="Beta Foods")
    shared_records = F.eligibility_records(1)

    batch_a = fixtures.sync_eligibility(employer_a["id"], records=shared_records)
    batch_b = fixtures.sync_eligibility(employer_b["id"], records=shared_records)

    rows_a, meta_a = validate_paginated(api_client.list_memberships(
        make_admin_headers(), params={"employer_id": employer_a["id"]}
    ))
    rows_b, meta_b = validate_paginated(api_client.list_memberships(
        make_admin_headers(), params={"employer_id": employer_b["id"]}
    ))

    assert meta_a["total_count"] == 1, (
        f"employer A should own exactly one membership, got {meta_a['total_count']}"
    )
    assert meta_b["total_count"] == 1, (
        f"employer B should own exactly one membership, got {meta_b['total_count']}"
    )
    assert_membership_shape(rows_a[0])
    assert rows_a[0]["id"] != rows_b[0]["id"], (
        "the second employer's identical ref must create its own membership row"
    )
    assert_fields(rows_a[0], {
        "employer_id": employer_a["id"],
        "external_employee_ref": shared_records[0]["external_employee_ref"],
        "source_file_id": batch_a["id"],
    }, "membership A")
    assert_fields(rows_b[0], {
        "employer_id": employer_b["id"],
        "external_employee_ref": shared_records[0]["external_employee_ref"],
        "source_file_id": batch_b["id"],
    }, "membership B")


def test_membership_listing_filtered_by_employer_excludes_the_other_employer():
    """The `employer_id` filter narrows a membership listing to one employer.

    PRD: "Membership listings may be filtered by `employer_id`, `source_file_id`, `status`, `employment_status` and `region_code`; eligibility batch listings may be filtered by `status`."

    Design: Corner/entities/eligibility_file_and_membership_rows_belong_only_to_their_parent_employer
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    employer_a = fixtures.create_employer(name="Alpha Freight")
    employer_b = fixtures.create_employer(name="Beta Foods")
    fixtures.sync_eligibility(
        employer_a["id"], records=F.eligibility_records(2, prefix="ALPHA")
    )
    fixtures.sync_eligibility(
        employer_b["id"], records=F.eligibility_records(1, prefix="BETA")
    )

    rows, meta = validate_paginated(api_client.list_memberships(
        make_admin_headers(), params={"employer_id": employer_a["id"]}
    ))

    assert meta["total_count"] == 2, (
        f"the filter should count only employer A's two rows, got {meta['total_count']}"
    )
    assert [row["employer_id"] for row in rows] == [employer_a["id"]] * 2, (
        "a filtered listing must not leak the other employer's memberships"
    )


def test_eligibility_batch_under_an_unknown_employer_reports_the_employer_missing():
    """A missing parent employer is reported before its batches are consulted.

    PRD: "A request that targets an eligibility batch under a non-existent employer fails with `ERR_EMPLOYER_NOT_FOUND` before the batch is looked for; a request that targets a placement slot under a non-existent offer fails with `ERR_OFFER_NOT_FOUND` before the slot is looked for."

    Design: Corner/entities/eligibility_file_and_membership_rows_belong_only_to_their_parent_employer
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)

    validate_error(
        api_client.create_eligibility_file(
            NON_EXISTENT_UUID,
            F.eligibility_file_payload(1, records=F.eligibility_records(1)),
            make_employer_admin_headers(NON_EXISTENT_UUID),
        ),
        ApiErrorId.EMPLOYER_NOT_FOUND,
    )
    validate_error(
        api_client.list_eligibility_files(NON_EXISTENT_UUID, make_admin_headers()),
        ApiErrorId.EMPLOYER_NOT_FOUND,
    )


# ── entities / foreign_key_references_are_validated_before_any_business_rule ──


def test_absent_body_foreign_keys_return_each_entity_own_not_found_code():
    """A body foreign key naming no row fails with that entity's own code.

    PRD: "The same precedence governs foreign keys supplied in a request body: a referenced row that does not exist yields that entity's own not-found code — `ERR_MERCHANT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_ELIGIBILITY_FILE_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_PLACEMENT_SLOT_NOT_FOUND`, `ERR_REDEMPTION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND` or `ERR_LEDGER_ENTRY_NOT_FOUND`."

    Design: Corner/entities/foreign_key_references_are_validated_before_any_business_rule
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant()

    validate_error(
        api_client.create_agreement(
            F.agreement_payload(NON_EXISTENT_UUID), make_partner_manager_headers()
        ),
        ApiErrorId.MERCHANT_NOT_FOUND,
    )
    validate_error(
        api_client.create_offer(
            F.offer_payload(NON_EXISTENT_UUID), make_merchant_headers(merchant["id"])
        ),
        ApiErrorId.AGREEMENT_NOT_FOUND,
    )
    validate_error(
        api_client.create_statement(
            F.statement_payload(NON_EXISTENT_UUID), make_partner_manager_headers()
        ),
        ApiErrorId.EMPLOYER_NOT_FOUND,
    )


def test_an_absent_agreement_outranks_an_inverted_offer_window():
    """Existence is settled before the window is examined, so the FK code wins.

    PRD: "This ordering is part of the contract: a request that violates two rules must fail with the code of the earlier one."

    Design: Corner/entities/foreign_key_references_are_validated_before_any_business_rule
    """
    fixtures.set_clock(C.DEFAULT_CLOCK)
    merchant = fixtures.create_merchant()

    response = api_client.create_offer(
        F.offer_payload(
            NON_EXISTENT_UUID,
            window_start="2026-12-01T00:00:00Z",
            window_end="2026-08-01T00:00:00Z",
        ),
        make_merchant_headers(merchant["id"]),
    )

    validate_error(response, ApiErrorId.AGREEMENT_NOT_FOUND)
