"""Entity creation defaults, required fields, enums, and computed fields (PRD §2.4, §3)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_supplier_payload, create_flavor_payload, create_enrollment_payload,
    create_scoop_shop_payload, create_campaign_payload,
    make_independent_board_member_headers,
    assert_supplier,
)

SM = TEST_USERS["sourcing_manager_headers"]
FM = TEST_USERS["flavor_manager_headers"]
DPM = TEST_USERS["dairy_program_manager_headers"]
FA = TEST_USERS["franchise_admin_headers"]


def test_supplier_creation_applies_defaults(api):
    """PRD §3.1: "The supplier's `status` lands in `PROSPECT`, and its
    `social_criteria_score` stays null until the first verified audit writes it
    (§3.2); there is no manual path to approval."
    PRD §2.4: "`id` (string): a unique, server-minted identifier formatted as a
    UUID" and "`version` (integer): starts at its initial value on creation and
    increments by one on every mutation".

    Design: Corner/entities/supplier_creation_applies_defaults
    """
    resp = api.create_supplier(
        create_supplier_payload(name="Defaults Dairy", country_code="US",
                                ingredient_category="DAIRY"), SM)
    data = validate_success(resp, expected_status=201)
    assert_supplier(data)
    assert data["status"] == "PROSPECT"
    assert data["social_criteria_score"] is None
    assert data["version"] == 1
    assert data["created_at"]


def test_flavor_create_missing_required_returns_invalid_request(api):
    """PRD §2.4: "Requests with a missing required field or a malformed value
    are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/flavor_create_missing_required_returns_invalid_request
    """
    payload = create_flavor_payload(name="x")
    del payload["name"]
    resp = api.create_flavor(payload, FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_flavor_create_invalid_enum_rejected(api):
    """PRD §2.4: "A field declared as an enum that receives a value outside its
    declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400)."

    Design: Corner/entities/flavor_create_invalid_enum_rejected
    """
    resp = api.create_flavor(
        create_flavor_payload(name="Gelato Gate", base_type="GELATO"), FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_supplier_computed_field_input_ignored(api):
    """PRD §3.1: "The supplier's `status` lands in `PROSPECT`, and its
    `social_criteria_score` stays null until the first verified audit writes it
    (§3.2)". A client-supplied value does not change that.

    Design: Corner/entities/supplier_computed_field_input_ignored
    """
    resp = api.create_supplier(
        create_supplier_payload(name="Presumptuous Produce",
                                ingredient_category="FRUIT",
                                social_criteria_score=99), SM)
    data = validate_success(resp, expected_status=201)
    assert data["social_criteria_score"] is None


def test_enrollment_blended_score_computed(api):
    """PRD §3.3: "the system computes `blended_score` as the round-half-up
    integer of the equal-weighted average — half environmental, half welfare."

    Design: Corner/entities/enrollment_blended_score_computed
    """
    enrollment = get_success_data(api.create_enrollment(
        create_enrollment_payload(farm_name="Rounding Ranch",
                                  baseline_volume_liters=5000), DPM))
    resp = api.assess_enrollment(
        enrollment["id"],
        {"env_practice_score": 81, "welfare_practice_score": 70}, DPM)
    data = validate_success(resp)
    assert data["blended_score"] == 76  # round_half_up(75.5)


def test_shop_franchise_fee_computed_by_operator_type(api):
    """PRD §3.8: "The franchise fee is computed by the server into
    `franchise_fee_cents`: 3,500,000 cents for a `FRANCHISEE`, and 0 for a
    `NONPROFIT_PARTNER`, whose partner-shop fee is waived."

    Design: Corner/entities/shop_franchise_fee_computed_by_operator_type
    """
    franchisee = validate_success(api.create_scoop_shop(
        create_scoop_shop_payload(name="Fee Shop", operator_type="FRANCHISEE",
                                  credit_limit_cents=100000), FA),
        expected_status=201)
    partner = validate_success(api.create_scoop_shop(
        create_scoop_shop_payload(name="Partner Shop",
                                  operator_type="NONPROFIT_PARTNER",
                                  nonprofit_verified=True,
                                  credit_limit_cents=100000), FA),
        expected_status=201)
    assert franchisee["franchise_fee_cents"] == 3_500_000
    assert partner["franchise_fee_cents"] == 0


def test_flavor_get_not_found_returns_404(api):
    """PRD §2.6: "The not-found vocabulary is per resource type: `ERR_SUPPLIER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_FLAVOR_NOT_FOUND`, `ERR_REVIVAL_REQUEST_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, and `ERR_ORDER_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/flavor_get_not_found_returns_404
    """
    resp = api.get_flavor("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", FM)
    validate_error(resp, ApiErrorId.ERR_FLAVOR_NOT_FOUND)


def test_campaign_notice_status_initialized_by_impact(api):
    """PRD §3.7: "sets the parallel `retail_notice_status` dimension:
    `NOT_REQUIRED` when the impact is `NONE`, `PENDING` otherwise."

    Design: Corner/entities/campaign_notice_status_initialized_by_impact
    """
    board = make_independent_board_member_headers("board-1")
    quiet = validate_success(api.create_campaign(
        create_campaign_payload(title="Quiet Campaign", issue_area="CLIMATE",
                                retail_partner_impact="NONE"), board),
        expected_status=201)
    loud = validate_success(api.create_campaign(
        create_campaign_payload(title="Loud Campaign", issue_area="FAIR_TRADE",
                                retail_partner_impact="HIGH"), board),
        expected_status=201)
    assert quiet["retail_notice_status"] == "NOT_REQUIRED"
    assert loud["retail_notice_status"] == "PENDING"
