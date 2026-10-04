"""Corner coverage: entity creation, computed defaults, not-found, pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_agreement,
    assert_manufacturer,
    create_manufacturer_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["contracts_manager_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestManufacturerCreation:
    def test_create_returns_201_with_id_and_active(self, api):
        """PRD §3.1: "A newly registered manufacturer starts in ACTIVE status;
        the administrator may later suspend it (transition to SUSPENDED),
        which blocks any new agreement activation or vehicle authorization
        referencing it without altering the posture of any existing
        agreement."
        PRD §4: "Endpoints that create a new resource return HTTP 201 with the
        created resource in data."

        Design: Corner/entities/manufacturer_creation_returns_201_and_id
        """
        resp = api.create_manufacturer(
            create_manufacturer_payload(
                legal_name="Mk Corp", duns="303030303",
            ),
            ADMIN,
        )
        manufacturer = validate_success(resp, expected_status=201)
        assert_manufacturer(manufacturer)
        assert manufacturer["status"] == "ACTIVE"
        assert is_valid_uuid(manufacturer["id"])

    def test_duplicate_duns_rejected(self, api):
        """PRD §3.1: "The duns value must be exactly nine digits and must be
        unique across all registered manufacturers; a duplicate is rejected
        with ERR_UNIQUENESS_VIOLATION (HTTP 409)."

        Design: Corner/entities/manufacturer_duns_uniqueness
        """
        resp = api.create_manufacturer(
            create_manufacturer_payload(legal_name="First", duns="404040404"), ADMIN,
        )
        validate_success(resp, expected_status=201)
        resp = api.create_manufacturer(
            create_manufacturer_payload(
                legal_name="Second", duns="404040404",
                manufacturer_type="CLOUD_SAAS", headquarters_country="GB",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION)


class TestAgreementComputedDefaults:
    def test_create_derives_posture_and_zero_ledger(self, api):
        """PRD §3.1: "The agreement is created in DRAFT status with
        dispute_credit_cents at zero and posture derived as GOOD_STANDING."

        Design: Corner/entities/agreement_posture_computed_default_good_standing
        """
        resp = api.create_manufacturer(create_manufacturer_payload(legal_name="P Corp"), ADMIN)
        manufacturer = validate_success(resp, expected_status=201)
        resp = api.create_agreement(
            {
                "manufacturer_id": manufacturer["id"],
                "scope_tiers": ["FEDERAL"],
                "mfc_discount_pct": 0.20,
                "small_business_goal_pct": 0.10,
                "product_scope": ["SW-"],
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2027-01-01T00:00:00Z",
            },
            CM,
        )
        agreement = validate_success(resp, expected_status=201)
        assert_agreement(agreement)
        assert agreement["posture"] == "GOOD_STANDING"
        assert agreement["status"] == "DRAFT"
        assert agreement["dispute_credit_cents"] == 0


class TestOrderTotalComputed:
    def test_order_total_derived_from_lines(self, api):
        """PRD §3.6: "At creation the order's totals are computed and frozen.
        For each line, the system locates the matching price line on the
        pinned list and computes a line subtotal by multiplying the line's
        offered_price_cents by the ordered quantity and rounding the result
        half-up to integer cents."

        Design: Corner/entities/order_total_computed_input_ignored
        """
        from test_helpers import setup_active_chain

        _, _, vehicle, price_list = setup_active_chain()
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "buyer_tier": "FEDERAL", "lines": [{"sku": "SW-1", "qty": 4}]},
            OPS,
        )
        order = validate_success(resp, expected_status=201)
        # offered 10000 * qty 4 = 40000, frozen at creation.
        assert order["order_total_cents"] == 40000
        assert order["compliance_status"] == "DRAFT"
        assert order["billing_status"] == "UNBILLED"


class TestManufacturerNotFound:
    def test_get_unknown_manufacturer_404(self, api):
        """PRD §2.9: "The first unresolved segment yields ERR_NOT_FOUND
        (HTTP 404)."

        Design: Corner/entities/get_manufacturer_not_found
        """
        resp = api.get_manufacturer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPaginationDefaults:
    def test_list_applies_default_limit_offset(self, api):
        """PRD §2.3: "When omitted, limit defaults to 10 and offset defaults
        to 0."
        PRD §2.3: "The meta envelope on list responses carries four pagination
        fields: limit (the page size actually applied), offset (the position
        actually applied), total_count (the total number of matching resources
        across all pages), and has_more (true when more resources exist beyond
        the returned page)."

        Design: Corner/entities/pagination_defaults_applied
        """
        for i in range(1, 13):
            resp = api.create_manufacturer(
                create_manufacturer_payload(
                    legal_name=f"M{i:02d}", duns=f"5100000{i:02d}",
                ),
                ADMIN,
            )
            validate_success(resp, expected_status=201)
        data, meta = validate_paginated(api.list_manufacturers(ADMIN))
        assert len(data) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
