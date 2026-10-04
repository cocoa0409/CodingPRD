"""Corner queue: validation claims — authorization ordering (role before
existence, existence before state), entity-backed ownership on item creation,
and segregation of duties on case decisions.
"""
from test_helpers import (
    ABSENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_decide_payload,
    create_item_payload,
    create_plant,
    make_brand_manager_headers,
    setup_scored_case,
    validate_error,
    validate_ok,
)

PM = TEST_USERS["portfolio_manager_headers"]
PM_PROPOSER = TEST_USERS["portfolio_manager_proposer_headers"]


def test_forbidden_role_precedes_existence_on_decide():
    """PRD §2.8: "When several validation rules could reject the same request,
    the server evaluates them in a fixed global order, and the first failing
    check determines the error returned."
    PRD §2.8: "3. The endpoint permits the caller's role (`ERR_FORBIDDEN_ROLE`)."
    preceding "5. Path `id` parameters resolve, checked left to right
    (`ERR_NOT_FOUND`)."

    Design: Corner/validations/forbidden_role_precedes_existence_on_decide
    """
    brand = create_brand()
    # BrandManager is not in decide's role list (PRD §4: PortfolioManager);
    # the case id does not exist — the role check (priority 3) fires first.
    resp = api_client.decide_rationalization_case(
        ABSENT_UUID,
        create_decide_payload("APPROVE"),
        make_brand_manager_headers(brand["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_existence_precedes_state_on_decide():
    """PRD §2.8: "5. Path `id` parameters resolve, checked left to right
    (`ERR_NOT_FOUND`)." preceding "7. Generic single-entity and cross-entity
    state guards (`ERR_INVALID_STATE`)".

    Design: Corner/validations/existence_precedes_state_on_decide
    """
    resp = api_client.decide_rationalization_case(
        ABSENT_UUID, create_decide_payload("APPROVE"), PM
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_brand_manager_cannot_create_item_for_other_brand():
    """PRD §3.1: "A `BrandManager` may create items only under the brand they
    manage — the request's `brand_id` must equal their `X-User-ID`, failing
    which the create is rejected with `ERR_OWNERSHIP_MISMATCH` — while a
    `PortfolioManager` may create items for any brand."

    Design: Corner/validations/brand_manager_cannot_create_item_for_other_brand
    """
    brand1 = create_brand()
    brand2 = create_brand()
    plant = create_plant()
    resp = api_client.create_item(
        create_item_payload(brand2["id"], plant["id"]),
        make_brand_manager_headers(brand1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_same_user_cannot_decide_own_case():
    """PRD §3.2: "Segregation of duties is enforced: the deciding caller's
    `X-User-ID` must differ from the case's `proposer_user_id`, and a
    self-decision is rejected with `ERR_SELF_DECISION` (HTTP 403)."

    Design: Corner/validations/same_user_cannot_decide_own_case
    """
    _, _, _, case = setup_scored_case()  # proposed by pm-proposer-1
    resp = api_client.decide_rationalization_case(
        case["id"], create_decide_payload("APPROVE"), PM_PROPOSER  # same identity
    )
    validate_error(resp, ApiErrorId.ERR_SELF_DECISION)
    after = validate_ok(api_client.get_rationalization_case(case["id"], PM))
    assert after["case_status"] == "SCORED", "a self-decision must not move the case"
