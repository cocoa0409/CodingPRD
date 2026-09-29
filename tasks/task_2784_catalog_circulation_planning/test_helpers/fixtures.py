"""Composite setup helpers.

Every test starts against an empty database, so every helper here builds its
preconditions from scratch using only the endpoints the PRD declares. Setup
calls use the lenient ``get_success_data`` validator so a broken precondition
reports as a setup failure rather than as a confusing assertion mismatch.

Money and quantity arguments are always JSON-native integers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, iso_utc, shift_days
from .constants import CLOCK_START
from . import factories as f
from .test_users import (
    ADMIN,
    ANALYST,
    BROKER,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    PLANNER_2,
)


# --------------------------------------------------------------------------
# Tier 0: the logical clock and single-entity primitives
# --------------------------------------------------------------------------
def set_clock(current_utc: str, headers=ADMIN) -> dict:
    """Move the logical clock every temporal rule reads."""
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(current_utc), headers)
    )


def new_season(headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_season(f.create_season_payload(**overrides), headers)
    )


def new_suppression_rule(season_id, headers=ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_suppression_rule(
            season_id, f.create_suppression_rule_payload(**overrides), headers
        )
    )


def new_segment(season_id, headers=PLANNER, **overrides) -> dict:
    return get_success_data(
        api_client.create_segment(
            f.create_segment_payload(season_id, **overrides), headers
        )
    )


def new_plan(season_id, headers=PLANNER, **overrides) -> dict:
    return get_success_data(
        api_client.create_plan(f.create_plan_payload(season_id, **overrides), headers)
    )


def new_drop(plan_id, headers=PLANNER, **overrides) -> dict:
    return get_success_data(
        api_client.create_drop(plan_id, f.create_drop_payload(**overrides), headers)
    )


def new_housefile_line(drop_id, segment_id, headers=PLANNER, **overrides) -> dict:
    return get_success_data(
        api_client.create_line(
            drop_id, f.create_housefile_line_payload(segment_id, **overrides), headers
        )
    )


def new_rental_line(drop_id, rental_id, headers=PLANNER, **overrides) -> dict:
    return get_success_data(
        api_client.create_line(
            drop_id, f.create_rental_line_payload(rental_id, **overrides), headers
        )
    )


def new_page_placement(drop_id, headers=PLANNER, **overrides) -> dict:
    return get_success_data(
        api_client.create_page_placement(
            drop_id, f.create_page_placement_payload(**overrides), headers
        )
    )


def new_presort_batch(drop_id, piece_count, declared_tier="FIVE_DIGIT",
                      headers=PLANNER) -> dict:
    return get_success_data(
        api_client.create_presort_batch(
            drop_id,
            f.create_presort_batch_payload(piece_count, declared_tier),
            headers,
        )
    )


def new_contact_event(segment_id, contact_date, channel="MAIL", headers=ANALYST,
                     **overrides) -> dict:
    return get_success_data(
        api_client.create_contact_event(
            f.create_contact_event_payload(
                segment_id, contact_date, channel, **overrides
            ),
            headers,
        )
    )


def new_test_cell(line_id, quantity, cell_role="TEST", headers=ANALYST,
                  **overrides) -> dict:
    return get_success_data(
        api_client.create_test_cell(
            line_id,
            f.create_test_cell_payload(quantity, cell_role, **overrides),
            headers,
        )
    )


def ingest_orders(orders, headers=ADMIN) -> dict:
    return get_success_data(
        api_client.ingest_online_orders(f.ingest_orders_payload(orders), headers)
    )


# --------------------------------------------------------------------------
# Read-back helpers
# --------------------------------------------------------------------------
def fetch_season(season_id, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_season(season_id, headers))


def fetch_segment(segment_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_segment(segment_id, headers))


def fetch_rental(rental_id, headers=BROKER) -> dict:
    return get_success_data(api_client.get_rental(rental_id, headers))


def fetch_plan(plan_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_plan(plan_id, headers))


def fetch_drop(drop_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_drop(drop_id, headers))


def fetch_line(line_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.get_line(line_id, headers))


def fetch_test_cell(cell_id, headers=ANALYST) -> dict:
    return get_success_data(api_client.get_test_cell(cell_id, headers))


def plan_version(plan_id, headers=PLANNER) -> int:
    return fetch_plan(plan_id, headers)["version"]


def drop_version(drop_id, headers=PLANNER) -> int:
    return fetch_drop(drop_id, headers)["version"]


# --------------------------------------------------------------------------
# Tier 1: state progression
# --------------------------------------------------------------------------
def new_rental_in_state(season_id, target_status="DELIVERED", coop_model_score=640,
                        delivered_gross_names=24000, headers=BROKER,
                        **overrides) -> dict:
    """Walk a prospect list rental REQUESTED -> MODELED -> ORDERED -> DELIVERED
    and stop at ``target_status``."""
    rental = get_success_data(
        api_client.create_rental(
            f.create_rental_payload(season_id, **overrides), headers
        )
    )
    if target_status == "REQUESTED":
        return rental
    rental = get_success_data(
        api_client.model_rental(
            rental["id"], f.model_rental_payload(coop_model_score), headers
        )
    )
    if target_status == "MODELED":
        return rental
    rental = get_success_data(api_client.order_rental(rental["id"], headers))
    if target_status == "ORDERED":
        return rental
    rental = get_success_data(
        api_client.deliver_rental(
            rental["id"], f.deliver_rental_payload(delivered_gross_names), headers
        )
    )
    return rental


def run_merge_purge(plan_id, input_rental_ids=None, headers=BROKER) -> dict:
    """Create a merge-purge run against the plan's current version."""
    expected = plan_version(plan_id)
    return get_success_data(
        api_client.create_merge_purge_run(
            plan_id,
            f.create_merge_purge_run_payload(expected, input_rental_ids),
            headers,
        )
    )


def allocate(drop_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.allocate_drop(drop_id, headers))


def cost_plan(plan_id, headers=PLANNER_1) -> dict:
    return get_success_data(api_client.cost_plan(plan_id, headers))


def submit_plan(plan_id, headers=PLANNER_2) -> dict:
    return get_success_data(api_client.submit_plan_for_review(plan_id, headers))


def approve_plan(plan_id, headers=DIRECTOR_9) -> dict:
    return get_success_data(api_client.approve_plan(plan_id, headers))


def presort_drop(drop_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.presort_drop(drop_id, headers))


def mail_drop(drop_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.mail_drop(drop_id, headers))


def deliver_drop(drop_id, headers=PLANNER) -> dict:
    return get_success_data(api_client.deliver_drop(drop_id, headers))


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy
# --------------------------------------------------------------------------
def setup_housefile_plan(season_overrides=None, segment_overrides=None,
                         plan_overrides=None) -> dict:
    """Season + one leaf housefile segment + one DRAFT plan.

    With the factory defaults the segment scores rfm_score 1000 (BEST,
    PREMIUM_FULL) and owns 30000 names, and the plan carries a 20000000-cent
    budget entirely uncommitted.
    """
    season = new_season(**(season_overrides or {}))
    segment = new_segment(season["id"], **(segment_overrides or {}))
    plan = new_plan(season["id"], **(plan_overrides or {}))
    return {"season": season, "segment": segment, "plan": plan}


def setup_plan_with_completed_universe(season_overrides=None,
                                       segment_overrides=None,
                                       plan_overrides=None,
                                       input_rental_ids=None) -> dict:
    """Season + segment + plan + one COMPLETED merge-purge run, which is the
    precondition allocation and costing both demand."""
    world = setup_housefile_plan(season_overrides, segment_overrides, plan_overrides)
    world["merge_purge_run"] = run_merge_purge(
        world["plan"]["id"], input_rental_ids
    )
    world["plan"] = fetch_plan(world["plan"]["id"])
    return world


def setup_drop_with_proposed_line(season_overrides=None, segment_overrides=None,
                                  plan_overrides=None, drop_overrides=None,
                                  line_overrides=None) -> dict:
    """A PLANNED drop carrying one PROPOSED housefile line, on a plan whose
    universe is already established."""
    world = setup_plan_with_completed_universe(
        season_overrides, segment_overrides, plan_overrides
    )
    world["drop"] = new_drop(world["plan"]["id"], **(drop_overrides or {}))
    world["line"] = new_housefile_line(
        world["drop"]["id"], world["segment"]["id"], **(line_overrides or {})
    )
    world["drop"] = fetch_drop(world["drop"]["id"])
    return world


# --------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_allocated_drop(season_overrides=None, segment_overrides=None,
                         plan_overrides=None, drop_overrides=None,
                         line_overrides=None) -> dict:
    """Run the budget waterfall so the drop has a planned quantity and the line
    is ALLOCATED with a frozen committed cost."""
    world = setup_drop_with_proposed_line(
        season_overrides, segment_overrides, plan_overrides,
        drop_overrides, line_overrides,
    )
    world["drop"] = allocate(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    world["plan"] = fetch_plan(world["plan"]["id"])
    return world


def setup_costed_plan(**kwargs) -> dict:
    """An allocated drop whose plan has been costed by u-planner-1."""
    world = setup_allocated_drop(**kwargs)
    world["plan"] = cost_plan(world["plan"]["id"])
    world["drop"] = fetch_drop(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    return world


def setup_plan_under_review(**kwargs) -> dict:
    """A costed plan submitted for review by u-planner-2, so both operator
    stamps differ from the director who will approve it."""
    world = setup_costed_plan(**kwargs)
    world["plan"] = submit_plan(world["plan"]["id"])
    return world


def setup_approved_drop(**kwargs) -> dict:
    """An approved plan, which is the gate presort sits behind."""
    world = setup_plan_under_review(**kwargs)
    world["plan"] = approve_plan(world["plan"]["id"])
    world["drop"] = fetch_drop(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    return world


def setup_presorted_drop(batches=None, **kwargs) -> dict:
    """An approved drop whose mail stream covers the planned quantity exactly
    and which has been repriced from actual postage.

    ``batches`` is a list of ``(declared_tier, piece_count)`` pairs. When it is
    omitted a single FIVE_DIGIT batch covering the whole planned quantity is
    recorded.

    The batches are laid down while the plan is still editable: PRD §2.10 lists
    ``POST /catalog-circulation/drops/{id}/presort-batches`` among the
    structural mutations that require the owning plan's status to be ``DRAFT``
    or ``COSTED``, while ``/presort`` itself demands an ``APPROVED`` plan.
    """
    world = setup_allocated_drop(**kwargs)
    planned = world["drop"]["planned_quantity"]
    world["presort_batches"] = []
    for declared_tier, piece_count in (batches or [("FIVE_DIGIT", planned)]):
        world["presort_batches"].append(
            new_presort_batch(world["drop"]["id"], piece_count, declared_tier)
        )
    world["plan"] = cost_plan(world["plan"]["id"])
    world["plan"] = submit_plan(world["plan"]["id"])
    world["plan"] = approve_plan(world["plan"]["id"])
    world["drop"] = presort_drop(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    world["plan"] = fetch_plan(world["plan"]["id"])
    return world


def setup_mailed_drop(mail_clock=None, **kwargs) -> dict:
    """A presorted drop mailed once the logical clock has reached its in-home
    date. ``mail_clock`` defaults to the drop's own in-home date."""
    world = setup_presorted_drop(**kwargs)
    set_clock(mail_clock or world["drop"]["in_home_date"])
    world["drop"] = mail_drop(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    world["segment"] = fetch_segment(world["segment"]["id"])
    world["plan"] = fetch_plan(world["plan"]["id"])
    return world


def setup_delivered_drop(**kwargs) -> dict:
    """A mailed drop recorded as delivered; the measurement dimension is
    deliberately untouched."""
    world = setup_mailed_drop(**kwargs)
    world["drop"] = deliver_drop(world["drop"]["id"])
    return world


def setup_matchback_open_drop(orders=None, attribution_variant="LAST_TOUCH_MAIL",
                              attribution_window_days=30, **kwargs) -> dict:
    """A mailed drop with an ingested order feed and one OPEN matchback run."""
    world = setup_mailed_drop(**kwargs)
    if orders:
        world["ingest"] = ingest_orders(orders)
    expected = world["drop"]["version"]
    world["matchback_run"] = get_success_data(
        api_client.create_matchback_run(
            world["drop"]["id"],
            f.create_matchback_run_payload(
                expected, attribution_variant, attribution_window_days
            ),
            ANALYST,
        )
    )
    world["drop"] = fetch_drop(world["drop"]["id"])
    return world


def setup_measured_control_and_test_cells(control_quantity=5000, control_responders=200,
                                          control_demand_cents=3700000,
                                          test_quantity=5000, test_responders=300,
                                          test_demand_cents=5550000, **kwargs) -> dict:
    """A mailed drop whose allocated line carries a measured CONTROL cell and a
    measured TEST cell, so lift is computable against a live control rate."""
    world = setup_mailed_drop(**kwargs)
    line_id = world["line"]["id"]
    control = new_test_cell(line_id, control_quantity, "CONTROL", cell_code="C_CTL")
    test = new_test_cell(line_id, test_quantity, "TEST", cell_code="C_TST")
    world["control_cell"] = get_success_data(
        api_client.measure_test_cell(
            control["id"],
            f.measure_test_cell_payload(control_responders, control_demand_cents),
            ANALYST,
        )
    )
    world["test_cell"] = get_success_data(
        api_client.measure_test_cell(
            test["id"],
            f.measure_test_cell_payload(test_responders, test_demand_cents),
            ANALYST,
        )
    )
    world["control_cell"] = fetch_test_cell(control["id"])
    return world


# --------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# --------------------------------------------------------------------------
def add_contact_events(segment_id, dated_channels, headers=ANALYST) -> list:
    """Log a sequence of ``(contact_date, channel)`` touches against a segment.

    Used to drive the weighted fatigue score to an exact value before the
    behaviour under test runs.
    """
    events = []
    for contact_date, channel in dated_channels:
        events.append(new_contact_event(segment_id, contact_date, channel, headers))
    return events


def setup_segment_at_fatigue(dated_channels, season_overrides=None,
                             segment_overrides=None) -> dict:
    """Season + segment carrying an exact set of contact events, so the
    segment's weighted fatigue score sits wherever the caller needs it
    relative to the season's suppression threshold."""
    season = new_season(**(season_overrides or {}))
    segment = new_segment(season["id"], **(segment_overrides or {}))
    events = add_contact_events(segment["id"], dated_channels)
    return {
        "season": season,
        "segment": fetch_segment(segment["id"]),
        "contact_events": events,
    }


def setup_plan_with_rental_line(coop_model_score=640, delivered_gross_names=24000,
                                rental_overrides=None, season_overrides=None,
                                segment_overrides=None, plan_overrides=None,
                                drop_overrides=None, line_overrides=None) -> dict:
    """A drop carrying one allocated rental line.

    Because only a NETTED rental may back an allocated line, the merge-purge
    run that establishes the universe also lists the rental in its input set.
    """
    season = new_season(**(season_overrides or {}))
    segment = new_segment(season["id"], **(segment_overrides or {}))
    plan = new_plan(season["id"], **(plan_overrides or {}))
    rental = new_rental_in_state(
        season["id"],
        "DELIVERED",
        coop_model_score,
        delivered_gross_names,
        **(rental_overrides or {}),
    )
    run = run_merge_purge(plan["id"], [rental["id"]])
    drop = new_drop(plan["id"], **(drop_overrides or {}))
    line = new_rental_line(drop["id"], rental["id"], **(line_overrides or {}))
    drop = allocate(drop["id"])
    return {
        "season": season,
        "segment": segment,
        "plan": fetch_plan(plan["id"]),
        "rental": fetch_rental(rental["id"]),
        "merge_purge_run": run,
        "drop": drop,
        "line": fetch_line(line["id"]),
    }


def setup_two_drops_sharing_a_segment(gap_days=21, first_in_home_date=None,
                                      season_overrides=None,
                                      segment_overrides=None,
                                      plan_overrides=None,
                                      requested_quantity=5000) -> dict:
    """One plan, two drops whose in-home dates sit ``gap_days`` apart, and one
    live line for the shared segment on the first drop.

    The second drop is left empty so a test can attempt the crowding line
    itself and observe whether the symmetric buffer admits it.
    """
    world = setup_plan_with_completed_universe(
        season_overrides, segment_overrides, plan_overrides
    )
    anchor_date = first_in_home_date or iso_utc("2026-09-15")
    drop_one = new_drop(
        world["plan"]["id"], drop_number=1, in_home_date=anchor_date
    )
    drop_two = new_drop(
        world["plan"]["id"],
        drop_number=2,
        in_home_date=shift_days(anchor_date, gap_days),
    )
    anchor_line = new_housefile_line(
        drop_one["id"], world["segment"]["id"], requested_quantity=requested_quantity
    )
    world["drop_one"] = fetch_drop(drop_one["id"])
    world["drop_two"] = fetch_drop(drop_two["id"])
    world["anchor_line"] = anchor_line
    return world


def setup_drop_with_placement(placement_overrides=None, **kwargs) -> dict:
    """A PLANNED drop carrying one page placement, so the space ledger has a
    non-zero allocated figure to reconcile against."""
    world = setup_plan_with_completed_universe(**kwargs)
    drop = new_drop(world["plan"]["id"])
    placement = new_page_placement(drop["id"], **(placement_overrides or {}))
    world["drop"] = fetch_drop(drop["id"])
    world["placement"] = placement
    return world


def setup_allocated_line_for_test_cells(requested_quantity=10000, **kwargs) -> dict:
    """An ALLOCATED line of a known size, which is the only line status a test
    cell may be created against."""
    return setup_allocated_drop(
        line_overrides={"requested_quantity": requested_quantity}, **kwargs
    )


# --------------------------------------------------------------------------
# Tier 5: finalization and terminal states
# --------------------------------------------------------------------------
def setup_cancelled_plan(**kwargs) -> dict:
    """An allocated drop whose plan has been cancelled, so every line is
    VOIDED, every drop CANCELLED and every completed universe SUPERSEDED."""
    world = setup_allocated_drop(**kwargs)
    world["plan"] = get_success_data(
        api_client.cancel_plan(world["plan"]["id"], DIRECTOR_9)
    )
    world["drop"] = fetch_drop(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    return world


def setup_finalized_matchback(**kwargs) -> dict:
    """A matchback read taken through to FINALIZED, closing the drop's
    measurement dimension."""
    world = setup_matchback_open_drop(**kwargs)
    world["matchback_run"] = get_success_data(
        api_client.finalize_matchback_run(world["matchback_run"]["id"], ANALYST)
    )
    world["drop"] = fetch_drop(world["drop"]["id"])
    return world


def setup_clock_at_start() -> None:
    """Return the logical clock to the value it holds at process start.

    Useful when a test has already moved the clock forward and needs the
    original instant back before exercising a temporal rule.
    """
    set_clock(CLOCK_START)
