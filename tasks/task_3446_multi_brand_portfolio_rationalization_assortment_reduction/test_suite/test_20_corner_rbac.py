"""Corner queue: RBAC claims — exclusive-operation denials, entity-backed
ownership mismatches, and the positive own-brand item creation.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_brand_term,
    create_combined_negotiation_payload,
    create_decide_payload,
    create_item_payload,
    create_negotiation_respond_payload,
    create_plant,
    create_plant_payload,
    create_qualification_run_payload,
    create_retailer,
    get_tsa_for_divestiture,
    make_brand_manager_headers,
    make_plant_director_headers,
    make_retailer_buyer_headers,
    setup_divestiture_closed,
    setup_negotiation_terms_proposed,
    setup_scored_case,
    setup_transfer_planned,
    validate_created,
    validate_error,
    validate_ok,
)

PM = TEST_USERS["portfolio_manager_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


def test_brand_manager_cannot_create_plant():
    """PRD §2.1: "`PortfolioManager` is the corporate portfolio executive and
    exclusively owns brand, plant, retailer, rationalization-case, divestiture,
    footprint-closure, and combined-negotiation mutations."
    PRD §2.1: "When the caller's role is not in the target endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/brand_manager_cannot_create_plant
    """
    brand = create_brand()
    resp = api_client.create_plant(
        create_plant_payload(quarterly_capacity_units=1000),
        make_brand_manager_headers(brand["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_supply_chain_planner_cannot_decide_case():
    """PRD §2.1: "`PortfolioManager` is the corporate portfolio executive and
    exclusively owns brand, plant, retailer, rationalization-case, divestiture,
    footprint-closure, and combined-negotiation mutations."
    PRD §2.1: "When the caller's role is not in the target endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/supply_chain_planner_cannot_decide_case
    """
    _, _, _, case = setup_scored_case()
    resp = api_client.decide_rationalization_case(
        case["id"], create_decide_payload("APPROVE"), SCP
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = validate_ok(api_client.get_rationalization_case(case["id"], PM))
    assert after["case_status"] == "SCORED"


def test_retailer_buyer_cannot_create_negotiation():
    """PRD §2.1: "`PortfolioManager` ... exclusively owns brand, plant,
    retailer, rationalization-case, divestiture, footprint-closure, and
    combined-negotiation mutations."
    PRD §2.1: "`RetailerBuyer` exclusively responds to combined negotiations
    for the represented retailer."

    Design: Corner/rbac/retailer_buyer_cannot_create_negotiation
    """
    retailer = create_retailer(risk_rating="LOW")
    brand1 = create_brand()
    brand2 = create_brand()
    terms = [create_brand_term(brand1["id"], 100, 90),
             create_brand_term(brand2["id"], 60, 50)]
    resp = api_client.create_combined_negotiation(
        create_combined_negotiation_payload(retailer["id"], terms),
        make_retailer_buyer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_portfolio_manager_cannot_record_qualification_run():
    """PRD §2.1: "`PlantDirector` exclusively records qualification runs at the
    directed plant".

    Design: Corner/rbac/portfolio_manager_cannot_record_qualification_run
    """
    _, _, _, _, transfer = setup_transfer_planned()
    resp = api_client.record_qualification_run(
        transfer["id"],
        create_qualification_run_payload(run_date="2026-09-02T00:00:00Z"),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_portfolio_manager_cannot_terminate_tsa():
    """PRD §2.1: "`FinanceController` exclusively controls capital cycles, runs
    selection, and terminates transition service agreements."

    Design: Corner/rbac/portfolio_manager_cannot_terminate_tsa
    """
    _, _, tsa = setup_divestiture_closed()
    assert tsa["tsa_status"] == "ACTIVE", "Setup failed"
    resp = api_client.terminate_tsa(tsa["id"], PM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_tsa_for_divestiture(tsa["divestiture_id"])["tsa_status"] == "ACTIVE"


def test_plant_director_certifying_at_non_target_plant_returns_ownership_mismatch():
    """PRD §2.1: "When `X-User-Role` is `PlantDirector`, `X-User-ID` is the
    `id` of the acting `Plant`; the caller may certify a qualification run only
    when their `X-User-ID` equals the transfer's target plant `id`."
    PRD §2.1: "A violation of any entity-backed ownership rule is rejected with
    `ERR_OWNERSHIP_MISMATCH` (HTTP 403)".

    Design: Corner/rbac/plant_director_certifying_at_non_target_plant_returns_ownership_mismatch
    """
    _, source_plant, target_plant, _, transfer = setup_transfer_planned()
    # The SOURCE plant's director is the wrong identity for the target plant.
    resp = api_client.record_qualification_run(
        transfer["id"],
        create_qualification_run_payload(run_date="2026-09-02T00:00:00Z"),
        make_plant_director_headers(source_plant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_retailer_buyer_responding_for_other_retailer_returns_ownership_mismatch():
    """PRD §2.1: "When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the
    `id` of the acting `Retailer`; the caller may respond to a combined
    negotiation only when their `X-User-ID` equals the negotiation's retailer
    `id`."

    Design: Corner/rbac/retailer_buyer_responding_for_other_retailer_returns_ownership_mismatch
    """
    retailer1, _, negotiation = setup_negotiation_terms_proposed()
    retailer2 = create_retailer(risk_rating="HIGH")
    resp = api_client.respond_to_negotiation(
        negotiation["id"],
        create_negotiation_respond_payload("ACCEPT"),
        make_retailer_buyer_headers(retailer2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    after = validate_ok(api_client.get_combined_negotiation(negotiation["id"], PM))
    assert after["negotiation_status"] == "TERMS_PROPOSED"
    assert after["retailer_id"] == retailer1["id"]


def test_brand_manager_creates_item_for_own_brand_succeeds():
    """PRD §3.1: "A `BrandManager` may create items only under the brand they
    manage — the request's `brand_id` must equal their `X-User-ID`, failing
    which the create is rejected with `ERR_OWNERSHIP_MISMATCH` — while a
    `PortfolioManager` may create items for any brand."

    Design: Corner/rbac/brand_manager_creates_item_for_own_brand_succeeds
    """
    brand = create_brand()
    plant = create_plant()
    resp = api_client.create_item(
        create_item_payload(brand["id"], plant["id"]),
        make_brand_manager_headers(brand["id"]),
    )
    item = validate_created(resp)
    assert item["item_status"] == "LISTED"
    assert item["brand_id"] == brand["id"]
