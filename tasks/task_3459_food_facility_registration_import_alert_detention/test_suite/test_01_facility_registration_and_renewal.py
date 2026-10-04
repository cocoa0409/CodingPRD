"""Facility registration, biennial renewal window, expiry sweep, and renewal OCC
(PRD §3.1 lifecycle rules, §2.4 ops checkpoint, §2.7 optimistic concurrency)."""

from test_helpers import (
    CLOCK_DEFAULT_UTC,
    DEFAULT_EXPIRES_AT,
    DEFAULT_RENEWAL_WINDOW_OPEN,
    FIRST_REGISTRATION_NUMBER,
    TEST_USERS,
    ApiErrorId,
    assert_facility,
    create_facility,
    create_facility_payload,
    get_facility,
    is_valid_uuid,
    make_facility_owner_headers,
    renew_facility,
    renew_facility_payload,
    set_clock,
    setup_expired_facility,
    setup_suspended_facility,
    validate_error,
    validate_success,
)


def test_first_facility_gets_minted_registration_number_and_biennial_expiry(api):
    """PRD §3.1: "A new facility is created with `registration_status` set to
    `REGISTERED`, with `registered_at` set to the current logical-clock instant,
    and with `expires_at` computed as `registered_at` plus 730 days."
    PRD §2.5: "each Facility carries a server-minted `registration_number` in
    the format `FFR-NNNNNN` — a zero-padded, monotonically increasing sequence
    whose first issued value is `FFR-000001`."

    Design: Corner/entities/facility_creation_assigns_registration_number_and_biennial_expiry
    """
    resp = api.create_facility(
        create_facility_payload(
            legal_name="Acme Brine Works",
            facility_kind="DOMESTIC",
            country_code="US",
            ufi="UFI-US-0001",
        ),
        TEST_USERS["facility_owner_headers"],
    )
    fac = validate_success(resp, 201)
    assert_facility(fac)
    assert fac["registration_number"] == FIRST_REGISTRATION_NUMBER, (
        f"first facility from an empty database must be FFR-000001, got "
        f"{fac['registration_number']}"
    )
    assert fac["registration_status"] == "REGISTERED"
    assert fac["version"] == 1
    assert fac["registered_at"] == CLOCK_DEFAULT_UTC
    assert fac["expires_at"] == DEFAULT_EXPIRES_AT, (
        f"registered_at + 730 days must be 2028-08-31T00:00:00Z, got "
        f"{fac['expires_at']}"
    )
    assert fac["violation_count"] == 0
    assert fac["open_detention_count"] == 0
    assert is_valid_uuid(fac["id"])
    meta = resp.json().get("meta", {})
    assert meta.get("api_request_id"), "response envelope must carry meta.api_request_id"
    assert meta.get("api_request_timestamp"), (
        "response envelope must carry meta.api_request_timestamp"
    )


def test_facility_get_with_unknown_id_returns_facility_not_found(api):
    """PRD §2.9: "the system validates identifiers in a strict left-to-right
    order as they appear in the path, and rejects the request with the `404`
    error corresponding to the *first* identifier that does not resolve:
    `ERR_FACILITY_NOT_FOUND` for a Facility".

    Design: Corner/entities/facility_get_with_unknown_id_returns_facility_not_found
    """
    resp = api.get_facility(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["platform_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND)


def test_facility_duplicate_ufi_rejected(api):
    """PRD §3.1: "The `ufi` must be unique across all registered facilities; a
    duplicate is rejected with `ERR_DUPLICATE_UFI` (HTTP 409)."

    Design: Corner/entities/facility_duplicate_ufi_rejected
    """
    first = create_facility(
        api=api,
        legal_name="Rioja Bodega",
        facility_kind="FOREIGN",
        country_code="ES",
        ufi="UFI-ES-2002",
    )
    resp = api.create_facility(
        create_facility_payload(
            legal_name="Rioja Bodega Segunda",
            facility_kind="FOREIGN",
            country_code="ES",
            ufi="UFI-ES-2002",
        ),
        TEST_USERS["facility_owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UFI)
    after = get_facility(first["id"], api=api)
    assert after["legal_name"] == "Rioja Bodega"
    assert after["version"] == 1


def test_renewal_at_window_open_extends_old_expiry(api):
    """PRD §3.1: "the renewal window runs from 90 days before `expires_at`
    through 30 days after `expires_at`, both bounds inclusive" and "When the
    facility is still `REGISTERED` at renewal time (the current instant is
    before `expires_at`), the new `expires_at` extends the old one by a further
    730 days."

    Design: Corner/calculations/renewal_from_registered_extends_old_expiry_at_window_open_boundary
    """
    fac = create_facility(
        api=api,
        legal_name="Sapporo Seafoods",
        facility_kind="FOREIGN",
        country_code="JP",
        ufi="UFI-JP-2201",
    )
    set_clock(DEFAULT_RENEWAL_WINDOW_OPEN, api=api)  # 2028-06-02: expires_at - 90d
    pre = get_facility(fac["id"], api=api)
    assert pre["registration_status"] == "REGISTERED"
    assert pre["version"] == 1
    renewed = renew_facility(fac, expected_facility_version=pre["version"], api=api)
    assert renewed["registration_status"] == "REGISTERED"
    assert renewed["expires_at"] == "2030-08-31T00:00:00Z", (
        f"REGISTERED renewal must extend the old expiry 2028-08-31 by 730 days, "
        f"got {renewed['expires_at']}"
    )
    assert renewed["version"] == 2


def test_renewal_window_closed_after_grace_end(api):
    """PRD §3.1: "Provided the state permits it, the renewal window runs from
    90 days before `expires_at` through 30 days after `expires_at`, both bounds
    inclusive; a request outside that window fails with
    `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/renewal_window_closed_for_registered_facility
    """
    fac = setup_expired_facility(
        "2028-10-15T00:00:00Z",
        api=api,
        legal_name="Cusco Cafe",
        facility_kind="FOREIGN",
        country_code="PE",
        ufi="UFI-PE-2314",
    )
    assert fac["registration_status"] == "EXPIRED"
    assert fac["version"] == 2
    resp = api.renew_facility(
        fac["id"],
        renew_facility_payload(fac["version"]),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
    after = get_facility(fac["id"], api=api)
    assert after["registration_status"] == "EXPIRED"


def test_renewal_with_stale_version_returns_stale_version(api):
    """PRD §2.7: "If it does not match the facility's current `version` —
    because another writer's renewal or a cascade-driven mutation advanced it
    since — the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/renewal_with_stale_version_returns_stale_version
    """
    fac = create_facility(
        api=api,
        legal_name="Quito Cacao",
        facility_kind="FOREIGN",
        country_code="EC",
        ufi="UFI-EC-2701",
    )
    set_clock(DEFAULT_RENEWAL_WINDOW_OPEN, api=api)
    cur = get_facility(fac["id"], api=api)
    stale = api.renew_facility(
        fac["id"],
        renew_facility_payload(cur["version"] - 1),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    ok = renew_facility(fac, expected_facility_version=cur["version"], api=api)
    assert ok["registration_status"] == "REGISTERED"
    assert ok["expires_at"] == "2030-08-31T00:00:00Z"
    assert ok["version"] == 2


def test_facility_expiry_renewal_cycle_loops_twice(api):
    """PRD §3.1: "the expiry sweep itself is strictly-less-than as described in
    §2.4 — at the exact instant of `expires_at`, the facility is still
    registered."
    PRD §3.1: "When the facility has already lapsed to `EXPIRED` (the current
    instant is at or after `expires_at`), the new `expires_at` is instead set to
    the current logical instant plus 730 days and the facility returns to
    `REGISTERED`."

    Design: Difficulty/non_linear_state_machine/facility_registration_expiry_renewal_cycle
    """
    fac = create_facility(
        api=api,
        legal_name="Alvorada Alimentos",
        facility_kind="FOREIGN",
        country_code="BR",
        ufi="UFI-BR-401",
    )
    assert fac["expires_at"] == DEFAULT_EXPIRES_AT
    assert fac["version"] == 1

    # Exactly at expires_at the sweep must NOT fire (strictly-less-than).
    set_clock(DEFAULT_EXPIRES_AT, api=api)
    at_expiry = get_facility(fac["id"], api=api)
    assert at_expiry["registration_status"] == "REGISTERED", (
        "at current time == expires_at the facility is still REGISTERED"
    )

    # One day past expiry the sweep flips it EXPIRED.
    set_clock("2028-09-01T00:00:00Z", api=api)
    expired = get_facility(fac["id"], api=api)
    assert expired["registration_status"] == "EXPIRED"
    assert expired["version"] == 2

    # Grace renewal (window closes 2028-09-30) rebases expiry to now + 730 days.
    renewed = renew_facility(fac, expected_facility_version=expired["version"], api=api)
    assert renewed["registration_status"] == "REGISTERED"
    assert renewed["expires_at"] == "2030-09-01T00:00:00Z", (
        f"EXPIRED renewal must rebase to now + 730 days, got {renewed['expires_at']}"
    )
    assert renewed["version"] == 3

    # The loop closes a second time.
    set_clock("2030-09-02T00:00:00Z", api=api)
    final = get_facility(fac["id"], api=api)
    assert final["registration_status"] == "EXPIRED"


def test_renewal_state_error_beats_temporal_error(api):
    """PRD §2.6: "a renewal attempted on a `SUSPENDED` facility reports the
    state failure `ERR_FACILITY_NOT_RENEWABLE` even if the renewal window is
    also closed".

    Design: Difficulty/priority_pair_validation_conflict/renewal_state_beats_temporal
    """
    ctx = setup_suspended_facility(
        api=api,
        legal_name="Douro Conservas",
        facility_kind="FOREIGN",
        country_code="PT",
        ufi="UFI-PT-701",
    )
    fac = ctx["facility"]
    assert fac["registration_status"] == "SUSPENDED"
    # Past the grace end 2028-09-30: the temporal window is closed too.
    set_clock("2028-10-15T00:00:00Z", api=api)
    cur = get_facility(fac["id"], api=api)
    resp = api.renew_facility(
        fac["id"],
        renew_facility_payload(cur["version"]),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_RENEWABLE)
    after = get_facility(fac["id"], api=api)
    assert after["registration_status"] == "SUSPENDED"
    assert after["expires_at"] == DEFAULT_EXPIRES_AT
