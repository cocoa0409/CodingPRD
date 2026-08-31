"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  Setup calls
go through get_success_data() so a broken precondition surfaces as an explicit
"Setup step failed" rather than as a confusing assertion later on.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CYCLE_WINDOW_END,
    CYCLE_WINDOW_START,
    EVENT_WINDOW_END,
    EVENT_WINDOW_START,
    YEAR_ROUND_WINDOW_END,
)
from .factories import (
    backpack_payload,
    cash_donation_payload,
    collection_site_payload,
    distribution_event_payload,
    donation_batch_payload,
    drive_cycle_payload,
    grade_kit_spec_payload,
    inventory_adjustment_payload,
    kit_spec_line_payload,
    notebook_payload,
    pencil_payload,
    purchase_order_payload,
    school_payload,
    student_registration_payload,
    supply_item_payload,
    teacher_request_payload,
    volunteer_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_school_liaison_headers,
    make_site_coordinator_headers,
)

PD = TEST_USERS["program_director_headers"]
PD_ALT = TEST_USERS["program_director_alt_headers"]
WL = TEST_USERS["warehouse_lead_headers"]
DR = TEST_USERS["donor_relations_headers"]


# --------------------------------------------------------------------------
# Tier 1: single-resource creation and state progression
# --------------------------------------------------------------------------


def create_school(**overrides) -> dict:
    """Register a partner school; it lands in PROSPECT."""
    return get_success_data(api_client.create_school(school_payload(**overrides), PD))


def move_school(school_id, target_status, headers=PD):
    """Raw partnership-status transition; returns the raw response."""
    return api_client.set_partnership_status(
        school_id, {"target_status": target_status}, headers
    )


def create_active_school(**overrides) -> dict:
    """PROSPECT -> MOU_PENDING -> ACTIVE.  Returns the ACTIVE school."""
    school = create_school(**overrides)
    get_success_data(move_school(school["id"], "MOU_PENDING"))
    return get_success_data(move_school(school["id"], "ACTIVE"))


def create_supply_item(**overrides) -> dict:
    return get_success_data(api_client.create_supply_item(supply_item_payload(**overrides), PD))


def create_pencil(**overrides) -> dict:
    """WRITING item, 250 cents a unit, packs of 12."""
    return get_success_data(api_client.create_supply_item(pencil_payload(**overrides), PD))


def create_notebook(**overrides) -> dict:
    """PAPER item, 180 cents a unit, packs of 10."""
    return get_success_data(api_client.create_supply_item(notebook_payload(**overrides), PD))


def create_backpack(**overrides) -> dict:
    """BACKPACK item, 1450 cents a unit, packs of 6."""
    return get_success_data(api_client.create_supply_item(backpack_payload(**overrides), PD))


def create_drive_cycle(**overrides) -> dict:
    return get_success_data(api_client.create_drive_cycle(drive_cycle_payload(**overrides), PD))


def move_cycle(cycle_id, target_status, headers=PD):
    return api_client.set_drive_cycle_status(cycle_id, {"target_status": target_status}, headers)


def create_collecting_cycle(**overrides) -> dict:
    """Open a cycle and move it to COLLECTING."""
    cycle = create_drive_cycle(**overrides)
    return get_success_data(move_cycle(cycle["id"], "COLLECTING"))


def create_year_round_cycle(**overrides) -> dict:
    payload = {
        "name": "Year-Round 2026",
        "cadence": "YEAR_ROUND",
        "window_start": CYCLE_WINDOW_START,
        "window_end": YEAR_ROUND_WINDOW_END,
    }
    payload.update(overrides)
    return create_drive_cycle(**payload)


def advance_cycle_to(cycle_id, target_status) -> dict:
    """Walk the cycle phase machine one step at a time up to target_status."""
    order = ["COLLECTING", "SORTING", "DISTRIBUTION", "RECONCILED", "CLOSED"]
    result = None
    for phase in order:
        result = get_success_data(move_cycle(cycle_id, phase))
        if phase == target_status:
            return result
    return result


def create_site(cycle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_collection_site(collection_site_payload(cycle_id, **overrides), PD)
    )


def move_site_operational(site_id, target_status, headers=PD):
    return api_client.set_site_operational_status(
        site_id, {"target_status": target_status}, headers
    )


def move_site_pledge(site_id, target_status, headers=None):
    return api_client.set_site_pledge_status(
        site_id,
        {"target_status": target_status},
        headers or make_site_coordinator_headers(site_id),
    )


def create_active_site(cycle_id, **overrides) -> dict:
    """Open a collection site and take its operational dimension to ACTIVE."""
    site = create_site(cycle_id, **overrides)
    return get_success_data(move_site_operational(site["id"], "ACTIVE"))


def create_active_corporate_site(cycle_id, pledged_item_count=50, **overrides) -> dict:
    """CORPORATE site walked to operational ACTIVE and pledge PLEDGE_ACTIVE."""
    site = create_site(
        cycle_id,
        name="Beacon Insurance",
        site_type="CORPORATE",
        bin_capacity=6,
        pledged_item_count=pledged_item_count,
        **overrides,
    )
    get_success_data(move_site_pledge(site["id"], "PLEDGED"))
    get_success_data(move_site_operational(site["id"], "ACTIVE"))
    return get_success_data(move_site_pledge(site["id"], "PLEDGE_ACTIVE"))


def set_clock(to_iso8601) -> dict:
    """Move the logical program clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PD))


# --------------------------------------------------------------------------
# Tier 2: needs lists and their lines
# --------------------------------------------------------------------------


def create_spec(school_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_grade_kit_spec(
            grade_kit_spec_payload(school_id, **overrides),
            make_school_liaison_headers(school_id),
        )
    )


def add_spec_line(school_id, spec_id, supply_item_id, qty_per_student=1, **overrides) -> dict:
    return get_success_data(
        api_client.create_kit_spec_line(
            kit_spec_line_payload(
                spec_id, supply_item_id, qty_per_student=qty_per_student, **overrides
            ),
            make_school_liaison_headers(school_id),
        )
    )


def move_spec(school_id, spec_id, target_status):
    return api_client.set_grade_kit_spec_status(
        spec_id, {"target_status": target_status}, make_school_liaison_headers(school_id)
    )


def create_published_spec(school_id, lines, grade_band="K_2", student_target_count=100) -> dict:
    """Open a needs list, attach `lines` as (supply_item_id, qty_per_student), publish it."""
    spec = create_spec(
        school_id, grade_band=grade_band, student_target_count=student_target_count
    )
    for item_id, qty in lines:
        add_spec_line(school_id, spec["id"], item_id, qty_per_student=qty)
    return get_success_data(move_spec(school_id, spec["id"], "PUBLISHED"))


# --------------------------------------------------------------------------
# Tier 3: inventory, cash and purchasing
# --------------------------------------------------------------------------


def adjust_inventory(cycle_id, supply_item_id, delta_on_hand_qty, **overrides) -> dict:
    """Warehouse cycle-count adjustment; creates the position when absent."""
    return get_success_data(
        api_client.adjust_inventory_position(
            inventory_adjustment_payload(
                cycle_id, supply_item_id, delta_on_hand_qty, **overrides
            ),
            WL,
        )
    )


def read_position(cycle_id, supply_item_id) -> dict:
    """Read the (cycle, item) position through the filtered list endpoint."""
    body = api_client.list_inventory_positions(
        WL, params={"drive_cycle_id": cycle_id, "supply_item_id": supply_item_id}
    ).json()
    rows = body["data"]
    assert rows, f"no inventory position for cycle {cycle_id} item {supply_item_id}"
    return rows[0]


def create_cash_gift(cycle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_cash_donation(cash_donation_payload(cycle_id, **overrides), DR)
    )


def create_purchase_order(cycle_id, supply_item_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_purchase_order(
            purchase_order_payload(cycle_id, supply_item_id, **overrides), WL
        )
    )


def cycle_version(cycle_id, headers=WL) -> int:
    """The governing cycle's current version, for expected_drive_cycle_version."""
    return get_success_data(api_client.get_drive_cycle(cycle_id, headers))["version"]


def move_order(order_id, cycle_id, target_status, headers=WL):
    """Transition a purchase order, reading the cycle's live version first."""
    return api_client.transition_purchase_order(
        order_id,
        {
            "target_status": target_status,
            "expected_drive_cycle_version": cycle_version(cycle_id),
        },
        headers,
    )


def submit_order(order_id, cycle_id, headers=WL) -> dict:
    return get_success_data(move_order(order_id, cycle_id, "SUBMITTED", headers))


def approve_order(order_id, cycle_id, headers=PD_ALT) -> dict:
    return get_success_data(move_order(order_id, cycle_id, "APPROVED", headers))


def receive_order(order_id, cycle_id, headers=WL) -> dict:
    return get_success_data(move_order(order_id, cycle_id, "RECEIVED", headers))


# --------------------------------------------------------------------------
# Tier 4: donation intake
# --------------------------------------------------------------------------


def create_batch(site_id, supply_item_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_donation_batch(
            donation_batch_payload(site_id, supply_item_id, **overrides),
            make_site_coordinator_headers(site_id),
        )
    )


def move_batch(batch_id, target_status, headers=WL, **extra):
    payload = {"target_status": target_status}
    payload.update(extra)
    return api_client.transition_donation_batch(batch_id, payload, headers)


def inspect_batch(site_id, batch_id) -> dict:
    """Inspection is the SiteCoordinator's step, and only for its own site."""
    return get_success_data(
        move_batch(batch_id, "INSPECTED", headers=make_site_coordinator_headers(site_id))
    )


def create_inspected_batch(site_id, supply_item_id, **overrides) -> dict:
    batch = create_batch(site_id, supply_item_id, **overrides)
    return inspect_batch(site_id, batch["id"])


# --------------------------------------------------------------------------
# Tier 5: distribution events and registrations
# --------------------------------------------------------------------------


def create_event(school_id, cycle_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_distribution_event(
            distribution_event_payload(school_id, cycle_id, **overrides),
            make_school_liaison_headers(school_id),
        )
    )


def move_event(event_id, school_id, target_status):
    return api_client.transition_distribution_event(
        event_id, {"target_status": target_status}, make_school_liaison_headers(school_id)
    )


def create_published_event(school_id, cycle_id, **overrides) -> dict:
    event = create_event(school_id, cycle_id, **overrides)
    return get_success_data(move_event(event["id"], school_id, "PUBLISHED"))


def read_event(event_id, school_id) -> dict:
    return get_success_data(
        api_client.get_distribution_event(event_id, make_school_liaison_headers(school_id))
    )


def event_version(event_id, school_id) -> int:
    """The governing event's current version, for expected_distribution_event_version."""
    return read_event(event_id, school_id)["version"]


def create_registration(event_id, school_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_student_registration(
            student_registration_payload(event_id, **overrides),
            make_school_liaison_headers(school_id),
        )
    )


def move_registration(registration_id, event_id, school_id, target_status, expected_version=None):
    """Transition a registration, reading the event's live version unless pinned."""
    version = (
        expected_version
        if expected_version is not None
        else event_version(event_id, school_id)
    )
    return api_client.transition_student_registration(
        registration_id,
        {
            "target_status": target_status,
            "expected_distribution_event_version": version,
        },
        make_school_liaison_headers(school_id),
    )


def verify_registration(registration_id, event_id, school_id) -> dict:
    return get_success_data(move_registration(registration_id, event_id, school_id, "VERIFIED"))


def confirm_registration(registration_id, event_id, school_id) -> dict:
    return get_success_data(move_registration(registration_id, event_id, school_id, "CONFIRMED"))


def waitlist_registration(registration_id, event_id, school_id) -> dict:
    return get_success_data(move_registration(registration_id, event_id, school_id, "WAITLISTED"))


def read_registration(registration_id) -> dict:
    return get_success_data(api_client.get_student_registration(registration_id, PD))


def create_verified_registration(event_id, school_id, **overrides) -> dict:
    reg = create_registration(event_id, school_id, **overrides)
    return verify_registration(reg["id"], event_id, school_id)


def create_confirmed_registration(event_id, school_id, **overrides) -> dict:
    reg = create_verified_registration(event_id, school_id, **overrides)
    return confirm_registration(reg["id"], event_id, school_id)


# --------------------------------------------------------------------------
# Tier 6: teacher supplemental requests
# --------------------------------------------------------------------------


def create_teacher_request(school_id, cycle_id, supply_item_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_teacher_request(
            teacher_request_payload(school_id, cycle_id, supply_item_id, **overrides),
            make_school_liaison_headers(school_id),
        )
    )


def move_teacher_request(request_id, target_status, headers=PD):
    return api_client.transition_teacher_request(
        request_id, {"target_status": target_status}, headers
    )


# --------------------------------------------------------------------------
# Tier 7: volunteer sessions
# --------------------------------------------------------------------------


def create_volunteer_event(site_id, **overrides):
    """Raw create; returns the response so collision tests can read the error."""
    return api_client.create_volunteer_event(
        volunteer_event_payload(site_id, **overrides), make_site_coordinator_headers(site_id)
    )


def create_scheduled_session(site_id, **overrides) -> dict:
    return get_success_data(create_volunteer_event(site_id, **overrides))


def move_volunteer_event(site_id, event_id, target_status, **extra):
    payload = {"target_status": target_status}
    payload.update(extra)
    return api_client.transition_volunteer_event(
        event_id, payload, make_site_coordinator_headers(site_id)
    )


# --------------------------------------------------------------------------
# Tier 8: whole-program scenarios shared by many claims
# --------------------------------------------------------------------------


class Program(dict):
    """Attribute-style access over a scenario's captured ids."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc


def setup_backpack_program(
    backpack_on_hand=2,
    seat_capacity=10,
    publish_event=True,
    student_target_count=100,
    title_i_pct=0.80,
    max_concurrent_seats=120,
    grade_band="K_2",
    qty_per_student=1,
    cadence="BACK_TO_SCHOOL",
    event_window_start=EVENT_WINDOW_START,
    event_window_end=EVENT_WINDOW_END,
):
    """ACTIVE school + PUBLISHED one-backpack needs list + COLLECTING cycle with
    stock on hand + a distribution event (published by default)."""
    school = create_active_school(
        title_i_pct=title_i_pct, max_concurrent_seats=max_concurrent_seats
    )
    backpack = create_backpack()
    spec = create_published_spec(
        school["id"],
        [(backpack["id"], qty_per_student)],
        grade_band=grade_band,
        student_target_count=student_target_count,
    )
    cycle = create_collecting_cycle(cadence=cadence)
    position = None
    if backpack_on_hand:
        position = adjust_inventory(cycle["id"], backpack["id"], backpack_on_hand)
    event = create_event(
        school["id"],
        cycle["id"],
        grade_band=grade_band,
        seat_capacity=seat_capacity,
        window_start=event_window_start,
        window_end=event_window_end,
    )
    if publish_event:
        event = get_success_data(move_event(event["id"], school["id"], "PUBLISHED"))
    return Program(
        school=school,
        school_id=school["id"],
        backpack=backpack,
        backpack_id=backpack["id"],
        spec=spec,
        spec_id=spec["id"],
        cycle=cycle,
        cycle_id=cycle["id"],
        position=position,
        position_id=position["id"] if position else None,
        event=event,
        event_id=event["id"],
    )


def setup_three_line_program(
    pencil_on_hand,
    notebook_on_hand,
    backpack_on_hand,
    seat_capacity=20,
    publish_event=True,
    title_i_pct=0.80,
    student_target_count=100,
):
    """ACTIVE school with a PUBLISHED K_2 needs list of 4 pencils, 2 notebooks and
    1 backpack per student, a COLLECTING cycle stocked by opening cycle counts,
    and a distribution event."""
    school = create_active_school(title_i_pct=title_i_pct)
    pencil = create_pencil()
    notebook = create_notebook()
    backpack = create_backpack()
    spec = create_published_spec(
        school["id"],
        [(pencil["id"], 4), (notebook["id"], 2), (backpack["id"], 1)],
        student_target_count=student_target_count,
    )
    cycle = create_collecting_cycle()
    pencil_pos = adjust_inventory(cycle["id"], pencil["id"], pencil_on_hand)
    notebook_pos = adjust_inventory(cycle["id"], notebook["id"], notebook_on_hand)
    backpack_pos = adjust_inventory(cycle["id"], backpack["id"], backpack_on_hand)
    event = create_event(school["id"], cycle["id"], seat_capacity=seat_capacity)
    if publish_event:
        event = get_success_data(move_event(event["id"], school["id"], "PUBLISHED"))
    return Program(
        school=school,
        school_id=school["id"],
        pencil=pencil,
        pencil_id=pencil["id"],
        notebook=notebook,
        notebook_id=notebook["id"],
        backpack=backpack,
        backpack_id=backpack["id"],
        spec=spec,
        spec_id=spec["id"],
        cycle=cycle,
        cycle_id=cycle["id"],
        pencil_position=pencil_pos,
        notebook_position=notebook_pos,
        backpack_position=backpack_pos,
        event=event,
        event_id=event["id"],
    )


def setup_supplemental_budget(unrestricted_cents=50_000, cadence="BACK_TO_SCHOOL"):
    """ACTIVE school + pencil catalogue item + COLLECTING cycle carrying one
    UNRESTRICTED gift, which is what fixes supplemental_cap_cents."""
    school = create_active_school()
    pencil = create_pencil()
    cycle = create_collecting_cycle(cadence=cadence)
    gift = create_cash_gift(
        cycle["id"], amount_cents=unrestricted_cents, restriction_type="UNRESTRICTED"
    )
    return Program(
        school=school,
        school_id=school["id"],
        pencil=pencil,
        pencil_id=pencil["id"],
        cycle=cycle,
        cycle_id=cycle["id"],
        gift=gift,
        gift_id=gift["id"],
    )


def setup_site_with_scheduled_session(
    window_start="2026-08-05T09:00:00Z",
    window_end="2026-08-05T15:30:00Z",
    volunteer_count=8,
    bin_capacity=10,
):
    """COLLECTING cycle + ACTIVE retail site already occupied by one SCHEDULED
    assembly session."""
    cycle = create_collecting_cycle()
    site = create_active_site(cycle["id"], bin_capacity=bin_capacity)
    session = create_scheduled_session(
        site["id"],
        event_type="ASSEMBLY",
        window_start=window_start,
        window_end=window_end,
        volunteer_count=volunteer_count,
        minor_volunteer_count=0,
        adult_supervisor_count=1,
    )
    return Program(
        cycle=cycle,
        cycle_id=cycle["id"],
        site=site,
        site_id=site["id"],
        session=session,
        session_id=session["id"],
    )


def setup_funded_purchase_order(
    requested_unit_gap=24, unrestricted_cents=20_000, item=None, cycle=None
):
    """COLLECTING cycle with an UNRESTRICTED gift and one DRAFT purchase order."""
    cycle = cycle or create_collecting_cycle()
    item = item or create_pencil()
    gift = create_cash_gift(
        cycle["id"], amount_cents=unrestricted_cents, restriction_type="UNRESTRICTED"
    )
    order = create_purchase_order(
        cycle["id"], item["id"], requested_unit_gap=requested_unit_gap
    )
    return Program(
        cycle=cycle,
        cycle_id=cycle["id"],
        item=item,
        item_id=item["id"],
        gift=gift,
        gift_id=gift["id"],
        order=order,
        order_id=order["id"],
    )


def setup_three_active_partners():
    """Three ACTIVE schools, each carrying one PUBLISHED needs list - the
    condition that switches the per-school supplemental sub-cap on."""
    backpack = create_backpack()
    pencil = create_pencil()
    schools = []
    for name, band, target, title_i in (
        ("Lincoln Elementary", "K_2", 100, 0.80),
        ("Garfield Middle", "G6_8", 80, 0.60),
        ("Roosevelt High", "G9_12", 120, 0.40),
    ):
        school = create_active_school(name=name, title_i_pct=title_i)
        create_published_spec(
            school["id"], [(backpack["id"], 1)], grade_band=band, student_target_count=target
        )
        schools.append(school)
    return Program(backpack=backpack, pencil=pencil, pencil_id=pencil["id"], schools=schools)
