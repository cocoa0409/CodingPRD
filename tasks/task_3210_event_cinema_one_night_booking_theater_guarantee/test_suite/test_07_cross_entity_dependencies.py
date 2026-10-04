"""Cross-entity state dependencies: one entity's state gating another's transition."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    run_on_sale_sweep, first_screening, make_exhibitor_headers,
    setup_booking_approved, setup_verified_delivery,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def _pending_circuit_booking():
    """Every booking precondition satisfied, but the circuit is left PENDING."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(accredit=False, credit_rating="B",
                             settlement_terms="NET_30", screen_pool_total=2000)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": booking, "line": line}


def test_submit_is_refused_while_the_circuit_is_not_accredited():
    """PRD §3.2: "A `DRAFT` booking moves to `PENDING_APPROVAL` only when all six of
    the following hold: the committed screen total has reached the booking's
    `min_screens`; the booking carries at least one line; `on_sale_at` is at or after
    the current clock instant; the guarantee is at or above the distributor's floor;
    the circuit is `ACCREDITED`; and the title is in `BOOKABLE` or `CLEARED`".
    PRD §3.2: "a title whose status will not permit a new commitment is
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/booking_submit_requires_accredited_circuit
    """
    scene = _pending_circuit_booking()
    booking = scene["booking"]
    resp = api_client.submit_booking(booking["id"], booking["version"],
                                     make_exhibitor_headers(scene["circuit"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_booking(booking["id"])["status"] == "DRAFT"


def test_submit_refusal_is_caused_only_by_the_circuit_state():
    """PRD §3.1: "A circuit starts `PENDING` and must be accredited before it may
    commit anything: accreditation requires a screen pool of at least 1 and moves it
    to `ACCREDITED`".
    PRD §3.2: "the committed screen total has reached the booking's `min_screens`".

    Design: Difficulty/cross_entity_state_dependency/booking_submit_requires_accredited_circuit
    """
    scene = _pending_circuit_booking()
    booking = get_booking(scene["booking"]["id"])
    assert scene["circuit"]["status"] == "PENDING"
    assert booking["status"] == "DRAFT"
    assert booking["committed_screens_total"] >= booking["min_screens"], (
        "the booking's own screen precondition holds, so the circuit's state is the "
        "only blocker"
    )


def test_accrediting_the_circuit_alone_unblocks_the_identical_submit():
    """PRD §3.1: "A circuit starts `PENDING` and must be accredited before it may
    commit anything".

    Design: Difficulty/cross_entity_state_dependency/booking_submit_requires_accredited_circuit
    """
    scene = _pending_circuit_booking()
    # §2.5: the submitted request must attest the version the client last observed,
    # so re-read the booking rather than reuse the snapshot taken before the refusal.
    booking = get_booking(scene["booking"]["id"])
    get_success_data(api_client.accredit_circuit(scene["circuit"]["id"], OPS))
    submitted = get_success_data(api_client.submit_booking(
        booking["id"], booking["version"],
        make_exhibitor_headers(scene["circuit"]["id"])))
    assert submitted["status"] == "PENDING_APPROVAL", (
        "the same request now succeeds with no change to the booking payload"
    )


def _on_sale_booking_with_unverified_delivery(verify=False):
    """ON_SALE booking with a key minted; the package is DELIVERED but not VERIFIED."""
    ctx = setup_booking_approved()
    booking = ctx["booking"]
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    ctx["booking"] = get_booking(booking["id"])
    setup_verified_delivery(ctx, verify=verify)
    key = get_success_data(api_client.create_encryption_key(
        {"screening_id": ctx["screening"]["id"],
         "not_valid_before_utc": "2026-12-01T00:00:00Z",
         "not_valid_after_utc": "2026-12-01T03:00:00Z"}, OPS))
    ctx["key"] = key
    return ctx


def test_delivery_reaches_delivered_but_not_verified():
    """PRD §3.4: "the package moves to `DELIVERED`, its `delivered_at_utc` is stamped
    with the current clock instant, and the received checksum is stored."

    Design: Difficulty/cross_entity_state_dependency/key_issue_requires_verified_content_delivery
    """
    ctx = _on_sale_booking_with_unverified_delivery()
    assert ctx["delivery"]["status"] == "DELIVERED"


def test_key_issuance_is_refused_on_the_packages_state():
    """PRD §3.4: "A key may be issued only when the screening it unlocks is still
    `SCHEDULED` — a screening that has already been skipped or voided yields
    `ERR_KEY_NOT_ISSUABLE` — when the parent booking is in `ON_SALE`, `CONFIRMED`, or
    `SETTLED`, and when the booking's content package has reached `VERIFIED`; a
    booking whose package has not verified yields `ERR_DELIVERY_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/key_issue_requires_verified_content_delivery
    """
    ctx = _on_sale_booking_with_unverified_delivery()
    resp = api_client.issue_key(ctx["key"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_VERIFIED, 409)
    assert ctx["booking"]["status"] == "ON_SALE", (
        "the screening is scheduled and the booking is in a key-issuable status, so "
        "only the delivery's state blocks issuance"
    )


def test_verifying_the_package_alone_unblocks_the_identical_issue():
    """PRD §3.4: "That last gate is the reason a failed package is not a recoverable
    nuisance: until a replacement package is registered and verified, no key of that
    booking can be issued at all, and the run cannot be played."

    Design: Difficulty/cross_entity_state_dependency/key_issue_requires_verified_content_delivery
    """
    ctx = _on_sale_booking_with_unverified_delivery()
    verified = get_success_data(api_client.verify_delivery(ctx["delivery"]["id"], OPS))
    assert verified["status"] == "VERIFIED"
    issued = get_success_data(api_client.issue_key(ctx["key"]["id"], OPS))
    assert issued["issuance_status"] == "ISSUED"
    assert isinstance(issued["key_ref"], str) and issued["key_ref"], (
        "a system-minted key reference appears only on issuance"
    )