"""The shape of a refusal: one error identifier per response, and the
identifier that a given defect is reported under."""
from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_fuel_delivery_payload,
    create_settlement_line_payload,
)
from test_helpers.fixtures import (
    ANALYST,
    FUEL_COORDINATOR,
    activate_ppa,
    create_customer,
    create_ppa,
    create_settlement_line,
    create_site,
    get_ppa,
    get_site,
    list_deliveries,
    set_clock,
    setup_active_ppa,
)


def test_a_period_that_is_both_inverted_and_overlapping_reports_one_error():
    """PRD §3.4: "Its `period_end` must be strictly after its `period_start`, or the request
    is refused with `ERR_SETTLEMENT_PERIOD_INVALID` (HTTP 422). Its half-open interval from
    `period_start` to `period_end` must not overlap any existing line on the same contract other
    than lines that have been reversed, or the request is refused with
    `ERR_SETTLEMENT_PERIOD_OVERLAP` (HTTP 422)."
    PRD §2.4: "Validation runs in a fixed order, and the order is observable because only the first failure is
    reported."

    Design: Corner/errors/mixed_priority_request_surfaces_only_the_highest_priority_error
    """
    ctx = setup_active_ppa()
    create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-04-11T00:00:00Z",
    )

    # The span runs backwards and the two instants also land inside the
    # existing line's interval, so two defects are present at once.
    response = api_client.create_settlement_line(
        ctx["ppa_id"],
        ANALYST,
        create_settlement_line_payload(
            expected_ppa_version=get_ppa(ctx["ppa_id"])["version"],
            period_start="2026-04-05T00:00:00Z",
            period_end="2026-04-04T00:00:00Z",
            customer_source_deadline_iso8601="2026-04-02T00:00:00Z",
        ),
    )

    validate_error(response, ApiErrorId.ERR_SETTLEMENT_PERIOD_INVALID)
    assert response.status_code == 422
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value
    ), "only the first failure is reported, so the overlap code must not be the one surfaced"
    assert "error_id" not in response.json()["data"].get("secondary_error", {}), (
        "the error envelope carries a single error identifier"
    )

    rows, meta = validate_paginated(
        api_client.list_settlement_lines(ctx["ppa_id"], ANALYST)
    )
    assert meta["total_count"] == 1, (
        f"the refused period is not persisted; found {meta['total_count']} rows"
    )


def test_a_delivery_attested_by_a_customer_with_no_sourced_contract_is_refused():
    """PRD §2.6: "when a delivery names an `attesting_customer_id`, that
    `Customer` must exist, its `status` must be `CUSTOMER_ACTIVE`, and at least one contract at
    the site must carry `fuel_responsibility` of `CUSTOMER_SOURCED_GAS`. A delivery naming an
    attesting customer that fails any of those three tests is refused with
    `ERR_CUSTOMER_SOURCING_UNVERIFIED` (HTTP 422) — both when the delivery is scheduled and
    again when it is confirmed."

    Design: Corner/errors/customer_sourcing_without_a_sourced_contract_returns_unverified
    """
    ctx = setup_active_ppa()
    assert ctx["ppa"]["fuel_responsibility"] == "PPA_FUEL_INCLUDED"

    response = api_client.create_fuel_delivery(
        ctx["site_id"],
        FUEL_COORDINATOR,
        create_fuel_delivery_payload(
            expected_site_version=get_site(ctx["site_id"])["version"],
            volume_therms=5000,
            attesting_customer_id=ctx["customer_id"],
            delivered_at="2026-03-12T00:00:00Z",
            confirm_after_iso8601="2026-03-13T00:00:00Z",
        ),
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_SOURCING_UNVERIFIED)
    assert response.status_code == 422, (
        f"an uncorroborated attestation is a 422 refusal; got {response.status_code}"
    )
    assert list_deliveries(ctx["site_id"]) == [], (
        "the refused delivery is not persisted and does not draw the pool"
    )
    unchanged = get_site(ctx["site_id"])
    assert unchanged["draw_position_therms"] == unchanged["initial_fuel_inventory_therms"]

    # Once a sourced contract is live at the site, the identical attestation
    # is corroborated and the delivery is accepted.
    sourced = create_ppa(
        ctx["site_id"],
        create_customer(name="Mendocino Timber Partners")["id"],
        fuel_responsibility="CUSTOMER_SOURCED_GAS",
        contracted_kw=300,
        contracted_annual_kwh=1944000,
        guaranteed_delivery_kwh=1944000,
    )
    activate_ppa(sourced["id"])

    accepted = api_client.create_fuel_delivery(
        ctx["site_id"],
        FUEL_COORDINATOR,
        create_fuel_delivery_payload(
            expected_site_version=get_site(ctx["site_id"])["version"],
            volume_therms=5000,
            attesting_customer_id=ctx["customer_id"],
            delivered_at="2026-03-12T00:00:00Z",
            confirm_after_iso8601="2026-03-13T00:00:00Z",
        ),
    )
    validate_success(accepted, expected_status=201)


def test_a_delivery_that_would_reach_the_site_commitment_ceiling_is_refused():
    """PRD §2.6: "Second, a site may carry only a bounded number of
    simultaneous commitments: the count of its deliveries in `DELIVERY_SCHEDULED` or
    `DELIVERY_IN_TRANSIT` must remain strictly below `MAX_ACTIVE_DEMANDS_PER_SITE` at all times,
    and a request that would take the count to that ceiling — whether it is a scheduled delivery,
    a resource hold, or the dispatch of an in-transit load — is refused with
    `ERR_SITE_DEMAND_LIMIT` (HTTP 422). The count used by this guard excludes the delivery
    being evaluated."

    Design: Corner/errors/delivery_over_the_draw_limit_returns_site_demand_limit
    """
    set_clock()
    site = create_site()
    opening = site["draw_position_therms"]
    created = 0
    refusal = None

    # The ceiling is a named policy constant rather than a literal, so the test
    # walks the site up to it instead of assuming its value.
    for _ in range(30):
        response = api_client.create_fuel_delivery(
            site["id"],
            FUEL_COORDINATOR,
            create_fuel_delivery_payload(
                expected_site_version=get_site(site["id"])["version"],
                volume_therms=1000,
                delivered_at="2026-03-12T00:00:00Z",
                confirm_after_iso8601="2026-03-13T00:00:00Z",
            ),
        )
        if response.status_code == 201:
            created += 1
            continue
        refusal = response
        break

    assert refusal is not None, (
        "a site must refuse a delivery once it holds as many simultaneous commitments as "
        "it is allowed to carry"
    )
    validate_error(refusal, ApiErrorId.ERR_SITE_DEMAND_LIMIT)
    assert refusal.status_code == 422
    assert refusal.json()["data"]["error_id"] != (
        ApiErrorId.ERR_INSUFFICIENT_DRAW_POSITION.value
    ), "the volume still fits the pool, so only the commitment count can be the defect"

    after = get_site(site["id"])
    assert after["draw_position_therms"] == opening - created * 1000, (
        "each accepted delivery draws exactly its own volume and the refused one draws nothing"
    )
    assert len(list_deliveries(site["id"])) == created
