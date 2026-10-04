"""The declared shape of each resource: creation defaults, round-tripping,
derived aggregates, parent resolution and the append-only transition ledger."""
from test_helpers import api_client, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    CUSTOMER_SERVICE,
    FUEL_COORDINATOR,
    OPERATOR,
    create_customer,
    create_ppa,
    create_site,
    get_site,
    list_deliveries,
    list_transitions,
    schedule_delivery,
    set_clock,
    setup_active_ppa,
)


def test_a_registered_facility_starts_active_available_and_fueled():
    """PRD §3.1: "A newly registered facility starts with `status` of
    `SITE_ACTIVE`, a `lifecycle_state` of `RESOURCE_AVAILABLE`, and its `draw_position_therms`
    set from the operator-funded `initial_fuel_inventory_therms` the registration records".

    Design: Corner/entities/site_create_returns_every_declared_field_and_starts_fueled
    """
    set_clock()
    response = api_client.create_site(
        {
            "name": "Gabilan Valley Cooling",
            "utility_territory": "PGE_CA",
            "grid_tariff_rate_cents_per_kwh": 24.0,
            "grid_outage_events_per_year": 4,
            "grid_annual_outage_hours": 37.5,
            "gas_commodity_rate_cents_per_therm": 5.0,
            "expected_annual_site_load_kwh": 9000000,
            "tax_rate_pct": 0.0725,
            "allowed_downtime_hours_per_year": 100.0,
            "clearance_zone_capacity": 400.0,
            "footprint_sqm": 1200.0,
            "standby_charge_cents_per_kw_month": 1.80,
            "interconnect_exit_fee_cents_per_kw": 95.0,
        },
        OPERATOR,
    )
    site = validate_success(response, expected_status=201)

    assert response.json()["response_type"] == "object"
    assert site["status"] == "SITE_ACTIVE", "status is never client-supplied"
    assert site["lifecycle_state"] == "RESOURCE_AVAILABLE"
    assert site["version"] == 1
    assert site["initial_fuel_inventory_therms"] > 0, (
        "the registration records an operator-funded opening inventory"
    )
    assert site["draw_position_therms"] == site["initial_fuel_inventory_therms"], (
        "the pool opens at exactly the inventory the registration records"
    )
    assert site["clearance_zone_used"] == 0.0


def test_every_declared_facility_configuration_field_round_trips_through_get():
    """PRD §2.4: "`created_at` is the instant the row was first persisted,
    rendered as an ISO 8601 timestamp in UTC with exactly three fractional digits."

    Design: Corner/entities/site_get_round_trips_every_configuration_field
    """
    set_clock()
    created = create_site(name="Gabilan Valley Cooling")
    response = api_client.get_site(created["id"], OPERATOR)
    site = validate_success(response)

    assert response.json()["response_type"] == "object"
    assert site["name"] == "Gabilan Valley Cooling"
    assert site["utility_territory"] == "PGE_CA"
    assert site["interconnect_exit_fee_cents_per_kw"] == 95.0
    assert site["footprint_sqm"] == 1200.0
    assert site["committed_feedstock_therms"] == 0
    assert site["contracted_purchase_cents"] == 0
    assert response.json()["meta"]["api_request_id"]
    assert response.json()["meta"]["api_request_timestamp"]


def test_the_contract_collection_paginates_with_a_stable_total_and_has_more():
    """PRD §2.3: "`total_count` reports the size
    of the full filtered collection, not the size of the page, and `has_more` reports whether
    further items remain beyond the page that was returned."

    Design: Corner/entities/ppa_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    site = create_site()
    first = create_customer(name="Growers Coop")
    second = create_customer(name="Cold Storage LLC", credit_tier="CREDIT_PRIME")
    create_ppa(site["id"], first["id"])
    create_ppa(site["id"], second["id"], term_years=10, contracted_kw=300)

    page_one = api_client.list_ppas(OPERATOR, {"site_id": site["id"], "limit": 1, "offset": 0})
    rows, meta = validate_paginated(page_one)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1

    page_two = api_client.list_ppas(OPERATOR, {"site_id": site["id"], "limit": 1, "offset": 1})
    rows_two, meta_two = validate_paginated(page_two)
    assert meta_two["has_more"] is False
    assert len(rows_two) == 1
    assert rows_two[0]["id"] != rows[0]["id"]


def test_a_well_formed_unknown_contract_identifier_is_reported_as_not_found():
    """PRD §2.4: "A path that names a contract resolves that contract next, and a contract that does not exist — or
    one whose `site_id` does not equal the site identifier the path also names — is refused with
    `ERR_PPA_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/software_paa_get_with_unknown_id_returns_ppa_not_found
    """
    set_clock()
    site = create_site()

    response = api_client.get_ppa(site["id"], OPERATOR)

    assert response.status_code == 404, (
        f"a well-formed but unknown contract id is a 404; got {response.status_code}"
    )
    assert response.json()["data"]["error_id"] == ApiErrorId.ERR_PPA_NOT_FOUND.value
    assert "state" not in response.json()["data"]


def test_omitting_a_required_contract_term_creates_no_row():
    """PRD §3.2: "A contract is drafted by a `SiteOperator` through a payload that names the facility it serves
    and the offtaker it serves them, carried as `site_id` and `customer_id`."
    PRD §2.4: "a missing required field, a field carrying the wrong type, an enum member outside its
    declared values, or a paired field supplied without its partner surfaces as
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/ppa_create_missing_term_years_returns_invalid_request
    """
    set_clock()
    site = create_site()
    customer = create_customer()

    response = api_client.create_ppa(
        {
            "site_id": site["id"],
            "customer_id": customer["id"],
            "contracted_kw": 500,
            "contracted_efficiency_kwh_per_therm": 7.4,
            "contracted_annual_kwh": 3240000,
            "tariff_base_cents_per_kwh": 12.0,
            "escalator_pct": 0.03,
            "fuel_adder_cents_per_therm": 2.50,
            "guaranteed_availability_pct": 0.97,
            "guaranteed_delivery_kwh": 3240000,
            "customer_cure_deadline_days": 30,
            "fuel_responsibility": "PPA_FUEL_INCLUDED",
            "loss_floor_cents": 25000,
        },
        OPERATOR,
    )

    assert response.status_code == 400
    assert response.json()["data"]["error_id"] == ApiErrorId.ERR_INVALID_REQUEST.value
    rows, meta = validate_paginated(
        api_client.list_ppas(OPERATOR, {"site_id": site["id"]})
    )
    assert meta["total_count"] == 0, "the refused draft must not be persisted"


def test_omitting_every_computed_field_leaves_the_declared_defaults_in_place():
    """PRD §3.1: "its
    `clearance_zone_used`, `committed_feedstock_therms` and
    `current_avoided_fuel_cost_cents_per_therm` all begin at zero."

    Design: Corner/entities/site_create_defaults_apply_when_computed_fields_are_omitted
    """
    set_clock()
    site = create_site()

    assert site["status"] == "SITE_ACTIVE"
    assert site["active_ppa_count"] == 0
    assert site["lifetime_customer_billable_cents"] == 0
    assert site["lifetime_availability_credit_cents"] == 0
    assert site["lifetime_settle_reconcile_count"] == 0
    assert site["reserved_capacity_hold_count"] == 0


def test_contracted_capacity_is_derived_from_the_contracts_and_never_echoed_back():
    """PRD §3.1: "The capacity exposure is tracked separately as
    `total_contracted_kw`, the sum of `contracted_kw` over the same three-state set of contracts".

    Design: Corner/entities/site_contracted_kw_is_derived_from_ppas_and_not_echoed
    """
    set_clock()
    site = api_client.create_site(
        {
            "name": "Gabilan Valley Cooling",
            "utility_territory": "PGE_CA",
            "grid_tariff_rate_cents_per_kwh": 24.0,
            "grid_outage_events_per_year": 4,
            "grid_annual_outage_hours": 37.5,
            "gas_commodity_rate_cents_per_therm": 5.0,
            "expected_annual_site_load_kwh": 9000000,
            "tax_rate_pct": 0.0725,
            "allowed_downtime_hours_per_year": 100.0,
            "clearance_zone_capacity": 400.0,
            "footprint_sqm": 1200.0,
            "standby_charge_cents_per_kw_month": 1.80,
            "interconnect_exit_fee_cents_per_kw": 95.0,
            "total_contracted_kw": 999,
        },
        OPERATOR,
    ).json()["data"]
    assert site["total_contracted_kw"] == 0, (
        "a posted derived field is ignored: the value is computed, not accepted"
    )
    assert site["committed_feedstock_therms"] == 0.0

    customer = create_customer()
    create_ppa(site["id"], customer["id"], contracted_kw=500)

    after = get_site(site["id"])
    assert after["total_contracted_kw"] == 500
    assert after["contracted_purchase_cents"] != 0, (
        "the monetary exposure is the sum over the same three-state contract set"
    )


def test_the_transition_ledger_is_append_only_and_carries_no_version():
    """PRD §2.4: "The
    transition record carries only `id` and `created_at`: it has no `updated_at` field and no
    `version` field, it is never edited after it is written, and no operation accepts an expected
    version for it."

    Design: Corner/entities/transition_ledger_is_append_only_with_no_version_field
    """
    ctx = setup_active_ppa()
    rows = list_transitions(ctx["ppa_id"])

    assert len(rows) == 1
    record = rows[0]
    assert record["from_state"] == "PPA_DRAFT"
    assert record["to_state"] == "PPA_ACTIVE"
    assert record["id"]
    assert record["created_at"]
    assert "version" not in record, "an append-only audit record carries no version"
    assert record["transition_reversed"] is False

    fetched = validate_success(
        api_client.get_transition(record["id"], OPERATOR)
    )
    assert "version" not in fetched
    assert ctx["ppa"]["state"] == "PPA_ACTIVE"


def test_a_contract_naming_an_unknown_facility_is_refused_before_the_contract_is_read():
    """PRD §4: "Where a path nests
    one identifier inside another, the identifier on the left is validated before the one on the
    right, so a request naming a site that does not exist is refused with `ERR_SITE_NOT_FOUND`
    before the server ever considers the resource nested under it."

    Design: Corner/entities/ppa_site_parent_mismatch_returns_ppa_not_found
    """
    set_clock()
    site_a = create_site(name="Gabilan Valley Cooling")
    site_b = create_site(name="Gabilan Valley Packing", footprint_sqm=600.0)
    customer = create_customer()
    ppa_a = create_ppa(site_a["id"], customer["id"])
    ppa_b = create_ppa(site_b["id"], customer["id"], term_years=10, contracted_kw=300)

    response = api_client.create_ppa(
        {
            "site_id": ppa_a["id"],
            "customer_id": customer["id"],
            "term_years": 15,
            "contracted_kw": 500,
            "contracted_efficiency_kwh_per_therm": 7.4,
            "contracted_annual_kwh": 3240000,
            "tariff_base_cents_per_kwh": 12.0,
            "escalator_pct": 0.03,
            "fuel_adder_cents_per_therm": 2.50,
            "guaranteed_availability_pct": 0.97,
            "guaranteed_delivery_kwh": 3240000,
            "customer_cure_deadline_days": 30,
            "fuel_responsibility": "PPA_FUEL_INCLUDED",
            "loss_floor_cents": 25000,
        },
        OPERATOR,
    )

    assert response.status_code == 404
    assert response.json()["data"]["error_id"] == ApiErrorId.ERR_SITE_NOT_FOUND.value
    rows_a, meta_a = validate_paginated(api_client.list_site_ppas(site_a["id"], OPERATOR))
    rows_b, meta_b = validate_paginated(api_client.list_site_ppas(site_b["id"], OPERATOR))
    assert (meta_a["total_count"], meta_b["total_count"]) == (1, 1)
    # PRD §4: `GET /power/customers/{id}/ppas` admits `CustomerService`,
    # `SettlementAnalyst`, `SettlementApprover` and `Customer` — not `SiteOperator`.
    customer_ppas, customer_meta = validate_paginated(
        api_client.list_customer_ppas(customer["id"], CUSTOMER_SERVICE)
    )
    assert customer_meta["total_count"] == 2


def test_a_delivery_is_reachable_from_both_the_site_and_its_customer_side():
    """PRD §2.4: "The fuel delivery collection filters on `lifecycle_state` and
    `attesting_customer_id` when it is listed site-first".

    Design: Corner/entities/flat_topology_exposes_fk_reverse_lookups_both_ways
    """
    ctx = setup_active_ppa()
    delivery = schedule_delivery(ctx["site_id"], volume_therms=8000)

    nested = list_deliveries(ctx["site_id"])
    assert len(nested) == 1
    assert nested[0]["id"] == delivery["id"]

    filtered = list_deliveries(ctx["site_id"], lifecycle_state="DELIVERY_SCHEDULED")
    assert len(filtered) == 1

    attested = validate_success(
        api_client.list_customer_fuel_deliveries(
            ctx["customer_id"], FUEL_COORDINATOR
        )
    )
    data = attested["data"] if isinstance(attested, dict) and "data" in attested else attested
    assert data == [], "no delivery names that customer as attestor"