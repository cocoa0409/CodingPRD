"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints only —
each test runs against an empty database. Setup calls go through the lenient
get_success_data() validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion failure inside a test.

Identity threading: a BrokerAdmin's X-User-ID is the DataBroker's id and a
Consumer's X-User-ID is the Consumer's id, so every ownership-gated call below
uses make_broker_admin_headers(broker["id"]) / make_consumer_headers(
consumer["id"]) rather than the shared header constants.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import days_after
from .constants import (
    CLOCK_TEST_INSTANT,
    REQUIRED_DISCLOSURE_CATEGORIES,
    TEST_DEFAULTS,
)
from .factories import (
    DISCLOSURE_CONTENT,
    create_broker_payload,
    create_consumer_payload,
    create_deletion_request_payload,
    create_disclosure_payload,
    create_downstream_recipient_payload,
    create_fee_deposit_payload,
    create_registration_payload,
    create_regulator_inquiry_payload,
    create_verification_attempt_payload,
)
from .test_users import (
    REVIEWER_ALPHA_HEADERS,
    REVIEWER_BETA_HEADERS,
    TEST_USERS,
    make_broker_admin_headers,
    make_consumer_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE_AGENT = TEST_USERS["intake_agent_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
STATE_PLATFORM = TEST_USERS["state_platform_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(instant: str = CLOCK_TEST_INSTANT) -> str:
    """Pin the server's logical clock. Every composite helper below that takes a
    `clock` argument calls this first; pass clock=None to leave it untouched."""
    get_success_data(api_client.set_clock(instant, PLATFORM_ADMIN))
    return instant


def run_sweep() -> dict:
    """Run the deferred-action compliance sweep at the current clock instant."""
    return get_success_data(api_client.run_compliance_sweep(PLATFORM_ADMIN))


# ---------------------------------------------------------------------------
# Reads (used to refresh a projection after a cascade)
# ---------------------------------------------------------------------------


def fetch_broker(broker_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_broker(broker_id, headers or make_broker_admin_headers(broker_id))
    )


def fetch_registration(registration_id: str, headers) -> dict:
    return get_success_data(api_client.get_registration(registration_id, headers))


def fetch_consumer(consumer_id: str, headers) -> dict:
    return get_success_data(api_client.get_consumer(consumer_id, headers))


def fetch_deletion_request(request_id: str, headers) -> dict:
    return get_success_data(api_client.get_deletion_request(request_id, headers))


def fetch_propagation_task(task_id: str, headers) -> dict:
    return get_success_data(api_client.get_propagation_task(task_id, headers))


def fetch_recipient(recipient_id: str, headers) -> dict:
    return get_success_data(api_client.get_downstream_recipient(recipient_id, headers))


def fetch_suppression_entry(entry_id: str, headers) -> dict:
    return get_success_data(api_client.get_suppression_entry(entry_id, headers))


def fetch_inquiry(inquiry_id: str, headers) -> dict:
    return get_success_data(api_client.get_regulator_inquiry(inquiry_id, headers))


def list_audit_events(broker_id: str, headers, **params) -> list:
    return get_success_data(
        api_client.list_audit_events(broker_id, headers, params=params or None)
    )


# ---------------------------------------------------------------------------
# Tier 1: broker onboarding and registry filings
# ---------------------------------------------------------------------------


def onboard_broker(
    operating_state_codes=("CA",),
    deposit_cents=TEST_DEFAULTS["FEE_DEPOSIT_CENTS"],
    clock=None,
    **overrides,
) -> dict:
    """Create a broker and credit its filing-fee account.

    Returns a context dict: broker, broker_id, broker_headers.
    """
    if clock:
        set_clock(clock)
    payload = create_broker_payload(
        operating_state_codes=list(operating_state_codes),
        home_state_code=overrides.pop("home_state_code", operating_state_codes[0]),
        **overrides,
    )
    broker = get_success_data(api_client.create_broker(payload, PLATFORM_ADMIN))
    broker_headers = make_broker_admin_headers(broker["id"])
    if deposit_cents:
        broker = get_success_data(
            api_client.create_fee_deposit(
                broker["id"],
                create_fee_deposit_payload(amount_cents=deposit_cents),
                broker_headers,
            )
        )
    return {
        "broker": broker,
        "broker_id": broker["id"],
        "broker_headers": broker_headers,
    }


def open_draft_registration(
    broker_id: str,
    broker_headers: dict,
    state_code: str = "CA",
    expected_broker_version=None,
    **overrides,
) -> dict:
    """Open one DRAFT filing, reading the broker's live version when the caller
    does not pin one explicitly."""
    if expected_broker_version is None:
        expected_broker_version = fetch_broker(broker_id, broker_headers)["version"]
    payload = create_registration_payload(
        broker_id, expected_broker_version, state_code=state_code, **overrides
    )
    return get_success_data(api_client.create_registration(payload, broker_headers))


def add_disclosures(
    registration_id: str,
    broker_headers: dict,
    categories=REQUIRED_DISCLOSURE_CATEGORIES,
    sensitive_categories=(),
    content_overrides=None,
) -> list:
    """Attach one disclosure per category. `sensitive_categories` names the
    categories filed with covers_sensitive_categories true."""
    content_overrides = content_overrides or {}
    items = []
    for category in categories:
        payload = create_disclosure_payload(
            category,
            content=content_overrides.get(
                category, DISCLOSURE_CONTENT.get(category, DISCLOSURE_CONTENT["SOURCES"])
            ),
            covers_sensitive_categories=category in sensitive_categories,
        )
        items.append(
            get_success_data(
                api_client.create_disclosure(registration_id, payload, broker_headers)
            )
        )
    return items


def submit_registration(registration_id: str, broker_headers: dict) -> dict:
    return get_success_data(
        api_client.submit_registration(registration_id, broker_headers)
    )


def accept_registration(registration_id: str) -> dict:
    return get_success_data(
        api_client.accept_registration(registration_id, PLATFORM_ADMIN)
    )


def setup_accepted_registration(
    state_code: str = "CA",
    operating_state_codes=("CA",),
    deposit_cents=TEST_DEFAULTS["FEE_DEPOSIT_CENTS"],
    categories=REQUIRED_DISCLOSURE_CATEGORIES,
    sensitive_categories=(),
    clock=CLOCK_TEST_INSTANT,
    coverage_period_start=TEST_DEFAULTS["COVERAGE_PERIOD_START"],
    coverage_period_end=TEST_DEFAULTS["COVERAGE_PERIOD_END"],
    **broker_overrides,
) -> dict:
    """Broker with credit plus one ACCEPTED filing for `state_code`.

    Returns broker, broker_id, broker_headers, registration, registration_id,
    disclosures.
    """
    ctx = onboard_broker(
        operating_state_codes=operating_state_codes,
        deposit_cents=deposit_cents,
        clock=clock,
        **broker_overrides,
    )
    registration = open_draft_registration(
        ctx["broker_id"],
        ctx["broker_headers"],
        state_code=state_code,
        coverage_period_start=coverage_period_start,
        coverage_period_end=coverage_period_end,
    )
    ctx["disclosures"] = add_disclosures(
        registration["id"],
        ctx["broker_headers"],
        categories=categories,
        sensitive_categories=sensitive_categories,
    )
    submit_registration(registration["id"], ctx["broker_headers"])
    ctx["registration"] = accept_registration(registration["id"])
    ctx["registration_id"] = registration["id"]
    ctx["broker"] = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: recipients, consumers and deletion intake
# ---------------------------------------------------------------------------


def register_recipient(
    broker_id: str, broker_headers: dict, **overrides
) -> dict:
    """Register one downstream recipient of the broker's data."""
    payload = create_downstream_recipient_payload(broker_id, **overrides)
    return get_success_data(
        api_client.create_downstream_recipient(payload, broker_headers)
    )


def record_consumer(
    broker_id: str, headers=None, state_code: str = "CA", **overrides
) -> dict:
    """Record one consumer of the broker. Returns the consumer projection."""
    payload = create_consumer_payload(broker_id, state_code=state_code, **overrides)
    return get_success_data(
        api_client.create_consumer(payload, headers or INTAKE_AGENT)
    )


def open_deletion_request(
    broker_id: str,
    consumer: dict,
    headers=None,
    expected_consumer_version=None,
    **overrides,
) -> dict:
    """Intake one deletion request against the consumer's live version."""
    if expected_consumer_version is None:
        expected_consumer_version = consumer["version"]
    payload = create_deletion_request_payload(
        broker_id, consumer["id"], expected_consumer_version, **overrides
    )
    return get_success_data(
        api_client.create_deletion_request(payload, headers or INTAKE_AGENT)
    )


def record_verification_attempt(
    request_id: str, headers=None, **overrides
) -> dict:
    payload = create_verification_attempt_payload(**overrides)
    return get_success_data(
        api_client.create_verification_attempt(
            request_id, payload, headers or INTAKE_AGENT
        )
    )


def decide_verification(
    request_id: str, decision: str = "VERIFIED", headers=REVIEWER_ALPHA_HEADERS
) -> dict:
    return get_success_data(
        api_client.decide_verification(request_id, {"decision": decision}, headers)
    )


def setup_consumer_of_broker(
    state_code: str = "CA",
    consumer_state_code=None,
    derived_profile_count: int = 0,
    sensitive_categories=None,
    recipient_count: int = 0,
    clock=CLOCK_TEST_INSTANT,
    **kwargs,
) -> dict:
    """Broker with an ACCEPTED filing plus one consumer, and optionally N ACTIVE
    downstream recipients.

    Returns the accepted-registration context extended with consumer,
    consumer_id, consumer_headers, recipients.
    """
    recipient_overrides = kwargs.pop("recipient_overrides", {})
    ctx = setup_accepted_registration(state_code=state_code, clock=clock, **kwargs)
    ctx["recipients"] = [
        register_recipient(
            ctx["broker_id"],
            ctx["broker_headers"],
            name=f"Cobalt Lead Services {index + 1}",
            **recipient_overrides,
        )
        for index in range(recipient_count)
    ]
    if ctx["recipients"]:
        ctx["recipient"] = ctx["recipients"][0]
        ctx["recipient_id"] = ctx["recipients"][0]["id"]
    consumer_payload = {}
    if sensitive_categories:
        consumer_payload["sensitive_categories"] = list(sensitive_categories)
    consumer = record_consumer(
        ctx["broker_id"],
        state_code=consumer_state_code or state_code,
        derived_profile_count=derived_profile_count,
        **consumer_payload,
    )
    ctx["consumer"] = consumer
    ctx["consumer_id"] = consumer["id"]
    ctx["consumer_headers"] = make_consumer_headers(consumer["id"])
    return ctx


def setup_received_deletion_request(intake_channel="DIRECT_PORTAL", **kwargs) -> dict:
    """Consumer context plus one RECEIVED deletion request."""
    request_overrides = kwargs.pop("request_overrides", {})
    ctx = setup_consumer_of_broker(**kwargs)
    request = open_deletion_request(
        ctx["broker_id"],
        ctx["consumer"],
        intake_channel=intake_channel,
        **request_overrides,
    )
    ctx["request"] = request
    ctx["request_id"] = request["id"]
    return ctx


def setup_verified_deletion_request(
    attempt_overrides=None, decider=REVIEWER_ALPHA_HEADERS, **kwargs
) -> dict:
    """Deletion request carried through a passing identity check into VERIFIED.

    Returns the received-request context extended with attempt and the refreshed
    request projection.
    """
    ctx = setup_received_deletion_request(**kwargs)
    ctx["attempt"] = record_verification_attempt(
        ctx["request_id"], **(attempt_overrides or {})
    )
    ctx["request"] = decide_verification(
        ctx["request_id"], "VERIFIED", headers=decider
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: execution and the propagation plan
# ---------------------------------------------------------------------------


def execute_deletion_request(request_id: str, headers=REVIEWER_BETA_HEADERS) -> dict:
    """Execute the deletion. The executing X-User-ID must differ from the
    reviewer who decided the verification."""
    return get_success_data(
        api_client.execute_deletion_request(request_id, headers)
    )


def list_tasks(request_id: str, headers, **params) -> list:
    params = {"deletion_request_id": request_id, **params}
    return get_success_data(api_client.list_propagation_tasks(headers, params=params))


def find_task(
    request_id: str, headers, target_kind=None, recipient_id=None
) -> dict:
    """The single task of this request matching target_kind and/or recipient_id."""
    params = {}
    if target_kind:
        params["target_kind"] = target_kind
    if recipient_id:
        params["recipient_id"] = recipient_id
    tasks = list_tasks(request_id, headers, **params)
    assert tasks, (
        f"Setup expected a propagation task for request {request_id} "
        f"matching {params}, found none"
    )
    return tasks[0]


def setup_executing_deletion_request(executor=REVIEWER_BETA_HEADERS, **kwargs) -> dict:
    """Deletion request executed, with its minted propagation tasks indexed.

    Returns the verified-request context extended with request (EXECUTING),
    tasks (list) and tasks_by_kind (target_kind -> task).
    """
    ctx = setup_verified_deletion_request(**kwargs)
    ctx["request"] = execute_deletion_request(ctx["request_id"], headers=executor)
    ctx["tasks"] = list_tasks(ctx["request_id"], ctx["broker_headers"])
    ctx["tasks_by_kind"] = {}
    for task in ctx["tasks"]:
        ctx["tasks_by_kind"].setdefault(task["target_kind"], task)
    return ctx


def dispatch_task(task_id: str, headers) -> dict:
    return get_success_data(api_client.dispatch_propagation_task(task_id, headers))


def ack_task(task_id: str, headers) -> dict:
    return get_success_data(api_client.ack_propagation_task(task_id, headers))


def dispatch_and_ack_task(task_id: str, headers) -> dict:
    dispatch_task(task_id, headers)
    return ack_task(task_id, headers)


def fail_task(task_id: str, headers, failure_code="RECIPIENT_UNREACHABLE") -> dict:
    return get_success_data(
        api_client.fail_propagation_task(task_id, {"failure_code": failure_code}, headers)
    )


def waive_task(task_id: str, headers, waiver_justification=None) -> dict:
    justification = waiver_justification or (
        "Archive tier schema cannot represent the purge marker; legal sign-off "
        "recorded."
    )
    return get_success_data(
        api_client.waive_propagation_task(
            task_id, {"waiver_justification": justification}, headers
        )
    )


def set_recipient_status(recipient_id: str, status: str, headers) -> dict:
    return get_success_data(
        api_client.set_recipient_status(recipient_id, {"status": status}, headers)
    )


# ---------------------------------------------------------------------------
# Tier 4: completion join, suppression and opt-out signals
# ---------------------------------------------------------------------------


def find_suppression_entries(headers, **params) -> list:
    return get_success_data(
        api_client.list_suppression_entries(headers, params=params or None)
    )


def suppression_for_request(request_id: str, headers) -> dict:
    entries = find_suppression_entries(headers, originating_request_id=request_id)
    assert entries, (
        f"Setup expected a suppression entry minted by request {request_id}, "
        "found none"
    )
    return entries[0]


def setup_completed_deletion_request(**kwargs) -> dict:
    """Deletion request driven all the way through the completion join: every
    internal task dispatched and acknowledged, so the request closes, the
    consumer is purged and a suppression entry is minted.

    Returns the executing-request context extended with the refreshed request,
    consumer and the minted suppression entry.
    """
    ctx = setup_executing_deletion_request(**kwargs)
    for task in ctx["tasks"]:
        dispatch_and_ack_task(task["id"], ctx["broker_headers"])
    ctx["request"] = fetch_deletion_request(ctx["request_id"], ctx["broker_headers"])
    ctx["consumer"] = fetch_consumer(ctx["consumer_id"], ctx["broker_headers"])
    ctx["suppression"] = suppression_for_request(ctx["request_id"], ctx["broker_headers"])
    ctx["suppression_id"] = ctx["suppression"]["id"]
    ctx["broker"] = fetch_broker(ctx["broker_id"], ctx["broker_headers"])
    return ctx


def create_suppression_entry(
    broker_id: str,
    consumer_id: str,
    headers=REVIEWER_ALPHA_HEADERS,
    originating_request_id=None,
    source_scope="ALL_SOURCES",
    **overrides,
) -> dict:
    payload = {
        "broker_id": broker_id,
        "consumer_id": consumer_id,
        "originating_request_id": originating_request_id,
        "source_scope": source_scope,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_suppression_entry(payload, headers))


def create_opt_out_signal(
    broker_id: str,
    consumer: dict,
    headers=None,
    signal_type="WRITTEN_REQUEST",
    scope="SALE_AND_SHARING",
    expected_consumer_version=None,
    **overrides,
) -> dict:
    payload = {
        "broker_id": broker_id,
        "consumer_id": consumer["id"],
        "signal_type": signal_type,
        "scope": scope,
        "expected_consumer_version": (
            consumer["version"]
            if expected_consumer_version is None
            else expected_consumer_version
        ),
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_opt_out_signal(payload, headers or INTAKE_AGENT)
    )


# ---------------------------------------------------------------------------
# Tier 5: regulator inquiries over the audit trail
# ---------------------------------------------------------------------------


def open_inquiry(
    broker_id: str, response_due_at=None, headers=REGULATOR, **overrides
) -> dict:
    """Open a regulator inquiry. The deadline defaults to 30 days after the
    standard test instant, which is strictly after the clock."""
    payload = create_regulator_inquiry_payload(
        broker_id,
        response_due_at or days_after(CLOCK_TEST_INSTANT, 30),
        **overrides,
    )
    return get_success_data(api_client.create_regulator_inquiry(payload, headers))


def respond_to_inquiry(inquiry_id: str, cited_audit_event_ids, headers) -> dict:
    return get_success_data(
        api_client.respond_to_inquiry(
            inquiry_id, {"cited_audit_event_ids": list(cited_audit_event_ids)}, headers
        )
    )


def audit_event_ids_by_type(broker_id: str, headers, event_types) -> list:
    """One audit event id per requested event_type, in the order requested."""
    ids = []
    for event_type in event_types:
        events = list_audit_events(broker_id, headers, event_type=event_type)
        assert events, (
            f"Setup expected at least one {event_type} audit event for broker "
            f"{broker_id}, found none"
        )
        ids.append(events[0]["id"])
    return ids


def setup_inquiry_over_completed_request(**kwargs) -> dict:
    """A completed deletion lifecycle plus an OPEN regulator inquiry into it, so
    the broker has a rich audit trail to cite.

    Returns the completed-request context extended with inquiry and inquiry_id.
    """
    ctx = setup_completed_deletion_request(**kwargs)
    ctx["inquiry"] = open_inquiry(ctx["broker_id"])
    ctx["inquiry_id"] = ctx["inquiry"]["id"]
    return ctx
