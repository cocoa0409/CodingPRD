"""Resident onboarding, the move-out cascade and credential conservation."""

from test_helpers import (
    HARDWARE,
    advance_clock,
    MANAGER,
    ApiErrorId,
    assert_credential_conservation,
    create_installation_job,
    create_resident,
    get_success_data,
    list_credentials,
    list_status_events,
    make_resident_headers,
    pin_clock,
    provision_building,
    provision_device,
    provision_property,
    provision_unit,
    read_building_version,
    read_guest_pass,
    read_property,
    read_resident,
    read_unit,
    setup_active_resident_with_guest_pass,
    setup_occupied_unit_with_online_lock,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Onboarding gates
# ---------------------------------------------------------------------------

def test_onboarding_requires_an_online_smart_lock_on_the_unit(api):
    """PRD §3.4: "The platform will not onboard a resident unless four things
    hold: the resident is currently `PENDING_CREDENTIAL`; the resident's unit is
    in `OCCUPIED` or `NOTICE`; at least one `SMART_LOCK` device assigned to that
    unit is `ONLINE`; and the unit's building passes connectivity. When any of
    those fails, the request is refused with `ERR_INSUFFICIENT_CONNECTIVITY`
    (409)."

    Design: Difficulty/cross_entity_state_dependency/resident_onboard_requires_online_smart_lock
    """
    pin_clock()
    prop = provision_property(unit_capacity=2)
    bld = provision_building(prop["id"], wifi_rssi_dbm=-60)
    online_unit = provision_unit(prop["id"], unit_number="U1", building_id=bld["id"])
    offline_unit = provision_unit(prop["id"], unit_number="U2", building_id=bld["id"])
    online_lock = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=online_unit["id"],
        firmware_version="LATEST", battery_pct=100,
    )
    provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=offline_unit["id"],
        firmware_version="LATEST", battery_pct=100,
    )
    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [online_lock["id"]]}, HARDWARE)
    )
    good = create_resident(prop["id"], online_unit["id"], full_name="Rita Lock", email="rita@x.com")
    bad = create_resident(prop["id"], offline_unit["id"], full_name="Rex Offline", email="rex@x.com")

    ok = validate_success(api.onboard_resident(good["id"], MANAGER), 200)
    assert ok["status"] == "ACTIVE"

    resp = api.onboard_resident(bad["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CONNECTIVITY, 409)
    assert read_resident(prop["id"], bad["id"])["status"] == "PENDING_CREDENTIAL"


def test_onboarding_issues_a_credential_flips_portal_status_and_appends_an_event(api):
    """PRD §3.4: "On success the platform issues a resident credential — an
    `AccessCredential` whose `credential_type` is `RESIDENT`, carrying
    `subject_resident_id` equal to the resident's `id`, created directly in
    `ACTIVE` status — and recomputes `portal_credential_status` to `ACTIVE`."
    PRD §3.4: "Onboarding appends a `PENDING_CREDENTIAL` to `ACTIVE` event."

    Design: Corner/state_machines/resident_onboard_issues_credential_and_event
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-FX1"
    )

    data = validate_success(api.onboard_resident(resident["id"], MANAGER), 200)
    assert data["status"] == "ACTIVE"
    assert data["portal_credential_status"] == "ACTIVE"

    creds = list_credentials(subject_resident_id=resident["id"])
    assert len(creds) == 1
    assert creds[0]["status"] == "ACTIVE"
    assert creds[0]["credential_type"] == "RESIDENT"

    events = list_status_events(resident["id"])
    assert len(events) == 1
    assert events[0]["from_status"] == "PENDING_CREDENTIAL"
    assert events[0]["to_status"] == "ACTIVE"


def test_onboarding_an_already_active_resident_is_rejected(api):
    """PRD §3.4: "The platform will not onboard a resident unless four things
    hold: the resident is currently `PENDING_CREDENTIAL`."
    PRD §2.12: "this check guards tour verification, work-order assignment,
    installation-job start, maintenance certification, maintenance completion,
    guest-pass extension, and resident onboarding."

    Design: Difficulty/cross_entity_state_dependency/resident_onboard_requires_online_smart_lock
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-FX2", onboard=True
    )
    resp = api.onboard_resident(resident["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_resident_cannot_onboard_a_resident(api):
    """PRD §2.1: "The operations reserved to `PropertyManager` alone are resident
    onboarding, resident deactivation, the certification of legal notice on a
    maintenance visit, and the vacant-unit automation run."

    Design: Corner/rbac/resident_cannot_onboard_a_resident
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-RO1"
    )

    resp = api.onboard_resident(resident["id"], make_resident_headers(resident["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert read_resident(prop["id"], resident["id"])["status"] == "PENDING_CREDENTIAL"


# ---------------------------------------------------------------------------
# Move-out cascade
# ---------------------------------------------------------------------------

def test_move_out_revokes_credentials_the_unit_and_the_guest_pass(api):
    """PRD §2.7: "When a resident is deactivated, every credential in the
    resident's scope that is still `ISSUED` or `ACTIVE` is moved to `REVOKED` in
    the same operation, the resident's `portal_credential_status` is recomputed,
    and the resident's unit is pulled out of occupancy."
    PRD §3.5: "every `GuestPass` whose `host_resident_id` equals the departing
    resident's `id` and whose status is still `ACTIVE` is moved to `REVOKED`."

    Design: Difficulty/transitive_cascade/resident_moveout_credential_revocation_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-M1"
    )

    data = validate_success(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        ),
        200,
    )

    assert data["status"] == "DEACTIVATING"
    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "NOTICE"
    assert read_guest_pass(unit["id"], gpass["id"])["status"] == "REVOKED"
    creds = list_credentials(subject_resident_id=resident["id"])
    assert creds, "the resident held a credential before move-out"
    assert all(c["status"] == "REVOKED" for c in creds)


def test_resident_bubbles_to_revoked_once_no_live_credential_remains(api):
    """PRD §3.5: "The resident does not reach its terminal state at that moment.
    It rests in `DEACTIVATING` until no credential in its scope remains in
    `ISSUED` or `ACTIVE`, at which point it moves to `REVOKED` — its only
    terminal state — and appends a `DEACTIVATING` to `REVOKED` event, and
    `portal_credential_status` settles at `REVOKED`."

    Design: Difficulty/transitive_cascade/resident_moveout_credential_revocation_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-M2"
    )

    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        )
    )

    stored = read_resident(prop["id"], resident["id"])
    assert stored["status"] == "REVOKED"
    assert stored["portal_credential_status"] == "REVOKED"

    events = list_status_events(resident["id"])
    hops = [(e["from_status"], e["to_status"]) for e in events]
    assert ("PENDING_CREDENTIAL", "ACTIVE") in hops
    assert ("ACTIVE", "DEACTIVATING") in hops
    assert ("DEACTIVATING", "REVOKED") in hops


def test_move_out_records_the_full_status_event_trail(api):
    """PRD §3.4: "Every change of a resident's status leaves an audit record. A
    `ResidentStatusEvent` is appended carrying the `resident_id` it describes,
    the `from_status` it left and the `to_status` it entered."

    Design: Difficulty/transitive_cascade/resident_moveout_credential_revocation_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-M3"
    )
    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        )
    )

    events = list_status_events(resident["id"])
    assert len(events) == 3
    assert [e["to_status"] for e in events] == ["ACTIVE", "DEACTIVATING", "REVOKED"]
    assert all(e["resident_id"] == resident["id"] for e in events)


def test_status_event_records_carry_only_id_and_created_at(api):
    """PRD §2.4: "`ResidentStatusEvent` is an append-only audit record and
    carries only `id` and `created_at`; both `updated_at` and `version` are
    absent from its representation, and it is never modified after creation."

    Design: Difficulty/transitive_cascade/resident_moveout_credential_revocation_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-M4", onboard=True
    )

    events = list_status_events(resident["id"])
    assert events
    for event in events:
        assert "id" in event
        assert "created_at" in event
        assert "updated_at" not in event
        assert "version" not in event


# ---------------------------------------------------------------------------
# Credential conservation
# ---------------------------------------------------------------------------

def test_credential_count_is_conserved_across_revoke(api):
    """PRD §2.7: "The four live states partition the population, so counting
    every credential a resident has ever held gives the same number whether the
    count is taken as the sum of the `active`, `expired` and `revoked` groups or
    as the size of the full set."

    Design: Difficulty/compensating_invariant/credential_status_partition_conservation
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-CL1"
    )

    before = list_credentials(unit_id=unit["id"])
    assert_credential_conservation(before, 2)
    assert all(c["status"] == "ACTIVE" for c in before)

    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        )
    )

    after = list_credentials(unit_id=unit["id"])
    counts = assert_credential_conservation(after, 2)
    assert counts["REVOKED"] == 2, "both rows moved to the revoked bucket, none vanished"


def test_unit_scoped_count_includes_guest_and_tour_credentials(api):
    """PRD §2.7: "Scoped to a unit — restricted to rows whose `unit_id` equals the
    unit's `id` — the count covers every credential on the unit, including those
    of type `GUEST` and `TOUR`."

    Design: Difficulty/compensating_invariant/credential_status_partition_conservation
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-CL2"
    )

    unit_rows = list_credentials(unit_id=unit["id"])
    types = sorted({c["credential_type"] for c in unit_rows})
    assert types == ["GUEST", "RESIDENT"], "the unit scope covers guest credentials too"

    resident_rows = list_credentials(subject_resident_id=resident["id"])
    assert [c["credential_type"] for c in resident_rows] == ["RESIDENT"], (
        "the resident scope excludes guest credentials"
    )


# ---------------------------------------------------------------------------
# Guest-pass scope rules
# ---------------------------------------------------------------------------

def test_guest_pass_hosted_by_a_deactivating_resident_is_refused_for_resident_state(api):
    """PRD §2.12: "Seventh, an operation that acts on a resident's unit requires
    that resident not to be `REVOKED` — otherwise `ERR_RESIDENT_NOT_ACTIVE`
    (409); this guards guest-pass issuance and guest-pass extension."
    PRD §3.6: "The host must not be a `REVOKED` resident — a request acting on a
    unit on behalf of a revoked resident is refused with
    `ERR_RESIDENT_NOT_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/resident_not_active_beats_credential_scope_on_guest_pass
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-N1", onboard=True
    )
    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        )
    )

    resp = api.issue_guest_pass(
        unit["id"],
        {"host_resident_id": resident["id"], "guest_label": "Too Soon",
         "start_at": "2026-09-25T09:00:00Z", "end_at": "2026-09-26T09:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE, 409)
    # PRD §3.5: deactivation revokes the live credentials, so "the condition is
    # generally satisfied in the same breath" and the resident has already
    # bubbled to its terminal state by the time the refusal is evaluated.
    assert read_resident(prop["id"], resident["id"])["status"] == "REVOKED"


def test_guest_pass_hosted_by_a_revoked_resident_is_refused(api):
    """PRD §3.6: "The host must not be a `REVOKED` resident — a request acting on
    a unit on behalf of a revoked resident is refused with
    `ERR_RESIDENT_NOT_ACTIVE` (409)."

    Design: Corner/errors/guest_pass_from_revoked_resident_rejected
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-RV1", onboard=True
    )
    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-05T00:00:00Z"}, MANAGER
        )
    )
    advance_clock("2026-09-06T00:00:00Z")
    assert read_resident(prop["id"], resident["id"])["status"] == "REVOKED"

    resp = api.issue_guest_pass(
        unit["id"],
        {"host_resident_id": resident["id"], "guest_label": "Too Late",
         "start_at": "2026-09-10T09:00:00Z", "end_at": "2026-09-11T09:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE, 409)


def test_resident_cannot_issue_a_guest_pass_for_another_unit(api):
    """PRD §2.1: "When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of
    the acting `Resident`; ownership checks on any resource that references a
    `Resident` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "In particular, a guest pass may only be issued or extended by a
    `Resident` whose own `id` equals the pass's `host_resident_id`."

    Design: Corner/rbac/resident_cannot_create_guest_pass_for_another_unit
    """
    pin_clock()
    prop = provision_property(unit_capacity=2)
    bld = provision_building(prop["id"], wifi_rssi_dbm=-60)
    unit_one = provision_unit(prop["id"], unit_number="U-OO1", building_id=bld["id"])
    unit_two = provision_unit(prop["id"], unit_number="U-OO2", building_id=bld["id"])
    lock_one = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=unit_one["id"],
        firmware_version="LATEST", battery_pct=100,
    )
    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [lock_one["id"]]}, HARDWARE)
    )
    olive = create_resident(prop["id"], unit_one["id"], full_name="Olive Owner", email="olive@x.com")
    otto = create_resident(prop["id"], unit_two["id"], full_name="Otto Other", email="otto@x.com")
    get_success_data(api.onboard_resident(olive["id"], MANAGER))

    resp = api.issue_guest_pass(
        unit_two["id"],
        {"host_resident_id": otto["id"], "guest_label": "Not Mine",
         "start_at": "2026-09-10T09:00:00Z", "end_at": "2026-09-11T09:00:00Z"},
        make_resident_headers(olive["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_guest_pass_issued_by_its_own_host_resident_succeeds(api):
    """PRD §2.1: "In particular, a guest pass may only be issued or extended by a
    `Resident` whose own `id` equals the pass's `host_resident_id`."

    Design: Corner/rbac/resident_cannot_create_guest_pass_for_another_unit
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-OK1", onboard=True
    )

    resp = api.issue_guest_pass(
        unit["id"],
        {"host_resident_id": resident["id"], "guest_label": "Mine",
         "start_at": "2026-09-10T09:00:00Z", "end_at": "2026-09-11T09:00:00Z"},
        make_resident_headers(resident["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["host_resident_id"] == resident["id"]


# ---------------------------------------------------------------------------
# Installation jobs against the property budget
# ---------------------------------------------------------------------------

def test_hub_job_in_a_disconnected_building_is_refused(api):
    """PRD §3.8: "A hub installation carries an additional precondition of its
    own: installing a `HUB` requires the target building to already pass its
    connectivity check, and a building that does not is refused with
    `ERR_NO_HUB_CONNECTIVITY` (409)."

    Design: Corner/errors/hub_job_requires_connectivity
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"], wifi_rssi_dbm=-90)
    assert bld["connectivity_ok"] is False

    resp = api.create_installation_job(
        bld["id"],
        {"device_type": "HUB", "requires_resident_coordination": False,
         "access_window_start": "2026-09-05T09:00:00Z",
         "access_window_end": "2026-09-05T12:00:00Z",
         "expected_building_version": bld["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_HUB_CONNECTIVITY, 409)
    assert get_success_data(api.list_installation_jobs(MANAGER, {"building_id": bld["id"]})) == []


def test_hub_safety_check_precedes_the_budget_check(api):
    """PRD §2.12: "Because the budget check precedes the stale-version check, a
    request that is both over budget and stale is refused for the budget."
    PRD §2.12: "The order is as follows. First, authentication ... Twentieth, the
    operation must not push the property's committed budget over its allowance —
    otherwise `ERR_BUDGET_EXCEEDED` (409)."
    PRD §3.8: "A hub installation carries an additional precondition of its own:
    installing a `HUB` requires the target building to already pass its
    connectivity check, and a building that does not is refused with
    `ERR_NO_HUB_CONNECTIVITY` (409)."

    Design: Difficulty/priority_pair_validation_conflict/no_hub_connectivity_safety_beats_budget_fiscal_on_hub_job
    """
    pin_clock()
    prop = provision_property(temp_budget_cents_per_day=72000, unit_capacity=2)
    bld = provision_building(prop["id"], wifi_rssi_dbm=-90)
    unit = provision_unit(prop["id"], unit_number="U-S1", building_id=bld["id"])
    visit = get_success_data(
        api.request_maintenance_visit(
            unit["id"],
            {"technician_id": "tech-sam", "start_at": "2026-09-03T10:00:00Z",
             "end_at": "2026-09-07T14:00:00Z", "is_emergency": False},
            MANAGER,
        )
    )
    certified = validate_success(
        api.certify_notice(
            visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
        ),
        200,
    )
    assert certified["accrued_cost_cents"] == 72000, "100 planned hours at 700 cents"

    resp = api.create_installation_job(
        bld["id"],
        {"device_type": "HUB", "requires_resident_coordination": False,
         "access_window_start": "2026-09-08T09:00:00Z",
         "access_window_end": "2026-09-08T12:00:00Z",
         "expected_building_version": bld["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_HUB_CONNECTIVITY, 409)
    assert get_success_data(api.list_installation_jobs(MANAGER, {"building_id": bld["id"]})) == []


def test_installation_job_creation_reserves_and_bumps_the_building(api):
    """PRD §3.8: "The job is born `SCHEDULED`, and creating it holds a
    reservation of 2000 cents against the owning property's
    `budget_committed_cents`. Creation also advances the building: the building's
    `version` is incremented by exactly one."

    Design: Corner/cross_cutting_complexity_layers/stale_building_version_blocks_second_installation_job
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    unit = provision_unit(prop["id"], building_id=bld["id"])
    version_before = bld["version"]

    job, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="SMART_LOCK",
        expected_building_version=version_before,
    )
    assert job["status"] == "SCHEDULED"

    assert read_building_version(prop["id"], bld["id"]) == version_before + 1
    assert read_property(prop["id"])["budget_committed_cents"] == 2000


def test_second_job_with_a_stale_building_version_is_refused(api):
    """PRD §2.9: "If the building's current `version` differs from the supplied
    value — because another writer has changed the building's connectivity or
    placed its own job — the operation is rejected with `ERR_STALE_VERSION` and
    an HTTP status of 412."

    Design: Corner/cross_cutting_complexity_layers/stale_building_version_blocks_second_installation_job
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    unit = provision_unit(prop["id"], building_id=bld["id"])
    version_at_creation = bld["version"]
    create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="SMART_LOCK",
        expected_building_version=version_at_creation,
    )

    resp = api.create_installation_job(
        bld["id"],
        {"device_type": "THERMOSTAT", "unit_id": unit["id"],
         "requires_resident_coordination": False,
         "access_window_start": "2026-09-04T09:00:00Z",
         "access_window_end": "2026-09-04T12:00:00Z",
         "expected_building_version": version_at_creation},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    jobs = get_success_data(api.list_installation_jobs(MANAGER, {"building_id": bld["id"]}))
    assert len(jobs) == 1

def test_guest_pass_refusal_leaves_the_unit_without_a_new_pass(api):
    """PRD §3.6: "The host must not be a `REVOKED` resident — a request acting on
    a unit on behalf of a revoked resident is refused with
    `ERR_RESIDENT_NOT_ACTIVE` (409) — and the requested window must not collide
    with an existing occupation of the unit."

    Design: Difficulty/priority_pair_validation_conflict/resident_not_active_beats_credential_scope_on_guest_pass
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-N2", onboard=True
    )
    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        )
    )

    resp = api.issue_guest_pass(
        unit["id"],
        {"host_resident_id": resident["id"], "guest_label": "Blocked",
         "start_at": "2026-09-25T09:00:00Z", "end_at": "2026-09-26T09:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE, 409)
    assert get_success_data(api.list_guest_passes(MANAGER, {"unit_id": unit["id"]})) == []
    # PRD §3.5: the refusal changes nothing, and the resident has already
    # bubbled to its terminal state with the deactivation cascade.
    assert read_resident(prop["id"], resident["id"])["status"] == "REVOKED"


def test_hub_refusal_leaves_the_property_with_no_job_and_an_intact_cap(api):
    """PRD §3.8: "installing a `HUB` requires the target building to already pass
    its connectivity check, and a building that does not is refused with
    `ERR_NO_HUB_CONNECTIVITY` (409)."
    PRD §2.8: "each installation job placed against a building of the property
    holds a reservation of 2000 cents, and that reservation is carried inside
    `budget_committed_cents`."

    Design: Difficulty/priority_pair_validation_conflict/no_hub_connectivity_safety_beats_budget_fiscal_on_hub_job
    """
    pin_clock()
    prop = provision_property(temp_budget_cents_per_day=72000, unit_capacity=2)
    bld = provision_building(prop["id"], wifi_rssi_dbm=-90)
    unit = provision_unit(prop["id"], unit_number="U-S2", building_id=bld["id"])
    visit = get_success_data(
        api.request_maintenance_visit(
            unit["id"],
            {"technician_id": "tech-sam", "start_at": "2026-09-03T10:00:00Z",
             "end_at": "2026-09-07T14:00:00Z", "is_emergency": False},
            MANAGER,
        )
    )
    validate_success(
        api.certify_notice(
            visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
        ),
        200,
    )
    assert read_property(prop["id"])["budget_committed_cents"] == 72000

    resp = api.create_installation_job(
        bld["id"],
        {"device_type": "HUB", "requires_resident_coordination": False,
         "access_window_start": "2026-09-08T09:00:00Z",
         "access_window_end": "2026-09-08T12:00:00Z",
         "expected_building_version": bld["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_HUB_CONNECTIVITY, 409)

    assert get_success_data(api.list_installation_jobs(MANAGER, {"building_id": bld["id"]})) == []
    assert read_property(prop["id"])["budget_committed_cents"] == 72000, (
        "the refused reserve never landed on the committed total"
    )
