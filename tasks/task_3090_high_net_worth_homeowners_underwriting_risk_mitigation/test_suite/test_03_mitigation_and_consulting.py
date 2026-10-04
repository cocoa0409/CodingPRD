"""Mitigation requirements, the mitigation band cascade and the risk-consulting visit."""
from test_helpers import (
    api_client,
    assert_mitigation_requirement,
    create_consultation,
    create_underwritable_setup,
    get_success_data,
    impose_mitigation,
    reload_property,
    reset_clock,
    setup_consultation_slot,
    setup_mitigation_lapsed_property,
    validate_error,
    validate_success,
)


def test_mitigation_band_follows_the_ordered_cascade(api, underwriter_headers,
                                                     risk_consultant_headers):
    """PRD 3.3: "The property's `mitigation_band` summarizes the whole set and is read
    as an ordered cascade. If any verified requirement confers `CLEARED`, the band is
    `CLEARED`. Failing that, if any verified requirement confers `PARTIAL`, the band is
    `PARTIAL`. Failing that, if any requirement at all is `LAPSED` or `WAIVED`, the
    band is `FAILED`. Otherwise the band is `UNVERIFIED`."

    Design: Corner/validations/mitigation_verified_after_due_on_returns_lapsed
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZMIT",
                                                    agency_code="AGMIT")
    assert reload_property(prop["id"])["mitigation_band"] == "UNVERIFIED"

    partial = impose_mitigation(prop["id"], band_awarded="PARTIAL")
    get_success_data(api_client.verify_mitigation_requirement(
        partial["id"], "PARTIAL", risk_consultant_headers, verification_count=0))
    assert reload_property(prop["id"])["mitigation_band"] == "PARTIAL"

    # A verified CLEARED requirement outranks the PARTIAL one.
    cleared = impose_mitigation(prop["id"], requirement_code="FIRE_RESISTANT_ROOF",
                                band_awarded="CLEARED")
    get_success_data(api_client.verify_mitigation_requirement(
        cleared["id"], "CLEARED", risk_consultant_headers, verification_count=0))
    assert reload_property(prop["id"])["mitigation_band"] == "CLEARED"


def test_verification_is_a_compare_and_set_on_the_count(api, risk_consultant_headers,
                                                        underwriter_headers):
    """PRD 3.3: "The consultant supplies the `verified_band` observed in the field and,
    optionally, the `verification_count` last observed; a request carrying a count that
    no longer matches the stored one is refused rather than applying a second
    verification against a row the client has not re-read."

    Design: Corner/validations/mitigation_verified_after_due_on_returns_lapsed
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZCAS",
                                                    agency_code="AGCAS")
    req = impose_mitigation(prop["id"])
    assert req["verification_count"] == 0

    verified = validate_success(api_client.verify_mitigation_requirement(
        req["id"], "CLEARED", risk_consultant_headers, verification_count=0), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["verification_count"] == 1

    # Replaying the now-stale zero must not apply a second verification.
    res = api_client.verify_mitigation_requirement(
        req["id"], "CLEARED", risk_consultant_headers, verification_count=0)
    assert res.status_code >= 400, "a stale verification_count must be refused"


def test_verifying_after_the_due_date_is_refused(api, risk_consultant_headers):
    """PRD 3.3: "Verification must take place no later than the requirement's `due_on`
    — a verification attempted after that date is refused with `ERR_MITIGATION_LAPSED`."

    Design: Corner/validations/mitigation_verified_after_due_on_returns_lapsed
    """
    zone, agency, prop, req = setup_mitigation_lapsed_property(
        zone_code="ZLAPSE", agency_code="AGLAPSE",
        due_on="2026-12-01T00:00:00Z", clock_after="2026-12-02T00:00:00Z")
    assert req["status"] == "IMPOSED"

    res = api_client.verify_mitigation_requirement(
        req["id"], "CLEARED", risk_consultant_headers, verification_count=0)
    validate_error(res, "ERR_MITIGATION_LAPSED", expected_status=422)


def test_the_last_open_requirement_lapsing_fails_the_property(api,
                                                              risk_consultant_headers):
    """PRD 3.3: "When the last open requirement of a property lapses on its due date,
    or is waived, the property's gate closes: its `posture` becomes `WRITE_FROZEN` and
    every `DRAFT` or `SUBMITTED` enrollment of that property is driven to `DECLINED`."
    PRD 3.3: "Failing that, if any requirement at all is `LAPSED` or `WAIVED`, the band
    is `FAILED`."

    Design: Corner/validations/mitigation_verified_after_due_on_returns_lapsed
    """
    zone, agency, prop, req = setup_mitigation_lapsed_property(
        zone_code="ZLAPSE3", agency_code="AGLAPSE3")
    after = reload_property(prop["id"])
    assert after["base_posture"] == "DECLINED"
    assert after["posture"] == "WRITE_FROZEN"
    assert after["mitigation_band"] == "FAILED"

    # A lapsed row is no longer open for verification.
    open_rows = get_success_data(api_client.list_mitigation_requirements(
        prop["id"], risk_consultant_headers, params={"status": "IMPOSED"}))
    assert open_rows == []


def test_consultation_starting_exactly_at_the_previous_end_is_allowed(
        api, risk_consultant_headers):
    """PRD 3.3: "The overlap test uses a half-open interval running from `scheduled_for`
    to `scheduled_for` plus `duration_minutes`: an appointment starting exactly at the
    instant a previous one ends is adjacent, not overlapping, and is therefore allowed."

    Design: Difficulty/resource_temporal_overlap/risk_consultant_appointment_half_open_intervals_allow_adjacency
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZP1",
                                                    agency_code="AG15")
    first = setup_consultation_slot(prop["id"], scheduled_for="2026-09-10T09:00:00Z",
                                    duration_minutes=60, consultant_user_id="rc-dana")
    assert first["status"] == "SCHEDULED"

    adjacent = create_consultation(
        prop["id"], consultant_user_id="rc-dana",
        scheduled_for="2026-09-10T10:00:00Z", duration_minutes=30)
    assert adjacent["status"] == "SCHEDULED"


def test_consultation_overlapping_by_one_minute_is_refused(api, risk_consultant_headers):
    """PRD 3.3: "The booking is born `SCHEDULED` and is refused with
    `ERR_CONSULTATION_SLOT_CONFLICT` when it would overlap another non-cancelled
    consultation of the same consultant."

    Design: Difficulty/resource_temporal_overlap/risk_consultant_appointment_half_open_intervals_allow_adjacency
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZP2",
                                                    agency_code="AG152")
    setup_consultation_slot(prop["id"], scheduled_for="2026-09-10T09:00:00Z",
                            duration_minutes=60, consultant_user_id="rc-dana")

    res = api_client.create_risk_consultation(
        prop["id"],
        {"consultant_user_id": "rc-dana",
         "scheduled_for": "2026-09-10T08:59:00Z",
         "duration_minutes": 30},
        risk_consultant_headers)
    validate_error(res, "ERR_CONSULTATION_SLOT_CONFLICT", expected_status=409)


def test_consultation_exclusion_is_scoped_to_the_consultant(api, risk_consultant_headers):
    """PRD 3.3: "is refused with `ERR_CONSULTATION_SLOT_CONFLICT` when it would overlap
    another non-cancelled consultation of the same consultant."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZP3",
                                                    agency_code="AG153")
    setup_consultation_slot(prop["id"], scheduled_for="2026-09-10T09:00:00Z",
                            duration_minutes=60, consultant_user_id="rc-dana")

    other = create_consultation(
        prop["id"], consultant_user_id="rc-other",
        scheduled_for="2026-09-10T09:30:00Z", duration_minutes=30)
    assert other["consultant_user_id"] == "rc-other"


def test_cancelling_after_the_appointment_start_is_refused(api,
                                                           agency_producer_headers,
                                                           risk_consultant_headers):
    """PRD 3.3: "A scheduled visit may be completed by the consultant once the clock has
    reached `scheduled_for`, which stamps `completed_at`; it may be cancelled by a
    producer strictly before `scheduled_for`"

    Design: Corner/state_machines/consultation_cancel_after_the_appointment_has_started_is_refused
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZP4",
                                                    agency_code="AG154")
    reset_clock("2026-09-10T10:00:00Z")
    consult = create_consultation(prop["id"], consultant_user_id="rc-dana",
                                  scheduled_for="2026-09-10T09:00:00Z",
                                  duration_minutes=60)
    assert consult["status"] == "SCHEDULED"

    res = api_client.cancel_risk_consultation(consult["id"], agency_producer_headers)
    assert res.status_code >= 400, "cancel is only available strictly before scheduled_for"

    completed = validate_success(
        api_client.complete_risk_consultation(consult["id"], risk_consultant_headers), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] is not None


def test_consultation_report_imposes_its_recommendation(api, risk_consultant_headers):
    """PRD 3.3: "the visit's `report_issued_at` is stamped, a requirement is created
    with `source` `RISK_CONSULTANT` and status `IMPOSED`"
    PRD 3.5: "Imposing any requirement at all — from any source — moves an
    `UNDERWRITABLE` property to `MITIGATION_REQUIRED`"
    PRD 3.3: "The action answers with the pair of identifiers it produced — the
    `consultation_id` and the `mitigation_requirement_id` of the requirement it just
    imposed."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZP5",
                                                    agency_code="AG155")
    consult = create_consultation(prop["id"], consultant_user_id="rc-dana",
                                  scheduled_for="2026-09-10T09:00:00Z",
                                  duration_minutes=60)
    reset_clock("2026-09-10T10:00:00Z")
    get_success_data(api_client.complete_risk_consultation(consult["id"],
                                                           risk_consultant_headers))

    result = validate_success(api_client.issue_consultation_report(
        consult["id"],
        {"requirement_code": "EMBER_VENT_SCREEN", "band_awarded": "PARTIAL",
         "due_on": "2026-12-01T00:00:00Z"},
        risk_consultant_headers), 200)
    assert result["consultation_id"] == consult["id"]
    assert result["mitigation_requirement_id"]

    imposed = get_success_data(api_client.list_mitigation_requirements(
        prop["id"], risk_consultant_headers, params={"source": "RISK_CONSULTANT"}))
    assert len(imposed) == 1
    assert_mitigation_requirement(imposed[0])
    assert imposed[0]["status"] == "IMPOSED"
    assert reload_property(prop["id"])["base_posture"] == "MITIGATION_REQUIRED"