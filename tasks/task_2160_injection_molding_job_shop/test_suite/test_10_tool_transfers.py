"""Handing a tool to its customer: the three-step transfer and its deepest cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_production_job_payload,
    create_second_customer,
    decide_transfer,
    mold_version,
    read_job,
    read_mold,
    read_press,
    read_qualification,
    read_transfer,
    request_and_approve_transfer,
    request_transfer,
    setup_approved_tool,
    setup_staged_job,
    validate_error,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
PE = TEST_USERS["process_engineer_headers"]


def test_completing_a_transfer_rewrites_the_tool_and_revokes_its_qualifications(api):
    """PRD §3.9: "On success the transfer moves `APPROVED → COMPLETED` and the tool
    is rewritten in one step: `ownership` becomes `CUSTOMER_OWNED`, `customer_id`
    becomes the `to_customer_id`, the lifecycle status moves `PPAP_APPROVED →
    TRANSFERRED`, `active_transfer_id` is cleared, and `version` is incremented by
    1. The tool's arrival at `TRANSFERRED` then fires its own cascade — every
    `QUALIFIED` qualification row on that tool moves `QUALIFIED → REVOKED` — and
    each of those revocations fires its own cascade in turn, cancelling every
    `DRAFT`, `SCHEDULED` and `BLOCKED` job on that tool-and-machine pair with
    `block_reason` `QUALIFICATION_REVOKED`. Three links, one request."
    PRD §3.9: "The request snapshots the tool's current `ownership` into
    `from_ownership`, writes its own id onto the tool as `active_transfer_id`,
    increments the tool's `version` by 1, and lands in `REQUESTED`."

    Design: Difficulty/transitive_cascade/tool_transfer_completion_revokes_qualification_and_cancels_job
    """
    shop = setup_staged_job()
    acquirer = create_second_customer()
    transfer = request_and_approve_transfer(shop["mold"]["id"], acquirer["id"])

    completed = validate_success(
        api.complete_tool_transfer(
            transfer["id"], {"expected_mold_version": mold_version(shop["mold"]["id"])}, PA
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["from_ownership"] == "SHOP_OWNED"
    mold = read_mold(shop["mold"]["id"])
    assert mold["ownership"] == "CUSTOMER_OWNED"
    assert mold["status"] == "TRANSFERRED"
    assert mold["customer_id"] == acquirer["id"]
    assert mold.get("active_transfer_id") is None
    assert read_qualification(shop["qualification"]["id"])["status"] == "REVOKED"


def test_the_revocation_cascade_cancels_the_pairs_job_and_frees_the_press(api):
    """PRD §3.2: "Each revocation is itself a cascade origin: every job that names
    both that tool and that machine and whose `run_status` is `DRAFT`, `SCHEDULED`
    or `BLOCKED` is driven to `CANCELLED` with its `block_reason` set to
    `QUALIFICATION_REVOKED`."
    PRD §3.6: "Cancelling a `SCHEDULED` or a `RUNNING` job releases its duration
    from the press's `committed_minutes_scheduled` and increments the press's
    `version` by 1, and moves `material_status` `STAGED → UNSTAGED` with
    `staged_resin_lot_id` cleared."

    Design: Difficulty/transitive_cascade/tool_transfer_completion_revokes_qualification_and_cancels_job
    """
    shop = setup_staged_job()
    acquirer = create_second_customer()
    transfer = request_and_approve_transfer(shop["mold"]["id"], acquirer["id"])
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480

    validate_success(
        api.complete_tool_transfer(
            transfer["id"], {"expected_mold_version": mold_version(shop["mold"]["id"])}, PA
        )
    )

    job = read_job(shop["job"]["id"])
    assert job["run_status"] == "CANCELLED"
    assert job["block_reason"] == "QUALIFICATION_REVOKED"
    assert job["material_status"] == "UNSTAGED"
    assert job.get("staged_resin_lot_id") is None
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 0


def test_a_transfer_in_flight_and_then_a_completed_one_each_block_new_work(api):
    """PRD §3.9: "Only one transfer per tool may hold `REQUESTED` or `APPROVED` at a
    time; a second request, or any job operation attempted on a tool while
    `active_transfer_id` is set, is rejected with `ERR_MOLD_TRANSFER_IN_PROGRESS`."
    PRD §3.1: "Once a tool is `RETIRED` or `TRANSFERRED`, operations targeting it
    are rejected with `ERR_MOLD_RETIRED` or `ERR_MOLD_TRANSFERRED` respectively."

    Design: Corner/errors/transfer_lifecycle_blocks_job_creation_before_and_after_completion
    """
    shop = setup_approved_tool(with_lot=False)
    acquirer = create_second_customer()
    transfer = request_transfer(shop["mold"]["id"], acquirer["id"])
    assert transfer["status"] == "REQUESTED"

    payload = create_production_job_payload(
        shop["quote"]["id"], planned_qty=1000, press_id=shop["press"]["id"]
    )
    in_progress = api.create_production_job(payload, PE)
    assert in_progress.status_code == 409, f"Expected 409, got {in_progress.status_code}"
    validate_error(in_progress, ApiErrorId.ERR_MOLD_TRANSFER_IN_PROGRESS.value)

    decide_transfer(transfer["id"], "APPROVE", reason="buy-out agreed")
    validate_success(
        api.complete_tool_transfer(
            transfer["id"], {"expected_mold_version": mold_version(shop["mold"]["id"])}, PA
        )
    )
    mold = read_mold(shop["mold"]["id"])
    assert mold["status"] == "TRANSFERRED"
    assert mold["ownership"] == "CUSTOMER_OWNED"
    assert mold.get("active_transfer_id") is None

    transferred = api.create_production_job(payload, PE)
    assert transferred.status_code == 409, f"Expected 409, got {transferred.status_code}"
    validate_error(transferred, ApiErrorId.ERR_MOLD_TRANSFERRED.value)
    assert read_qualification(shop["qualification"]["id"])["status"] == "REVOKED"


def test_a_declined_transfer_can_never_be_completed(api):
    """PRD §3.9: "It requires the transfer's `status` to be `APPROVED` — otherwise
    `ERR_TRANSFER_NOT_APPROVED` — and requires that no job on that tool is currently
    `RUNNING`, otherwise `ERR_MOLD_TRANSFER_IN_PROGRESS`."
    PRD §3.9: "A decline moves the transfer `REQUESTED → DECLINED`, clears the
    tool's `active_transfer_id` back to unset and increments the tool's `version` by
    1, releasing the tool for production work again. `DECLINED` and `COMPLETED` are
    the transfer's terminal states."

    Design: Corner/state_machines/tool_transfer_complete_on_declined_returns_transfer_not_approved
    """
    shop = setup_approved_tool(with_lot=False)
    acquirer = create_second_customer()
    transfer = request_transfer(shop["mold"]["id"], acquirer["id"])
    decide_transfer(transfer["id"], "DECLINE", reason="buy-out price not agreed")

    response = api.complete_tool_transfer(
        transfer["id"], {"expected_mold_version": mold_version(shop["mold"]["id"])}, PA
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_TRANSFER_NOT_APPROVED.value)
    assert read_transfer(transfer["id"])["status"] == "DECLINED"
    mold = read_mold(shop["mold"]["id"])
    assert mold["ownership"] == "SHOP_OWNED"
    assert mold["customer_id"] == shop["customer"]["id"]
    assert mold.get("active_transfer_id") is None


def test_completing_with_a_stale_mold_version_is_rejected_and_retries_cleanly(api):
    """PRD §2.5: "Completing a tool transfer, which rewrites the mold's ownership
    and customer, requires `expected_mold_version` matching the mold's current
    `version`. A mismatch is rejected with `ERR_STALE_MOLD_VERSION` (HTTP 412)."
    PRD §3.9: "The request snapshots the tool's current `ownership` into
    `from_ownership`, writes its own id onto the tool as `active_transfer_id`,
    increments the tool's `version` by 1, and lands in `REQUESTED`."

    Design: Corner/cross_cutting_layers/stale_mold_version_on_transfer_complete_returns_412
    """
    shop = setup_approved_tool(with_lot=False)
    acquirer = create_second_customer()
    version_pre = mold_version(shop["mold"]["id"])
    transfer = request_and_approve_transfer(shop["mold"]["id"], acquirer["id"])

    stale = api.complete_tool_transfer(
        transfer["id"], {"expected_mold_version": version_pre}, PA
    )
    assert stale.status_code == 412, f"Expected 412, got {stale.status_code}"
    validate_error(stale, ApiErrorId.ERR_STALE_MOLD_VERSION.value)
    assert read_transfer(transfer["id"])["status"] == "APPROVED"
    assert read_mold(shop["mold"]["id"])["ownership"] == "SHOP_OWNED"

    version_now = mold_version(shop["mold"]["id"])
    assert version_now > version_pre

    retry = validate_success(
        api.complete_tool_transfer(
            transfer["id"], {"expected_mold_version": version_now}, PA
        )
    )
    assert retry["status"] == "COMPLETED"
    assert read_mold(shop["mold"]["id"])["status"] == "TRANSFERRED"
