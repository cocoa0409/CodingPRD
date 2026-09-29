"""Entity projections: declared fields, defaults, computed values and parent links.

Every test in this module proves one entity-level claim of the Utility Service
Line Warranty Program API: the shape a create returns, the defaults the PRD
declares for the optional inputs, the values the server computes for itself, the
identifiers it mints, and the not-found and referential-integrity codes that
guard the flat collection topology of PRD §2.11.

The harness restarts the server before every test, so each test builds its own
world from an empty store and pins the logical clock explicitly (PRD §2.5).
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_INVALID_RECURRENCE_LINK,
    ERR_INVALID_REQUEST,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_PARTNER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_contains_id,
    assert_created_at_ascending,
    assert_created_resource,
    assert_date_only,
    assert_error_shape,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_instant_format,
    assert_ledger_common_fields,
    assert_list_envelope,
    assert_nulls,
    assert_object_envelope,
    assert_refused,
    assert_uuid,
)
from test_helpers.constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
    COVERAGE_EFFECTIVE_AT,
    ENROLLMENT_TERM_END,
    ENROLLMENT_TERM_START,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    PLATFORM_ADMIN,
)

# A well-formed UUID that matches no row of any collection (PRD §2.8 tier 5).
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

def _created(response):
    """Unwrap a 201 create, which carries one resource under response_type 'object'."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"a create returns a single resource: response_type expected 'object', "
        f"got {body.get('response_type')!r}"
    )
    return validate_success(response, 201)


class TestUtilityPartnerEntity:
    """The partner projection: declared defaults, minted system fields, enums."""

    def test_partner_creation_returns_every_declared_field(self, api):
        """A minimal create body still returns the whole partner projection at its declared defaults.

        PRD: "A newly registered partner is `ONBOARDING`, its `version` is 1, its `suspension_reason` is null and its `enrolled_premises_count` is 0."
        PRD: "Four policy switches may be supplied in the same payload, and each has a default that applies when it is omitted."

        Design: Corner/entities/partner_creation_returns_every_declared_field
        """
        fixtures.set_clock(api, CLOCK_START)

        payload = factories.minimal_partner_payload()
        for switch in (
            "brand_approval_required",
            "min_days_between_drops",
            "max_mailings_per_year",
            "rate_filing_required",
            "bill_insert_supported",
        ):
            assert switch not in payload, f"{switch} must be omitted so its default is observable"

        partner = _created(api.create_partner(payload, PLATFORM_ADMIN))

        # Identity and bookkeeping: a bare UUID, version 1, created_at == updated_at.
        assert_created_resource(partner)
        assert_uuid(partner["id"], "partner id")
        assert_instant(partner["created_at"], CLOCK_START, "created_at")

        assert_fields(
            partner,
            {
                "name": "Cascadia Water",
                "utility_type": "WATER",
                "state_code": "OR",
                "status": "ONBOARDING",
                "version": 1,
                # The four policy switches at their declared defaults, plus the
                # bill-insert switch of PRD §3.1.
                "brand_approval_required": True,
                "min_days_between_drops": 21,
                "max_mailings_per_year": 2,
                "rate_filing_required": False,
                "bill_insert_supported": True,
                # The live cross-entity count starts empty.
                "enrolled_premises_count": 0,
            },
        )
        assert_nulls(partner, ["suspension_reason"])

    def test_partner_utility_type_rejects_an_invalid_enum_value(self, api):
        """An out-of-domain utility_type is a schema failure rather than a stored value.

        PRD: "A `PlatformAdmin` registers one by supplying its legal `name` — between 1 and 120 characters and not blank — the `utility_type` it operates, which is one of `WATER`, `WASTEWATER`, `ELECTRIC` or `COMBINATION`, and the `state_code` of the regulator with jurisdiction over it, which must be exactly two uppercase letters from A to Z."
        PRD: "On every operation that carries a body: a missing required field, a field of the wrong JSON type, an unknown enum member, or a violation of a declared length or range constraint yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/partner_utility_type_rejects_an_invalid_enum_value
        """
        fixtures.set_clock(api, CLOCK_START)

        payload = factories.minimal_partner_payload(
            name="Cascadia Telecom", utility_type="TELECOM"
        )
        assert_refused(api.create_partner(payload, PLATFORM_ADMIN), ERR_INVALID_REQUEST)

        # Nothing was persisted by the refused create.
        rows, _meta = assert_list_envelope(
            api.list_partners(PLATFORM_ADMIN), expected_total=0
        )
        assert rows == [], f"the refused create must persist nothing, got {rows!r}"

    def test_partner_retrieval_returns_the_stored_entity(self, api):
        """A read echoes exactly what the create stored, and never advances the version.

        PRD: "`version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every accepted mutation of that record."

        Design: Corner/entities/partner_retrieval_returns_the_stored_entity
        """
        fixtures.set_clock(api, CLOCK_START)

        created = _created(
            api.create_partner(
                factories.partner_payload(
                    name="Cascadia Water",
                    utility_type="WATER",
                    state_code="OR",
                    brand_approval_required=True,
                    min_days_between_drops=21,
                    max_mailings_per_year=2,
                    rate_filing_required=False,
                    bill_insert_supported=True,
                ),
                PLATFORM_ADMIN,
            )
        )
        assert created["version"] == 1

        read = assert_object_envelope(api.get_partner(created["id"], CUSTOMER_SERVICE_REP))
        assert_fields(
            read,
            {
                "id": created["id"],
                "name": "Cascadia Water",
                "utility_type": "WATER",
                "state_code": "OR",
                "status": "ONBOARDING",
                "min_days_between_drops": 21,
                "max_mailings_per_year": 2,
                "brand_approval_required": True,
                "rate_filing_required": False,
                "bill_insert_supported": True,
                "version": created["version"],
            },
        )
        assert_instant(read["created_at"], created["created_at"], "created_at")
        assert_instant(read["updated_at"], created["updated_at"], "updated_at")

        # A second read is equally free of side effects.
        reread = assert_object_envelope(api.get_partner(created["id"], CUSTOMER_SERVICE_REP))
        assert reread["version"] == 1, (
            f"a read is not a mutation, yet version reached {reread['version']}"
        )

    def test_partner_not_found_returns_partner_not_found(self, api):
        """A well-formed but unknown partner id is a lookup miss, not a schema failure.

        PRD: "On every endpoint with a path parameter, a well-formed UUID that matches no row of the addressed collection yields that collection's own not-found code (404): `ERR_PARTNER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_COMPLAINT_NOT_FOUND`."

        Design: Corner/entities/partner_not_found_returns_partner_not_found
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = _created(
            api.create_partner(factories.minimal_partner_payload(), PLATFORM_ADMIN)
        )

        response = api.get_partner(UNKNOWN_UUID, CUSTOMER_SERVICE_REP)
        assert_refused(response, ERR_PARTNER_NOT_FOUND)

        # The error envelope carries error_id and message and no business payload.
        data = assert_error_shape(response)
        assert set(data.keys()) == {"error_id", "message"}, (
            f"an error body carries only error_id and message, got {sorted(data.keys())}"
        )

        # The unrelated row is untouched and still listed.
        rows, _meta = assert_list_envelope(
            api.list_partners(CUSTOMER_SERVICE_REP), expected_total=1
        )
        assert_contains_id(rows, partner["id"])


class TestServiceLineProductEntity:
    """The filed product: list pagination and its flat parent reference."""

    def test_service_line_product_listing_is_paginated_in_created_at_order(self, api):
        """Three products over a page size of 2: total_count counts matching rows, not returned rows.

        PRD: "The `meta` object of a list response carries all four pagination fields: `limit` and `offset` echo the effective values used for the page, `total_count` reports the number of rows matching the filter before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."
        PRD: "Every list endpoint returns its rows sorted by `created_at` ascending, so the oldest record appears first and a freshly created record appears last."

        Design: Corner/entities/service_line_product_listing_is_paginated_in_created_at_order
        """
        world = fixtures.active_partner_with_product(
            api, product_overrides={"name": "Water Line Protect"}
        )
        first_id = world["product_id"]
        second_id = fixtures.file_product(
            api,
            world["partner_id"],
            name="Sewer Guard Basic",
            line_type="SEWER_LATERAL",
            ownership_boundary="PROPERTY_LINE",
            required_owned_segment="SEWER_PROPERTY_LINE_TO_MAIN",
            monthly_price_cents=3299,
            per_occurrence_cap_cents=900000,
            annual_cap_cents=1200000,
        )["id"]
        third_id = fixtures.file_product(
            api,
            world["partner_id"],
            name="Interior Plumbing Plus",
            line_type="INTERIOR_PLUMBING",
            ownership_boundary="INSIDE",
            required_owned_segment="INTERIOR_PLUMBING_SYSTEM",
            monthly_price_cents=1899,
            per_occurrence_cap_cents=300000,
            annual_cap_cents=500000,
        )["id"]

        page1 = api.list_products(
            MARKETING_OPS,
            params={"partner_id": world["partner_id"], "limit": 2, "offset": 0},
        )
        rows, meta = assert_list_envelope(page1, expected_total=3)
        assert meta["limit"] == 2, f"limit echoes the page size, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset echoes the window start, got {meta['offset']}"
        assert meta["has_more"] is True, "rows remain beyond the first window"
        assert len(rows) == 2, f"a page of 2 returns two rows, got {len(rows)}"
        assert_created_at_ascending(rows)
        assert_ids_in_order(rows, [first_id, second_id])

        page2 = api.list_products(
            MARKETING_OPS,
            params={"partner_id": world["partner_id"], "limit": 2, "offset": 2},
        )
        rows2, meta2 = assert_list_envelope(page2, expected_total=3)
        assert meta2["limit"] == 2 and meta2["offset"] == 2
        assert meta2["has_more"] is False, "nothing remains beyond the second window"
        assert len(rows2) == 1, f"only the tail row remains, got {len(rows2)}"
        assert_ids_in_order(rows2, [third_id])

    def test_service_line_product_requires_an_existing_parent_partner(self, api):
        """The parent arrives in the body, so an unknown partner_id is a 404 rather than a 400.

        PRD: "Only after every path identifier resolves are the identifiers inside the body checked."
        PRD: "Each of `partner_id`, `product_id`, `premises_id`, `source_campaign_id`, `contractor_id`, `supersedes_dispatch_id`, `recurrence_of_claim_id`, `claim_id` and `enrollment_id` must match an existing row, and a miss yields the referenced collection's not-found code (404)."

        Design: Corner/entities/service_line_product_requires_an_existing_parent_partner
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = _created(
            api.create_partner(factories.minimal_partner_payload(), PLATFORM_ADMIN)
        )

        payload = factories.minimal_product_payload(UNKNOWN_UUID, name="Orphan Product")
        assert_refused(api.create_product(payload, PLATFORM_ADMIN), ERR_PARTNER_NOT_FOUND)

        # No orphan product was created.
        rows, _meta = assert_list_envelope(api.list_products(PLATFORM_ADMIN), expected_total=0)
        assert rows == [], f"the refused filing must create nothing, got {rows!r}"

        # The legitimate parent was not touched either.
        read = assert_object_envelope(api.get_partner(partner["id"], PLATFORM_ADMIN))
        assert read["version"] == 1, (
            f"the refused create touched nothing, yet the partner reached version {read['version']}"
        )


class TestPremisesEntity:
    """The marketing file entry and its three declared optional defaults."""

    def test_premises_creation_applies_declared_defaults(self, api):
        """Omitting all three optional inputs yields false, GOOD, null — and a derived NONE suppression.

        PRD: "`do_not_mail` defaults to false and records the homeowner's own opt-out."
        PRD: "A newly created premises therefore opens with `version` 1, `last_mail_decision` `NOT_EVALUATED`, `mail_count_current_year` 0 and a freshly derived `suppression_reason` — which is already `DNM_REQUEST` if the address arrived with a do-not-mail request, or `BAD_ADDRESS` if it arrived undeliverable."

        Design: Corner/entities/premises_creation_applies_declared_defaults
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = _created(
            api.create_partner(factories.minimal_partner_payload(), PLATFORM_ADMIN)
        )

        payload = factories.minimal_premises_payload(partner["id"])
        for optional in ("do_not_mail", "address_status", "known_defect_reported_at"):
            assert optional not in payload, f"{optional} must be omitted so its default is observable"

        premises = _created(api.create_premises(payload, MARKETING_OPS))

        assert_created_resource(premises)
        assert_fields(
            premises,
            {
                "partner_id": partner["id"],
                "street_address": "12 Alder St",
                "state_code": "OR",
                "owned_segments": ["WATER_CURB_STOP_TO_HOME"],
                # The three declared optional defaults.
                "do_not_mail": False,
                "address_status": "GOOD",
                # System-maintained flags and the derived views.
                "regulator_hold": False,
                "suppression_reason": "NONE",
                "suppressed": False,
                "last_mail_decision": "NOT_EVALUATED",
                "mail_count_current_year": 0,
                "version": 1,
            },
        )
        assert_nulls(
            premises,
            ["known_defect_reported_at", "last_mail_suppression_reason", "last_mailed_campaign_id"],
        )


class TestMarketingCampaignEntity:
    """The campaign draft and the required fields that carry no default."""

    def test_campaign_creation_missing_required_drop_date_returns_invalid_request(self, api):
        """drop_date has no default, so omitting it is a schema failure that writes no state.

        PRD: "`MarketingOps` drafts it by naming the `partner_id` and the `product_id` — and the product must belong to that partner — together with an internal `name` of 1 to 120 non-blank characters, a `piece_type` that is one of `BILL_INSERT`, `DIRECT_MAIL_LETTER`, `POSTCARD` or `EMAIL`, the `drop_date` on which the piece is to enter the mail stream as a plain calendar date, and a `requested_quantity` between 0 and 1000000 inclusive."
        PRD: "On every operation that carries a body: a missing required field, a field of the wrong JSON type, an unknown enum member, or a violation of a declared length or range constraint yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/campaign_creation_missing_required_drop_date_returns_invalid_request
        """
        # An ACTIVE partner with a filed product, so no cross-entity gate can
        # pre-empt the request-body schema check.
        world = fixtures.active_partner_with_product(api)

        payload = factories.campaign_payload(
            world["partner_id"],
            world["product_id"],
            name="August postcard",
            piece_type="POSTCARD",
            requested_quantity=100,
            drop_date=None,
        )
        assert "drop_date" not in payload, "the trigger must omit drop_date entirely"

        assert_refused(api.create_campaign(payload, MARKETING_OPS), ERR_INVALID_REQUEST)

        rows, _meta = assert_list_envelope(
            api.list_campaigns(MARKETING_OPS, params={"partner_id": world["partner_id"]}),
            expected_total=0,
        )
        assert rows == [], (
            f"a campaign with a null drop_date must not be persisted, got {rows!r}"
        )


class TestEnrollmentEntity:
    """The policy's computed term, coverage clock and pinned money terms."""

    def test_enrollment_computed_dates_are_derived_from_the_clock(self, api):
        """coverage_effective_at, term_end and monthly_price_cents are computed by the server.

        PRD: "Dates are stamped from the logical clock: `enrollment_date` is the clock instant itself, `term_start` is the clock's calendar date and is the inclusive start of the coverage term, and `term_end` is exactly twelve calendar months after `term_start` and is the **exclusive** end of that term."
        PRD: "`coverage_effective_at` is `term_start` advanced by the product's `waiting_period_days` whole days, taken at midnight UTC — that is, at `00:00:00.000Z` on the resulting date."

        Design: Corner/entities/enrollment_computed_dates_ignore_client_supplied_input_ignored
        """
        # Water Line Protect at 2499 cents a month with a 30-day waiting period,
        # one OR address owning the insured segment, sold on 2026-08-05.
        world = fixtures.partner_product_premises(api)
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)

        payload = factories.enrollment_payload(
            world["premises_id"],
            world["product_id"],
            world["premises_version"],
            billing_mode="DIRECT_BILL",
            prepaid_amount_cents=None,
        )
        assert "prepaid_amount_cents" not in payload, (
            "prepaid_amount_cents must be omitted so the DIRECT_BILL default is observable"
        )

        enrollment = _created(api.create_enrollment(payload, CUSTOMER_SERVICE_REP))

        assert_created_resource(enrollment)

        # term_start is the clock's calendar date; term_end is twelve calendar
        # months later.
        assert_date_only(enrollment["term_start"], "term_start")
        assert_date_only(enrollment["term_end"], "term_end")
        assert enrollment["term_start"] == ENROLLMENT_TERM_START, (
            f"term_start expected {ENROLLMENT_TERM_START}, got {enrollment['term_start']!r}"
        )
        assert enrollment["term_end"] == ENROLLMENT_TERM_END, (
            f"term_end expected {ENROLLMENT_TERM_END} (twelve calendar months after "
            f"term_start), got {enrollment['term_end']!r}"
        )

        # coverage_effective_at is term_start advanced by 30 whole days at
        # midnight UTC.
        assert_instant_format(enrollment["coverage_effective_at"], "coverage_effective_at")
        assert_instant(
            enrollment["coverage_effective_at"], COVERAGE_EFFECTIVE_AT, "coverage_effective_at"
        )

        # The money terms are pinned from the product.
        assert_cents(enrollment["monthly_price_cents"], "monthly_price_cents")
        assert enrollment["monthly_price_cents"] == 2499, (
            f"monthly_price_cents is copied from the product, got "
            f"{enrollment['monthly_price_cents']!r}"
        )
        # PRD: "`prepaid_amount_cents`, when not supplied, is twelve times that pinned monthly price under `DIRECT_BILL` and zero under `BILL_INSERT`."
        assert_cents(enrollment["prepaid_amount_cents"], "prepaid_amount_cents")
        assert enrollment["prepaid_amount_cents"] == 2499 * 12

        # PRD: "`cap_year_start` is set to `term_start` when the product's `cap_reset_basis` is `ENROLLMENT_ANNIVERSARY`, and to 1 January of the year containing `term_start` when it is `CALENDAR_YEAR`."
        assert_date_only(enrollment["cap_year_start"], "cap_year_start")
        assert enrollment["cap_year_start"] == ENROLLMENT_TERM_START

        # The three status dimensions open where PRD §3.3 declares.
        assert_fields(
            enrollment,
            {
                "premises_id": world["premises_id"],
                "product_id": world["product_id"],
                "billing_mode": "DIRECT_BILL",
                "coverage_status": "PENDING_WAITING_PERIOD",
                "version": 1,
            },
        )


class TestLedgerEntryEntity:
    """The append-only money row: two common fields and no write endpoint."""

    def test_ledger_entry_is_immutable_with_no_version_field(self, api):
        """A ledger row exposes id and created_at only, and is written solely as a business side effect.

        PRD: "A ledger row carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never modified after it is appended."

        Design: Corner/entities/ledger_entry_is_immutable_with_no_version_field
        """
        # A DIRECT_BILL policy written on 2026-08-05. Creating the enrollment
        # posts no ledger row of its own, so the single CASH row under test is
        # posted by an explicit billing event.
        world = fixtures.enrolled_premises(api)
        get_success_data(
            api.create_billing_event(
                world["enrollment_id"],
                factories.billing_event_payload(
                    "PREMIUM_PAYMENT",
                    ENROLLMENT_TERM_START,
                    amount_cents=29988,
                    memo="Opening annual prepayment.",
                ),
                BILLING_OPS,
            )
        )

        rows, _meta = assert_list_envelope(
            api.list_ledger_entries(
                BILLING_OPS, params={"enrollment_id": world["enrollment_id"]}
            ),
            expected_total=1,
        )
        assert len(rows) == 1, f"exactly one row was appended, got {len(rows)}"
        row = rows[0]
        assert_fields(
            row,
            {
                "enrollment_id": world["enrollment_id"],
                "ledger_kind": "CASH",
                "entry_type": "PREMIUM_PAYMENT",
                "amount_cents": 29988,
            },
        )
        assert_cents(row["amount_cents"], "amount_cents")

        # The projection is exactly id and created_at: no updated_at, no version.
        assert_ledger_common_fields(row)
        assert_instant(row["created_at"], CLOCK_ENROLLMENT_DAY, "created_at")

        read = assert_object_envelope(api.get_ledger_entry(row["id"], BILLING_OPS))
        assert read["id"] == row["id"]
        assert_ledger_common_fields(read)
        assert_instant(read["created_at"], CLOCK_ENROLLMENT_DAY, "created_at")

        assert_refused(
            api.get_ledger_entry(UNKNOWN_UUID, BILLING_OPS), ERR_LEDGER_ENTRY_NOT_FOUND
        )


class TestClaimEntity:
    """The self-referential recurrence link and the occurrence root it resolves."""

    def test_claim_recurrence_link_must_name_a_claim_on_the_same_enrollment(self, api):
        """An existing claim on a different enrollment is a bad recurrence link, not a missing row.

        PRD: "A supplied link is only valid when the referenced claim belongs to the same `enrollment_id`, carries the same `line_type`, and was reported no more than 30 days before this claim's `reported_at`; otherwise the filing is refused with `ERR_INVALID_RECURRENCE_LINK`."
        PRD: "A claim filed with no link is the root of its own group and its `occurrence_root_claim_id` equals its own `id`."

        Design: Corner/entities/claim_recurrence_link_must_name_a_claim_on_the_same_enrollment
        """
        # Two independent OR addresses, each enrolled on the same product.
        world = fixtures.partner_product_premises(api)
        premises_b = fixtures.create_unique_premises(api, world["partner_id"])

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment_a = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"]
        )
        enrollment_b = fixtures.create_enrollment(
            api, premises_b["id"], world["product_id"], premises_b["version"]
        )

        # Move past the waiting period and let the nightly run activate both.
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        claim_a = _created(
            api.create_claim(
                factories.claim_payload(
                    enrollment_a["id"], incident_description="Claim on premises A."
                ),
                CUSTOMER_SERVICE_REP,
            )
        )
        assert claim_a["occurrence_root_claim_id"] == claim_a["id"], (
            "an unlinked claim is the root of its own occurrence group, got "
            f"{claim_a['occurrence_root_claim_id']!r}"
        )

        # The referenced claim exists, so only the relational check can catch it.
        linked = factories.claim_payload(
            enrollment_b["id"],
            incident_description="Claim on premises B claiming to be a recurrence of premises A's claim.",
            recurrence_of_claim_id=claim_a["id"],
        )
        assert_refused(api.create_claim(linked, CUSTOMER_SERVICE_REP), ERR_INVALID_RECURRENCE_LINK)

        rows, _meta = assert_list_envelope(
            api.list_claims(CUSTOMER_SERVICE_REP, params={"enrollment_id": enrollment_b["id"]}),
            expected_total=0,
        )
        assert rows == [], f"the refused filing must persist no claim, got {rows!r}"

        # The identical body without the link is admitted, so only the link was at fault.
        unlinked = factories.claim_payload(
            enrollment_b["id"],
            incident_description="Claim on premises B claiming to be a recurrence of premises A's claim.",
        )
        claim_b = _created(api.create_claim(unlinked, CUSTOMER_SERVICE_REP))
        assert claim_b["occurrence_root_claim_id"] == claim_b["id"]
        assert claim_b["enrollment_id"] == enrollment_b["id"]
