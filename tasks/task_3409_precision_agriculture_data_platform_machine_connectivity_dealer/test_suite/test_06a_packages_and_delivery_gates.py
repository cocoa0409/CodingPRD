"""Software package lifecycle gates and update-delivery creation gates."""

from test_helpers import (
    ADMIN,
    SYSTEM,
    ApiErrorId,
    add_published_package,
    create_package,
    publish_package,
    read_delivery,
    read_ticket,
    setup_activated_machine,
    setup_connected_machine,
    setup_delivery_awaiting_consent,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_delivery_create_mints_platform_consent_ticket(api):
    """PRD section 3.6: "Creation mints the bound consent ticket —
    `ticket_type` `SOFTWARE_UPDATE`, `requester_ref_id` the literal `platform`,
    state `REQUESTED` — links it through the delivery's `consent_ticket_id`,
    and the delivery itself starts `AWAITING_CONSENT` with `download_attempts`
    0, `failure_reason` null, and `installed_at` null."

    Design: Corner/entities/delivery_create_mints_platform_consent_ticket
    """
    ctx = setup_delivery_awaiting_consent(api)
    delivery = ctx["delivery"]
    assert delivery["status"] == "AWAITING_CONSENT"
    assert delivery["download_attempts"] == 0
    assert delivery["failure_reason"] is None
    assert delivery["installed_at"] is None

    ticket = read_ticket(ctx, api, ctx["ticket_id"])
    assert ticket["ticket_type"] == "SOFTWARE_UPDATE"
    assert ticket["requester_ref_id"] == "platform"
    assert ticket["status"] == "REQUESTED"
    assert ticket["machine_id"] == ctx["machine"]["id"]


def test_package_publish_twice_and_withdraw_draft_rejected(api):
    """PRD section 3.6: "Packages are born `DRAFT`; publishing moves `DRAFT` →
    `PUBLISHED`, and only `PUBLISHED` packages accept deliveries. Withdrawal
    moves `PUBLISHED` → `WITHDRAWN`, which is terminal" — a second publish and
    a withdraw on a `DRAFT` package are transitions that do not exist
    (`ERR_INVALID_STATE_TRANSITION`, PRD section 2.10 step 6).

    Design: Corner/state_machines/package_publish_twice_and_withdraw_draft_rejected
    """
    package = create_package(api)
    publish_package(api, package["id"])
    package2 = create_package(api, package_code="FW-11-DRAFT",
                              firmware_version="10.3.0", size_mb=900,
                              mandatory=True)

    response = api.publish_software_package(package["id"], headers=ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    response = api.withdraw_software_package(package2["id"], headers=ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    data = validate_success(api.get_software_package(package["id"], headers=ADMIN))
    assert data["status"] == "PUBLISHED"
    data = validate_success(api.get_software_package(package2["id"], headers=ADMIN))
    assert data["status"] == "DRAFT"


def test_delivery_start_download_before_consent_rejected(api):
    """PRD section 3.6: "Starting a download is legal from `CONSENT_GRANTED`
    and — the consent-preserving retry loop — from `FAILED`" — starting while
    the delivery still sits `AWAITING_CONSENT` is a transition that does not
    exist (`ERR_INVALID_STATE_TRANSITION`, PRD section 2.10 step 6) and does
    not consume the ticket.

    Design: Corner/state_machines/delivery_start_download_before_consent_rejected
    """
    ctx = setup_delivery_awaiting_consent(api)
    delivery_id = ctx["delivery"]["id"]

    response = api.start_update_download(delivery_id, headers=SYSTEM)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    delivery = read_delivery(ctx, api, delivery_id)
    assert delivery["status"] == "AWAITING_CONSENT"
    assert delivery["download_attempts"] == 0
    ticket = read_ticket(ctx, api, ctx["ticket_id"])
    assert ticket["status"] == "REQUESTED"


def test_delivery_model_mismatch_rejected(api):
    """PRD section 3.6: "the package's `target_model_code` must equal the
    machine's `model_code` (`ERR_PACKAGE_MODEL_MISMATCH`)" — a mismatched
    schedule persists no delivery and mints no consent ticket.

    Design: Corner/validations/delivery_model_mismatch_rejected
    """
    ctx = setup_activated_machine(api)
    package = add_published_package(
        ctx, api, package_code="FW-M9X", target_model_code="M9X",
        firmware_version="4.0.0", size_mb=500,
    )
    response = api.create_update_delivery(
        {"machine_id": ctx["machine"]["id"], "package_id": package["id"]},
        headers=ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_PACKAGE_MODEL_MISMATCH)

    rows, _meta = validate_paginated(
        api.list_update_deliveries(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 0
    rows, _meta = validate_paginated(
        api.list_consent_tickets(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 0


def test_delivery_duplicate_pending_rejected(api):
    """PRD section 3.6: "no non-terminal delivery may already exist for the
    same machine and package (`ERR_DELIVERY_ALREADY_PENDING`)".

    Design: Corner/validations/delivery_duplicate_pending_rejected
    """
    ctx = setup_delivery_awaiting_consent(api)
    response = api.create_update_delivery(
        {"machine_id": ctx["machine"]["id"],
         "package_id": ctx["package"]["id"]},
        headers=ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DELIVERY_ALREADY_PENDING)

    rows, _meta = validate_paginated(
        api.list_update_deliveries(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 1


def test_delivery_on_unactivated_machine_rejected(api):
    """PRD section 3.6: "the machine's lifecycle must be `ACTIVATED` or
    `IN_SERVICE` (`ERR_MACHINE_NOT_ACTIVATED`)" — a machine that is fully
    connected but never dealer-activated cannot be scheduled.

    Design: Corner/validations/delivery_on_unactivated_machine_rejected
    """
    ctx = setup_connected_machine(api)
    package = add_published_package(ctx, api)
    response = api.create_update_delivery(
        {"machine_id": ctx["machine"]["id"], "package_id": package["id"]},
        headers=ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_MACHINE_NOT_ACTIVATED)

    rows, _meta = validate_paginated(
        api.list_update_deliveries(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 0


def test_delivery_on_draft_package_rejected(api):
    """PRD section 3.6: "Four gates guard creation: the package must be
    `PUBLISHED` (`ERR_PACKAGE_NOT_PUBLISHED`)" — scheduling against a `DRAFT`
    package fails even when the machine is fully eligible.

    Design: Corner/validations/delivery_on_draft_package_rejected
    """
    ctx = setup_activated_machine(api)
    package = create_package(api)
    response = api.create_update_delivery(
        {"machine_id": ctx["machine"]["id"], "package_id": package["id"]},
        headers=ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_PACKAGE_NOT_PUBLISHED)
