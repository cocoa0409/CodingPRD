"""Contractual support in minutes: which developers may open which severity of partner ticket,
the shape rules that separate a partner ticket from a platform incident, the ordering the
communication log insists on, the cadence figure the walk of checkpoints produces, the tier
entitlement the escalation channel demands, and the sixty-minute buffer that coalesces repeat
incidents on one product.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.test_users import PLATFORM_ADMIN, SUPPORT_AGENT


def test_a_standard_tier_holder_may_open_an_s3_ticket_but_not_an_s2(api, programme):
    """A developer whose only live entitlement is standard tier is not admitted to the urgent
    severities: its S2 ticket is refused and stored nowhere, while the same ticket at S3 opens
    with the four-hour first-response commitment.

    PRD: "A second entitlement gate applies to urgency: an `S1` or `S2` `PARTNER_TICKET` may only be opened by a developer holding an `ACTIVE` entitlement whose `tier` is `PARTNER` or `PRIVILEGED`, otherwise `ERR_SEVERITY_NOT_ENTITLED` (HTTP 422)."

    PRD: "For a `PARTNER_TICKET` the commitment is **30 minutes** at `S1`, **60 minutes** at `S2`, **240 minutes** at `S3` and **480 minutes** at `S4`."

    Design: Corner/validations/s2_partner_ticket_requires_a_partner_entitlement
    """
    bundle = programme.entitlement_chain(requested_tier="STANDARD")
    product_id = bundle["product"]["id"]
    developer_id = bundle["developer"]["id"]
    developer_headers = bundle["developer_headers"]

    assert_fields(
        programme.read_entitlement(bundle["assignment"]["id"]),
        "QuotaAssignment",
        tier="STANDARD",
        entitlement_state="ACTIVE",
    )

    refused = api.create_support_case(
        f.support_case_payload(
            product_id,
            kind="PARTNER_TICKET",
            severity="S2",
            title="Catalogue reads failing for our storefront",
            developer_id=developer_id,
            started_at=None,
        ),
        developer_headers,
    )
    validate_error(refused, ApiError.SEVERITY_NOT_ENTITLED)

    _, empty_meta = validate_paginated(
        api.list_support_cases(PLATFORM_ADMIN, {"api_product_id": product_id})
    )
    assert empty_meta["total_count"] == 0, (
        f"the refused ticket must not have been stored, total_count is {empty_meta['total_count']}"
    )

    ticket = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product_id,
                kind="PARTNER_TICKET",
                severity="S3",
                title="Catalogue reads slow for our storefront",
                developer_id=developer_id,
                started_at=None,
            ),
            developer_headers,
        ),
        expected_status=201,
    )
    assert_fields(
        ticket,
        "SupportCase",
        state="OPEN",
        severity="S3",
        first_response_due_minutes=240,
        escalation_tier=0,
        communication_count=0,
        max_communication_gap_minutes=0,
        first_response_breached=False,
    )
    assert_instant_equals(ticket["started_at"], ticket["created_at"], "started_at")

    _, meta = validate_paginated(
        api.list_support_cases(PLATFORM_ADMIN, {"api_product_id": product_id})
    )
    assert meta["total_count"] == 1, (
        f"only the S3 ticket should have been stored, total_count is {meta['total_count']}"
    )


def test_a_partner_tier_holder_opens_the_same_s2_ticket_at_the_sixty_minute_commitment(
    api, programme
):
    """The identical S2 ticket body is admissible for a developer holding a partner-tier
    entitlement on the very same product, and the server pins the one-hour response commitment.

    PRD: "A second entitlement gate applies to urgency: an `S1` or `S2` `PARTNER_TICKET` may only be opened by a developer holding an `ACTIVE` entitlement whose `tier` is `PARTNER` or `PRIVILEGED`, otherwise `ERR_SEVERITY_NOT_ENTITLED` (HTTP 422)."

    PRD: "For a `PARTNER_TICKET` the commitment is **30 minutes** at `S1`, **60 minutes** at `S2`, **240 minutes** at `S3` and **480 minutes** at `S4`."

    Design: Corner/validations/s2_partner_ticket_requires_a_partner_entitlement
    """
    standard = programme.entitlement_chain(requested_tier="STANDARD")
    partner = programme.entitlement_chain(
        product=standard["product"], requested_tier="PARTNER"
    )
    product_id = standard["product"]["id"]

    assert_fields(
        programme.read_entitlement(partner["assignment"]["id"]),
        "QuotaAssignment",
        tier="PARTNER",
        entitlement_state="ACTIVE",
    )

    ticket = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product_id,
                kind="PARTNER_TICKET",
                severity="S2",
                title="Catalogue reads failing for settlement",
                developer_id=partner["developer"]["id"],
                started_at=None,
            ),
            partner["developer_headers"],
        ),
        expected_status=201,
    )
    assert_fields(
        ticket,
        "SupportCase",
        state="OPEN",
        severity="S2",
        kind="PARTNER_TICKET",
        first_response_due_minutes=60,
        escalation_tier=0,
        communication_count=0,
    )
    assert ticket["developer_id"] == partner["developer"]["id"], (
        "the ticket must record the reporting developer"
    )

    _, meta = validate_paginated(
        api.list_support_cases(PLATFORM_ADMIN, {"api_product_id": product_id})
    )
    assert meta["total_count"] == 1, (
        f"exactly one support case should exist on this product, got {meta['total_count']}"
    )


def test_a_partner_ticket_without_an_entitled_developer_is_a_kind_mismatch(api, programme):
    """A partner ticket must be anchored to a developer that actually holds live access: naming a
    developer with no entitlement at all, and naming no developer at all, are both refused as
    shape violations of the ticket kind.

    PRD: "A **`PARTNER_TICKET`** must name the reporting `developer_id`, and that developer must hold at least one `ACTIVE` entitlement on the named product."

    PRD: "Any violation of that shape — a partner ticket with no entitled `developer_id`, or a platform incident that names a `developer_id` or omits `started_at` — is rejected with `ERR_SUPPORT_CASE_KIND_MISMATCH` (HTTP 422)."

    Design: Corner/errors/support_case_shape_and_communication_ordering
    """
    product = programme.create_product()
    stranger = programme.register_developer()

    unentitled = api.create_support_case(
        f.support_case_payload(
            product["id"],
            kind="PARTNER_TICKET",
            severity="S3",
            title="Catalogue reads intermittently slow",
            developer_id=stranger["id"],
            started_at=None,
        ),
        SUPPORT_AGENT,
    )
    validate_error(unentitled, ApiError.SUPPORT_CASE_KIND_MISMATCH)

    anonymous = api.create_support_case(
        f.support_case_payload(
            product["id"],
            kind="PARTNER_TICKET",
            severity="S3",
            title="Anonymous partner ticket",
            started_at=None,
        ),
        SUPPORT_AGENT,
    )
    validate_error(anonymous, ApiError.SUPPORT_CASE_KIND_MISMATCH)

    _, meta = validate_paginated(
        api.list_support_cases(PLATFORM_ADMIN, {"api_product_id": product["id"]})
    )
    assert meta["total_count"] == 0, (
        f"neither malformed ticket may be stored, total_count is {meta['total_count']}"
    )


def test_a_platform_incident_that_names_a_developer_or_omits_its_start_is_a_kind_mismatch(
    api, programme
):
    """A platform incident is the mirror image of a ticket: it must carry its own start instant
    and must not name a reporting developer. Both malformed limbs share the one error id, and the
    well-formed incident opens with no developer and the tighter half-hour commitment.

    PRD: "A **`PLATFORM_INCIDENT`** must **not** name a `developer_id`, and it **must** supply `started_at`, the instant the incident began."

    PRD: "For a `PLATFORM_INCIDENT` the platform holds itself to a tighter standard: **15 minutes** at `S1`, **30 minutes** at `S2`, **120 minutes** at `S3` and **240 minutes** at `S4`."

    Design: Corner/errors/support_case_shape_and_communication_ordering
    """
    product = programme.create_product()
    stranger = programme.register_developer()

    with_developer = api.create_support_case(
        f.support_case_payload(
            product["id"],
            kind="PLATFORM_INCIDENT",
            severity="S2",
            title="Catalogue latency incident",
            started_at="2026-08-01T00:00:00Z",
            developer_id=stranger["id"],
        ),
        SUPPORT_AGENT,
    )
    validate_error(with_developer, ApiError.SUPPORT_CASE_KIND_MISMATCH)

    without_start = api.create_support_case(
        f.support_case_payload(
            product["id"],
            kind="PLATFORM_INCIDENT",
            severity="S2",
            title="Catalogue latency incident",
            started_at=None,
        ),
        SUPPORT_AGENT,
    )
    validate_error(without_start, ApiError.SUPPORT_CASE_KIND_MISMATCH)

    incident = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product["id"],
                kind="PLATFORM_INCIDENT",
                severity="S2",
                title="Catalogue latency incident",
                started_at="2026-08-01T00:00:00Z",
            ),
            SUPPORT_AGENT,
        ),
        expected_status=201,
    )
    assert_fields(
        incident,
        "SupportCase",
        kind="PLATFORM_INCIDENT",
        state="OPEN",
        first_response_due_minutes=30,
        communication_count=0,
        escalation_tier=0,
        started_at="2026-08-01T00:00:00Z",
    )
    assert incident["developer_id"] is None, (
        f"a platform incident carries no reporting developer, got {incident['developer_id']}"
    )

    _, meta = validate_paginated(
        api.list_support_cases(PLATFORM_ADMIN, {"api_product_id": product["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the well-formed incident may be stored, total_count is {meta['total_count']}"
    )


def test_communications_must_lie_between_the_case_start_the_last_update_and_the_clock(
    api, programme
):
    """The communication log is bounded from three sides at once: an update before the incident
    began, one behind the last recorded update, and one ahead of the logical clock are all
    refused, and none of the refusals moves the counter.

    PRD: "`sent_at` must be at or after the case's `started_at`, at or after the existing `last_communication_at` where one exists, and at or before the current logical clock; any violation is `ERR_COMMUNICATION_OUT_OF_ORDER` (HTTP 422)."

    PRD: "The first one additionally sets `first_response_at` and moves the case `OPEN → RESPONDING`; subsequent ones leave the case in `RESPONDING` — the self-transition `RESPONDING → RESPONDING` — while re-evaluating the cadence figures."

    Design: Corner/errors/support_case_shape_and_communication_ordering
    """
    product = programme.create_product()
    programme.set_clock("2026-08-01T03:00:00Z")
    incident = programme.open_incident(
        product["id"],
        severity="S2",
        title="Catalogue latency incident",
        started_at="2026-08-01T00:00:00Z",
    )

    before_start = api.create_support_communication(
        incident["id"],
        f.communication_payload(
            "2026-07-31T23:00:00Z", body="Note written before the incident began."
        ),
        SUPPORT_AGENT,
    )
    validate_error(before_start, ApiError.COMMUNICATION_OUT_OF_ORDER)

    first = validate_success(
        api.create_support_communication(
            incident["id"],
            f.communication_payload(
                "2026-08-01T01:00:00Z",
                body="We have identified elevated catalogue latency and are mitigating.",
            ),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        first,
        "SupportCase",
        state="RESPONDING",
        communication_count=1,
        last_communication_at="2026-08-01T01:00:00Z",
        first_response_at="2026-08-01T01:00:00Z",
        first_response_breached=True,
    )

    backdated = api.create_support_communication(
        incident["id"],
        f.communication_payload(
            "2026-08-01T00:30:00Z", body="Backdated note that predates the last update."
        ),
        SUPPORT_AGENT,
    )
    validate_error(backdated, ApiError.COMMUNICATION_OUT_OF_ORDER)

    ahead_of_clock = api.create_support_communication(
        incident["id"],
        f.communication_payload(
            "2026-08-01T04:00:00Z", body="Post-dated note that is ahead of the logical clock."
        ),
        SUPPORT_AGENT,
    )
    validate_error(ahead_of_clock, ApiError.COMMUNICATION_OUT_OF_ORDER)

    second = validate_success(
        api.create_support_communication(
            incident["id"],
            f.communication_payload(
                "2026-08-01T02:00:00Z", body="Mitigation applied; we are monitoring recovery."
            ),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        second,
        "SupportCase",
        state="RESPONDING",
        communication_count=2,
        last_communication_at="2026-08-01T02:00:00Z",
        first_response_at="2026-08-01T01:00:00Z",
    )


def test_resolving_an_open_incident_is_refused_on_state_not_on_the_missing_update(api, programme):
    """An incident nobody has communicated on is still sitting in OPEN, and resolution is a
    transition out of RESPONDING or ESCALATED only, so the refusal is the state precondition and
    the case is left completely untouched.

    PRD: "The case must be in `RESPONDING` or `ESCALATED`; either way the transition ends at `RESOLVED`, which is terminal, and the effects are identical for both origins."

    PRD: "(16) The support case is in the state its action requires, namely `OPEN`, `RESPONDING` or `ESCALATED` to record a communication and `RESPONDING` or `ESCALATED` to escalate or to resolve — `ERR_SUPPORT_CASE_STATE_INVALID`, 409, on communications, escalate and resolve."

    Design: Corner/state_machines/resolve_before_first_communication_is_a_state_refusal
    """
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S3",
        title="Elevated catalogue read latency",
        started_at="2026-08-01T00:00:00Z",
    )
    programme.set_clock("2026-08-01T01:00:00Z")

    refused = api.resolve_support_case(
        incident["id"],
        f.resolve_support_payload(resolution_note="Closing without any published update."),
        SUPPORT_AGENT,
    )
    validate_error(refused, ApiError.SUPPORT_CASE_STATE_INVALID)

    untouched = validate_success(api.get_support_case(incident["id"], PLATFORM_ADMIN))
    assert_fields(untouched, "SupportCase", state="OPEN", communication_count=0)
    assert untouched["resolved_at"] is None, (
        f"the refused resolution must not have stamped resolved_at: {untouched['resolved_at']}"
    )
    assert untouched["resolution_note"] is None, (
        "the refused resolution must not have recorded a resolution note"
    )


def test_the_same_resolution_succeeds_once_a_first_communication_exists(api, programme):
    """One published update moves the incident to RESPONDING and opens the resolution path: the
    identical resolve call now closes the case, stamps the clock and computes the hour of downtime.

    PRD: "Resolution sets `resolved_at`, computes `downtime_minutes` as the whole minutes between `started_at` and `resolved_at`, floored, recomputes `max_communication_gap_minutes` and `comms_gap_breached` now that the trailing segment counts, and records `credit_uplift_applied` as **1.5** when `comms_gap_breached` is true at resolution and **1.0** otherwise."

    PRD: "`first_response_breached` becomes true when the whole minutes elapsed from `started_at` to the first communication's `sent_at` **exceed** `first_response_due_minutes`."

    Design: Corner/state_machines/resolve_before_first_communication_is_a_state_refusal
    """
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S3",
        title="Elevated catalogue read latency",
        started_at="2026-08-01T00:00:00Z",
    )
    programme.set_clock("2026-08-01T01:00:00Z")

    responding = validate_success(
        api.create_support_communication(
            incident["id"],
            f.communication_payload(
                "2026-08-01T01:00:00Z",
                body="We have identified elevated latency on catalogue reads and are mitigating.",
            ),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        responding,
        "SupportCase",
        state="RESPONDING",
        communication_count=1,
        first_response_at="2026-08-01T01:00:00Z",
        first_response_breached=False,
    )

    resolved = validate_success(
        api.resolve_support_case(
            incident["id"],
            f.resolve_support_payload(
                resolution_note="Latency restored after cache warm-up; monitoring for 24 hours."
            ),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        resolved_at="2026-08-01T01:00:00Z",
        downtime_minutes=60,
        max_communication_gap_minutes=60,
        comms_gap_breached=False,
        credit_uplift_applied=1.0,
    )


def test_a_maximum_communication_gap_equal_to_the_cadence_allowance_does_not_breach(
    api, programme
):
    """Walking the incident from its start through both updates to resolution gives gaps of 20,
    60 and 21 minutes; the largest is exactly the sixty-minute allowance for S2, and because the
    comparison is strict the cadence is met and the credit uplift stays at one.

    PRD: "`comms_gap_breached` becomes true when `max_communication_gap_minutes` **exceeds** the severity's cadence allowance: **30 minutes** at `S1`, **60 minutes** at `S2`, **240 minutes** at `S3` and **1,440 minutes** at `S4`. This comparison too is strict — a gap exactly equal to the allowance does not breach."

    PRD: "`max_communication_gap_minutes` is the largest whole-minute gap, floored, between consecutive checkpoints in that chain; with only a single checkpoint it is 0."

    Design: Corner/calculations/comms_gap_equal_to_the_limit_does_not_breach
    """
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S2",
        title="Catalogue reads degraded",
        started_at="2026-08-01T00:00:00Z",
    )
    programme.set_clock("2026-08-01T01:41:00Z")
    programme.add_communication(
        incident, "2026-08-01T00:20:00Z", body="Investigating degraded catalogue reads."
    )
    programme.add_communication(
        incident, "2026-08-01T01:20:00Z", body="Mitigation applied; verifying recovery."
    )

    resolved = validate_success(
        api.resolve_support_case(
            incident["id"],
            f.resolve_support_payload(resolution_note="Catalogue reads restored."),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        resolved_at="2026-08-01T01:41:00Z",
        downtime_minutes=101,
        communication_count=2,
        last_communication_at="2026-08-01T01:20:00Z",
        max_communication_gap_minutes=60,
        comms_gap_breached=False,
        credit_uplift_applied=1.0,
        first_response_breached=False,
    )


def test_a_maximum_communication_gap_one_minute_over_the_allowance_lifts_the_credit_uplift(
    api, programme
):
    """The same incident with its second update published one minute later has a largest gap of
    61 minutes, which exceeds the S2 allowance, so the cadence is breached and the uplift the
    resolution records rises to one and a half.

    PRD: "`comms_gap_breached` becomes true when `max_communication_gap_minutes` **exceeds** the severity's cadence allowance: **30 minutes** at `S1`, **60 minutes** at `S2`, **240 minutes** at `S3` and **1,440 minutes** at `S4`. This comparison too is strict — a gap exactly equal to the allowance does not breach."

    PRD: "records `credit_uplift_applied` as **1.5** when `comms_gap_breached` is true at resolution and **1.0** otherwise"

    Design: Corner/calculations/comms_gap_equal_to_the_limit_does_not_breach
    """
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S2",
        title="Ledger reads degraded",
        started_at="2026-08-01T00:00:00Z",
    )
    programme.set_clock("2026-08-01T01:41:00Z")
    programme.add_communication(
        incident, "2026-08-01T00:20:00Z", body="Investigating degraded ledger reads."
    )
    programme.add_communication(
        incident,
        "2026-08-01T01:21:00Z",
        body="Mitigation applied one minute later than the cadence allows.",
    )

    resolved = validate_success(
        api.resolve_support_case(
            incident["id"],
            f.resolve_support_payload(resolution_note="Ledger reads restored."),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        resolved_at="2026-08-01T01:41:00Z",
        downtime_minutes=101,
        communication_count=2,
        last_communication_at="2026-08-01T01:21:00Z",
        max_communication_gap_minutes=61,
        comms_gap_breached=True,
        credit_uplift_applied=1.5,
        first_response_breached=False,
    )


def test_a_standard_holders_ticket_escalates_once_to_the_first_tier(api, programme):
    """A responding ticket raised for a standard-tier holder may take the first step along the
    partner escalation channel: the tier counter moves to one and the case sits in ESCALATED.

    PRD: "Each escalation increments `escalation_tier` by one and puts the case in `ESCALATED`, whether it came from `RESPONDING → ESCALATED` or from the self-transition `ESCALATED → ESCALATED`."

    PRD: "The case must be in `RESPONDING` or `ESCALATED`, otherwise `ERR_SUPPORT_CASE_STATE_INVALID`, and `escalation_tier` must be below 3."

    Design: Difficulty/cross_entity_state_dependency/support_escalation_requires_partner_entitlement
    """
    bundle = programme.entitlement_chain(requested_tier="STANDARD")
    assert_fields(
        programme.read_entitlement(bundle["assignment"]["id"]),
        "QuotaAssignment",
        tier="STANDARD",
        entitlement_state="ACTIVE",
    )

    ticket = programme.open_ticket(
        bundle["product"]["id"],
        bundle["developer"],
        severity="S3",
        title="Cursor pagination returns a duplicate page boundary",
        started_at=None,
    )
    assert_fields(ticket, "SupportCase", first_response_due_minutes=240, escalation_tier=0)
    responding = programme.add_communication(
        ticket,
        ticket["started_at"],
        body="Received; reproducing against the storefront sample application.",
    )
    assert_fields(
        responding, "SupportCase", state="RESPONDING", first_response_breached=False
    )

    escalated = validate_success(
        api.escalate_support_case(
            ticket["id"],
            f.escalate_payload(escalation_note="Handing to the catalogue platform team."),
            SUPPORT_AGENT,
        )
    )
    assert_fields(escalated, "SupportCase", state="ESCALATED", escalation_tier=1)


def test_the_second_escalation_of_a_standard_holders_ticket_is_refused_at_tier_one(
    api, programme
):
    """Climbing past the first tier is an entitlement question about a different entity: the
    reporting developer holds only standard-tier access, so the second escalation is refused and
    the case stays in ESCALATED at tier one rather than falling back.

    PRD: "For a `PARTNER_TICKET`, escalating beyond `escalation_tier` 1 requires the reporting developer to hold an `ACTIVE` entitlement of `tier` `PARTNER` or `PRIVILEGED`; without it the escalation is refused with `ERR_ESCALATION_NOT_ENTITLED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/support_escalation_requires_partner_entitlement
    """
    bundle = programme.entitlement_chain(requested_tier="STANDARD")
    ticket = programme.open_ticket(
        bundle["product"]["id"],
        bundle["developer"],
        severity="S3",
        title="Cursor pagination returns a duplicate page boundary",
        started_at=None,
    )
    programme.add_communication(
        ticket,
        ticket["started_at"],
        body="Received; reproducing against the storefront sample application.",
    )
    programme.escalate_case(ticket)

    refused = api.escalate_support_case(
        ticket["id"],
        f.escalate_payload(escalation_note="Requesting the partner duty manager."),
        SUPPORT_AGENT,
    )
    validate_error(refused, ApiError.ESCALATION_NOT_ENTITLED)

    stored = validate_success(api.get_support_case(ticket["id"], PLATFORM_ADMIN))
    assert_fields(stored, "SupportCase", state="ESCALATED", escalation_tier=1)


def test_a_partner_holders_ticket_escalates_past_the_first_tier(api, programme):
    """The same second escalation succeeds for a developer holding partner-tier access: the case
    climbs to tier two through the ESCALATED self-transition.

    PRD: "For a `PARTNER_TICKET`, escalating beyond `escalation_tier` 1 requires the reporting developer to hold an `ACTIVE` entitlement of `tier` `PARTNER` or `PRIVILEGED`; without it the escalation is refused with `ERR_ESCALATION_NOT_ENTITLED` (HTTP 422)."

    PRD: "Each escalation increments `escalation_tier` by one and puts the case in `ESCALATED`, whether it came from `RESPONDING → ESCALATED` or from the self-transition `ESCALATED → ESCALATED`."

    Design: Difficulty/cross_entity_state_dependency/support_escalation_requires_partner_entitlement
    """
    bundle = programme.entitlement_chain(requested_tier="PARTNER")
    assert_fields(
        programme.read_entitlement(bundle["assignment"]["id"]),
        "QuotaAssignment",
        tier="PARTNER",
        entitlement_state="ACTIVE",
    )

    ticket = programme.open_ticket(
        bundle["product"]["id"],
        bundle["developer"],
        severity="S2",
        title="Catalogue reads failing for our storefront",
        started_at=None,
    )
    assert_fields(ticket, "SupportCase", first_response_due_minutes=60, escalation_tier=0)
    programme.add_communication(
        ticket,
        ticket["started_at"],
        body="Received; reproducing against the storefront sample application.",
    )

    first = validate_success(
        api.escalate_support_case(
            ticket["id"],
            f.escalate_payload(escalation_note="Handing to the catalogue platform team."),
            SUPPORT_AGENT,
        )
    )
    assert_fields(first, "SupportCase", state="ESCALATED", escalation_tier=1)

    second = validate_success(
        api.escalate_support_case(
            ticket["id"],
            f.escalate_payload(escalation_note="Requesting the partner duty manager."),
            SUPPORT_AGENT,
        )
    )
    assert_fields(second, "SupportCase", state="ESCALATED", escalation_tier=2)


def test_a_repeat_incident_of_the_same_severity_inside_the_buffer_is_coalesced_away(
    api, programme
):
    """An S2 incident is resolved after forty minutes with its cadence met, and a fresh S2
    incident on the same product beginning only twenty minutes later falls inside the
    sixty-minute buffer, so it is refused and no second record appears.

    PRD: "A new `PLATFORM_INCIDENT` for the same `api_product_id` and the same `severity` must begin at least **60 minutes** after the `resolved_at` of the most recent such incident; one opened inside that buffer is rejected with `ERR_INCIDENT_COALESCE_WINDOW` (HTTP 409), and the update belongs on the existing incident as a communication instead."

    PRD: "Resolution sets `resolved_at`, computes `downtime_minutes` as the whole minutes between `started_at` and `resolved_at`, floored, recomputes `max_communication_gap_minutes` and `comms_gap_breached` now that the trailing segment counts, and records `credit_uplift_applied` as **1.5** when `comms_gap_breached` is true at resolution and **1.0** otherwise."

    Design: Difficulty/resource_temporal_overlap/incident_coalesce_buffer_sixty_minutes_after_resolution
    """
    programme.set_clock("2026-08-02T00:00:00Z")
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S2",
        title="Elevated latency on catalogue reads",
        started_at="2026-08-02T00:00:00Z",
    )
    programme.set_clock("2026-08-02T00:10:00Z")
    programme.add_communication(
        incident,
        "2026-08-02T00:10:00Z",
        body="Latency traced to a cache warm-up after a routine deploy.",
    )
    programme.set_clock("2026-08-02T00:40:00Z")

    resolved = validate_success(
        api.resolve_support_case(
            incident["id"],
            f.resolve_support_payload(
                resolution_note="Cache warm; latency back to baseline."
            ),
            SUPPORT_AGENT,
        )
    )
    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        resolved_at="2026-08-02T00:40:00Z",
        downtime_minutes=40,
        max_communication_gap_minutes=30,
        comms_gap_breached=False,
        credit_uplift_applied=1.0,
    )

    programme.set_clock("2026-08-02T01:00:00Z")
    refused = api.create_support_case(
        f.support_case_payload(
            product["id"],
            kind="PLATFORM_INCIDENT",
            severity="S2",
            title="Latency regression returned",
            started_at="2026-08-02T01:00:00Z",
        ),
        SUPPORT_AGENT,
    )
    validate_error(refused, ApiError.INCIDENT_COALESCE_WINDOW)

    _, meta = validate_paginated(
        api.list_support_cases(
            PLATFORM_ADMIN, {"api_product_id": product["id"], "kind": "PLATFORM_INCIDENT"}
        )
    )
    assert meta["total_count"] == 1, (
        f"the coalesced incident must not have been stored, total_count is {meta['total_count']}"
    )


def test_an_incident_of_a_different_severity_inside_the_buffer_is_still_accepted(api, programme):
    """The buffer is scoped to the pair of product and severity: at the very instant an S2 repeat
    would be coalesced away, an S1 incident on the same product opens normally with its own
    fifteen-minute commitment.

    PRD: "A new `PLATFORM_INCIDENT` for the same `api_product_id` and the same `severity` must begin at least **60 minutes** after the `resolved_at` of the most recent such incident; one opened inside that buffer is rejected with `ERR_INCIDENT_COALESCE_WINDOW` (HTTP 409), and the update belongs on the existing incident as a communication instead."

    PRD: "For a `PLATFORM_INCIDENT` the platform holds itself to a tighter standard: **15 minutes** at `S1`, **30 minutes** at `S2`, **120 minutes** at `S3` and **240 minutes** at `S4`."

    Design: Difficulty/resource_temporal_overlap/incident_coalesce_buffer_sixty_minutes_after_resolution
    """
    programme.set_clock("2026-08-02T00:00:00Z")
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S2",
        title="Elevated latency on catalogue reads",
        started_at="2026-08-02T00:00:00Z",
    )
    programme.set_clock("2026-08-02T00:10:00Z")
    programme.add_communication(
        incident,
        "2026-08-02T00:10:00Z",
        body="Latency traced to a cache warm-up after a routine deploy.",
    )
    programme.set_clock("2026-08-02T00:40:00Z")
    programme.resolve_case(incident, resolution_note="Cache warm; latency back to baseline.")
    programme.set_clock("2026-08-02T01:00:00Z")

    opened = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product["id"],
                kind="PLATFORM_INCIDENT",
                severity="S1",
                title="Catalogue reads failing outright",
                started_at="2026-08-02T01:00:00Z",
            ),
            SUPPORT_AGENT,
        ),
        expected_status=201,
    )
    assert_fields(
        opened,
        "SupportCase",
        kind="PLATFORM_INCIDENT",
        severity="S1",
        state="OPEN",
        first_response_due_minutes=15,
        started_at="2026-08-02T01:00:00Z",
    )

    _, meta = validate_paginated(
        api.list_support_cases(
            PLATFORM_ADMIN, {"api_product_id": product["id"], "kind": "PLATFORM_INCIDENT"}
        )
    )
    assert meta["total_count"] == 2, (
        f"both incidents should be stored, total_count is {meta['total_count']}"
    )


def test_an_incident_exactly_sixty_minutes_after_resolution_is_accepted(api, programme):
    """The buffer is inclusive at its boundary: an S2 incident on the same product beginning
    exactly sixty minutes after the previous S2 was resolved is admitted.

    PRD: "A new `PLATFORM_INCIDENT` for the same `api_product_id` and the same `severity` must begin at least **60 minutes** after the `resolved_at` of the most recent such incident; one opened inside that buffer is rejected with `ERR_INCIDENT_COALESCE_WINDOW` (HTTP 409), and the update belongs on the existing incident as a communication instead."

    PRD: "A new case starts in `state` `OPEN` with `escalation_tier` 0, `communication_count` 0, `max_communication_gap_minutes` 0, `first_response_breached` false, and `first_response_at`, `last_communication_at`, `resolved_at`, `downtime_minutes`, `credit_uplift_applied` and `resolution_note` null, `affected_assignment_count` 0 and `total_credit_calls` 0."

    Design: Difficulty/resource_temporal_overlap/incident_coalesce_buffer_sixty_minutes_after_resolution
    """
    programme.set_clock("2026-08-02T00:00:00Z")
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"],
        severity="S2",
        title="Elevated latency on catalogue reads",
        started_at="2026-08-02T00:00:00Z",
    )
    programme.set_clock("2026-08-02T00:10:00Z")
    programme.add_communication(
        incident,
        "2026-08-02T00:10:00Z",
        body="Latency traced to a cache warm-up after a routine deploy.",
    )
    programme.set_clock("2026-08-02T00:40:00Z")
    programme.resolve_case(incident, resolution_note="Cache warm; latency back to baseline.")
    programme.set_clock("2026-08-02T01:40:00Z")

    opened = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product["id"],
                kind="PLATFORM_INCIDENT",
                severity="S2",
                title="Latency regression, second occurrence",
                started_at="2026-08-02T01:40:00Z",
            ),
            SUPPORT_AGENT,
        ),
        expected_status=201,
    )
    assert_fields(
        opened,
        "SupportCase",
        kind="PLATFORM_INCIDENT",
        severity="S2",
        state="OPEN",
        first_response_due_minutes=30,
        escalation_tier=0,
        communication_count=0,
        max_communication_gap_minutes=0,
        first_response_breached=False,
        started_at="2026-08-02T01:40:00Z",
    )
    assert opened["resolved_at"] is None, "a newly opened incident is not resolved"
    assert opened["credit_uplift_applied"] is None, (
        "a newly opened incident carries no credit uplift yet"
    )

    _, meta = validate_paginated(
        api.list_support_cases(
            PLATFORM_ADMIN, {"api_product_id": product["id"], "kind": "PLATFORM_INCIDENT"}
        )
    )
    assert meta["total_count"] == 2, (
        f"both incidents should be stored, total_count is {meta['total_count']}"
    )
