"""Breadth tests: encounter scheduling gates, affiliate lifecycle, stock listing."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_tx_clinic, setup_assessed_encounter, setup_completed_encounter,
    setup_patient_with_assessment,
    set_clock, create_affiliate, create_catalog_entry, create_patient,
    create_assessment, create_encounter, create_stock_lot,
    create_device_reservation,
    get_stock_lot, get_encounter,
    TEST_USERS, FPL_INCOME_H1_PCT_265, ENC_START, ENC_END,
    LARC_START, LARC_END,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
SUPPLY = TEST_USERS["supply_coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_encounter_with_inverted_interval_rejected(api):
    """PRD §3.4: "The **temporal well-formedness** check runs on every
    encounter creation: `scheduled_end` must be strictly greater than
    `scheduled_start` ... a malformed interval [rejects the encounter with
    `ERR_INVALID_INTERVAL` (HTTP 400)]."

    An inverted interval is 400 ERR_INVALID_INTERVAL and persists no
    encounter.

    Design: Corner/validations/encounter_with_inverted_interval_rejected
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    res = api_client.create_encounter(
        patient["id"],
        {"service_code": "CONTRACEPTIVE_COUNSELING",
         "provider_id": clinic["provider"]["id"],
         "channel": "IN_PERSON",
         "scheduled_start": "2026-09-10T10:30:00Z",
         "scheduled_end": "2026-09-10T10:00:00Z"},
        FRONT_DESK,
    )
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=400)
    rows, meta = validate_paginated(
        api_client.list_patient_encounters(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 0


def test_affiliate_close_blocked_by_open_encounters(api):
    """PRD §3.1: "A `GrantAdministrator` may close an affiliate from either
    `ACTIVE` or `SUSPENDED`, but only when the affiliate has no encounter in
    `SCHEDULED` or `IN_PROGRESS` — otherwise the closure is rejected with
    `ERR_AFFILIATE_HAS_OPEN_ENCOUNTERS` (HTTP 409)."

    Close with a SCHEDULED encounter is 409; after cancelling it, close
    succeeds and the affiliate is CLOSED.

    Design: Corner/validations/affiliate_close_blocked_by_open_encounters
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_assessed_encounter(clinic, income_cents=FPL_INCOME_H1_PCT_265)
    aff = clinic["affiliate"]

    res = api_client.close_affiliate(aff["id"], ADMIN)
    validate_error(res, "ERR_AFFILIATE_HAS_OPEN_ENCOUNTERS",
                   expected_status=409)
    still_active = validate_success(api_client.get_affiliate(aff["id"], ADMIN))
    assert still_active["status"] == "ACTIVE"

    validate_success(api_client.cancel_encounter(ctx["encounter"]["id"],
                                                 FRONT_DESK))
    closed = validate_success(api_client.close_affiliate(aff["id"], ADMIN))
    assert closed["status"] == "CLOSED"


def test_lot_expired_for_normal_reservation_but_within_grace_for_rapid(api):
    """PRD §3.6: "A normal reservation may not use a lot whose `expires_on`
    precedes the encounter date at all; such a create is rejected with
    `ERR_LOT_EXPIRED` (HTTP 422)."
    PRD §3.6: "An eligible rapid reinsertion may draw from a lot whose
    `expires_on` falls within a 7-day grace window around the encounter date
    — a tolerance that does not apply to normal reservations."

    A lot expiring 2026-09-20 cannot serve a normal reservation for a
    2026-09-25 encounter, but an eligible rapid reinsertion (expulsion 10
    days prior) may use it under the grace.

    Design: Corner/validations/lot_expired_for_normal_reservation_but_within_grace_for_rapid
    """
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION",
        enc_start="2026-09-25T10:00:00Z", enc_end="2026-09-25T10:30:00Z",
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IMPLANT",
                           lot_number="LOT-E", unit_cost_cents=40000,
                           on_hand=2, expires_on="2026-09-20")

    res = api_client.create_device_reservation(
        ctx["encounter"]["id"], {"lot_id": lot["id"]}, SUPPLY,
    )
    validate_error(res, "ERR_LOT_EXPIRED", expected_status=422)

    rapid = validate_success(
        api_client.create_device_reservation(
            ctx["encounter"]["id"],
            {"lot_id": lot["id"],
             "is_rapid_reinsertion": True,
             "expulsion_recorded_at": "2026-09-15T10:00:00Z"},
            SUPPLY,
        ),
        201,
    )
    assert rapid["status"] == "RESERVED"
    assert get_stock_lot(lot["id"])["reserved_out"] == 1, (
        "only the eligible rapid reservation holds a unit"
    )


def test_rapid_reinsertion_beyond_thirty_days_rejected(api):
    """PRD §3.6: "A reservation flagged as rapid reinsertion is eligible only
    when the gap between the encounter's `scheduled_start` and the supplied
    `expulsion_recorded_at` is at most 30 days, evaluated with second
    precision; the comparison is inclusive, so exactly 30 days is eligible
    and 30 days plus one second is not, with violations rejected as
    `ERR_REINSERTION_WINDOW_EXCEEDED` (HTTP 422)."

    Expulsion exactly 30 days before the encounter is eligible; 30 days +
    59:59 beyond is rejected.

    Design: Corner/validations/rapid_reinsertion_beyond_thirty_days_rejected
    """
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    enc_ok = create_encounter(
        patient["id"], clinic["provider"]["id"],
        service_code="LARC_INSERTION",
        scheduled_start="2026-10-10T10:00:00Z",
        scheduled_end="2026-10-10T10:30:00Z",
    )
    enc_late = create_encounter(
        patient["id"], clinic["provider"]["id"],
        service_code="LARC_INSERTION",
        scheduled_start="2026-10-10T11:00:00Z",
        scheduled_end="2026-10-10T11:30:00Z",
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IMPLANT",
                           lot_number="LOT-W", unit_cost_cents=40000,
                           on_hand=2, expires_on="2027-01-01")

    eligible = validate_success(
        api_client.create_device_reservation(
            enc_ok["id"],
            {"lot_id": lot["id"],
             "is_rapid_reinsertion": True,
             "expulsion_recorded_at": "2026-09-10T10:00:00Z"},
            SUPPLY,
        ),
        201,
    )
    assert eligible["status"] == "RESERVED", (
        "exactly 30 days (2026-09-10T10:00 -> 2026-10-10T10:00) is eligible"
    )

    res = api_client.create_device_reservation(
        enc_late["id"],
        {"lot_id": lot["id"],
         "is_rapid_reinsertion": True,
         "expulsion_recorded_at": "2026-09-10T10:59:59Z"},
        SUPPLY,
    )
    validate_error(res, "ERR_REINSERTION_WINDOW_EXCEEDED",
                   expected_status=422)
    assert get_stock_lot(lot["id"])["reserved_out"] == 1


def test_encounter_create_without_current_assessment_rejected(api):
    """PRD §3.4: "The new encounter pins the patient's `CURRENT` household
    assessment into its `assessment_id` field at scheduling time; if no
    current assessment exists, creation is rejected with
    `ERR_NO_CURRENT_ASSESSMENT` (HTTP 422)."

    A registered but never-assessed patient cannot be scheduled.

    Design: Corner/endpoints/encounter_create_without_current_assessment_rejected
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    patient = create_patient(clinic["affiliate"]["id"], external_ref="NA-1",
                             date_of_birth="1990-01-01")
    res = api_client.create_encounter(
        patient["id"],
        {"service_code": "CONTRACEPTIVE_COUNSELING",
         "provider_id": clinic["provider"]["id"],
         "channel": "IN_PERSON",
         "scheduled_start": ENC_START,
         "scheduled_end": ENC_END},
        FRONT_DESK,
    )
    validate_error(res, "ERR_NO_CURRENT_ASSESSMENT", expected_status=422)
    rows, meta = validate_paginated(
        api_client.list_patient_encounters(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 0


def test_waive_billing_only_for_confidential_or_minor(api):
    """PRD §3.7: "Waiver is the alternative path: a `BillingSpecialist` may
    waive billing on a `COMPLETED`/`UNBILLED` encounter whenever the patient
    is confidential — that is, the patient's `confidentiality_flag` is `true`
    or the patient was a minor at encounter time — flipping billing from
    `UNBILLED` to `WAIVED`."
    PRD §5: "`ERR_INVALID_STATE` | 409 Conflict".

    Waiving a non-confidential adult's completed encounter is a 409 and
    billing stays UNBILLED.

    Design: Corner/endpoints/waive_billing_only_for_confidential_or_minor
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_completed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    res = api_client.waive_billing(ctx["encounter"]["id"], BILLING)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    enc_after = get_encounter(ctx["encounter"]["id"])
    assert enc_after["billing_status"] == "UNBILLED"


def test_affiliate_suspend_cascade_blocks_new_encounters(api):
    """PRD §2.7: "Suspending an affiliate transitions every `ACTIVE` catalog
    entry of that affiliate to `SUSPENDED` ... A catalog entry that is
    `SUSPENDED` blocks creation of new encounters for that `service_code`,
    with the rejection surfacing as `ERR_SERVICE_OUT_OF_SCOPE`".

    After suspension, the catalog entry reads SUSPENDED and new encounter
    creation on an existing patient of that affiliate is rejected.

    Design: Corner/endpoints/affiliate_suspend_cascade_blocks_new_encounters
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    aff = clinic["affiliate"]
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    validate_success(api_client.suspend_affiliate(aff["id"], ADMIN))

    res = api_client.create_encounter(
        patient["id"],
        {"service_code": "CONTRACEPTIVE_COUNSELING",
         "provider_id": clinic["provider"]["id"],
         "channel": "IN_PERSON",
         "scheduled_start": ENC_START,
         "scheduled_end": ENC_END},
        FRONT_DESK,
    )
    validate_error(res, "ERR_SERVICE_OUT_OF_SCOPE", expected_status=422)

    entries, _meta = validate_paginated(
        api_client.list_catalog_entries(aff["id"], ADMIN)
    )
    assert len(entries) == 1
    assert entries[0]["status"] == "SUSPENDED", (
        "the affiliate-level cascade flipped the entry to SUSPENDED"
    )


def test_stock_lot_list_filters_by_device_code(api):
    """PRD §4: "GET | `/family-planning/affiliates/{id}/stock-lots` | List
    stock lots | GrantAdministrator, SupplyCoordinator, Clinician" — the
    list accepts a `device_code` filter parameter.
    PRD §2.3: "All list endpoints accept the optional query parameters
    `limit` and `offset`."

    Filtering by device_code narrows the list to the two IUD_COPPER lots;
    the unfiltered list returns all three.

    Design: Corner/endpoints/stock_lot_list_filters_by_device_code
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    create_stock_lot(aff["id"], device_code="IUD_COPPER", lot_number="F-1",
                     unit_cost_cents=10000, on_hand=5)
    create_stock_lot(aff["id"], device_code="IUD_COPPER", lot_number="F-2",
                     unit_cost_cents=11000, on_hand=5)
    create_stock_lot(aff["id"], device_code="IMPLANT", lot_number="F-3",
                     unit_cost_cents=40000, on_hand=3)

    filtered, meta = validate_paginated(
        api_client.list_stock_lots(aff["id"], SUPPLY,
                                   params={"device_code": "IUD_COPPER"})
    )
    assert len(filtered) == 2
    assert all(lot["device_code"] == "IUD_COPPER" for lot in filtered)
    assert meta["total_count"] == 2

    unfiltered, _meta2 = validate_paginated(
        api_client.list_stock_lots(aff["id"], SUPPLY)
    )
    assert len(unfiltered) == 3
