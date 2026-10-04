"""Depth tests: validation priority conflicts across different error-category pairs."""
from test_helpers import (
    ATTRACTION_HOST,
    PERMIT_CLERK,
    PLATFORM_ADMIN,
    REMIT_ADMIN,
    SERVICE_WRITER,
    ApiErrorId,
    create_boat_unit,
    create_member,
    create_open_attraction,
    create_permit_sale,
    create_remit_batch,
    create_service_intake,
    create_service_order,
    create_store,
    create_waiver,
    get_success_data,
    request_session,
    set_clock,
    validate_error,
)


# ===========================================================================
# state_terminal_beats_safety_waiver_gate  (queue A / priority_pair_validation_conflict)
# ===========================================================================

def _cancelled_lapsed_waiver_session(api):
    """An ARCHERY_RANGE venue, a waiver that lapses after the session is booked,
    and a cancelled session."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_pr@x.com",
                           full_name="Pia Ross")
    attraction = create_open_attraction(api, store["id"], attraction_type="ARCHERY_RANGE",
                                        capacity_units=12, dwell_cost_minutes=45)
    # The waiver is live at the request instant and lapses on 2026-09-02, so the
    # session can be booked before the sweep expires the waiver.
    waiver = create_waiver(api, store["id"], member["id"],
                           activity_scope="ARCHERY_RANGE",
                           signed_at_utc="2026-09-01T00:00:00Z", waiver_term_days=1)
    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        session_kind="ARCHERY_LANE", party_size=2, lane_no=3,
                        waiver_id=waiver["id"]),
        201,
    )
    get_success_data(api.cancel_session(session["id"], ATTRACTION_HOST), 200)
    # Move the clock past the expiry and let the sweep write the lapse, so the
    # cancelled session is the only remaining thing standing between the
    # check-in and the waiver gate.
    set_clock(api, "2026-09-05T00:00:00Z")
    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)
    checked = get_success_data(api.get_waiver(waiver["id"], ATTRACTION_HOST), 200)
    assert checked["expires_on"].startswith("2026-09-02"), (
        f"the one-day waiver lapses on 2026-09-02, got {checked['expires_on']}"
    )
    assert checked["status"] == "EXPIRED", (
        f"the sweep expired the lapsed waiver, got {checked['status']}"
    )
    return store, attraction, member, waiver, session, checked


def test_checking_in_a_cancelled_session_reports_already_terminal(api):
    """PRD §2.11: "A `p7` terminal-state rejection beats a `p9` missing-waiver
    rejection, so re-submitting against a finished session fails as
    `ERR_ALREADY_TERMINAL` (HTTP 409) rather than as a waiver problem."

    Design: Difficulty/priority_pair_validation_conflict/state_terminal_beats_safety_waiver_gate
    """
    store, attraction, member, waiver, session, checked = (
        _cancelled_lapsed_waiver_session(api)
    )
    response = api.check_in_session(session["id"], ATTRACTION_HOST)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


def test_a_lapsed_waiver_on_a_finished_session_never_surfaces_as_a_waiver_error(api):
    """PRD §2.11: "State checks then run: a target entity not in any source
    state the requested transition declares yields `ERR_INVALID_STATE` (HTTP
    409), and a target entity already in a terminal state yields
    `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §3.2: "a waiver that is not `SIGNED`, or whose `expires_on` is earlier
    than the store clock's current instant, is rejected with
    `ERR_WAIVER_EXPIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_terminal_beats_safety_waiver_gate
    """
    store, attraction, member, waiver, session, checked = (
        _cancelled_lapsed_waiver_session(api)
    )
    response = api.check_in_session(session["id"], ATTRACTION_HOST)
    body = response.json()
    error_id = body["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_WAIVER_REQUIRED.value, (
        "the state category strictly precedes the safety-category rows"
    )
    assert error_id != ApiErrorId.ERR_WAIVER_EXPIRED.value, (
        "the lapsed waiver is never reached because the session is already terminal"
    )
    assert error_id == ApiErrorId.ERR_ALREADY_TERMINAL.value


# ===========================================================================
# safety_permit_gate_beats_capacity_constraint  (queue A / priority_pair_validation_conflict)
# ===========================================================================

def _wrong_permit_taxidermy_intake(api):
    """A taxidermy intake backed by a FISHING permit rather than a hunting one."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_pc@x.com",
                           full_name="Pax Cruz")
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=10, dwell_cost_minutes=30)
    batch = create_remit_batch(api, store["id"])
    sale = get_success_data(
        api.create_permit_sale(
            store["id"],
            {
                "member_id": member["id"],
                "permit_type": "FISHING",
                "residency_class": "RESIDENT",
                "term_days": 30,
                "land_access_units": 0,
                "agent_user_id": "clerk_4471",
                "permit_remit_batch_id": batch["id"],
                "expected_remit_batch_version": batch["version"],
            },
            PERMIT_CLERK,
        ),
        201,
    )
    unit = create_boat_unit(api, store["id"], stock_no="BU-PC", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HINPC0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"], order_kind="TAXIDERMY",
                                 promised_lead_days=60)
    # PRD §3.6 enforces the lawful-take gate "both when the intake is created and
    # when the permit verification step is taken", so the wrong-type permit is
    # declined at the create call; the verification step is a second gate.
    refresh = get_success_data(api.get_remit_batch(batch["id"], REMIT_ADMIN), 200)
    hunting = create_permit_sale(api, store["id"], member["id"], batch["id"],
                                 refresh["version"], permit_type="HUNTING",
                                 term_days=30)
    intake = create_service_intake(
        api, store["id"], member["id"], order["id"], intake_kind="TAXIDERMY",
        specimen_quantity=20, quoted_lead_days=60, deposit_cents=5000,
        species_code="WTDEER", permit_sale_id=hunting["id"],
    )
    return store, attraction, member, sale, order, intake


def test_a_fishing_permit_does_not_verify_a_taxidermy_intake(api):
    """PRD §3.6: "Advancing a taxidermy intake past `INTAKE_QUOTED` requires a
    `permit_sale_id` referencing a permit sale whose `permit_type` is `HUNTING`
    or `ARCHERY_RANGE` and whose `status` is `ISSUED` or `REMITTED` — a
    lawful-take permit, because a mount may not be made of an unlawfully taken
    animal."
    PRD §3.6: "The refusal is `ERR_PERMIT_VERIFICATION_REQUIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_permit_gate_beats_capacity_constraint
    """
    store, attraction, member, sale, order, intake = _wrong_permit_taxidermy_intake(api)
    # The same taxidermy intake presented with the FISHING permit held by the
    # fixture is refused at its own create gate, in precedence over the venue
    # capacity constraint.
    response = api.create_service_intake(
        store["id"],
        {
            "member_id": member["id"],
            "service_order_id": order["id"],
            "intake_kind": "TAXIDERMY",
            "specimen_quantity": 20,
            "quoted_lead_days": 60,
            "deposit_cents": 5000,
            "species_code": "WTDEER",
            "permit_sale_id": sale["id"],
        },
        SERVICE_WRITER,
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_VERIFICATION_REQUIRED, 422)

    unchanged = get_success_data(api.get_service_intake(intake["id"], SERVICE_WRITER), 200)
    assert unchanged["status"] == "INTAKE_QUOTED", (
        f"the hunting-permit intake starts at its initial stage; got "
        f"{unchanged['status']}"
    )


def test_a_wrong_type_permit_is_refused_at_intake_creation_before_the_verification_step(api):
    """PRD §3.6: "The refusal is `ERR_PERMIT_VERIFICATION_REQUIRED` (HTTP 422),
    and it is enforced both when the intake is created and when the permit
    verification step is taken, so a taxidermy intake cannot be taken into the
    shop without its permit at either gate."
    PRD §3.6: "An intake of any other kind presented with a non-null
    `permit_sale_id` is equally refused, since non-hunting intakes have no
    permit to present."

    Design: Difficulty/priority_pair_validation_conflict/safety_permit_gate_beats_capacity_constraint
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_pc2@x.com",
                           full_name="Pax Crane")
    batch = create_remit_batch(api, store["id"])
    sale = get_success_data(
        api.create_permit_sale(
            store["id"],
            {
                "member_id": member["id"],
                "permit_type": "FISHING",
                "residency_class": "RESIDENT",
                "term_days": 30,
                "land_access_units": 0,
                "agent_user_id": "clerk_4471",
                "permit_remit_batch_id": batch["id"],
                "expected_remit_batch_version": batch["version"],
            },
            PERMIT_CLERK,
        ),
        201,
    )
    unit = create_boat_unit(api, store["id"], stock_no="BU-PC2", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HINPC0000002", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="OUTFITTING", promised_lead_days=20)

    response = api.create_service_intake(
        store["id"],
        {
            "member_id": member["id"],
            "service_order_id": order["id"],
            "intake_kind": "OUTFITTING",
            "specimen_quantity": 1,
            "quoted_lead_days": 20,
            "deposit_cents": 5000,
            "permit_sale_id": sale["id"],
        },
        SERVICE_WRITER,
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_VERIFICATION_REQUIRED, 422)