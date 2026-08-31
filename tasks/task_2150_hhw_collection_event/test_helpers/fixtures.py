"""Composite setup helpers.

Almost every rule in this contract only becomes observable once the programme
is parked at a precise point of the collection-day pipeline, and reaching that
point costs between two and thirty-two API calls. `setup_canon(n)` walks the
canonical pipeline and stops after step `n`, so a test can name the exact state
it needs:

     1  programme (budget 40000000, ceiling 500000, rate 4200)   -> program
     2  candidate site (impervious, 2000 L, 15.0 m, 4 lanes)     -> site
     3  site APPROVE by the site-approving inspector             [APPROVED]
     4  material category LATEX_PAINT (TOXIC, 155 cents/kg)      -> category
     5  collection event 2026-09-12T08:00Z..20:00Z               -> event   [PLANNED]
     6  event CONFIRM_SITE                                       [SITE_CONFIRMED]
     7  staffer Dana Reyes (HAZWOPER 2027-06-30)                 -> staffer
     8  lane assignment lane 1, 08:00..20:00 (12.00 h)           -> lane
     9  event-day inspection PASS by the day-of inspector        [COMPLIANT, capacity 48]
    10  event OPEN_REGISTRATION                                  [OPEN_FOR_REGISTRATION]
    11  resident Ana Ruiz (CO-ARV)                               -> resident
    12  resident VERIFY CO-ARV                                   [ELIGIBLE]
    13  appointment 09:00 slot, HOUSEHOLD, 18.5 kg               -> appointment [REQUESTED]
    14  appointment CONFIRM                                      [CONFIRMED]
    15  logical clock -> 2026-09-12T09:00Z
    16  event START                                              [IN_PROGRESS]
    17  appointment CHECK_IN                                     [CHECKED_IN]
    18  appointment START_UNLOAD                                 [UNLOADING]
    19  dropoff line 1.5 kg latex                                -> lines[0]
    20  dropoff line 2.5 kg latex                                -> lines[1]
    21  dropoff line 0.5 kg latex                                -> lines[2]
    22  appointment COMPLETE_UNLOAD                              [COMPLETED]
    23  container DRUM-A1 (TOXIC, 200 kg)                        -> container [OPEN]
    24  pack line 1
    25  pack line 2
    26  pack line 3                                              [estimate 699]
    27  container SEAL                                           [SEALED]
    28  read the event's current version                         -> event_version
    29  manifest MAN-0001 over DRUM-A1                           -> manifest [DRAFT]
    30  manifest SIGN                                            [SIGNED]
    31  manifest SHIP                                            [SHIPPED]
    32  manifest RECEIVE                                         [RECEIVED, invoice 698]

Every step uses the lenient setup validator so a broken precondition reports
"Setup step failed" rather than an obscure KeyError.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LATEX, TEST_DEFAULTS
from .factories import (
    create_appointment_payload,
    create_container_payload,
    create_dropoff_line_payload,
    create_event_payload,
    create_lane_assignment_payload,
    create_manifest_payload,
    create_material_category_payload,
    create_program_payload,
    create_resident_payload,
    create_site_payload,
    create_staffer_payload,
)
from .test_users import (
    ADMIN,
    ANONYMOUS,
    CLERK,
    CONTRACTOR,
    COORDINATOR,
    INSPECTOR,
    SITE_APPROVER,
    TECH,
)


# ─── Granular steps ───────────────────────────────────

def set_clock(instant: str, headers=ADMIN) -> dict:
    """Move the server's logical clock. Mutates no entity."""
    return get_success_data(api_client.set_clock({"to_iso8601": instant}, headers))


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def create_site(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_site(create_site_payload(program_id, **overrides), COORDINATOR)
    )


def site_action(site_id: str, action: str, headers=SITE_APPROVER, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(api_client.site_transition(site_id, body, headers))


def approve_site(site_id: str, headers=SITE_APPROVER, finding_code="PAD-OK") -> dict:
    return site_action(site_id, "APPROVE", headers, finding_code=finding_code)


def create_approved_site(program_id: str, headers=SITE_APPROVER, **overrides) -> dict:
    site = create_site(program_id, **overrides)
    return approve_site(site["id"], headers)


def create_category(program_id: str, spec=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_material_category(
            create_material_category_payload(program_id, spec or LATEX, **overrides),
            ADMIN,
        )
    )


def create_event(program_id: str, site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_event(
            create_event_payload(program_id, site_id, **overrides), COORDINATOR
        )
    )


def event_action(event_id: str, action: str, headers=COORDINATOR, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(api_client.event_transition(event_id, body, headers))


def inspect_event(event_id: str, result: str, headers=INSPECTOR, **payload) -> dict:
    body = {"result": result}
    body.update(payload)
    return get_success_data(
        api_client.file_containment_inspection(event_id, body, headers)
    )


def create_staffer(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_staffer(create_staffer_payload(program_id, **overrides), COORDINATOR)
    )


def assign_lane(event_id: str, staffer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lane_assignment(
            create_lane_assignment_payload(event_id, staffer_id, **overrides), COORDINATOR
        )
    )


def release_lane(assignment_id: str, released_reason="ROSTER_CHANGE") -> dict:
    body = {} if released_reason is None else {"released_reason": released_reason}
    return get_success_data(
        api_client.release_lane_assignment(assignment_id, body, COORDINATOR)
    )


def register_resident(program_id: str, headers=ANONYMOUS, **overrides) -> dict:
    return get_success_data(
        api_client.create_resident(create_resident_payload(program_id, **overrides), headers)
    )


def resident_action(resident_id: str, action: str, headers=CLERK, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.resident_eligibility_action(resident_id, body, headers)
    )


def verify_resident(resident_id: str, verified_jurisdiction_code: str) -> dict:
    return resident_action(
        resident_id, "VERIFY", verified_jurisdiction_code=verified_jurisdiction_code
    )


def create_eligible_resident(program_id: str, jurisdiction="CO-ARV", **overrides) -> dict:
    """Register and verify a resident into ELIGIBLE. Returns the verified row,
    whose `version` is the value an appointment booking must quote back."""
    resident = register_resident(
        program_id, claimed_jurisdiction_code=jurisdiction, **overrides
    )
    return verify_resident(resident["id"], jurisdiction)


def book_appointment(
    event_id: str, resident: dict, category_ids, headers=CLERK, **overrides
) -> dict:
    """Book against the resident's currently observed `version`."""
    payload = create_appointment_payload(
        event_id, resident["id"], resident["version"], category_ids, **overrides
    )
    return get_success_data(api_client.create_appointment(payload, headers))


def appointment_action(
    appointment_id: str, action: str, headers=CLERK, **payload
) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.appointment_transition(appointment_id, body, headers)
    )


def record_line(
    appointment_id: str, category_id: str, net_weight_kg, declared_kg=None, headers=TECH
) -> dict:
    payload = create_dropoff_line_payload(
        appointment_id, category_id, net_weight_kg, declared_kg
    )
    return get_success_data(api_client.create_dropoff_line(payload, headers))


def open_container(event_id: str, headers=CONTRACTOR, **overrides) -> dict:
    return get_success_data(
        api_client.create_container(create_container_payload(event_id, **overrides), headers)
    )


def pack_line(container_id: str, dropoff_line_id: str, headers=CONTRACTOR) -> dict:
    return get_success_data(
        api_client.pack_line(container_id, {"dropoff_line_id": dropoff_line_id}, headers)
    )


def container_action(container_id: str, action: str, headers=CONTRACTOR) -> dict:
    return get_success_data(
        api_client.container_transition(container_id, {"action": action}, headers)
    )


def prepare_manifest(
    event_id: str, container_ids, expected_event_version=None, headers=CONTRACTOR, **overrides
) -> dict:
    if expected_event_version is None:
        expected_event_version = read_event(event_id)["version"]
    payload = create_manifest_payload(
        event_id, container_ids, expected_event_version, **overrides
    )
    return get_success_data(api_client.create_manifest(payload, headers))


def manifest_action(manifest_id: str, action: str, headers=None, **payload) -> dict:
    """SIGN / RECEIVE / REJECT belong to the administrator; SHIP / REOPEN to the
    contractor. The default header follows that split."""
    if headers is None:
        headers = ADMIN if action in ("SIGN", "RECEIVE", "REJECT") else CONTRACTOR
    body = {"action": action}
    body.update(payload)
    return get_success_data(api_client.manifest_transition(manifest_id, body, headers))


# ─── Fresh reads ──────────────────────────────────────

def read_program(program_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_program(program_id, headers))


def read_cost_summary(program_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.get_cost_summary(program_id, headers))


def read_site(site_id: str, headers=COORDINATOR) -> dict:
    return get_success_data(api_client.get_site(site_id, headers))


def read_event(event_id: str, headers=COORDINATOR) -> dict:
    return get_success_data(api_client.get_event(event_id, headers))


def read_resident(resident_id: str, headers=CLERK) -> dict:
    return get_success_data(api_client.get_resident(resident_id, headers))


def read_staffer(staffer_id: str, headers=COORDINATOR) -> dict:
    return get_success_data(api_client.get_staffer(staffer_id, headers))


def read_lane_assignment(assignment_id: str, headers=COORDINATOR) -> dict:
    return get_success_data(api_client.get_lane_assignment(assignment_id, headers))


def read_appointment(appointment_id: str, headers=CLERK) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, headers))


def read_dropoff_line(line_id: str, headers=TECH) -> dict:
    return get_success_data(api_client.get_dropoff_line(line_id, headers))


def read_container(container_id: str, headers=CONTRACTOR) -> dict:
    return get_success_data(api_client.get_container(container_id, headers))


def read_manifest(manifest_id: str, headers=CONTRACTOR) -> dict:
    return get_success_data(api_client.get_manifest(manifest_id, headers))


# ─── The canonical pipeline ───────────────────────────

CANON_STEPS = 32
DEFAULT_LINE_WEIGHTS = (1.5, 2.5, 0.5)


def setup_canon(steps: int = CANON_STEPS, **opts) -> dict:
    """Walk the canonical collection-day pipeline and stop after `steps`.

    Recognised options:
      program / site / event / staffer / lane / appointment / container /
      manifest  — dicts of payload overrides for that step
      category  — the material category specification to publish
      line_weights — iterable of weighed masses for steps 19..21
      event_day_instant — the instant the clock moves to at step 15
    """
    ctx: dict = {"lines": []}

    if steps >= 1:
        ctx["program"] = create_program(**opts.get("program", {}))
        ctx["program_id"] = ctx["program"]["id"]
    if steps >= 2:
        ctx["site"] = create_site(ctx["program_id"], **opts.get("site", {}))
        ctx["site_id"] = ctx["site"]["id"]
    if steps >= 3:
        ctx["site"] = approve_site(ctx["site_id"])
    if steps >= 4:
        ctx["category"] = create_category(
            ctx["program_id"], opts.get("category", LATEX)
        )
        ctx["category_id"] = ctx["category"]["id"]
    if steps >= 5:
        ctx["event"] = create_event(
            ctx["program_id"], ctx["site_id"], **opts.get("event", {})
        )
        ctx["event_id"] = ctx["event"]["id"]
    if steps >= 6:
        ctx["event"] = event_action(ctx["event_id"], "CONFIRM_SITE")
    if steps >= 7:
        ctx["staffer"] = create_staffer(ctx["program_id"], **opts.get("staffer", {}))
        ctx["staffer_id"] = ctx["staffer"]["id"]
    if steps >= 8:
        ctx["lane"] = assign_lane(
            ctx["event_id"], ctx["staffer_id"], **opts.get("lane", {})
        )
        ctx["lane_id"] = ctx["lane"]["id"]
    if steps >= 9:
        ctx["event"] = inspect_event(ctx["event_id"], "PASS", finding_code="PAD-OK")
    if steps >= 10:
        ctx["event"] = event_action(ctx["event_id"], "OPEN_REGISTRATION")
    if steps >= 11:
        ctx["resident"] = register_resident(ctx["program_id"])
        ctx["resident_id"] = ctx["resident"]["id"]
    if steps >= 12:
        ctx["resident"] = verify_resident(ctx["resident_id"], "CO-ARV")
    if steps >= 13:
        ctx["appointment"] = book_appointment(
            ctx["event_id"],
            ctx["resident"],
            [ctx["category_id"]],
            **opts.get("appointment", {}),
        )
        ctx["appointment_id"] = ctx["appointment"]["id"]
    if steps >= 14:
        ctx["appointment"] = appointment_action(ctx["appointment_id"], "CONFIRM")
    if steps >= 15:
        set_clock(opts.get("event_day_instant", TEST_DEFAULTS["EVENT_DAY_INSTANT"]))
    if steps >= 16:
        ctx["event"] = event_action(ctx["event_id"], "START")
    if steps >= 17:
        ctx["appointment"] = appointment_action(
            ctx["appointment_id"], "CHECK_IN", headers=TECH
        )
    if steps >= 18:
        ctx["appointment"] = appointment_action(
            ctx["appointment_id"], "START_UNLOAD", headers=TECH
        )

    weights = list(opts.get("line_weights", DEFAULT_LINE_WEIGHTS))
    for index, weight in enumerate(weights):
        if steps >= 19 + index:
            ctx["lines"].append(
                record_line(ctx["appointment_id"], ctx["category_id"], weight)
            )
    if ctx["lines"]:
        ctx["line_ids"] = [line["id"] for line in ctx["lines"]]

    if steps >= 22:
        ctx["appointment"] = appointment_action(
            ctx["appointment_id"], "COMPLETE_UNLOAD", headers=TECH
        )
    if steps >= 23:
        ctx["container"] = open_container(ctx["event_id"], **opts.get("container", {}))
        ctx["container_id"] = ctx["container"]["id"]
    for index, line in enumerate(ctx["lines"]):
        if steps >= 24 + index:
            ctx["container"] = pack_line(ctx["container_id"], line["id"])
    if steps >= 27:
        ctx["container"] = container_action(ctx["container_id"], "SEAL")
    if steps >= 28:
        ctx["event_version"] = read_event(ctx["event_id"])["version"]
    if steps >= 29:
        ctx["manifest"] = prepare_manifest(
            ctx["event_id"],
            [ctx["container_id"]],
            ctx["event_version"],
            **opts.get("manifest", {}),
        )
        ctx["manifest_id"] = ctx["manifest"]["id"]
    if steps >= 30:
        ctx["manifest"] = manifest_action(ctx["manifest_id"], "SIGN")
    if steps >= 31:
        ctx["manifest"] = manifest_action(ctx["manifest_id"], "SHIP")
    if steps >= 32:
        ctx["manifest"] = manifest_action(
            ctx["manifest_id"], "RECEIVE", invoice_reference="INV-77"
        )
    return ctx


# ─── Named stopping points ────────────────────────────

def setup_approved_site(**opts) -> dict:
    """Programme plus one APPROVED site."""
    return setup_canon(3, **opts)


def setup_planned_event(**opts) -> dict:
    """Programme, approved site, published category and one PLANNED event."""
    return setup_canon(5, **opts)


def setup_compliant_event(**opts) -> dict:
    """Event SITE_CONFIRMED with a staffed lane and a COMPLIANT pad."""
    return setup_canon(9, **opts)


def setup_open_event(**opts) -> dict:
    """Event OPEN_FOR_REGISTRATION on a compliant pad."""
    return setup_canon(10, **opts)


def setup_eligible_resident(**opts) -> dict:
    """Open event plus one verified, eligible resident."""
    return setup_canon(12, **opts)


def setup_requested_appointment(**opts) -> dict:
    """Open event with one REQUESTED appointment."""
    return setup_canon(13, **opts)


def setup_confirmed_appointment(**opts) -> dict:
    """Open event with one CONFIRMED appointment holding its reservation."""
    return setup_canon(14, **opts)


def setup_unloading_appointment(**opts) -> dict:
    """Event IN_PROGRESS with the appointment at the lane, ready for weighed lines."""
    return setup_canon(18, **opts)


def setup_weighed_lines(**opts) -> dict:
    """Event IN_PROGRESS with the canonical three accepted latex lines recorded."""
    return setup_canon(21, **opts)


def setup_completed_visit(**opts) -> dict:
    """The visit driven all the way to COMPLETED."""
    return setup_canon(22, **opts)


def setup_packed_container(**opts) -> dict:
    """One OPEN container holding the three accepted lines (estimate 699)."""
    return setup_canon(26, **opts)


def setup_sealed_container(**opts) -> dict:
    """The container SEALED and its estimate encumbered against the budget."""
    return setup_canon(27, **opts)


def setup_draft_manifest(**opts) -> dict:
    """A DRAFT manifest carrying the sealed container."""
    return setup_canon(29, **opts)


def setup_shipped_manifest(**opts) -> dict:
    """The manifest SIGNED and SHIPPED, its money in transit."""
    return setup_canon(31, **opts)


def setup_received_manifest(**opts) -> dict:
    """The manifest RECEIVED and its invoice minted."""
    return setup_canon(32, **opts)


# ─── Scenario extensions ──────────────────────────────

def add_resident_with_appointment(
    ctx: dict,
    full_name="Ben Ortiz",
    jurisdiction="CO-DEN",
    declared_total_kg=12.0,
    slot_start_utc=None,
    confirm=False,
    **appointment_overrides,
) -> dict:
    """Register, verify and book a second resident at the same event.

    Returns {"resident": ..., "appointment": ...}.
    """
    resident = create_eligible_resident(
        ctx["program_id"], jurisdiction, full_name=full_name
    )
    appointment = book_appointment(
        ctx["event_id"],
        resident,
        [ctx["category_id"]],
        slot_start_utc=slot_start_utc or TEST_DEFAULTS["SECOND_SLOT_START_UTC"],
        declared_total_kg=declared_total_kg,
        **appointment_overrides,
    )
    if confirm:
        appointment = appointment_action(appointment["id"], "CONFIRM")
    return {"resident": resident, "appointment": appointment}


def setup_restricted_program(**opts) -> dict:
    """An open event whose projected cost per participant (50400 cents against a
    30000-cent ceiling) has driven the programme to RESTRICTED."""
    options = dict(opts)
    program = dict(options.pop("program", {}))
    program.setdefault("cost_per_participant_ceiling_cents", 30_000)
    return setup_canon(options.pop("steps", 13), program=program, **options)


def setup_frozen_program(**opts) -> dict:
    """Two events of one programme both deficient — enough to freeze it outright."""
    ctx = setup_canon(5, **opts)
    ctx["second_event"] = create_event(
        ctx["program_id"],
        ctx["site_id"],
        window_start_utc="2026-10-10T08:00:00.000Z",
        window_end_utc="2026-10-10T20:00:00.000Z",
    )
    ctx["second_event_id"] = ctx["second_event"]["id"]
    ctx["event"] = inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")
    ctx["program_after_one"] = read_program(ctx["program_id"])
    ctx["second_event"] = inspect_event(
        ctx["second_event_id"], "FAIL", finding_code="DRAIN-UNCOVERED"
    )
    ctx["program"] = read_program(ctx["program_id"])
    return ctx


def setup_two_confirmed_appointments(
    lane_end_utc="2026-09-12T10:00:00.000Z",
    first_kg=10.0,
    second_kg=12.0,
    **opts,
) -> dict:
    """An open event carrying two CONFIRMED appointments held by two residents.

    The lane interval is short on purpose so the staffing leg — not the pad —
    binds the event's `slot_capacity`. Returns the canonical context extended
    with "first" and "second", each {"resident": ..., "appointment": ...}.
    """
    options = dict(opts)
    lane = dict(options.pop("lane", {}))
    lane.setdefault("end_utc", lane_end_utc)
    ctx = setup_canon(10, lane=lane, **options)

    ctx["first"] = add_resident_with_appointment(
        ctx,
        full_name="Ana Ruiz",
        jurisdiction="CO-ARV",
        declared_total_kg=first_kg,
        slot_start_utc=TEST_DEFAULTS["SLOT_START_UTC"],
        confirm=True,
    )
    ctx["second"] = add_resident_with_appointment(
        ctx,
        full_name="Ben Ortiz",
        jurisdiction="CO-DEN",
        declared_total_kg=second_kg,
        slot_start_utc=TEST_DEFAULTS["SECOND_SLOT_START_UTC"],
        confirm=True,
    )
    return ctx


def setup_deficiency_cascade_scenario() -> dict:
    """Two confirmed appointments on a 30000-cent ceiling, plus a second lane
    that carries the event to 14.00 certified hours (58800 cents of staffing).

    With two reservations the projected cost per participant sits at 29400 —
    just inside the ceiling — so the programme is still OPEN. Losing both
    reservations is what pushes the projection past the ceiling.
    """
    ctx = setup_two_confirmed_appointments(
        program={"cost_per_participant_ceiling_cents": 30_000}
    )
    ctx["second_staffer"] = create_staffer(
        ctx["program_id"], full_name="Mo Chen", role_code="TRAFFIC"
    )
    ctx["second_lane"] = assign_lane(
        ctx["event_id"],
        ctx["second_staffer"]["id"],
        lane_number=2,
        start_utc=TEST_DEFAULTS["WINDOW_START_UTC"],
        end_utc=TEST_DEFAULTS["WINDOW_END_UTC"],
    )
    ctx["event"] = read_event(ctx["event_id"])
    ctx["program"] = read_program(ctx["program_id"])
    return ctx


def setup_two_class_manifest(manifest_tracking_number="MAN-0002") -> dict:
    """One SHIPPED manifest carrying two drums of different compatibility classes.

    Three latex-paint lines (1.5, 2.5 and 0.5 kg at 155 cents/kg) go into the
    TOXIC drum and one pool-acid line (0.25 kg at 480 cents/kg) into the
    CORROSIVE_ACID drum, so the two rate classes must blend at settlement.
    Returns the canonical context extended with "acid_category", "container_a",
    "container_b", "estimate_a", "estimate_b" and "manifest".
    """
    from .constants import POOL_ACID

    ctx = setup_canon(10)
    ctx["acid_category"] = create_category(ctx["program_id"], POOL_ACID)
    ctx["resident"] = create_eligible_resident(ctx["program_id"], "CO-ARV")
    ctx["resident_id"] = ctx["resident"]["id"]
    ctx["appointment"] = book_appointment(
        ctx["event_id"],
        ctx["resident"],
        [ctx["category_id"], ctx["acid_category"]["id"]],
        declared_total_kg=18.5,
    )
    ctx["appointment_id"] = ctx["appointment"]["id"]
    appointment_action(ctx["appointment_id"], "CONFIRM")
    set_clock(TEST_DEFAULTS["EVENT_DAY_INSTANT"])
    event_action(ctx["event_id"], "START")
    appointment_action(ctx["appointment_id"], "CHECK_IN", headers=TECH)
    appointment_action(ctx["appointment_id"], "START_UNLOAD", headers=TECH)

    ctx["lines"] = [
        record_line(ctx["appointment_id"], ctx["category_id"], 1.5, 6.0),
        record_line(ctx["appointment_id"], ctx["category_id"], 2.5, 8.0),
        record_line(ctx["appointment_id"], ctx["category_id"], 0.5, 4.5),
        record_line(ctx["appointment_id"], ctx["acid_category"]["id"], 0.25, 0.25),
    ]
    ctx["line_ids"] = [line["id"] for line in ctx["lines"]]
    appointment_action(ctx["appointment_id"], "COMPLETE_UNLOAD", headers=TECH)

    ctx["container_a"] = open_container(
        ctx["event_id"],
        container_code="DRUM-A1",
        compatibility_class="TOXIC",
        capacity_kg=200.0,
    )
    ctx["container_b"] = open_container(
        ctx["event_id"],
        container_code="DRUM-B1",
        compatibility_class="CORROSIVE_ACID",
        capacity_kg=100.0,
    )
    pack_line(ctx["container_a"]["id"], ctx["line_ids"][0])
    pack_line(ctx["container_a"]["id"], ctx["line_ids"][1])
    ctx["estimate_a"] = pack_line(ctx["container_a"]["id"], ctx["line_ids"][2])[
        "estimated_disposal_cost_cents"
    ]
    ctx["estimate_b"] = pack_line(ctx["container_b"]["id"], ctx["line_ids"][3])[
        "estimated_disposal_cost_cents"
    ]
    container_action(ctx["container_a"]["id"], "SEAL")
    container_action(ctx["container_b"]["id"], "SEAL")

    ctx["manifest"] = prepare_manifest(
        ctx["event_id"],
        [ctx["container_a"]["id"], ctx["container_b"]["id"]],
        manifest_tracking_number=manifest_tracking_number,
    )
    ctx["manifest_id"] = ctx["manifest"]["id"]
    manifest_action(ctx["manifest_id"], "SIGN")
    ctx["manifest"] = manifest_action(ctx["manifest_id"], "SHIP")
    return ctx
