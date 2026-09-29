"""Composite setup builders.

The harness restarts the server before every individual test, so every builder
here starts from an empty database and constructs the whole world it needs.
Builders return plain dictionaries of created resources; ``Scenario`` gives
those dictionaries attribute access so call sites read cleanly.

All setup calls go through ``get_success_data`` so a broken setup step reports
the server's own error identifier rather than a ``KeyError``.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    DIRECTOR_HEADERS,
    VENDOR_REP_HEADERS,
    make_store_manager_headers,
)


class Scenario(dict):
    """A dictionary of created resources with attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


# ==========================================================================
# Tier 1 -- primitives and single-entity builders
# ==========================================================================
def set_clock(api, current_utc: str, headers: Optional[Dict[str, str]] = None) -> None:
    """Replace the server's logical clock value."""
    get_success_data(
        api.set_clock(f.clock_payload(current_utc), headers or ANALYST_HEADERS)
    )


def reset_clock(api) -> None:
    """Return the logical clock to the value it holds before any caller sets it."""
    set_clock(api, DEFAULT_CLOCK_UTC)


def create_season(api, headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    """Register a season. Opens in ``PLANNING``."""
    return get_success_data(
        api.create_season(f.season_payload(**overrides), headers or DIRECTOR_HEADERS)
    )


def transition_season(
    api, season_id: str, to_status: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_season(
            season_id, f.season_transition_payload(to_status), headers or DIRECTOR_HEADERS
        )
    )


def read_season(api, season_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_season(season_id, headers or DIRECTOR_HEADERS))


def read_item(api, item_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_item(item_id, headers or ANALYST_HEADERS))


def read_plan(api, plan_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_markdown_plan(plan_id, headers or ANALYST_HEADERS))


def read_step(api, step_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_markdown_step(step_id, headers or ANALYST_HEADERS))


def read_execution(api, execution_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_zone_execution(execution_id, headers or ANALYST_HEADERS))


def read_store(api, store_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_store(store_id, headers or DIRECTOR_HEADERS))


def read_reservation(api, reservation_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_clearance_reservation(reservation_id, headers or ANALYST_HEADERS)
    )


def read_agreement(api, agreement_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_allowance_agreement(agreement_id, headers or ANALYST_HEADERS)
    )


def read_claim(api, claim_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_vendor_claim(claim_id, headers or CONTROLLER_HEADERS))


def read_disposition(api, order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_disposition_order(order_id, headers or ANALYST_HEADERS)
    )


def list_reservations_of_plan(api, plan_id: str) -> List[Dict[str, Any]]:
    body = get_success_data(
        api.list_clearance_reservations(
            ANALYST_HEADERS, {"markdown_plan_id": plan_id, "limit": 100}
        )
    )
    return body


def list_claims_of_agreement(api, agreement_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_vendor_claims(
            CONTROLLER_HEADERS, {"allowance_agreement_id": agreement_id, "limit": 100}
        )
    )


def create_chain_zone(api, headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_zone(f.chain_zone_payload(**overrides), headers or DIRECTOR_HEADERS)
    )


def create_region_zone(
    api, parent_zone_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_zone(
            f.region_zone_payload(parent_zone_id, **overrides), headers or DIRECTOR_HEADERS
        )
    )


def create_store_zone(
    api, parent_zone_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_price_zone(
            f.store_zone_payload(parent_zone_id, **overrides), headers or DIRECTOR_HEADERS
        )
    )


def create_store(
    api, price_zone_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_store(f.store_payload(price_zone_id, **overrides), headers or DIRECTOR_HEADERS)
    )


def create_item(
    api, season_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_item(f.item_payload(season_id, **overrides), headers or ANALYST_HEADERS)
    )


def post_sales_week(
    api,
    item_id: str,
    week_ending_date: str,
    units_sold: int,
    ticket_price_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_sales_week(
            item_id,
            f.sales_week_payload(week_ending_date, units_sold, ticket_price_cents),
            headers or ANALYST_HEADERS,
        )
    )


def post_history(
    api,
    item_id: str,
    history: Sequence[Tuple[str, int, int]] = f.BASE_SALES_HISTORY,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Post a whole weekly history in order, one reading at a time."""
    return [
        post_sales_week(api, item_id, date, units, price, headers)
        for date, units, price in history
    ]


def create_estimate(
    api, item_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_elasticity_estimate(
            f.elasticity_estimate_payload(item_id, **overrides), headers or ANALYST_HEADERS
        )
    )


def certify_estimate(
    api,
    estimate_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.certify_elasticity_estimate(
            estimate_id, f.certify_payload(**overrides), headers or ANALYST_HEADERS
        )
    )


def certified_estimate(
    api, item_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """Request an estimate and certify it in one step."""
    certify_overrides = {}
    if "override_low_confidence" in overrides:
        certify_overrides["override_low_confidence"] = overrides.pop(
            "override_low_confidence"
        )
    estimate = create_estimate(api, item_id, headers, **overrides)
    return certify_estimate(api, estimate["id"], headers, **certify_overrides)


def create_plan(
    api,
    season_id: str,
    item_id: str,
    estimate_id: str,
    headers: Optional[Dict[str, str]] = None,
    expected_item_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """Open a markdown plan, reading the item's current ``version`` for the guard."""
    if expected_item_version is None:
        expected_item_version = read_item(api, item_id)["version"]
    return get_success_data(
        api.create_markdown_plan(
            f.markdown_plan_payload(
                season_id, item_id, estimate_id, expected_item_version, **overrides
            ),
            headers or ANALYST_HEADERS,
        )
    )


def add_rung(
    api,
    plan_id: str,
    step_index: int,
    effective_date: str,
    depth_pct: float,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_markdown_step(
            plan_id,
            f.markdown_step_payload(step_index, effective_date, depth_pct, **overrides),
            headers or ANALYST_HEADERS,
        )
    )


def submit_plan(api, plan_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.submit_markdown_plan(plan_id, f.submit_payload(), headers or ANALYST_HEADERS)
    )


def approve_plan(api, plan_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.approve_markdown_plan(plan_id, f.approve_payload(), headers or DIRECTOR_HEADERS)
    )


def request_revision(
    api, plan_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.request_plan_revision(
            plan_id, f.request_revision_payload(**overrides), headers or DIRECTOR_HEADERS
        )
    )


def reopen_plan(
    api,
    plan_id: str,
    clear_ladder: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.reopen_markdown_plan(
            plan_id, f.reopen_payload(clear_ladder), headers or ANALYST_HEADERS
        )
    )


def schedule_execution(
    api,
    plan_id: str,
    step_id: str,
    price_zone_id: str,
    execution_scope: str,
    effective_date: str,
    units_in_scope: int,
    store_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_zone_execution(
            f.zone_execution_payload(
                plan_id,
                step_id,
                price_zone_id,
                execution_scope,
                effective_date,
                units_in_scope,
                store_id,
                **overrides,
            ),
            headers or ANALYST_HEADERS,
        )
    )


def post_signage(
    api, execution_id: str, store_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Record that the signage is physically up.

    For a store-scope execution the acting ``X-User-ID`` must be the store's
    ``id``; pass that store id so the ownership check passes.
    """
    if headers is None:
        headers = make_store_manager_headers(store_id) if store_id else None
    if headers is None:
        raise AssertionError(
            "post_signage needs either a store_id or explicit store-manager headers"
        )
    return get_success_data(
        api.post_signage(execution_id, f.post_signage_payload(), headers)
    )


def verify_signage(
    api, execution_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.verify_signage(execution_id, f.verify_signage_payload(), headers or DIRECTOR_HEADERS)
    )


def apply_execution(
    api, execution_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.apply_zone_execution(execution_id, f.apply_payload(), headers or ANALYST_HEADERS)
    )


def roll_back_execution(
    api, execution_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.roll_back_zone_execution(
            execution_id, f.roll_back_payload(**overrides), headers or ANALYST_HEADERS
        )
    )


def allocate_clearance(
    api,
    season_id: str,
    plan_id: str,
    total_units: int,
    headers: Optional[Dict[str, str]] = None,
    expected_season_version: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Allocate clearance floor space across the season's open stores."""
    if expected_season_version is None:
        expected_season_version = read_season(api, season_id)["version"]
    return get_success_data(
        api.create_clearance_allocation(
            season_id,
            f.clearance_allocation_payload(plan_id, total_units, expected_season_version),
            headers or ANALYST_HEADERS,
        )
    )


def release_reservation(
    api, reservation_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.release_clearance_reservation(
            reservation_id, f.release_payload(**overrides), headers or ANALYST_HEADERS
        )
    )


def create_agreement(
    api, season_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_allowance_agreement(
            f.allowance_agreement_payload(season_id, **overrides), headers or ANALYST_HEADERS
        )
    )


def counter_agreement(
    api,
    agreement_id: str,
    share_pct: float,
    cap_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.counter_allowance_agreement(
            agreement_id,
            f.counter_payload(share_pct, cap_cents),
            headers or VENDOR_REP_HEADERS,
        )
    )


def accept_agreement(
    api, agreement_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Accept the offer on the table. The accepting party's role must differ
    from ``last_offer_by_role``, so a retailer-opened agreement is accepted by
    the vendor representative.
    """
    return get_success_data(
        api.accept_allowance_agreement(
            agreement_id, f.accept_payload(), headers or VENDOR_REP_HEADERS
        )
    )


def agreed_agreement(
    api, season_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """Open a negotiation and have the vendor accept the retailer's opening terms."""
    agreement = create_agreement(api, season_id, headers, **overrides)
    return accept_agreement(api, agreement["id"])


def create_claim(
    api,
    agreement_id: str,
    plan_id: str,
    claimed_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_vendor_claim(
            f.vendor_claim_payload(agreement_id, plan_id, claimed_cents),
            headers or ANALYST_HEADERS,
        )
    )


def recognize_claim(
    api, claim_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.recognize_vendor_claim(claim_id, f.recognize_payload(), headers or CONTROLLER_HEADERS)
    )


def reverse_claim(
    api, claim_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_vendor_claim(
            claim_id, f.reverse_payload(**overrides), headers or CONTROLLER_HEADERS
        )
    )


def create_disposition(
    api, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_disposition_order(payload, headers or ANALYST_HEADERS)
    )


def approve_disposition(
    api, order_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.approve_disposition_order(
            order_id, f.approve_disposition_payload(), headers or CONTROLLER_HEADERS
        )
    )


def settle_disposition(
    api, order_id: str, settled_units: int, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.settle_disposition_order(
            order_id, f.settle_payload(settled_units), headers or CONTROLLER_HEADERS
        )
    )


def cancel_disposition(
    api, order_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_disposition_order(
            order_id, f.cancel_payload(**overrides), headers or ANALYST_HEADERS
        )
    )


def generate_review(
    api, season_id: str, review_type: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_exit_review(
            season_id, f.exit_review_payload(review_type), headers or DIRECTOR_HEADERS
        )
    )


# ==========================================================================
# Tier 2 -- the base world: an ACTIVE season, its zone geometry, and one item
#           with four weeks of price history
# ==========================================================================
WORKING_CLOCK = "2026-10-10T00:00:00Z"
FIRST_RUNG_DATE = "2026-10-19"
FIRST_RUNG_CLOCK = "2026-10-19T00:00:00Z"
FIRST_RUNG_DEPTH_PCT = 22.57
LATE_RUNG_DATE = "2026-11-16"
LATE_RUNG_CLOCK = "2026-11-16T00:00:00Z"


def base_scenario(api, **season_overrides) -> Scenario:
    """Season ``FW26-APPAREL`` ACTIVE, a CHAIN and a REGION zone, three stores,
    and item ``A-1001`` carrying four posted weeks of sales history.

    Store ``0202`` holds 500 bays and store ``0101`` holds 300, both OPEN;
    store ``0303`` holds 120 bays but sits in ``REMODEL``. The clock is left at
    ``2026-10-10T00:00:00Z``, by which date the item's six-week protected
    new-arrival window has closed.
    """
    season = create_season(api, **season_overrides)
    chain_zone = create_chain_zone(api)
    west_zone = create_region_zone(api, chain_zone["id"])
    store_0101 = create_store(
        api, west_zone["id"], store_number="0101", clearance_bay_units=300
    )
    store_0202 = create_store(
        api, west_zone["id"], store_number="0202", clearance_bay_units=500
    )
    store_0303 = create_store(
        api,
        west_zone["id"],
        store_number="0303",
        clearance_bay_units=120,
        status="REMODEL",
    )
    item = create_item(api, season["id"])
    season = transition_season(api, season["id"], "ACTIVE")
    weeks = post_history(api, item["id"])
    set_clock(api, WORKING_CLOCK)
    return Scenario(
        season=season,
        chain_zone=chain_zone,
        west_zone=west_zone,
        store_0101=store_0101,
        store_0202=store_0202,
        store_0303=store_0303,
        item=item,
        weeks=weeks,
    )


def certified_scenario(api, sc: Optional[Scenario] = None) -> Scenario:
    """The base world plus an ``AUTO`` estimate that resolved to ``OWN_HISTORY``
    with ``HIGH`` confidence and has been certified.
    """
    sc = sc or base_scenario(api)
    estimate = create_estimate(api, sc.item["id"])
    sc["estimate"] = certify_estimate(api, estimate["id"])
    return sc


def planned_scenario(
    api, sc: Optional[Scenario] = None, plan_type: str = "PERMANENT", **plan_overrides
) -> Scenario:
    """A ``DRAFT`` markdown plan opened against the certified estimate."""
    sc = sc or certified_scenario(api)
    sc["plan"] = create_plan(
        api,
        sc.season["id"],
        sc.item["id"],
        sc.estimate["id"],
        plan_type=plan_type,
        **plan_overrides,
    )
    return sc


def approved_plan_scenario(
    api,
    sc: Optional[Scenario] = None,
    effective_date: str = FIRST_RUNG_DATE,
    depth_pct: float = FIRST_RUNG_DEPTH_PCT,
    plan_type: str = "PERMANENT",
    **plan_overrides,
) -> Scenario:
    """A one-rung ladder submitted by the analyst and approved by a director
    who is not the plan's creator.
    """
    sc = sc or planned_scenario(api, plan_type=plan_type, **plan_overrides)
    sc["step1"] = add_rung(api, sc.plan["id"], 1, effective_date, depth_pct)
    submit_plan(api, sc.plan["id"])
    sc["plan"] = approve_plan(api, sc.plan["id"])
    return sc


def allocated_scenario(
    api, sc: Optional[Scenario] = None, total_units: int = 600
) -> Scenario:
    """An approved plan that has drawn ``total_units`` of clearance floor space
    through the waterfall, filling the largest free bay first.
    """
    sc = sc or approved_plan_scenario(api)
    sc["reservations"] = allocate_clearance(api, sc.season["id"], sc.plan["id"], total_units)
    return sc


def scheduled_execution_scenario(
    api,
    sc: Optional[Scenario] = None,
    units_in_scope: int = 200,
    effective_date: str = FIRST_RUNG_DATE,
) -> Scenario:
    """A ZONE-scope execution of rung 1 against the REGION zone, still
    ``SCHEDULED`` with ``PENDING`` signage.
    """
    sc = sc or approved_plan_scenario(api, effective_date=effective_date)
    sc["execution"] = schedule_execution(
        api,
        sc.plan["id"],
        sc.step1["id"],
        sc.west_zone["id"],
        "ZONE",
        effective_date,
        units_in_scope,
    )
    return sc


def verified_execution_scenario(
    api,
    sc: Optional[Scenario] = None,
    units_in_scope: int = 200,
    effective_date: str = FIRST_RUNG_DATE,
) -> Scenario:
    """A scheduled execution whose signage has been posted in time by a store
    manager and then verified by the director, so the apply gate is open.
    """
    sc = sc or scheduled_execution_scenario(
        api, units_in_scope=units_in_scope, effective_date=effective_date
    )
    post_signage(api, sc.execution["id"], sc.store_0101["id"])
    sc["execution"] = verify_signage(api, sc.execution["id"])
    return sc


def applied_execution_scenario(
    api,
    sc: Optional[Scenario] = None,
    units_in_scope: int = 200,
    effective_date: str = FIRST_RUNG_DATE,
    clock: str = FIRST_RUNG_CLOCK,
) -> Scenario:
    """A verified execution applied on its effective date, which writes the
    ticket down and drives the five-hop apply cascade.
    """
    sc = sc or verified_execution_scenario(
        api, units_in_scope=units_in_scope, effective_date=effective_date
    )
    set_clock(api, clock)
    sc["execution"] = apply_execution(api, sc.execution["id"])
    sc["plan"] = read_plan(api, sc.plan["id"])
    sc["item"] = read_item(api, sc.item["id"])
    sc["season"] = read_season(api, sc.season["id"])
    return sc


def exit_window_scenario(
    api, sc: Optional[Scenario] = None, total_units: int = 600
) -> Scenario:
    """Clearance commitment tips the season into its exit window: the plan is
    approved, 600 units of space are reserved, and applying the execution
    commits them, which lifts ``committed_clearance_units`` to the trigger.
    """
    sc = sc or allocated_scenario(api, total_units=total_units)
    sc = scheduled_execution_scenario(api, sc)
    sc = verified_execution_scenario(api, sc)
    sc = applied_execution_scenario(api, sc)
    return sc


# ==========================================================================
# Tier 4 -- accumulation and threshold targeting
# ==========================================================================
def executing_plan_with_agreement(
    api,
    sc: Optional[Scenario] = None,
    share_pct: float = 25.00,
    cap_cents: int = 56400,
) -> Scenario:
    """An ``EXECUTING`` permanent plan with 225600 cents of applied gross
    markdown, plus an ``AGREED`` allowance agreement for the same vendor,
    category and season.
    """
    sc = sc or applied_execution_scenario(api)
    sc["agreement"] = agreed_agreement(
        api, sc.season["id"], current_share_pct=share_pct, current_cap_cents=cap_cents
    )
    return sc


def peer_pool_scenario(api, sc: Optional[Scenario] = None) -> Scenario:
    """A cluster peer of item ``A-1001`` that holds a ``CERTIFIED`` estimate, so
    the cluster-pooled path has exactly one qualifying peer.
    """
    sc = sc or base_scenario(api)
    peer = create_item(
        api,
        sc.season["id"],
        sku="C-3003",
        original_retail_cents=3999,
        unit_cost_cents=1500,
        units_received_total=400,
    )
    post_history(
        api,
        peer["id"],
        [
            ("2026-09-05", 45, 3999),
            ("2026-09-12", 45, 3999),
            ("2026-09-19", 45, 3999),
            ("2026-09-26", 45, 3999),
        ],
    )
    peer_estimate = create_estimate(api, peer["id"], method="OWN_HISTORY")
    sc["peer_item"] = peer
    sc["peer_estimate"] = peer_estimate
    return sc


# ==========================================================================
# Tier 5 -- finalization and terminal states
# ==========================================================================
def exit_pending_scenario(api, sc: Optional[Scenario] = None) -> Scenario:
    """A season in ``EXIT_WINDOW`` whose item has been reclassified into
    ``EXIT_PENDING``, which is what makes it eligible for a disposition order.

    The clock is advanced to within two whole weeks of the season's exit
    target date of 2027-01-15.
    """
    sc = sc or exit_window_scenario(api)
    set_clock(api, "2027-01-05T00:00:00Z")
    sc["item"] = read_item(api, sc.item["id"])
    sc["season"] = read_season(api, sc.season["id"])
    return sc


def closed_season_scenario(api, sc: Optional[Scenario] = None) -> Scenario:
    """A ``CLOSED`` season: a FINAL review exists and no disposition order of
    the season is still in ``DRAFT`` or ``APPROVED``.
    """
    sc = sc or exit_window_scenario(api)
    sc["final_review"] = generate_review(api, sc.season["id"], "FINAL")
    sc["season"] = transition_season(api, sc.season["id"], "CLOSED")
    return sc


# ==========================================================================
# Tier 3 -- full-lifecycle shortcuts for the deeper scenarios
# ==========================================================================
PEER_B_HISTORY = [
    ("2026-09-05", 40, 3999),
    ("2026-09-12", 38, 3999),
    ("2026-09-19", 52, 3599),
    ("2026-09-26", 55, 3599),
]

SECOND_RUNG_DATE = "2026-11-09"
SECOND_RUNG_DEPTH_PCT = 35.00


def add_item_b(api, sc: Scenario) -> Dict[str, Any]:
    """Register cluster peer ``B-2002`` and post its four weeks of history.

    Its earliest week sold 40 units at 3999 cents and its latest sold 55 at
    3599, giving a two-point log-log slope of -3.0217 and 185 units sold.
    """
    peer = create_item(
        api,
        sc.season["id"],
        sku="B-2002",
        first_receipt_date="2026-08-18",
        original_retail_cents=3999,
        unit_cost_cents=1500,
        units_received_total=400,
    )
    post_history(api, peer["id"], PEER_B_HISTORY)
    sc["item_b"] = peer
    return peer


def dual_estimate_scenario(api) -> Scenario:
    """Item ``A-1001`` qualifies for own history while cluster peer ``B-2002``
    already holds a ``CERTIFIED`` own-history estimate, so both estimation
    paths are available for item A.
    """
    sc = base_scenario(api)
    add_item_b(api, sc)
    peer_estimate = create_estimate(api, sc.item_b["id"], method="OWN_HISTORY")
    sc["peer_b_estimate"] = certify_estimate(api, peer_estimate["id"])
    return sc


def scorecard_scenario(api) -> Scenario:
    """A season in ``EXIT_WINDOW`` carrying every row that makes the two review
    variants diverge: one APPLIED execution, one still-SCHEDULED execution, a
    claim still ``SUBMITTED`` and a disposition order still ``APPROVED``.
    """
    sc = base_scenario(api)
    add_item_b(api, sc)
    sc = certified_scenario(api, sc)
    sc = planned_scenario(api, sc)
    sc["step1"] = add_rung(api, sc.plan["id"], 1, FIRST_RUNG_DATE, FIRST_RUNG_DEPTH_PCT)
    sc["step2"] = add_rung(
        api, sc.plan["id"], 2, SECOND_RUNG_DATE, SECOND_RUNG_DEPTH_PCT
    )
    submit_plan(api, sc.plan["id"])
    sc["plan"] = approve_plan(api, sc.plan["id"])
    sc["execution"] = schedule_execution(
        api,
        sc.plan["id"],
        sc.step1["id"],
        sc.west_zone["id"],
        "ZONE",
        FIRST_RUNG_DATE,
        200,
    )
    post_signage(api, sc.execution["id"], sc.store_0101["id"])
    verify_signage(api, sc.execution["id"])
    set_clock(api, FIRST_RUNG_CLOCK)
    sc["execution"] = apply_execution(api, sc.execution["id"])
    sc["execution_two"] = schedule_execution(
        api,
        sc.plan["id"],
        sc.step2["id"],
        sc.west_zone["id"],
        "ZONE",
        SECOND_RUNG_DATE,
        100,
    )
    sc["agreement"] = agreed_agreement(
        api, sc.season["id"], current_share_pct=25.00, current_cap_cents=100000
    )
    sc["claim"] = create_claim(api, sc.agreement["id"], sc.plan["id"], 60000)
    sc["disposition"] = create_disposition(
        api,
        f.salvage_order_payload(sc.season["id"], sc.item["id"], 50, 300),
    )
    sc["season"] = transition_season(api, sc.season["id"], "EXIT_WINDOW")
    sc["disposition"] = approve_disposition(api, sc.disposition["id"])
    sc["item"] = read_item(api, sc.item["id"])
    sc["plan"] = read_plan(api, sc.plan["id"])
    return sc
