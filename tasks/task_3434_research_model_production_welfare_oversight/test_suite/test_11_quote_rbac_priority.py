"""Order quote tier/surcharge stacking with pinned rounding, the two
cross-category validation-priority pairs, and Customer-role authorization
and ownership denials.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    compute_expected_quote,
    create_active_customer,
    create_allocation_payload,
    create_catalog_strain,
    create_order_payload,
    create_order_submitted,
    create_strain_payload,
    make_customer_headers,
    read_customer,
    setup_sourcing_order,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]
_FM = TEST_USERS["facility_manager_headers"]
_VET = TEST_USERS["veterinarian_headers"]


def _sourced_immuno_vf_order():
    """IMMUNOCOMPROMISED strain in a VF room; 60M/60F order sourced with a VF
    health floor (quote arithmetic is the assertion target)."""
    bundle = setup_sourcing_order(
        quantity_male=60,
        quantity_female=60,
        breeding_pair_count=25,
        order_overrides={"min_health_status": "VF"},
        site_kwargs={
            "strain_overrides": {
                "immune_class": "IMMUNOCOMPROMISED",
                "min_barrier_level": "VF",
            }
        },
    )
    return bundle


def test_order_quote_tiered_surcharge_stacking():
    """PRD Section 3.6: "A volume tier discount applies to the subtotal: 20
    percent when the total quantity is at least 250 animals, otherwise 10
    percent when it is at least 100 animals, otherwise no discount; the
    discounted figure is rounded half-up to integer cents. Then surcharges
    apply to the discounted figure: 25 percent when the strain's
    `immune_class` is `IMMUNOCOMPROMISED` (nothing for `IMMUNOCOMPETENT`),
    plus a barrier premium of 40 percent when the order's `min_health_status`
    is `GERM_FREE`, or 20 percent when it is `VF`, or nothing otherwise; the
    result is again rounded half-up to integer cents to produce
    `quoted_total_cents`."

    Design: Difficulty/combinatorial_formula/order_quote_tiered_surcharge_stacking
    """
    bundle = _sourced_immuno_vf_order()
    order = bundle["order"]
    assert order["status"] == "SOURCING"
    # 120*1000 = 120000; tier -10% -> 108000; surcharges 0.25 + 0.20 ->
    # ROUND_HALF_UP(108000 * 1.45) = 156600.
    expected = compute_expected_quote(120, 1000, "IMMUNOCOMPROMISED", "VF")
    assert expected == 156600
    assert order["quoted_total_cents"] == expected


def test_order_quote_raises_gross_exposure_by_exact_quote():
    """PRD Section 3.6: "A successful sourcing transition computes and stores
    `quoted_total_cents`, raises the customer's GROSS exposure by that amount,
    and increments the order's `version`."
    PRD Section 3.6: "The evaluation order is fixed — tier discount first,
    surcharges second — and each step rounds to integer cents before the next
    consumes it".

    Design: Difficulty/combinatorial_formula/order_quote_tiered_surcharge_stacking
    """
    bundle = _sourced_immuno_vf_order()
    order = bundle["order"]
    customer = bundle["customer"]

    before = read_customer(customer["id"])
    assert before["credit_exposure_cents"] == order["quoted_total_cents"]
    assert before["credit_exposure_cents"] == compute_expected_quote(
        120, 1000, "IMMUNOCOMPROMISED", "VF"
    )


def test_age_window_constraint_beats_credit_hold_fiscal():
    """PRD Section 2.7: "When several rules are violated by the same request,
    the reported error is always the one with the lowest priority number".
    PRD Section 3.6: "a lower bound above the upper bound is
    `ERR_INVALID_AGE_WINDOW`, HTTP 422".
    PRD Section 3.6: "Both `CREDIT_HOLD` and `SUSPENDED` block new order
    submission and order sourcing, and the violation is fiscal in kind:
    `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/age_window_constraint_beats_credit_hold_fiscal
    """
    strain = create_catalog_strain()
    customer = create_active_customer()
    validate_success(
        api_client.transition_customer(
            customer["id"], {"target_state": "CREDIT_HOLD"}, _ADMIN
        )
    )

    # Constraint violation (inverted age window) AND fiscal violation
    # (CREDIT_HOLD) in one request: the constraint's lower priority number
    # wins.
    payload = create_order_payload(
        strain["id"], min_age_weeks=7, max_age_weeks=4,
        quantity_male=5, quantity_female=5,
    )
    resp = api_client.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_AGE_WINDOW)


def test_credit_hold_alone_reports_fiscal_error():
    """PRD Section 3.6: "Both `CREDIT_HOLD` and `SUSPENDED` block new order
    submission and order sourcing, and the violation is fiscal in kind:
    `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/age_window_constraint_beats_credit_hold_fiscal
    """
    strain = create_catalog_strain()
    customer = create_active_customer()
    validate_success(
        api_client.transition_customer(
            customer["id"], {"target_state": "CREDIT_HOLD"}, _ADMIN
        )
    )

    # Control leg: with a valid age window the fiscal violation surfaces on
    # its own — proving the masking in the paired scenario.
    payload = create_order_payload(
        strain["id"], min_age_weeks=4, max_age_weeks=6,
        quantity_male=5, quantity_female=5,
    )
    resp = api_client.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)


def test_quarantine_safety_beats_age_temporal():
    """PRD Section 2.7: "When several rules are violated by the same request,
    the reported error is always the one with the lowest priority number".
    PRD Section 3.7: "Safety first: the room housing the cohort must not be
    `QUARANTINED` or `DECOMMISSIONED` (`ERR_ROOM_QUARANTINED`, HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_beats_age_temporal
    """
    bundle = setup_sourcing_order(
        quantity_male=5, quantity_female=5,
        cohorts=[{
            "count_male": 10, "count_female": 10,
            "birth_date": "2026-06-01T00:00:00Z", "hold": True,
        }],
    )
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    # Manual quarantine (no barrier downgrade) after the order was sourced.
    validate_success(
        api_client.transition_room(
            bundle["site"]["room"]["id"], {"target_state": "QUARANTINED"}, _VET
        )
    )

    # Safety violation (quarantined room) AND temporal violation (cohort age
    # 19 weeks at delivery, window [4,6]): safety's lower priority number
    # wins.
    payload = create_allocation_payload(
        order["id"], cohort["id"], order["version"], qty_male=5, qty_female=5
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_ROOM_QUARANTINED)


def test_stale_age_alone_reports_temporal_error():
    """PRD Section 3.7: "the cohort's age, evaluated per Section 3.3 at the
    order's `required_delivery_date`, must lie within the order's
    `min_age_weeks` to `max_age_weeks` window, both bounds inclusive, else
    `ERR_AGE_SPEC_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_beats_age_temporal
    """
    bundle = setup_sourcing_order(
        quantity_male=5, quantity_female=5,
        cohorts=[{
            "count_male": 10, "count_female": 10,
            "birth_date": "2026-06-01T00:00:00Z", "hold": True,
        }],
    )
    order = bundle["order"]
    cohort = bundle["cohorts"][0]

    # Control leg: no quarantine, so the temporal violation surfaces alone —
    # the cohort is 19 weeks old at the 2026-10-13 delivery, outside [4,6].
    payload = create_allocation_payload(
        order["id"], cohort["id"], order["version"], qty_male=5, qty_female=5
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_AGE_SPEC_MISMATCH)


def test_customer_cannot_create_strain():
    """PRD Section 2.1: "A request whose role is authenticated but is not
    listed among the roles authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD Section 3.2: "A `PlatformAdmin` registers each research model strain
    with a unique `strain_code`".

    Design: Corner/rbac/customer_cannot_create_strain
    """
    customer = create_active_customer()
    resp = api_client.create_strain(
        create_strain_payload(), make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_customer_cannot_read_other_customers_record():
    """PRD Section 2.1: "A `Customer`-role caller whose `X-User-ID` does not
    equal the target resource's owning customer (its own customer record and
    sub-collections, its orders and their allocations and shipments, its
    contracts, its site inspections) is rejected with
    `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD Section 4: "the `Customer` role may read only its own record."

    Design: Corner/rbac/customer_cannot_read_other_customers_record
    """
    customer_a = create_active_customer(institution_name="Inst A")
    customer_b = create_active_customer(institution_name="Inst B")

    resp = api_client.get_customer(
        customer_a["id"], make_customer_headers(customer_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    own = validate_success(
        api_client.get_customer(
            customer_a["id"], make_customer_headers(customer_a["id"])
        )
    )
    assert own["institution_name"] == "Inst A"
