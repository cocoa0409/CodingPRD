"""Locking the plan, the end-of-day close sweep, and who may do what."""

from test_helpers import (
    BAKER,
    CAKE_DESK,
    DECORATOR,
    REGIONAL_ADMIN,
    SECOND_BAKER,
    add_forecast_line,
    api_client,
    assert_cents,
    assert_ratio,
    assert_waste_record,
    close_day,
    confirm_cake_order,
    create_bake_day_payload,
    create_completed_par_baked_run,
    create_department_payload,
    create_waste_record_payload,
    forecast_line_payload,
    generate_plan_payload,
    get_success_data,
    headers_without_user_id,
    lock_day,
    make_department_manager_headers,
    open_pickup_slot,
    provision_second_department,
    read_bake_day,
    read_cake_order,
    read_pickup_slot,
    read_run,
    setup_draft_day,
    setup_planned_day,
    setup_reference_data,
    take_cake_order,
    validate_error,
    validate_paginated,
    validate_success,
)

BAKE_DAY_MORNING = "2026-08-12T04:00:00Z"
SLOT_START = "2026-08-12T14:00:00Z"
SLOT_END = "2026-08-12T16:00:00Z"


def _day_ready_to_close():
    """A planned day carrying one completed batch, one idle run and one live cake.

    The croissant batch is completed at its full 80 units for 600 cents of flour,
    the plan's thaw-and-serve filler is left `SCHEDULED`, and a standard two-tier
    cake is confirmed into an open pickup window holding 8 of its 10 units.
    """
    setup = setup_planned_day(clock=BAKE_DAY_MORNING)
    setup["run"] = create_completed_par_baked_run(
        setup, rack_count=2, bake_start_utc=BAKE_DAY_MORNING
    )
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=10,
    )
    order = take_cake_order(setup["bake_day"], slot, setup["cake_base"]["id"])
    setup["cake_order"] = confirm_cake_order(order["id"])
    setup["pickup_slot"] = read_pickup_slot(slot["id"])
    return setup


def _swept_records(bake_day_id):
    return validate_paginated(
        api_client.list_waste_records(REGIONAL_ADMIN, {"bake_day_id": bake_day_id})
    )


def test_closing_the_day_donates_the_shelf_and_stands_everything_else_down():
    """One transaction sweeps the shelf, the queue, the cakes and the windows.

    PRD §3.9: "The `disposition_reason` on each swept record is `DONATED` when
    `donate_remaining` is true and the owning department has
    `donation_partner_enabled` set to true".  The 80 donated units book 640 cents of
    shrink on 600 cents of production, so the ratio the close records is 1.0667.

    Design: Corner/state_machines/bake_day_close_sweeps_day_old_units_expires_cakes_and_closes_slots
    """
    setup = _day_ready_to_close()
    assert setup["department"]["donation_partner_enabled"] is True
    locked = lock_day(setup["bake_day"], setup["department"])
    assert locked["plan_posture"] == "LOCKED"

    closed = close_day(locked, setup["department"])
    assert closed["plan_posture"] == "CLOSED"
    assert closed["version"] == locked["version"] + 1

    records, meta = _swept_records(closed["id"])
    assert meta["total_count"] == 1, "One swept record per run left on the shelf"
    swept = records[0]
    assert_waste_record(swept)
    assert swept["production_run_id"] == setup["run"]["id"]
    assert swept["units"] == 80
    assert swept["disposition_reason"] == "DONATED"
    assert swept["record_status"] == "ACTIVE"
    assert swept["attested_by_user_id"] == setup["department"]["id"], (
        "The swept record is stamped with the closing manager's identity"
    )
    assert_cents(swept["waste_cost_cents"], 640, "80 units at the 8-cent basis")

    cleared = read_run(setup["run"]["id"])
    assert cleared["wasted_units_total"] == 80
    assert cleared["on_shelf_units"] == 0
    assert cleared["disposition_status"] == "CLEARED"

    stood_down = read_run(setup["filler_run"]["id"])
    assert stood_down["execution_status"] == "CANCELLED"
    assert stood_down["cancelled_reason"] == "DAY_CLOSED"

    cake = read_cake_order(setup["cake_order"]["id"])
    assert cake["order_status"] == "EXPIRED"
    assert cake["version"] == setup["cake_order"]["version"] + 1
    window = read_pickup_slot(setup["pickup_slot"]["id"])
    assert window["slot_status"] == "CLOSED"
    assert window["reserved_decoration_units"] == 0, (
        "An EXPIRED cake releases the capacity it held"
    )

    assert closed["waste_units_total"] == 80
    assert_cents(closed["shrink_cost_cents"], 640, "shrink_cost_cents")
    assert_cents(closed["production_cost_cents"], 600, "production_cost_cents")
    assert closed["produced_units_total"] == 80
    assert_ratio(closed["shrink_cost_basis_pct"], 1.0667, "shrink_cost_basis_pct")
    assert_ratio(closed["shrink_unit_basis_pct"], 1.0000, "shrink_unit_basis_pct")
    assert closed["markdown_authorization"] == "MANAGER_ONLY", (
        "The budget breach is recorded even though nothing can be discounted now"
    )
    assert closed["planned_units_total"] == 80, (
        "The cancelled filler run drops out of the planned rollups"
    )


def test_closing_without_donating_books_the_shelf_as_day_old_shrink():
    """The same sweep books the units differently when the flag is false.

    PRD §3.9: the reason is "`DAY_OLD_UNSOLD` in every other case — a department
    without a donation partner books day-old shrink no matter what the flag says."
    Everything else about the sweep — the units, the cost, the cleared run and the
    frozen ratios — is identical.

    Design: Corner/endpoints/day_close_without_donation_sweeps_shelf_stock_as_day_old_unsold
    """
    setup = _day_ready_to_close()
    locked = lock_day(setup["bake_day"], setup["department"])

    closed = close_day(locked, setup["department"], donate_remaining=False)
    assert closed["plan_posture"] == "CLOSED"

    records, meta = _swept_records(closed["id"])
    assert meta["total_count"] == 1
    swept = records[0]
    assert swept["disposition_reason"] == "DAY_OLD_UNSOLD"
    assert swept["units"] == 80
    assert_cents(swept["waste_cost_cents"], 640, "waste_cost_cents")

    cleared = read_run(setup["run"]["id"])
    assert cleared["on_shelf_units"] == 0
    assert cleared["disposition_status"] == "CLEARED"

    assert closed["waste_units_total"] == 80
    assert_cents(closed["shrink_cost_cents"], 640, "shrink_cost_cents")
    assert_ratio(closed["shrink_cost_basis_pct"], 1.0667, "shrink_cost_basis_pct")
    assert closed["markdown_authorization"] == "MANAGER_ONLY"
    assert read_cake_order(setup["cake_order"]["id"])["order_status"] == "EXPIRED"


def test_a_closed_day_refuses_every_further_write_against_it():
    """`CLOSED` is terminal for the day and for everything hanging off it.

    PRD §3.9: "From that point on, every write against the day or against any of its
    runs, windows, cake orders and waste records is rejected with
    `ERR_BAKE_DAY_CLOSED`."  Locking and closing it a second time are both refused,
    and so is attesting waste against one of its runs.

    Design: Corner/state_machines/closing_or_locking_an_already_closed_bake_day_is_rejected
    """
    setup = _day_ready_to_close()
    locked = lock_day(setup["bake_day"], setup["department"])
    closed = close_day(locked, setup["department"])
    manager = setup["manager"]

    again = api_client.close_bake_day(closed["id"], {}, manager)
    validate_error(again, "ERR_BAKE_DAY_CLOSED", 409)

    relock = api_client.lock_plan(closed["id"], manager)
    validate_error(relock, "ERR_BAKE_DAY_CLOSED", 409)

    late_waste = api_client.create_waste_record(
        create_waste_record_payload(setup["run"]["id"], 1, "DAMAGED"), SECOND_BAKER
    )
    validate_error(late_waste, "ERR_BAKE_DAY_CLOSED", 409)

    unmoved = read_bake_day(closed["id"])
    assert unmoved["plan_posture"] == "CLOSED"
    assert unmoved["version"] == closed["version"], (
        "No rejected write may advance the closed day's version"
    )
    _, meta = _swept_records(closed["id"])
    assert meta["total_count"] == 1, "The refused attestation created no record"


def test_opening_a_bake_day_without_an_operator_identity_is_unauthenticated():
    """Authentication is the very first band, before any role reasoning.

    PRD §2.10 puts "**Authentication** — headers present and `X-User-Role`
    recognised (`ERR_UNAUTHENTICATED`)" at band 1.  The identical payload succeeds
    the moment the acting manager's `X-User-ID` is supplied.

    Design: Corner/rbac/create_bake_day_missing_x_user_header_returns_unauthenticated
    """
    setup = setup_reference_data()
    payload = create_bake_day_payload(setup["department"]["id"])

    anonymous = api_client.create_bake_day(
        payload, headers_without_user_id("DepartmentManager")
    )
    validate_error(anonymous, "ERR_UNAUTHENTICATED", 401)

    _, meta = validate_paginated(
        api_client.list_bake_days(
            REGIONAL_ADMIN, {"department_id": setup["department"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "The rejected request created no bake day"

    identified = validate_success(
        api_client.create_bake_day(payload, setup["manager"]), 201
    )
    assert identified["department_id"] == setup["department"]["id"]
    assert identified["plan_posture"] == "DRAFT"


def test_each_endpoint_admits_only_the_roles_it_declares():
    """A baker may not plan and a manager may not register departments.

    PRD §2.10 band 2 is "**Role authorisation** — the acting role is listed for the
    endpoint (`ERR_ROLE_NOT_PERMITTED`)."  Plan generation is a manager's call and
    department registration is a `RegionalAdmin`'s, and each rejection leaves the
    other caller's own privileges untouched.

    Design: Corner/rbac/baker_cannot_generate_a_plan_and_manager_cannot_provision_departments
    """
    setup = setup_draft_day()
    day = add_forecast_line(
        setup["bake_day"], setup["department"], setup["croissant"]["id"], "MORNING", 40
    )

    baker_plans = api_client.generate_plan(
        day["id"], generate_plan_payload(day["version"]), BAKER
    )
    validate_error(baker_plans, "ERR_ROLE_NOT_PERMITTED", 403)
    assert read_bake_day(day["id"])["plan_posture"] == "DRAFT"

    manager_registers = api_client.create_department(
        create_department_payload(name="Store 99 Bakery", store_number="0099"),
        setup["manager"],
    )
    validate_error(manager_registers, "ERR_ROLE_NOT_PERMITTED", 403)

    admin_registers = validate_success(
        api_client.create_department(
            create_department_payload(name="Store 99 Bakery", store_number="0099"),
            REGIONAL_ADMIN,
        ),
        201,
    )
    assert admin_registers["store_number"] == "0099"

    manager_plans = validate_success(
        api_client.generate_plan(
            day["id"], generate_plan_payload(day["version"]), setup["manager"]
        ),
        200,
    )
    assert manager_plans["plan_posture"] == "PLANNED"


def test_a_manager_of_another_department_may_not_forecast_on_this_day():
    """Department scope is checked before anything about the request body.

    PRD §2.10 band 3 is "**Department scope** — a `DepartmentManager` owns the
    target (`ERR_DEPARTMENT_SCOPE_VIOLATION`)."  The visiting manager's request
    names a perfectly valid product on a perfectly valid day and is still refused,
    while the owning manager's identical request is accepted.

    Design: Corner/rbac/a_manager_of_another_department_cannot_forecast_on_this_bake_day
    """
    setup = setup_draft_day()
    day = setup["bake_day"]
    other_department = provision_second_department()
    visiting_manager = make_department_manager_headers(other_department["id"])
    payload = forecast_line_payload(setup["croissant"]["id"], "MORNING", 40)

    trespass = api_client.append_forecast_line(day["id"], payload, visiting_manager)
    validate_error(trespass, "ERR_DEPARTMENT_SCOPE_VIOLATION", 403)

    untouched = read_bake_day(day["id"])
    assert untouched["forecast_lines"] == []
    assert untouched["version"] == day["version"]

    owned = validate_success(
        api_client.append_forecast_line(day["id"], payload, setup["manager"]), 200
    )
    assert len(owned["forecast_lines"]) == 1
    assert owned["version"] == day["version"] + 1


def test_every_read_endpoint_answers_all_five_operating_roles():
    """Reads are open to the whole department, however narrow the writes are.

    PRD §4: ""Any role" in the table below means all five of `RegionalAdmin`,
    `DepartmentManager`, `Baker`, `Decorator` and `CakeDesk`."  A decorator and a
    cake-desk operator can read a production run they could never create.

    Design: Corner/rbac/every_get_endpoint_is_readable_by_all_five_roles
    """
    setup = setup_planned_day()
    run_id = setup["filler_run"]["id"]
    reads = {
        "department": (api_client.get_department, setup["department"]["id"]),
        "bake day": (api_client.get_bake_day, setup["bake_day"]["id"]),
        "product": (api_client.get_product, setup["croissant"]["id"]),
        "ingredient": (api_client.get_ingredient, setup["flour"]["id"]),
        "oven": (api_client.get_oven, setup["oven"]["id"]),
        "production run": (api_client.get_production_run, run_id),
    }

    for role_label, headers in (
        ("RegionalAdmin", REGIONAL_ADMIN),
        ("DepartmentManager", setup["manager"]),
        ("Baker", BAKER),
        ("Decorator", DECORATOR),
        ("CakeDesk", CAKE_DESK),
    ):
        for resource_label, (getter, resource_id) in reads.items():
            data = validate_success(getter(resource_id, headers), 200)
            assert data["id"] == resource_id, (
                f"{role_label} must be able to read the {resource_label}"
            )

    listed, meta = validate_paginated(
        api_client.list_production_runs(DECORATOR, {"bake_day_id": setup["bake_day"]["id"]})
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == run_id
    assert get_success_data(api_client.get_production_run(run_id, CAKE_DESK))[
        "execution_status"
    ] == "SCHEDULED"
