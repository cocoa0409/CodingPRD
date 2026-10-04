"""Brand creation defaults, computed-field hygiene, protective lockdown and
posture-gated writes."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assert_brand,
    validate_error, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
CA = TEST_USERS["compliance_auditor_headers"]
CM = TEST_USERS["channel_manager_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]


def test_brand_create_returns_defaults_and_envelope():
    """PRD §3.1: "A new brand starts in `OPERATING` status with `protection_posture` `NORMAL`, `dilution_consumed_bps` of 0, `core_identity_share_bps` of 10000, and `genericization_risk_bps` of 0, and with `lockdown_reason` unset."
    PRD §3.1: "A `BrandManager` registers one by supplying its display `name`, the `legal_entity_name` of the owning company, and optionally an `equity_budget_bps` — the annual brand-equity dilution budget in basis points, which must be positive and defaults to 10000 when omitted."
    PRD §4: "Operations that create a new resource return `201 Created`; operations that modify, transition or compute against an existing resource return `200 OK`."

    Design: Corner/entities/brand_create_returns_defaults_and_envelope
    """
    resp = api_client.create_brand(
        {"name": "Multi-Use Brand", "legal_entity_name": "Multi-Use Products Co"}, BM)
    data = validate_success(resp, 201)
    assert_brand(data)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
    assert body["meta"].get("api_request_timestamp"), \
        "meta.api_request_timestamp must be present"
    assert data["status"] == "OPERATING"
    assert data["lockdown_reason"] is None
    assert data["protection_posture"] == "NORMAL"
    assert data["dilution_consumed_bps"] == 0
    assert data["core_identity_share_bps"] == 10000
    assert data["genericization_risk_bps"] == 0
    assert data["equity_budget_bps"] == 10000, "omitted equity_budget_bps defaults to 10000"


def test_brand_create_missing_legal_entity_returns_invalid_request():
    """PRD §2.6: "Required body fields must be present; enum, integer, date and datetime values must be well-formed and in range — `severity` within 1 to 5, `discount_pct` greater than 0 and at most 90.00, `component_codes` between 1 and 12 entries, constrained arrays non-empty. Fields that are undeclared, computed or system-sourced and appear in a request body are ignored, never stored (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.1: "A `BrandManager` registers one by supplying its display `name`, the `legal_entity_name` of the owning company, and optionally an `equity_budget_bps`" — only equity_budget_bps is optional, so legal_entity_name is required.

    Design: Corner/entities/brand_create_missing_legal_entity_returns_invalid_request
    """
    resp = api_client.create_brand({"name": "Incomplete Brand"}, BM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_brand_create_with_computed_field_input_ignored():
    """PRD §2.6: "Fields that are undeclared, computed or system-sourced and appear in a request body are ignored, never stored (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.1: "A new brand starts in `OPERATING` status with `protection_posture` `NORMAL`" — a client-supplied protection_posture must not be stored.

    Design: Corner/entities/brand_create_with_computed_field_input_ignored
    """
    resp = api_client.create_brand(
        {"name": "Spoofed Brand", "legal_entity_name": "Spoof Co",
         "protection_posture": "CRITICAL"}, BM)
    data = validate_success(resp, 201)
    assert data["protection_posture"] == "NORMAL", \
        "computed protection_posture supplied in the body must be ignored, not stored"


def test_lockdown_blocks_launch_and_lift_requires_clear_conditions():
    """PRD §3.1: "While a brand is locked down, product-line launches, registration submissions, the activation of exclusive coverage and the resumption of suspended promotions are all refused with `ERR_BRAND_IN_LOCKDOWN` (HTTP 409)."
    PRD §3.1: "the lift is refused with `ERR_LOCKDOWN_CONDITIONS_UNMET` (HTTP 409) for as long as either of two conditions holds: any counterfeit case of the brand is still open (in `REPORTED` or `ACTION_TAKEN`) with `severity` equal to 5, or any confidentiality grant touching a formulation of one of the brand's lines was revoked for cause within the trailing 90 days."
    PRD §3.2: "Three gates guard the launch, evaluated in this order: the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`, 409), the brand's posture must not be `CRITICAL` (`ERR_POSTURE_CRITICAL`, 409), and at least one pack format of the line must be `IN_PRODUCTION` (`ERR_NO_PRODUCIBLE_PACK_FORMAT`, 409)."

    Design: Corner/errors/lockdown_blocks_launch_and_lift_requires_clear_conditions
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market()

    lock = api_client.lockdown_brand(sc["brand"]["id"], "MANUAL", CA)
    assert validate_success(lock)["status"] == "PROTECTIVE_LOCKDOWN"

    blocked = api_client.launch_product_line(sc["line"]["id"], BM)
    validate_error(blocked, ApiErrorId.ERR_BRAND_IN_LOCKDOWN)

    lifted = api_client.lift_brand_lockdown(sc["brand"]["id"], CA)
    lifted_data = validate_success(lifted)
    assert lifted_data["status"] == "OPERATING"
    assert lifted_data["lockdown_reason"] is None

    fx.create_counterfeit_case_record(sc["brand"]["id"], market["id"], severity=5)
    relock = api_client.lockdown_brand(sc["brand"]["id"], "COUNTERFEIT_SURGE", CA)
    assert validate_success(relock)["status"] == "PROTECTIVE_LOCKDOWN"

    blocked_lift = api_client.lift_brand_lockdown(sc["brand"]["id"], CA)
    validate_error(blocked_lift, ApiErrorId.ERR_LOCKDOWN_CONDITIONS_UNMET)


def test_critical_posture_blocks_registration_submit():
    """PRD §3.4: "Submission moves `DRAFT` → `SUBMITTED`, stamps `submitted_at`, and is gated on the brand being `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`) and its posture not `CRITICAL` (`ERR_POSTURE_CRITICAL`)."
    PRD §3.1: "The posture is `CRITICAL` when at least two such breaches exist, or any single open case has `severity` 5, or the open-case severities sum to at least 10."

    Design: Corner/errors/critical_posture_blocks_registration_submit
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True)
    reg = fx.create_market_registration_record(
        market["id"], sc["line"]["id"], sc["formulation"]["id"])
    case = fx.create_counterfeit_case_record(sc["brand"]["id"], market["id"], severity=5)

    blocked = api_client.submit_market_registration(reg["id"], RA)
    validate_error(blocked, ApiErrorId.ERR_POSTURE_CRITICAL)

    close = api_client.close_counterfeit_case(case["id"], CA)
    validate_success(close)
    submitted = api_client.submit_market_registration(reg["id"], RA)
    assert validate_success(submitted)["status"] == "SUBMITTED"


def test_exclusive_activation_blocked_at_critical_posture():
    """PRD §3.5: "Activation moves a `PROPOSED` assignment to `ACTIVE` through a battery of gates, in order: the distributor must be `APPROVED` (`ERR_DISTRIBUTOR_NOT_APPROVED`); the current date must lie inside the closed coverage window (`ERR_WINDOW_INVALID`); the line must be `LAUNCHED` (`ERR_LINE_NOT_LAUNCHED`, HTTP 409); when the market's `registration_required` is true, a registration for the assignment's market and line must be `ACTIVE` (`ERR_REGISTRATION_NOT_ACTIVE`, HTTP 409); when the assignment is exclusive, the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`, 409) and its posture not `CRITICAL` (`ERR_POSTURE_CRITICAL`, 409); exclusivity is re-checked against overlapping exclusive `ACTIVE` or `SUSPENDED` assignments on the cell (`ERR_EXCLUSIVE_OVERLAP`); and the cell must currently hold fewer than 3 assignments in `ACTIVE` or `SUSPENDED` — a third coexists, a fourth is refused with `ERR_CELL_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/errors/exclusive_activation_blocked_at_critical_posture
    """
    sc = fx.setup_launched_line()
    market = fx.create_market()
    dist = fx.create_approved_distributor(market["id"])
    asg = fx.propose_coverage_assignment(
        dist["id"], market["id"], sc["line"]["id"], exclusive=True)
    case = fx.create_counterfeit_case_record(sc["brand"]["id"], market["id"], severity=5)

    blocked = api_client.activate_coverage_assignment(asg["id"], CM)
    validate_error(blocked, ApiErrorId.ERR_POSTURE_CRITICAL)

    validate_success(api_client.close_counterfeit_case(case["id"], CA))
    activated = api_client.activate_coverage_assignment(asg["id"], CM)
    assert validate_success(activated)["status"] == "ACTIVE"
