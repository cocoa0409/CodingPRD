"""Role membership, the permission list, and entity-backed identity semantics."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    close_markdown_window,
    create_sub_ticket_payload,
    create_waste_record,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    produce_batch,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def test_the_verify_endpoint_admits_only_the_manager_role():
    """PRD §2.1: "A request whose role is recognized but is not listed as an
    authorized role for the addressed operation is rejected with
    `ERR_UNAUTHORIZED`."
    PRD §2.11: "an unauthorized role yields `ERR_UNAUTHORIZED` before any business
    rule fires."

    Design: Corner/roles/deli_clerk_cannot_verify_own_waste_under_manager_role
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    batch = produce_batch(master.s, master.j4["id"], master.a1["id"], "B-C", 4, produced_lbs=4,
                          slicer_id=master.slicers[0]["id"])
    record = create_waste_record(master.s, batch["id"], master.a2["id"], reason="QUALITY",
                                 acting_associate_id=master.a1["id"])
    close_markdown_window(batch, master.j4)
    validate_success(api_client.discard_waste_record(record["id"], 4, clerk_headers(master.a1["id"])))
    batch_now = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))

    denied = api_client.verify_waste_record(
        record["id"], master.a3["id"], master.c_a3_fh["id"], batch_now["version"],
        clerk_headers(master.a1["id"]),
    )
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)

    unchanged = validate_success(api_client.get_waste_record(record["id"], platform_admin_headers()))
    assert unchanged["status"] == "DISCARDED", "the denied attempt changed nothing"

    allowed = validate_success(
        api_client.verify_waste_record(
            record["id"], master.a3["id"], master.c_a3_fh["id"], batch_now["version"],
            manager_headers(master.a3["id"]),
        )
    )
    assert allowed["status"] == "VERIFIED"


def test_opening_a_sanitation_cycle_is_outside_the_scale_operators_remit():
    """PRD §2.1: "`ScaleOperator`, like `PlatformAdmin`, is opaque: `X-User-ID` is
    an opaque operator identifier not tied to any persisted entity, recorded on
    scale and label operations but never compared to an entity `id`."
    PRD §2.1: "A request whose role is recognized but is not listed as an
    authorized role for the addressed operation is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/roles/scale_operator_cannot_open_a_sanitation_cycle
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    slicer = master.slicers[0]
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-C", 125, produced_lbs=125,
                  slicer_id=slicer["id"])

    denied = api_client.create_sanitation_cycle(
        {"store_id": master.s, "slicer_id": slicer["id"], "cycle_type": "ROUTINE",
         "cycle_minutes": 10},
        scale_operator_headers(),
    )
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)

    allowed = validate_success(
        api_client.create_sanitation_cycle(
            {"store_id": master.s, "slicer_id": slicer["id"], "cycle_type": "ROUTINE",
             "cycle_minutes": 10},
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert allowed["status"] == "OPEN"
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "SANITIZING", (
        "the status moved only after the authorized call"
    )


def test_an_entity_backed_identity_is_checked_against_the_store_it_addresses():
    """PRD §2.1: "`DeliManager`, `DeliClerk` and `BakeryCoordinator` are
    entity-backed: when `X-User-Role` is one of these, `X-User-ID` is the `id` of
    an acting `Associate` row, and ownership checks on any resource that
    references an `Associate` compare the resource's foreign-key field to
    `X-User-ID`."

    Design: Corner/roles/entity_backed_identity_binds_user_id_to_the_associate
    """
    set_clock("2026-09-02T06:00:00Z")
    first = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                   slicer_count=1)
    second = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)

    own_store = validate_success(api_client.get_store(first.s, clerk_headers(first.a1["id"])))
    assert own_store["id"] == first.s, "the identity's own store resolves"

    cross = api_client.create_batch(
        {"store_id": second.s, "deli_item_id": second.j4["id"], "slicer_id": second.slicers[0]["id"],
         "produced_by_associate_id": first.a1["id"], "batch_code": "B-CROSS", "planned_lbs": 4},
        clerk_headers(first.a1["id"]),
    )
    assert cross.status_code >= 400, (
        "an associate of another store cannot act on this store's batches"
    )

    opaque = validate_success(api_client.get_store(second.s, platform_admin_headers()))
    assert opaque["id"] == second.s, (
        "an opaque PlatformAdmin identity reads any store, since its X-User-ID is compared to nothing"
    )


def test_replacing_a_roles_permission_list_flips_its_ticketing_authorization():
    """PRD §2.1: "A platform-admin capability exists to replace the permission list
    attached to a role for the installation; it accepts a `role` and the
    replacement `permissions`, and the acting role's entry becomes the
    authoritative permission set for authorization checks."
    PRD §2.1: "Replacing a role's permissions with a set that omits an operation is
    the supported way to force that role's denial path, and the response reports
    how many roles currently hold a non-empty permission list."

    Design: Corner/roles/role_permission_list_controls_authorization_attribute_based
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=600, store_number="102", store_name="Store Two",
                                    slicer_count=2, clerk_allergy_set=("MILK", "WHEAT"))
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])
    ticket = get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 2,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )

    stripped = validate_success(
        api_client.set_role_permissions("DeliClerk", ["read", "create"], platform_admin_headers())
    )
    assert isinstance(stripped["active_role_count"], int)

    denied = api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)

    validate_success(
        api_client.set_role_permissions(
            "DeliClerk", ["read", "create", "ticket"], platform_admin_headers()
        )
    )
    allowed = validate_success(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))
    assert allowed["status"] == "TICKETED", (
        "the same request shape flips only on the role's stored permission list"
    )