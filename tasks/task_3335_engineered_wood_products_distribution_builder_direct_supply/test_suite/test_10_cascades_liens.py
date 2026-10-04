"""Delivery completion cascade, lien lifecycle, and priority-pair tests."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    create_branch,
    create_order,
    create_product,
    create_takeoff,
    create_truck_shift,
    file_lien,
    get_builder,
    get_job,
    get_lot,
    get_order,
    get_takeoff,
    make_builder_contact_headers,
    receive_lot,
    set_clock,
    setup_builder_with_job,
    setup_delivered_order,
    setup_quoted_takeoff,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT, CREDIT, FLEET


def test_delivery_completion_propagates_lots_order_job_builder():
    """PRD §3.7: "When outcome is COMPLETED, completed_at is stamped from the
    logical clock and the parent order cascades from CONFIRMED to DELIVERED:
    on every reserved lot the delivered quantity moves from qty_reserved_mbf
    into qty_sold_mbf, with fully sold lots becoming SOLD_OUT ... the job's
    exposure_committed_cents decreases by order_total_cents while its
    exposure_settled_cents increases by delivered_total_cents, and
    last_completed_delivery_date is set to the completion date; the builder's
    committed and settled counters shift identically; and the builder's
    version bumps by 1."

    Design: Difficulty/transitive_cascade/delivery_completion_propagates_lots_order_job_builder
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(order_qty=10, unit_price_cents=100000,
                                     lot_qty=10)
    order = scenario["order"]
    builder = scenario["builder"]
    job = scenario["job"]
    lot = scenario["lot"]
    v0 = scenario["builder"]["version"]

    l1 = get_lot(lot["id"])
    assert l1["qty_reserved_mbf"] == 0
    assert l1["qty_sold_mbf"] == 10
    assert l1["lot_status"] == "SOLD_OUT"

    assert order["order_status"] == "DELIVERED"
    assert order["delivered_total_cents"] == 1000000

    job_now = get_job(job["id"])
    assert job_now["last_completed_delivery_date"] == "2026-09-10"
    assert job_now["exposure_settled_cents"] == 1000000
    assert job_now["exposure_committed_cents"] == 0

    builder_now = get_builder(builder["id"])
    assert builder_now["exposure_committed_cents"] == 0
    assert builder_now["exposure_settled_cents"] == 1000000
    assert builder_now["version"] > v0


def test_delivery_completion_sets_completed_at_from_logical_clock():
    """PRD §3.7: "When outcome is COMPLETED, completed_at is stamped from the
    logical clock" and PRD §2.4: "A single server-side logical clock governs
    every system-stamped field — received_at on inventory lots, quoted_at on
    take-off requests, filed_at and released_at on lien filings, and
    completed_at on deliveries".

    Design: Difficulty/transitive_cascade/delivery_completion_propagates_lots_order_job_builder
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(
        order_qty=10, unit_price_cents=100000,
        clock_at_completion="2026-09-10T13:00:00Z",
    )
    delivery = scenario["delivery"]
    assert delivery["completed_at"] == "2026-09-10T13:00:00.000Z"


def test_confirm_on_delivered_order_state_beats_suspended_fiscal():
    """PRD §2.8: "fifth, state-machine legality (ERR_INVALID_STATE); sixth,
    business-temporal rules ... and ninth, fiscal checks (the HTTP 402 credit
    and exposure family). A request failing an earlier category is rejected
    there even if a later category would also fail." PRD §3.6: "Attempting to
    confirm or cancel an order in any other status, including the terminal
    DELIVERED and CANCELLED, is ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/confirm_on_delivered_order_state_beats_suspended_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(order_qty=10, unit_price_cents=100000)
    order = scenario["order"]
    builder = scenario["builder"]

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_order(order["id"])["order_status"] == "DELIVERED"
    assert get_builder(builder["id"])["credit_status"] == "SUSPENDED"


def test_expired_quote_temporal_beats_suspended_builder_fiscal():
    """PRD §2.8: "fifth, state-machine legality (ERR_INVALID_STATE); sixth,
    business-temporal rules (quote expiry, delivery-window containment, the
    drop buffer, lien deadlines) ... and ninth, fiscal checks (the HTTP 402
    credit and exposure family). A request failing an earlier category is
    rejected there even if a later category would also fail." PRD §3.5: "If
    the quote lapses, the request is treated as EXPIRED — the system evaluates
    the expiry at the moment an accept or revise is attempted against the
    strict fourteen-day comparison".

    Design: Difficulty/priority_pair_validation_conflict/expired_quote_temporal_beats_suspended_builder_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    branch = create_branch()
    builder, job = setup_builder_with_job(5000000)
    takeoff = create_takeoff(job["id"], builder["id"],
                             includes_floor_system_design=True)

    set_clock("2026-09-05T10:00:00Z")
    submit_design(takeoff["id"], design_package_reference="DSN-A",
                  quoted_total_cents=800000)

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    set_clock("2026-09-20T10:00:00Z")
    resp = api.accept_takeoff(
        takeoff["id"],
        {"branch_id": branch["id"], "pricing_week_mode": "LOCK_AT_ACCEPT"},
        make_builder_contact_headers(builder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
    assert get_takeoff(takeoff["id"])["takeoff_status"] == "EXPIRED"

    orders, _meta = validate_paginated(
        api.list_sales_orders(ACCT, params={"takeoff_request_id": takeoff["id"]})
    )
    assert orders == []


def test_expired_quote_revise_also_surfaces_temporal_error():
    """PRD §3.5: `acceptance or revision is rejected with ERR_QUOTE_EXPIRED
    (HTTP 400) once the logical clock is strictly later than quoted_at plus 14
    days, while a quote at exactly the fourteen-day mark is still valid;`
    PRD §2.8: "A request failing an earlier category is rejected there even if
    a later category would also fail."

    Design: Difficulty/priority_pair_validation_conflict/expired_quote_temporal_beats_suspended_builder_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    branch = create_branch()
    builder, job = setup_builder_with_job(5000000)
    takeoff = create_takeoff(job["id"], builder["id"])

    set_clock("2026-09-05T10:00:00Z")
    submit_design(takeoff["id"], design_package_reference="DSN-A",
                  quoted_total_cents=800000)

    resp = api.credit_review(builder["id"], {"decision": "SUSPEND"}, CREDIT)
    validate_success(resp)

    set_clock("2026-09-20T10:00:00Z")
    resp = api.revise_takeoff(
        takeoff["id"],
        {"revision_note": "too late"},
        make_builder_contact_headers(builder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
    assert get_takeoff(takeoff["id"])["takeoff_status"] == "EXPIRED"


def test_lien_filing_on_deadline_day_allowed():
    """PRD §3.8: "Second, the logical-clock date must be on or before the lien
    deadline — filing exactly on the deadline day is allowed — where the
    deadline is the job's last_completed_delivery_date plus 90 days; a date
    past the deadline rejects with ERR_LIEN_DEADLINE_PASSED (HTTP 400)." and
    "A filed lien starts in lien_status FILED, records amount_cents as the
    job's exposure_settled_cents at filing time ... carries the computed
    deadline_date".

    Design: Difficulty/boundary_precision_check/lien_filing_on_deadline_day_allowed_day_after_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(
        credit_limit_cents=20000000, order_qty=10, unit_price_cents=100000,
        clock_at_completion="2026-09-10T13:00:00Z",
    )
    job = scenario["job"]

    set_clock("2026-12-09T09:00:00Z")
    lien = file_lien(job["id"])
    assert lien["lien_status"] == "FILED"
    assert lien["deadline_date"] == "2026-12-09"
    assert lien["amount_cents"] == 1000000


def test_lien_filing_day_after_deadline_rejected():
    """PRD §3.8: "Second, the logical-clock date must be on or before the lien
    deadline — filing exactly on the deadline day is allowed — where the
    deadline is the job's last_completed_delivery_date plus 90 days; a date
    past the deadline rejects with ERR_LIEN_DEADLINE_PASSED (HTTP 400)."

    Design: Difficulty/boundary_precision_check/lien_filing_on_deadline_day_allowed_day_after_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(
        credit_limit_cents=20000000, order_qty=10, unit_price_cents=100000,
        clock_at_completion="2026-09-10T13:00:00Z",
    )
    job = scenario["job"]

    set_clock("2026-12-10T09:00:00Z")
    resp = api.create_lien_filing(job["id"], CREDIT)
    validate_error(resp, ApiErrorId.ERR_LIEN_DEADLINE_PASSED)

    liens, _meta = validate_paginated(api.list_job_lien_filings(job["id"], CREDIT))
    assert liens == []


def test_lien_release_valid_transition_then_second_release_rejected():
    """PRD §3.8: "Release is a CreditManager action valid only while the lien
    is FILED; it moves the lien to RELEASED and stamps released_at from the
    logical clock, with any other status rejecting as ERR_INVALID_STATE."

    Design: Corner/state_machines/lien_release_valid_transition_then_second_release_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(
        credit_limit_cents=20000000, order_qty=10, unit_price_cents=100000,
        clock_at_completion="2026-09-10T13:00:00Z",
    )
    job = scenario["job"]

    set_clock("2026-10-01T09:00:00Z")
    lien = file_lien(job["id"])

    released = validate_success(api.release_lien_filing(lien["id"], CREDIT))
    assert released["lien_status"] == "RELEASED"
    assert released["released_at"] == "2026-10-01T09:00:00.000Z"

    resp = api.release_lien_filing(lien["id"], CREDIT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_duplicate_active_lien_rejected():
    """PRD §3.8: "Third, no other lien on the same job may currently be in
    FILED, else ERR_LIEN_ALREADY_ACTIVE (HTTP 409)."

    Design: Corner/errors/duplicate_active_lien_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_delivered_order(
        credit_limit_cents=20000000, order_qty=10, unit_price_cents=100000,
        clock_at_completion="2026-09-10T13:00:00Z",
    )
    job = scenario["job"]

    set_clock("2026-10-01T09:00:00Z")
    lien = file_lien(job["id"])

    resp = api.create_lien_filing(job["id"], CREDIT)
    validate_error(resp, ApiErrorId.ERR_LIEN_ALREADY_ACTIVE)

    liens, _meta = validate_paginated(api.list_job_lien_filings(job["id"], CREDIT))
    assert len(liens) == 1
    assert liens[0]["id"] == lien["id"]
    assert liens[0]["lien_status"] == "FILED"


def test_lien_filing_without_settled_exposure_rejected():
    """PRD §3.8: "First, the job's exposure_settled_cents must be greater than
    0, else ERR_LIEN_NO_OUTSTANDING_EXPOSURE (HTTP 402)."

    Design: Corner/errors/lien_filing_without_settled_exposure_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])
    confirm_order(order["id"])

    resp = api.create_lien_filing(job["id"], CREDIT)
    validate_error(resp, ApiErrorId.ERR_LIEN_NO_OUTSTANDING_EXPOSURE)

    liens, _meta = validate_paginated(api.list_job_lien_filings(job["id"], CREDIT))
    assert liens == []


def test_confirm_on_cancelled_order_rejected_terminal_lockdown():
    """PRD §3.6: "Attempting to confirm or cancel an order in any other
    status, including the terminal DELIVERED and CANCELLED, is
    ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/confirm_on_delivered_order_state_beats_suspended_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    product = create_product()
    branch = create_branch()
    receive_lot(branch["id"], product["id"], 100, 40000)
    builder, job = setup_builder_with_job(5000000)
    order = create_order(job["id"], branch["id"], builder["id"], qty_mbf=10,
                         unit_price_cents=100000, product_id=product["id"])

    resp = api.cancel_sales_order(order["id"], ACCT)
    cancelled = validate_success(resp)
    assert cancelled["order_status"] == "CANCELLED"

    resp = api.confirm_sales_order(order["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_order(order["id"])["order_status"] == "CANCELLED"
