"""Foreign facility inspections: scheduling overlap semantics, completion
findings, and the refusal cascade (PRD §3.8)."""

from test_helpers import (
    CLOCK_DEFAULT_UTC,
    DEFAULT_DETENTION_DEADLINE,
    TEST_USERS,
    ApiErrorId,
    complete_inspection,
    create_facility,
    create_importer,
    create_inspection_payload,
    create_prior_notice,
    create_entry,
    get_entry,
    get_facility,
    get_prior_notice,
    make_facility_owner_headers,
    refuse_inspection_entry,
    schedule_inspection,
    validate_error,
    validate_success,
)


def test_refuse_entry_on_completed_inspection_returns_inspection_not_open(api):
    """PRD §3.8: "The facility, for its part, may refuse to permit the
    inspection: a `FacilityOwner` whose `X-User-ID` equals the inspection's
    `facility_id` (else `ERR_OWNERSHIP_VIOLATION`) records the refusal while
    the inspection is `SCHEDULED` (else `ERR_INSPECTION_NOT_OPEN`)."

    Design: Corner/state_machines/refuse_entry_on_completed_inspection_returns_inspection_not_open
    """
    fac = create_facility(
        api=api,
        legal_name="Luzern Milchwerk",
        facility_kind="FOREIGN",
        country_code="CH",
        ufi="UFI-CH-2104",
    )
    insp = schedule_inspection(fac["id"], api=api)
    complete_inspection(insp, 0, api=api)
    resp = api.refuse_inspection_entry(
        insp["id"], make_facility_owner_headers(fac["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_OPEN)
    f = get_facility(fac["id"], api=api)
    assert f["registration_status"] == "REGISTERED", "no cascade may fire"
    assert f["violation_count"] == 0


def test_inspection_on_domestic_facility_returns_foreign_required(api):
    """PRD §3.8: "Scheduling supplies the target `facility_id` — which must
    belong to a `FOREIGN` facility, a `DOMESTIC` target failing with
    `ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY` (HTTP 422)".

    Design: Corner/validations/inspection_on_domestic_facility_returns_foreign_required
    """
    fac = create_facility(
        api=api,
        legal_name="Fresno Raisin Packers",
        facility_kind="DOMESTIC",
        country_code="US",
        ufi="UFI-US-2315",
    )
    resp = api.create_inspection(
        create_inspection_payload(
            facility_id=fac["id"],
            scheduled_start_at="2026-10-10T09:00:00Z",
            scheduled_end_at="2026-10-10T17:00:00Z",
        ),
        TEST_USERS["field_inspector_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY)


def test_inspection_completion_adds_findings_to_violation_count(api):
    """PRD §3.8: "Completion records the `findings_violation_count` (zero or
    greater) supplied in the report, adds it to the facility's
    `violation_count`, increments the facility's `version`, and moves the
    inspection to `COMPLETED`."

    Design: Corner/endpoints/inspection_completion_adds_findings_to_violation_count
    """
    fac = create_facility(
        api=api,
        legal_name="Iquique Salmon",
        facility_kind="FOREIGN",
        country_code="CL",
        ufi="UFI-CL-2603",
    )
    insp = schedule_inspection(fac["id"], api=api)
    done = complete_inspection(insp, 3, api=api)
    assert done["status"] == "COMPLETED"
    f = get_facility(fac["id"], api=api)
    assert f["violation_count"] == 3
    assert f["version"] == 2, "facility version increments from 1 to 2"


def test_inspection_refusal_cascade(api):
    """PRD §3.8: "**Link 1:** the facility itself — if currently `REGISTERED` —
    is suspended to `SUSPENDED` with `version` incremented".
    PRD §3.8: "**Link 2:** every import entry of that facility whose
    disposition is `PENDING`, whatever its `review_status`, is detained for
    cause exactly as in §3.6".
    PRD §3.8: "**Link 3:** every prior notice of the facility still in
    `CONFIRMED` is flipped to `COMPROMISED`, rendering it unusable for entry
    creation."

    Design: Difficulty/transitive_cascade/inspection_refusal_cascade
    """
    fac_h = create_facility(
        api=api,
        legal_name="Rur Konserven",
        facility_kind="FOREIGN",
        country_code="DE",
        ufi="UFI-DE-501",
    )
    imp5 = create_importer(
        api=api, firm_name="Bluegrass Brokers", account_code="IMP-501"
    )
    pn_h1 = create_prior_notice(
        imp5,
        fac_h,
        api=api,
        product_code="PC-PEA-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=60,
        unit_value_cents=300,
        port_code="US-CHS",
    )
    ent_h = create_entry(imp5, pn_h1, api=api)  # notice CONSUMED, entry PENDING
    pn_h2 = create_prior_notice(
        imp5,
        fac_h,
        api=api,
        product_code="PC-PEA-02",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-04T00:00:00Z",
        declared_units=30,
        unit_value_cents=300,
        port_code="US-CHS",
    )
    insp = schedule_inspection(fac_h["id"], api=api)

    refused = refuse_inspection_entry(insp, fac_h, api=api)
    assert refused["status"] == "REFUSED_BY_FACILITY"

    # Link 1: facility suspended.
    f = get_facility(fac_h["id"], api=api)
    assert f["registration_status"] == "SUSPENDED"
    # Link 2 derived counter.
    assert f["open_detention_count"] == 1

    # Link 2: the PENDING entry is detained for cause with a fresh 240h window.
    e = get_entry(ent_h["id"], api=api)
    assert e["disposition_status"] == "DETAINED"
    assert e["detained_at"] == CLOCK_DEFAULT_UTC
    assert e["response_deadline_at"] == DEFAULT_DETENTION_DEADLINE
    assert e["detained_under_alert_id"] is None, "cascade detention is for-cause"
    assert e["units_held"] == 60

    # Link 3: the unconsumed notice is compromised; the consumed one is spared.
    assert get_prior_notice(pn_h2["id"], api=api)["status"] == "COMPROMISED"
    assert get_prior_notice(pn_h1["id"], api=api)["status"] == "CONSUMED"


def test_inspector_calendar_half_open_overlap(api):
    """PRD §3.8: "One inspector may not hold two overlapping engagements: if
    the new interval intersects another `SCHEDULED` inspection of the same
    inspector — intervals being half-open, so a new start exactly equal to an
    existing end is adjacency and is allowed — scheduling fails with
    `ERR_INSPECTION_SCHEDULE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/inspector_calendar_half_open_overlap
    """
    fac_p = create_facility(
        api=api, legal_name="Bavaria Backerei", country_code="DE", ufi="UFI-DE-1201"
    )
    fac_q = create_facility(
        api=api, legal_name="Alpen Kaserei", country_code="DE", ufi="UFI-DE-1202"
    )
    insp_p = schedule_inspection(
        fac_p["id"],
        api=api,
        inspector_headers=TEST_USERS["field_inspector_headers"],  # fi-1
        scheduled_start_at="2026-10-10T09:00:00Z",
        scheduled_end_at="2026-10-10T17:00:00Z",
    )
    assert insp_p["status"] == "SCHEDULED"

    # Adjacency: new start == existing end is allowed under half-open semantics.
    adj_resp = api.create_inspection(
        create_inspection_payload(
            facility_id=fac_q["id"],
            scheduled_start_at="2026-10-10T17:00:00Z",
            scheduled_end_at="2026-10-11T09:00:00Z",
        ),
        TEST_USERS["field_inspector_headers"],
    )
    adj = validate_success(adj_resp, 201)
    assert adj["status"] == "SCHEDULED"

    # One minute earlier overlaps the same inspector's calendar.
    over_resp = api.create_inspection(
        create_inspection_payload(
            facility_id=fac_q["id"],
            scheduled_start_at="2026-10-10T16:59:00Z",
            scheduled_end_at="2026-10-10T18:00:00Z",
        ),
        TEST_USERS["field_inspector_headers"],
    )
    validate_error(over_resp, ApiErrorId.ERR_INSPECTION_SCHEDULE_OVERLAP)

    # The resource is the inspector's calendar: a different inspector may hold
    # the identical window.
    other_resp = api.create_inspection(
        create_inspection_payload(
            facility_id=fac_q["id"],
            scheduled_start_at="2026-10-10T16:59:00Z",
            scheduled_end_at="2026-10-10T18:00:00Z",
        ),
        TEST_USERS["field_inspector_two_headers"],  # fi-2
    )
    other = validate_success(other_resp, 201)
    assert other["status"] == "SCHEDULED"
