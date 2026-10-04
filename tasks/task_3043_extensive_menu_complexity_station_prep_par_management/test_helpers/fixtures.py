"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server, with an empty database, before
each test).  Setup calls use ``get_success_data`` so a failed precondition
surfaces as a clear "Setup failed" error rather than an assertion noise.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_restaurant_payload, create_menu_revision_payload,
    create_recipe_payload, create_prep_item_payload, create_station_payload,
    create_station_par_payload, create_cook_payload,
    create_demand_forecast_payload, create_prep_list_payload,
    create_prep_batch_payload, create_shift_assignment_payload,
    create_bakery_order_payload, create_waste_entry_payload,
    create_service_ticket_payload,
)
from .test_users import (
    system_admin_headers, menu_admin_headers, inventory_controller_headers,
    bootstrap_kitchen_manager_headers,
    make_kitchen_manager_headers, make_prep_cook_headers,
    make_line_cook_headers, make_pastry_chef_headers,
)

CLOCK_START = "2026-09-01T00:00:00Z"


def set_clock(to_iso8601: str = CLOCK_START):
    """Drive the logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, system_admin_headers()))


def create_restaurant(budget_cents=100000, name="Ridgeview", code="RIDGE"):
    """Create a restaurant and return it."""
    return get_success_data(api_client.create_restaurant(
        create_restaurant_payload(
            name=name, code=code, weekly_bakery_budget_cents=budget_cents),
        system_admin_headers()))


def create_manager(restaurant_id, name="Kara Manager",
                   certified_station_types=("GRILL",)):
    """Create the restaurant's kitchen-manager cook row.

    The KitchenManager role is cook-identity-backed, so the very first cook
    row is created under the bootstrap manager id; every subsequent
    KitchenManager call must use that row's id.
    """
    return get_success_data(api_client.create_cook(
        create_cook_payload(restaurant_id, name=name,
                            certified_station_types=list(certified_station_types)),
        bootstrap_kitchen_manager_headers()))


def create_cook(restaurant_id, manager_id, name="Chris Cook",
                certified_station_types=("GRILL",)):
    """Create a cook under an existing kitchen manager."""
    return get_success_data(api_client.create_cook(
        create_cook_payload(restaurant_id, name=name,
                            certified_station_types=list(certified_station_types)),
        make_kitchen_manager_headers(manager_id)))


def create_prep_item(name="P", station_type="SAUTE", shelf_life_hours=48,
                     min_batch_size=10, batch_unit="OZ"):
    """Create a prep item (MenuAdmin is opaque-identity)."""
    return get_success_data(api_client.create_prep_item(
        create_prep_item_payload(
            name=name, station_type=station_type,
            shelf_life_hours=shelf_life_hours,
            min_batch_size=min_batch_size, batch_unit=batch_unit),
        menu_admin_headers()))


def create_station(restaurant_id, manager_id, name="Saute 1",
                   station_type="SAUTE", rack_slot_capacity=100,
                   mise_en_place_layout=None):
    payload = create_station_payload(
        restaurant_id, name=name, station_type=station_type,
        rack_slot_capacity=rack_slot_capacity)
    if mise_en_place_layout is not None:
        payload["mise_en_place_layout"] = mise_en_place_layout
    return get_success_data(api_client.create_station(
        payload, make_kitchen_manager_headers(manager_id)))


def create_station_par(station_id, prep_item_id, manager_id, par_quantity=20):
    return get_success_data(api_client.create_station_par(
        create_station_par_payload(station_id, prep_item_id,
                                   par_quantity=par_quantity),
        make_kitchen_manager_headers(manager_id)))


def create_menu_revision_with_recipes(restaurant_id, recipes, label="V1",
                                      effective_from="2026-09-01T00:00:00Z",
                                      publish=False):
    """Create a menu revision plus one recipe per spec in ``recipes``.

    Each spec is a dict with keys ``name``, ``station_type`` and
    ``components`` (list of {prep_item_id, quantity_per_portion, unit});
    optional keys ``allergen_tags`` and ``modification_policy``.
    Returns (revision, {name: recipe}).
    """
    revision = get_success_data(api_client.create_menu_revision(
        create_menu_revision_payload(
            restaurant_id, label=label, effective_from=effective_from),
        menu_admin_headers()))
    created = {}
    for spec in recipes:
        payload = create_recipe_payload(
            revision["id"], name=spec["name"],
            station_type=spec["station_type"],
            components=spec["components"])
        if "allergen_tags" in spec:
            payload["allergen_tags"] = spec["allergen_tags"]
        if "modification_policy" in spec:
            payload["modification_policy"] = spec["modification_policy"]
        created[spec["name"]] = get_success_data(
            api_client.create_recipe(payload, menu_admin_headers()))
    if publish:
        publish_menu_revision(revision["id"])
        revision = get_success_data(
            api_client.get_menu_revision(revision["id"], menu_admin_headers()))
    return revision, created


def publish_menu_revision(revision_id):
    """Walk a revision DRAFT -> IN_REVIEW -> APPROVED -> PUBLISHED."""
    get_success_data(api_client.submit_review(revision_id, menu_admin_headers()))
    get_success_data(api_client.approve_revision(revision_id, menu_admin_headers()))
    return get_success_data(
        api_client.publish_revision(revision_id, menu_admin_headers()))


def create_forecast(restaurant_id, manager_id, item_mix,
                    service_date="2026-09-02T00:00:00Z", expected_covers=100):
    """Create a DRAFT demand forecast."""
    return get_success_data(api_client.create_demand_forecast(
        create_demand_forecast_payload(
            restaurant_id, service_date=service_date,
            expected_covers=expected_covers, item_mix=item_mix),
        make_kitchen_manager_headers(manager_id)))


def finalize_forecast(forecast_id, manager_id):
    """Walk a forecast DRAFT -> SUBMITTED -> FINALIZED."""
    mh = make_kitchen_manager_headers(manager_id)
    get_success_data(api_client.submit_forecast(forecast_id, mh))
    return get_success_data(api_client.finalize_forecast(forecast_id, mh))


def create_finalized_forecast(restaurant_id, manager_id, item_mix,
                              service_date="2026-09-02T00:00:00Z",
                              expected_covers=100):
    forecast = create_forecast(
        restaurant_id, manager_id, item_mix,
        service_date=service_date, expected_covers=expected_covers)
    return finalize_forecast(forecast["id"], manager_id)


def create_locked_prep_list(restaurant_id, manager_id, forecast_id,
                            generation_variant="OPTIMISTIC"):
    """Create a prep list, generate it, and lock it.

    Returns (prep_list, version_after_generate).
    """
    mh = make_kitchen_manager_headers(manager_id)
    prep_list = get_success_data(api_client.create_prep_list(
        create_prep_list_payload(restaurant_id, forecast_id), mh))
    generated = get_success_data(api_client.generate_prep_list(
        prep_list["id"], {"generation_variant": generation_variant}, mh))
    get_success_data(api_client.lock_prep_list(prep_list["id"], mh))
    locked = get_success_data(api_client.get_prep_list(prep_list["id"], mh))
    return locked, generated["version"]


def create_prep_batch(prep_list_id, prep_item_id, station_id, prep_cook_id,
                      quantity):
    return get_success_data(api_client.create_prep_batch(
        create_prep_batch_payload(
            prep_list_id, prep_item_id, station_id, quantity=quantity),
        make_prep_cook_headers(prep_cook_id)))


def create_and_prep_batch(prep_list_id, prep_item_id, station_id,
                          prep_cook_id, quantity):
    """Plan a batch and mark it prepped. Returns the PREPPED batch."""
    batch = create_prep_batch(
        prep_list_id, prep_item_id, station_id, prep_cook_id, quantity)
    return get_success_data(api_client.mark_prepped(
        batch["id"], make_prep_cook_headers(prep_cook_id)))


def create_bakery_order(restaurant_id, pastry_id, cheesecake_type="ORIGINAL",
                        whole_cakes_ordered=10):
    return get_success_data(api_client.create_bakery_order(
        create_bakery_order_payload(
            restaurant_id, cheesecake_type=cheesecake_type,
            whole_cakes_ordered=whole_cakes_ordered),
        make_pastry_chef_headers(pastry_id)))


def create_confirmed_bakery_order(restaurant_id, pastry_id,
                                  cheesecake_type="ORIGINAL",
                                  whole_cakes_ordered=10):
    """Bakery order walked DRAFT -> SUBMITTED -> CONFIRMED."""
    order = create_bakery_order(
        restaurant_id, pastry_id,
        cheesecake_type=cheesecake_type,
        whole_cakes_ordered=whole_cakes_ordered)
    get_success_data(api_client.submit_bakery_order(
        order["id"], make_pastry_chef_headers(pastry_id)))
    return get_success_data(api_client.confirm_bakery_order(
        order["id"], inventory_controller_headers()))


def setup_bakery_env(station_type="BAKERY"):
    """Restaurant + kitchen-manager cook + pastry-chef cook.

    Returns dict with restaurant, manager (id, headers), pastry (id, headers).
    """
    restaurant = create_restaurant()
    manager = create_manager(restaurant["id"],
                             certified_station_types=[station_type])
    pastry = create_cook(restaurant["id"], manager["id"], name="Pat Pastry",
                         certified_station_types=[station_type])
    return {
        "restaurant": restaurant,
        "manager_id": manager["id"],
        "manager_headers": make_kitchen_manager_headers(manager["id"]),
        "pastry_id": pastry["id"],
        "pastry_headers": make_pastry_chef_headers(pastry["id"]),
    }


def setup_kitchen(station_type="SAUTE", rack_slot_capacity=500,
                  need_line_cook=False, shelf_life_hours=48,
                  min_batch_size=10, batch_unit="OZ",
                  publish=True, quantity_per_portion=3):
    """Full kitchen scenario:

    restaurant + manager + prep cook (+ optional line cook) + one prep item +
    one menu revision with one recipe referencing the item + one station.

    Returns a dict of every created entity and the role ids.  When
    ``publish`` is true the revision is published (recipe becomes ACTIVE).
    """
    restaurant = create_restaurant()
    manager = create_manager(restaurant["id"],
                             certified_station_types=[station_type])
    prep_cook = create_cook(restaurant["id"], manager["id"], name="Paula Prep",
                            certified_station_types=[station_type])
    line_cook = None
    if need_line_cook:
        line_cook = create_cook(restaurant["id"], manager["id"],
                                name="Leo Line",
                                certified_station_types=[station_type])
    item = create_prep_item(name="P", station_type=station_type,
                            shelf_life_hours=shelf_life_hours,
                            min_batch_size=min_batch_size, batch_unit=batch_unit)
    revision, recipes = create_menu_revision_with_recipes(
        restaurant["id"],
        [{"name": "R", "station_type": station_type,
          "components": [{"prep_item_id": item["id"],
                          "quantity_per_portion": quantity_per_portion,
                          "unit": batch_unit}]}],
        publish=publish)
    station = create_station(restaurant["id"], manager["id"],
                             station_type=station_type,
                             rack_slot_capacity=rack_slot_capacity)
    return {
        "restaurant": restaurant,
        "manager": manager,
        "manager_headers": make_kitchen_manager_headers(manager["id"]),
        "prep_cook": prep_cook,
        "prep_cook_headers": make_prep_cook_headers(prep_cook["id"]),
        "line_cook": line_cook,
        "line_cook_headers": (
            make_line_cook_headers(line_cook["id"]) if line_cook else None),
        "prep_item": item,
        "revision": revision,
        "recipe": recipes["R"],
        "station": station,
    }
