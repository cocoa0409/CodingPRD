"""Depth tests: interval semantics and the zero-available stock boundary."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_tx_clinic, setup_assessed_encounter,
    create_affiliate, create_affiliate_with_tiers_abcd,
    create_catalog_entry, create_provider, create_license,
    create_patient, create_assessment, create_stock_lot,
    create_device_reservation, create_privacy_hold_payload,
    set_clock, get_stock_lot,
    TEST_USERS, FPL_INCOME_H1_PCT_265, LARC_START, LARC_END,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]
SUPPLY = TEST_USERS["supply_coordinator_headers"]


def _setup_short_license_clinic(api):
    """Clinic whose provider holds a deliberately short TX license.

    License covers [2026-09-10T09:00, 2026-09-10T10:30) only.
    """
    set_clock("2026-09-01T00:00:00Z")
    aff, _tiers = create_affiliate_with_tiers_abcd(quota=50)
    create_catalog_entry(aff["id"], service_code="CONTRACEPTIVE_COUNSELING",
                         in_scope=True, telehealth_eligible=True,
                         full_fee_cents=20000)
    provider = create_provider(aff["id"])
    create_license(provider["id"], state_code="TX",
                   valid_from="2026-09-10T09:00:00Z",
                   valid_until="2026-09-10T10:30:00Z")
    patient = create_patient(aff["id"], external_ref="T1",
                             date_of_birth="1990-01-01")
    create_assessment(patient, household_size=1,
                      annual_income_cents=FPL_INCOME_H1_PCT_265,
                      income_basis="DOCUMENTED")
    return aff, provider, patient


def _telehealth_payload(provider_id, start, end):
    return {
        "service_code": "CONTRACEPTIVE_COUNSELING",
        "provider_id": provider_id,
        "channel": "TELEHEALTH",
        "patient_location_state": "TX",
        "scheduled_start": start,
        "scheduled_end": end,
    }


def test_encounter_fully_inside_license_interval_accepted(api):
    """PRD §3.4: "the entire half-open encounter interval
    `[scheduled_start, scheduled_end)` must be contained in the half-open
    license interval `[valid_from, valid_until)`."

    An encounter [09:30, 10:00) fully inside the license [09:00, 10:30) is
    created successfully.

    Design: Difficulty/resource_temporal_overlap/telehealth_license_must_contain_whole_encounter_interval
    """
    _aff, provider, patient = _setup_short_license_clinic(api)
    enc = validate_success(
        api_client.create_encounter(
            patient["id"],
            _telehealth_payload(provider["id"],
                                "2026-09-10T09:30:00Z",
                                "2026-09-10T10:00:00Z"),
            FRONT_DESK,
        ),
        201,
    )
    assert enc["clinical_status"] == "SCHEDULED"


def test_license_expiring_mid_encounter_rejected(api):
    """PRD §3.4: "The containment is over the **whole** encounter interval:
    a license valid at the start instant but expiring mid-encounter fails
    the check, and point-in-time checks are forbidden ... Failure is rejected
    with `ERR_TELEHEALTH_LICENSE_GAP` (HTTP 422)."

    An encounter [10:00, 11:00) starts inside the license [09:00, 10:30) but
    ends past valid_until — rejected even though the start instant is covered.

    Design: Difficulty/resource_temporal_overlap/telehealth_license_must_contain_whole_encounter_interval
    """
    _aff, provider, patient = _setup_short_license_clinic(api)
    res = api_client.create_encounter(
        patient["id"],
        _telehealth_payload(provider["id"],
                            "2026-09-10T10:00:00Z",
                            "2026-09-10T11:00:00Z"),
        FRONT_DESK,
    )
    validate_error(res, "ERR_TELEHEALTH_LICENSE_GAP", expected_status=422)


def test_adjacent_privacy_holds_do_not_overlap(api):
    """PRD §3.11: "Adjacent intervals — where the new hold's `hold_start`
    equals the existing hold's `hold_end` — do **not** overlap and do
    **not** merge; they remain distinct holds."

    A hold starting exactly at the existing hold's hold_end is accepted and
    both holds persist as distinct ACTIVE rows.

    Design: Difficulty/resource_temporal_overlap/privacy_hold_adjacent_intervals_do_not_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    patient = create_patient(aff["id"], external_ref="T2",
                             date_of_birth="1990-01-01")
    validate_success(
        api_client.create_privacy_hold(
            patient["id"],
            create_privacy_hold_payload(
                hold_start="2026-09-01T00:00:00Z",
                hold_end="2026-09-10T00:00:00Z", scope="ALL",
                authorized_staff_ids=[],
            ),
            PRIVACY,
        ),
        201,
    )
    adjacent = validate_success(
        api_client.create_privacy_hold(
            patient["id"],
            create_privacy_hold_payload(
                hold_start="2026-09-10T00:00:00Z",
                hold_end="2026-09-20T00:00:00Z", scope="ALL",
                authorized_staff_ids=[],
            ),
            PRIVACY,
        ),
        201,
    )
    assert adjacent["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api_client.list_privacy_holds(patient["id"], PRIVACY)
    )
    assert len(rows) == 2, (
        "the adjacent hold remains distinct — the system never silently merges"
    )
    assert meta["total_count"] == 2


def test_overlapping_privacy_hold_rejected(api):
    """PRD §3.11: "Two half-open intervals overlap exactly when the existing
    hold's `hold_start` is strictly before the new hold's `hold_end` **and**
    the new hold's `hold_start` is strictly before the existing hold's
    `hold_end`. ... Overlapping same-scope holds are rejected with
    `ERR_PRIVACY_HOLD_OVERLAP` (HTTP 409); the system never silently merges."

    A hold starting one second before the existing hold's hold_end overlaps
    and is rejected with 409.

    Design: Difficulty/resource_temporal_overlap/privacy_hold_adjacent_intervals_do_not_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    patient = create_patient(aff["id"], external_ref="T2b",
                             date_of_birth="1990-01-01")
    validate_success(
        api_client.create_privacy_hold(
            patient["id"],
            create_privacy_hold_payload(
                hold_start="2026-09-01T00:00:00Z",
                hold_end="2026-09-20T00:00:00Z", scope="ALL",
                authorized_staff_ids=[],
            ),
            PRIVACY,
        ),
        201,
    )
    res = api_client.create_privacy_hold(
        patient["id"],
        create_privacy_hold_payload(
            hold_start="2026-09-19T23:59:59Z",
            hold_end="2026-09-25T00:00:00Z", scope="ALL",
            authorized_staff_ids=[],
        ),
        PRIVACY,
    )
    validate_error(res, "ERR_PRIVACY_HOLD_OVERLAP", expected_status=409)
    rows, meta = validate_paginated(
        api_client.list_privacy_holds(patient["id"], PRIVACY)
    )
    assert len(rows) == 1


def _setup_two_patients_one_unit_lot(api):
    """Two SCHEDULED LARC encounters and a lot with exactly one unit."""
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    ctx1 = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION", enc_start=LARC_START, enc_end=LARC_END,
        external_ref="Z1",
    )
    ctx2 = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION",
        enc_start="2026-09-15T11:00:00Z", enc_end="2026-09-15T11:30:00Z",
        external_ref="Z2",
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IUD_COPPER",
                           lot_number="LOT-Z", unit_cost_cents=15000,
                           on_hand=1, expires_on="2027-01-01")
    return clinic, ctx1, ctx2, lot


def test_lot_with_one_available_unit_accepts_exactly_one_reservation(api):
    """PRD §3.6: "The lot must have `on_hand` minus `reserved_out` greater
    than or equal to 1; otherwise the create is rejected with
    `ERR_STOCK_UNAVAILABLE` (HTTP 422). On success, the lot's `reserved_out`
    increments by 1 and `on_hand` is unchanged".

    A lot with on_hand 1 accepts the first reservation (available 1 >= 1),
    leaving on_hand 1 and reserved_out 1.

    Design: Difficulty/boundary_precision_check/stock_zero_available_boundary
    """
    _clinic, ctx1, _ctx2, lot = _setup_two_patients_one_unit_lot(api)
    reservation = create_device_reservation(ctx1["encounter"]["id"], lot["id"])
    assert reservation["status"] == "RESERVED"
    lot_after = get_stock_lot(lot["id"])
    assert lot_after["on_hand"] == 1
    assert lot_after["reserved_out"] == 1, (
        "available is now exactly 0 — the boundary the next request crosses"
    )


def test_second_reservation_at_zero_available_rejected(api):
    """PRD §3.6: "The lot must have `on_hand` minus `reserved_out` greater
    than or equal to 1; otherwise the create is rejected with
    `ERR_STOCK_UNAVAILABLE` (HTTP 422)."

    With available units at exactly 0 the second reservation is rejected and
    reserved_out does not drift past the physical pool.

    Design: Difficulty/boundary_precision_check/stock_zero_available_boundary
    """
    _clinic, ctx1, ctx2, lot = _setup_two_patients_one_unit_lot(api)
    create_device_reservation(ctx1["encounter"]["id"], lot["id"])
    res = api_client.create_device_reservation(
        ctx2["encounter"]["id"], {"lot_id": lot["id"]}, SUPPLY,
    )
    validate_error(res, "ERR_STOCK_UNAVAILABLE", expected_status=422)
    lot_after = get_stock_lot(lot["id"])
    assert lot_after["reserved_out"] == 1, (
        f"rejection leaves reserved_out at 1, got {lot_after['reserved_out']}"
    )
    assert lot_after["on_hand"] == 1
