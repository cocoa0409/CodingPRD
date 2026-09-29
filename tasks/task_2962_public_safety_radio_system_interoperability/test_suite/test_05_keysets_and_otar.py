"""Encryption keyset custody and over-the-air rekey campaigns.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_KEYSET_NOT_ACTIVE,
    ERR_OTAR_WINDOW_OUTSIDE_CRYPTO_PERIOD,
    ERR_OTAR_WINDOW_OVERLAP,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pagination_meta,
    assert_unit_dimensions,
)
from test_helpers.constants import (
    ACTION_SUSPEND,
    AGENCY_TYPE_EMS,
    AGENCY_TYPE_FIRE,
    ALGO_AES256,
    ALGO_DES_OFB,
    CAMPAIGN_COMPLETED,
    CAMPAIGN_SCHEDULED,
    KEY_KEYED,
    KEY_KEYLESS,
    KEYSET_ACTIVE,
    KEYSET_DECISION_APPROVE,
    KEYSET_DECISION_REJECT,
    KEYSET_PENDING_APPROVAL,
    MODEL_MOBILE,
    MODEL_PORTABLE,
    PROVISION_ASSIGNED,
    PROVISION_SUSPENDED,
    ROLE_KEY_CUSTODIAN,
    ROLE_SECURITY_OFFICER,
    STANDARD_P25_PHASE2,
)
from test_helpers.test_users import (
    KEY_CUSTODIAN,
    KEY_CUSTODIAN_ID,
    SECURITY_OFFICER,
    SECURITY_OFFICER_ID,
    SYSTEM_ADMIN,
    make_operator_headers,
)


def test_keyset_system_fields_are_server_stamped(api: ApiClient, clock_at_start: str):
    """None of the custody fields is a client input: the opening status, the
    author, the approver, and the compromise stamp are all decided by the server.

    PRD 3.5: "A new keyset opens in `PENDING_APPROVAL` with
    `created_by_user_id` set to the custodian's `X-User-ID`,
    `approved_by_user_id` null, `compromised_at` null, and `loaded_unit_count`
    0."

    Design: Corner/entities/keyset_system_fields_are_server_stamped
    """
    keyset = validate_success(
        api.create_keyset(
            {
                "keyset_name": "KS-SYSFIELDS-1",
                "algorithm": ALGO_DES_OFB,
                "crypto_period_start": "2026-08-01T00:00:00Z",
                "crypto_period_end": "2026-11-01T00:00:00Z",
            },
            KEY_CUSTODIAN,
        ),
        201,
    )

    assert_common_fields(keyset, expected_version=1)
    assert_fields(
        keyset,
        keyset_name="KS-SYSFIELDS-1",
        algorithm=ALGO_DES_OFB,
        status=KEYSET_PENDING_APPROVAL,
        created_by_user_id=KEY_CUSTODIAN_ID,
        loaded_unit_count=0,
    )
    assert_nulls(keyset, "approved_by_user_id", "compromised_at")
    assert keyset["id"] != keyset["keyset_name"], (
        "the identifier is server-minted and distinct from the key reference name"
    )


def test_keyset_second_approval_rejected(api: ApiClient, clock_at_start: str):
    """The approval endpoint is not idempotent: once the keyset is `ACTIVE` it is
    no longer in `PENDING_APPROVAL`, so a replay is a refused transition.

    PRD 3.5: "Either ruling requires the keyset to be in `PENDING_APPROVAL` and
    enforces the segregation rule of Section 2.9 against `created_by_user_id`,
    and either increments the keyset's `version` by one."

    PRD 2.4 check 12: "The requested transition is an edge out of the resource's
    current state (and, for a site event, an edge belonging to its `event_class`
    arm) — otherwise `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/keyset_second_approval_rejected
    """
    keyset = fx.create_keyset(
        api,
        keyset_name="KS-IDEMPOTENT-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-11-01T00:00:00Z",
    )
    approved = fx.decide_keyset(api, keyset["id"], KEYSET_DECISION_APPROVE)
    assert_fields(
        approved,
        status=KEYSET_ACTIVE,
        approved_by_user_id=SECURITY_OFFICER_ID,
        created_by_user_id=KEY_CUSTODIAN_ID,
        version=keyset["version"] + 1,
    )

    replay = api.decide_keyset(
        keyset["id"], f.keyset_decision_payload(KEYSET_DECISION_APPROVE), SECURITY_OFFICER
    )
    validate_error(replay, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200)
    assert_fields(
        unchanged,
        status=KEYSET_ACTIVE,
        approved_by_user_id=SECURITY_OFFICER_ID,
        created_by_user_id=KEY_CUSTODIAN_ID,
        version=approved["version"],
    )

    # The other ruling is refused for the same reason: ACTIVE is not PENDING_APPROVAL.
    reject_after = api.decide_keyset(
        keyset["id"], f.keyset_decision_payload(KEYSET_DECISION_REJECT), SECURITY_OFFICER
    )
    validate_error(reject_after, ERR_INVALID_STATE_TRANSITION, 409)
    assert_fields(
        validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200),
        status=KEYSET_ACTIVE,
        approved_by_user_id=SECURITY_OFFICER_ID,
    )


def test_rbac_key_custodian_cannot_approve_its_own_keyset_role(
    api: ApiClient, clock_at_start: str
):
    """The two crypto roles are split, and the role check runs before the
    segregation check, so the custodian's own approval is a role denial.

    PRD 2.1: "`KeyCustodian` creates keysets and schedules and runs
    over-the-air rekeying."

    PRD 2.4 check 3: "The acting role appears in the endpoint's authorised role
    list — otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_key_custodian_cannot_approve_its_own_keyset_role
    """
    keyset = fx.create_keyset(
        api,
        keyset_name="KS-RBAC-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-11-01T00:00:00Z",
    )

    # kc-1 is also the author, but check 3 fires before check 10, so this is
    # ERR_UNAUTHORIZED rather than ERR_SEGREGATION_OF_DUTIES.
    refused = api.decide_keyset(
        keyset["id"], f.keyset_decision_payload(KEYSET_DECISION_APPROVE), KEY_CUSTODIAN
    )
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    unchanged = validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200)
    assert_fields(
        unchanged, status=KEYSET_PENDING_APPROVAL, version=keyset["version"]
    )
    assert_nulls(unchanged, "approved_by_user_id")

    ruled = fx.decide_keyset(api, keyset["id"], KEYSET_DECISION_APPROVE)
    assert_fields(
        ruled, status=KEYSET_ACTIVE, approved_by_user_id=SECURITY_OFFICER_ID
    )


def test_error_segregation_of_duties_when_keyset_author_approves_it(
    api: ApiClient, clock_at_start: str
):
    """Segregation of duties compares `X-User-ID`, not role, so the same principal
    cannot approve what it created even while wearing the officer's hat.

    PRD 2.9: "A `Keyset` stores the `X-User-ID` of the `KeyCustodian` who created
    it as `created_by_user_id`; when a `SecurityOfficer` approves or rejects that
    keyset, the acting `X-User-ID` must differ from `created_by_user_id`, and an
    identical value is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`."

    PRD 2.1: "When `X-User-Role` is `SystemAdmin`, `RFEngineer`, `FleetEngineer`,
    `ChangeControlBoard`, `KeyCustodian`, or `SecurityOfficer`, the accompanying
    `X-User-ID` is an opaque operator identifier that is not tied to any
    persisted entity."

    Design: Corner/errors/error_segregation_of_duties_when_keyset_author_approves_it
    """
    # so-1 acts as the custodian here, so it becomes created_by_user_id.
    keyset = validate_success(
        api.create_keyset(
            f.keyset_payload(
                keyset_name="KS-SOD-1",
                algorithm=ALGO_AES256,
                crypto_period_start="2026-08-01T00:00:00Z",
                crypto_period_end="2026-11-01T00:00:00Z",
            ),
            make_operator_headers(SECURITY_OFFICER_ID, ROLE_KEY_CUSTODIAN),
        ),
        201,
    )
    assert_fields(keyset, created_by_user_id=SECURITY_OFFICER_ID)

    self_ruling = api.decide_keyset(
        keyset["id"], f.keyset_decision_payload(KEYSET_DECISION_APPROVE), SECURITY_OFFICER
    )
    validate_error(self_ruling, ERR_SEGREGATION_OF_DUTIES, 403)

    unchanged = validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200)
    assert_fields(unchanged, status=KEYSET_PENDING_APPROVAL)
    assert_nulls(unchanged, "approved_by_user_id")

    # A different principal in the officer role clears the bar.
    accepted = validate_success(
        api.decide_keyset(
            keyset["id"],
            f.keyset_decision_payload(KEYSET_DECISION_APPROVE),
            make_operator_headers(KEY_CUSTODIAN_ID, ROLE_SECURITY_OFFICER),
        ),
        200,
    )
    assert_fields(
        accepted,
        status=KEYSET_ACTIVE,
        approved_by_user_id=KEY_CUSTODIAN_ID,
        created_by_user_id=SECURITY_OFFICER_ID,
    )


def test_otar_window_outside_crypto_period_rejected(api: ApiClient, clock_at_start: str):
    """Containment of the rekey window in the crypto period is inclusive on the
    exclusive end, so a window ending exactly at `crypto_period_end` is legal
    while one four days later is not.

    PRD 3.5: "Second, the window must lie wholly inside the keyset's crypto
    period — `window_start` at or after `crypto_period_start` and `window_end` at
    or before `crypto_period_end` — and a window that pokes out either side is
    rejected with `ERR_OTAR_WINDOW_OUTSIDE_CRYPTO_PERIOD`."

    Design: Corner/validations/otar_window_outside_crypto_period_rejected
    """
    agency = fx.register_agency(
        api,
        name="Crypto Window Agency",
        agency_code="CRW01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    keyset = fx.active_keyset(
        api,
        keyset_name="KS-CRYPTO-WIN",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-09-01T00:00:00Z",
    )

    poking_out = api.create_otar_campaign(
        f.otar_campaign_payload(
            keyset["id"],
            agency["id"],
            window_start="2026-08-25T00:00:00Z",
            window_end="2026-09-05T00:00:00Z",
        ),
        KEY_CUSTODIAN,
    )
    validate_error(poking_out, ERR_OTAR_WINDOW_OUTSIDE_CRYPTO_PERIOD, 422)

    flush = validate_success(
        api.create_otar_campaign(
            f.otar_campaign_payload(
                keyset["id"],
                agency["id"],
                window_start="2026-08-25T00:00:00Z",
                window_end="2026-09-01T00:00:00Z",
            ),
            KEY_CUSTODIAN,
        ),
        201,
    )
    assert_fields(flush, status=CAMPAIGN_SCHEDULED)
    assert_instant_equals(flush["window_end"], "2026-09-01T00:00:00Z", "window_end")

    rows, meta = validate_paginated(
        api.list_otar_campaigns(SYSTEM_ADMIN, params={"keyset_id": keyset["id"]})
    )
    assert_pagination_meta(meta, total_count=1)
    assert [r["id"] for r in rows] == [flush["id"]], (
        "only the contained window may have been persisted"
    )


def test_otar_execute_before_window_start_rejected(api: ApiClient, clock_at_start: str):
    """Execution is gated on the half-open window, so a campaign four days in the
    future cannot be run early and nothing about it moves.

    PRD 3.5: "Executing a campaign must happen inside its own window: the logical
    clock must lie at or after `window_start` and strictly before `window_end`,
    and an execution attempted outside that half-open interval is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    PRD 3.5: "A scheduled campaign opens with `status` `SCHEDULED`,
    `target_unit_count`, `rekeyed_unit_count`, and `failed_unit_count` all 0, and
    `executed_at` null."

    Design: Corner/state_machines/otar_execute_before_window_start_rejected
    """
    agency = fx.register_agency(
        api,
        name="Early Execute Agency",
        agency_code="EAR01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    keyset = fx.active_keyset(
        api,
        keyset_name="KS-EARLY-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-11-01T00:00:00Z",
    )
    campaign = fx.schedule_campaign(
        api,
        keyset["id"],
        agency["id"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )

    # The clock still reads 2026-08-01T00:00:00Z, four days before window_start.
    early = api.execute_otar_campaign(campaign["id"], KEY_CUSTODIAN)
    validate_error(early, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_otar_campaign(campaign["id"], SYSTEM_ADMIN), 200)
    assert_fields(
        unchanged,
        status=CAMPAIGN_SCHEDULED,
        target_unit_count=0,
        rekeyed_unit_count=0,
        failed_unit_count=0,
        version=campaign["version"],
    )
    assert_nulls(unchanged, "executed_at")
    assert_fields(
        validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200),
        status=KEYSET_ACTIVE,
        loaded_unit_count=0,
    )


def test_otar_campaign_outcome_counts_suspended_units_as_failures(
    api: ApiClient, clock_at_start: str
):
    """A `SUSPENDED` radio is inside the target set but unreachable over the air,
    so it is counted as a failure rather than skipped, and the two counters still
    sum to the target size.

    PRD 3.5: "A target whose `provision_status` is `SUSPENDED` cannot be reached
    over the air, so it is left untouched and `failed_unit_count` rises by one
    instead."

    PRD 3.5: "The sum of `rekeyed_unit_count` and `failed_unit_count` always
    equals `target_unit_count` afterwards."

    Design: Corner/calculations/otar_campaign_outcome_counts_suspended_units_as_failures
    """
    agency = fx.register_agency(
        api,
        name="OTAR Aggregate Agency",
        agency_code="OTR01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="OTR-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    reachable = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="OTR0001",
        radio_id=28001,
        model=MODEL_PORTABLE,
    )
    unreachable = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="OTR0002",
        radio_id=28002,
        model=MODEL_MOBILE,
    )
    fx.lifecycle(api, unreachable["id"], agency["id"], ACTION_SUSPEND)

    keyset = fx.active_keyset(
        api,
        keyset_name="KS-OTAR-AGG",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-11-01T00:00:00Z",
    )
    campaign = fx.schedule_campaign(
        api,
        keyset["id"],
        agency["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    executed = fx.execute_campaign(api, campaign["id"])

    assert_fields(
        executed,
        status=CAMPAIGN_COMPLETED,
        target_unit_count=2,
        rekeyed_unit_count=1,
        failed_unit_count=1,
    )
    assert (
        executed["rekeyed_unit_count"] + executed["failed_unit_count"]
        == executed["target_unit_count"]
    ), "the two counters must sum to the target set size"
    assert_instant_equals(executed["executed_at"], "2026-08-01T00:00:00Z", "executed_at")

    keyed = fx.read_unit(api, reachable["id"])
    assert_unit_dimensions(keyed, PROVISION_ASSIGNED, KEY_KEYED)
    assert_fields(keyed, active_keyset_id=keyset["id"])
    assert_instant_equals(keyed["last_otar_at"], "2026-08-01T00:00:00Z", "last_otar_at")

    untouched = fx.read_unit(api, unreachable["id"])
    assert_unit_dimensions(untouched, PROVISION_SUSPENDED, KEY_KEYLESS)
    assert_nulls(untouched, "active_keyset_id", "last_otar_at")

    assert_fields(
        validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200),
        loaded_unit_count=1,
    )


def test_otar_campaign_creation_requires_active_keyset(api: ApiClient, clock_at_start: str):
    """The blocking state lives on the crypto material: a keyset still awaiting its
    officer cannot be scheduled, and the refusal persists no campaign row.

    PRD 3.5: "The keyset must be `ACTIVE` at scheduling time, or the request is
    rejected with `ERR_KEYSET_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/otar_campaign_creation_requires_active_keyset
    """
    agency = fx.register_agency(
        api,
        name="Papa Valley EMS",
        agency_code="EMSP1",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    keyset = fx.create_keyset(
        api,
        keyset_name="KS-PEND-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-12-01T00:00:00Z",
    )
    assert_fields(
        keyset,
        status=KEYSET_PENDING_APPROVAL,
        created_by_user_id=KEY_CUSTODIAN_ID,
    )
    assert_nulls(keyset, "approved_by_user_id")

    refused = api.create_otar_campaign(
        f.otar_campaign_payload(
            keyset["id"],
            agency["id"],
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-03T00:00:00Z",
        ),
        KEY_CUSTODIAN,
    )
    validate_error(refused, ERR_KEYSET_NOT_ACTIVE, 409)

    _, meta = validate_paginated(
        api.list_otar_campaigns(SYSTEM_ADMIN, params={"keyset_id": keyset["id"]})
    )
    assert_pagination_meta(meta, total_count=0)
    assert_fields(
        validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200),
        status=KEYSET_PENDING_APPROVAL,
        version=keyset["version"],
    )


def test_otar_campaign_creation_accepted_once_a_second_user_approves_the_keyset(
    api: ApiClient, clock_at_start: str
):
    """Nothing about the campaign payload changes: the unblocking act is a
    segregation-of-duties approval by a second principal.

    PRD 3.5: "`APPROVE` moves it `PENDING_APPROVAL` → `ACTIVE` and records the
    officer's `X-User-ID` as `approved_by_user_id`; it also performs a quiet
    housekeeping step, retiring the keys the new one displaces."

    PRD 3.5: "A scheduled campaign opens with `status` `SCHEDULED`,
    `target_unit_count`, `rekeyed_unit_count`, and `failed_unit_count` all 0, and
    `executed_at` null."

    Design: Difficulty/cross_entity_state_dependency/otar_campaign_creation_requires_active_keyset
    """
    agency = fx.register_agency(
        api,
        name="Papa Valley EMS",
        agency_code="EMSP1",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    keyset = fx.create_keyset(
        api,
        keyset_name="KS-PEND-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-12-01T00:00:00Z",
    )
    payload = f.otar_campaign_payload(
        keyset["id"],
        agency["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    validate_error(
        api.create_otar_campaign(payload, KEY_CUSTODIAN), ERR_KEYSET_NOT_ACTIVE, 409
    )

    activated = fx.decide_keyset(api, keyset["id"], KEYSET_DECISION_APPROVE)
    assert_fields(
        activated,
        status=KEYSET_ACTIVE,
        approved_by_user_id=SECURITY_OFFICER_ID,
        loaded_unit_count=0,
    )

    # The byte-identical payload now succeeds.
    campaign = validate_success(api.create_otar_campaign(payload, KEY_CUSTODIAN), 201)
    assert_common_fields(campaign, expected_version=1)
    assert_fields(
        campaign,
        status=CAMPAIGN_SCHEDULED,
        keyset_id=keyset["id"],
        agency_id=agency["id"],
        target_unit_count=0,
        rekeyed_unit_count=0,
        failed_unit_count=0,
    )
    assert_nulls(campaign, "executed_at")

    _, meta = validate_paginated(
        api.list_otar_campaigns(SYSTEM_ADMIN, params={"keyset_id": keyset["id"]})
    )
    assert_pagination_meta(meta, total_count=1)


def _quebec_scheduled_window(api: ApiClient):
    """Agency Q plus an `ACTIVE` keyset and one `SCHEDULED` campaign covering
    `[2026-08-05T00:00:00Z, 2026-08-05T04:00:00Z)`."""
    agency = fx.register_agency(
        api,
        name="Quebec Fire District",
        agency_code="FIRQ1",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    keyset = fx.active_keyset(
        api,
        keyset_name="KS-WIN-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-12-01T00:00:00Z",
    )
    first = fx.schedule_campaign(
        api,
        keyset["id"],
        agency["id"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-05T04:00:00Z",
    )
    assert_fields(first, status=CAMPAIGN_SCHEDULED)
    assert_instant_equals(first["window_start"], "2026-08-05T00:00:00Z", "window_start")
    assert_instant_equals(first["window_end"], "2026-08-05T04:00:00Z", "window_end")
    return agency, keyset, first


def test_otar_window_half_open_adjacency_accepted(api: ApiClient, clock_at_start: str):
    """A window that begins exactly where the incumbent's ends is adjacency, not
    overlap, because `window_end` is exclusive.

    PRD 3.5: "First, the campaign window must not overlap another campaign for the
    same `keyset_id` and the same `agency_id` whose `status` is `SCHEDULED`;
    overlap is judged on half-open intervals, so a new window beginning exactly at
    an existing window's end is accepted, and a genuine overlap is rejected with
    `ERR_OTAR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/otar_window_half_open_adjacency_accepted_overlap_rejected
    """
    agency, keyset, first = _quebec_scheduled_window(api)

    adjacent = validate_success(
        api.create_otar_campaign(
            f.otar_campaign_payload(
                keyset["id"],
                agency["id"],
                window_start="2026-08-05T04:00:00Z",
                window_end="2026-08-05T08:00:00Z",
            ),
            KEY_CUSTODIAN,
        ),
        201,
    )
    assert_fields(adjacent, status=CAMPAIGN_SCHEDULED, keyset_id=keyset["id"])
    assert_instant_equals(
        adjacent["window_start"], first["window_end"], "adjacent window_start"
    )

    rows, meta = validate_paginated(
        api.list_otar_campaigns(
            SYSTEM_ADMIN,
            params={"keyset_id": keyset["id"], "status": CAMPAIGN_SCHEDULED},
        )
    )
    assert_pagination_meta(meta, total_count=2)
    assert {r["id"] for r in rows} == {first["id"], adjacent["id"]}, (
        "both back-to-back windows must survive"
    )


def test_otar_window_genuine_overlap_rejected(api: ApiClient, clock_at_start: str):
    """One minute of genuine intersection collides, and the rejection is the
    overlap error rather than the crypto-period error the group-13 order would
    reach later.

    PRD 3.5: "First, the campaign window must not overlap another campaign for the
    same `keyset_id` and the same `agency_id` whose `status` is `SCHEDULED`;
    overlap is judged on half-open intervals, so a new window beginning exactly at
    an existing window's end is accepted, and a genuine overlap is rejected with
    `ERR_OTAR_WINDOW_OVERLAP`."

    PRD 2.4: "then the temporal window rules in the order
    `ERR_OTAR_WINDOW_OVERLAP`, `ERR_PATCH_WINDOW_OVERLAP`,
    `ERR_MAINTENANCE_BUFFER_VIOLATION`, `ERR_MAINTENANCE_CONCURRENCY_CAP`"

    Design: Difficulty/resource_temporal_overlap/otar_window_half_open_adjacency_accepted_overlap_rejected
    """
    agency, keyset, first = _quebec_scheduled_window(api)

    adjacent = validate_success(
        api.create_otar_campaign(
            f.otar_campaign_payload(
                keyset["id"],
                agency["id"],
                window_start="2026-08-05T04:00:00Z",
                window_end="2026-08-05T08:00:00Z",
            ),
            KEY_CUSTODIAN,
        ),
        201,
    )

    # 03:59 precedes the first window's exclusive end and 06:00 follows the
    # second window's start, so this intersects both.
    collision = api.create_otar_campaign(
        f.otar_campaign_payload(
            keyset["id"],
            agency["id"],
            window_start="2026-08-05T03:59:00Z",
            window_end="2026-08-05T06:00:00Z",
        ),
        KEY_CUSTODIAN,
    )
    validate_error(collision, ERR_OTAR_WINDOW_OVERLAP, 409)

    rows, meta = validate_paginated(
        api.list_otar_campaigns(SYSTEM_ADMIN, params={"keyset_id": keyset["id"]})
    )
    assert_pagination_meta(meta, total_count=2)
    assert {r["id"] for r in rows} == {first["id"], adjacent["id"]}, (
        "no third campaign row may exist"
    )
