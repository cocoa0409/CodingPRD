"""Composite setup helpers.

Multi-step scenarios used by the claim-driven tests: SPA + commercial-train
preparation, ADP lifecycle, vessel-call marine chains, proration schedules,
cancellation/resale economics, and turnaround cascades. Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_ACTUAL_INDEX_PRICE,
    DEFAULT_REFERENCE_INDEX_PRICE,
)
from .factories import (
    create_adp_payload,
    create_berth_payload,
    create_cargo_slot_payload,
    create_customer_payload,
    create_day_schedule_payload,
    create_nomination_payload,
    create_pipeline_payload,
    create_resale_payload,
    create_spa_payload,
    create_train_payload,
    create_turnaround_payload,
    create_vessel_nomination_payload,
    declare_cod_payload,
)
from .test_users import TEST_USERS, make_customer_rep_headers, make_operator_headers

OP = TEST_USERS["operator_headers"]
CM = TEST_USERS["commercial_headers"]
GS = TEST_USERS["gas_headers"]
MS = TEST_USERS["marine_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), OP)
    )


def create_commercial_train(commissioning_cargoes_required: int = 0, **overrides):
    """Create a train and walk it to COMMERCIAL_OPERATION (COD declared)."""
    train = get_success_data(
        api_client.create_train(
            create_train_payload(
                commissioning_cargoes_required=commissioning_cargoes_required, **overrides
            ),
            OP,
        )
    )
    get_success_data(api_client.begin_commissioning(train["id"], OP))
    for _ in range(commissioning_cargoes_required):
        get_success_data(
            api_client.record_commissioning_cargo(
                train["id"], {"proceeds_usd": 1000000}, OP
            )
        )
    train = get_success_data(
        api_client.declare_cod(train["id"], declare_cod_payload(), OP)
    )
    return train


def create_commenced_spa(customer_id: str, **overrides):
    """Create a commercial train, then an SPA, then commence deliveries.

    Returns the SPA dict in DELIVERIES_COMMENCED.
    """
    create_commercial_train()
    spa = get_success_data(
        api_client.create_spa(create_spa_payload(customer_id, **overrides), CM)
    )
    spa = get_success_data(api_client.commence_spa_deliveries(spa["id"], CM))
    return spa


def create_draft_adp(spa_id: str, expected_spa_version: int, **overrides):
    return get_success_data(
        api_client.create_adp(
            create_adp_payload(spa_id, expected_spa_version, **overrides), CM
        )
    )


def add_cargo_slot(adp_id: str, **overrides):
    return get_success_data(
        api_client.create_cargo_slot(adp_id, create_cargo_slot_payload(**overrides), CM)
    )


def create_confirmed_adp_with_slots(
    slot_specs=None, commence: bool = True, **spa_overrides
):
    """Customer + commenced SPA + ADP (DRAFT) + slots + propose + confirm.

    slot_specs: list of kwargs dicts for the slots (window_start/window_end/
    quantity_mmbtu). Defaults to one 3,600,000 mmbtu slot in June 2027.
    Returns dict: customer, customer_rep_headers, spa, adp, slots.
    """
    if slot_specs is None:
        slot_specs = [{}]
    customer = create_customer()
    if commence:
        spa = create_commenced_spa(customer["id"], **spa_overrides)
    else:
        spa = get_success_data(
            api_client.create_spa(create_spa_payload(customer["id"], **spa_overrides), CM)
        )
    adp = create_draft_adp(spa["id"], spa["version"])
    slots = [add_cargo_slot(adp["id"], **spec) for spec in slot_specs]
    get_success_data(api_client.propose_adp(adp["id"], CM))
    rep = make_customer_rep_headers(customer["id"])
    adp = get_success_data(api_client.confirm_adp(adp["id"], rep))
    return {
        "customer": customer,
        "rep": rep,
        "spa": spa,
        "adp": adp,
        "slots": slots,
    }


def create_locked_adp_with_slots(slot_specs=None, **spa_overrides):
    """Same as create_confirmed_adp_with_slots, plus lock."""
    ctx = create_confirmed_adp_with_slots(slot_specs, **spa_overrides)
    adp = get_success_data(api_client.lock_adp(ctx["adp"]["id"], CM))
    ctx["adp"] = adp
    return ctx


def create_cancelled_slot(slot_specs=None, cancel_clock: str = "2027-04-15T00:00:00Z", **spa_overrides):
    """Confirmed ADP, advance the clock, then cancel the first slot.

    Returns ctx dict with extra key "cancellation".
    """
    ctx = create_confirmed_adp_with_slots(slot_specs, **spa_overrides)
    slot = ctx["slots"][0]
    get_success_data(api_client.set_clock(cancel_clock, OP))
    cancellation = get_success_data(api_client.cancel_cargo_slot(slot["id"], ctx["rep"]))
    ctx["cancellation"] = cancellation
    ctx["slot"] = get_success_data(api_client.get_cargo_slot(slot["id"], CM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: vessel call marine chain
# ---------------------------------------------------------------------------

def nominate_vessel_call(slot, rep_headers, **overrides):
    """Nominate a vessel against the slot using its current version."""
    return get_success_data(
        api_client.nominate_vessel(
            slot["id"],
            create_vessel_nomination_payload(slot["version"], **overrides),
            rep_headers,
        )
    )


def setup_nominated_call(commence=True, slot_spec=None, **spa_overrides):
    """Confirmed ADP + one slot + NOMINATED vessel call + a berth.

    Returns ctx: customer, rep, spa, adp, slots, call, berth.
    """
    specs = [slot_spec] if slot_spec is not None else None
    ctx = create_confirmed_adp_with_slots(specs, commence=commence, **spa_overrides)
    slot = get_success_data(api_client.get_cargo_slot(ctx["slots"][0]["id"], CM))
    call = nominate_vessel_call(slot, ctx["rep"])
    berth = get_success_data(api_client.create_berth(create_berth_payload(), OP))
    ctx["slot"] = slot
    ctx["call"] = call
    ctx["berth"] = berth
    return ctx


def setup_departed_call(
    nor_time: str = "2027-01-12T06:00:00Z",
    berth_time: str = "2027-01-12T14:00:00Z",
    depart_time: str = "2027-01-13T22:24:00Z",
    slot_spec=None,
    berth_window_start: str = "2027-01-12T00:00:00Z",
    berth_window_end: str = "2027-01-14T00:00:00Z",
    lock_adp: bool = True,
    **spa_overrides,
):
    """Full marine chain to DEPARTED: slot window Jan 2027, call accepted,
    NOR tendered, berthed, departed. The slot is LOADED with its provisional
    invoice computed.

    Returns ctx: customer, rep, spa, adp, slots, slot (latest), call (latest),
    berth.
    """
    default_spec = {
        "window_start": "2027-01-10T00:00:00Z",
        "window_end": "2027-01-17T00:00:00Z",
        "quantity_mmbtu": 3600000,
    }
    if slot_spec is not None:
        default_spec.update(slot_spec)
    ctx = create_confirmed_adp_with_slots([default_spec], **spa_overrides)
    if lock_adp:
        ctx["adp"] = get_success_data(api_client.lock_adp(ctx["adp"]["id"], CM))
    slot = get_success_data(api_client.get_cargo_slot(ctx["slots"][0]["id"], CM))
    call = nominate_vessel_call(slot, ctx["rep"])
    berth = get_success_data(api_client.create_berth(create_berth_payload(), OP))
    call = get_success_data(
        api_client.accept_vessel_call(
            call["id"],
            {
                "berth_id": berth["id"],
                "window_start": berth_window_start,
                "window_end": berth_window_end,
            },
            MS,
        )
    )
    get_success_data(api_client.set_clock(nor_time, OP))
    call = get_success_data(api_client.tender_nor(call["id"], ctx["rep"]))
    get_success_data(api_client.set_clock(berth_time, OP))
    call = get_success_data(api_client.berth_vessel_call(call["id"], MS))
    get_success_data(api_client.set_clock(depart_time, OP))
    call = get_success_data(api_client.depart_vessel_call(call["id"], MS))
    slot = get_success_data(api_client.get_cargo_slot(slot["id"], CM))
    ctx["slot"] = slot
    ctx["call"] = call
    ctx["berth"] = berth
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: proration schedule
# ---------------------------------------------------------------------------

def setup_proration_schedule(
    nomination_amounts=(60000, 50000, 20000),
    capacity_mmbtu: int = 100000,
    pipeline_daily_capacity: int = 500000,
    slot_quantity: int = 5000000,
    gas_day: str = "2027-06-03",
    close: bool = True,
):
    """Confirmed ADP with one slot per nomination amount, an OPEN (or CLOSED)
    day schedule, and one nomination per slot in the given order.

    Returns ctx with: customer, rep, spa, adp, slots, pipeline, schedule,
    nominations (list, in creation order).
    """
    specs = [{"quantity_mmbtu": slot_quantity} for _ in nomination_amounts]
    ctx = create_confirmed_adp_with_slots(specs)
    pipeline = get_success_data(
        api_client.create_pipeline(
            create_pipeline_payload(daily_capacity_mmbtu=pipeline_daily_capacity), OP
        )
    )
    schedule = get_success_data(
        api_client.create_day_schedule(
            pipeline["id"],
            create_day_schedule_payload(gas_day=gas_day, capacity_mmbtu=capacity_mmbtu),
            GS,
        )
    )
    nominations = []
    for slot, amount in zip(ctx["slots"], nomination_amounts):
        nominations.append(
            get_success_data(
                api_client.create_nomination(
                    schedule["id"],
                    create_nomination_payload(slot["id"], amount),
                    GS,
                )
            )
        )
    if close:
        get_success_data(api_client.close_day_schedule(schedule["id"], GS))
        nominations = [
            get_success_data(api_client.get_nomination(n["id"], GS))
            for n in nominations
        ]
        schedule = get_success_data(api_client.get_day_schedule(schedule["id"], GS))
    ctx["pipeline"] = pipeline
    ctx["schedule"] = schedule
    ctx["nominations"] = nominations
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: cancellation / resale / settlement
# ---------------------------------------------------------------------------

def setup_settled_cancellation(resales=(), cancel_clock: str = "2027-04-15T00:00:00Z"):
    """Cancel a slot, optionally create+sell resales, then settle.

    resales: iterable of (offered_volume_mmbtu, sale_price or None) — None
    means leave the resale OFFERED (auto-UNSOLD at settle).
    Returns ctx with: cancellation (SETTLED), slot, resales.
    """
    ctx = create_cancelled_slot(cancel_clock=cancel_clock)
    cx = ctx["cancellation"]
    resale_list = []
    for volume, price in resales:
        resale = get_success_data(
            api_client.create_resale(cx["id"], create_resale_payload(volume), GS)
        )
        if price is not None:
            resale = get_success_data(
                api_client.sell_resale(
                    resale["id"], {"sale_price_usd_per_mmbtu": price}, GS
                )
            )
        resale_list.append(resale)
    ctx["resales"] = resale_list
    ctx["cancellation"] = get_success_data(api_client.settle_cancellation(cx["id"], CM))
    ctx["slot"] = get_success_data(api_client.get_cargo_slot(ctx["slot"]["id"], CM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: turnaround lifecycle
# ---------------------------------------------------------------------------

def propose_and_approve_turnaround(
    train_id: str,
    planned_start_date: str = "2027-03-01",
    planned_end_date: str = "2027-03-05",
    proposer_id: str = "op-1",
    approver_id: str = "op-2",
):
    """Propose a turnaround as one operator and approve it as another."""
    ta = get_success_data(
        api_client.propose_turnaround(
            train_id,
            create_turnaround_payload(
                planned_start_date=planned_start_date,
                planned_end_date=planned_end_date,
            ),
            make_operator_headers(proposer_id),
        )
    )
    ta = get_success_data(
        api_client.approve_turnaround(ta["id"], make_operator_headers(approver_id))
    )
    return ta


def begin_turnaround_at(turnaround_id: str, clock_iso: str, operator_id: str = "op-3"):
    """Advance the logical clock and begin the turnaround."""
    get_success_data(api_client.set_clock(clock_iso, OP))
    return get_success_data(
        api_client.begin_turnaround(turnaround_id, make_operator_headers(operator_id))
    )


# ---------------------------------------------------------------------------
# Common payload fragments
# ---------------------------------------------------------------------------

FINAL_INVOICE_PAYLOAD = {"actual_index_price_usd_per_mmbtu": DEFAULT_ACTUAL_INDEX_PRICE}
RECONCILE_PAYLOAD = {"reference_index_price_usd_per_mmbtu": DEFAULT_REFERENCE_INDEX_PRICE}
