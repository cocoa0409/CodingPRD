"""The declined-enrollment cascade and the defense-completion cascade."""
from test_helpers import (
    api_client,
    assert_managed_risk_event,
    assert_mitigation_requirement,
    create_agency,
    create_property,
    create_zone,
    get_success_data,
    make_agency_producer_headers,
    reload_property,
    request_dispatch,
    run_posture_eval,
    setup_active_zone_mitigation_required,
    setup_active_zone_underwritable,
    setup_two_property_cascade_book,
    validate_error,
    validate_success,
)


def test_declining_an_enrollment_cancels_the_property_defense_request(
        api, underwriter_headers):
    """PRD 3.9: "In the first hop, every defense dispatch of the property that is still
    in `REQUESTED` transitions to `CANCELLED`, with `vendor_ref` cleared, `assigned_at`
    reset, and `defense_in_progress` recomputed to false."

    Design: Difficulty/transitive_cascade/enrollment_decline_cascades_through_dispatch_zone_and_posture
    """
    (zone, agency, (p1, e1, dispatch), (p2, e2)) = setup_two_property_cascade_book(
        zone_code="ZH1", agency_code="AG7")
    assert dispatch["status"] == "REQUESTED"
    assert reload_property(p1["id"])["defense_in_progress"] is False

    declined = validate_success(api_client.decline_enrollment(
        e1["id"], "underwriting", underwriter_headers), 200)
    assert declined["status"] == "DECLINED"
    assert declined["committed_reserve_cents"] == 0

    # Hop 1: the queued defense request is cancelled.
    after = get_success_data(api_client.list_property_dispatches(
        p1["id"], underwriter_headers))
    assert len(after) == 1
    assert after[0]["status"] == "CANCELLED"
    assert after[0]["vendor_ref"] is None
    assert after[0]["assigned_at"] is None
    assert reload_property(p1["id"])["defense_in_progress"] is False


def test_declining_an_enrollment_reruns_concentration_across_the_book(
        api, underwriter_headers):
    """PRD 3.9: "a cancelled request returns insured value to the zone's exposure base,
    which sends the second hop across the whole book: concentration is recomputed for
    the dispatch's own zone and for every other zone, re-deriving
    `concentration_ratio_pct`, `concentration_band` and `freeze_active` everywhere,
    since the portfolio denominator itself has moved."
    PRD 2.10: "When the portfolio holds fewer than two such enrollments the ratio is
    pinned to 0.0 and the band to `NORMAL`"

    Design: Difficulty/transitive_cascade/enrollment_decline_cascades_through_dispatch_zone_and_posture
    """
    (zone, agency, (p1, e1, dispatch), (p2, e2)) = setup_two_property_cascade_book(
        zone_code="ZH1B", agency_code="AG7B")

    before = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    # Both dwellings share one zone, so that zone is the entire active book.
    assert before["concentration_ratio_pct"] == 100.0
    assert before["concentration_band"] == "CRITICAL"
    assert before["freeze_active"] is True

    validate_success(api_client.decline_enrollment(
        e1["id"], "underwriting", underwriter_headers), 200)

    # One ACTIVE enrollment remains, so the book is below the population minimum.
    after = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert after["concentration_ratio_pct"] == 0.0
    assert after["concentration_band"] == "NORMAL"
    assert after["freeze_active"] is False
    # The surviving enrollment is untouched by the sweep.
    surviving = get_success_data(api_client.get_enrollment(e2["id"], underwriter_headers))
    assert surviving["status"] in ("SUBMITTED", "REFERRED")


def test_declining_a_draft_enrollment_unwinds_the_property(
        api, underwriter_headers):
    """PRD 3.9: "it is launched by any decline — whether an underwriter declined an
    enrollment directly from `DRAFT`, `SUBMITTED` or `REFERRED`"
    PRD 3.9: "The declined enrollment itself recomputes `committed_reserve_cents` to 0"

    Design: Difficulty/transitive_cascade/enrollment_decline_cascades_through_dispatch_zone_and_posture
    """
    zone = create_zone(zone_code="ZH1C", state_event="ACTIVE")
    agency = create_agency(agency_code="AG7C")
    prop = create_property(zone["id"], agency["id"])
    dispatch = request_dispatch(prop["id"], underwriter_headers)
    assert dispatch["status"] == "REQUESTED"

    draft = get_success_data(api_client.create_enrollment(
        prop["id"],
        {"agency_id": agency["id"], "dwelling_coverage_cents": 300_000_000,
         "contents_coverage_cents": 0, "scheduled_coverage_cents": 0,
         "loss_of_use_coverage_cents": 0},
        make_agency_producer_headers(agency["id"])))
    assert draft["status"] == "DRAFT"

    declined = validate_success(api_client.decline_enrollment(
        draft["id"], "producer request", underwriter_headers), 200)
    assert declined["status"] == "DECLINED"
    assert declined["committed_reserve_cents"] == 0

    cancelled = get_success_data(api_client.list_property_dispatches(
        prop["id"], underwriter_headers))[0]
    assert cancelled["status"] == "CANCELLED"


def test_completing_a_dispatch_imposes_a_defensible_space_requirement(
        api, underwriter_headers):
    """PRD 3.6: "Completion is not a mere bookkeeping event — it auto-imposes a
    `DEFENSIBLE_SPACE` requirement with `band_awarded` `CLEARED` and `source`
    `DEFENSE_FOLLOW_UP`"

    Design: Difficulty/transitive_cascade/defense_completion_cascades_into_mitigation_and_posture
    """
    zone, agency, prop, existing = setup_active_zone_mitigation_required(
        zone_code="ZI1", agency_code="AG8")
    assert prop["base_posture"] == "MITIGATION_REQUIRED"

    request_dispatch(prop["id"], underwriter_headers)
    get_success_data(api_client.poll_vendors(zone["id"], underwriter_headers))
    listing = get_success_data(api_client.list_property_dispatches(
        prop["id"], underwriter_headers))
    dispatch = listing[0]

    validate_success(api_client.advance_dispatch(dispatch["id"], underwriter_headers), 200)
    completed = validate_success(
        api_client.advance_dispatch(dispatch["id"], underwriter_headers), 200)
    assert completed["status"] == "COMPLETED"

    # Hop 2: a requirement no request named is now on the property.
    follow_ups = get_success_data(api_client.list_mitigation_requirements(
        prop["id"], underwriter_headers, params={"source": "DEFENSE_FOLLOW_UP"}))
    assert len(follow_ups) == 1
    assert_mitigation_requirement(follow_ups[0])
    assert follow_ups[0]["requirement_code"] == "DEFENSIBLE_SPACE"
    assert follow_ups[0]["band_awarded"] == "CLEARED"
    assert follow_ups[0]["status"] == "IMPOSED"
    assert reload_property(prop["id"])["base_posture"] == "MITIGATION_REQUIRED"


def test_verifying_the_follow_up_requirement_restores_the_gate(
        api, underwriter_headers, risk_consultant_headers):
    """PRD 3.6: "if that new requirement is verified as `CLEARED` within 14 days the
    property returns to `UNDERWRITABLE`."

    Design: Difficulty/transitive_cascade/defense_completion_cascades_into_mitigation_and_posture
    """
    zone, agency, prop = setup_active_zone_underwritable(
        zone_code="ZI1B", agency_code="AG8B")
    assert prop["base_posture"] == "UNDERWRITABLE"
    request_dispatch(prop["id"], underwriter_headers)
    get_success_data(api_client.poll_vendors(zone["id"], underwriter_headers))
    dispatch = get_success_data(api_client.list_property_dispatches(
        prop["id"], underwriter_headers))[0]
    validate_success(api_client.advance_dispatch(dispatch["id"], underwriter_headers), 200)
    validate_success(api_client.advance_dispatch(dispatch["id"], underwriter_headers), 200)

    follow_up = get_success_data(api_client.list_mitigation_requirements(
        prop["id"], underwriter_headers, params={"source": "DEFENSE_FOLLOW_UP"}))[0]
    validate_success(api_client.verify_mitigation_requirement(
        follow_up["id"], "CLEARED", risk_consultant_headers,
        verification_count=0), 200)

    after = reload_property(prop["id"])
    assert after["mitigation_band"] == "CLEARED"
    assert after["base_posture"] == "UNDERWRITABLE"


def test_a_second_verification_records_a_repeat_inspection_notice(
        api, underwriter_headers, risk_consultant_headers):
    """PRD 3.3: "That history matters on the second pass: if the count reaches 2, a
    `ManagedRiskEvent` of `event_type` `REPEAT_INSPECTION_NOTICE` is recorded, unless a
    letter carrying the identical key already exists."

    Design: Difficulty/transitive_cascade/defense_completion_cascades_into_mitigation_and_posture
    """
    zone, agency, prop, requirement = _mitigation_ready_property(
        zone_code="ZRL", agency_code="AGRL")

    first = validate_success(api_client.verify_mitigation_requirement(
        requirement["id"], "CLEARED", risk_consultant_headers, verification_count=0), 200)
    assert first["verification_count"] == 1

    reopened = validate_success(api_client.reopen_mitigation_requirement(
        requirement["id"], "2026-12-01T00:00:00Z", risk_consultant_headers), 200)
    assert reopened["status"] == "IMPOSED"
    assert reopened["verification_count"] == 1

    second = validate_success(api_client.verify_mitigation_requirement(
        requirement["id"], "CLEARED", risk_consultant_headers, verification_count=1), 200)
    assert second["verification_count"] == 2

    letters = get_success_data(api_client.list_property_managed_risk_events(
        prop["id"], underwriter_headers, params={"event_type": "REPEAT_INSPECTION_NOTICE"}))
    assert len(letters) == 1
    assert_managed_risk_event(letters[0])
    assert prop["id"] in letters[0]["derived_key"]


def _mitigation_ready_property(zone_code, agency_code):
    """An underwritable property carrying one IMPOSED requirement."""
    from test_helpers import add_approved_appraisal, impose_mitigation

    zone = create_zone(zone_code=zone_code)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    requirement = impose_mitigation(prop["id"], requirement_code="FIRE_RESISTANT_ROOF",
                                    band_awarded="CLEARED", source="UNDERWRITING",
                                    due_on="2026-12-01T00:00:00Z")
    return zone, agency, reload_property(prop["id"]), requirement