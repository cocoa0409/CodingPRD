"""Composite setup helpers for the drive-thru coffee stand domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z — PRD §2.4).
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client as api
from .constants import ADMIN_USER_ID, MANAGER_USER_ID
from .factories import (
    create_agreement_payload,
    create_assignment_payload,
    create_crew_member_payload,
    create_distribution_payload,
    create_loyalty_account_payload,
    create_order_payload,
    create_points_adjustment_payload,
    create_recipe_payload,
    create_region_payload,
    create_shift_payload,
    create_stand_payload,
    create_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_crew_member_headers,
    make_loyalty_customer_headers,
    make_shift_lead_headers,
    make_stand_operator_headers,
)

PA = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["regional_manager_headers"]


def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api.set_clock(to_iso8601, PA))


# ---------------------------------------------------------------------------
# Tier 1: stand boot chain (region -> stand -> approve -> crew -> agreement)
# ---------------------------------------------------------------------------

def create_region(**overrides):
    return get_success_data(api.create_region(create_region_payload(**overrides), PA))


def create_stand(region_id, **overrides):
    return get_success_data(
        api.create_stand(create_stand_payload(region_id, **overrides), PA)
    )


def create_crew_member(home_stand_id, **overrides):
    return get_success_data(
        api.create_crew_member(create_crew_member_payload(home_stand_id, **overrides), PA)
    )


def create_loyalty_account(home_stand_id, **overrides):
    return get_success_data(
        api.create_loyalty_account(create_loyalty_account_payload(home_stand_id, **overrides), PA)
    )


def nominate_agreement(stand_id, crew_member_id, nominator_headers=None, **overrides):
    """RegionalManager nominates a crew member as shop operator (PRD §3.2)."""
    headers = nominator_headers or RM
    return get_success_data(
        api.create_agreement(
            create_agreement_payload(stand_id, crew_member_id, **overrides), headers
        )
    )


def approve_agreement(agreement_id, approver_headers=None):
    """PlatformAdmin approves a NOMINATED agreement; approver must differ from
    the nominator (segregation of duties, PRD §3.2)."""
    headers = approver_headers or PA
    return get_success_data(api.approve_agreement(agreement_id, headers))


def activate_agreement(agreement):
    """The selected operator activates their own APPROVED agreement."""
    return get_success_data(
        api.activate_agreement(
            agreement["id"], make_stand_operator_headers(agreement["crew_member_id"])
        )
    )


def setup_stand_with_agreement(stand_overrides=None, op_overrides=None):
    """Region + stand + site approval + operator crew member + NOMINATED
    agreement. Returns a dict with region, stand, op, agreement."""
    region = create_region()
    stand = create_stand(region["id"], **(stand_overrides or {}))
    # Site approval (PRD §3.1): PROPOSED -> APPROVED so the stand can be
    # opened later in the boot chain.
    stand = get_success_data(api.approve_stand(stand["id"], PA))
    op = create_crew_member(
        stand["id"], full_name="Op One", hired_on="2024-01-01", **(op_overrides or {})
    )
    agreement = nominate_agreement(stand["id"], op["id"])
    return {"region": region, "stand": stand, "op": op, "agreement": agreement}


def setup_open_stand(stand_overrides=None, op_overrides=None):
    """Full boot chain: stand APPROVED, agreement ACTIVE, stand OPEN.

    Returns a dict with region, stand (as of open), op, agreement, and
    operator_headers (StandOperator headers bound to the operator's id).
    """
    ctx = setup_stand_with_agreement(stand_overrides, op_overrides)
    ctx["agreement"] = approve_agreement(ctx["agreement"]["id"])
    ctx["agreement"] = activate_agreement(ctx["agreement"])
    op_headers = make_stand_operator_headers(ctx["op"]["id"])
    ctx["operator_headers"] = op_headers
    stand = get_success_data(api.open_stand(ctx["stand"]["id"], op_headers))
    ctx["stand"] = stand
    return ctx


def stand_version(ctx):
    """Re-read the stand and return its current version (OCC chaining)."""
    stand = get_success_data(api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]))
    ctx["stand"] = stand
    return stand["version"]


# ---------------------------------------------------------------------------
# Tier 2: menu setup (recipe + distribution, activated)
# ---------------------------------------------------------------------------

def add_recipe(ctx, activate=True, **overrides):
    """Create a recipe and stage + activate its distribution on ctx's stand."""
    recipe = get_success_data(
        api.create_recipe(create_recipe_payload(**overrides), PA)
    )
    dist = get_success_data(
        api.create_distribution(
            create_distribution_payload(recipe["id"], ctx["stand"]["id"]), PA
        )
    )
    if activate:
        dist = get_success_data(
            api.activate_distribution(dist["id"], ctx["operator_headers"])
        )
    return recipe, dist


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def place_window_order(ctx, recipe_id, lane_code="A", items=None, headers=None,
                       loyalty_account_id=None):
    """Create a WINDOW order on the stand, OCC-chained to the stand's current
    version. Returns the created order."""
    if items is None:
        items = [{"recipe_id": recipe_id, "quantity": 1, "modifier_names": []}]
    version = stand_version(ctx)
    payload = create_order_payload(
        ctx["stand"]["id"], "WINDOW", version, items, lane_code=lane_code,
    )
    if loyalty_account_id is not None:
        payload["loyalty_account_id"] = loyalty_account_id
    headers = headers or make_crew_member_headers(ctx["taker"]["id"])
    return get_success_data(api.create_order(payload, headers))


def place_app_order(ctx, recipe_id, loyalty_account_id, items=None):
    """Create a LOYALTY_APP order as the owning LoyaltyCustomer (QUEUED)."""
    if items is None:
        items = [{"recipe_id": recipe_id, "quantity": 1, "modifier_names": []}]
    version = stand_version(ctx)
    payload = create_order_payload(
        ctx["stand"]["id"], "LOYALTY_APP", version, items,
        loyalty_account_id=loyalty_account_id,
    )
    return get_success_data(
        api.create_order(payload, make_loyalty_customer_headers(loyalty_account_id))
    )


def list_items_of_order(ctx, order_id):
    items, _meta = validate_paginated(
        api.list_order_items(
            make_crew_member_headers(ctx["taker"]["id"]), params={"order_id": order_id}
        )
    )
    return items


def build_item_ready(ctx, item_id):
    """PENDING -> BUILDING -> READY on a single item."""
    headers = make_crew_member_headers(ctx["taker"]["id"])
    get_success_data(api.start_build(item_id, headers))
    return get_success_data(api.complete_build(item_id, headers))


def build_all_items_ready(ctx, order_id):
    for item in list_items_of_order(ctx, order_id):
        build_item_ready(ctx, item["id"])


def authorize_order(ctx, order_id, headers=None, card_token="VISA-OK"):
    headers = headers or make_crew_member_headers(ctx["taker"]["id"])
    return get_success_data(
        api.authorize_payment(order_id, {"card_token": card_token}, headers)
    )


def capture_order_payment(ctx, order, lead_headers=None):
    """Authorize (if UNPAID) then capture the order's payment as the lead."""
    if lead_headers is None:
        lead_headers = make_shift_lead_headers(ctx["lead"]["id"])
    order = get_success_data(api.get_order(order["id"], lead_headers))
    payments, _meta = validate_paginated(
        api.list_payments(lead_headers, params={"order_id": order["id"]})
    )
    if payments:
        payment = payments[0]
    else:
        payment = authorize_order(ctx, order["id"])
    if payment["status"] == "AUTHORIZED":
        payment = get_success_data(api.capture_payment(payment["id"], lead_headers))
    return payment


def serve_window_order(ctx, recipe_id, lane_code="A", handoff_clock=None,
                       loyalty_account_id=None):
    """Full happy path: create -> build ready -> authorize -> call-to-window
    -> capture -> handoff. Returns dict with order, payment, items."""
    order = place_window_order(
        ctx, recipe_id, lane_code=lane_code, loyalty_account_id=loyalty_account_id
    )
    items = list_items_of_order(ctx, order["id"])
    for item in items:
        build_item_ready(ctx, item["id"])
    payment = authorize_order(ctx, order["id"])
    lead_headers = make_shift_lead_headers(ctx["lead"]["id"])
    get_success_data(api.call_to_window(order["id"], lead_headers))
    payment = get_success_data(api.capture_payment(payment["id"], lead_headers))
    if handoff_clock is not None:
        set_clock(handoff_clock)
    order = get_success_data(api.handoff_order(order["id"], lead_headers))
    return {"order": order, "payment": payment, "items": items}


def setup_open_stand_with_menu(clock="2026-09-01T06:00:00Z", stand_overrides=None):
    """OPEN stand + crew (operator, taker, lead) + activated CORE recipe.

    Returns a dict with region, stand, op, taker, lead, agreement, recipe,
    dist, and bound role headers.
    """
    set_clock(clock)
    ctx = setup_open_stand(stand_overrides=stand_overrides)
    ctx["taker"] = create_crew_member(ctx["stand"]["id"], full_name="Taker Tim")
    ctx["lead"] = create_crew_member(ctx["stand"]["id"], full_name="Lead Lena")
    ctx["recipe"], ctx["dist"] = add_recipe(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: shift lifecycle helpers
# ---------------------------------------------------------------------------

def create_draft_shift(ctx, **overrides):
    return get_success_data(
        api.create_shift(
            create_shift_payload(ctx["stand"]["id"], **overrides),
            ctx["operator_headers"],
        )
    )


def add_assignment(ctx, shift_id, crew_member_id, role="BAR",
                   starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T09:00:00Z"):
    """Add an assignment, OCC-chained to the shift's current version."""
    shift = get_success_data(api.get_shift(shift_id, ctx["operator_headers"]))
    payload = create_assignment_payload(
        crew_member_id, shift["version"], role=role,
        starts_at=starts_at, ends_at=ends_at,
    )
    return get_success_data(
        api.create_assignment(shift_id, payload, ctx["operator_headers"])
    )


def setup_published_shift(ctx, crew_roles, start_clock=None, **shift_overrides):
    """Create a DRAFT shift, add the given (crew_member, role) assignments,
    publish it. crew_roles is a list of (crew_dict, role) pairs."""
    shift = create_draft_shift(ctx, **shift_overrides)
    assignments = []
    for crew, role in crew_roles:
        assignments.append(add_assignment(ctx, shift["id"], crew["id"], role=role))
    shift = get_success_data(api.publish_shift(shift["id"], ctx["operator_headers"]))
    if start_clock is not None:
        set_clock(start_clock)
    return shift, assignments


def setup_in_progress_shift(ctx, crew_roles, shift_starts_at="2026-09-01T07:00:00Z"):
    """Published shift started once the clock reaches starts_at."""
    shift, assignments = setup_published_shift(ctx, crew_roles)
    set_clock(shift_starts_at)
    shift = get_success_data(api.start_shift(shift["id"], ctx["operator_headers"]))
    return shift, assignments
