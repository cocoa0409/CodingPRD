"""Access-control corners: role exclusivity probed with otherwise-valid requests
so only rung 2 can answer, and the two identity-scoping families where the role is
permitted and only the `X-User-ID`-to-resource comparison of rung 7 can refuse.
"""

from test_helpers import (
    ApiErrorId,
    assert_list_count,
    assert_state_pair,
    make_compliance_headers,
    make_guest_headers,
    make_therapist_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx

RBAC_CLOCK = "2026-08-09T09:00:00.000Z"
# Exactly 120 minutes after the clock, so the booking clears the lead-time rung.
SERVICE_START_AT = "2026-08-09T11:00:00.000Z"
ARRIVAL_CLOCK = "2026-08-09T11:00:00.000Z"
SHIFT_BLOCK = {"start_at": SERVICE_START_AT, "end_at": "2026-08-09T18:00:00.000Z"}

DRY60_TYPE = {
    "code": "DRY60",
    "name": "Signature Dry Massage",
    "duration_minutes": 60,
    "room_class_required": "DRY",
    "required_skill_code": "SWEDISH",
    "required_scope_level": "BASIC",
    "base_price_cents": 18000,
    "retail_product_line": "BODY",
    "contraindication_codes": None,
    "high_demand": None,
}
DRY_ROOM = {"room_class": "DRY", "turnover_buffer_minutes": 15,
            "hourly_fixed_cost_cents": 2500}
SWEDISH_BASIC = {"skill_code": "SWEDISH", "scope_level": "BASIC"}
NO_LOYALTY = {"loyalty_tier": None}
BODY_RETAIL = {"product_sku": "BODY-OIL-01", "product_line": "BODY",
               "amount_cents": 6000}


def _rbac_world(therapist_names=("RBAC Therapist",), guest_name="RBAC Guest",
                resort_room_number="2601"):
    """A DRY60 menu item in one DRY room, credentialled therapists on an
    AVAILABLE block covering the 11:00 slot, and a guest whose intake form is
    already SCREENED_CLEAR."""
    return fx.build_world(
        room_codes=("DRY-1",),
        therapist_names=therapist_names,
        clock=RBAC_CLOCK,
        treatment_type_overrides=DRY60_TYPE,
        room_overrides=DRY_ROOM,
        certification_overrides=SWEDISH_BASIC,
        guest_overrides=dict(NO_LOYALTY, full_name=guest_name,
                             resort_room_number=resort_room_number),
        shift_block_overrides=SHIFT_BLOCK)


def _book(world, therapist_id=None, headers=None):
    return validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, SERVICE_START_AT,
                              therapist_id or world.therapist_id),
        headers or fx.COORDINATOR), 201)


# ---------------------------------------------------------------------------
# exclusive_operations_are_refused_to_every_other_role
# ---------------------------------------------------------------------------

DRY2_ROOM_PAYLOAD = dict(DRY_ROOM, code="DRY-2", capacity_guests=1)


def test_the_director_only_inventory_writes_are_refused_to_every_other_role():
    """Room registration, room status change and therapist registration answer 403
    to the officer, the coordinator and the therapist alike, and create nothing.

    PRD §2.7 rung 2: "**Role authorisation** — `X-User-Role` is one of the five
    roles and that role is authorised for the endpoint. Applies to every endpoint.
    Violation: `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.1: "A recognised role that is not listed as authorised for the requested
    operation — and likewise an unrecognised role string — is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.1: "A `SpaDirector` is spa leadership: it owns the treatment menu, the
    room inventory, the therapist roster, clinical overrides, final settlements and
    the revenue and utilisation reports."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    world = _rbac_world()
    therapist_headers = make_therapist_headers(world.therapist_id)

    for label, headers in (("ComplianceOfficer",
                            make_compliance_headers(fx.CO_SUBMIT)),
                           ("SpaCoordinator", fx.COORDINATOR),
                           ("Therapist", therapist_headers)):
        refused = api_client.create_treatment_room(
            f.treatment_room_payload(**DRY2_ROOM_PAYLOAD), headers)
        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert refused.status_code == 403, (
            f"{label} must be refused on rung 2, got {refused.status_code}")

    patched = api_client.patch_treatment_room(
        world.room_id, {"status": "MAINTENANCE"}, fx.COORDINATOR)
    validate_error(patched, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert world.fetch_room()["status"] == "ACTIVE", (
        "the refused PATCH left the room ACTIVE")

    sneaky = api_client.create_therapist(
        f.therapist_payload(full_name="Sneaky Therapist",
                            commission_tier="JUNIOR"),
        therapist_headers)
    validate_error(sneaky, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # The only room that exists is the one the director registered; a second
    # DRY-2 registration would now have to answer 201, and does.
    second = validate_success(api_client.create_treatment_room(
        f.treatment_room_payload(**DRY2_ROOM_PAYLOAD), fx.DIRECTOR), 201)
    assert second["code"] == "DRY-2", (
        "the three refusals never created DRY-2, so the director's own "
        "registration is not a duplicate")


def test_the_role_rung_outranks_the_state_rung_on_the_intake_endpoints():
    """Screening as director and overriding as officer are refused for the role,
    not for the state, although the form is already SCREENED_CLEAR.

    PRD §2.7: "The server walks the ladder from the top and returns the error of
    the **first** rung the request violates; lower rungs are not evaluated once a
    rung has failed."

    PRD §2.1: "A `ComplianceOfficer` is the licensing, continuing-education and
    clinical-screening authority: it submits and reviews licences (never the same
    licence), records continuing-education courses, grants and revokes skill
    certifications, and screens intake forms."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    world = _rbac_world()
    assert world.intake["status"] == "SCREENED_CLEAR", (
        "the state rung would fire second if the role rung ever let it through")

    screened = api_client.screen_intake_form(world.intake["id"], {}, fx.DIRECTOR)
    validate_error(screened, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert screened.json()["data"]["error_id"] != \
        ApiErrorId.ERR_INVALID_INTAKE_STATE.value, (
        "rung 2 answers before rung 9 is ever evaluated")

    overridden = api_client.override_intake_form(
        world.intake["id"], f.override_payload("not my job"),
        make_compliance_headers(fx.CO_SCREEN))
    validate_error(overridden, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    form = validate_success(api_client.get_intake_form(
        world.intake["id"], fx.DIRECTOR))
    assert form["status"] == "SCREENED_CLEAR"
    assert form["overridden_by_user_id"] is None, (
        "the refused override recorded no overriding user")
    assert form["screened_by_user_id"] == fx.CO_SCREEN, (
        "the refused re-screening did not overwrite the original screener")
    assert form["version"] == world.intake["version"], (
        "neither refusal mutated the form")


def test_the_front_desk_and_therapist_transitions_refuse_across_the_boundary():
    """Confirm, start, settlement and no-show each admit exactly one role, and the
    coordinator's legal confirm is the only write that lands.

    PRD §2.1: "A `SpaCoordinator` runs front-desk operations: booking, confirming,
    checking in, cancelling and no-showing appointments, publishing shift blocks,
    registering guests, and resolving retail recommendations on a guest's behalf."

    PRD §2.1: "A `Therapist` is a licensed service provider who starts and
    completes only their own appointments and recommends retail products on them."

    PRD §2.7 rung 8: "**Optimistic concurrency** — the submitted expected-version
    field equals the parent resource's current `version`. Applies to intake-form
    creation and final-settlement creation. Violation: `ERR_STALE_GUEST_VERSION` or
    `ERR_STALE_APPOINTMENT_VERSION` (412)."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    world = _rbac_world()
    # Booked by the Guest role, which proves POST /appointments is shared.
    appointment = _book(world, headers=make_guest_headers(world.guest_id))
    appointment_id = appointment["id"]

    validate_error(
        api_client.confirm_appointment(appointment_id, {}, fx.DIRECTOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    validate_error(
        api_client.start_appointment(appointment_id, {}, fx.COORDINATOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    # The expected version is the appointment's current one, so nothing but the
    # role rung can explain this refusal.
    validate_error(
        api_client.create_settlement(
            appointment_id, f.settlement_payload(appointment["version"]),
            fx.COORDINATOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    validate_error(
        api_client.no_show_appointment(appointment_id, {},
                                       make_guest_headers(world.guest_id)),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    confirmed = fx.confirm(appointment_id)
    assert_state_pair(confirmed, "CONFIRMED", "CLEARED")

    stored = world.fetch_appointment(appointment_id)
    assert_state_pair(stored, "CONFIRMED", "CLEARED")
    assert stored["gratuity_cents"] == 0, "no refused probe posted a gratuity"
    assert stored["version"] == appointment["version"] + 1, (
        "exactly one write landed: the coordinator's confirm")
    assert_list_count(api_client.list_settlements(appointment_id, fx.DIRECTOR), 0,
                      "settlements after the refused coordinator settlement")


# ---------------------------------------------------------------------------
# guest_identity_scoping_on_shared_guest_endpoints
# ---------------------------------------------------------------------------

STRANGER_NAME = "Stranger Guest"
STRANGER_ROOM_NUMBER = "2702"


def _guest_scoping_world():
    """G1 owns a screened intake form, an in-service appointment and a RECOMMENDED
    retail attachment on it; G2 owns nothing but an identity."""
    world = _rbac_world(therapist_names=("Scoping Therapist",),
                        guest_name="Owner Guest", resort_room_number="2701")
    stranger = fx.create_guest(full_name=STRANGER_NAME,
                               resort_room_number=STRANGER_ROOM_NUMBER,
                               **NO_LOYALTY)
    appointment = _book(world)
    fx.confirm(appointment["id"])
    fx.set_clock(ARRIVAL_CLOCK)
    fx.check_in(appointment["id"])
    fx.start_service(appointment["id"], world.therapist_id)
    attachment = validate_success(api_client.create_retail_attachment(
        appointment["id"], f.retail_attachment_payload(**BODY_RETAIL),
        make_therapist_headers(world.therapist_id)), 201)
    return world, stranger, appointment["id"], attachment


def test_every_shared_guest_endpoint_scopes_to_the_owning_guest():
    """Eight calls a `Guest` is authorised to make are refused on identity alone —
    including the two whose path never names a guest.

    PRD §2.7 rung 7: "**Resource ownership** — a `Guest` caller's `X-User-ID` equals
    the guest the resource hangs off, and a `Therapist` caller's `X-User-ID` equals
    the appointment's `therapist_id`. Applies to every endpoint whose
    authorised-role list includes `Guest` or `Therapist`. Violation:
    `ERR_NOT_RESOURCE_OWNER` (403)."

    PRD §2.1: "When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting
    `Guest` entity; a `Guest` caller may act only on resources that hang off that
    guest — their own intake forms, their own appointments, the retail attachments
    and folio postings of those appointments, and their own guest record."

    PRD §2.1: "An ownership violation by a `Guest` or `Therapist` caller is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/guest_identity_scoping_on_shared_guest_endpoints
    """
    world, stranger, appointment_id, attachment = _guest_scoping_world()
    intruder = make_guest_headers(stranger["id"])
    owner_id = world.guest_id
    intake_id = world.intake["id"]

    probes = (
        ("read the guest record", api_client.get_guest(owner_id, intruder)),
        ("list the intake forms",
         api_client.list_intake_forms(owner_id, intruder)),
        ("read one intake form", api_client.get_intake_form(intake_id, intruder)),
        ("read one appointment",
         api_client.get_appointment(appointment_id, intruder)),
        ("cancel the appointment",
         api_client.cancel_appointment(
             appointment_id, f.cancel_payload("not my booking"), intruder)),
        ("resolve the attachment",
         api_client.resolve_retail_attachment(
             attachment["id"], f.resolve_payload("PURCHASED"), intruder)),
        ("list the folio charges",
         api_client.list_guest_folio_charges(owner_id, intruder)),
    )
    for label, response in probes:
        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        assert response.status_code == 403, (
            f"{label}: the resource exists and the role is permitted, so the "
            f"answer is 403 and never 404, got {response.status_code}")

    # The version G2 carries is two writes stale — the form creation and the
    # screening each bumped G1 — yet rung 7 answers before rung 8 is reached.
    written = api_client.create_intake_form(
        owner_id, f.intake_form_payload(world.guest["version"],
                                        condition_codes=["ACTIVE_INFECTION"]),
        intruder)
    error = validate_error(written, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_STALE_GUEST_VERSION.value, (
        "the ownership rung outranks the optimistic-concurrency rung")

    owner = make_guest_headers(owner_id)
    assert_list_count(api_client.list_intake_forms(owner_id, owner), 1,
                      "intake forms after the refused G2 creation")
    stored = world.fetch_appointment(appointment_id)
    assert_state_pair(stored, "IN_SERVICE", "CLEARED")
    assert stored["cancellation_charge_cents"] == 0, (
        "the refused cancellation charged nothing")
    rows = assert_list_count(
        api_client.list_retail_attachments(appointment_id, fx.DIRECTOR), 1,
        "retail attachments after the refused G2 resolve")
    assert rows[0]["status"] == "RECOMMENDED"
    assert rows[0]["resolved_by_user_id"] is None, (
        "the refused resolve recorded no resolving user")


def test_the_owning_guest_makes_the_same_calls_successfully():
    """Identical requests, identical paths, one different `X-User-ID`: the owner is
    served the nested attachment list and the folio posting made at check-in.

    PRD §2.1: "When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting
    `Guest` entity; a `Guest` caller may act only on resources that hang off that
    guest — their own intake forms, their own appointments, the retail attachments
    and folio postings of those appointments, and their own guest record."

    PRD §4: "Checks the guest in, cutting the provisional settlement and posting the
    treatment charge to the folio."

    PRD §3.6: "It then posts a folio charge of `kind` `TREATMENT` whose
    `amount_cents` is that row's `folio_total_cents`".

    Design: Corner/rbac/guest_identity_scoping_on_shared_guest_endpoints
    """
    world, _stranger, appointment_id, attachment = _guest_scoping_world()
    owner = make_guest_headers(world.guest_id)

    attachments = assert_list_count(
        api_client.list_retail_attachments(appointment_id, owner), 1,
        "the owner's own view of the attachment list")
    assert attachments[0]["id"] == attachment["id"]
    assert attachments[0]["status"] == "RECOMMENDED"

    charges = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, owner), 1,
        "the owner's own folio")
    assert charges[0]["kind"] == "TREATMENT", (
        f"check-in posts the treatment charge, got {charges[0]['kind']}")
    appointment = validate_success(
        api_client.get_appointment(appointment_id, owner))
    assert appointment["id"] == appointment_id, (
        "the owner reads their own appointment")
    provisional = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR,
                                    params={"variant": "PROVISIONAL"}),
        1, "the provisional row cut at check-in")[0]
    assert charges[0]["amount_cents"] == provisional["folio_total_cents"], (
        "the treatment posting carries the provisional row's folio_total_cents")
    assert charges[0]["appointment_id"] == appointment_id

    assert validate_success(api_client.get_guest(world.guest_id, owner))["id"] == \
        world.guest_id
    assert validate_success(api_client.get_intake_form(
        world.intake["id"], owner))["status"] == "SCREENED_CLEAR"


# ---------------------------------------------------------------------------
# therapist_identity_scoping_on_service_and_self_read_endpoints
# ---------------------------------------------------------------------------

T1 = "Therapist One"
T2 = "Therapist Two"
SERVICE_DURATION_MINUTES = 60


def _therapist_scoping_world():
    """Two equally credentialled therapists on the same AVAILABLE block, and one
    CHECKED_IN appointment assigned to T1."""
    world = _rbac_world(therapist_names=(T1, T2),
                        guest_name="Therapist Scoping Guest",
                        resort_room_number="2801")
    appointment = _book(world, therapist_id=world.therapist_of(T1))
    fx.confirm(appointment["id"])
    fx.set_clock(ARRIVAL_CLOCK)
    world.appointments["a"] = fx.check_in(appointment["id"])
    return world


def test_the_unassigned_therapist_can_neither_start_nor_read_the_service():
    """T2 is ACTIVE, VERIFIED, certified for SWEDISH and on shift for the same
    window, so only `therapist_id` can explain the four refusals.

    PRD §2.7 rung 7: "**Resource ownership** — a `Guest` caller's `X-User-ID` equals
    the guest the resource hangs off, and a `Therapist` caller's `X-User-ID` equals
    the appointment's `therapist_id`. Applies to every endpoint whose
    authorised-role list includes `Guest` or `Therapist`. Violation:
    `ERR_NOT_RESOURCE_OWNER` (403)."

    PRD §2.1: "When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the
    acting `Therapist` entity; ownership checks on any resource that references a
    therapist compare that resource's therapist reference to `X-User-ID`."

    PRD §2.1: "Concretely, a `Therapist` caller may act on an appointment only when
    `X-User-ID` equals that appointment's `therapist_id`."

    Design: Corner/rbac/therapist_identity_scoping_on_service_and_self_read_endpoints
    """
    world = _therapist_scoping_world()
    appointment_id = world.appointments["a"]["id"]
    one_id = world.therapist_of(T1)
    intruder = make_therapist_headers(world.therapist_of(T2))

    assert world.fetch_therapist(T2)["status"] == "ACTIVE", (
        "T2's own standing is impeccable; only the assignment differs")

    for label, response in (
            ("start the service",
             api_client.start_appointment(appointment_id, {}, intruder)),
            ("read the appointment",
             api_client.get_appointment(appointment_id, intruder)),
            ("read the assigned therapist",
             api_client.get_therapist(one_id, intruder)),
            ("list the assigned therapist's shift blocks",
             api_client.list_shift_blocks(one_id, intruder))):
        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        assert response.status_code == 403, (
            f"{label}: refused on identity, got {response.status_code}")

    held = world.fetch_appointment(appointment_id)
    assert_state_pair(held, "CHECKED_IN", "CLEARED")
    assert held["started_at"] is None, "the refused start set no started_at"

    owner = make_therapist_headers(one_id)
    started = validate_success(api_client.start_appointment(
        appointment_id, {}, owner))
    assert_state_pair(started, "IN_SERVICE", "CLEARED")
    assert started["started_at"] is not None, (
        "T1's start is a legal CHECKED_IN to IN_SERVICE transition")
    assert validate_success(api_client.get_therapist(one_id, owner))["id"] == one_id
    assert_list_count(api_client.list_shift_blocks(one_id, owner), 1,
                      "T1's own shift blocks")


def test_the_unassigned_therapist_cannot_attach_list_or_consume_the_completion():
    """T2's attachment create, attachment list and completion are all refused, and
    T1's identical calls all land.

    PRD §2.7 rung 7: "**Resource ownership** — a `Guest` caller's `X-User-ID` equals
    the guest the resource hangs off, and a `Therapist` caller's `X-User-ID` equals
    the appointment's `therapist_id`. Applies to every endpoint whose
    authorised-role list includes `Guest` or `Therapist`. Violation:
    `ERR_NOT_RESOURCE_OWNER` (403)."

    PRD §4: "The assigned therapist recommends a retail product from `product_sku`,
    `product_line` and `amount_cents`; the line must match the treatment's
    `retail_product_line`."

    PRD §4: "The assigned therapist reports `actual_duration_minutes` and an optional
    `gratuity_cents`, setting `completed_at`. No settlement is cut here."

    Design: Corner/rbac/therapist_identity_scoping_on_service_and_self_read_endpoints
    """
    world = _therapist_scoping_world()
    appointment_id = world.appointments["a"]["id"]
    owner = make_therapist_headers(world.therapist_of(T1))
    intruder = make_therapist_headers(world.therapist_of(T2))
    fx.start_service(appointment_id, world.therapist_of(T1))

    validate_error(
        api_client.create_retail_attachment(
            appointment_id, f.retail_attachment_payload(**BODY_RETAIL), intruder),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    attachment = validate_success(api_client.create_retail_attachment(
        appointment_id, f.retail_attachment_payload(**BODY_RETAIL), owner), 201)
    assert attachment["status"] == "RECOMMENDED"

    validate_error(api_client.list_retail_attachments(appointment_id, intruder),
                   ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    rows = assert_list_count(
        api_client.list_retail_attachments(appointment_id, owner), 1,
        "T1's own view of the attachments they recommended")
    assert rows[0]["id"] == attachment["id"]

    validate_error(
        api_client.complete_appointment(
            appointment_id, f.complete_payload(SERVICE_DURATION_MINUTES, 0),
            intruder),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    mid_service = validate_success(
        api_client.get_appointment(appointment_id, owner))
    assert_state_pair(mid_service, "IN_SERVICE", "CLEARED")
    assert mid_service["completed_at"] is None, (
        "T2's refusal consumed no part of the completion")

    completed = validate_success(api_client.complete_appointment(
        appointment_id, f.complete_payload(SERVICE_DURATION_MINUTES, 0), owner))
    assert completed["schedule_status"] == "COMPLETED"
    assert completed["actual_duration_minutes"] == SERVICE_DURATION_MINUTES
    assert completed["completed_at"] is not None
    repeated = api_client.complete_appointment(
        appointment_id, f.complete_payload(SERVICE_DURATION_MINUTES, 0), owner)
    validate_error(repeated, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)
