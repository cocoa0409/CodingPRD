"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is restarted before every individual test and
therefore starts against an empty database.
"""
from . import factories as f
from .api_client import api_client
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
CARE = TEST_USERS["customer_service_headers"]
ANALYST = TEST_USERS["credit_analyst_headers"]
INSPECTOR = TEST_USERS["trade_in_inspector_headers"]
CUSTOMER = TEST_USERS["customer_headers"]

CLOCK_DAY_1 = "2026-09-02T00:00:00Z"


def _data(response, what):
    """Lenient setup validator: clear 'Setup failed' errors, not assertion noise."""
    assert 200 <= response.status_code < 300, (
        f"Setup failed: {what} returned HTTP {response.status_code}: "
        f"{response.text[:400]}"
    )
    return response.json()["data"]


def _post(method_call, what):
    return _data(method_call, what)


# ---------------------------------------------------------------------------
# Tier 1: clock and primitives
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601):
    """Advance the logical clock; scheduled transitions due by then fire."""
    return _post(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "advance clock")


def get_system_config():
    """Read the single system configuration row."""
    return _post(api_client.get_system_config(ADMIN), "read system config")


def create_account(**overrides):
    """Open a billing account; credit class and deposit are derived on creation."""
    return _post(
        api_client.create_account(f.account_payload(**overrides), ADMIN),
        "create account",
    )


def create_bare_line(account_id, mdn, billing_mode="PREPAID", **overrides):
    """Create a subscriber line in service_status PROVISIONED (not activated)."""
    payload = f.subscriber_line_payload(
        account_id, mdn, billing_mode=billing_mode, **overrides
    )
    return _post(api_client.create_subscriber_line(payload, ADMIN), "create line")


def activate_line(line_id, activation_at=None):
    """Activate service on a provisioned line."""
    payload = {}
    if activation_at is not None:
        payload["activation_at"] = activation_at
    return _post(
        api_client.activate_subscriber_line(line_id, payload, ADMIN), "activate line"
    )


def cancel_line(line_id, reason_code="NONPAYMENT"):
    return _post(
        api_client.cancel_subscriber_line(line_id, {"reason_code": reason_code}, ADMIN),
        "cancel line",
    )


def get_line(line_id):
    return _post(api_client.get_subscriber_line(line_id, ADMIN), "read line")


def line_version(line_id):
    """The version a client must echo back on one of the three versioned writes."""
    return get_line(line_id)["version"]


def get_account(account_id):
    return _post(api_client.get_account(account_id, ADMIN), "read account")


def create_activated_line(account_id, mdn, billing_mode="PREPAID", **overrides):
    """Create a line and take it to service_status ACTIVE."""
    line = create_bare_line(account_id, mdn, billing_mode=billing_mode, **overrides)
    activate_line(line["id"])
    return get_line(line["id"])


def create_rejection_code(rejection_code, **overrides):
    """Register a carrier rejection code in the reference catalog."""
    return _post(
        api_client.create_rejection_code(
            f.rejection_code_payload(rejection_code, **overrides), ADMIN
        ),
        f"create rejection code {rejection_code}",
    )


def open_account_with_line(mdn, billing_mode="PREPAID", account_overrides=None,
                           **line_overrides):
    """Account + one ACTIVATED line. Returns (account, line)."""
    account = create_account(**(account_overrides or {}))
    line = create_activated_line(account["id"], mdn, billing_mode=billing_mode,
                                 **line_overrides)
    return account, line


def open_account_with_lines(mdns, billing_mode="PREPAID", account_overrides=None):
    """Account + N activated lines, in the order supplied."""
    account = create_account(**(account_overrides or {}))
    lines = [create_activated_line(account["id"], mdn, billing_mode=billing_mode)
             for mdn in mdns]
    return account, lines


# ---------------------------------------------------------------------------
# Tier 2: port-in workflow
# ---------------------------------------------------------------------------

def create_draft_port_request(line, **overrides):
    """Open a DRAFT port request against a line, echoing the line's version."""
    payload = f.port_request_payload(line["id"], line_version(line["id"]), **overrides)
    return _post(api_client.create_port_request(payload, CARE), "create port request")


def submit_port_request(port_request, transfer_pin=None,
                        account_number_at_losing_carrier=None):
    payload = {
        "transfer_pin": transfer_pin or port_request["transfer_pin"],
        "account_number_at_losing_carrier": (
            account_number_at_losing_carrier
            or port_request["account_number_at_losing_carrier"]
        ),
    }
    return _post(
        api_client.submit_port_request(port_request["id"], payload, CARE),
        "submit port request",
    )


def record_rejection(port_request_id, rejection_code):
    return _post(
        api_client.record_port_rejection(
            port_request_id, {"rejection_code": rejection_code}, ADMIN
        ),
        f"record rejection {rejection_code}",
    )


def resubmit_port_request(port_request, transfer_pin=None,
                          account_number_at_losing_carrier=None):
    payload = {
        "transfer_pin": transfer_pin or port_request["transfer_pin"],
        "account_number_at_losing_carrier": (
            account_number_at_losing_carrier
            or port_request["account_number_at_losing_carrier"]
        ),
    }
    return _post(
        api_client.resubmit_port_request(port_request["id"], payload, CARE),
        "resubmit port request",
    )


def accept_port_request(port_request_id):
    return _post(
        api_client.accept_port_request(port_request_id, {}, ADMIN),
        "accept port request",
    )


def get_port_request(port_request_id):
    # PRD §3.11 makes the single request readable by "a platform operator, a care
    # agent, a credit analyst or a customer", so the operator identity used by the
    # rest of the setup helpers is a permitted reader.
    return _post(
        api_client.get_port_request(port_request_id, ADMIN), "read port request"
    )


def setup_pending_port_request(mdn, line_overrides=None, request_overrides=None):
    """Account + line + a port request in request_state PENDING.

    The line is left PROVISIONED/UNASSIGNED because PRD §3.1 requires the target
    line's `number_status` be `UNASSIGNED` or `RESERVED` at submission; an
    activated line is `ASSIGNED` and could not be submitted at all.
    Returns (account, line, port_request).
    """
    account = create_account()
    line = create_bare_line(account["id"], mdn, **(line_overrides or {}))
    # The port workflow begins at the clock's day-one reading, as every PRD §3.1
    # recipe does, so a rejection recorded afterwards carries that instant as its
    # `last_rejection_at` and the cooling-off arithmetic is measured from it.
    advance_clock(CLOCK_DAY_1)
    port_request = create_draft_port_request(line, **(request_overrides or {}))
    submitted = submit_port_request(port_request)
    return account, line, submitted


def setup_rejected_port_request(mdn, rejection_code, code_overrides=None,
                                line_overrides=None, request_overrides=None):
    """Account + ACTIVATED line + a port request in request_state REJECTED.

    The catalog row is registered first. Returns (account, line, port_request).
    """
    create_rejection_code(rejection_code, **(code_overrides or {}))
    account, line, port_request = setup_pending_port_request(
        mdn, line_overrides=line_overrides, request_overrides=request_overrides
    )
    record_rejection(port_request["id"], rejection_code)
    return account, line, get_port_request(port_request["id"])


def setup_ported_line(mdn, cutover_at="2026-09-05T00:00:00Z"):
    """Account + line carried all the way through to request_state PORTED.

    The line is born PROVISIONED/UNASSIGNED — PRD §3.1 requires the target line's
    `number_status` be `UNASSIGNED` or `RESERVED` at submission, and an activated
    line is `ASSIGNED`. PRD §3.8's port cutover cascade then sets `service_status`
    ACTIVE on the line when the cutover lands, so no pre-activation is needed.
    Returns (account, line, port_request).
    """
    account = create_account()
    line = create_bare_line(account["id"], mdn)
    advance_clock(CLOCK_DAY_1)
    port_request = create_draft_port_request(
        line, requested_cutover_at=cutover_at
    )
    submit_port_request(port_request)
    accept_port_request(port_request["id"])
    after = cutover_at if cutover_at > CLOCK_DAY_1 else CLOCK_DAY_1
    advance_clock(max(after, "2026-09-06T00:00:00Z"))
    return account, get_line(line["id"]), get_port_request(port_request["id"])


# ---------------------------------------------------------------------------
# Tier 2: protection cases
# ---------------------------------------------------------------------------

def create_protection_case(line, verified_identity=True, **overrides):
    payload = f.port_protection_case_payload(
        line["id"], verified_identity=verified_identity, **overrides
    )
    return _post(api_client.create_port_protection_case(payload, CARE),
                 "create protection case")


def resolve_protection_case(case_id, resolution):
    return _post(
        api_client.resolve_port_protection_case(case_id, {"resolution": resolution},
                                                ADMIN),
        f"resolve protection case {resolution}",
    )


def create_active_protection_case(line, **overrides):
    """Open a case and ACTIVATE it so the line reads port_protection_status PROTECTED."""
    case = create_protection_case(line, **overrides)
    resolve_protection_case(case["id"], "ACTIVATE")
    return case


# ---------------------------------------------------------------------------
# Tier 2: device financing and trade-in
# ---------------------------------------------------------------------------

def create_device_plan(line, **overrides):
    payload = f.device_plan_payload(line["id"], line_version(line["id"]), **overrides)
    return _post(api_client.create_device_plan(payload, CARE), "create device plan")


def get_device_plan(plan_id):
    return _post(api_client.get_device_plan(plan_id, ADMIN), "read device plan")


def create_activated_device_plan(line, activation_at=CLOCK_DAY_1, **overrides):
    return create_device_plan(line, activation_at=activation_at, **overrides)


def create_trade_in_assessment(plan_id, **overrides):
    payload = f.trade_in_assessment_payload(plan_id, **overrides)
    return _post(api_client.create_trade_in_assessment(payload, CARE),
                 "create trade-in assessment")


def grade_trade_in_assessment(assessment_id, graded_condition):
    return _post(
        api_client.grade_trade_in_assessment(
            assessment_id, {"graded_condition": graded_condition}, INSPECTOR
        ),
        f"grade trade-in {graded_condition}",
    )


def setup_plan_with_graded_trade_in(mdn, plan_overrides=None, declared="GOOD",
                                    graded="FAIR"):
    """Account + ACTIVE line + ACTIVE plan + a graded trade-in assessment.

    Returns (account, line, plan, assessment).
    """
    account = create_account()
    line = create_activated_line(account["id"], mdn, billing_mode="POSTPAID")
    advance_clock(CLOCK_DAY_1)
    plan = create_device_plan(line, activation_at=CLOCK_DAY_1, **(plan_overrides or {}))
    assessment = create_trade_in_assessment(plan["id"], declared_condition=declared)
    graded_assessment = grade_trade_in_assessment(assessment["id"], graded)
    return account, line, get_device_plan(plan["id"]), graded_assessment


# ---------------------------------------------------------------------------
# Tier 2: promotional credit schedules
# ---------------------------------------------------------------------------

def create_promo_schedule(line, **overrides):
    payload = f.promo_schedule_payload(line["id"], line_version(line["id"]),
                                       **overrides)
    return _post(api_client.create_promo_schedule(payload, CARE),
                 "create promo schedule")


def activate_promo_schedule(schedule_id):
    return _post(
        api_client.activate_promo_schedule(schedule_id, {}, CARE),
        "activate promo schedule",
    )


def claw_back_promo_schedule(schedule_id):
    return _post(
        api_client.claw_back_promo_schedule(schedule_id, {}, ADMIN),
        "claw back promo schedule",
    )


def get_promo_schedule(schedule_id):
    # PRD §3.11: promotional schedules are "individually readable by the roles
    # involved in their workflow", which includes the platform operator identity
    # the rest of the setup helpers use.
    return _post(api_client.get_promo_schedule(schedule_id, ADMIN),
                 "read promo schedule")


def create_active_promo_schedule(line, **overrides):
    """Create a schedule and bring it to schedule_state ACTIVE.

    The activate transition is permitted only at or after `window_start`; a
    schedule that comes back PROVISIONAL therefore has a window that has not yet
    opened on the logical clock, so the clock is advanced to the window before
    applying the credit.
    """
    schedule = create_promo_schedule(line, **overrides)
    if schedule["schedule_state"] == "PROVISIONAL":
        advance_clock(schedule["window_start"])
        activate_promo_schedule(schedule["id"])
        schedule = get_promo_schedule(schedule["id"])
    return schedule


# ---------------------------------------------------------------------------
# Tier 2: reservations, line additions, migrations
# ---------------------------------------------------------------------------

def create_reservation(account_id, mdn, **overrides):
    payload = f.number_reservation_payload(account_id, mdn, **overrides)
    return _post(api_client.create_number_reservation(payload, ADMIN),
                 "create reservation")


def commit_reservation(reservation_id, subscriber_line_id):
    return _post(
        api_client.commit_number_reservation(
            reservation_id, {"subscriber_line_id": subscriber_line_id}, ADMIN
        ),
        "commit reservation",
    )


def create_line_addition(account_id, line_count, **overrides):
    payload = f.line_addition_payload(account_id, line_count, **overrides)
    return _post(api_client.create_line_addition_request(payload, CARE),
                 "create line addition request")


def review_line_addition(request_id, decision="APPROVE", decision_note=None):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return _post(
        api_client.review_line_addition_request(request_id, payload, ANALYST),
        f"review line addition {decision}",
    )


def create_migration_request(line, **overrides):
    payload = f.migration_request_payload(line["id"], **overrides)
    return _post(api_client.create_migration_request(payload, CARE),
                 "create migration request")


def check_migration_eligibility(migration_id, changed_at=None):
    payload = {}
    if changed_at is not None:
        payload["changed_at"] = changed_at
    return _post(
        api_client.check_migration_eligibility(migration_id, payload, CARE),
        "check migration eligibility",
    )


def get_migration_request(migration_id):
    return _post(api_client.get_migration_request(migration_id, CARE),
                 "read migration request")


# ---------------------------------------------------------------------------
# Tier 3: composite setups shared by several claims
# ---------------------------------------------------------------------------

def setup_account_with_active_lines(line_count, mdn_offset=0, billing_mode="POSTPAID",
                                    account_overrides=None):
    """Account holding exactly `line_count` ACTIVE lines.

    Used wherever a claim depends on the account's active_line_count.
    Returns (account, lines).
    """
    account = create_account(**(account_overrides or {}))
    lines = []
    for index in range(line_count):
        lines.append(
            create_activated_line(
                account["id"], f.unique_mdn(mdn_offset + index),
                billing_mode=billing_mode,
            )
        )
    return account, lines


def setup_line_with_plan_and_schedule(mdn, plan_price_cents=40000,
                                      installment_months=24,
                                      schedule_overrides=None,
                                      activate_schedule=False):
    """ACTIVE PREPAID line carrying both an ACTIVE plan and a PROVISIONAL schedule.

    Returns (account, line, plan, schedule).
    """
    account = create_account()
    line = create_activated_line(account["id"], mdn, billing_mode="PREPAID")
    advance_clock(CLOCK_DAY_1)
    plan = create_device_plan(
        line,
        device_price_cents=plan_price_cents,
        down_payment_cents=0,
        installment_months=installment_months,
        activation_at=CLOCK_DAY_1,
    )
    schedule = create_promo_schedule(line, **(schedule_overrides or {}))
    if activate_schedule:
        activate_promo_schedule(schedule["id"])
        schedule = get_promo_schedule(schedule["id"])
    return account, get_line(line["id"]), get_device_plan(plan["id"]), schedule


def setup_protected_line_with_rejected_request(
    mdn, rejection_code="PORT_BLOCK", retry_after_hours=48,
    resubmission_allowed=True, requested_cutover_at="2026-09-20T00:00:00Z",
):
    """ACTIVE line carrying an ACTIVE protection case and a REJECTED port request.

    The catalog row is registered first so the rejection can be recorded.
    Returns (account, line, port_request, protection_case).
    """
    create_rejection_code(
        rejection_code,
        resubmission_allowed=resubmission_allowed,
        retry_after_hours=retry_after_hours,
    )
    account = create_account()
    line = create_bare_line(account["id"], mdn, billing_mode="PREPAID")
    advance_clock(CLOCK_DAY_1)
    port_request = create_draft_port_request(
        line, requested_cutover_at=requested_cutover_at
    )
    submit_port_request(port_request)
    record_rejection(port_request["id"], rejection_code)
    case = create_active_protection_case(line)
    return account, get_line(line["id"]), get_port_request(port_request["id"]), case


def setup_line_with_existing_schedule(mdn, window_start="2026-09-02T00:00:00Z",
                                      installment_months=1,
                                      retention_requirement_cycles=1,
                                      activate=True):
    """ACTIVE line carrying one short existing schedule, optionally ACTIVE.

    Returns (account, line, existing_schedule).
    """
    account = create_account()
    line = create_activated_line(account["id"], mdn, billing_mode="PREPAID")
    advance_clock(CLOCK_DAY_1)
    schedule = create_promo_schedule(
        line,
        window_start=window_start,
        installment_months=installment_months,
        retention_requirement_cycles=retention_requirement_cycles,
    )
    if activate:
        activate_promo_schedule(schedule["id"])
        schedule = get_promo_schedule(schedule["id"])
    return account, get_line(line["id"]), schedule


def setup_migration_with_anchor_lines(anchor_line_count, mdn_offset=0,
                                      prepaid_balance_cents=0,
                                      requested_cutover_at="2026-10-01T00:00:00Z"):
    """Account holding `anchor_line_count` ACTIVE lines plus a PREPAID line to migrate.

    The anchor lines exist so the account's active_line_count is a known value
    before the migration's own line is counted.
    Returns (account, anchor_lines, migrating_line, migration_request).
    """
    account = create_account()
    anchors = []
    for index in range(anchor_line_count):
        anchors.append(
            create_activated_line(account["id"], f.unique_mdn(mdn_offset + index),
                                  billing_mode="POSTPAID")
        )
    # The migrating line is deliberately left out of service: PRD §3.3's proration
    # rule reads the account's `active_line_count` "as observed before this
    # migration's line is counted", so the migrating line must not already be
    # contributing to that count. The cutover hop sets its `number_status` to
    # ASSIGNED on its own.
    migrating = create_bare_line(account["id"], f.unique_mdn(mdn_offset + 50),
                                 billing_mode="PREPAID")
    migration = create_migration_request(
        migrating,
        prepaid_balance_cents=prepaid_balance_cents,
        requested_cutover_at=requested_cutover_at,
    )
    return account, anchors, migrating, migration


def complete_migration(account, migrating_line, migration, cutover_at):
    """Schedule and complete a migration by advancing the clock to its cutover."""
    check_migration_eligibility(migration["id"])
    advance_clock(cutover_at)
    return get_migration_request(migration["id"])