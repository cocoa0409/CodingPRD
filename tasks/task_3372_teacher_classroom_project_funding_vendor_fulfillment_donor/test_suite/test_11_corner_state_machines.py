"""State-machine corners: stage gating, terminal lockdown, the delivery
bubble-up across two vendors, the thank-you close, and an early choice."""

from test_helpers import (
    ADMIN_HEADERS,
    REVIEWER_BEN_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_instant,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.constants import BASE_CLOCK
from test_helpers.test_users import make_donor_headers, make_teacher_headers


def test_vet_stage_on_in_review_project_returns_invalid_state(api):
    """stage=VET is legal only from VETTING; against an IN_REVIEW project the
    decision is a state error and nothing is recorded.

    PRD: "Any decision against a project not in the state matching its stage fails with `ERR_INVALID_STATE`."
    Design: Corner/state_machines/vet_stage_on_in_review_project_returns_invalid_state
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]
    fixtures.submit_project(api, project_id, world["teacher"])

    res = api.review_project(
        project_id, f.review_payload("VET", "APPROVE"), REVIEWER_BEN_HEADERS
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "IN_REVIEW"
    assert project.get("screened_by_id") is None, "no screen approval ever recorded"


def test_rejected_project_is_terminal_for_submit(api):
    """REJECTED is terminal: a resubmit with a fresh OCC version still fails
    on the state check.

    PRD: "Vetting applies to a project in `VETTING` and admits three outcomes: `APPROVE` moves the project to `FUNDING`, records the acting reviewer as `vetted_by_id`, stamps `funding_started_at` with the current logical-clock time, and computes `funding_deadline` as that instant plus the project's `funding_window_days`; `RETURN` sends the project back to `RETURNED`; and `REJECT` terminates it as `REJECTED`."
    PRD: "The full project state set is `DRAFT`, `IN_REVIEW`, `VETTING`, `RETURNED`, `REJECTED`, `FUNDING`, `FUNDED`, `EXPIRED`, `CANCELLED`, `FULFILLED`, and `CLOSED`; `REJECTED`, `EXPIRED`, `CANCELLED`, and `CLOSED` are terminal."
    PRD: "Submitting moves a project from `DRAFT` (or `RETURNED`, as a revision loop) to `IN_REVIEW`. The request carries `expected_project_version` and fails stale with `ERR_STALE_VERSION`; a project in any other state fails with `ERR_INVALID_STATE`"
    Design: Corner/state_machines/rejected_project_is_terminal_for_submit
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]
    fixtures.submit_project(api, project_id, world["teacher"])
    fixtures.review_project(api, project_id, "SCREEN", "APPROVE", "rev-ana")
    rejected = fixtures.review_project(api, project_id, "VET", "REJECT", "rev-ben")
    assert rejected["status"] == "REJECTED"

    # The OCC version is current, so the failure must be the state check.
    res = api.submit_project(
        project_id,
        f.submit_payload(fixtures.current_project_version(api, project_id)),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    assert fixtures.read_project(api, project_id)["status"] == "REJECTED"


def test_delivering_the_final_purchase_order_bubbles_project_to_fulfilled(api):
    """Two vendors -> two purchase orders; only the last DELIVER flips the
    project.

    PRD: "At that moment the system groups the project's pinned items by vendor, auto-issues exactly one purchase order per distinct vendor with at least one item (§3.7)"
    PRD: "Delivery confirmation belongs to the project's owning teacher — or to a `PlatformAdmin`; anyone else is `ERR_FORBIDDEN`. Advancing with `action` value `DELIVER` moves a `SHIPPED` order to `DELIVERED` and stamps `delivered_at`. When every purchase order of the project has reached `DELIVERED`, the project bubbles up from `FUNDED` to `FULFILLED` automatically"
    Design: Corner/state_machines/delivering_final_po_bubbles_project_to_fulfilled
    """
    world = fixtures.setup_two_vendor_funded_project(api)
    project_id = world["project"]["id"]
    po_book, po_rug = world["po_book"], world["po_rug"]

    # One purchase order per vendor, each carrying its own lines and quote.
    assert po_book["vendor_id"] == world["vendor"]["id"]
    assert_cents(po_book["line_total_cents"], 10000, "book PO lines")
    assert_cents(po_book["shipping_fee_cents"], 959, "book PO fee")
    assert po_rug["vendor_id"] == world["vendor2"]["id"]
    assert_cents(po_rug["line_total_cents"], 2000, "rug PO lines")
    assert_cents(po_rug["shipping_fee_cents"], 959, "rug PO fee")

    fixtures.ship_purchase_order(api, po_book)
    fixtures.ship_purchase_order(api, po_rug, tracking="1Z888BB20123456789")

    fixtures.deliver_purchase_order(api, po_book["id"], world["teacher"])
    mid = fixtures.read_project(api, project_id)
    assert mid["status"] == "FUNDED", "one PO still SHIPPED: no bubble-up yet"

    fixtures.deliver_purchase_order(api, po_rug["id"], world["teacher"])
    final = fixtures.read_project(api, project_id)
    assert final["status"] == "FULFILLED", "every PO delivered: bubble-up fires"
    assert fixtures.read_purchase_order(api, po_book["id"])["status"] == "DELIVERED"
    assert fixtures.read_purchase_order(api, po_rug["id"])["status"] == "DELIVERED"


def test_thank_you_submission_closes_the_fulfilled_project(api):
    """Submitting the package stamps it from the logical clock and closes the
    project.

    PRD: "The package must be `PENDING` and the project must be `FULFILLED` (`ERR_INVALID_STATE` otherwise), the actor must be the project's owning teacher (`ERR_FORBIDDEN`), and a suspended teacher is blocked by `ERR_TEACHER_SUSPENDED`. On success the package moves to `SUBMITTED`, `submitted_at` is stamped from the logical clock, and the project bubbles up from `FULFILLED` to terminal `CLOSED`."
    Design: Corner/state_machines/thank_you_submission_closes_fulfilled_project
    """
    world = fixtures.setup_fulfilled_project(api)
    project_id = world["project"]["id"]
    assert world["project"]["status"] == "FULFILLED"

    res = api.submit_thank_you_package(
        project_id, f.thank_you_package_payload(), make_teacher_headers(world["teacher"]["id"])
    )
    package = validate_success(res, 200)
    assert package["status"] == "SUBMITTED"
    assert_instant(package["submitted_at"], BASE_CLOCK, "submitted_at")

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "CLOSED", "FULFILLED -> CLOSED bubble-up"

    packages, _meta = validate_paginated(api.get_thank_you_package(project_id, ADMIN_HEADERS))
    assert len(packages) == 1
    assert packages[0]["status"] == "SUBMITTED"


def test_choice_on_a_captured_donation_returns_invalid_state(api):
    """reallocation-choice applies only from CHOICE_PENDING; a CAPTURED
    donation rejects it and no aggregates move.

    PRD: "The donation must still be `CHOICE_PENDING` (`ERR_INVALID_STATE` otherwise)"
    Design: Corner/state_machines/choice_on_captured_donation_returns_invalid_state
    """
    world = fixtures.setup_funding_project(api)
    donor = fixtures.create_donor(api)
    donation = fixtures.donate(api, world["project"]["id"], donor, 5000)
    assert donation["status"] == "CAPTURED"

    res = api.reallocation_choice(
        donation["id"],
        f.reallocation_choice_payload("REFUND", donation["version"]),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    after = fixtures.read_donation(api, donation["id"])
    assert after["status"] == "CAPTURED"
    donor_after = fixtures.read_donor(api, donor["id"])
    assert_cents(donor_after["lifetime_refunded_cents"], 0, "no compensating movement")
