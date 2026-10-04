"""Take-off quote cycle: revision loop, expiry boundary, invalid transitions,
and ownership."""
from test_helpers import (
    ApiErrorId,
    accept_takeoff,
    create_branch,
    create_takeoff,
    get_takeoff,
    set_clock,
    setup_builder_with_job,
    setup_quoted_takeoff,
    submit_design,
    make_builder_contact_headers,
    validate_error,
    validate_success,
    create_active_builder,
    create_job,
    get_success_data,
)
from test_helpers import api_client as api
from test_helpers.fixtures import ACCT


def test_takeoff_revision_loop_restores_quoted_and_counts_revision():
    """PRD §3.5: "A builder who wants changes requests a revision while the
    request is QUOTED, supplying a revision_note; the request moves to
    REVISION_REQUESTED and revision_count increments by 1." and "The same
    submission is also valid from REVISION_REQUESTED, in which case both
    fields are overwritten and quoted_at is refreshed."

    Design: Difficulty/non_linear_state_machine/takeoff_revision_loop_restores_quoted_and_counts_revision
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_quoted_takeoff(quoted_total_cents=800000, design_ref="DSN-A")
    branch = scenario["branch"]
    builder = scenario["builder"]
    takeoff = scenario["takeoff"]
    bc_headers = make_builder_contact_headers(builder["id"])

    resp = api.revise_takeoff(
        takeoff["id"], {"revision_note": "resize garage bay"}, bc_headers
    )
    validate_success(resp)

    revised = submit_design(
        takeoff["id"], design_package_reference="DSN-B",
        quoted_total_cents=850000,
    )
    assert revised["takeoff_status"] == "QUOTED"

    resp = api.accept_takeoff(
        takeoff["id"],
        {"branch_id": branch["id"], "pricing_week_mode": "LOCK_AT_ACCEPT"},
        bc_headers,
    )
    order = validate_success(resp, expected_status=201)

    final = get_takeoff(takeoff["id"])
    assert final["takeoff_status"] == "ACCEPTED"
    assert final["revision_count"] == 1
    assert final["quoted_total_cents"] == 850000
    assert final["design_package_reference"] == "DSN-B"

    assert order["order_status"] == "DRAFT"
    assert order["order_total_cents"] == 850000
    assert order["takeoff_request_id"] == takeoff["id"]


def test_takeoff_revision_count_increments_on_each_revise():
    """PRD §3.5: "A builder who wants changes requests a revision while the
    request is QUOTED, supplying a revision_note; the request moves to
    REVISION_REQUESTED and revision_count increments by 1." Two full
    QUOTED -> REVISION_REQUESTED -> QUOTED loops leave revision_count at 2.

    Design: Difficulty/non_linear_state_machine/takeoff_revision_loop_restores_quoted_and_counts_revision
    """
    set_clock("2026-09-01T00:00:00Z")
    scenario = setup_quoted_takeoff(quoted_total_cents=800000, design_ref="DSN-A")
    builder = scenario["builder"]
    takeoff = scenario["takeoff"]
    bc_headers = make_builder_contact_headers(builder["id"])

    for i in (1, 2):
        resp = api.revise_takeoff(
            takeoff["id"], {"revision_note": f"revision {i}"}, bc_headers
        )
        validate_success(resp)
        submit_design(
            takeoff["id"], design_package_reference=f"DSN-{i}",
            quoted_total_cents=800000 + i,
        )

    final = get_takeoff(takeoff["id"])
    assert final["takeoff_status"] == "QUOTED"
    assert final["revision_count"] == 2
    assert final["quoted_total_cents"] == 800002


def test_takeoff_accept_from_submitted_rejected():
    """PRD §3.5: "Acceptance is guarded by three checks: the request must be
    QUOTED" and PRD §3.5: "Submitting a design from any other status is
    ERR_INVALID_STATE." An accept on a never-quoted takeoff is
    ERR_INVALID_STATE.

    Design: Corner/state_machines/takeoff_accept_from_submitted_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    branch = create_branch()
    builder, job = setup_builder_with_job(5000000)
    takeoff = create_takeoff(job["id"], builder["id"])

    resp = api.accept_takeoff(
        takeoff["id"],
        {"branch_id": branch["id"], "pricing_week_mode": "LOCK_AT_ACCEPT"},
        make_builder_contact_headers(builder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_takeoff(takeoff["id"])["takeoff_status"] == "SUBMITTED"


def test_submit_design_twice_second_is_invalid_state_idempotency():
    """PRD §3.5: "From SUBMITTED this moves the request to QUOTED, setting
    both fields and stamping quoted_at from the logical clock. ... Submitting
    a design from any other status is ERR_INVALID_STATE."

    Design: Corner/state_machines/submit_design_twice_second_is_invalid_state_idempotency
    """
    set_clock("2026-09-01T00:00:00Z")
    branch = create_branch()
    builder, job = setup_builder_with_job(5000000)
    takeoff = create_takeoff(
        job["id"], builder["id"], includes_floor_system_design=False
    )
    submit_design(takeoff["id"], design_package_reference="DSN-A",
                  quoted_total_cents=800000)

    resp = api.submit_design(
        takeoff["id"],
        {"design_package_reference": "DSN-X", "quoted_total_cents": 1},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    final = get_takeoff(takeoff["id"])
    assert final["quoted_total_cents"] == 800000
    assert final["design_package_reference"] == "DSN-A"


def test_quote_expiry_boundary_exact_plus_fourteen_days_valid():
    """PRD §3.5: `acceptance or revision is rejected with ERR_QUOTE_EXPIRED
    (HTTP 400) once the logical clock is strictly later than quoted_at plus 14
    days, while a quote at exactly the fourteen-day mark is still valid;`

    Design: Corner/calculations/quote_expiry_boundary_exact_plus_fourteen_days_valid
    """
    set_clock("2026-09-01T00:00:00Z")
    branch = create_branch()
    builder, job = setup_builder_with_job(5000000)
    t_a = create_takeoff(job["id"], builder["id"], plan_reference="PLAN-A")
    t_b = create_takeoff(job["id"], builder["id"], plan_reference="PLAN-B")

    set_clock("2026-09-05T10:00:00Z")
    submit_design(t_a["id"], design_package_reference="DSN-A",
                  quoted_total_cents=800000)
    submit_design(t_b["id"], design_package_reference="DSN-B",
                  quoted_total_cents=810000)

    bc_headers = make_builder_contact_headers(builder["id"])

    set_clock("2026-09-19T10:00:00Z")
    resp = api.accept_takeoff(
        t_a["id"],
        {"branch_id": branch["id"], "pricing_week_mode": "LOCK_AT_ACCEPT"},
        bc_headers,
    )
    order = validate_success(resp, expected_status=201)
    assert order["order_status"] == "DRAFT"
    assert order["order_total_cents"] == 800000

    set_clock("2026-09-19T10:00:01Z")
    resp = api.accept_takeoff(
        t_b["id"],
        {"branch_id": branch["id"], "pricing_week_mode": "LOCK_AT_ACCEPT"},
        bc_headers,
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
    assert get_takeoff(t_b["id"])["takeoff_status"] == "EXPIRED"
