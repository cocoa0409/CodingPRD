"""Agreement formation: body-FK order, point-date and half-open interval
uniqueness, and the financed-activation gate.

Covers PRD §2.10 (body FK order), §3.3 (production-day point-date
uniqueness), §3.1 (half-open agreement interval overlap, activation gate).
Instances: Corner/validations/agreement_body_fk_checked_in_declared_input_order,
Difficulty/resource_temporal_overlap/* (2), and
Difficulty/cross_entity_state_dependency/activate_blocked_until_financing_disbursed.
"""
from test_helpers import (
    FINANCED_AMOUNT_CENTS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    catalog_entry,
    create_agreement_payload,
    create_bakery,
    create_distributor,
    create_draft_agreement,
    create_financing_plan,
    create_listed_territory,
    create_production_day,
    create_production_day_payload,
    disburse_financing_plan,
    find_production_day,
    get_agreement,
    get_distributor,
    get_territory,
    activate_agreement,
    reset_clock_to_default,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["company_admin_headers"]
_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]


def _draft_financed_agreement():
    """Bakery + LISTED territory + distributor + DRAFT agreement with
    financed_amount_cents 52000 and a DRAFT (not yet disbursed) plan."""
    reset_clock_to_default()
    bakery = create_bakery()
    territory = create_listed_territory()
    distributor = create_distributor()
    agreement = create_draft_agreement(
        territory["id"],
        distributor["id"],
        bakery["id"],
        financed_amount_cents=FINANCED_AMOUNT_CENTS,
    )
    plan = create_financing_plan(agreement, principal_cents=FINANCED_AMOUNT_CENTS)
    return bakery, territory, distributor, agreement, plan


def test_agreement_body_fk_checked_in_declared_input_order(api):
    """PRD §2.10: "Foreign keys supplied in request bodies are likewise
    validated in the endpoint's declared input order — agreement creation
    checks `territory_id`, then `distributor_id`, then `bakery_id`, surfacing
    `ERR_TERRITORY_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, or
    `ERR_BAKERY_NOT_FOUND` respectively, each at HTTP 404."

    Design: Corner/validations/agreement_body_fk_checked_in_declared_input_order
    """
    reset_clock_to_default()
    bakery = create_bakery()
    territory = create_listed_territory()
    distributor = create_distributor()
    bad_territory = "00000000-0000-4000-8000-000000000001"
    bad_distributor = "00000000-0000-4000-8000-000000000002"

    resp1 = api_client.create_agreement(
        create_agreement_payload(bad_territory, bad_distributor, bakery["id"]),
        _ROUTE_OPS,
    )
    error1 = validate_error(resp1, ApiErrorId.ERR_TERRITORY_NOT_FOUND)
    assert error1["error_id"] != "ERR_DISTRIBUTOR_NOT_FOUND"

    resp2 = api_client.create_agreement(
        create_agreement_payload(territory["id"], bad_distributor, bakery["id"]),
        _ROUTE_OPS,
    )
    validate_error(resp2, ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND)

    rows, _meta = validate_paginated(
        api_client.list_agreements(
            _ROUTE_OPS, params={"distributor_id": distributor["id"]}
        )
    )
    assert rows == []


def test_production_day_duplicate_same_bakery_date_rejected(api):
    """PRD §3.3: "Only one production day may exist for a given bakery and
    date — a point-date uniqueness, not an interval — and a duplicate is
    rejected with `ERR_PRODUCTION_DAY_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/production_day_point_date_uniqueness
    """
    reset_clock_to_default()
    bakery = create_bakery()
    create_production_day(bakery["id"], "2026-09-04")
    resp = api_client.create_production_day(
        bakery["id"], create_production_day_payload("2026-09-04"), _ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_DAY_EXISTS)
    day = find_production_day(bakery["id"], "2026-09-04")
    assert day["status"] == "PLANNING"
    assert day["version"] == 1


def test_production_day_point_uniqueness_scoped_per_bakery(api):
    """PRD §3.3: "Only one production day may exist for a given bakery and
    date — a point-date uniqueness, not an interval — and a duplicate is
    rejected with `ERR_PRODUCTION_DAY_EXISTS`."
    PRD §3.3: "the day's `capacity_units` takes the override when supplied and
    the bakery's `daily_capacity_units` otherwise, and the day's `bakery_id` is
    taken from the creation path."

    Design: Difficulty/resource_temporal_overlap/production_day_point_date_uniqueness
    """
    reset_clock_to_default()
    bakery = create_bakery()
    bakery2 = create_bakery(
        name="Northwest Bakery",
        daily_capacity_units=50,
        product_catalog=[catalog_entry("WHT-24", "White 24oz", 5, 320)],
    )
    create_production_day(bakery["id"], "2026-09-04")
    day_other_date = create_production_day(bakery["id"], "2026-09-05")
    assert day_other_date["capacity_units"] == 100
    day_other_bakery = create_production_day(bakery2["id"], "2026-09-04")
    assert day_other_bakery["capacity_units"] == 50
    assert day_other_bakery["bakery_id"] == bakery2["id"]


def test_distributor_agreement_overlap_rejected(api):
    """PRD §3.1: "Two intervals intersect when the existing one starts before
    the new one ends and the new one starts before the existing one ends;
    adjacency, where one interval's `end_date` equals the other's `start_date`,
    does not intersect and is allowed. A violating overlap is rejected with
    `ERR_DISTRIBUTOR_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/distributor_agreement_half_open_interval_overlap
    """
    reset_clock_to_default()
    bakery = create_bakery()
    territory = create_listed_territory()
    distributor = create_distributor()
    create_draft_agreement(territory["id"], distributor["id"], bakery["id"])
    territory2 = create_listed_territory(
        area_code="DAL-E", list_price_cents=18000000
    )
    resp = api_client.create_agreement(
        create_agreement_payload(
            territory2["id"],
            distributor["id"],
            bakery["id"],
            purchase_price_cents=800000,
            start_date="2027-06-01",
            end_date="2028-06-01",
        ),
        _ROUTE_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_AGREEMENT_OVERLAP)


def test_distributor_agreement_adjacent_interval_allowed(api):
    """PRD §3.1: "adjacency, where one interval's `end_date` equals the other's
    `start_date`, does not intersect and is allowed."
    PRD §3.1: "on success the territory flips `LISTED → UNDER_AGREEMENT` and
    its `version` advances by one."

    Design: Difficulty/resource_temporal_overlap/distributor_agreement_half_open_interval_overlap
    """
    reset_clock_to_default()
    bakery = create_bakery()
    territory = create_listed_territory()
    distributor = create_distributor()
    create_draft_agreement(territory["id"], distributor["id"], bakery["id"])
    territory2 = create_listed_territory(
        area_code="DAL-E", list_price_cents=18000000
    )
    resp = api_client.create_agreement(
        create_agreement_payload(
            territory2["id"],
            distributor["id"],
            bakery["id"],
            purchase_price_cents=800000,
            start_date="2027-09-01",
            end_date="2028-09-01",
        ),
        _ROUTE_OPS,
    )
    agreement2 = validate_success(resp, 201)
    assert agreement2["status"] == "DRAFT"
    assert agreement2["start_date"] == "2027-09-01"
    assert get_territory(territory2["id"])["status"] == "UNDER_AGREEMENT"


def test_activate_blocked_until_financing_disbursed(api):
    """PRD §3.1: "When `financed_amount_cents` is greater than zero, activation
    is gated: an `ACTIVE` financing plan must already exist for the agreement,
    and its absence rejects the activation with `ERR_FINANCING_NOT_DISBURSED`."

    Design: Difficulty/cross_entity_state_dependency/activate_blocked_until_financing_disbursed
    """
    _, _, distributor, agreement, _plan = _draft_financed_agreement()
    resp = api_client.activate_agreement(agreement["id"], _ROUTE_OPS)
    validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_DISBURSED)
    assert get_agreement(agreement["id"])["status"] == "DRAFT"
    assert get_distributor(distributor["id"])["status"] == "PROSPECT"


def test_activate_succeeds_after_financing_disbursed(api):
    """PRD §3.1: "When `financed_amount_cents` is greater than zero, activation
    is gated: an `ACTIVE` financing plan must already exist for the agreement,
    and its absence rejects the activation with `ERR_FINANCING_NOT_DISBURSED`."
    PRD §3.1: "Activation stamps `activated_on` from the logical clock and
    promotes the distributor `PROSPECT → ACTIVE` — a no-op when the distributor
    is already `ACTIVE` through another agreement — advancing the distributor's
    `version` by one."

    Design: Difficulty/cross_entity_state_dependency/activate_blocked_until_financing_disbursed
    """
    _, _, distributor, agreement, plan = _draft_financed_agreement()
    resp = api_client.activate_agreement(agreement["id"], _ROUTE_OPS)
    validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_DISBURSED)
    disburse_financing_plan(plan["id"])
    activated = activate_agreement(agreement["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["activated_on"] is not None
    assert get_distributor(distributor["id"])["status"] == "ACTIVE"
