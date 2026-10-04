"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the API before every test. Setup calls
use `get_success_data()` so a failed precondition reads as "Setup failed" rather
than as a confusing assertion failure in the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_agency_payload,
    create_appraisal_document_payload,
    create_appraisal_payload,
    create_claim_payload,
    create_enrollment_payload,
    create_mitigation_requirement_payload,
    create_non_renewal_notice_payload,
    create_property_payload,
    create_risk_consultation_payload,
    create_risk_zone_payload,
    create_scheduled_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_agency_producer_headers,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
RC = TEST_USERS["risk_consultant_headers"]
OPS = TEST_USERS["platform_admin_headers"]


# ─── Primitives ───────────────────────────────────────────────────────────────

def reset_clock(instant=CLOCK_START):
    """Advance the logical clock to `instant` (deterministic 'now' for the API)."""
    return get_success_data(api_client.set_clock(instant, OPS))


def create_zone(zone_code="ZTEST", **overrides):
    """Register a catastrophe risk zone."""
    payload = create_risk_zone_payload(zone_code=zone_code, **overrides)
    return get_success_data(api_client.create_risk_zone(payload, OPS))


def create_agency(agency_code="AGTEST", **overrides):
    """Register a producing agency."""
    payload = create_agency_payload(agency_code=agency_code, **overrides)
    return get_success_data(api_client.create_agency(payload, OPS))


def create_property(risk_zone_id, agency_id, address_line="1 Test Rd", **overrides):
    """Register a dwelling in a zone for a producing agency."""
    payload = create_property_payload(risk_zone_id, agency_id,
                                      address_line=address_line, **overrides)
    return get_success_data(api_client.create_property(payload, UW))


def reload_property(property_id):
    """Read a property's current derived posture, valuation and version."""
    return get_success_data(api_client.get_property(property_id, UW))


def run_posture_eval(property_id, expected_property_version=None):
    """Run the ordered underwriting gate, defaulting to a freshly read version."""
    if expected_property_version is None:
        expected_property_version = reload_property(property_id)["version"]
    res = api_client.posture_eval(property_id, expected_property_version, UW)
    return res


def create_appraisal(property_id, **overrides):
    """Record a replacement-cost appraisal (born PENDING_REVIEW).

    PRD §3.1: "Replacement-cost valuation begins when an underwriter records an
    appraisal against a dwelling" — the caller is an opaque operator identity,
    never an Agency id (PRD §2.1), so `appraiser_name` (not the acting agency)
    names the appraiser.
    """
    return get_success_data(api_client.create_appraisal(
        property_id, create_appraisal_payload(**overrides), UW))


def review_and_approve_appraisal(appraisal_id):
    """Walk an appraisal PENDING_REVIEW -> REVIEWED -> APPROVED."""
    get_success_data(api_client.review_appraisal(appraisal_id, UW))
    return get_success_data(api_client.approve_appraisal(appraisal_id, UW))


def add_approved_appraisal(property_id, **overrides):
    """Record, review and approve an appraisal in one step."""
    appr = create_appraisal(property_id, **overrides)
    return review_and_approve_appraisal(appr["id"])


def create_appraisal_document(property_id, **overrides):
    """File an appraisal document substantiating scheduled property."""
    return get_success_data(api_client.create_appraisal_document(
        property_id, create_appraisal_document_payload(**overrides), UW))


def create_scheduled_item(property_id, appraisal_doc_id, **overrides):
    """Schedule an item against a dwelling (born PENDING)."""
    return get_success_data(api_client.create_scheduled_item(
        property_id, create_scheduled_item_payload(appraisal_doc_id, **overrides),
        make_agency_producer_headers(_agency_of(property_id))))


def add_approved_scheduled_item(property_id, item_type="JEWELRY",
                                declared_value_cents=50_000_000,
                                appraised_value_cents=60_000_000):
    """File a document, schedule the matching item and approve it."""
    prop = reload_property(property_id)
    doc = create_appraisal_document(property_id, item_class=item_type,
                                    appraised_value_cents=appraised_value_cents)
    item = get_success_data(api_client.create_scheduled_item(
        property_id,
        create_scheduled_item_payload(doc["id"], item_type=item_type,
                                      declared_value_cents=declared_value_cents),
        make_agency_producer_headers(prop["agency_id"])))
    return get_success_data(api_client.approve_scheduled_item(item["id"], UW))


def _agency_of(property_id):
    """The producing agency recorded on a dwelling."""
    return reload_property(property_id)["agency_id"]


def impose_mitigation(property_id, **overrides):
    """Impose a mitigation requirement (born IMPOSED)."""
    payload = create_mitigation_requirement_payload(**overrides)
    return get_success_data(api_client.create_mitigation_requirement(
        property_id, payload, RC))


def verify_mitigation(requirement_id, verified_band, verification_count=None):
    """Verify a requirement within its due date."""
    return get_success_data(api_client.verify_mitigation_requirement(
        requirement_id, verified_band, RC, verification_count=verification_count))


def add_verified_mitigation(property_id, band_awarded="CLEARED",
                            verified_band=None, **overrides):
    """Impose and verify one mitigation requirement in a single step."""
    req = impose_mitigation(property_id, band_awarded=band_awarded, **overrides)
    verified = verified_band or band_awarded
    return get_success_data(api_client.verify_mitigation_requirement(
        req["id"], verified, RC, verification_count=0))


def create_consultation(property_id, **overrides):
    """Book a complimentary risk-consulting visit."""
    return get_success_data(api_client.create_risk_consultation(
        property_id, create_risk_consultation_payload(**overrides), RC))


def request_dispatch(property_id, headers=None):
    """Request private wildfire defense for a dwelling during an active event."""
    return get_success_data(api_client.request_dispatch(property_id, headers or UW))


def create_enrollment(property_id, agency_id=None, **overrides):
    """Open a policy enrollment for a dwelling (born DRAFT)."""
    if agency_id is None:
        agency_id = _agency_of(property_id)
    return get_success_data(api_client.create_enrollment(
        property_id, create_enrollment_payload(agency_id, **overrides),
        make_agency_producer_headers(agency_id)))


def submit_enrollment(enrollment_id, agency_id):
    """Submit a draft enrollment for underwriting."""
    return get_success_data(api_client.submit_enrollment(
        enrollment_id, make_agency_producer_headers(agency_id)))


def refer_enrollment(enrollment_id):
    return get_success_data(api_client.refer_enrollment(enrollment_id, UW))


def approve_enrollment(enrollment_id):
    """Approve an enrollment and snapshot its terms."""
    return get_success_data(api_client.approve_enrollment(enrollment_id, UW))


def attach_enrollment(enrollment_id, property_id, expected_property_version=None):
    """Bind the enrollment, defaulting to a freshly read property version."""
    if expected_property_version is None:
        expected_property_version = reload_property(property_id)["version"]
    return get_success_data(api_client.attach_enrollment(
        enrollment_id, expected_property_version, UW))


def recall_enrollment(enrollment_id, agency_id):
    return get_success_data(api_client.recall_enrollment(
        enrollment_id, make_agency_producer_headers(agency_id)))


def report_claim(enrollment_id, **overrides):
    return get_success_data(api_client.create_claim(
        enrollment_id, create_claim_payload(**overrides), ADJ))


def review_claim(claim_id):
    return get_success_data(api_client.review_claim(claim_id, ADJ))


def approve_claim(claim_id):
    return get_success_data(api_client.approve_claim(claim_id, ADJ))


def settle_claim(claim_id):
    return get_success_data(api_client.settle_claim(claim_id, ADJ))


def create_non_renewal_notice(enrollment_id, **overrides):
    return get_success_data(api_client.create_non_renewal_notice(
        enrollment_id, create_non_renewal_notice_payload(**overrides), UW))


# ─── Tier 1: State Progression ────────────────────────────────────────────────

def create_underwritable_setup(zone=None, agency=None, dwelling_cost_cents=None,
                               with_cleared_mitigation=False, **property_overrides):
    """Zone + agency + property with an approved site appraisal, posture evaluated.

    Returns (zone, agency, property). The property is left UNDERWRITABLE in an
    EXTREME / WITHIN_WUI zone, so its write-facing posture is REFERRAL_REQUIRED.
    """
    zone = zone or create_zone("ZSETUP")
    agency = agency or create_agency("AGSETUP")
    prop = create_property(zone["id"], agency["id"], **property_overrides)
    if dwelling_cost_cents is not None:
        add_approved_appraisal(prop["id"], dwelling_cost_cents=dwelling_cost_cents)
    else:
        add_approved_appraisal(prop["id"])
    if with_cleared_mitigation:
        add_verified_mitigation(prop["id"], band_awarded="CLEARED")
    run_posture_eval(prop["id"])
    return zone, agency, reload_property(prop["id"])


def create_underwritable_property(zone=None, agency=None, **property_overrides):
    """Same as create_underwritable_setup, returning only the property."""
    _, _, prop = create_underwritable_setup(zone=zone, agency=agency,
                                            **property_overrides)
    return prop


def create_write_eligible_property(zone_code="ZELIG", agency_code="AGELIG",
                                   **property_overrides):
    """A property whose posture resolves to WRITE_ELIGIBLE.

    An ELEVATED zone outside the WUI clears the referral branch, so a site
    appraisal with no mitigation yields WRITE_ELIGIBLE.
    """
    zone = create_zone(zone_code=zone_code, wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"], **property_overrides)
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    return zone, agency, reload_property(prop["id"])


# ─── Tier 2: Entity Hierarchy ─────────────────────────────────────────────────

def setup_property_with_scheduled_item(item_type="COLLECTION",
                                       declared_value_cents=50_000_000,
                                       dwelling_cost_cents=200_000_000):
    """Zone + agency + property (approved appraisal) + one approved scheduled item.

    The zone is ELEVATED/OUTSIDE_WUI so the gate's EXTREME/WITHIN_WUI
    auto-imposition does not fire and the dwelling's posture resolves to
    WRITE_ELIGIBLE (PRD §2.9's WUI referral branch is gated on `exposure_band`
    being `ELEVATED`).
    """
    zone = create_zone("ZSCHED", wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="STANDARD", sustained_wind_mph=35)
    agency = create_agency("AGSCHED")
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"], dwelling_cost_cents=dwelling_cost_cents)
    run_posture_eval(prop["id"])
    item = add_approved_scheduled_item(
        prop["id"], item_type=item_type, declared_value_cents=declared_value_cents,
        appraised_value_cents=declared_value_cents + 10_000_000)
    return zone, agency, reload_property(prop["id"]), item


# ─── Tier 3: Full Lifecycle Shortcuts ─────────────────────────────────────────

def setup_submitted_enrollment(zone_code="ZSUB", agency_code="AGSUB", zone_kwargs=None,
                               coverage_cents=300_000_000, dwelling_cost_cents=200_000_000,
                               mitigation_band="CLEARED", **property_overrides):
    """Property through to a SUBMITTED enrollment. Returns (zone, agency, prop, enroll).

    With `mitigation_band="CLEARED"` the property is design-cleared, so approval
    snapshots the EXTENDED replacement provision.
    """
    zone = create_zone(zone_code=zone_code, **(zone_kwargs or {}))
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"], **property_overrides)
    add_approved_appraisal(prop["id"], dwelling_cost_cents=dwelling_cost_cents)
    if mitigation_band is not None:
        add_verified_mitigation(prop["id"], band_awarded=mitigation_band,
                                verified_band=mitigation_band)
    run_posture_eval(prop["id"])
    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=coverage_cents)
    submit_enrollment(enroll["id"], agency["id"])
    return zone, agency, prop, notify_state(enroll)


def notify_state(enroll, status=None):
    """Small helper so fixtures always hand back the freshest enrollment row."""
    refreshed = get_success_data(api_client.get_enrollment(
        enroll["id"], TEST_USERS["underwriter_headers"]))
    if status is not None:
        assert refreshed["status"] == status, (
            f"expected enrollment {refreshed['id']} in {status}, got {refreshed['status']}")
    return refreshed


def setup_approved_enrollment(zone_code="ZAPPR", agency_code="AGAPPR", zone_kwargs=None,
                              coverage_cents=300_000_000, dwelling_cost_cents=200_000_000,
                              mitigation_band="CLEARED", **property_overrides):
    """Property through to an APPROVED (unbound) enrollment.

    Returns (zone, agency, prop, enrollment). The enrollment's snapshotted
    replacement_provision is EXTENDED when mitigation is CLEARED.
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code=zone_code, agency_code=agency_code, zone_kwargs=zone_kwargs,
        coverage_cents=coverage_cents, dwelling_cost_cents=dwelling_cost_cents,
        mitigation_band=mitigation_band, **property_overrides)
    approved = approve_enrollment(enroll["id"])
    return zone, agency, reload_property(prop["id"]), approved


def setup_attached_enrollment(zone_code="ZATT", agency_code="AGATT", zone_kwargs=None,
                              coverage_cents=300_000_000, dwelling_cost_cents=200_000_000,
                              mitigation_band="CLEARED", **property_overrides):
    """Property through to a bound (ATTACHED) enrollment.

    Returns (zone, agency, prop, enrollment).
    """
    zone, agency, prop, enroll = setup_approved_enrollment(
        zone_code=zone_code, agency_code=agency_code, zone_kwargs=zone_kwargs,
        coverage_cents=coverage_cents, dwelling_cost_cents=dwelling_cost_cents,
        mitigation_band=mitigation_band, **property_overrides)
    attached = attach_enrollment(enroll["id"], prop["id"])
    return zone, agency, reload_property(prop["id"]), attached


def setup_bound_claim(zone_code="ZCLAIM", agency_code="AGCLAIM", **claim_overrides):
    """Bound enrollment plus one reported claim. Returns (zone, agency, prop, enroll, claim)."""
    zone, agency, prop, enroll = setup_attached_enrollment(
        zone_code=zone_code, agency_code=agency_code)
    claim = report_claim(enroll["id"], **claim_overrides)
    return zone, agency, prop, enroll, claim


def setup_reviewed_claim(zone_code="ZCLMRV", agency_code="AGCLMRV", **claim_overrides):
    """Bound enrollment plus a claim walked into UNDER_REVIEW."""
    zone, agency, prop, enroll, claim = setup_bound_claim(
        zone_code=zone_code, agency_code=agency_code, **claim_overrides)
    reviewed = review_claim(claim["id"])
    return zone, agency, prop, enroll, reviewed

# ─── Tier 4: Accumulation / Threshold Targeting ───────────────────────────────

def setup_scheduled_cap_boundary(dwelling_cost_cents=200_000_000,
                                 existing_scheduled_cents=50_000_000):
    """A property whose 60 percent scheduled-value cap is exactly computable.

    Total insured value is dwelling + the one approved item, so the aggregate
    cap is exactly 0.60 x total_insured_value_cents. Returns (zone, agency, prop, item).
    """
    zone, agency, prop, item = setup_property_with_scheduled_item(
        item_type="COLLECTION", declared_value_cents=existing_scheduled_cents,
        dwelling_cost_cents=dwelling_cost_cents)
    return zone, agency, prop, item


def file_document_and_schedule(property_id, item_type="JEWELRY",
                               declared_value_cents=50_000_000,
                               appraised_value_cents=60_000_000,
                               appraisal_date=TEST_DEFAULTS["DOC_APPRAISAL_DATE"],
                               item_class=None):
    """File a document and schedule a matching item, leaving it PENDING.

    Returns (document, item). Use this when the test itself drives the approval.
    """
    prop = reload_property(property_id)
    doc = create_appraisal_document(property_id, item_class=item_class or item_type,
                                    appraisal_date=appraisal_date,
                                    appraised_value_cents=appraised_value_cents)
    item = get_success_data(api_client.create_scheduled_item(
        property_id,
        create_scheduled_item_payload(doc["id"], item_type=item_type,
                                      declared_value_cents=declared_value_cents),
        make_agency_producer_headers(prop["agency_id"])))
    return doc, item


def setup_zone_with_requested_dispatches(count=3, zone_code="ZDISP",
                                         agency_code="AGDISP", state_event="ACTIVE",
                                         headroom_minutes=0):
    """An active zone with `count` dwellings, each holding a REQUESTED dispatch.

    Returns (zone, agency, requests) where `requests[i] == (property, dispatch)`.
    """
    zone = create_zone(zone_code=zone_code, state_event=state_event)
    agency = create_agency(agency_code=agency_code)
    requests = []
    for i in range(count):
        prop = create_property(zone["id"], agency["id"],
                               address_line=f"{i + 1} Crag Rd")
        disp = request_dispatch(prop["id"])
        requests.append((prop, disp))
    return zone, agency, requests


def setup_consultation_slot(property_id, scheduled_for="2026-09-10T09:00:00Z",
                            duration_minutes=60, consultant_user_id=None):
    """Book one SCHEDULED consultation for a named consultant."""
    kwargs = {"scheduled_for": scheduled_for, "duration_minutes": duration_minutes}
    if consultant_user_id is not None:
        kwargs["consultant_user_id"] = consultant_user_id
    return create_consultation(property_id, **kwargs)


# ─── Tier 5: Finalization / Terminal State ────────────────────────────────────

def setup_declined_property(zone_code="ZDECL", agency_code="AGDECL",
                            zone_kwargs=None, dwelling_cost_cents=100_000_000,
                            signed_valuation_cents=200_000_000):
    """A property driven to DECLINED by a guarantee-ratio failure.

    The property's dwelling valuation is `signed_valuation_cents` from one
    approved appraisal, so admitting a second approved appraisal of a smaller
    amount is the condition that drives the gate to DECLINED.
    """
    zone = create_zone(zone_code=zone_code, **(zone_kwargs or {}))
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"], dwelling_cost_cents=signed_valuation_cents)
    add_approved_appraisal(prop["id"], dwelling_cost_cents=dwelling_cost_cents)
    res = run_posture_eval(prop["id"])
    assert res.status_code == 200, f"Setup failed: posture-eval {res.status_code} {res.text}"
    return zone, agency, reload_property(prop["id"])


def setup_mitigation_lapsed_property(zone_code="ZLAPSE", agency_code="AGLAPSE",
                                     due_on="2026-12-01T00:00:00Z",
                                     clock_after="2026-12-02T00:00:00Z"):
    """Underwritable property with one IMPOSED requirement whose due date has passed.

    Returns (zone, agency, prop, requirement). The clock has already crossed `due_on`.
    """
    zone, agency, prop = create_underwritable_setup(
        zone=create_zone(zone_code=zone_code), agency=create_agency(agency_code=agency_code))
    req = impose_mitigation(prop["id"], requirement_code="FIRE_RESISTANT_ROOF",
                            source="RISK_CONSULTANT", due_on=due_on)
    reset_clock(clock_after)
    return zone, agency, reload_property(prop["id"]), req


def setup_active_zone_mitigation_required(zone_code="ZDEFENSE", agency_code="AGDEFENSE"):
    """An ACTIVE EXTREME/OUTSIDE_WUI zone with one MITIGATION_REQUIRED property.

    The property holds an IMPOSED DEFENSIBLE_SPACE requirement (PARTIAL), so the
    gate has already moved it off UNDERWRITABLE.  The zone is OUTSIDE_WUI so the
    WUI referral branch does not fire (PRD §2.9 gates it on `WITHIN_WUI` or
    `ADJACENT_WUI`), which keeps the property's posture legible.

    Returns (zone, agency, prop, req).
    """
    zone = create_zone(zone_code=zone_code, state_event="ACTIVE",
                       wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="EXTREME", sustained_wind_mph=45)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    req = impose_mitigation(prop["id"], requirement_code="DEFENSIBLE_SPACE",
                            band_awarded="PARTIAL", source="UNDERWRITING",
                            due_on="2026-12-01T00:00:00Z")
    return zone, agency, reload_property(prop["id"]), req


def setup_active_zone_underwritable(zone_code="ZACTIVE", agency_code="AGACTIVE"):
    """An ACTIVE zone whose gate leaves the dwelling UNDERWRITABLE.

    The zone is ELEVATED/OUTSIDE_WUI so the gate's EXTREME/WITHIN_WUI
    auto-imposition never fires (PRD §3.5 imposes the DEFENSIBLE_SPACE
    follow-up only when the zone's `exposure_band` is `EXTREME` and its WUI band
    is `WITHIN_WUI` or `ADJACENT_WUI`).  The dwelling is therefore writable with
    an UNVERIFIED band — the precondition for the defense branches, because PRD
    §3.7 tests the EXTENDED branch before the guaranteed one, so `GUARANTEED` is
    only reachable from a property that is not design-cleared.

    Returns (zone, agency, prop).
    """
    zone = create_zone(zone_code=zone_code, state_event="ACTIVE",
                       wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    return zone, agency, reload_property(prop["id"])


def setup_two_property_cascade_book(zone_code="ZCASC", agency_code="AGCASC"):
    """One ACTIVE zone, two underwritable dwellings, both with SUBMITTED enrollments.

    The first dwelling additionally holds a REQUESTED defense dispatch. Returns
    (zone, agency, (p1, e1, d1), (p2, e2)).
    """
    zone = create_zone(zone_code=zone_code, state_event="ACTIVE")
    agency = create_agency(agency_code=agency_code)
    p1 = create_property(zone["id"], agency["id"], address_line="31 Ridge Rd")
    p2 = create_property(zone["id"], agency["id"], address_line="32 Ridge Rd")
    for p in (p1, p2):
        add_approved_appraisal(p["id"])
        run_posture_eval(p["id"])
    e1 = create_enrollment(p1["id"], agency_id=agency["id"])
    e2 = create_enrollment(p2["id"], agency_id=agency["id"])
    submit_enrollment(e1["id"], agency["id"])
    submit_enrollment(e2["id"], agency["id"])
    d1 = request_dispatch(p1["id"])
    return (zone, agency,
            (reload_property(p1["id"]), notify_state(e1), d1),
            (reload_property(p2["id"]), notify_state(e2)))


def setup_two_property_submitted_book(zone_code="ZBOOK", agency_code="AGBOOK",
                                      dwelling_cost_cents=200_000_000,
                                      state_event="ACTIVE"):
    """One zone, two dwellings of equal insured value, both SUBMITTED (no dispatch).

    Returns (zone, agency, prop1, enroll1, prop2, enroll2).
    """
    zone = create_zone(zone_code=zone_code, state_event=state_event)
    agency = create_agency(agency_code=agency_code)
    p1 = create_property(zone["id"], agency["id"], address_line="131 Ember Rd")
    p2 = create_property(zone["id"], agency["id"], address_line="132 Ember Rd")
    for p in (p1, p2):
        add_approved_appraisal(p["id"], dwelling_cost_cents=dwelling_cost_cents)
        run_posture_eval(p["id"])
    e1 = create_enrollment(p1["id"], agency_id=agency["id"])
    e2 = create_enrollment(p2["id"], agency_id=agency["id"])
    submit_enrollment(e1["id"], agency["id"])
    submit_enrollment(e2["id"], agency["id"])
    return (zone, agency, reload_property(p1["id"]), notify_state(e1),
            reload_property(p2["id"]), notify_state(e2))


def setup_frozen_and_unfrozen_siblings(zone_code="ZPAIR", agency_code="AGPAIR"):
    """Same zone: one property whose gate never ran (WRITE_FROZEN) and one underwritable.

    The zone is ELEVATED/OUTSIDE_WUI so the live sibling's posture resolves to
    WRITE_ELIGIBLE: the WUI referral branch is gated on exposure_band ELEVATED,
    not on EXTREME (PRD §2.9).

    Returns (zone, agency, frozen_prop, live_prop, live_enroll).
    """
    zone = create_zone(zone_code=zone_code, wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    dead = create_property(zone["id"], agency["id"], address_line="51 Mesa Rd")
    live = create_property(zone["id"], agency["id"], address_line="52 Mesa Rd")
    add_approved_appraisal(live["id"])
    add_verified_mitigation(live["id"], band_awarded="CLEARED")
    run_posture_eval(live["id"])
    enroll = create_enrollment(live["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=250_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    return zone, agency, reload_property(dead["id"]), reload_property(live["id"]), notify_state(enroll)


def setup_partial_mitigation_submitted(zone_code="ZTIER", agency_code="AGTIER",
                                       band="PARTIAL"):
    """A property with one verified mitigation of `band` and a SUBMITTED enrollment.

    Used to exercise the risk-tier ladder at an exact break point.  The zone is
    ELEVATED/OUTSIDE_WUI so the WUI referral branch does not fire and the
    enrollment can reach approval (PRD §2.9).
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code=zone_code, agency_code=agency_code,
        zone_kwargs={"wildland_urban_interface_band": "OUTSIDE_WUI",
                     "exposure_band": "ELEVATED", "sustained_wind_mph": 35},
        mitigation_band=band, coverage_cents=300_000_000)
    return zone, agency, prop, enroll


def setup_property_with_reviewed_second_appraisal(zone_code="ZREV", agency_code="AGREV",
                                                  second_cost_cents=90_000_000):
    """A property with one approved 200000000 appraisal and a second row in REVIEWED."""
    zone, agency, prop = create_underwritable_setup(
        zone=create_zone(zone_code=zone_code), agency=create_agency(agency_code=agency_code))
    second = create_appraisal(prop["id"], dwelling_cost_cents=second_cost_cents,
                              appraised_on="2026-08-25T00:00:00Z",
                              valuation_confidence_pct=80.0)
    get_success_data(api_client.review_appraisal(second["id"], UW))
    return zone, agency, reload_property(prop["id"]), second


def setup_property_with_late_second_appraisal(zone_code="ZOCC", agency_code="AGOCC"):
    """A property whose version is read, then advanced by a second approval.

    Returns (zone, agency, prop, stale_version, second_appraisal).
    """
    zone, agency, prop = create_underwritable_setup(
        zone=create_zone(zone_code=zone_code), agency=create_agency(agency_code=agency_code))
    stale_version = reload_property(prop["id"])["version"]
    second = add_approved_appraisal(prop["id"], dwelling_cost_cents=50_000_000,
                                    appraised_on="2026-08-25T00:00:00Z",
                                    valuation_confidence_pct=90.0)
    return zone, agency, reload_property(prop["id"]), stale_version, second


def setup_declined_property_pair(well_capitalised_kwargs=None, thin_kwargs=None):
    """Two declined properties on two zones with different branch capitalisation.

    Returns (zone_ok, prop_ok, zone_thin, prop_thin).
    """
    zone_ok = create_zone(zone_code="ZVOK",
                          **(well_capitalised_kwargs or {}))
    zone_thin = create_zone(zone_code="ZVTHIN", mitigation_band_multiplier=1.5,
                            mitigated_loss_multiplier=1.20,
                            **(thin_kwargs or {}))
    agency = create_agency(agency_code="AGREOPEN")
    p_ok = create_property(zone_ok["id"], agency["id"], address_line="10 Corner Rd")
    p_thin = create_property(zone_thin["id"], agency["id"], address_line="11 Corner Rd")
    for p in (p_ok, p_thin):
        add_approved_appraisal(p["id"], dwelling_cost_cents=200_000_000)
        add_approved_appraisal(p["id"], dwelling_cost_cents=100_000_000)
        run_posture_eval(p["id"])
    return zone_ok, reload_property(p_ok["id"]), zone_thin, reload_property(p_thin["id"])


# ─── Cross-entity and RBAC setups ─────────────────────────────────────────────

def setup_reviewed_appraisal_property(zone_code="ZRCON", agency_code="AGRCON"):
    """A property holding one REVIEWED (unapproved) appraisal. Returns (zone, agency, prop, appr)."""
    zone = create_zone(zone_code=zone_code)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    appr = create_appraisal(prop["id"])
    get_success_data(api_client.review_appraisal(appr["id"], UW))
    return zone, agency, reload_property(prop["id"]), appr


def setup_draft_enrollment_on_write_eligible(zone_code="ZDRAFT", agency_code="AGDRAFT",
                                             coverage_cents=300_000_000):
    """A WRITE_ELIGIBLE property plus a DRAFT enrollment. Returns (zone, agency, prop, enroll)."""
    zone = create_zone(zone_code=zone_code, wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=coverage_cents)
    return zone, agency, prop, enroll


def setup_inactive_agency_draft(zone_code="ZINACT", agency_code="AGINACT"):
    """An agency deactivated after one DRAFT enrollment was opened.

    Returns (zone, agency, prop, enroll). The agency is already inactive.
    """
    zone = create_zone(zone_code=zone_code, wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    get_success_data(api_client.set_agency_active(agency["id"], False, OPS))
    return zone, agency, prop, enroll


def setup_enrollment_with_extra_scheduled_item(zone_code="ZFING", agency_code="AGFING"):
    """An APPROVED enrollment whose valuation fingerprint is invalidated by a later item.

    Returns (zone, agency, prop, enrollment, item). The extra 50000000 item is
    approved after the enrollment approval, so the fingerprint no longer matches.
    """
    zone = create_zone(zone_code=zone_code, wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    run_posture_eval(prop["id"])
    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    approved = approve_enrollment(enroll["id"])
    item = add_approved_scheduled_item(prop["id"], item_type="FINE_ART",
                                       declared_value_cents=50_000_000,
                                       appraised_value_cents=60_000_000)
    return zone, agency, reload_property(prop["id"]), approved, item


def setup_approved_enrollment_with_cleared_mitigation(zone_code="ZENDOR", agency_code="AGENDOR",
                                                      coverage_cents=300_000_000,
                                                      due_on="2026-12-01T00:00:00Z"):
    """An APPROVED, EXTENDED-provision enrollment with a long-lived mitigation.

    The zone is ELEVATED/OUTSIDE_WUI so a cleared property is WRITE_ELIGIBLE:
    the CLEARED requirement is imposed and verified before the gate runs, which
    is what lets approval snapshot the EXTENDED provision (PRD §3.7: a verified
    CLEARED mitigation confers the design-cleared branch).

    The zone's concentration is NOT recomputed here — PRD §3.7's recall requires
    the agency's own band to be CRITICAL, which only holds once the caller has
    built a book that re-derives it.  Callers that need recall run the
    concentration check themselves.

    Returns (zone, agency, prop, enrollment).
    """
    zone = create_zone(zone_code=zone_code, wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    add_verified_mitigation(prop["id"], band_awarded="CLEARED", due_on=due_on)
    run_posture_eval(prop["id"])
    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=coverage_cents)
    submit_enrollment(enroll["id"], agency["id"])
    approved = approve_enrollment(enroll["id"])
    return zone, agency, prop, approved


def prime_agency_critical(zone, prop, agency, coverage_cents=300_000_000):
    """Run the concentration sweep so the agency's own band re-derives CRITICAL.

    PRD §2.10 measures the two scopes against different denominators.  The
    agency scope narrows the numerator to the zone-and-agency intersection, so a
    sibling of the same agency inside the same zone lifts that agency's share of
    the zone to 100 percent.  The zone scope divides by the whole portfolio, so a
    third dwelling placed in a second zone dilutes this zone's share below the
    30.0 CRITICAL break point — which keeps both scopes reachable at once: the
    agency is CRITICAL while its zone stays short of a portfolio freeze.

    A property whose gate has never run has a total insured value of zero
    (PRD §3.5) and contributes nothing to either scope, so every sibling is
    appraised and gated.  Both secondary zones are placed outside the WUI with an
    ELEVATED band so the gate leaves their dwellings writable (PRD §2.9).

    Returns the zone as read back from the sweep; the agency's band is the
    caller's to consume (PRD §3.7's recall).
    """
    subject_exposure = reload_property(prop["id"])["total_insured_value_cents"]
    sibling = create_property(zone["id"], agency["id"], address_line="9 Prime Rd")
    add_approved_appraisal(sibling["id"], dwelling_cost_cents=subject_exposure)
    run_posture_eval(sibling["id"])
    sibling_enroll = create_enrollment(sibling["id"], agency_id=agency["id"],
                                       dwelling_coverage_cents=coverage_cents)
    submit_enrollment(sibling_enroll["id"], agency["id"])

    # The diluting dwelling lives in its own zone under its own agency, and is
    # sized several times the subject's exposure so this zone's share of the
    # portfolio drops below 30.0.
    other_zone = create_zone(zone_code="%sDIL" % zone["zone_code"],
                             wildland_urban_interface_band="OUTSIDE_WUI",
                             exposure_band="ELEVATED", sustained_wind_mph=35)
    other_agency = create_agency(agency_code="%sDIL" % agency["agency_code"])
    filler = create_property(other_zone["id"], other_agency["id"],
                             address_line="10 Prime Rd")
    add_approved_appraisal(filler["id"],
                           dwelling_cost_cents=6 * subject_exposure)
    run_posture_eval(filler["id"])
    filler_enroll = create_enrollment(filler["id"], agency_id=other_agency["id"],
                                      dwelling_coverage_cents=6 * coverage_cents)
    submit_enrollment(filler_enroll["id"], other_agency["id"])

    return get_success_data(api_client.check_concentration(zone["id"], UW))


def recallable_approved_enrollment(zone_code="ZRECALL", agency_code="AGRECALL",
                                    coverage_cents=300_000_000):
    """An APPROVED enrollment whose agency band can be driven to CRITICAL.

    The zone is ELEVATED/OUTSIDE_WUI so the cleared property is WRITE_ELIGIBLE;
    the recall precondition itself is satisfied by the caller running
    `prime_agency_critical` (PRD §3.7).

    Returns (zone, agency, prop, enrollment).
    """
    return setup_approved_enrollment_with_cleared_mitigation(
        zone_code=zone_code, agency_code=agency_code, coverage_cents=coverage_cents)


def setup_three_draft_enrollments_two_zones(zone1_code="ZLIST1", zone2_code="ZLIST2",
                                            agency_code="AGLIST"):
    """Three DRAFT enrollments: two on zone 1, one on zone 2.

    Returns (zone1, zone2, agency, enrollments).
    """
    zone1 = create_zone(zone_code=zone1_code)
    zone2 = create_zone(zone_code=zone2_code, wildland_urban_interface_band="ADJACENT_WUI",
                        exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code=agency_code)
    p1 = create_property(zone1["id"], agency["id"], address_line="2 Corner Rd")
    p2 = create_property(zone1["id"], agency["id"], address_line="3 Corner Rd")
    p3 = create_property(zone2["id"], agency["id"], address_line="4 Orchard Rd")
    enrolls = [create_enrollment(p["id"], agency_id=agency["id"],
                                 dwelling_coverage_cents=150_000_000)
               for p in (p1, p2, p3)]
    return zone1, zone2, agency, enrolls


def setup_three_properties_two_appraised(zone_code="ZPAGE", agency_code="AGPAGE"):
    """Three properties on one zone; two appraised and gated, one left pending.

    Returns (zone, agency, props).
    """
    zone = create_zone(zone_code=zone_code)
    agency = create_agency(agency_code=agency_code)
    props = [create_property(zone["id"], agency["id"],
                             address_line=f"{7 + i} Corner Rd",
                             grid_risk_block="CORN-C")
             for i in range(3)]
    for p in props[:2]:
        add_approved_appraisal(p["id"])
        run_posture_eval(p["id"])
    return zone, agency, [reload_property(p["id"]) for p in props]


# Alias kept for readability at call sites that treat the helper as a composite setup.
setup_underwritable_property = create_underwritable_property
