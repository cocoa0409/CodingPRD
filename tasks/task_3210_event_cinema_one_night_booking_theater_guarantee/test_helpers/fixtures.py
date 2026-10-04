"""Composite setup helpers (multi-API-call preconditions).

Every fixture builds state from scratch through PRD-declared endpoints; the
server is restarted before every test so nothing carries over between tests.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_distributor_payload, create_circuit_payload, create_theater_payload,
    create_title_payload, create_booking_payload, create_booking_line_payload,
    create_content_delivery_payload, create_encryption_key_payload,
    create_feed_event_payload, create_encore_window_payload, create_screening_payload,
    create_settlement_payload, showtime_plan_element,
)
from .test_users import (
    TEST_USERS, make_distributor_headers, make_exhibitor_headers,
    make_theater_headers,
)

OPS = "platform_ops_headers"
PROG = "programming_manager_headers"
FIN = "finance_ops_headers"
OFFICER = "content_officer_headers"

_code_counter = itertools.count(9000)


def unique_circuit_code(prefix="T"):
    return f"{prefix}{next(_code_counter)}"


# --- Primitive creators ------------------------------------------------------

def set_clock(to_iso8601="2026-09-01T00:00:00Z"):
    return get_success_data(api_client.set_clock(to_iso8601, TEST_USERS[OPS]))


def create_distributor(**overrides):
    payload = create_distributor_payload(**overrides)
    return get_success_data(api_client.create_distributor(payload, TEST_USERS[OPS]))


def create_circuit(accredit=True, **overrides):
    overrides.setdefault("circuit_code", unique_circuit_code())
    payload = create_circuit_payload(**overrides)
    circuit = get_success_data(api_client.create_circuit(payload, TEST_USERS[OPS]))
    if accredit:
        circuit = get_success_data(
            api_client.accredit_circuit(circuit["id"], TEST_USERS[OPS]))
    return circuit


def create_theater(circuit_id, **overrides):
    payload = create_theater_payload(circuit_id, **overrides)
    return get_success_data(api_client.create_theater(
        payload, make_exhibitor_headers(circuit_id)))


def create_title(distributor_id, publish=True, **overrides):
    payload = create_title_payload(distributor_id, **overrides)
    title = get_success_data(api_client.create_title(payload, TEST_USERS[PROG]))
    if publish:
        title = get_success_data(
            api_client.publish_title(title["id"], TEST_USERS[PROG]))
    return title


def create_booking(title_id, circuit_id, **overrides):
    payload = create_booking_payload(title_id, circuit_id, **overrides)
    return get_success_data(api_client.create_booking(
        payload, make_exhibitor_headers(circuit_id)))


def current_booking_version(booking_id):
    """Re-read the booking's current `version`.

    PRD §2.5/§2.6: every booking mutation advances the booking's `version`, so a
    client must attest the version it last observed. These lifecycle helpers are
    "a client" too: the `version` argument callers pass in is only a hint, and the
    helper always attests the freshest observed booking version so an intermediate
    mutation inside a fixture cannot invalidate the next step with
    `ERR_STALE_VERSION`. Tests that need to exercise a genuinely stale attestation
    call `api_client` directly with a pinned version.
    """
    return get_success_data(
        api_client.get_booking(booking_id, TEST_USERS[OPS]))["version"]


def add_line(booking_id, circuit_id, theater_id, version=None, **overrides):
    payload = create_booking_line_payload(
        theater_id, current_booking_version(booking_id), **overrides)
    return get_success_data(api_client.add_booking_line(
        booking_id, payload, make_exhibitor_headers(circuit_id)))


def submit_booking(booking_id, circuit_id, version=None):
    return get_success_data(api_client.submit_booking(
        booking_id, current_booking_version(booking_id),
        make_exhibitor_headers(circuit_id)))


def approve_booking(booking_id, distributor_id, version=None, line_id=None):
    return get_success_data(api_client.approve_booking(
        booking_id, current_booking_version(booking_id),
        make_distributor_headers(distributor_id), line_id))


def confirm_booking(booking_id, version=None):
    return get_success_data(api_client.confirm_booking(
        booking_id, current_booking_version(booking_id), TEST_USERS[OPS]))


def run_on_sale_sweep():
    return get_success_data(api_client.run_on_sale_sweep(TEST_USERS[OPS]))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, TEST_USERS[OPS]))


def get_circuit(circuit_id):
    return get_success_data(api_client.get_circuit(circuit_id, TEST_USERS[OPS]))


def get_theater(theater_id):
    return get_success_data(api_client.get_theater(theater_id, TEST_USERS[OPS]))


def get_line(line_id):
    return get_success_data(api_client.get_booking_line(line_id, TEST_USERS[OPS]))


def get_title(title_id):
    return get_success_data(api_client.get_title(title_id, TEST_USERS[OPS]))


def get_distributor(distributor_id):
    return get_success_data(
        api_client.get_distributor(distributor_id, TEST_USERS[OPS]))


def get_encore_window(window_id):
    return get_success_data(
        api_client.get_encore_window(window_id, TEST_USERS[OPS]))


def get_settlement(settlement_id):
    return get_success_data(
        api_client.get_settlement(settlement_id, TEST_USERS[OPS]))


def get_key(key_id):
    return get_success_data(api_client.get_encryption_key(key_id, TEST_USERS[OPS]))


def list_screenings(booking_id, limit=10, offset=0):
    data, _meta = (lambda r: (r["data"], r["meta"]))(
        api_client.list_screenings(TEST_USERS[OPS],
                                   {"booking_id": booking_id,
                                    "limit": limit, "offset": offset}).json())
    return data


def first_screening(booking_id):
    rows = list_screenings(booking_id)
    assert rows, f"expected at least one screening on booking {booking_id}"
    return rows[0]


# --- Tier 2/3: the standard catalogue fixture and its lifecycle shortcuts -----

def setup_circuit_venue_title(dist_overrides=None, circ_overrides=None,
                              theater_overrides=None, title_overrides=None,
                              accredit=True, publish=True):
    """Distributor + accredited circuit + one CA venue + published title.

    The common four-record prelude every booking fixture builds on.
    """
    distributor = create_distributor(**(dist_overrides or {}))
    circuit = create_circuit(accredit=accredit, **(circ_overrides or {}))
    theater = create_theater(circuit["id"], **(theater_overrides or {}))
    title = create_title(distributor["id"], publish=publish,
                         **(title_overrides or {}))
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title,
            "distributor_headers": make_distributor_headers(distributor["id"]),
            "exhibitor_headers": make_exhibitor_headers(circuit["id"]),
            "theater_headers": make_theater_headers(theater["id"])}


def setup_booking_approved(ctx=None, screens=60, expected_attendance=100,
                           guarantee_cents=None, revenue_share_pct=None,
                           booking_overrides=None, line_overrides=None,
                           release_screens=False):
    """Full prelude + booking driven DRAFT -> PENDING_APPROVAL -> APPROVED.

    Returns the ctx dict enriched with booking / line / screening records.

    `release_screens=True` drives the approval one step further through the
    compensating release of §3.2, leaving the booking `APPROVED` with its line
    `RELEASED` and its screenings `SKIPPED_CANCELLED`. That is the only state in
    which a cascade fixture can legitimately revoke a key, because PRD §3.4 only
    lets a key in `PENDING` be revoked automatically.
    """
    c = setup_circuit_venue_title(**(ctx or {}))
    booking_overrides = dict(booking_overrides or {})
    if guarantee_cents is not None:
        booking_overrides["guarantee_cents"] = guarantee_cents
    if revenue_share_pct is not None:
        booking_overrides["revenue_share_pct"] = revenue_share_pct
    booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                            **booking_overrides)
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=screens,
                    expected_attendance=expected_attendance,
                    **(line_overrides or {}))
    booking = get_booking(booking["id"])
    booking = submit_booking(booking["id"], c["circuit"]["id"], booking["version"])
    booking = approve_booking(booking["id"], c["distributor"]["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    screening = first_screening(booking["id"])
    if release_screens:
        # §3.4: a key in `PENDING` whose screening enters `SKIPPED_CANCELLED` is
        # revoked automatically with reason `CONTENT_FAILURE`. The package must be
        # registered before the release so the key can be minted and verified first.
        package = get_success_data(api_client.create_content_delivery(
            create_content_delivery_payload(
                booking["id"], booking["version"], delivery_method="BOTH"),
            TEST_USERS[OPS]))
        package = get_success_data(api_client.mark_delivery_delivered(
            package["id"], package["content_checksum"], TEST_USERS[OPS]))
        package = get_success_data(api_client.verify_delivery(
            package["id"], TEST_USERS[OPS]))
        key = get_success_data(api_client.create_encryption_key(
            create_encryption_key_payload(
                screening["id"], not_valid_before_utc="2026-12-01T19:00:00Z",
                not_valid_after_utc="2026-12-01T21:00:00Z"), TEST_USERS[OPS]))
        get_success_data(api_client.release_screens(
            booking["id"], line["id"], current_booking_version(booking["id"]),
            make_distributor_headers(c["distributor"]["id"])))
        booking = get_booking(booking["id"])
        line = get_line(line["id"])
        screening = first_screening(booking["id"])
        c.update({"delivery": package, "key": key})
    c.update({"booking": booking, "line": line, "screening": screening})
    return c


def setup_booking_on_sale(ctx=None, **kwargs):
    """Approved booking advanced to ON_SALE by the on-sale sweep."""
    c = setup_booking_approved(ctx=ctx, **kwargs)
    booking = c["booking"]
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(booking["id"])
    assert booking["status"] == "ON_SALE", (
        f"Setup failed: expected ON_SALE, got {booking['status']}")
    c["booking"] = booking
    return c


def setup_booking_confirmed(ctx=None, **kwargs):
    """Approved booking driven through ON_SALE to CONFIRMED."""
    c = setup_booking_on_sale(ctx=ctx, **kwargs)
    booking = confirm_booking(c["booking"]["id"], c["booking"]["version"])
    c["booking"] = booking
    return c


def setup_verified_delivery(ctx, method="FILE", checksum="sha256:aa11bb22",
                            scheduled_delivery_utc="2026-11-25T00:00:00Z",
                            verify=True):
    """Register a content package on the ctx booking, deliver it, verify it."""
    booking = ctx["booking"]
    delivery = get_success_data(api_client.create_content_delivery(
        create_content_delivery_payload(booking["id"], booking["version"],
                                       delivery_method=method,
                                       content_checksum=checksum,
                                       scheduled_delivery_utc=scheduled_delivery_utc),
        TEST_USERS[OPS]))
    delivery = get_success_data(api_client.mark_delivery_delivered(
        delivery["id"], checksum, TEST_USERS[OPS]))
    if verify:
        delivery = get_success_data(
            api_client.verify_delivery(delivery["id"], TEST_USERS[OPS]))
    ctx["delivery"] = delivery
    ctx["booking"] = get_booking(booking["id"])
    return ctx


def setup_issued_key(ctx, not_valid_before_utc="2026-12-01T19:00:00Z",
                     not_valid_after_utc="2026-12-01T21:00:00Z", issue=True):
    """Mint a key on the ctx screening and (optionally) issue it.

    Requires the booking's content package to be VERIFIED and the booking to be
    in a key-issuable status.
    """
    screening = ctx["screening"]
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(
            screening["id"], not_valid_before_utc=not_valid_before_utc,
            not_valid_after_utc=not_valid_after_utc),
        TEST_USERS[OPS]))
    if issue:
        key = get_success_data(api_client.issue_key(key["id"], TEST_USERS[OPS]))
    ctx["key"] = key
    return ctx


def setup_booking_with_issued_key(method="BOTH",
                                  scheduled_delivery_utc="2026-11-25T00:00:00Z",
                                  key_before="2026-12-01T19:00:00Z",
                                  key_after="2026-12-01T21:00:00Z", **kwargs):
    """APPROVED booking + verified delivery + a `PENDING` key on its screening.

    The booking is deliberately left `APPROVED` with its line `COMMITTED` and its
    screening `SCHEDULED`: the cascades these tests drive (title withdrawal, venue
    going dark) are only declared from the pre-`ON_SALE` states, and PRD §3.4
    revokes keys automatically only while they are `PENDING`, so the key must not
    be issued. The default key interval matches the synthesized screening window
    (19:00 to 21:00 UTC for the default showtime plan), which is what keeps
    `key_window_alignment` true; a deliberately narrower key is exercised by the
    alignment tests in test_13.
    """
    ctx = setup_booking_approved(**kwargs)
    setup_verified_delivery(ctx, method=method,
                            scheduled_delivery_utc=scheduled_delivery_utc)
    setup_issued_key(ctx, not_valid_before_utc=key_before,
                     not_valid_after_utc=key_after, issue=False)
    return ctx


def file_verified_feed_event(ctx, outage_minutes=20, failure_type="FEED_LOSS",
                             detected_at_utc="2026-12-01T19:05:00Z",
                             confirm=True):
    """File a feed event on the ctx booking and (optionally) confirm it.

    Filing and confirmation use two different platform operators, because PRD
    §2.12 forbids one operator from performing both legs of the confirmation.
    """
    event = get_success_data(api_client.create_feed_event(
        create_feed_event_payload(ctx["booking"]["id"],
                                  failure_type=failure_type,
                                  detected_at_utc=detected_at_utc,
                                  outage_minutes=outage_minutes),
        TEST_USERS[OPS]))
    if confirm:
        event = get_success_data(
            api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"]))
    ctx["feed_event"] = event
    return ctx


def report_screening(screening_id, theater_id, attendance, outcome,
                     at_instant="2026-12-01T21:30:00Z"):
    """Advance the clock past the screening and file the venue's report."""
    set_clock(at_instant)
    return get_success_data(api_client.report_screening(
        screening_id, attendance, outcome, make_theater_headers(theater_id)))


def setup_reported_booking(attendance=175, outcome="SCREENED",
                           at_instant="2026-12-01T21:30:00Z", **kwargs):
    """Confirmed booking whose single screening has been reported."""
    ctx = setup_booking_confirmed(**kwargs)
    ctx["screening"] = report_screening(ctx["screening"]["id"],
                                        ctx["theater"]["id"], attendance,
                                        outcome, at_instant)
    ctx["line"] = get_line(ctx["line"]["id"])
    ctx["booking"] = get_booking(ctx["booking"]["id"])
    return ctx


def setup_settled_booking(gross_box_office_cents=3000000, reported_line_count=1,
                          topup_paid_cents=0, adjustment_cents=0,
                          attendance=175, **kwargs):
    """Confirmed + reported booking, then a settlement created for it."""
    ctx = setup_reported_booking(attendance=attendance, **kwargs)
    settlement = get_success_data(api_client.create_settlement(
        create_settlement_payload(
            ctx["booking"]["id"],
            gross_box_office_cents=gross_box_office_cents,
            reported_line_count=reported_line_count,
            topup_paid_cents=topup_paid_cents,
            adjustment_cents=adjustment_cents),
        TEST_USERS[FIN]))
    ctx["settlement"] = settlement
    ctx["booking"] = get_booking(ctx["booking"]["id"])
    return ctx


def setup_encore_eligible_booking(attendance=175, expected_attendance=100,
                                  **kwargs):
    """Confirmed booking whose committed line reached the encore ratio floor."""
    ctx = setup_reported_booking(attendance=attendance,
                                 expected_attendance=expected_attendance, **kwargs)
    return ctx


# --- Tier 4: multi-entity scenes that several claims share -------------------

def setup_multi_venue_booking(venue_specs, guarantee_cents=100,
                              approve_all=True, **ctx_kwargs):
    """A booking with one line per venue, optionally approving every line.

    `venue_specs` is a list of dicts carrying the per-line overrides
    (committed_screens, expected_attendance, and any venue overrides under
    "theater"). Returns the ctx plus "lines" and "theaters" in proposal order.
    """
    c = setup_circuit_venue_title(**(ctx_kwargs or {}))
    theaters = []
    for spec in venue_specs:
        theater_overrides = spec.pop("theater", {}) if "theater" in spec else {}
        theaters.append(create_theater(c["circuit"]["id"], **theater_overrides))
    booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                            guarantee_cents=guarantee_cents)
    lines = []
    for theater, spec in zip(theaters, venue_specs):
        spec = {k: v for k, v in spec.items() if k != "theater"}
        line = add_line(booking["id"], c["circuit"]["id"], theater["id"],
                        booking["version"], **spec)
        booking = get_booking(booking["id"])
        lines.append(line)
    booking = submit_booking(booking["id"], c["circuit"]["id"], booking["version"])
    if approve_all:
        for line in lines:
            approve = approve_booking(booking["id"], c["distributor"]["id"],
                                      booking["version"], line["id"])
            line = get_line(line["id"])
            booking = get_booking(booking["id"])
            booking = get_booking(booking["id"])
    c.update({"booking": booking, "lines": lines, "theaters": theaters})
    return c


def setup_two_circuit_settlement_scene(net_terms="NET_30",
                                       gross_terms="GROSS_ON_GROSS",
                                       guarantee_cents=1000000,
                                       revenue_share_pct=0.40,
                                       attendance=175, gross_box_office_cents=3000000):
    """Two circuits, one booking each, both reported and ready to settle.

    The venue commitment, title and screening plan are identical; only the
    settlement terms of the two circuits differ.
    """
    distributor = create_distributor()
    title = create_title(distributor["id"])
    result = {"distributor": distributor, "title": title, "sides": []}
    plan = None
    on_sale_at = None
    built = []
    for label, terms in (("allocation_order", net_terms), ("net_off_top", gross_terms)):
        circuit = create_circuit(settlement_terms=terms, screen_pool_total=600)
        theater = create_theater(circuit["id"], theater_name=f"{label} venue",
                                 city="Burbank", state_code="CA", seats_total=200)
        booking_kwargs = {"guarantee_cents": guarantee_cents,
                          "revenue_share_pct": revenue_share_pct}
        if plan is not None:
            # PRD §3.1 requires every showtime date to fall at or after the clock
            # instant when the plan is validated, so the second booking cannot
            # reuse a plan whose dates are already in the past. Side 1's plan is
            # still in the future, so replaying it keeps both sides identical.
            booking_kwargs["showtime_plan"] = plan
        booking = create_booking(title["id"], circuit["id"], **booking_kwargs)
        if plan is None:
            plan = booking["showtime_plan"]
            on_sale_at = booking["on_sale_at"]
        line = add_line(booking["id"], circuit["id"], theater["id"],
                        booking["version"], committed_screens=30,
                        expected_attendance=100)
        booking = submit_booking(booking["id"], circuit["id"],
                                 get_booking(booking["id"])["version"])
        booking = approve_booking(booking["id"], distributor["id"],
                                  booking["version"], line["id"])
        line = get_line(line["id"])
        booking = get_booking(booking["id"])
        built.append({"label": label, "terms": terms, "circuit": circuit,
                      "theater": theater, "booking": booking, "line": line})
    # Both bookings must be ON_SALE before either is reported: PRD §3.3 requires
    # `on_sale_at` to be at or after the clock instant when a booking is
    # submitted, so the clock may only be advanced once every booking exists.
    # Both bookings now share one on-sale instant because side 2 replays side 1's
    # showtime plan.
    assert all(side["booking"]["on_sale_at"] == on_sale_at for side in built), (
        "both settlement sides must arm their on-sale checkpoint at the same instant")
    set_clock(on_sale_at)
    run_on_sale_sweep()
    for side in built:
        label, terms = side["label"], side["terms"]
        circuit, theater, line = side["circuit"], side["theater"], side["line"]
        booking = get_booking(side["booking"]["id"])
        booking = confirm_booking(booking["id"], booking["version"])
        screening = first_screening(booking["id"])
        screening = report_screening(screening["id"], theater["id"], attendance,
                                     "SCREENED")
        booking = get_booking(booking["id"])
        line = get_line(line["id"])
        booking = get_booking(booking["id"])
        settlement = get_success_data(api_client.create_settlement(
            create_settlement_payload(
                booking["id"], gross_box_office_cents=gross_box_office_cents),
            TEST_USERS[FIN]))
        result["sides"].append({
            "label": label, "terms": terms, "circuit": circuit, "theater": theater,
            "booking": booking, "line": line, "screening": screening,
            "settlement": settlement,
        })
    return result


def setup_screen_pool_scene(pool_total, first_screens, second_screens,
                            title_max=120, **ctx_kwargs):
    """A circuit whose pool is too small for both bookings' commitments.

    Booking A is approved with `first_screens`; booking B is left in
    PENDING_APPROVAL carrying `second_screens`, ready for the approval under
    test.
    """
    c = setup_circuit_venue_title(circ_overrides={"screen_pool_total": pool_total},
                                 title_overrides={"max_screen_commitment": title_max},
                                 **(ctx_kwargs or {}))
    first = create_booking(c["title"]["id"], c["circuit"]["id"])
    first_line = add_line(first["id"], c["circuit"]["id"], c["theater"]["id"],
                          first["version"], committed_screens=first_screens,
                          expected_attendance=100)
    first = submit_booking(first["id"], c["circuit"]["id"],
                           get_booking(first["id"])["version"])
    first = approve_booking(first["id"], c["distributor"]["id"],
                            first["version"], first_line["id"])
    first_line = get_line(first_line["id"])
    second = create_booking(c["title"]["id"], c["circuit"]["id"],
                            showtime_plan=[showtime_plan_element(
                                date_utc="2026-12-02T00:00:00Z",
                                auditorium="AUD-2")])
    second_line = add_line(second["id"], c["circuit"]["id"], c["theater"]["id"],
                           second["version"], committed_screens=second_screens,
                           expected_attendance=40)
    second = submit_booking(second["id"], c["circuit"]["id"],
                           get_booking(second["id"])["version"])
    c.update({"first_booking": first, "first_line": first_line,
              "second_booking": second, "second_line": second_line})
    return c


def setup_presale_boundary_scene(exact_tickets, short_tickets, threshold=5000,
                                 **ctx_kwargs):
    """Two ON_SALE bookings on one circuit, one clearing the presale gate.

    Booking A records exactly `exact_tickets`; booking B records
    `short_tickets`. Both carry `threshold` as their pre-sale threshold and
    share the same on-sale instant, so a single clock advance arms both
    checkpoints.
    """
    c = setup_circuit_venue_title(**(ctx_kwargs or {}))
    bookings = []
    for index, (label, tickets, auditorium) in enumerate((
            ("exact", exact_tickets, "AUD-1"), ("short", short_tickets, "AUD-2"))):
        booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                                pre_sale_threshold=threshold,
                                showtime_plan=[showtime_plan_element(
                                    index=1, date_utc="2026-12-01T00:00:00Z",
                                    start_minute_utc=1140 + 240 * index,
                                    auditorium=auditorium)])
        line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                        booking["version"], committed_screens=60,
                        expected_attendance=100)
        booking = submit_booking(booking["id"], c["circuit"]["id"],
                                get_booking(booking["id"])["version"])
        booking = approve_booking(booking["id"], c["distributor"]["id"],
                                  booking["version"], line["id"])
        line = get_line(line["id"])
        booking = get_booking(booking["id"])
        bookings.append({"label": label, "booking": booking, "line": line,
                         "tickets": tickets})
    set_clock(bookings[0]["booking"]["on_sale_at"])
    run_on_sale_sweep()
    for entry in bookings:
        get_success_data(api_client.record_presale_sales(
            entry["booking"]["id"], entry["tickets"],
            make_theater_headers(c["theater"]["id"])))
        entry["booking"] = get_booking(entry["booking"]["id"])
    c.update({"entries": bookings, "exact": bookings[0], "short": bookings[1]})
    return c


def create_direct_screening(booking_id, theater_id, auditorium, starts_at, ends_at):
    """Attach an encore screening directly through the screening endpoint."""
    return get_success_data(api_client.create_screening(
        create_screening_payload(booking_id, theater_id, auditorium=auditorium,
                                 starts_at=starts_at, ends_at=ends_at),
        TEST_USERS[OPS]))