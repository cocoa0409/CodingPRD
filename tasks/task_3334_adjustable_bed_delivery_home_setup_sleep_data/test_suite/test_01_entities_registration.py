"""Entity creation, registration defaults, and computed read claims."""
from test_helpers import (
    ApiErrorId,
    assert_customer,
    assert_fit_assessment,
    assert_store,
    create_completed_assessment,
    create_customer,
    create_full_catalog,
    create_product_model_payload,
    create_store,
    set_clock,
    setup_store_with_catalog,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import ADMIN, ANON, SALES


def test_store_create_applies_default_window_capacity(api, admin_headers):
    """PRD §3.1: "Each store carries a `name`, an array of `zone_codes`
    describing the delivery postal prefixes it serves, and a
    `default_window_capacity_slots` value that defaults to 4 and seeds the
    slot budget the store normally grants new delivery windows."

    Design: Corner/entities/store_create_returns_defaults_and_server_fields
    """
    resp = api.create_store(
        {"name": "Flagship", "zone_codes": ["941", "940"]}, admin_headers)
    data = validate_success(resp, expected_status=201)
    assert_store(data)
    assert data["default_window_capacity_slots"] == 4, (
        f"default_window_capacity_slots must default to 4, got "
        f"{data['default_window_capacity_slots']}")
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"


def test_store_create_defaults_timestamped_by_logical_clock(api, admin_headers):
    """PRD §2.4: "Every persisted entity carries a server-minted `id` that is
    a UUID with no type prefix, plus `created_at` and `updated_at` timestamps
    in ISO 8601 UTC with three fractional digits, plus an integer `version`
    that starts at 1 and increments by exactly 1 on every mutation of that
    entity."

    Design: Corner/entities/store_create_returns_defaults_and_server_fields
    """
    resp = api.create_store(
        {"name": "Meta", "zone_codes": ["941"]}, admin_headers)
    data = validate_success(resp, expected_status=201)
    body = resp.json()
    assert body.get("response_type") == "object"
    assert "meta" in body
    assert body["meta"].get("api_request_id"), "meta.api_request_id missing"
    assert body["meta"].get("api_request_timestamp"), \
        "meta.api_request_timestamp missing"
    assert data["id"], "id must be server-minted"
    assert data["created_at"], "created_at must be present"
    assert data["updated_at"], "updated_at must be present"


def test_customer_registration_free_tier_defaults(api, anonymous_headers):
    """PRD §3.1: "The new `Customer` starts with `subscription_tier` set to
    `FREE`, `subscription_status` set to `ACTIVE`, `store_credit_cents` at 0,
    and a computed `entitlements` array derived from the tier: `FREE` maps to
    `[SCORE_BASIC]`, `PLUS` maps to `[SCORE_BASIC, SCORE_DETAIL]`, and
    `PREMIUM` maps to `[SCORE_BASIC, SCORE_DETAIL, TRENDS]`."

    Design: Corner/entities/customer_registration_sets_free_tier_entitlements
    """
    set_clock()
    store = create_store()
    resp = api.create_customer(
        {"home_store_id": store["id"], "email": "e@x.com",
         "full_name": "Eve E"}, anonymous_headers)
    data = validate_success(resp, expected_status=201)
    assert_customer(data)
    assert data["subscription_tier"] == "FREE"
    assert data["subscription_status"] == "ACTIVE"
    assert data["entitlements"] == ["SCORE_BASIC"], (
        f"FREE entitlements must be [SCORE_BASIC], got {data['entitlements']}")
    assert data["store_credit_cents"] == 0


def test_customer_registration_read_returns_credit_and_entitlements(
        api, admin_headers):
    """PRD §3.1: "Reading a customer returns the `store_credit_cents` balance
    along with the computed entitlements."

    Design: Corner/entities/customer_registration_sets_free_tier_entitlements
    """
    set_clock()
    store = create_store()
    customer = create_customer(store["id"], email="e2@x.com")
    resp = api.get_customer(customer["id"], admin_headers)
    data = validate_success(resp)
    assert data["store_credit_cents"] == 0
    assert data["entitlements"] == ["SCORE_BASIC"]
    assert data["subscription_tier"] == "FREE"


def test_complete_assessment_computes_firmness_and_skus(api, sales_headers):
    """PRD §3.2: "The `recommended_firmness` is computed by taking a base
    value tied to `sleep_position` — 35 for `SIDE`, 55 for `BACK`, 65 for
    `STOMACH`, 50 for `COMBINATION` — adding a weight adjustment of −10 for
    `UNDER_130`, 0 for `BAND_130_230`, or +10 for `OVER_230`, adding a feel
    adjustment of −10 for `PLUSH`, 0 for `MEDIUM`, or +10 for `FIRM`,
    subtracting 5 when `partner_sleeper` is true, rounding the sum to the
    nearest multiple of 5 with ties rounding half up (so a raw 52 becomes 50
    and a raw 53 becomes 55), and clamping the result to no lower than 5 and
    no higher than 100."

    Design: Corner/entities/fit_assessment_recommended_firmness_computed_on_complete
    """
    store = setup_store_with_catalog()
    customer = create_customer(store["id"], email="f@x.com")
    fa = create_completed_assessment(
        customer["id"], store["id"],
        sleep_position="SIDE", weight_band="OVER_230",
        partner_sleeper=True, preferred_feel="FIRM")
    assert_fit_assessment(fa)
    assert fa["status"] == "COMPLETED"
    # SIDE 35 + OVER_230 10 + FIRM 10 + partner -5 = 50
    assert fa["recommended_firmness"] == 50, (
        f"recommended_firmness must be 50, got {fa['recommended_firmness']}")
    assert fa["recommended_skus"] == ["MAT-1", "BASE-1", "CHAM-1", "PUMP-1"], (
        f"recommended_skus must pick the lowest-priced model per required "
        f"category, got {fa['recommended_skus']}")
    assert fa["completed_at"], "completed_at must be stamped on completion"


def test_complete_assessment_stomach_profile_firmness_85(api, sales_headers):
    """PRD §3.2: "adding a weight adjustment of −10 for `UNDER_130`, 0 for
    `BAND_130_230`, or +10 for `OVER_230`, adding a feel adjustment of −10 for
    `PLUSH`, 0 for `MEDIUM`, or +10 for `FIRM`, subtracting 5 when
    `partner_sleeper` is true"

    Design: Corner/entities/fit_assessment_recommended_firmness_computed_on_complete
    """
    store = setup_store_with_catalog()
    customer = create_customer(store["id"], email="g@x.com")
    fa = create_completed_assessment(
        customer["id"], store["id"],
        sleep_position="STOMACH", weight_band="OVER_230",
        partner_sleeper=False, preferred_feel="FIRM")
    # STOMACH 65 + OVER_230 10 + FIRM 10 + no partner = 85
    assert fa["recommended_firmness"] == 85, (
        f"recommended_firmness must be 85, got {fa['recommended_firmness']}")
    assert fa["status"] == "COMPLETED"
