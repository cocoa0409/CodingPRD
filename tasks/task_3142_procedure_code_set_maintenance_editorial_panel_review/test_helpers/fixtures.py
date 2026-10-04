"""Composite setup helpers — build the multi-step preconditions each claim needs.

Every helper builds its state from scratch through PRD-declared endpoints, because
the harness restarts the server (and therefore empties the database) before every
test. Helpers use the lenient success validator so a broken setup produces a clear
"Setup failed" error rather than a confusing assertion failure downstream.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .test_users import (
    TEST_USERS,
    SECOND_EDITORIAL_STAFF_HEADERS,
    make_licensee_headers,
    make_change_applicant_headers,
    make_committee_reviewer_headers,
)

STAFF = TEST_USERS["editorial_staff_headers"]
CHAIR = TEST_USERS["editorial_panel_chair_headers"]
LICENSING = TEST_USERS["licensing_officer_headers"]
REVIEWER = TEST_USERS["committee_reviewer_headers"]

COMMENT_OPEN = "2026-09-01T00:00:00Z"
COMMENT_CLOSE_30D = "2026-10-01T00:00:00Z"
ERRATA_DEADLINE = "2027-06-30T00:00:00Z"
FACILITY_EFFECTIVE = "2027-01-01T00:00:00Z"

# The GPCI triple used by the dollar-split claim family.
GPCI_WORK, GPCI_PE, GPCI_MP = 1.0521, 1.1234, 0.6980
CONVERSION_FACTOR = 34.63


def _data(response):
    """Lenient success extraction for setup calls."""
    return get_success_data(response)


def _items(response):
    data = get_success_data(response)
    return data if isinstance(data, list) else []


def _page(response):
    return validate_paginated(response)


# --------------------------------------------------------------------------
# Primitive steps
# --------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK, headers=None):
    """Set the server's logical clock. The clock never reads wall-clock time."""
    headers = headers or STAFF
    return _data(api_client.set_clock(to_iso8601, headers))


def create_society(name="Alpha Society", code="ALP", seats=1,
                   gpci_work=1.0000, gpci_pe=1.0000, gpci_mp=1.0000, headers=None):
    headers = headers or STAFF
    payload = {
        "name": name,
        "specialty_code": code,
        "voting_seat_count": seats,
        "gpci_work": gpci_work,
        "gpci_pe": gpci_pe,
        "gpci_mp": gpci_mp,
    }
    return _data(api_client.create_specialty_society(payload, headers))


def create_national_society(name="National Society", code="NAT", seats=1):
    return create_society(name=name, code=code, seats=seats)


def create_applicant(name="Alpha Applicant", applicant_type="SPECIALTY_SOCIETY",
                     society_id=None, is_entity_member=True, dues_paid_current=True,
                     contact_email="alpha@example.org", headers=None):
    headers = headers or STAFF
    payload = {
        "name": name,
        "applicant_type": applicant_type,
        "is_entity_member": is_entity_member,
        "dues_paid_current": dues_paid_current,
        "contact_email": contact_email,
    }
    if society_id is not None:
        payload["society_id"] = society_id
    return _data(api_client.create_applicant(payload, headers))


def create_meeting(meeting_code="FEB2027", meeting_month="FEBRUARY",
                   starts_at="2027-02-08T14:00:00Z", ends_at="2027-02-08T23:00:00Z",
                   citation_mode=False, headers=None):
    headers = headers or STAFF
    payload = {
        "meeting_code": meeting_code,
        "meeting_month": meeting_month,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "citation_mode": citation_mode,
    }
    return _data(api_client.create_meeting(payload, headers))


def create_cycle(meeting_ids, year=2027, capacity=300,
                 comment_open=COMMENT_OPEN, comment_close=COMMENT_CLOSE_30D,
                 addendum_comment_close=None, errata_deadline=None,
                 single_floor_budgeting=False, headers=None):
    headers = headers or STAFF
    addendum_comment_close = addendum_comment_close or f"{year}-11-15T00:00:00Z"
    errata_deadline = errata_deadline or ERRATA_DEADLINE
    payload = {
        "year": year,
        "comment_open": comment_open,
        "comment_close": comment_close,
        "addendum_comment_close": addendum_comment_close,
        "meeting_ids": list(meeting_ids),
        "code_set_capacity": capacity,
        "errata_deadline": errata_deadline,
        "single_floor_budgeting": single_floor_budgeting,
    }
    return _data(api_client.create_release_cycle(payload, headers))


def create_change(code, applicant_id, society_id=None, change_type="ADDITION",
                  category="CATEGORY_I", code_family=None, tier="TIER_II",
                  evidence_index=70, volume=700, organ_systems=None,
                  descriptor_current="Placeholder descriptor",
                  descriptor_proposed=None, guidelines="None",
                  parenthetical_instructions="None", headers=None):
    headers = headers or STAFF
    payload = {
        "code": code,
        "change_type": change_type,
        "category": category,
        "code_family": code_family if code_family is not None else code[:3],
        "applicant_id": applicant_id,
        "clinical_evidence_tier": tier,
        "evidence_sufficiency_index": evidence_index,
        "procedure_volume_threshold": volume,
        "descriptor_current": descriptor_current,
    }
    if society_id is not None:
        payload["society_id"] = society_id
    if organ_systems is not None:
        payload["organ_system_count"] = organ_systems
    if descriptor_proposed is not None:
        payload["descriptor_proposed"] = descriptor_proposed
    if guidelines is not None:
        payload["guidelines"] = guidelines
    if parenthetical_instructions is not None:
        payload["parenthetical_instructions"] = parenthetical_instructions
    return _data(api_client.create_code_change(payload, headers))


def submit_into_cycle(cycle_id, change_ids, expected_change_version, headers=None):
    headers = headers or STAFF
    payload = {
        "change_ids": list(change_ids),
        "expected_change_version": expected_change_version,
    }
    return _data(api_client.submit_release_cycle_changes(cycle_id, payload, headers))


def post_change(change_id, open_at=COMMENT_OPEN, close_at=COMMENT_CLOSE_30D, headers=None):
    """Post a change for public comment, stamping its comment window."""
    headers = headers or STAFF
    payload = {"comment_period_open_at": open_at, "comment_period_close_at": close_at}
    return _data(api_client.post_code_change(change_id, payload, headers))


def docket(meeting_id, change_ids, headers=None):
    """Set the meeting agenda, moving each named change to AGENDA_SET."""
    headers = headers or STAFF
    return _data(api_client.set_meeting_agenda(meeting_id, {"change_ids": list(change_ids)}, headers))


def open_meeting(meeting_id, headers=None):
    headers = headers or CHAIR
    return _data(api_client.open_meeting(meeting_id, headers))


def cast_vote(change_id, meeting_id, society_id, vote, headers=None):
    headers = headers or CHAIR
    payload = {
        "change_id": change_id,
        "meeting_id": meeting_id,
        "society_id": society_id,
        "vote": vote,
    }
    return _data(api_client.create_editorial_vote(payload, headers))


# --------------------------------------------------------------------------
# Tier 1: state progression
# --------------------------------------------------------------------------

def create_meeting_in_state(target_state, meeting_code="FEB2027", meeting_month="FEBRUARY",
                            starts_at="2027-02-08T14:00:00Z", ends_at="2027-02-08T23:00:00Z",
                            citation_mode=False, docket_change_ids=None):
    """Walk EditorialPanelMeeting.meeting_status to the requested state.

    Supported targets: SCHEDULED (no calls), PUBLIC_COMMENT_OPEN, OPEN.
    """
    meeting = create_meeting(meeting_code, meeting_month, starts_at, ends_at, citation_mode)
    state = meeting["meeting_status"]
    if target_state == state:
        return meeting
    if target_state == "PUBLIC_COMMENT_OPEN":
        return _data(api_client.open_meeting_comment_window(
            meeting["id"],
            {"public_comment_open_at": COMMENT_OPEN, "public_comment_close_at": COMMENT_CLOSE_30D},
            STAFF,
        ))
    if target_state == "OPEN":
        if docket_change_ids:
            meeting = docket(meeting["id"], docket_change_ids)
        else:
            meeting = _data(api_client.set_meeting_agenda(
                meeting["id"], {"change_ids": []}, STAFF))
        return _data(api_client.open_meeting(meeting["id"], CHAIR))
    raise ValueError(f"unsupported target_state {target_state!r}")


def create_licence_and_territory(territory_code="US-TEST", method="SITE",
                                 licensee_type="PROVIDER", licensee_name="Test Clinic",
                                 sales_unit_count=10, expected_users=20,
                                 vendtor_worldwide=False, base_fee_cents=0,
                                 payer_revenue_tier=None, activate=False):
    """Create a territory and a licence bound to it. Returns (licence, territory)."""
    territory = _data(api_client.create_distribution_territory(
        {
            "territory_code": territory_code,
            "method": method,
            "edi_payer_network": False,
            "metadata_schema_version": "2026.1",
        },
        LICENSING,
    ))
    payload = {
        "licensee_type": licensee_type,
        "licensee_name": licensee_name,
        "vendor_worldwide": vendtor_worldwide,
        "expected_users": expected_users,
        "sales_unit_count": sales_unit_count,
        "base_fee_cents": base_fee_cents,
        "territory_id": territory["id"],
    }
    if payer_revenue_tier is not None:
        payload["payer_revenue_tier"] = payer_revenue_tier
    licence = _data(api_client.create_licensing_agreement(payload, LICENSING))
    if activate:
        licence = _data(api_client.activate_licensing_agreement(licence["id"], LICENSING))
    return licence, territory


def create_code_value(code="00002", society_id=None, work_rvu=2.80,
                      facility_pe_rvu=1.90, nonfacility_pe_rvu=1.90, mp_rvu=0.24,
                      conversion_factor=CONVERSION_FACTOR,
                      rounding_variant="AGGREGATE_ROUNDING",
                      effective_date=FACILITY_EFFECTIVE):
    """Create a code value and, when an effective date is supplied, restamp it."""
    payload = {
        "code": code,
        "work_rvu": work_rvu,
        "facility_pe_rvu": facility_pe_rvu,
        "nonfacility_pe_rvu": nonfacility_pe_rvu,
        "mp_rvu": mp_rvu,
        "conversion_factor": conversion_factor,
        "rounding_variant": rounding_variant,
    }
    if society_id is not None:
        payload["specialty_id"] = society_id
    value = _data(api_client.create_code_value(payload, LICENSING))
    if effective_date:
        value = _data(api_client.restamp_code_value_effective_date(
            value["id"], {"effective_date": effective_date}, LICENSING))
    return value


def create_errata_notice(code_value_id, errata_effective_date="2027-05-03T00:00:00Z",
                         prior_cents=18173, reason="Practice-expense RVU overstated"):
    payload = {
        "code_value_id": code_value_id,
        "errata_effective_date": errata_effective_date,
        "prior_facility_payment_cents": prior_cents,
        "reason": reason,
    }
    return _data(api_client.create_errata_notice(payload, STAFF))


# --------------------------------------------------------------------------
# Tier 2/3: entity hierarchy and lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_society_applicant(society_name="Alpha Society", society_code="ALP", seats=1,
                            applicant_type="SPECIALTY_SOCIETY", applicant_name="Alpha Applicant"):
    """One society plus one applicant filed on its behalf."""
    society = create_society(society_name, society_code, seats)
    applicant = create_applicant(applicant_name, applicant_type, society_id=society["id"])
    return society, applicant


def setup_meeting_and_cycle(meeting_code="FEB2027", meeting_month="FEBRUARY",
                            starts_at="2027-02-08T14:00:00Z", ends_at="2027-02-08T23:00:00Z",
                            citation_mode=False, year=2027, capacity=300,
                            comment_open=COMMENT_OPEN, comment_close=COMMENT_CLOSE_30D,
                            addendum_comment_close=None, errata_deadline=None,
                            single_floor_budgeting=False):
    """One scheduled meeting plus one release cycle naming it. Returns (meeting, cycle)."""
    meeting = create_meeting(meeting_code, meeting_month, starts_at, ends_at, citation_mode)
    cycle = create_cycle(
        [meeting["id"]], year=year, capacity=capacity, comment_open=comment_open,
        comment_close=comment_close, addendum_comment_close=addendum_comment_close,
        errata_deadline=errata_deadline, single_floor_budgeting=single_floor_budgeting,
    )
    return meeting, cycle


def setup_panel_ready_change(change_code="00001", filler_codes=("00011", "00012"),
                             society_name="Alpha Society", society_code="ALP",
                             tier="TIER_I", volume=8000, organ_systems=1,
                             change_type="ADDITION", meeting_code="FEB2027",
                             meeting_month="FEBRUARY", citation_mode=False,
                             capacity=300, year=2027, post=True):
    """Walk a sponsored change through submission, posting, docketing and meeting opening.

    Returns a dict with society, applicant, meeting, cycle, change, fillers and the
    versions observed along the way. Two filler changes are docketed alongside so the
    meeting reaches its three-docket quorum.
    """
    set_clock(DEFAULT_CLOCK)
    society = create_society(society_name, society_code, seats=1)
    applicant = create_applicant(society_id=society["id"])
    meeting = create_meeting(meeting_code, meeting_month,
                             f"{year}-02-08T14:00:00Z", f"{year}-02-08T23:00:00Z",
                             citation_mode)
    cycle = create_cycle([meeting["id"]], year=year, capacity=capacity)

    change = create_change(
        change_code, applicant["id"], society_id=society["id"], change_type=change_type,
        tier=tier, volume=volume, organ_systems=organ_systems,
        descriptor_proposed="Placeholder descriptor revised",
    )
    version_at_creation = change["version"]
    fillers = []
    for code in filler_codes:
        fillers.append(create_change(code, applicant["id"], society_id=society["id"]))

    if change_type != "REVISION":
        submit_into_cycle(cycle["id"], [change["id"]], version_at_creation)
    else:
        submit_into_cycle(cycle["id"], [change["id"]], version_at_creation)

    if post:
        change = post_change(change["id"])
    version_after_post = change["version"]

    docket(meeting["id"], [change["id"]] + [f["id"] for f in fillers])
    open_meeting(meeting["id"])

    return {
        "society": society,
        "applicant": applicant,
        "meeting": meeting,
        "cycle": cycle,
        "change": change,
        "fillers": fillers,
        "version_at_creation": version_at_creation,
        "version_after_post": version_after_post,
    }


def setup_submitted_change_in_cycle(change_code="00069", society_name="Window Society",
                                    society_code="WIN", meeting_code="JUN2026",
                                    meeting_month="JUNE", year=2028, capacity=400,
                                    meeting_starts="2026-06-08T14:00:00Z",
                                    meeting_ends="2026-06-08T23:00:00Z",
                                    tier="TIER_II", volume=700, sponsored=False,
                                    submit=True, docket_change=False):
    """One change belonging to an open release cycle, still in DRAFT.

    With ``docket_change`` the change is also placed on the meeting's agenda
    (review_status AGENDA_SET, meeting_id pointed at the meeting) while the
    meeting is still SCHEDULED, which is the state PRD SS3.4 requires of the
    naming meeting before a docketed change may be returned to DRAFT.

    With ``submit`` false the change is left unenrolled (cycle_id null), which is
    the precondition a refused-submission probe needs.
    """
    set_clock(DEFAULT_CLOCK)
    society = None
    if sponsored:
        society = create_society(society_name, society_code, seats=1)
    applicant = create_applicant(society_id=society["id"] if society else None)
    meeting = create_meeting(meeting_code, meeting_month, meeting_starts, meeting_ends)
    cycle = create_cycle([meeting["id"]], year=year, capacity=capacity,
                         addendum_comment_close=f"{year}-11-15T00:00:00Z",
                         errata_deadline=f"{year}-06-30T00:00:00Z")
    cycle = _data(api_client.open_release_cycle(cycle["id"], STAFF))
    change = create_change(change_code, applicant["id"],
                           society_id=society["id"] if society else None,
                           tier=tier, volume=volume)
    version = change["version"]
    if sponsored and submit:
        submit_into_cycle(cycle["id"], [change["id"]], version)
    if docket_change:
        docket(meeting["id"], [change["id"]])
    return {"society": society, "applicant": applicant, "meeting": meeting,
            "cycle": cycle, "change": change, "version_at_creation": version}


def setup_three_docketed_changes(meeting_code="FEB2030", meeting_month="FEBRUARY",
                                 starts_at="2030-02-11T14:00:00Z",
                                 ends_at="2030-02-11T23:00:00Z",
                                 citation_mode=False, codes=("00091", "00092", "00093"),
                                 first_society_seats=1, second_society_seats=None):
    """One meeting plus three changes docketed on its agenda.

    Returns a dict with meeting, applicant, societies, changes and the agenda response.
    """
    set_clock(DEFAULT_CLOCK)
    applicant = create_applicant()
    societies = [create_society("First Society", "FS1", seats=first_society_seats)]
    if second_society_seats is not None:
        societies.append(create_society("Second Society", "FS2", seats=second_society_seats))
    meeting = create_meeting(meeting_code, meeting_month, starts_at, ends_at, citation_mode)
    changes = [create_change(code, applicant["id"]) for code in codes]
    agenda = docket(meeting["id"], [c["id"] for c in changes])
    return {"meeting": meeting, "applicant": applicant, "societies": societies,
            "changes": changes, "agenda": agenda}


# --------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# --------------------------------------------------------------------------

def setup_gpci_society(code="BET", name="Beta Society"):
    """A society carrying the regional GPCI triple used by the dollar-split family."""
    set_clock(DEFAULT_CLOCK)
    return create_society(name=name, code=code, seats=1,
                          gpci_work=GPCI_WORK, gpci_pe=GPCI_PE, gpci_mp=GPCI_MP)


def setup_gpci_code_value(code="00002", rounding_variant="AGGREGATE_ROUNDING",
                          society_code="BET", work_rvu=2.80, facility_pe_rvu=1.90,
                          nonfacility_pe_rvu=1.90, mp_rvu=0.24,
                          conversion_factor=CONVERSION_FACTOR,
                          effective_date=FACILITY_EFFECTIVE):
    """One code value priced from the regional GPCI triple.

    The inputs are chosen so the aggregate and component rounding orders diverge by
    one cent, which is the divergence the dollar-split claims assert.
    """
    society = setup_gpci_society(society_code)
    value = create_code_value(code=code, society_id=society["id"], work_rvu=work_rvu,
                              facility_pe_rvu=facility_pe_rvu,
                              nonfacility_pe_rvu=nonfacility_pe_rvu, mp_rvu=mp_rvu,
                              conversion_factor=conversion_factor,
                              rounding_variant=rounding_variant,
                              effective_date=None)
    if effective_date:
        value = _data(api_client.restamp_code_value_effective_date(
            value["id"], {"effective_date": effective_date}, LICENSING))
    return {"society": society, "value": value}


def setup_release_cycle_only(capacity=192, year=2027, single_floor_budgeting=False,
                             meeting_code="APR2027", meeting_month="APRIL",
                             starts_at="2027-04-12T14:00:00Z",
                             ends_at="2027-04-12T23:00:00Z",
                             comment_open="2026-01-01T00:00:00Z",
                             comment_close="2026-02-01T00:00:00Z",
                             open_cycle=False):
    """A meeting and a release cycle of the given capacity, nothing else.

    With ``open_cycle`` the cycle is advanced from PLANNING to OPEN through the
    PRD SS3.6 opening operation.  The cycle return path that recomputes the
    descriptor pools requires an OPEN cycle, and - unlike submission, which is
    gated only on the logical clock being at or before ``comment_close`` - the
    opening carries no clock precondition.
    """
    set_clock(DEFAULT_CLOCK)
    meeting = create_meeting(meeting_code, meeting_month, starts_at, ends_at)
    cycle = create_cycle([meeting["id"]], year=year, capacity=capacity,
                         comment_open=comment_open, comment_close=comment_close,
                         single_floor_budgeting=single_floor_budgeting)
    if open_cycle:
        cycle = _data(api_client.open_release_cycle(cycle["id"], STAFF))
    return {"meeting": meeting, "cycle": cycle}


# --------------------------------------------------------------------------
# Tier 5: licensing / delivery lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_active_licence(territory_code="US-TEST", method="SITE",
                         licensee_type="PROVIDER", licensee_name="Test Clinic",
                         sales_unit_count=10, expected_users=20,
                         vendor_worldwide=False, base_fee_cents=0,
                         payer_revenue_tier=None, activate=True):
    """A territory plus a licence bound to it, activated by default."""
    set_clock(DEFAULT_CLOCK)
    licence, territory = create_licence_and_territory(
        territory_code=territory_code, method=method, licensee_type=licensee_type,
        licensee_name=licensee_name, sales_unit_count=sales_unit_count,
        expected_users=expected_users, vendtor_worldwide=vendor_worldwide,
        base_fee_cents=base_fee_cents, payer_revenue_tier=payer_revenue_tier,
        activate=activate,
    )
    return {"licence": licence, "territory": territory}


def setup_reserved_delivery(territory_code="US-TEST", sales_unit_count=8):
    """An active licence holding one RESERVED delivery order.

    Returns the licence (refreshed after the reservation advanced its version), the
    territory, the delivery order and the observed versions.
    """
    bundle = setup_active_licence(territory_code=territory_code,
                                  sales_unit_count=sales_unit_count)
    licence = bundle["licence"]
    version_before = licence["version"]
    headers = make_licensee_headers(licence["id"])
    order = _data(api_client.create_content_delivery_order(
        {
            "license_id": licence["id"],
            "distribution_channel": "SITE",
            "format_params": {"electronic_format": "NONE", "media": "NONE",
                              "version_qualifier": "2026.1",
                              "payer_identifier_qualifier": "NONE"},
            "payer_identifier": "PLACEHOLDER",
            "expected_license_version": version_before,
        },
        headers,
    ))
    refreshed = _data(api_client.get_licensing_agreement(licence["id"], LICENSING))
    return {
        "licence": refreshed,
        "territory": bundle["territory"],
        "order": order,
        "version_before_reservation": version_before,
        "version_after_reservation": refreshed["version"],
        "licensee_headers": headers,
    }


def setup_ready_delivery(territory_code="US-MOUNTAIN", sales_unit_count=20):
    """An active licence holding one delivery order already marked READY."""
    bundle = setup_reserved_delivery(territory_code=territory_code,
                                     sales_unit_count=sales_unit_count)
    order = _data(api_client.mark_delivery_ready(
        bundle["order"]["id"], {"media": "NONE"}, STAFF))
    bundle["order"] = order
    return bundle


def setup_errata_target(code="00030", facility_pe_rvu=1.80, mp_rvu=0.36,
                        prior_cents=18173, errata_effective_date="2027-05-03T00:00:00Z"):
    """A code value with an errata notice proposed against it."""
    bundle = setup_gpci_code_value(code=code, facility_pe_rvu=facility_pe_rvu,
                                   mp_rvu=mp_rvu, society_code="LAM")
    notice = create_errata_notice(bundle["value"]["id"],
                                  errata_effective_date=errata_effective_date,
                                  prior_cents=prior_cents)
    bundle["notice"] = notice
    return bundle