"""Update delivery lifecycle: the consent-preserving retry loop, the mandatory
THROTTLED carve-out, and the two withdrawal/suspension cascades."""

from test_helpers import (
    SYSTEM,
    ApiErrorId,
    activate_machine_in,
    activate_plan,
    add_machine,
    add_published_package,
    create_grant,
    create_plan,
    grant_ticket,
    ingest_batch,
    open_session,
    provision_modem_success,
    read_delivery,
    read_grant,
    read_machine,
    read_plan,
    read_session,
    read_ticket,
    report_failed,
    report_installed,
    request_dealer_ticket,
    resume_org,
    schedule_delivery,
    setup_activated_machine,
    setup_delivery_downloading,
    start_download,
    suspend_org,
    validate_error,
    validate_paginated,
    withdraw_package,
)


def test_mandatory_package_downloads_while_throttled_optional_blocked(api):
    """PRD section 2.5: "Starting an update download requires `CONNECTED`,
    except that a mandatory package may also download while `THROTTLED`." On a
    machine throttled at exactly 80% of its STANDARD cap, the optional
    package's start fails with `ERR_MACHINE_POSTURE_BLOCKED` while the
    mandatory package's start succeeds.

    Design: Corner/cross_cutting/mandatory_package_downloads_while_throttled_optional_blocked
    """
    ctx = setup_activated_machine(api)
    machine_id = ctx["machine"]["id"]
    package_opt = add_published_package(ctx, api, package_code="FW-OPT")
    package_man = add_published_package(
        ctx, api, package_code="FW-SEC", firmware_version="10.2.1",
        size_mb=120, mandatory=True,
    )
    delivery_opt = schedule_delivery(api, machine_id, package_opt["id"])
    delivery_man = schedule_delivery(api, machine_id, package_man["id"])
    grant_ticket(ctx, api, delivery_opt["consent_ticket_id"])
    grant_ticket(ctx, api, delivery_man["consent_ticket_id"])

    ingest_batch(ctx, api, machine_id, batch_id="b-throttle",
                 start_hour_iso="2026-09-01T00:00:00Z", hour_count=2,
                 payload_mb=16384)
    machine = read_machine(ctx, api, machine_id)
    assert machine["connectivity_posture"] == "THROTTLED"

    response = api.start_update_download(delivery_opt["id"], headers=SYSTEM)
    validate_error(response, ApiErrorId.ERR_MACHINE_POSTURE_BLOCKED)

    delivery_man = start_download(api, delivery_man["id"])
    assert delivery_man["status"] == "DOWNLOADING"


def test_delivery_retry_from_failed_reaches_installed(api):
    """PRD section 3.6: "Starting a download is legal from `CONSENT_GRANTED`
    and — the consent-preserving retry loop — from `FAILED`, where no new
    ticket is minted and the already-consumed ticket is untouched. ... Each
    start increments `download_attempts`" and "The machine reports success,
    moving `DOWNLOADING` → `INSTALLED` — terminal — stamping `installed_at` and
    writing the package's `firmware_version` onto the machine's
    `modem_firmware_version`."

    Design: Difficulty/non_linear_state_machine/update_delivery_failed_retry_preserves_consumed_consent
    """
    ctx = setup_delivery_downloading(api)
    delivery_id = ctx["delivery"]["id"]

    report_failed(api, delivery_id, "CRC mismatch")
    delivery = start_download(api, delivery_id)
    assert delivery["status"] == "DOWNLOADING"
    assert delivery["download_attempts"] == 2

    delivery = report_installed(api, delivery_id)
    assert delivery["status"] == "INSTALLED"
    assert delivery["installed_at"] is not None
    machine = read_machine(ctx, api, ctx["machine"]["id"])
    assert machine["modem_firmware_version"] == "10.2.0"


def test_delivery_retry_mints_no_second_consent_ticket(api):
    """PRD section 3.6: "the consent-preserving retry loop — from `FAILED`,
    where no new ticket is minted and the already-consumed ticket is untouched"
    and PRD section 2.7: "Consent is consumed exactly once." — after a
    failure/retry/reinstall loop exactly one ticket exists for the machine and
    it stays `CONSUMED`.

    Design: Difficulty/non_linear_state_machine/update_delivery_failed_retry_preserves_consumed_consent
    """
    ctx = setup_delivery_downloading(api)
    delivery_id = ctx["delivery"]["id"]
    ticket_id = ctx["ticket_id"]

    report_failed(api, delivery_id, "CRC mismatch")
    start_download(api, delivery_id)
    report_installed(api, delivery_id)

    rows, _meta = validate_paginated(
        api.list_consent_tickets(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == ticket_id
    assert rows[0]["status"] == "CONSUMED"
    assert rows[0]["bound_delivery_id"] == delivery_id


def test_org_suspend_cascades_plan_posture_and_delivery(api):
    """PRD section 3.1: "Suspending an organization is a `PlatformAdmin` action
    with a deliberate cascade, in three links: every `ACTIVE` data plan of the
    organization transitions to `SUSPENDED`; each of those plan suspensions
    recomputes the covered machine's `connectivity_posture` to
    `PLAN_SUSPENDED`; and every machine whose posture becomes `PLAN_SUSPENDED`
    forces each of its in-flight `DOWNLOADING` update deliveries to `FAILED`
    with `failure_reason` set to `CONNECTIVITY_LOST`."

    Design: Difficulty/transitive_cascade/org_suspend_cascade_depth3_to_delivery
    """
    ctx = setup_delivery_downloading(api)
    suspend_org(api, ctx["org"]["id"])

    plan = read_plan(ctx, api, ctx["plan"]["id"])
    assert plan["status"] == "SUSPENDED"
    machine = read_machine(ctx, api, ctx["machine"]["id"])
    assert machine["connectivity_posture"] == "PLAN_SUSPENDED"
    delivery = read_delivery(ctx, api, ctx["delivery"]["id"])
    assert delivery["status"] == "FAILED"
    assert delivery["failure_reason"] == "CONNECTIVITY_LOST"


def test_org_suspend_fanout_and_resume_revives_nothing(api):
    """PRD section 3.1: "In the same action, every `ACTIVE` data share grant of
    the organization transitions to `SUSPENDED`, and every `OPEN` diagnostic
    session on the organization's machines transitions to `CLOSED` with
    `closed_reason` `ACCESS_WITHDRAWN`." and "Resuming an organization restores
    it to `ACTIVE` and increments its `version`, but deliberately revives
    nothing: plans stay `SUSPENDED`, grants stay `SUSPENDED`, and failed
    deliveries stay `FAILED` — each child must be resumed or retried
    individually."

    Design: Difficulty/transitive_cascade/org_suspend_cascade_depth3_to_delivery
    """
    ctx = setup_delivery_downloading(api)
    grant = create_grant(ctx, api, grantee_type="AGRONOMIST",
                         grantee_ref_id="agron-ada", scopes=["TELEMATICS"])
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket["id"])
    session = open_session(ctx, api, ctx["machine"]["id"], ticket["id"])

    suspend_org(api, ctx["org"]["id"])
    grant = read_grant(ctx, api, grant["id"])
    assert grant["status"] == "SUSPENDED"
    session = read_session(ctx, api, session["id"])
    assert session["status"] == "CLOSED"
    assert session["closed_reason"] == "ACCESS_WITHDRAWN"
    delivery = read_delivery(ctx, api, ctx["delivery"]["id"])
    assert delivery["status"] == "FAILED"

    resume_org(api, ctx["org"]["id"])
    plan = read_plan(ctx, api, ctx["plan"]["id"])
    assert plan["status"] == "SUSPENDED"
    grant = read_grant(ctx, api, grant["id"])
    assert grant["status"] == "SUSPENDED"
    delivery = read_delivery(ctx, api, ctx["delivery"]["id"])
    assert delivery["status"] == "FAILED"


def test_package_withdraw_cancels_pending_deliveries(api):
    """PRD section 3.6: "withdrawal cascades: every delivery of the package
    still in `AWAITING_CONSENT` or `CONSENT_GRANTED` transitions to
    `CANCELLED`, and each cancelled delivery's consent ticket, if still
    `REQUESTED` or `GRANTED`, transitions to `REVOKED`."

    Design: Difficulty/transitive_cascade/package_withdraw_cascade_depth2_to_consent
    """
    ctx = setup_activated_machine(api)
    machine2 = add_machine(ctx, api, serial_number="SN-0002",
                           modem_imei="IMEI-0002")
    provision_modem_success(ctx, api, machine2["id"])
    plan2 = create_plan(ctx, api, machine2["id"])
    activate_plan(ctx, api, plan2["id"])
    activate_machine_in(ctx, api, machine2["id"])

    package = add_published_package(ctx, api)
    delivery1 = schedule_delivery(api, ctx["machine"]["id"], package["id"])
    delivery2 = schedule_delivery(api, machine2["id"], package["id"])
    grant_ticket(ctx, api, delivery2["consent_ticket_id"])

    withdraw_package(api, package["id"])
    delivery1 = read_delivery(ctx, api, delivery1["id"])
    delivery2 = read_delivery(ctx, api, delivery2["id"])
    assert delivery1["status"] == "CANCELLED"
    assert delivery2["status"] == "CANCELLED"


def test_package_withdraw_revokes_bound_consent_tickets(api):
    """PRD section 3.6: "each cancelled delivery's consent ticket, if still
    `REQUESTED` or `GRANTED`, transitions to `REVOKED`" — the cascade reaches
    both a never-decided (`REQUESTED`) ticket and a granted one.

    Design: Difficulty/transitive_cascade/package_withdraw_cascade_depth2_to_consent
    """
    ctx = setup_activated_machine(api)
    machine2 = add_machine(ctx, api, serial_number="SN-0002",
                           modem_imei="IMEI-0002")
    provision_modem_success(ctx, api, machine2["id"])
    plan2 = create_plan(ctx, api, machine2["id"])
    activate_plan(ctx, api, plan2["id"])
    activate_machine_in(ctx, api, machine2["id"])

    package = add_published_package(ctx, api)
    delivery1 = schedule_delivery(api, ctx["machine"]["id"], package["id"])
    delivery2 = schedule_delivery(api, machine2["id"], package["id"])
    grant_ticket(ctx, api, delivery2["consent_ticket_id"])

    withdraw_package(api, package["id"])
    ticket1 = read_ticket(ctx, api, delivery1["consent_ticket_id"])
    ticket2 = read_ticket(ctx, api, delivery2["consent_ticket_id"])
    assert ticket1["status"] == "REVOKED"
    assert ticket2["status"] == "REVOKED"
