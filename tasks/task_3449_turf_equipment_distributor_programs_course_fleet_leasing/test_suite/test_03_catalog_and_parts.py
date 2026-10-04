"""Catalog governance: part defaults, the supersession graph's acyclicity,
model sales-window aging, and the orderable-parts gate (PRD §3.2 and §3.3).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_part,
    create_catalog_model,
    create_distributor_active,
    create_lease_for,
    create_order_for,
    create_part_for,
    create_part_payload,
    make_distributor_manager_headers,
    run_rollover,
    setup_program,
    validate_error,
    validate_success,
)


def test_part_create_defaults_support_status_active(api, corporate_admin_headers):
    """PRD §3.2: "A new part starts in `ACTIVE` support."

    Design: Corner/entities/part_create_defaults_support_status_active
    """
    model = create_catalog_model()
    part = validate_success(
        api.create_part(create_part_payload(model["id"]), corporate_admin_headers),
        201,
    )
    assert_part(part)
    assert part["support_status"] == "ACTIVE", (
        f"a newly published part starts in ACTIVE support, got {part['support_status']!r}"
    )


def test_part_supersede_cycle_rejected(api, corporate_admin_headers):
    """PRD §3.2: "the supersession graph must remain acyclic — walking
    `superseded_by_part_id` forward from the successor must never arrive back
    at the part being superseded, or the request fails with
    `ERR_SUPERSESSION_CYCLE` (HTTP 422)."

    Design: Corner/validations/part_supersede_cycle_rejected
    """
    model = create_catalog_model()
    p1 = create_part_for(model)
    p2 = create_part_for(model, sku="P2-BEDKNIFE-X", name="Bedknife 13-blade",
                           unit_cost_cents=13500)
    superseded = validate_success(
        api.transition_part(p1["id"], "SUPERSEDED", corporate_admin_headers,
                            successor_part_id=p2["id"])
    )
    assert superseded["support_status"] == "SUPERSEDED"
    assert superseded["superseded_by_part_id"] == p2["id"]

    resp = api.transition_part(
        p2["id"], "SUPERSEDED", corporate_admin_headers, successor_part_id=p1["id"]
    )
    validate_error(resp, ApiErrorId.ERR_SUPERSESSION_CYCLE.value)
    p2_after = validate_success(api.get_part(p2["id"], corporate_admin_headers))
    assert p2_after["support_status"] == "ACTIVE", (
        f"the rejected supersession must leave P2 untouched, got {p2_after['support_status']!r}"
    )


def test_model_auto_discontinued_after_sales_window(api):
    """PRD §3.2: "Catalog aging is enforced by the season rollover: a model
    whose age strictly exceeds 240 months — a twenty-year sales window — is
    moved to `DISCONTINUED`, its terminal state."
    PRD §3.2: "Discontinuation blocks new commercial references: lease lines
    naming the model are rejected with `ERR_MODEL_DISCONTINUED` (HTTP 409)"

    Design: Corner/state_machines/model_auto_discontinued_after_sales_window
    """
    ctx = setup_program()
    advance_clock("2046-10-01T00:00:00Z")  # model age 241 months > 240
    run_rollover()
    resp = api.create_lease(
        {
            "course_id": ctx["course"]["id"],
            "cycle_months": 36,
            "start_date": "2047-03-01",
            "lines": [{"model_id": ctx["model"]["id"], "qty": 1}],
        },
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MODEL_DISCONTINUED.value)


def test_order_submit_discontinued_part_rejected(api, corporate_admin_headers):
    """PRD §3.3: "Submitting the order, moving it from `DRAFT` to `SUBMITTED`,
    is a `DistributorManager` act with four gates. The line rules above are
    re-checked; every referenced part must be in `ACTIVE` or `LAST_BUY`
    support, else `ERR_PART_DISCONTINUED`; the acting distributor's `status`
    must be `ACTIVE`, else `ERR_DISTRIBUTOR_NOT_ACTIVE` (HTTP 409); and the
    distributor must operate the equipment channel, else `ERR_WRONG_CHANNEL`."

    Design: Corner/validations/order_submit_discontinued_part_rejected
    """
    ctx = setup_program()
    part = create_part_for(ctx["model"])
    validate_success(
        api.transition_part(part["id"], "LAST_BUY", corporate_admin_headers)
    )
    validate_success(
        api.transition_part(part["id"], "DISCONTINUED", corporate_admin_headers)
    )

    order = create_order_for(ctx["distributor"], [{"part_id": part["id"], "qty": 2}])
    assert order["status"] == "DRAFT"
    resp = api.transition_parts_order(
        order["id"], "SUBMITTED",
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PART_DISCONTINUED.value)
    after = validate_success(api.get_parts_order(order["id"], corporate_admin_headers))
    assert after["status"] == "DRAFT", (
        f"the rejected submit must leave the order in DRAFT, got {after['status']!r}"
    )
