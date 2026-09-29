"""Subscriber units and their two independent state dimensions.

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
    ERR_AGENCY_SCOPE_VIOLATION,
    ERR_DUPLICATE_RADIO_ID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TEMPLATE_NOT_PUBLISHED,
    ERR_UNIT_NOT_FOUND,
    ERR_UNIT_RETIRED,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pagination_meta,
    assert_site_capacity_counters,
    assert_unit_dimensions,
    ids_of,
)
from test_helpers.constants import (
    ACTION_ASSIGN,
    ACTION_REINSTATE,
    ACTION_RETIRE,
    ACTION_SUSPEND,
    ACTION_ZEROIZE,
    AGENCY_TYPE_EMS,
    AGENCY_TYPE_FIRE,
    AGENCY_TYPE_PUBLIC_WORKS,
    ALGO_AES256,
    BACKUP_GENERATOR,
    CAMPAIGN_COMPLETED,
    ENC_CLEAR,
    KEY_KEYED,
    KEY_KEYLESS,
    KEY_ZEROIZED,
    KIND_NORMAL,
    MODEL_CONTROL_STATION,
    MODEL_MOBILE,
    MODEL_PORTABLE,
    NONEXISTENT_ID,
    OUTCOME_GRANTED,
    OUTCOME_RELEASED,
    PROVISION_ASSIGNED,
    PROVISION_INVENTORY,
    PROVISION_RETIRED,
    PROVISION_SUSPENDED,
    STANDARD_P25_PHASE2,
    TEMPLATE_DRAFT,
    TEMPLATE_PUBLISHED,
    TG_KIND_DISPATCH,
)
from test_helpers.test_users import (
    SYSTEM_ADMIN,
    make_agency_radio_manager_headers,
)


def test_unit_creation_returns_declared_initial_and_default_fields(
    api: ApiClient, clock_at_start: str
):
    """A radio added with only its four required inputs opens on every declared
    default, and an inventory radio is not yet billable.

    PRD 3.4: "Two optional inputs shape how the radio behaves when channels are
    scarce: `priority_class`, an integer from 1 to 10 where 1 is the highest
    priority, defaulting to 5; and `emergency_button_enabled`, defaulting to
    false, which determines whether the radio may originate emergency traffic at
    all."

    PRD 3.4: "A new unit opens with `provision_status` `INVENTORY`, `key_status`
    `KEYLESS`, `template_id` null, `active_keyset_id` null, `billable` false,
    `days_in_service_last_period` 0, and `assigned_at`, `retired_at`, and
    `last_otar_at` all null."

    Design: Corner/entities/unit_creation_returns_declared_initial_and_default_fields
    """
    agency = fx.register_agency(
        api, name="Corner Creation Agency", agency_code="CRN01", agency_type=AGENCY_TYPE_EMS
    )

    unit = validate_success(
        api.create_unit(
            {
                "agency_id": agency["id"],
                "serial_number": "CRN0001",
                "radio_id": 20001,
                "model": MODEL_PORTABLE,
            },
            make_agency_radio_manager_headers(agency["id"]),
        ),
        201,
    )

    assert_common_fields(unit, expected_version=1)
    assert_unit_dimensions(unit, PROVISION_INVENTORY, KEY_KEYLESS)
    assert_fields(
        unit,
        agency_id=agency["id"],
        serial_number="CRN0001",
        radio_id=20001,
        model=MODEL_PORTABLE,
        priority_class=5,
        emergency_button_enabled=False,
        billable=False,
        days_in_service_last_period=0,
    )
    assert_nulls(
        unit, "template_id", "active_keyset_id", "assigned_at", "retired_at", "last_otar_at"
    )

    # PRD 3.4: "`billable` is true exactly when `provision_status` is `ASSIGNED`
    # or `SUSPENDED`, and false for `INVENTORY` and `RETIRED`."
    assert_fields(fx.read_agency(api, agency["id"]), billable_subscriber_count=0)


def test_unit_listing_paginates_with_total_count_and_has_more(
    api: ApiClient, clock_at_start: str
):
    """The unit list reports the whole matching population in `total_count` while
    returning only the requested window, and filters compose with paging.

    PRD 2.4: "Every one of these lists also accepts `limit` and `offset`."

    PRD 2.4: "Filter parameters on list endpoints are additive: supplying more
    than one narrows the result set, and supplying none returns every row."

    Design: Corner/entities/unit_listing_paginates_with_total_count_and_has_more
    """
    agency = fx.register_agency(
        api,
        name="Paging Agency",
        agency_code="PAG01",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        recorder_retention_days=30,
    )
    created = [
        fx.add_unit(
            api, agency["id"], serial_number="PAG0001", radio_id=21001, model=MODEL_PORTABLE
        ),
        fx.add_unit(
            api, agency["id"], serial_number="PAG0002", radio_id=21002, model=MODEL_PORTABLE
        ),
        fx.add_unit(
            api, agency["id"], serial_number="PAG0003", radio_id=21003, model=MODEL_MOBILE
        ),
    ]

    first_page, first_meta = validate_paginated(
        api.list_units(
            SYSTEM_ADMIN, params={"agency_id": agency["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
    assert_pagination_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)

    second_page, second_meta = validate_paginated(
        api.list_units(
            SYSTEM_ADMIN, params={"agency_id": agency["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, f"the tail page must return 1 row, got {len(second_page)}"
    assert_pagination_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)

    walked = ids_of(first_page) + ids_of(second_page)
    assert len(set(walked)) == 3, f"paging must not repeat a row, got {walked}"
    assert set(walked) == set(ids_of(created)), (
        "the two pages together must cover exactly the three created units"
    )

    # The provision_status filter applies on top of pagination.
    _, retired_meta = validate_paginated(
        api.list_units(
            SYSTEM_ADMIN,
            params={"agency_id": agency["id"], "provision_status": PROVISION_RETIRED},
        )
    )
    assert_pagination_meta(retired_meta, total_count=0)


def test_duplicate_radio_id_rejected(api: ApiClient, clock_at_start: str):
    """The P25 decimal identifier is unique system-wide, not per agency, so a
    second agency cannot reuse it.

    PRD 3.4: "Both the serial and the decimal identifier must be unique across
    every subscriber unit in the system, and a collision on either is rejected
    with `ERR_DUPLICATE_RADIO_ID`."

    Design: Corner/validations/duplicate_radio_id_rejected
    """
    first_agency = fx.register_agency(
        api,
        name="Radio Id First Agency",
        agency_code="RID01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    second_agency = fx.register_agency(
        api,
        name="Radio Id Second Agency",
        agency_code="RID02",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    fx.add_unit(
        api,
        first_agency["id"],
        serial_number="RID0001",
        radio_id=30001,
        model=MODEL_PORTABLE,
    )

    collision = api.create_unit(
        f.unit_payload(
            second_agency["id"],
            serial_number="RID0002",
            radio_id=30001,
            model=MODEL_MOBILE,
        ),
        make_agency_radio_manager_headers(second_agency["id"]),
    )
    validate_error(collision, ERR_DUPLICATE_RADIO_ID, 409)

    _, meta = validate_paginated(
        api.list_units(SYSTEM_ADMIN, params={"agency_id": second_agency["id"]})
    )
    assert_pagination_meta(meta, total_count=0)

    # Only the collision was refused: a free decimal id is accepted.
    accepted = validate_success(
        api.create_unit(
            f.unit_payload(
                second_agency["id"],
                serial_number="RID0002",
                radio_id=30002,
                model=MODEL_MOBILE,
            ),
            make_agency_radio_manager_headers(second_agency["id"]),
        ),
        201,
    )
    assert_fields(accepted, radio_id=30002, agency_id=second_agency["id"])


def test_unit_assign_twice_rejected_as_invalid_transition(
    api: ApiClient, clock_at_start: str
):
    """`ASSIGN` is declared only out of `INVENTORY`, so replaying it on an already
    assigned radio is not an idempotent no-op but a refused transition.

    PRD 2.4 check 12: "The requested transition is an edge out of the resource's
    current state (and, for a site event, an edge belonging to its `event_class`
    arm) — otherwise `ERR_INVALID_STATE_TRANSITION`."

    PRD 3.4: "**`ASSIGN`** takes a radio from `INVENTORY` to `ASSIGNED` and is
    the only action that consumes `template_id`; the field must be present and
    must resolve to an existing programming template."

    Design: Corner/state_machines/unit_assign_twice_rejected_as_invalid_transition
    """
    agency = fx.register_agency(
        api,
        name="Double Assign Agency",
        agency_code="DBL01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="DBL-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="DBL0001",
        radio_id=23001,
        model=MODEL_PORTABLE,
    )
    assert_fields(unit, provision_status=PROVISION_ASSIGNED)

    replay = api.unit_lifecycle(
        unit["id"],
        f.lifecycle_payload(ACTION_ASSIGN, template["id"]),
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(replay, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = fx.read_unit(api, unit["id"])
    assert_fields(
        unchanged, provision_status=PROVISION_ASSIGNED, template_id=template["id"]
    )
    assert_instant_equals(unchanged["assigned_at"], "2026-08-01T00:00:00Z", "assigned_at")

    # The refused call fired no side effects.
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=1)
    assert_fields(fx.read_agency(api, agency["id"]), billable_subscriber_count=1)


def test_unit_suspend_releases_held_talkpath_and_recomputes_occupancy(
    api: ApiClient, clock_at_start: str
):
    """Suspending the radio that holds the only channel evicts it from the air and
    frees the channel, but the site's peak is monotonic and does not fall back.

    PRD 3.4: "Suspension does, however, evict the radio from the air: every
    talkpath request originated by this unit whose `outcome` is `GRANTED` and
    whose `released_at` is still null becomes `RELEASED` with `released_at`
    stamped at now, and because those channels came free, `busy_talkpaths` is
    recomputed on each site that was affected."

    PRD 3.4: "A suspended radio keeps its loaded key, so `key_status` is
    untouched, and it remains billable — `billable` stays true, because
    suspension does not stop the meter."

    Design: Corner/state_machines/unit_suspend_releases_held_talkpath_and_recomputes_occupancy
    """
    agency = fx.register_agency(
        api,
        name="Suspend Cascade Agency",
        agency_code="SUS01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    site = fx.register_site(
        api,
        site_code="SUS-1",
        name="Suspend One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    template = fx.published_template(
        api,
        template_name="SUS-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="SUS-A",
        tg_decimal_id=1001,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="SUS0001",
        radio_id=24001,
        model=MODEL_PORTABLE,
    )

    talkpath = fx.request_talkpath(
        api, site["id"], talkgroup["id"], unit["id"], agency["id"], KIND_NORMAL
    )
    # usable = 4 - 1 control channel = 3; NORMAL mode means no surge reserve.
    assert_fields(
        talkpath,
        outcome=OUTCOME_GRANTED,
        available_talkpaths_at_decision=3,
        reserve_talkpaths_at_decision=0,
    )
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]), busy_talkpaths=1, peak_talkpaths=1
    )

    fx.set_clock(api, "2026-08-01T00:05:00Z")
    suspended = fx.lifecycle(api, unit["id"], agency["id"], ACTION_SUSPEND)
    assert_fields(suspended, provision_status=PROVISION_SUSPENDED, billable=True)

    released = validate_success(
        api.get_talkpath_request(talkpath["id"], SYSTEM_ADMIN), 200
    )
    assert_fields(released, outcome=OUTCOME_RELEASED)
    assert_instant_equals(released["released_at"], "2026-08-01T00:05:00Z", "released_at")

    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=0,
        peak_talkpaths=1,
        granted_request_count=1,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )


def test_error_unit_retired_blocks_further_lifecycle_actions(
    api: ApiClient, clock_at_start: str
):
    """`RETIRED` is terminal in the provisioning dimension, so a second `RETIRE`
    on the same radio is refused with the retired-unit error and nothing on the
    row — either dimension — moves.

    PRD 3.4: "**`RETIRE`** takes a radio from `INVENTORY`, `ASSIGNED`, or
    `SUSPENDED` to `RETIRED`, which is terminal in the provisioning dimension;
    retiring a radio that is already `RETIRED` is rejected with
    `ERR_UNIT_RETIRED`."

    PRD 2.4: "Within group 13 the relative order is likewise fixed: the
    retired-unit guard (`ERR_UNIT_RETIRED`), then the keyset-active guard
    (`ERR_KEYSET_NOT_ACTIVE`), then the template-published guard
    (`ERR_TEMPLATE_NOT_PUBLISHED`), then the talkgroup-availability guard
    (`ERR_TALKGROUP_LOCKED`), then the site-on-air guard (`ERR_SITE_OFF_AIR`),
    then coverage sufficiency (`ERR_COVERAGE_CLASS_INSUFFICIENT`), then recorder
    retention (`ERR_RECORDER_RETENTION_BELOW_MINIMUM`), then emergency and
    priority entitlement (`ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED`), then the
    temporal window rules in the order `ERR_OTAR_WINDOW_OVERLAP`,
    `ERR_PATCH_WINDOW_OVERLAP`, `ERR_MAINTENANCE_BUFFER_VIOLATION`,
    `ERR_MAINTENANCE_CONCURRENCY_CAP`, then the referential rules in the order
    `ERR_TEMPLATE_VERSION_STALE`, `ERR_ENCRYPTION_MODE_MISMATCH`,
    `ERR_SELF_PATCH_NOT_PERMITTED`, `ERR_INTEROP_PRIVILEGE_INSUFFICIENT`, then
    `ERR_PATCH_AUTHORITY_REQUIRED`, then `ERR_OTAR_WINDOW_OUTSIDE_CRYPTO_PERIOD`,
    then the uniqueness rules `ERR_DUPLICATE_RADIO_ID` and
    `ERR_DUPLICATE_TALKGROUP_ID`, then `ERR_TEMPLATE_SLOT_CAPACITY_EXCEEDED`,
    then `ERR_REVISION_LIMIT_EXCEEDED`, then the fiscal rules in the order
    `ERR_AGENCY_VOTING_SUSPENDED`, `ERR_FEE_PERIOD_INVALID`,
    `ERR_PAYMENT_EXCEEDS_BALANCE`, and finally the capacity rule
    `ERR_NO_PREEMPTABLE_TALKPATH`."

    PRD 3.4: "On success `retired_at` is stamped with now and `billable` becomes
    false, while `key_status` is left exactly as it was — a retired radio may
    still hold a key."

    Design: Corner/errors/error_unit_retired_blocks_further_lifecycle_actions
    """
    agency = fx.register_agency(
        api,
        name="Retired Unit Agency",
        agency_code="RTU01",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        recorder_retention_days=30,
    )
    unit = fx.add_unit(
        api, agency["id"], serial_number="RTU0001", radio_id=38001, model=MODEL_MOBILE
    )
    retired = fx.lifecycle(api, unit["id"], agency["id"], ACTION_RETIRE)
    assert_unit_dimensions(retired, PROVISION_RETIRED, KEY_KEYLESS)

    refused = api.unit_lifecycle(
        unit["id"],
        f.lifecycle_payload(ACTION_RETIRE),
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(refused, ERR_UNIT_RETIRED, 409)

    unchanged = fx.read_unit(api, unit["id"])
    assert_unit_dimensions(unchanged, PROVISION_RETIRED, KEY_KEYLESS)
    assert_fields(unchanged, billable=False)
    assert_instant_equals(unchanged["retired_at"], "2026-08-01T00:00:00Z", "retired_at")
    assert_fields(fx.read_agency(api, agency["id"]), billable_subscriber_count=0)


def test_error_unit_not_found_on_lifecycle_action(api: ApiClient, clock_at_start: str):
    """Path identifiers resolve before body foreign keys, so an unknown unit id
    decides the error even when the body also names a missing template.

    PRD 2.4: "Path identifiers are resolved strictly left to right, and the
    first identifier that fails to resolve decides the error."

    PRD 2.4 check 6: "Body foreign keys resolve, in the endpoint's declared field
    order — otherwise the not-found error of the failing reference."

    Design: Corner/errors/error_unit_not_found_on_lifecycle_action
    """
    agency = fx.register_agency(
        api,
        name="No Such Unit Agency",
        agency_code="NFU01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )

    refused = api.unit_lifecycle(
        NONEXISTENT_ID,
        f.lifecycle_payload(ACTION_ASSIGN, NONEXISTENT_ID),
        make_agency_radio_manager_headers(agency["id"]),
    )
    # Not ERR_TEMPLATE_NOT_FOUND: the path segment fails first.
    validate_error(refused, ERR_UNIT_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api.list_units(SYSTEM_ADMIN, params={"agency_id": agency["id"]})
    )
    assert_pagination_meta(meta, total_count=0)


def test_error_agency_scope_violation_on_another_agencys_unit(
    api: ApiClient, clock_at_start: str
):
    """Holding the `AgencyRadioManager` role is not enough: the acting identity
    must own the radio being driven.

    PRD 3.4: "In every case the acting `X-User-ID` must equal the unit's
    `agency_id`, or the request is rejected with `ERR_AGENCY_SCOPE_VIOLATION`,
    and every successful lifecycle action increments the unit's `version` by
    one."

    Design: Corner/errors/error_agency_scope_violation_on_another_agencys_unit
    """
    owner = fx.register_agency(
        api,
        name="Scope Agency A",
        agency_code="SCA01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    intruder = fx.register_agency(
        api,
        name="Scope Agency B",
        agency_code="SCB01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    unit = fx.add_unit(
        api, owner["id"], serial_number="SCA0001", radio_id=37001, model=MODEL_PORTABLE
    )

    body = f.lifecycle_payload(ACTION_ZEROIZE)

    refused = api.unit_lifecycle(
        unit["id"], body, make_agency_radio_manager_headers(intruder["id"])
    )
    validate_error(refused, ERR_AGENCY_SCOPE_VIOLATION, 403)
    assert_unit_dimensions(
        fx.read_unit(api, unit["id"]), PROVISION_INVENTORY, KEY_KEYLESS
    )

    accepted = validate_success(
        api.unit_lifecycle(
            unit["id"], body, make_agency_radio_manager_headers(owner["id"])
        ),
        200,
    )
    assert_unit_dimensions(accepted, PROVISION_INVENTORY, KEY_ZEROIZED)
    assert accepted["version"] > unit["version"], (
        "a successful lifecycle action increments the unit's version by one"
    )


def test_unit_lifecycle_action_endpoint_rejects_unknown_action(
    api: ApiClient, clock_at_start: str
):
    """`action` is a closed enum, so an unlisted verb is a malformed body caught by
    body validation rather than a transition refused by the state machine.

    PRD 3.4: "The provisioning dimension is driven entirely by the unit lifecycle
    operation, which takes an `action` of `ASSIGN`, `SUSPEND`, `REINSTATE`,
    `RETIRE`, or `ZEROIZE`, plus an optional `template_id` used by one of them."

    PRD 2.4 check 7: "The body parses, required fields are present, enum values
    are members of their declared sets, integers lie inside their declared
    ranges, and datetime fields are ISO-8601 UTC instants ending in `Z` —
    otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/unit_lifecycle_action_endpoint_rejects_unknown_action
    """
    agency = fx.register_agency(
        api,
        name="Unknown Action Agency",
        agency_code="ACT01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    unit = fx.add_unit(
        api,
        agency["id"],
        serial_number="ACT0001",
        radio_id=36001,
        model=MODEL_CONTROL_STATION,
    )
    manager = make_agency_radio_manager_headers(agency["id"])

    # Body validation is check 7; the transition check is check 12, so the enum
    # failure decides and this is 400, not 409 ERR_INVALID_STATE_TRANSITION.
    refused = api.unit_lifecycle(unit["id"], {"action": "REPROGRAM"}, manager)
    validate_error(refused, ERR_INVALID_REQUEST, 400)
    assert_unit_dimensions(
        fx.read_unit(api, unit["id"]), PROVISION_INVENTORY, KEY_KEYLESS
    )

    # A declared member of the same enum is accepted on the same row.
    accepted = validate_success(
        api.unit_lifecycle(unit["id"], f.lifecycle_payload(ACTION_ZEROIZE), manager), 200
    )
    assert_unit_dimensions(accepted, PROVISION_INVENTORY, KEY_ZEROIZED)


def _echo_public_works_keyed_fleet(api: ApiClient):
    """Build one `ASSIGNED` + `KEYED` radio for the parallel-dimension tests.

    Returns `(agency, template, unit, keyset)` with the logical clock left at
    `2026-08-01T00:00:00Z`.
    """
    agency = fx.register_agency(
        api,
        name="Echo Public Works",
        agency_code="PWKE1",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        recorder_retention_days=30,
    )
    template = fx.published_template(
        api,
        template_name="PW-P2-BASE",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
        encryption_required=False,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="SNE001",
        radio_id=5001,
        model=MODEL_MOBILE,
        priority_class=5,
    )
    # PRD 3.4: "Assigning a radio never alters its `key_status`".
    assert_unit_dimensions(unit, PROVISION_ASSIGNED, KEY_KEYLESS)

    keyset = fx.active_keyset(
        api,
        keyset_name="KS-AES-2026-Q3",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-12-01T00:00:00Z",
    )
    campaign = fx.keyed_fleet(
        api,
        agency["id"],
        keyset["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-01T00:00:00Z",
    )
    assert_fields(
        campaign,
        status=CAMPAIGN_COMPLETED,
        target_unit_count=1,
        rekeyed_unit_count=1,
        failed_unit_count=0,
    )
    keyed = fx.read_unit(api, unit["id"])
    assert_unit_dimensions(keyed, PROVISION_ASSIGNED, KEY_KEYED)
    assert_fields(keyed, active_keyset_id=keyset["id"])
    return agency, template, keyed, keyset


def test_subscriber_unit_provisioning_moves_leave_the_encryption_dimension_alone(
    api: ApiClient, clock_at_start: str
):
    """Walking the provisioning dimension `ASSIGNED` → `SUSPENDED` → `ASSIGNED`
    never disturbs `key_status`, and reinstatement does not rewrite the original
    assignment instant.

    PRD 3.4: "The critical structural fact about a subscriber unit is that it
    carries **two state machines on one row, and they never touch each other**."

    PRD 3.4: "**`REINSTATE`** takes a radio from `SUSPENDED` back to `ASSIGNED`,
    closing a cycle in the provisioning dimension, and leaves `key_status`
    untouched."

    Design: Difficulty/non_linear_state_machine/subscriber_unit_parallel_dimensions_evolve_independently
    """
    agency, _template, unit, keyset = _echo_public_works_keyed_fleet(api)

    suspended = fx.lifecycle(api, unit["id"], agency["id"], ACTION_SUSPEND)
    assert_unit_dimensions(suspended, PROVISION_SUSPENDED, KEY_KEYED)
    assert_fields(suspended, active_keyset_id=keyset["id"], billable=True)

    reinstated = fx.lifecycle(api, unit["id"], agency["id"], ACTION_REINSTATE)
    assert_unit_dimensions(reinstated, PROVISION_ASSIGNED, KEY_KEYED)
    assert_fields(reinstated, active_keyset_id=keyset["id"], billable=True)
    # PRD 3.4: "`assigned_at` is **not** rewritten."
    assert_instant_equals(
        reinstated["assigned_at"], unit["assigned_at"], "assigned_at after REINSTATE"
    )

    # The key survived the whole provisioning cycle, so the keyset still counts it.
    loaded = validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200)
    assert_fields(loaded, loaded_unit_count=1)


def test_subscriber_unit_zeroize_leaves_the_provisioning_dimension_alone(
    api: ApiClient, clock_at_start: str
):
    """`ZEROIZE` is available from any provisioning position and moves only the
    encryption dimension, and a later `REINSTATE` cannot bring the key back.

    PRD 3.4: "**`ZEROIZE`** is the one lifecycle action that touches the
    encryption dimension instead. It takes `key_status` from `KEYLESS`, `KEYED`,
    or `KEY_STALE` to `ZEROIZED`, which is terminal; a radio already `ZEROIZED`
    cannot be zeroized again. Zeroizing clears `active_keyset_id` to null and
    leaves `provision_status` exactly as it was, and the `loaded_unit_count` of
    the keyset that was previously loaded is recomputed to reflect the departure."

    Design: Difficulty/non_linear_state_machine/subscriber_unit_parallel_dimensions_evolve_independently
    """
    agency, _template, unit, keyset = _echo_public_works_keyed_fleet(api)

    fx.lifecycle(api, unit["id"], agency["id"], ACTION_SUSPEND)

    zeroized = fx.lifecycle(api, unit["id"], agency["id"], ACTION_ZEROIZE)
    assert_unit_dimensions(zeroized, PROVISION_SUSPENDED, KEY_ZEROIZED)
    assert_nulls(zeroized, "active_keyset_id")

    departed = validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200)
    assert_fields(departed, loaded_unit_count=0)

    # The provisioning machine keeps running with the key gone.
    reinstated = fx.lifecycle(api, unit["id"], agency["id"], ACTION_REINSTATE)
    assert_unit_dimensions(reinstated, PROVISION_ASSIGNED, KEY_ZEROIZED)
    assert_nulls(reinstated, "active_keyset_id")
    assert_fields(reinstated, billable=True)
    assert_instant_equals(
        reinstated["assigned_at"], unit["assigned_at"], "assigned_at after REINSTATE"
    )


def test_unit_assignment_requires_published_template(api: ApiClient, clock_at_start: str):
    """A codeplug still in `DRAFT` may not be loaded onto a radio, and the refusal
    leaves both sides of the cross-entity dependency untouched.

    PRD 3.4: "**`ASSIGN`** takes a radio from `INVENTORY` to `ASSIGNED` and is
    the only action that consumes `template_id`; the field must be present and
    must resolve to an existing programming template. That template's `status`
    must be `PUBLISHED`, or the request is rejected with
    `ERR_TEMPLATE_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/unit_assignment_requires_published_template
    """
    agency = fx.register_agency(
        api,
        name="Oscar County EMS",
        agency_code="EMSO1",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    template = fx.create_template(
        api,
        template_name="OSCAR-DRAFT-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=6,
        encryption_required=False,
    )
    assert_fields(template, status=TEMPLATE_DRAFT, deployed_unit_count=0)
    unit = fx.add_unit(
        api,
        agency["id"],
        serial_number="SNO001",
        radio_id=9001,
        model=MODEL_PORTABLE,
        priority_class=4,
    )

    refused = api.unit_lifecycle(
        unit["id"],
        f.lifecycle_payload(ACTION_ASSIGN, template["id"]),
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(refused, ERR_TEMPLATE_NOT_PUBLISHED, 409)

    unchanged = fx.read_unit(api, unit["id"])
    assert_unit_dimensions(unchanged, PROVISION_INVENTORY, KEY_KEYLESS)
    assert_nulls(unchanged, "template_id", "assigned_at")
    assert_fields(unchanged, billable=False)
    assert_fields(fx.read_agency(api, agency["id"]), billable_subscriber_count=0)
    assert_fields(
        fx.read_template(api, template["id"]),
        status=TEMPLATE_DRAFT,
        deployed_unit_count=0,
    )


def test_unit_assignment_succeeds_once_the_template_is_published(
    api: ApiClient, clock_at_start: str
):
    """Publishing the identical codeplug flips the gate, and the successful
    assignment refreshes exactly the three declared derived figures.

    PRD 3.3: "Publication moves a template's `status` from `DRAFT` to
    `PUBLISHED` and increments its `version` by one; a template may be assigned
    to radios and approved for deployment only once it is `PUBLISHED`, and any
    other lifecycle position is rejected with `ERR_TEMPLATE_NOT_PUBLISHED`."

    PRD 3.4: "On success the unit's `template_id` is set to the supplied value,
    `assigned_at` is stamped with now, `billable` becomes true, and
    `provision_status` becomes `ASSIGNED` while `key_status` is left exactly as
    it was."

    Design: Difficulty/cross_entity_state_dependency/unit_assignment_requires_published_template
    """
    agency = fx.register_agency(
        api,
        name="Oscar County EMS",
        agency_code="EMSO1",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    template = fx.create_template(
        api,
        template_name="OSCAR-DRAFT-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=6,
        encryption_required=False,
    )
    unit = fx.add_unit(
        api,
        agency["id"],
        serial_number="SNO001",
        radio_id=9001,
        model=MODEL_PORTABLE,
        priority_class=4,
    )

    published = fx.publish_template(api, template["id"])
    assert_fields(
        published,
        status=TEMPLATE_PUBLISHED,
        template_version=1,
        version=template["version"] + 1,
    )

    assigned = validate_success(
        api.unit_lifecycle(
            unit["id"],
            f.lifecycle_payload(ACTION_ASSIGN, template["id"]),
            make_agency_radio_manager_headers(agency["id"]),
        ),
        200,
    )
    assert_unit_dimensions(assigned, PROVISION_ASSIGNED, KEY_KEYLESS)
    assert_fields(assigned, template_id=template["id"], billable=True)
    assert_instant_equals(assigned["assigned_at"], "2026-08-01T00:00:00Z", "assigned_at")

    # The three derived figures PRD 3.4 names, and nothing else.
    assert_fields(
        fx.read_agency(api, agency["id"]),
        billable_subscriber_count=1,
        governance_vote_weight=1,
        voting_eligible=True,
    )
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=1)
