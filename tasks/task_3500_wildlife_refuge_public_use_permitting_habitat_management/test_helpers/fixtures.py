"""Composite setup helpers.

Encapsulates the multi-step preambles the PRD's workflows demand: driving a
determination to FINAL through its comment window, walking a permit through
the revision loop to ACTIVE, awarding a grazing agreement through the bid
selector, debiting an agreement into SUSPENDED, and the closure-cascade
scenario. Every fixture builds from scratch against a fresh server (the
runner restarts it per test) using only PRD-declared endpoints, and threads
ownership identities (applicant_ref / cooperator_ref / volunteer id) into
the caller headers on every anchored call.

CLOCK DISCIPLINE: the logical clock starts at 2026-09-01T00:00:00Z and only
moves forward. create_final_determination leaves the clock at the day after
comment_close_date (default 2026-09-21). Compose fixtures in nondecreasing
clock order, or pass later window dates to the determination fixtures.
"""
from uuid import uuid4

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DETERMINATION_COMMENT_OPEN_DATE, DETERMINATION_COMMENT_CLOSE_DATE,
    PERMIT_START_DATE, PERMIT_END_DATE, CLOSURE_START_DATE, CLOSURE_END_DATE,
    PROGRAM_DATE, TREATMENT_WINDOW_START, TREATMENT_WINDOW_END,
    add_days, clock_iso,
)
from .factories import (
    create_management_unit_payload, create_determination_payload,
    create_finalize_payload, create_comment_payload, create_adjudicate_payload,
    create_permit_payload, create_return_for_revision_payload,
    create_revoke_payload, create_treatment_payload, create_closure_payload,
    create_program_payload, create_volunteer_payload, create_assignment_payload,
    create_grazing_offering_payload, create_bid_payload, create_assess_payload,
    create_ledger_entry_payload, create_citation_payload,
    create_population_objective_payload, create_survey_payload,
    create_clock_payload,
)
from .test_users import (
    TEST_USERS, make_permit_applicant_headers, make_cooperator_headers,
)

__all__ = [
    # clock
    "advance_clock",
    # units
    "create_unit", "get_unit_posture",
    # determinations and comments
    "create_determination", "get_determination", "open_comment_window",
    "create_determination_in_public_comment", "create_determination_in_adjudication",
    "create_final_determination", "submit_comment", "adjudicate_comment",
    "setup_determination_with_comment", "setup_adjudication_with_comment",
    # permits
    "create_submitted_permit", "create_under_review_permit",
    "create_approved_permit", "create_active_permit", "get_permit",
    "revoke_permit",
    # treatments
    "create_treatment", "get_treatment", "start_and_complete_treatment",
    "create_completed_treatment",
    # closures
    "create_closure", "activate_closure", "lift_closure", "create_active_closure",
    "setup_closure_cascade_scenario",
    # programs, volunteers, assignments
    "create_volunteer", "clear_volunteer", "create_cleared_volunteer",
    "create_program", "get_program", "create_assignment", "get_assignment",
    "setup_program_with_volunteers",
    # grazing
    "create_grazing_offering", "place_bid", "close_and_select",
    "setup_grazing_offering", "find_agreement_by_winning_bid",
    "setup_awarded_agreement",
    # agreements
    "get_agreement", "refresh_agreement", "assess_period",
    "setup_assessed_agreement", "post_payment", "post_refund",
    "complete_agreement", "issue_agreement_citation", "issue_permit_citation",
    "void_citation", "setup_suspended_agreement",
    # population
    "create_population_objective", "record_survey",
]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (RefugeManager only). Returns {"current_utc"}.

    Fires the five pinned auto-transition classes in order: determinations,
    treatments, volunteers (with cascades), programs, permits.
    """
    resp = api_client.set_clock(
        create_clock_payload(to_iso8601), TEST_USERS["refuge_manager_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Management units
# ---------------------------------------------------------------------------
def create_unit(name="North Marsh", habitat_type="WETLAND", acreage=1200,
                headers=None) -> dict:
    """Create a management unit (RefugeManager). Computed fields start at
    posture OPEN, committed_visitor_days 0, habitat scores 0."""
    payload = create_management_unit_payload(
        name=name, habitat_type=habitat_type, acreage=acreage)
    resp = api_client.create_management_unit(
        payload, headers or TEST_USERS["refuge_manager_headers"])
    return get_success_data(resp, 201)


def get_unit_posture(unit_id: str, headers=None) -> dict:
    """Computed read: posture, committed visitor days, habitat scores,
    active closure count."""
    resp = api_client.get_unit_posture(unit_id, headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Compatibility determinations and public comments
# ---------------------------------------------------------------------------
def create_determination(use_type="RESEARCH", title=None,
                         comment_open_date=DETERMINATION_COMMENT_OPEN_DATE,
                         comment_close_date=DETERMINATION_COMMENT_CLOSE_DATE,
                         headers=None) -> dict:
    """Create a DRAFT determination (PermitOfficer). comment_open_date must be
    >= the current clock date."""
    payload = create_determination_payload(
        use_type=use_type, title=title or f"{use_type} compatibility",
        comment_open_date=comment_open_date, comment_close_date=comment_close_date)
    resp = api_client.create_determination(
        payload, headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp, 201)


def get_determination(determination_id: str, headers=None) -> dict:
    resp = api_client.get_determination(
        determination_id, headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


def open_comment_window(determination: dict, headers=None) -> dict:
    """Advance the clock to the determination's comment_open_date and open the
    window (DRAFT -> PUBLIC_COMMENT)."""
    advance_clock(clock_iso(determination["comment_open_date"]))
    resp = api_client.open_determination_comment(
        determination["id"], headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


def create_determination_in_public_comment(
        use_type="RESEARCH", comment_open_date=DETERMINATION_COMMENT_OPEN_DATE,
        comment_close_date=DETERMINATION_COMMENT_CLOSE_DATE, headers=None) -> dict:
    """Determination driven to PUBLIC_COMMENT; clock left at comment_open_date."""
    det = create_determination(
        use_type=use_type, comment_open_date=comment_open_date,
        comment_close_date=comment_close_date, headers=headers)
    return open_comment_window(det, headers=headers)


def create_determination_in_adjudication(
        use_type="RESEARCH", comment_open_date=DETERMINATION_COMMENT_OPEN_DATE,
        comment_close_date=DETERMINATION_COMMENT_CLOSE_DATE, headers=None) -> dict:
    """Determination driven to ADJUDICATION; clock left one day past
    comment_close_date (intake closed by the clock, not by an officer)."""
    det = create_determination_in_public_comment(
        use_type=use_type, comment_open_date=comment_open_date,
        comment_close_date=comment_close_date, headers=headers)
    advance_clock(clock_iso(add_days(det["comment_close_date"], 1)))
    return get_determination(det["id"], headers=headers)


def create_final_determination(use_type="RESEARCH", finding="COMPATIBLE",
                               rationale="No material interference with refuge purposes.",
                               comment_open_date=DETERMINATION_COMMENT_OPEN_DATE,
                               comment_close_date=DETERMINATION_COMMENT_CLOSE_DATE,
                               headers=None) -> dict:
    """Full determination lifecycle to FINAL with the given finding. Leaves the
    clock one day past comment_close_date (default 2026-09-21). Requires zero
    unresolved comments, so call before submitting any."""
    det = create_determination_in_adjudication(
        use_type=use_type, comment_open_date=comment_open_date,
        comment_close_date=comment_close_date, headers=headers)
    payload = create_finalize_payload(finding=finding, rationale=rationale)
    resp = api_client.finalize_determination(
        det["id"], payload, headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


def submit_comment(determination_id: str, author_name="Citizen A",
                   body="Comment on the proposed use.") -> dict:
    """Anonymous public comment; determination must be in PUBLIC_COMMENT.
    Increments the determination's unresolved_comment_count."""
    payload = create_comment_payload(author_name=author_name, body=body)
    resp = api_client.create_comment(
        determination_id, payload, TEST_USERS["anonymous_headers"])
    return get_success_data(resp, 201)


def adjudicate_comment(comment_id: str, disposition="NOTED", headers=None) -> dict:
    """Adjudicate a SUBMITTED comment (PermitOfficer). Decrements the parent
    determination's unresolved_comment_count."""
    payload = create_adjudicate_payload(disposition=disposition)
    resp = api_client.adjudicate_comment(
        comment_id, payload, headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


def setup_determination_with_comment(use_type="PHOTOGRAPHY", **kwargs):
    """Determination in PUBLIC_COMMENT carrying exactly one SUBMITTED comment.
    Returns (determination, comment). Clock left at comment_open_date."""
    det = create_determination_in_public_comment(use_type=use_type, **kwargs)
    comment = submit_comment(det["id"])
    return det, comment


def setup_adjudication_with_comment(use_type="PHOTOGRAPHY", **kwargs):
    """Determination auto-moved to ADJUDICATION with one still-unresolved
    comment. Returns (determination, comment)."""
    det, comment = setup_determination_with_comment(use_type=use_type, **kwargs)
    advance_clock(clock_iso(add_days(det["comment_close_date"], 1)))
    return get_determination(det["id"]), comment


# ---------------------------------------------------------------------------
# Permit applications
# ---------------------------------------------------------------------------
def create_submitted_permit(unit_id, determination_id, applicant_ref=None,
                            use_type="RESEARCH", crew_size=4,
                            start_date=PERMIT_START_DATE,
                            end_date=PERMIT_END_DATE) -> dict:
    """Submit a permit application (SUBMITTED). applicant_ref defaults to a
    fresh dashed UUID and is threaded into the caller's X-User-ID."""
    kwargs = dict(use_type=use_type, crew_size=crew_size,
                  start_date=start_date, end_date=end_date)
    if applicant_ref is not None:
        kwargs["applicant_ref"] = applicant_ref
    payload = create_permit_payload(unit_id, determination_id, **kwargs)
    resp = api_client.create_permit(
        payload, make_permit_applicant_headers(payload["applicant_ref"]))
    return get_success_data(resp, 201)


def create_under_review_permit(unit_id, determination_id, applicant_ref=None,
                               use_type="RESEARCH", crew_size=4,
                               start_date=PERMIT_START_DATE,
                               end_date=PERMIT_END_DATE,
                               resubmit_overrides=None) -> dict:
    """Walk a fresh application through the review dialogue:
    SUBMITTED -> REVISION_REQUESTED -> UNDER_REVIEW. resubmit_overrides may
    carry revised crew_size / start_date / end_date / note."""
    permit = create_submitted_permit(
        unit_id, determination_id, applicant_ref=applicant_ref, use_type=use_type,
        crew_size=crew_size, start_date=start_date, end_date=end_date)
    resp = api_client.return_permit_for_revision(
        permit["id"], create_return_for_revision_payload(),
        TEST_USERS["permit_officer_headers"])
    get_success_data(resp)
    resp = api_client.resubmit_permit(
        permit["id"], resubmit_overrides or {},
        make_permit_applicant_headers(permit["applicant_ref"]))
    return get_success_data(resp)


def create_approved_permit(unit_id, determination_id, applicant_ref=None,
                           use_type="RESEARCH", crew_size=4,
                           start_date=PERMIT_START_DATE,
                           end_date=PERMIT_END_DATE) -> dict:
    """Permit driven to APPROVED with assessed_fee_cents set. The referenced
    determination must be FINAL and COMPATIBLE."""
    permit = create_under_review_permit(
        unit_id, determination_id, applicant_ref=applicant_ref, use_type=use_type,
        crew_size=crew_size, start_date=start_date, end_date=end_date)
    resp = api_client.approve_permit(
        permit["id"], TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


def create_active_permit(unit_id, determination_id, applicant_ref=None,
                         use_type="RESEARCH", crew_size=4,
                         start_date=PERMIT_START_DATE,
                         end_date=PERMIT_END_DATE) -> dict:
    """Permit driven to ACTIVE by paying exactly the assessed fee; commits
    crew_size x trip_days onto the unit's committed_visitor_days."""
    permit = create_approved_permit(
        unit_id, determination_id, applicant_ref=applicant_ref, use_type=use_type,
        crew_size=crew_size, start_date=start_date, end_date=end_date)
    resp = api_client.pay_permit(
        permit["id"], {"amount_cents": permit["assessed_fee_cents"]},
        make_permit_applicant_headers(permit["applicant_ref"]))
    return get_success_data(resp)


def get_permit(permit_id: str, headers=None) -> dict:
    resp = api_client.get_permit(
        permit_id, headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


def revoke_permit(permit_id: str, reason="Permit revoked by the refuge.",
                  headers=None) -> dict:
    resp = api_client.revoke_permit(
        permit_id, create_revoke_payload(reason=reason),
        headers or TEST_USERS["permit_officer_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Habitat treatments
# ---------------------------------------------------------------------------
def create_treatment(unit_id, treatment_type="INVASIVE_CONTROL",
                     window_start=TREATMENT_WINDOW_START,
                     window_end=TREATMENT_WINDOW_END, notes=None,
                     headers=None) -> dict:
    """Schedule a treatment (SCHEDULED). window_start must be >= the current
    clock date; window_end strictly after window_start."""
    kwargs = dict(treatment_type=treatment_type, window_start=window_start,
                  window_end=window_end)
    if notes is not None:
        kwargs["notes"] = notes
    resp = api_client.create_treatment(
        unit_id, create_treatment_payload(**kwargs),
        headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp, 201)


def get_treatment(unit_id, treatment_id, headers=None) -> dict:
    """Read one treatment via the unit listing (no by-id endpoint exists)."""
    items = get_success_data(api_client.list_treatments(
        unit_id, headers or TEST_USERS["biologist_headers"], params={"limit": 100}))
    for item in items:
        if item["id"] == treatment_id:
            return item
    raise AssertionError(f"treatment {treatment_id} not found on unit {unit_id}")


def start_and_complete_treatment(unit_id, treatment: dict, headers=None) -> dict:
    """Advance the clock to the treatment's window_start (opening the window),
    start it, and complete it. Returns the COMPLETED record. The unit posture
    at the clock date must not be CLOSED."""
    hdrs = headers or TEST_USERS["biologist_headers"]
    advance_clock(clock_iso(treatment["window_start"]))
    get_success_data(api_client.start_treatment(treatment["id"], hdrs))
    get_success_data(api_client.complete_treatment(treatment["id"], hdrs))
    return get_treatment(unit_id, treatment["id"], headers=hdrs)


def create_completed_treatment(unit_id, treatment_type="INVASIVE_CONTROL",
                               window_start=TREATMENT_WINDOW_START,
                               window_end=TREATMENT_WINDOW_END, notes=None,
                               headers=None) -> dict:
    """Create a treatment and drive it to COMPLETED. When composing several
    completed treatments on one unit, call in nondecreasing window_start
    order (the clock only moves forward) with non-overlapping windows."""
    treatment = create_treatment(
        unit_id, treatment_type=treatment_type, window_start=window_start,
        window_end=window_end, notes=notes, headers=headers)
    return start_and_complete_treatment(unit_id, treatment, headers=headers)


# ---------------------------------------------------------------------------
# Facility closures
# ---------------------------------------------------------------------------
def create_closure(unit_id, closure_type="MIGRATION", scope="FULL",
                   start_date=CLOSURE_START_DATE, end_date=CLOSURE_END_DATE,
                   headers=None) -> dict:
    """Schedule a closure (SCHEDULED). Activation and lift are explicit ranger
    actions; closures are never clock-driven."""
    payload = create_closure_payload(
        closure_type=closure_type, scope=scope,
        start_date=start_date, end_date=end_date)
    resp = api_client.create_closure(
        unit_id, payload, headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp, 201)


def activate_closure(closure_id: str, headers=None) -> dict:
    """Activate a SCHEDULED closure (Biologist). Fires the program-cancel,
    assignment-release, and (FULL scope only) permit-suspension cascades and
    recomputes the unit posture."""
    resp = api_client.activate_closure(
        closure_id, headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp)


def lift_closure(closure_id: str, headers=None) -> dict:
    """Lift an ACTIVE closure. Pinned permits reinstate when their end_date is
    on or after the current clock date, else expire. Cancelled programs are
    never restored."""
    resp = api_client.lift_closure(
        closure_id, headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp)


def create_active_closure(unit_id, **kwargs) -> dict:
    closure = create_closure(unit_id, **kwargs)
    return activate_closure(closure["id"], headers=kwargs.get("headers"))


def setup_closure_cascade_scenario(closure_scope="FULL", closure_type="MIGRATION",
                                   closure_start=CLOSURE_START_DATE,
                                   closure_end=CLOSURE_END_DATE,
                                   crew_size=2,
                                   permit_start="2026-10-10",
                                   permit_end="2026-10-11",
                                   program_date="2026-10-15",
                                   min_volunteers=1, max_volunteers=3) -> dict:
    """The shared cascade stage: one unit carrying an ACTIVE paid permit, one
    SCHEDULED program with one ACTIVE assignment, and one SCHEDULED closure
    whose inclusive window covers both the permit window and the program
    date. Returns a dict with unit, determination, permit, volunteer,
    program, assignment, closure. Clock is left at 2026-09-21 (before every
    staged date)."""
    unit = create_unit()
    determination = create_final_determination(use_type="RESEARCH")
    permit = create_active_permit(
        unit["id"], determination["id"], crew_size=crew_size,
        start_date=permit_start, end_date=permit_end)
    volunteer = create_cleared_volunteer()
    program = create_program(
        unit["id"], program_date=program_date,
        min_volunteers=min_volunteers, max_volunteers=max_volunteers)
    assignment = create_assignment(program["id"], volunteer["id"])
    closure = create_closure(
        unit["id"], closure_type=closure_type, scope=closure_scope,
        start_date=closure_start, end_date=closure_end)
    return {
        "unit": unit, "determination": determination, "permit": permit,
        "volunteer": volunteer, "program": program,
        "assignment": assignment, "closure": closure,
    }


# ---------------------------------------------------------------------------
# Interpretive programs, volunteers, assignments
# ---------------------------------------------------------------------------
def create_volunteer(full_name="Vol One", email=None) -> dict:
    """Anonymous self-registration; starts PENDING with null cleared_on."""
    kwargs = {"full_name": full_name}
    if email is not None:
        kwargs["email"] = email
    resp = api_client.create_volunteer(
        create_volunteer_payload(**kwargs), TEST_USERS["anonymous_headers"])
    return get_success_data(resp, 201)


def clear_volunteer(volunteer_id: str, headers=None) -> dict:
    """Clear (or renew) a volunteer's background; stamps cleared_on with the
    current logical clock date."""
    resp = api_client.clear_volunteer_background(
        volunteer_id, headers or TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def create_cleared_volunteer(full_name="Vol One", email=None) -> dict:
    """Register and clear in one step; cleared_on == current clock date."""
    volunteer = create_volunteer(full_name=full_name, email=email)
    return clear_volunteer(volunteer["id"])


def create_program(unit_id, title="Owl Prowl", program_date=PROGRAM_DATE,
                   min_volunteers=1, max_volunteers=3, headers=None) -> dict:
    """Schedule an interpretive program (SCHEDULED). program_date must be >=
    the current clock date and must not intersect an ACTIVE FULL closure
    window on the unit."""
    payload = create_program_payload(
        title=title, program_date=program_date,
        min_volunteers=min_volunteers, max_volunteers=max_volunteers)
    resp = api_client.create_program(
        unit_id, payload, headers or TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp, 201)


def get_program(unit_id, program_id, headers=None) -> dict:
    """Read one program via the unit listing (no by-id endpoint exists)."""
    items = get_success_data(api_client.list_programs(
        unit_id, headers or TEST_USERS["volunteer_coordinator_headers"],
        params={"limit": 100}))
    for item in items:
        if item["id"] == program_id:
            return item
    raise AssertionError(f"program {program_id} not found on unit {unit_id}")


def create_assignment(program_id: str, volunteer_id: str, headers=None) -> dict:
    """Assign a CLEARED volunteer to a SCHEDULED program (starts ACTIVE)."""
    resp = api_client.create_assignment(
        program_id, create_assignment_payload(volunteer_id),
        headers or TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp, 201)


def get_assignment(assignment_id: str, headers=None) -> dict:
    resp = api_client.get_assignment(
        assignment_id, headers or TEST_USERS["volunteer_coordinator_headers"])
    return get_success_data(resp)


def setup_program_with_volunteers(unit=None, num_volunteers=2,
                                  program_date=PROGRAM_DATE,
                                  min_volunteers=1, max_volunteers=3,
                                  title="Owl Prowl") -> dict:
    """A unit, one SCHEDULED program, and num_volunteers CLEARED volunteers
    each holding an ACTIVE assignment. Returns dict with unit, program,
    volunteers, assignments. cleared_on == current clock date for each."""
    if unit is None:
        unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED", acreage=500)
    program = create_program(
        unit["id"], title=title, program_date=program_date,
        min_volunteers=min_volunteers, max_volunteers=max_volunteers)
    volunteers = []
    assignments = []
    for i in range(num_volunteers):
        volunteer = create_cleared_volunteer(full_name=f"Vol {i + 1}")
        assignment = create_assignment(program["id"], volunteer["id"])
        volunteers.append(volunteer)
        assignments.append(assignment)
    return {"unit": unit, "program": program,
            "volunteers": volunteers, "assignments": assignments}


# ---------------------------------------------------------------------------
# Grazing offerings, bids, award
# ---------------------------------------------------------------------------
def create_grazing_offering(unit_id, headers=None, **overrides) -> dict:
    """Post a grazing offering (OPEN). The gate is the refuge's FINAL
    COMPATIBLE determination covering use_type GRAZING — the payload takes no
    determination_id. application_deadline must be >= the current clock date."""
    resp = api_client.create_grazing_offering(
        unit_id, create_grazing_offering_payload(**overrides),
        headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp, 201)


def place_bid(offering_id, cooperator_ref=None, rate_cents_per_aum=2000,
              stewardship_rating=7) -> dict:
    """Submit a cooperator bid (SUBMITTED). cooperator_ref defaults to a fresh
    dashed UUID and is threaded into the caller's X-User-ID."""
    payload = create_bid_payload(
        cooperator_ref=cooperator_ref, rate_cents_per_aum=rate_cents_per_aum,
        stewardship_rating=stewardship_rating)
    resp = api_client.create_bid(
        offering_id, payload, make_cooperator_headers(payload["cooperator_ref"]))
    return get_success_data(resp, 201)


def close_and_select(offering_id: str, headers=None) -> dict:
    """Close bidding and select (RefugeManager): highest rank_score wins, ties
    break toward earliest created_at; an empty eligible pool expires the
    offering. On award, creates the CooperativeAgreement."""
    resp = api_client.close_and_select_offering(
        offering_id, headers or TEST_USERS["refuge_manager_headers"])
    return get_success_data(resp)


def setup_grazing_offering(unit=None, finding="COMPATIBLE",
                           min_stewardship_rating=5, **offering_overrides) -> dict:
    """Unit + FINAL GRAZING determination (the offering gate) + one OPEN
    offering. Returns dict with unit, determination, offering. Clock left at
    2026-09-21; the default application_deadline 2026-10-01 stays valid."""
    if unit is None:
        unit = create_unit(name="South Pasture", habitat_type="GRASSLAND", acreage=3000)
    determination = create_final_determination(use_type="GRAZING", finding=finding)
    offering = create_grazing_offering(
        unit["id"], min_stewardship_rating=min_stewardship_rating, **offering_overrides)
    return {"unit": unit, "determination": determination, "offering": offering}


def find_agreement_by_winning_bid(winning_bid_id: str, headers=None) -> dict:
    """Fetch the cascade-created agreement via the winning_bid_id filter;
    exactly one agreement exists per winning bid."""
    items = get_success_data(api_client.list_agreements(
        headers or TEST_USERS["refuge_manager_headers"],
        params={"winning_bid_id": winning_bid_id}))
    assert len(items) == 1, (
        f"expected exactly one agreement for winning bid {winning_bid_id}, "
        f"got {len(items)}")
    return items[0]


def setup_awarded_agreement(bids=None, unit=None, min_stewardship_rating=5,
                            **offering_overrides) -> dict:
    """Full award flow: OPEN offering, bids placed, close-and-select, and the
    created agreement fetched via its winning bid.

    bids: list of (cooperator_ref, rate_cents_per_aum, stewardship_rating)
    tuples or dicts; defaults to a single eligible bid ("coop-1", 2000, 7).
    Returns dict with unit, determination, offering, bids (placed),
    winning_bid, agreement (ACTIVE, compliance_points 100, totals 0).
    """
    ctx = setup_grazing_offering(
        unit=unit, min_stewardship_rating=min_stewardship_rating,
        **offering_overrides)
    offering = ctx["offering"]
    if bids is None:
        bids = [("coop-1", 2000, 7)]
    placed = []
    for spec in bids:
        if isinstance(spec, dict):
            placed.append(place_bid(
                offering["id"],
                cooperator_ref=spec.get("cooperator_ref"),
                rate_cents_per_aum=spec.get("rate_cents_per_aum", 2000),
                stewardship_rating=spec.get("stewardship_rating", 7)))
        else:
            ref, rate, rating = spec
            placed.append(place_bid(
                offering["id"], cooperator_ref=ref,
                rate_cents_per_aum=rate, stewardship_rating=rating))
    close_and_select(offering["id"])
    bid_list = get_success_data(api_client.list_bids(
        offering["id"], TEST_USERS["refuge_manager_headers"],
        params={"limit": 100}))
    winners = [b for b in bid_list if b["status"] == "WINNING"]
    assert len(winners) == 1, (
        f"expected exactly one WINNING bid on offering {offering['id']}, "
        f"got {len(winners)}")
    agreement = find_agreement_by_winning_bid(winners[0]["id"])
    ctx.update({"bids": placed, "winning_bid": winners[0], "agreement": agreement})
    return ctx


# ---------------------------------------------------------------------------
# Cooperative agreements
# ---------------------------------------------------------------------------
def get_agreement(agreement_id: str, headers=None) -> dict:
    resp = api_client.get_agreement(
        agreement_id, headers or TEST_USERS["refuge_manager_headers"])
    return get_success_data(resp)


def refresh_agreement(agreement: dict, headers=None) -> dict:
    """Re-read an agreement after a mutation (version and totals advance)."""
    return get_agreement(agreement["id"], headers=headers)


def assess_period(agreement_id, period_key="2026-11", aum_used=3,
                  rate_cents_per_aum=1001, expected_agreement_version=None,
                  headers=None) -> dict:
    """Record one period's cost-share assessment (Biologist). When
    expected_agreement_version is omitted the current version is read first,
    satisfying the OCC guard. Each assessment rounds the period half-up, adds
    it into assessed_total_cents, and increments the agreement version."""
    if expected_agreement_version is None:
        expected_agreement_version = get_agreement(agreement_id)["version"]
    payload = create_assess_payload(
        expected_agreement_version, period_key=period_key, aum_used=aum_used,
        rate_cents_per_aum=rate_cents_per_aum)
    resp = api_client.assess_agreement(
        agreement_id, payload, headers or TEST_USERS["biologist_headers"])
    return get_success_data(resp)


def setup_assessed_agreement(periods=(("2026-11", 3, 1001),), **kwargs) -> dict:
    """Awarded agreement plus a sequence of period assessments.
    periods: iterable of (period_key, aum_used, rate_cents_per_aum).
    Returns the award context with the refreshed agreement."""
    ctx = setup_awarded_agreement(**kwargs)
    agreement = ctx["agreement"]
    for period_key, aum_used, rate in periods:
        agreement = assess_period(
            agreement["id"], period_key=period_key, aum_used=aum_used,
            rate_cents_per_aum=rate)
    ctx["agreement"] = agreement
    return ctx


def post_payment(agreement: dict, amount_cents: int, headers=None) -> dict:
    """PAYMENT ledger entry by the owning Cooperator (X-User-ID == the
    agreement's cooperator_ref). Must not exceed the outstanding balance."""
    payload = create_ledger_entry_payload("PAYMENT", amount_cents)
    hdrs = headers or make_cooperator_headers(agreement["cooperator_ref"])
    resp = api_client.create_ledger_entry(agreement["id"], payload, hdrs)
    return get_success_data(resp)


def post_refund(agreement: dict, amount_cents: int, headers=None) -> dict:
    """REFUND ledger entry (RefugeManager only). Capped at the refundable
    balance (paid_total_cents - refunded_total_cents)."""
    payload = create_ledger_entry_payload("REFUND", amount_cents)
    resp = api_client.create_ledger_entry(
        agreement["id"], payload, headers or TEST_USERS["refuge_manager_headers"])
    return get_success_data(resp)


def complete_agreement(agreement_id: str, headers=None) -> dict:
    """Complete an ACTIVE agreement at zero outstanding balance (RefugeManager)."""
    resp = api_client.complete_agreement(
        agreement_id, headers or TEST_USERS["refuge_manager_headers"])
    return get_success_data(resp)


def issue_agreement_citation(agreement: dict, severity="MAJOR", note=None,
                             expected_agreement_version=None,
                             headers=None) -> dict:
    """Issue a citation against an agreement (LawEnforcementOfficer). Debits
    compliance_points by severity (MINOR 10 / MAJOR 25 / CRITICAL 50) and
    increments the agreement version; points below 60 cascade-suspend an
    ACTIVE agreement. The agreement dict must be fresh, or pass
    expected_agreement_version explicitly."""
    if expected_agreement_version is None:
        expected_agreement_version = agreement["version"]
    payload = create_citation_payload(
        subject_agreement_id=agreement["id"], severity=severity,
        note=note or "Violation observed on refuge.",
        expected_agreement_version=expected_agreement_version)
    resp = api_client.create_citation(
        payload, headers or TEST_USERS["law_enforcement_officer_headers"])
    return get_success_data(resp, 201)


def issue_permit_citation(permit_id: str, severity="MAJOR", note=None,
                          headers=None) -> dict:
    """Issue a citation against a permit. Records the violation only — no fee,
    status, or version effect — and carries no OCC field."""
    payload = create_citation_payload(
        subject_permit_id=permit_id, severity=severity,
        note=note or "Violation observed on refuge.")
    resp = api_client.create_citation(
        payload, headers or TEST_USERS["law_enforcement_officer_headers"])
    return get_success_data(resp, 201)


def void_citation(citation_id: str, reason="Dismissed on review.",
                  headers=None) -> dict:
    """Void an ISSUED citation. Agreement-subject voids credit the points back
    and reinstate a SUSPENDED agreement that reaches >= 60."""
    resp = api_client.void_citation(
        citation_id, {"reason": reason},
        headers or TEST_USERS["law_enforcement_officer_headers"])
    return get_success_data(resp)


def setup_suspended_agreement(severities=("CRITICAL",), **kwargs) -> dict:
    """Awarded agreement debited into SUSPENDED by citations (default one
    CRITICAL: 100 - 50 = 50 < 60). Returns the award context with the
    refreshed agreement and the issued citations list."""
    ctx = setup_awarded_agreement(**kwargs)
    agreement = ctx["agreement"]
    citations = []
    for severity in severities:
        citations.append(issue_agreement_citation(agreement, severity=severity))
        agreement = refresh_agreement(agreement)
    assert agreement["status"] == "SUSPENDED", (
        f"expected SUSPENDED after {list(severities)}, "
        f"got {agreement['status']} at {agreement['compliance_points']} points")
    ctx.update({"agreement": agreement, "citations": citations})
    return ctx


# ---------------------------------------------------------------------------
# Population objectives
# ---------------------------------------------------------------------------
def create_population_objective(unit_id, species="Sandhill Crane",
                                target_count=1000, headers=None) -> dict:
    """Set a population objective (StateAgencyPartner); starts NO_SURVEY with
    null current_survey_count."""
    payload = create_population_objective_payload(
        species=species, target_count=target_count)
    resp = api_client.create_population_objective(
        unit_id, payload, headers or TEST_USERS["state_agency_partner_headers"])
    return get_success_data(resp, 201)


def record_survey(objective_id: str, survey_count: int, headers=None) -> dict:
    """Record a survey count; recomputes AT_TARGET (survey*10 >= target*7) or
    BELOW_TARGET."""
    resp = api_client.record_survey(
        objective_id, create_survey_payload(survey_count),
        headers or TEST_USERS["state_agency_partner_headers"])
    return get_success_data(resp)
