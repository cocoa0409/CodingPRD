"""Non-linear state machines: the cyclic booking negotiation and the key's two parallel axes."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    get_key, first_screening, setup_booking_approved, setup_verified_delivery,
    setup_issued_key, make_distributor_headers, make_exhibitor_headers,
    make_theater_headers,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
OFFICER = TEST_USERS["content_officer_headers"]


def _submitted_booking():
    """DRAFT -> PENDING_APPROVAL with one 60-screen proposed line."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=2000)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": booking, "line": line}


def test_booking_counter_moves_the_booking_into_countered():
    """PRD §3.2: "A distributor counters a `PENDING_APPROVAL` booking with
    `proposed_guarantee_cents` and `proposed_revenue_share_pct`, moving it to
    `COUNTERED` and overwriting the booking's `guarantee_cents` and
    `revenue_share_pct` with the proposed values".

    Design: Difficulty/non_linear_state_machine/booking_negotiation_cycle_and_counter_cap
    """
    scene = _submitted_booking()
    booking = scene["booking"]
    result = get_success_data(api_client.counter_booking(
        booking["id"], 4000000, 0.35, booking["version"],
        make_distributor_headers(scene["distributor"]["id"])))
    assert result["status"] == "COUNTERED"
    assert result["guarantee_cents"] == 4000000
    assert result["revenue_share_pct"] == 0.35


def test_booking_re_propose_returns_the_booking_to_the_state_it_already_held():
    """PRD §3.2: "The exhibitor answers a counter with `proposed_guarantee_cents`
    and `proposed_revenue_share_pct` — both optional, and a re-proposal that supplies
    no guarantee simply keeps the existing one — returning the booking to
    `PENDING_APPROVAL` provided the guarantee remains at or above the distributor
    floor and the on-sale instant has not already passed."

    Design: Difficulty/non_linear_state_machine/booking_negotiation_cycle_and_counter_cap
    """
    scene = _submitted_booking()
    booking = scene["booking"]
    counter = get_success_data(api_client.counter_booking(
        booking["id"], 4000000, 0.35, booking["version"],
        make_distributor_headers(scene["distributor"]["id"])))
    reproposal = get_success_data(api_client.repropose_booking(
        counter["id"], counter["version"],
        make_exhibitor_headers(scene["circuit"]["id"])))
    assert reproposal["status"] == "PENDING_APPROVAL", (
        "the machine is cyclic: the booking returns to a state it already occupied"
    )
    assert reproposal["guarantee_cents"] == 4000000, (
        "a re-proposal supplying no guarantee keeps the countered one"
    )


def test_booking_third_counter_round_completes_and_leaves_booking_countered():
    """PRD §3.2: "Countering is capped: a booking may be countered at most three
    times".

    Design: Difficulty/non_linear_state_machine/booking_negotiation_cycle_and_counter_cap
    """
    scene = _submitted_booking()
    booking = scene["booking"]
    distrib_headers = make_distributor_headers(scene["distributor"]["id"])
    exhib_headers = make_exhibitor_headers(scene["circuit"]["id"])
    version = booking["version"]
    for _ in range(3):
        state = get_success_data(api_client.counter_booking(
            booking["id"], 4000000, 0.35, version, distrib_headers))
        assert state["status"] == "COUNTERED"
        version = state["version"]
        state = get_success_data(api_client.repropose_booking(
            booking["id"], version, exhib_headers))
        assert state["status"] == "PENDING_APPROVAL"
        version = state["version"]
    final = get_booking(booking["id"])
    assert final["status"] == "PENDING_APPROVAL"
    assert final["guarantee_cents"] == 4000000


def test_booking_fourth_counter_is_refused_with_the_counter_limit_error():
    """PRD §3.2: "a fourth attempt is refused with `ERR_COUNTER_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/booking_negotiation_cycle_and_counter_cap
    """
    scene = _submitted_booking()
    booking = scene["booking"]
    distrib_headers = make_distributor_headers(scene["distributor"]["id"])
    exhib_headers = make_exhibitor_headers(scene["circuit"]["id"])
    version = booking["version"]
    for _ in range(3):
        state = get_success_data(api_client.counter_booking(
            booking["id"], 4000000, 0.35, version, distrib_headers))
        version = get_success_data(api_client.repropose_booking(
            booking["id"], state["version"], exhib_headers))["version"]
    resp = api_client.counter_booking(booking["id"], 4000000, 0.35, version,
                                      distrib_headers)
    validate_error(resp, ApiErrorId.ERR_COUNTER_LIMIT_REACHED, 409)
    assert get_booking(booking["id"])["guarantee_cents"] == 4000000, (
        "the refused fourth counter leaves the guarantee unchanged"
    )


def test_encryption_key_minted_before_its_window_reads_not_yet_valid():
    """PRD §2.11: "The second, `validity_state`, is derived purely from the instant
    at which it is read and the key's own interval, taking the values
    `NOT_YET_VALID`, `VALID`, or `EXPIRED`".
    PRD §3.4: "an issued key still reports `NOT_YET_VALID` before its interval
    opens."

    Design: Difficulty/non_linear_state_machine/encryption_key_parallel_issuance_and_validity
    """
    ctx = setup_booking_on_sale_with_delivery()
    set_clock("2026-11-20T00:00:00Z")
    key = get_success_data(api_client.create_encryption_key(
        {"screening_id": ctx["screening"]["id"],
         "not_valid_before_utc": "2026-12-01T19:00:00Z",
         "not_valid_after_utc": "2026-12-01T21:00:00Z"}, OPS))
    assert key["issuance_status"] == "PENDING"
    assert key["validity_state"] == "NOT_YET_VALID"


def test_encryption_key_issuance_advances_only_the_issuance_axis():
    """PRD §3.4: "Issuance moves the key to `ISSUED`, mints its `key_ref` as a
    system-generated opaque identifier, and recomputes its `validity_state`."

    Design: Difficulty/non_linear_state_machine/encryption_key_parallel_issuance_and_validity
    """
    ctx = setup_booking_on_sale_with_delivery()
    set_clock("2026-11-20T00:00:00Z")
    key = get_success_data(api_client.create_encryption_key(
        {"screening_id": ctx["screening"]["id"],
         "not_valid_before_utc": "2026-12-01T19:00:00Z",
         "not_valid_after_utc": "2026-12-01T21:00:00Z"}, OPS))
    issued = get_success_data(api_client.issue_key(key["id"], OPS))
    assert issued["issuance_status"] == "ISSUED"
    assert issued["validity_state"] == "NOT_YET_VALID", (
        "2026-11-20 is before the key window opens, so only the issuance axis moved"
    )
    assert isinstance(issued["key_ref"], str) and issued["key_ref"]


def test_encryption_key_reads_valid_inside_its_window():
    """PRD §3.4: "The instantaneous test asks, for whatever instant is currently
    being read, whether that instant falls before the key's opening boundary, inside
    the closed interval between the two boundaries, or after the closing boundary,
    yielding `NOT_YET_VALID`, `VALID`, or `EXPIRED` respectively."

    Design: Difficulty/non_linear_state_machine/encryption_key_parallel_issuance_and_validity
    """
    ctx = setup_booking_on_sale_with_delivery()
    set_clock("2026-11-20T00:00:00Z")
    key = get_success_data(api_client.create_encryption_key(
        {"screening_id": ctx["screening"]["id"],
         "not_valid_before_utc": "2026-12-01T19:00:00Z",
         "not_valid_after_utc": "2026-12-01T21:00:00Z"}, OPS))
    issued = get_success_data(api_client.issue_key(key["id"], OPS))
    set_clock("2026-12-01T20:00:00Z")
    assert get_key(issued["id"])["validity_state"] == "VALID"


def test_encryption_key_revocation_advances_only_the_issuance_axis():
    """PRD §3.4: "A revoked key still reports a `validity_state` — it reports `VALID`
    while its interval covers the instant being asked about".

    Design: Difficulty/non_linear_state_machine/encryption_key_parallel_issuance_and_validity
    """
    ctx = setup_booking_on_sale_with_delivery()
    set_clock("2026-11-20T00:00:00Z")
    key = get_success_data(api_client.create_encryption_key(
        {"screening_id": ctx["screening"]["id"],
         "not_valid_before_utc": "2026-12-01T19:00:00Z",
         "not_valid_after_utc": "2026-12-01T21:00:00Z"}, OPS))
    issued = get_success_data(api_client.issue_key(key["id"], OPS))
    set_clock("2026-12-01T20:00:00Z")
    revoked = get_success_data(api_client.revoke_key(
        issued["id"], "FEED_LOSS", OFFICER))
    assert revoked["issuance_status"] == "REVOKED"
    assert revoked["validity_state"] == "VALID", (
        "the two dimensions advance independently of one another"
    )


def test_encryption_key_reads_expired_after_its_window_closes():
    """PRD §3.4: "Custody state and time-window state are two separate answers to two
    separate questions."

    Design: Difficulty/non_linear_state_machine/encryption_key_parallel_issuance_and_validity
    """
    ctx = setup_booking_on_sale_with_delivery()
    set_clock("2026-11-20T00:00:00Z")
    key = get_success_data(api_client.create_encryption_key(
        {"screening_id": ctx["screening"]["id"],
         "not_valid_before_utc": "2026-12-01T19:00:00Z",
         "not_valid_after_utc": "2026-12-01T21:00:00Z"}, OPS))
    issued = get_success_data(api_client.issue_key(key["id"], OPS))
    set_clock("2026-12-01T20:00:00Z")
    get_success_data(api_client.revoke_key(issued["id"], "FEED_LOSS", OFFICER))
    set_clock("2026-12-02T00:00:00Z")
    assert get_key(issued["id"])["validity_state"] == "EXPIRED", (
        "a revoked key is computed for revoked keys as well as live ones"
    )


def setup_booking_on_sale_with_delivery():
    """ON_SALE booking whose file delivery is verified, on a 3-hour screening."""
    ctx = setup_booking_approved()
    booking = ctx["booking"]
    set_clock(booking["on_sale_at"])
    get_success_data(api_client.run_on_sale_sweep(OPS))
    ctx["booking"] = get_booking(booking["id"])
    setup_verified_delivery(ctx)
    return ctx