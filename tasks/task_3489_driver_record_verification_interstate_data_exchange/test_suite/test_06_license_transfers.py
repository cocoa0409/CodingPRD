"""The interstate license transfer protocol: the contest loop, completion
cascade, in-flight exclusivity, OCC guard, and the suspension cancellation."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_license_transfer,
    complete_transfer,
    contest_transfer,
    current_driver_version,
    initiate_transfer,
    license_transfer_payload,
    list_driver_records,
    list_licenses,
    list_license_transfers,
    make_jurisdiction_registrar_headers,
    read_license,
    read_license_transfer,
    read_participations,
    setup_certified_jurisdiction,
    setup_transfer_world,
    setup_verified_license,
    suspend_jurisdiction,
    surrender_transfer,
)


def test_license_transfer_contest_loop(api):
    """PRD §3.6: "Surrender is recorded by the sending side. A registrar of the
    `from_jurisdiction_id` records surrender of the prior license, moving the transfer
    `INITIATED` → `SURRENDER_RECORDED`; the prior license itself goes `ACTIVE` →
    `SURRENDERED`, and any `contest_reason` is cleared to null. The same action also
    closes a contest loop: from `CONTESTED`, a re-surrender returns the transfer to
    `SURRENDER_RECORDED` with identical effects."
    PRD §3.6: "Contest is the receiving side's objection. A registrar of the
    `to_jurisdiction_id` contests a recorded surrender with a `reason`, moving the
    transfer `SURRENDER_RECORDED` → `CONTESTED`; the reason is recorded as
    `contest_reason`, and — as compensation while the dispute runs — the prior license
    walks back `SURRENDERED` → `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/license_transfer_contest_loop
    """
    world = setup_transfer_world(api, from_code="AA", to_code="BB", stage="INITIATED")
    from_ctx = world["from_ctx"]
    to_ctx = world["to_ctx"]
    transfer_id = world["transfer_id"]
    license_id = from_ctx["license_id"]

    transfer = surrender_transfer(api, transfer_id, from_ctx["jurisdiction_id"])
    assert transfer["status"] == "SURRENDER_RECORDED"
    assert read_license(api, license_id)["status"] == "SURRENDERED"

    transfer = contest_transfer(api, transfer_id, to_ctx["jurisdiction_id"], "DATA_MISMATCH")
    assert transfer["status"] == "CONTESTED"
    assert transfer["contest_reason"] == "DATA_MISMATCH"
    assert read_license(api, license_id)["status"] == "ACTIVE", (
        "the contest compensation restored the prior license"
    )

    transfer = surrender_transfer(api, transfer_id, from_ctx["jurisdiction_id"])
    assert transfer["status"] == "SURRENDER_RECORDED", "the loop closed exactly once"
    assert transfer["contest_reason"] is None, "re-surrender cleared the contest reason"
    assert read_license(api, license_id)["status"] == "SURRENDERED"

    transfer = complete_transfer(api, transfer_id, to_ctx["jurisdiction_id"])
    assert_license_transfer(transfer)
    assert transfer["status"] == "COMPLETED"
    assert transfer["new_license_id"] is not None


def test_jurisdiction_suspend_cascade_cancels_transfers(api):
    """PRD §2.8: "Link two, caused by link one: every license transfer whose
    `to_jurisdiction_id` is the suspended jurisdiction and whose status is `INITIATED`
    or `CONTESTED` transitions to `CANCELLED`, because the `POINTER_NETWORK`
    participation those transfers relied upon is no longer certified."
    PRD §2.8: "Link one: every system participation of that jurisdiction currently
    `CERTIFIED` transitions to `SUSPENDED`".

    Design: Difficulty/transitive_cascade/jurisdiction_suspend_cascade_cancels_transfers
    """
    world = setup_transfer_world(api, from_code="AA", to_code="BB", stage="INITIATED")
    from_ctx = world["from_ctx"]
    to_ctx = world["to_ctx"]

    suspend_jurisdiction(api, to_ctx["jurisdiction_id"])

    rows, _ = read_participations(api, to_ctx["jurisdiction_id"])
    assert rows[0]["status"] == "SUSPENDED", "link 1: CERTIFIED -> SUSPENDED"
    transfer = read_license_transfer(api, world["transfer_id"])
    assert transfer["status"] == "CANCELLED", (
        "link 2: the in-flight transfer into the suspended jurisdiction cancelled"
    )
    assert read_license(api, from_ctx["license_id"])["status"] == "ACTIVE", (
        "an INITIATED transfer never recorded surrender, so no compensation is needed"
    )
    rows, _ = read_participations(api, from_ctx["jurisdiction_id"])
    assert rows[0]["status"] == "CERTIFIED", (
        "the cascade is scoped to the suspended jurisdiction"
    )


def test_transfer_complete_from_initiated_rejected(api):
    """PRD §3.6: "Three preconditions guard it: the prior license must be
    `SURRENDERED`, else `ERR_INVALID_STATE`".

    Design: Corner/state_machines/transfer_complete_from_initiated_rejected
    """
    world = setup_transfer_world(api, from_code="AA", to_code="BB", stage="INITIATED")
    resp = api.complete_transfer(
        world["transfer_id"],
        make_jurisdiction_registrar_headers(world["to_ctx"]["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_license_transfer(api, world["transfer_id"])["status"] == "INITIATED"
    assert read_license(api, world["from_ctx"]["license_id"])["status"] == "ACTIVE"


def test_transfer_second_in_flight_rejected(api):
    """PRD §3.6: "One transfer per driver may be in flight at a time: if the driver
    already has a transfer in `INITIATED`, `SURRENDER_RECORDED`, or `CONTESTED`,
    initiation is rejected with `ERR_TRANSFER_ALREADY_IN_FLIGHT`."

    Design: Corner/state_machines/transfer_second_in_flight_rejected
    """
    world = setup_transfer_world(api, from_code="AA", to_code="BB", stage="INITIATED")
    from_ctx = world["from_ctx"]
    fresh_version = current_driver_version(api, from_ctx["driver_id"])
    resp = api.create_license_transfer(
        license_transfer_payload(
            from_ctx["driver_id"], from_ctx["license_id"], fresh_version
        ),
        make_jurisdiction_registrar_headers(world["to_ctx"]["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_IN_FLIGHT)
    rows, meta = list_license_transfers(api, params={"driver_id": from_ctx["driver_id"]})
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["transfer_id"] and rows[0]["status"] == "INITIATED"


def test_transfer_initiate_stale_driver_version_returns_412(api):
    """PRD §2.7: "a `POST /driver-exchange/license-transfers` request must carry the
    same field under the same rule. If the driver identity's version has advanced since
    the client last read it — because another jurisdiction's record claim, or an earlier
    transfer initiation, legitimately became the driver's latest state — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/transfer_initiate_stale_driver_version_returns_412
    """
    from_ctx = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    setup_verified_license(api, from_ctx, license_class="STANDARD")
    to_ctx = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    stale_version = current_driver_version(api, from_ctx["driver_id"]) - 1
    resp = api.create_license_transfer(
        license_transfer_payload(
            from_ctx["driver_id"], from_ctx["license_id"], stale_version
        ),
        make_jurisdiction_registrar_headers(to_ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows, meta = list_license_transfers(api, params={"driver_id": from_ctx["driver_id"]})
    assert meta["total_count"] == 0 and rows == []


def test_transfer_completion_conserves_single_active_record(api):
    """PRD §3.6: "The completion cascade then fires in full: the prior driver record
    goes `ACTIVE` → `TRANSFERRED_OUT`; a new driver record is created for the same
    driver with `holding_jurisdiction_id` set to the receiving jurisdiction, status
    `ACTIVE`, and both `points_total` and `abstract_points_total` at zero; a new license
    is created in `PENDING_VERIFICATION` with `issuing_jurisdiction_id` set to the
    receiving jurisdiction, its `record_id` pointing at the new record, its
    `license_class` copied from the prior license, and both check statuses `PENDING`;
    and the transfer's `new_license_id` is set to the new license as the transfer
    reaches its terminal `COMPLETED` state. The one-driver-one-record invariant holds
    across the move — exactly one `ACTIVE` record per driver before, during, and after."

    Design: Difficulty/compensating_invariant/transfer_completion_conserves_single_active_record
    """
    world = setup_transfer_world(api, from_code="AA", to_code="BB", stage="SURRENDER_RECORDED")
    from_ctx = world["from_ctx"]
    to_ctx = world["to_ctx"]

    transfer = complete_transfer(api, world["transfer_id"], to_ctx["jurisdiction_id"])
    assert transfer["status"] == "COMPLETED"
    assert transfer["new_license_id"] is not None

    rows, meta = list_driver_records(api, params={"driver_id": from_ctx["driver_id"]})
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    old_record = by_id[from_ctx["record_id"]]
    assert old_record["status"] == "TRANSFERRED_OUT"
    assert old_record["holding_jurisdiction_id"] == from_ctx["jurisdiction_id"]
    new_records = [r for r in rows if r["status"] == "ACTIVE"]
    assert len(new_records) == 1, "exactly one ACTIVE record survives the move"
    new_record = new_records[0]
    assert new_record["holding_jurisdiction_id"] == to_ctx["jurisdiction_id"]
    assert new_record["points_total"] == 0 and new_record["abstract_points_total"] == 0

    licenses, license_meta = list_licenses(api, params={"driver_id": from_ctx["driver_id"]})
    assert license_meta["total_count"] == 2
    licenses_by_id = {lic["id"]: lic for lic in licenses}
    assert licenses_by_id[from_ctx["license_id"]]["status"] == "SURRENDERED"
    new_license = licenses_by_id[transfer["new_license_id"]]
    assert new_license["status"] == "PENDING_VERIFICATION"
    assert new_license["issuing_jurisdiction_id"] == to_ctx["jurisdiction_id"]
    assert new_license["license_class"] == "STANDARD", "class copied from the prior license"
    assert new_license["record_id"] == new_record["id"], (
        "the new license points at the new record — referential closure of the move"
    )


def test_get_unknown_license_transfer_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_TRANSFER_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/get_unknown_license_transfer_not_found
    """
    resp = api.get_license_transfer(NON_EXISTENT_UUID, ASSOCIATION_ADMIN_HEADERS)
    assert_error(resp, ApiErrorId.ERR_TRANSFER_NOT_FOUND)


def test_record_surrender_by_to_side_forbidden(api):
    """PRD §2.6: "When a `JurisdictionRegistrar` acts on a jurisdiction-scoped resource,
    `X-User-ID` must equal the `id` of the jurisdiction that owns — or will own — the
    resource: the record-holding jurisdiction for conviction posting; the issuing
    jurisdiction for license reinstatement; the invoiced jurisdiction for invoice
    dispute and settlement; the `from_jurisdiction_id` for recording a surrender; the
    `to_jurisdiction_id` for initiating, contesting, or completing a license transfer or
    completing a title transfer; and the registrar's own jurisdiction for enrolling in
    a system, claiming a record, issuing a license, titling a vehicle, or requesting a
    re-titling. A mismatch is `ERR_JURISDICTION_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §3.6: "Surrender is recorded by the sending side."

    Design: Corner/rbac/record_surrender_by_to_side_forbidden
    """
    world = setup_transfer_world(api, from_code="AA", to_code="BB", stage="INITIATED")
    resp = api.record_surrender(
        world["transfer_id"],
        make_jurisdiction_registrar_headers(world["to_ctx"]["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_JURISDICTION_OWNERSHIP_MISMATCH)
    assert read_license_transfer(api, world["transfer_id"])["status"] == "INITIATED"
    assert read_license(api, world["from_ctx"]["license_id"])["status"] == "ACTIVE"
