"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls go
through `get_success_data()` so a broken precondition surfaces as a setup
failure rather than as a confusing assertion.

The helpers thread a single mutable `ctx` dictionary:

    ctx["origin"], ctx["destination"]  -- terminal rows, always the latest read
    ctx["grades"]                      -- {grade_code: product grade row}
    ctx["segment"]                     -- the pipeline segment row
    ctx["shippers"]                    -- {shipper_code: shipper row}
    ctx["tariffs"]                     -- {grade_code: tariff row}
    ctx["cycle"]                       -- the nomination cycle row
    ctx["nominations"]                 -- {shipper_code+grade_code: nomination row}
    ctx["tickets"]                     -- batch tickets in sequence order
    ctx["settlements"]                 -- settlement rows in listing order
    ctx["events"]                      -- maintenance event rows
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, PUBLISHER_USER_ID, TEST_DEFAULTS
from .factories import (
    cbob_grade_payload,
    create_cycle_payload,
    create_inventory_adjustment_payload,
    create_maintenance_event_payload,
    create_nomination_payload,
    create_segment_payload,
    create_shipper_payload,
    create_shipping_history_payload,
    create_tariff_payload,
    deliver_payload,
    destination_terminal_payload,
    inject_payload,
    jet_grade_payload,
    linefill_adjustment_payload,
    origin_terminal_payload,
    proration_policy_payload,
    settle_payload,
    suspend_shipper_payload,
    transmix_grade_payload,
    ulsd_grade_payload,
)
from .test_users import (
    ADMIN,
    OPERATOR,
    PUBLISHER,
    SCHEDULER,
    make_scheduler_headers,
    make_shipper_headers,
)

GRADE_PAYLOADS = {
    "ULSD": ulsd_grade_payload,
    "CBOB": cbob_grade_payload,
    "JET": jet_grade_payload,
    "TRANSMIX": transmix_grade_payload,
}

SHIPPER_SPECS = {
    "ALPHA": {"shipper_code": "ALPHA", "name": "Alpha Petroleum Marketing"},
    "BRAVO": {"shipper_code": "BRAVO", "name": "Bravo Fuels"},
    "CHARLIE": {"shipper_code": "CHARLIE", "name": "Charlie Energy"},
}


# --------------------------------------------------------------- logical clock


def set_clock(instant, headers=None):
    """Move the logical clock. Available to all four roles; mutates no entity."""
    return get_success_data(api_client.set_current_utc(instant, headers or SCHEDULER))


def reset_clock():
    """Return the logical clock to the instant it reads before any call."""
    return set_clock(CLOCK_EPOCH)


# ------------------------------------------------------- Tier 1: the network


def setup_network(
    *,
    clock=CLOCK_EPOCH,
    origin_overrides=None,
    destination_overrides=None,
    segment_overrides=None,
    grades=("ULSD",),
    linefill_grade="ULSD",
    linefill_bbl=TEST_DEFAULTS["LINEFILL_FUNDING_BBL"],
    origin_stock_bbl=None,
):
    """Stand up the physical network: two terminals, the product grades, the
    segment, and optionally its linefill and the origin tank's opening stock.

    Returns the shared `ctx` dictionary every later helper threads.
    """
    set_clock(clock, ADMIN)

    origin = get_success_data(
        api_client.create_terminal(
            origin_terminal_payload(**(origin_overrides or {})), ADMIN
        )
    )
    destination = get_success_data(
        api_client.create_terminal(
            destination_terminal_payload(**(destination_overrides or {})), ADMIN
        )
    )

    grade_rows = {}
    for code in grades:
        grade_rows[code] = get_success_data(
            api_client.create_product_grade(GRADE_PAYLOADS[code](), ADMIN)
        )

    linefill_code = linefill_grade if linefill_grade in grade_rows else list(grade_rows)[0]
    segment = get_success_data(
        api_client.create_segment(
            create_segment_payload(
                origin["id"],
                destination["id"],
                grade_rows[linefill_code]["id"],
                **(segment_overrides or {}),
            ),
            ADMIN,
        )
    )

    ctx = {
        "origin": origin,
        "destination": destination,
        "grades": grade_rows,
        "segment": segment,
        "shippers": {},
        "tariffs": {},
        "cycle": None,
        "nominations": {},
        "tickets": [],
        "settlements": [],
        "events": [],
    }

    if linefill_bbl:
        fund_linefill(ctx, linefill_bbl)
    if origin_stock_bbl:
        adjust_inventory(ctx, origin_stock_bbl)

    return ctx


def fund_linefill(ctx, adjustment_bbl, reason="initial linefill"):
    """Fund the segment's linefill through a LINEFILL inventory adjustment."""
    ctx["origin"] = get_success_data(
        api_client.create_inventory_adjustment(
            ctx["origin"]["id"],
            linefill_adjustment_payload(
                ctx["origin"]["version"],
                ctx["segment"]["id"],
                adjustment_bbl=adjustment_bbl,
                reason=reason,
            ),
            OPERATOR,
        )
    )
    refresh_segment(ctx)
    return ctx["origin"]


def adjust_inventory(ctx, adjustment_bbl, reason="refinery receipt", terminal=None):
    """Book an INVENTORY adjustment against the origin tank by default."""
    key = terminal or "origin"
    ctx[key] = get_success_data(
        api_client.create_inventory_adjustment(
            ctx[key]["id"],
            create_inventory_adjustment_payload(
                ctx[key]["version"],
                adjustment_kind="INVENTORY",
                adjustment_bbl=adjustment_bbl,
                reason=reason,
                segment_id=ctx["segment"]["id"],
            ),
            OPERATOR,
        )
    )
    return ctx[key]


def change_proration_policy(ctx, proration_policy):
    """File a new proration methodology on the segment."""
    ctx["segment"] = get_success_data(
        api_client.change_proration_policy(
            ctx["segment"]["id"], proration_policy_payload(proration_policy), ADMIN
        )
    )
    return ctx["segment"]


# ----------------------------------------------------- Tier 1: refresh helpers


def refresh_origin(ctx):
    ctx["origin"] = get_success_data(
        api_client.get_terminal(ctx["origin"]["id"], SCHEDULER)
    )
    return ctx["origin"]


def refresh_destination(ctx):
    ctx["destination"] = get_success_data(
        api_client.get_terminal(ctx["destination"]["id"], SCHEDULER)
    )
    return ctx["destination"]


def refresh_segment(ctx):
    ctx["segment"] = get_success_data(
        api_client.get_segment(ctx["segment"]["id"], SCHEDULER)
    )
    return ctx["segment"]


def refresh_cycle(ctx):
    ctx["cycle"] = get_success_data(api_client.get_cycle(ctx["cycle"]["id"], SCHEDULER))
    return ctx["cycle"]


def refresh_shipper(ctx, shipper_code):
    ctx["shippers"][shipper_code] = get_success_data(
        api_client.get_shipper(ctx["shippers"][shipper_code]["id"], SCHEDULER)
    )
    return ctx["shippers"][shipper_code]


def refresh_nomination(ctx, key):
    ctx["nominations"][key] = get_success_data(
        api_client.get_nomination(ctx["nominations"][key]["id"], SCHEDULER)
    )
    return ctx["nominations"][key]


def refresh_tickets(ctx):
    """Re-read the cycle's batch tickets in sequence order."""
    body = api_client.list_batch_tickets(
        SCHEDULER, params={"cycle_id": ctx["cycle"]["id"], "limit": 100}
    ).json()
    ctx["tickets"] = body["data"]
    return ctx["tickets"]


def refresh_settlements(ctx):
    body = api_client.list_settlements(
        SCHEDULER, params={"cycle_id": ctx["cycle"]["id"], "limit": 100}
    ).json()
    ctx["settlements"] = body["data"]
    return ctx["settlements"]


# ---------------------------------------- Tier 2: shippers, history, tariffs


def add_shipper(ctx, shipper_code, **overrides):
    """Enrol one shipper. Defaults cover ALPHA, BRAVO and CHARLIE."""
    spec = dict(SHIPPER_SPECS.get(shipper_code, {"shipper_code": shipper_code}))
    spec.setdefault("name", f"{shipper_code.title()} Marketing")
    spec.update(overrides)
    row = get_success_data(api_client.create_shipper(create_shipper_payload(**spec), ADMIN))
    ctx["shippers"][shipper_code] = row
    return row


def add_shippers(ctx, codes=("ALPHA",), **overrides):
    """Enrol several shippers in the order given -- creation order is load-bearing
    for the tie-breaks the PRD specifies on `created_at`."""
    return [add_shipper(ctx, code, **overrides) for code in codes]


def suspend_shipper(ctx, shipper_code, suspended_reason="credit review pending"):
    """Suspend a shipper, recording the reason."""
    ctx["shippers"][shipper_code] = get_success_data(
        api_client.suspend_shipper(
            ctx["shippers"][shipper_code]["id"],
            suspend_shipper_payload(suspended_reason=suspended_reason),
            ADMIN,
        )
    )
    return ctx["shippers"][shipper_code]


def add_history(
    ctx,
    shipper_code,
    actual_shipped_bbl,
    cycle_end_at,
    record_status="FINAL",
    cycle_code=None,
):
    """Record one immutable historical movement row for a shipper on the segment."""
    row = get_success_data(
        api_client.create_shipping_history(
            create_shipping_history_payload(
                ctx["shippers"][shipper_code]["id"],
                ctx["segment"]["id"],
                actual_shipped_bbl=actual_shipped_bbl,
                cycle_end_at=cycle_end_at,
                record_status=record_status,
                cycle_code=cycle_code or cycle_end_at[:7],
            ),
            ADMIN,
        )
    )
    ctx.setdefault("history", []).append(row)
    return row


def add_tariff(ctx, grade_code, activate=True, **overrides):
    """File a tariff for one grade on the segment, activating it by default."""
    row = get_success_data(
        api_client.create_tariff(
            create_tariff_payload(
                ctx["segment"]["id"], ctx["grades"][grade_code]["id"], **overrides
            ),
            ADMIN,
        )
    )
    if activate:
        row = get_success_data(api_client.activate_tariff(row["id"], ADMIN))
    ctx["tariffs"][grade_code] = row
    return row


def add_tariffs(ctx, grade_codes=("ULSD",), activate=True, **overrides):
    """File and activate one tariff per grade."""
    return [add_tariff(ctx, code, activate=activate, **overrides) for code in grade_codes]


# ------------------------------------------- Tier 2: cycles and nominations


def open_cycle(ctx, **overrides):
    """Open a nomination cycle on the segment."""
    ctx["cycle"] = get_success_data(
        api_client.create_cycle(
            create_cycle_payload(ctx["segment"]["id"], **overrides), SCHEDULER
        )
    )
    return ctx["cycle"]


def nominate(
    ctx,
    shipper_code,
    grade_code="ULSD",
    nominated_bbl=30000,
    expected_cycle_version=None,
    key=None,
    **overrides,
):
    """Submit a nomination, re-reading the cycle first so the OCC token is fresh.

    PRD 2.6: "A successful submission increments the cycle's `version` by one, so
    a client that submits twice must re-read the cycle between attempts."
    """
    if expected_cycle_version is None:
        refresh_cycle(ctx)
        expected_cycle_version = ctx["cycle"]["version"]
    shipper = ctx["shippers"][shipper_code]
    row = get_success_data(
        api_client.create_nomination(
            create_nomination_payload(
                ctx["cycle"]["id"],
                shipper["id"],
                ctx["grades"][grade_code]["id"],
                ctx["origin"]["id"],
                ctx["destination"]["id"],
                expected_cycle_version,
                nominated_bbl=nominated_bbl,
                **overrides,
            ),
            make_shipper_headers(shipper["id"]),
        )
    )
    ctx["nominations"][key or f"{shipper_code}:{grade_code}"] = row
    refresh_cycle(ctx)
    return row


def nomination_key(shipper_code, grade_code="ULSD"):
    return f"{shipper_code}:{grade_code}"


def close_cycle(ctx):
    """Close the nomination window: pin rates and size the line."""
    ctx["cycle"] = get_success_data(api_client.close_cycle(ctx["cycle"]["id"], SCHEDULER))
    return ctx["cycle"]


def prorate_cycle(ctx):
    """Prorate the cycle's nominations against effective capacity."""
    ctx["cycle"] = get_success_data(
        api_client.prorate_cycle(ctx["cycle"]["id"], SCHEDULER)
    )
    return ctx["cycle"]


def build_schedule(ctx):
    """Sequence the prorated nominations into batch tickets."""
    ctx["cycle"] = get_success_data(
        api_client.build_schedule(ctx["cycle"]["id"], SCHEDULER)
    )
    refresh_tickets(ctx)
    return ctx["cycle"]


def publish_schedule(ctx, publisher_user_id=PUBLISHER_USER_ID):
    """Publish the built schedule under a named operator identity, because the
    recorded publisher is what the duty-separation check later compares against."""
    ctx["cycle"] = get_success_data(
        api_client.publish_schedule(
            ctx["cycle"]["id"], make_scheduler_headers(publisher_user_id)
        )
    )
    refresh_tickets(ctx)
    return ctx["cycle"]


def settle_cycle(ctx, basis_mode="DELIVERED"):
    """Settle the cycle and read back the settlements it raised."""
    ctx["cycle"] = get_success_data(
        api_client.settle_cycle(ctx["cycle"]["id"], settle_payload(basis_mode), SCHEDULER)
    )
    refresh_settlements(ctx)
    return ctx["cycle"]


# ---------------------------------------- Tier 3: movement and maintenance


def inject_ticket(ctx, ticket_id, injected_bbl, measured_sulfur_ppm=9, measured_rvp_psi=8):
    """Inject a batch on-specification as a setup step."""
    row = get_success_data(
        api_client.inject_batch(
            ticket_id,
            inject_payload(injected_bbl, measured_sulfur_ppm, measured_rvp_psi),
            OPERATOR,
        )
    )
    refresh_tickets(ctx)
    return row


def deliver_ticket(ctx, ticket_id, delivered_bbl):
    """Deliver an injected batch as a setup step."""
    row = get_success_data(
        api_client.deliver_batch(ticket_id, deliver_payload(delivered_bbl), OPERATOR)
    )
    refresh_tickets(ctx)
    return row


def plan_maintenance(ctx, **overrides):
    """Plan maintenance work on the segment. A PLANNED event derates nothing yet."""
    row = get_success_data(
        api_client.create_maintenance_event(
            create_maintenance_event_payload(ctx["segment"]["id"], **overrides), SCHEDULER
        )
    )
    ctx["events"].append(row)
    return row


def notify_maintenance(ctx, event_id):
    """Issue the notice, which is what actually derates the line."""
    row = get_success_data(api_client.notify_maintenance_event(event_id, SCHEDULER))
    refresh_segment(ctx)
    if ctx.get("cycle"):
        refresh_cycle(ctx)
        refresh_tickets(ctx)
    return row


def ticket_for(ctx, nomination_id):
    """The batch ticket lifted from a given nomination, if one exists."""
    for ticket in ctx["tickets"]:
        if ticket["nomination_id"] == nomination_id:
            return ticket
    return None


def ticket_at(ctx, sequence_position):
    """The batch ticket at a given sequence position."""
    for ticket in ctx["tickets"]:
        if ticket["sequence_position"] == sequence_position:
            return ticket
    return None


# ------------------------------------ Tier 4: named composite starting states


def setup_open_cycle(
    *,
    shippers=("ALPHA",),
    grades=("ULSD",),
    tariff_grades=None,
    origin_stock_bbl=None,
    linefill_bbl=TEST_DEFAULTS["LINEFILL_FUNDING_BBL"],
    origin_overrides=None,
    destination_overrides=None,
    segment_overrides=None,
    cycle_overrides=None,
    shipper_overrides=None,
    tariff_overrides=None,
    clock=CLOCK_EPOCH,
):
    """Network + shippers + an active tariff per grade + one OPEN cycle.

    This is the shared preamble behind almost every nomination-time claim.
    """
    ctx = setup_network(
        clock=clock,
        grades=grades,
        linefill_bbl=linefill_bbl,
        origin_stock_bbl=origin_stock_bbl,
        origin_overrides=origin_overrides,
        destination_overrides=destination_overrides,
        segment_overrides=segment_overrides,
    )
    add_shippers(ctx, shippers, **(shipper_overrides or {}))
    add_tariffs(ctx, tariff_grades or grades, **(tariff_overrides or {}))
    open_cycle(ctx, **(cycle_overrides or {}))
    return ctx


def setup_cycle_with_nomination(nominated_bbl=30000, **kwargs):
    """One OPEN cycle carrying ALPHA's SUBMITTED nomination."""
    ctx = setup_open_cycle(**kwargs)
    nominate(ctx, "ALPHA", nominated_bbl=nominated_bbl)
    return ctx


def setup_closed_cycle(nominated_bbl=30000, **kwargs):
    """ALPHA's nomination pinned and ACCEPTED on a CLOSED cycle."""
    ctx = setup_cycle_with_nomination(nominated_bbl=nominated_bbl, **kwargs)
    close_cycle(ctx)
    refresh_nomination(ctx, nomination_key("ALPHA"))
    return ctx


def setup_prorated_cycle(nominated_bbl=30000, **kwargs):
    """ALPHA's nomination PRORATED on a PRORATED cycle."""
    ctx = setup_closed_cycle(nominated_bbl=nominated_bbl, **kwargs)
    prorate_cycle(ctx)
    refresh_nomination(ctx, nomination_key("ALPHA"))
    return ctx


def setup_scheduled_cycle(nominated_bbl=30000, **kwargs):
    """A built but unpublished schedule: cycle SCHEDULED, tickets PLANNED."""
    ctx = setup_prorated_cycle(nominated_bbl=nominated_bbl, **kwargs)
    build_schedule(ctx)
    refresh_nomination(ctx, nomination_key("ALPHA"))
    return ctx


def setup_published_cycle(
    nominated_bbl=30000,
    origin_stock_bbl=TEST_DEFAULTS["ORIGIN_STOCK_BBL"],
    publisher_user_id=PUBLISHER_USER_ID,
    **kwargs,
):
    """A PUBLISHED cycle with stock in the origin tank, ready for injection."""
    ctx = setup_scheduled_cycle(
        nominated_bbl=nominated_bbl, origin_stock_bbl=origin_stock_bbl, **kwargs
    )
    publish_schedule(ctx, publisher_user_id)
    refresh_nomination(ctx, nomination_key("ALPHA"))
    refresh_origin(ctx)
    return ctx


def setup_delivered_cycle(
    nominated_bbl=30000,
    injected_bbl=30000,
    delivered_bbl=29900,
    publisher_user_id=PUBLISHER_USER_ID,
    **kwargs,
):
    """ALPHA's single batch injected on-spec and delivered, so the cycle is
    settleable."""
    ctx = setup_published_cycle(
        nominated_bbl=nominated_bbl, publisher_user_id=publisher_user_id, **kwargs
    )
    ticket = ctx["tickets"][0]
    inject_ticket(ctx, ticket["id"], injected_bbl)
    deliver_ticket(ctx, ticket["id"], delivered_bbl)
    refresh_origin(ctx)
    refresh_destination(ctx)
    refresh_segment(ctx)
    return ctx


def setup_draft_settlement(basis_mode="DELIVERED", **kwargs):
    """One DRAFT settlement on a SETTLED cycle, published by `sched-publisher-1`."""
    ctx = setup_delivered_cycle(**kwargs)
    settle_cycle(ctx, basis_mode)
    return ctx


# ---------------------------- Tier 5: multi-shipper and history-driven states


def add_canonical_alpha_history(ctx, shipper_code="ALPHA"):
    """Two FINAL rows inside the one-year lookback, 30000 and 42000 barrels.

    Their mean is 36000.00, which is the history base the PRD's averaging rule
    produces: the sum divided by the number of qualifying records.
    """
    add_history(ctx, shipper_code, 30000, "2026-06-30T00:00:00Z")
    add_history(ctx, shipper_code, 42000, "2026-07-31T00:00:00Z")
    return ctx


def setup_multi_shipper_cycle(
    nominations,
    *,
    grades=("ULSD",),
    history=(),
    shippers=None,
    close=False,
    prorate=False,
    build=False,
    publish=False,
    origin_stock_bbl=None,
    publisher_user_id=PUBLISHER_USER_ID,
    **kwargs,
):
    """Drive an arbitrary multi-shipper cycle to a chosen lifecycle stage.

    `nominations` is a sequence of (shipper_code, grade_code, nominated_bbl)
    triples applied in order, because creation order breaks the PRD's ties on
    `created_at`. `history` is a sequence of
    (shipper_code, actual_shipped_bbl, cycle_end_at[, record_status]) tuples
    recorded before the cycle opens.
    """
    codes = shippers or []
    if not codes:
        for spec in nominations:
            if spec[0] not in codes:
                codes.append(spec[0])
    ctx = setup_open_cycle(
        shippers=tuple(codes),
        grades=grades,
        origin_stock_bbl=origin_stock_bbl,
        **kwargs,
    )
    for row in history:
        add_history(ctx, row[0], row[1], row[2], *(row[3:]))
    for shipper_code, grade_code, bbl in nominations:
        nominate(ctx, shipper_code, grade_code, nominated_bbl=bbl)
    if close or prorate or build or publish:
        close_cycle(ctx)
    if prorate or build or publish:
        prorate_cycle(ctx)
    if build or publish:
        build_schedule(ctx)
    if publish:
        publish_schedule(ctx, publisher_user_id)
    for key in list(ctx["nominations"]):
        refresh_nomination(ctx, key)
    refresh_cycle(ctx)
    refresh_segment(ctx)
    return ctx


def setup_history_weighted_pair(
    alpha_bbl=60000, bravo_bbl=60000, prorate=True, **kwargs
):
    """Two ULSD nominations on a HISTORY_WEIGHTED segment where only ALPHA has a
    shipping history, so the class split and the new-shipper reserve both bite."""
    return setup_multi_shipper_cycle(
        [("ALPHA", "ULSD", alpha_bbl), ("BRAVO", "ULSD", bravo_bbl)],
        history=[
            ("ALPHA", 30000, "2026-06-30T00:00:00Z"),
            ("ALPHA", 42000, "2026-07-31T00:00:00Z"),
        ],
        prorate=prorate,
        **kwargs,
    )


def setup_multi_grade_published_cycle(
    specs=(("ALPHA", "JET", 20000), ("BRAVO", "ULSD", 20000), ("CHARLIE", "CBOB", 20000)),
    *,
    grades=("JET", "ULSD", "CBOB"),
    linefill_grade="ULSD",
    origin_stock_bbl=TEST_DEFAULTS["ORIGIN_STOCK_BBL"],
    **kwargs,
):
    """Three grades in one cycle, which is what makes the interface transmix cuts
    observable across all three branches of the rank-gap rule."""
    ctx = setup_multi_shipper_cycle(
        list(specs),
        grades=grades,
        origin_stock_bbl=origin_stock_bbl,
        publish=True,
        **kwargs,
    )
    return ctx


def setup_two_bay_terminal_schedule(
    specs=(
        ("NOVA", "ULSD", 20000),
        ("ORION", "ULSD", 20000),
        ("PEGASUS", "ULSD", 20000),
    ),
    **kwargs,
):
    """Three PLANNED tickets in consecutive 24-hour slots at a two-bay origin
    terminal, which is the state the bay-occupancy arithmetic is read against."""
    return setup_multi_shipper_cycle(list(specs), build=True, **kwargs)
