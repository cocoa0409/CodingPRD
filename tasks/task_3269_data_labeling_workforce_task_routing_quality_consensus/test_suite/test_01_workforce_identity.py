"""Workforce identity: registration, defaults, deterministic scoring, headers."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    compute_qualification_score,
    create_program_payload,
    create_worker_payload,
    validate_error,
    validate_success,
)


ADMIN = TEST_USERS["admin_headers"]


def test_worker_registration_returns_every_declared_default(api):
    """PRD §2.6: "Field workers hold a `payout_currency` of `USD`, `MXN`, `PHP`,
    `VND`, `BRL`, or `INR`, defaulting to `USD`, and a `settlement_min_cents`
    floor, defaulting to 1000, below which a settlement request is not
    accepted."

    Design: Corner/entities/worker_registration_returns_every_declared_field_at_zero_balance
    """
    resp = api.register_worker(create_worker_payload(handle="mira-vega"), TEST_USERS["anonymous_headers"])
    data = validate_success(resp, 201)

    assert data["handle"] == "mira-vega"
    assert data["payout_currency"] == "USD", "payout_currency must default to USD"
    assert data["settlement_min_cents"] == 1000, "settlement_min_cents must default to 1000"
    assert data["worker_receivable_cents"] == 0
    assert data["lifetime_earned_cents"] == 0
    assert data["restricted"] is False
    assert data["version"] == 1, "a fresh resource starts at version 1"


def test_worker_registration_zero_balance_invariants(api):
    """PRD §3.10: "Paying a commit raises `worker_receivable_cents`, the conserved
    quantity carried on the **WorkerIdentity** and computed as the sum of accepted
    payouts minus settled cents plus reversed cents, which is never negative."

    Design: Corner/entities/worker_registration_returns_every_declared_field_at_zero_balance
    """
    resp = api.register_worker(create_worker_payload(handle="kevin-lum"), TEST_USERS["anonymous_headers"])
    data = validate_success(resp, 201)

    assert data["worker_receivable_cents"] == 0
    assert data["lifetime_earned_cents"] == 0
    assert data["total_accepted_payout_cents"] == 0

    read = validate_success(api.get_worker(data["id"], ADMIN), 200)
    assert read["worker_receivable_cents"] == data["worker_receivable_cents"]
    assert read["lifetime_earned_cents"] == data["lifetime_earned_cents"]


def test_worker_explicit_overrides_replace_the_declared_defaults(api):
    """PRD §2.6: "The tier is `NOVICE`, `PROFICIENT`, or `EXPERT` and sets both the
    minimum score the worker must clear and the pay multiplier."

    PRD §2.6: "Field workers hold a `payout_currency` of `USD`, `MXN`, `PHP`,
    `VND`, `BRL`, or `INR`, defaulting to `USD`, and a `settlement_min_cents`
    floor, defaulting to 1000, below which a settlement request is not
    accepted."

    Design: Corner/entities/worker_creation_applies_every_declared_default
    """
    resp = api.register_worker(
        create_worker_payload(handle="linh-tran", payout_currency="VND", settlement_min_cents=5000),
        TEST_USERS["anonymous_headers"],
    )
    data = validate_success(resp, 201)

    assert data["payout_currency"] == "VND", "an explicit currency replaces the default"
    assert data["settlement_min_cents"] == 5000, "an explicit floor replaces the default"
    assert data.get("display_name") in (None, ""), "no default is declared for display_name"


def test_worker_system_fields_are_server_minted(api):
    """PRD §2.7: "Each resource carries a server-minted `id` formatted as a UUID
    string with no type prefix embedded in it. Each carries `created_at`, an ISO
    8601 timestamp in UTC with exactly three fractional digits."

    PRD §2.7: "Each carries `updated_at`, an ISO 8601 UTC timestamp with three
    fractional digits that is refreshed on every modification of the resource."

    Design: Corner/entities/worker_system_fields_are_server_generated_and_immutable
    """
    from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

    resp = api.register_worker(create_worker_payload(handle="priya-nair"), TEST_USERS["anonymous_headers"])
    data = validate_success(resp, 201)

    assert is_valid_uuid(data["id"]), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601 UTC"
    assert data["version"] == 1

    read = validate_success(api.get_worker(data["id"], ADMIN), 200)
    assert read["created_at"] == data["created_at"], "created_at is stable across reads"
    assert read["updated_at"] == read["created_at"], "updated_at equals created_at until a mutation"


def test_qualification_score_is_deterministic_from_handle_and_language(api):
    """PRD §2.6: "The qualification's `qualification_score` is not an input and not
    an audit result: it is derived deterministically from the worker's `handle`
    and is expressed as the sum of 5000 and the remainder, modulo 5000, of the
    quantity `len(handle)` multiplied by 977 plus the sum of the handle's
    character codes multiplied by 31 plus the sum of the language code's
    character codes multiplied by 17."

    Design: Corner/entities/qualification_score_is_deterministic_and_ignores_client_input
    """
    worker = validate_success(
        api.register_worker(create_worker_payload(handle="tomas-ibarra"), TEST_USERS["anonymous_headers"]),
        201,
    )
    expected = compute_qualification_score("tomas-ibarra", "es-MX")
    assert expected == 6724, "the deterministic score of tomas-ibarra in es-MX"

    resp = api.worker_qualification_action(
        worker["id"],
        {
            "language_code": "es-MX",
            "tier": "PROFICIENT",
            "qualification_action": "ENROLL",
            "qualification_score": 9999,
        },
        ADMIN,
    )
    data = validate_success(resp, 200)
    assert data["qualification_score"] == expected, "a client-supplied score is never read"
    assert data["tier_min_score"] == 6500

    hi_in = compute_qualification_score("tomas-ibarra", "hi-IN")
    assert hi_in == 6367, "the language code feeds the same formula"
    assert hi_in < 6500, "so the same handle can sit below its tier minimum"


def test_worker_registration_without_a_handle_returns_invalid_request(api):
    """PRD §2.11: "Two classes share the first rank and are checked first: the
    request-body completeness check, which refuses a body that is missing a
    required input field or supplies one with a value of the wrong type,
    reported as `ERR_INVALID_REQUEST` (400)"

    Design: Corner/entities/create_worker_without_a_handle_returns_invalid_request
    """
    resp = api.register_worker({}, TEST_USERS["anonymous_headers"])
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_unknown_sensitivity_class_is_refused_at_the_envelope_gate(api):
    """PRD §2.5: "An engagement declares a `sensitivity_class` of `STANDARD`,
    `SENSITIVE`, or `RESTRICTED` at registration, defaulting to `STANDARD`."

    Design: Corner/entities/sensitivity_class_enum_rejects_an_unknown_value
    """
    good = create_program_payload()
    data = validate_success(api.create_program(good, ADMIN), 201)
    assert data["sensitivity_class"] == "STANDARD", "omission takes the STANDARD default"

    bad = create_program_payload(sensitivity_class="TOP_SECRET")
    resp = api.create_program(bad, ADMIN)
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_missing_identity_header_returns_unauthenticated(api):
    """PRD §2.1: "The two headers must both be present and non-empty on every
    request; when either is missing or empty the request is refused with
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/missing_user_id_header_returns_unauthenticated
    """
    worker = validate_success(
        api.register_worker(create_worker_payload(handle="omar-haddad"), TEST_USERS["anonymous_headers"]),
        201,
    )

    anonymous = {"X-User-ID": "", "X-User-Role": "PlatformAdmin", "Content-Type": "application/json"}
    validate_error(api.get_worker(worker["id"], anonymous), "ERR_UNAUTHENTICATED", 401)
    validate_error(api.get_worker(NON_EXISTENT_UUID, anonymous), "ERR_UNAUTHENTICATED", 401)

    validate_success(api.get_worker(worker["id"], ADMIN), 200)


def test_only_the_admin_may_move_the_logical_clock(api):
    """PRD §2.9: "It maintains a logical clock that starts at exactly
    `2026-09-01T00:00:00Z` and only ever moves when a `PlatformAdmin` supplies a
    new instant as `current_utc` through the clock-setting capability. The clock
    never falls back to wall-clock time."

    Design: Corner/rbac/only_the_admin_may_move_the_logical_clock
    """
    validate_error(
        api.set_clock("2026-09-15T00:00:00Z", TEST_USERS["reviewer_headers"]),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.set_clock("2026-09-15T00:00:00Z", TEST_USERS["worker_headers"]),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_success(api.set_clock("2026-09-15T00:00:00Z", ADMIN), 200)