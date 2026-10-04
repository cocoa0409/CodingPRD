"""Registry surface (PRD §3.1): operator/mine creation defaults, request-shape
closure, and the logical clock's pinned startup reading (PRD §2.4).

Clock note: the logical clock starts at 2026-09-01T00:00:00Z and never reads
wall-clock time (PRD §2.4). Pinned readings in this file are >= that startup
instant; recipe-relative intervals are preserved.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_mine,
    assert_operator,
    assert_system_timestamp,
    create_operator_payload,
    is_valid_uuid,
    set_clock,
    setup_mine,
    setup_operator,
    validate_created,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]


def test_operator_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "An `MSHAAdmin` registers an operator by supplying its
    `legal_name`, its `annual_tonnage_tons`, and its `home_district`."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
    `created_at` and `updated_at` fields are ISO 8601 UTC timestamps;
    `updated_at` refreshes on every mutation of the resource."

    Design: Corner/entities/operator_create_returns_defaults_and_system_fields
    """
    set_clock("2026-09-10T08:00:00Z")
    payload = create_operator_payload(
        legal_name="Canyon Coal Co", annual_tonnage_tons=1000, home_district="D-11"
    )
    resp = api.create_operator(payload, _ADMIN)
    data = validate_created(resp)
    assert_operator(data)
    assert data["legal_name"] == "Canyon Coal Co"
    assert data["annual_tonnage_tons"] == 1000
    assert data["home_district"] == "D-11"
    assert is_valid_uuid(data["id"])
    # System timestamps stamp the logical-clock reading with 3-fraction-digit
    # rendering (PRD §2.4).
    assert data["created_at"] == "2026-09-10T08:00:00.000Z"
    assert data["updated_at"] == "2026-09-10T08:00:00.000Z"
    # PRD pins the +1-per-mutation version delta, not the start value; assert
    # the derivable contract (integer >= 1).
    assert isinstance(data["version"], int) and data["version"] >= 1


def test_mine_create_derives_posture_defaults(api):
    """PRD §3.1: "A new mine starts with `status` set to `ACTIVE`,
    `production_status` set to `NORMAL`, `pov_status` set to `NONE`, and no
    cycles at all."
    PRD §2.10: "List endpoints never error on an empty result set: a filter that
    matches nothing returns HTTP 200 with an empty array in `data`,
    `total_count` of 0, and `has_more` false."

    Design: Corner/entities/mine_create_derives_posture_defaults
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine = setup_mine(
        mine_type="UNDERGROUND",
        mine_name="Canyon No 1",
        activation_date="2026-09-01",
    )
    assert_mine(mine)
    assert mine["operator_id"] == operator["id"]
    assert mine["status"] == "ACTIVE"
    assert mine["production_status"] == "NORMAL"
    assert mine["pov_status"] == "NONE"
    assert isinstance(mine["version"], int) and mine["version"] >= 1
    cycles, meta = validate_paginated(api.list_inspection_cycles(mine["id"], _DM))
    assert cycles == [], "a new mine owns zero cycles until one is explicitly opened"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_mine_create_missing_mine_type_rejected(api):
    """PRD §3.1: "An `MSHAAdmin` then registers each **Mine** with a payload
    containing the owning `operator_id`, a `mine_name`, the `mine_type`, and the
    `activation_date` — the calendar date on which the mine became subject to
    the act and on which its first inspection cycle will begin."
    PRD §2.5 tier 3: "Required fields are present, no undeclared fields appear,
    enum values fall inside their declared sets, and integer ranges hold
    (`persons_affected` at least 1, `miners_withdrawn_count` at least 0,
    `annual_tonnage_tons` at least 0); otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/mine_create_missing_mine_type_rejected
    """
    operator = setup_operator()
    payload = {
        "operator_id": operator["id"],
        "mine_name": "Nameless Type Mine",
        "activation_date": "2026-09-01",
        # mine_type deliberately omitted
    }
    resp = api.create_mine(payload, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    mines, meta = validate_paginated(api.list_operator_mines(operator["id"], _ADMIN))
    assert mines == [] and meta["total_count"] == 0, (
        "a rejected create must leave no Mine resource behind"
    )


def test_mine_create_invalid_mine_type_rejected(api):
    """PRD §3.1: "The `mine_type` is either `UNDERGROUND` or `SURFACE`, and it
    drives both the statutory cycle length (§2.6) and the set of mine plans the
    mine must hold (§3.3)."
    PRD §2.5 tier 3: "Required fields are present, no undeclared fields appear,
    enum values fall inside their declared sets, and integer ranges hold
    (`persons_affected` at least 1, `miners_withdrawn_count` at least 0,
    `annual_tonnage_tons` at least 0); otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/mine_create_invalid_mine_type_rejected
    """
    operator = setup_operator()
    payload = {
        "operator_id": operator["id"],
        "mine_name": "Open Pit Mine",
        "mine_type": "OPEN_PIT",  # outside the declared enum
        "activation_date": "2026-09-01",
    }
    resp = api.create_mine(payload, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_mine_create_undeclared_status_field_rejected(api):
    """PRD §2.5 tier 3: "Required fields are present, no undeclared fields
    appear, enum values fall inside their declared sets, and integer ranges hold
    (`persons_affected` at least 1, `miners_withdrawn_count` at least 0,
    `annual_tonnage_tons` at least 0); otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "A new mine starts with `status` set to `ACTIVE`,
    `production_status` set to `NORMAL`, `pov_status` set to `NONE`, and no
    cycles at all."

    Design: Corner/entities/mine_create_undeclared_status_field_rejected
    """
    operator = setup_operator()
    payload = {
        "operator_id": operator["id"],
        "mine_name": "Pre-idled Mine",
        "mine_type": "SURFACE",
        "activation_date": "2026-09-01",
        "status": "IDLED",  # system-managed: smuggled seed fields are rejected
    }
    resp = api.create_mine(payload, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_clock_default_at_startup_is_fixed_epoch(api):
    """PRD §2.4: "Before any administrative call sets it, the logical clock
    reads exactly `2026-09-01T00:00:00Z`."
    PRD §2.4: "Time inside the domain is governed by a **logical clock**, never
    by wall-clock time."

    Design: Corner/entities/clock_default_at_startup_is_fixed_epoch
    """
    # Deliberately no set_clock call: the runner restarts the server against an
    # empty database before this test, so the clock is still at its pinned
    # startup reading when the operator is created.
    resp = api.create_operator(
        create_operator_payload(
            legal_name="Epoch Probe Co", annual_tonnage_tons=1000, home_district="D-00"
        ),
        _ADMIN,
    )
    data = validate_created(resp)
    assert_system_timestamp(data["created_at"], "Operator.created_at")
    assert data["created_at"] == "2026-09-01T00:00:00.000Z", (
        "created_at must read the pinned startup clock, not wall-clock time"
    )
