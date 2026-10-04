"""Composite setup helpers for the Wish Grant API.

The harness restarts the server before every test, so every fixture builds
its preconditions from scratch through the public endpoints. Setup calls use
the lenient get_success_data() validator: a broken precondition surfaces as a
clear "Setup failed" error, not a confusing assertion failure deep in a test.

Identity threading: the Volunteer role is entity-backed, so every
membership-gated call (visit create/conclude) builds its headers from the
actual volunteer entity id via make_volunteer_headers(). Plan creation
defaults to the "coord-1" WishCoordinator identity and approval to the
"dir-1" ChapterDirector identity, so segregation of duties holds by default;
pass explicit headers to exercise SoD or escalation paths.

Return convention: composite fixtures return a plain dict of the entities
they built (see each docstring for the keys).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_CHILD_DOB,
    CANONICAL_CHILD_NAME,
    CANONICAL_CHILD_ZIP,
    DEFAULT_CLOCK_ISO,
    DEFAULT_EVENT_END_DATE,
    DEFAULT_EVENT_START_DATE,
    DEFAULT_OFFER_VALID_UNTIL,
    DEFAULT_VISIT_END,
    DEFAULT_VISIT_START,
    URGENT_PROGNOSIS_MONTHS,
)
from .factories import (
    create_abort_payload,
    create_certify_payload,
    create_chapter_payload,
    create_clock_payload,
    create_conclude_completed_payload,
    create_conclude_payload,
    create_decide_payload,
    create_determine_payload,
    create_donation_offer_payload,
    create_fulfillment_plan_payload,
    create_line_item_payload,
    create_medical_clearance_payload,
    create_referral_payload,
    create_volunteer_payload,
    create_volunteer_transition_payload,
    create_wish_event_payload,
    create_wish_team_payload,
    create_wish_visit_payload,
)
from .test_users import TEST_USERS, make_volunteer_headers

NATIONAL_ADMIN = TEST_USERS["national_admin_headers"]
REFERRAL_SOURCE = TEST_USERS["referral_source_headers"]
MEDICAL_PROVIDER = TEST_USERS["medical_provider_headers"]
ELIGIBILITY_REVIEWER = TEST_USERS["eligibility_reviewer_headers"]
WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
IN_KIND_OFFICER = TEST_USERS["in_kind_officer_headers"]
CHAPTER_DIRECTOR = TEST_USERS["chapter_director_headers"]
NATIONAL_DIRECTOR = TEST_USERS["national_director_headers"]


def _setup_failed(step: str, response):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {response.status_code}: {response.text}"
    )


def _ok(response, step: str):
    data = get_success_data(response)
    if not isinstance(data, dict):
        _setup_failed(step, response)
    return data


# ===========================================================================
# Tier 0 — single-call helpers and fresh re-reads
# ===========================================================================

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO) -> str:
    """Advance the logical clock; returns the reported current_utc."""
    resp = api_client.set_clock(create_clock_payload(to_iso8601), NATIONAL_ADMIN)
    return _ok(resp, "set_clock")["current_utc"]


def create_chapter(**overrides) -> dict:
    """Create a chapter. Defaults: prefix 900, budget 2_000_000, target 800_000."""
    resp = api_client.create_chapter(create_chapter_payload(**overrides),
                                     NATIONAL_ADMIN)
    return _ok(resp, "create_chapter")


def get_chapter(chapter_id) -> dict:
    return _ok(api_client.get_chapter(chapter_id, NATIONAL_ADMIN), "get_chapter")


def create_volunteer(chapter_id, **overrides) -> dict:
    """Create a volunteer (lands in APPLIED)."""
    resp = api_client.create_volunteer(
        create_volunteer_payload(chapter_id, **overrides), WISH_COORDINATOR)
    return _ok(resp, "create_volunteer")


def transition_volunteer(volunteer_id, target_state) -> dict:
    resp = api_client.transition_volunteer(
        volunteer_id, create_volunteer_transition_payload(target_state),
        WISH_COORDINATOR)
    return _ok(resp, "transition_volunteer")


def activate_volunteer(volunteer_id) -> dict:
    """Walk a volunteer APPLIED -> TRAINED -> ACTIVE; returns the fresh record."""
    transition_volunteer(volunteer_id, "TRAINED")
    transition_volunteer(volunteer_id, "ACTIVE")
    return get_volunteer(volunteer_id)


def get_volunteer(volunteer_id) -> dict:
    return _ok(api_client.get_volunteer(volunteer_id, WISH_COORDINATOR),
               "get_volunteer")


def create_active_volunteer(chapter_id, full_name="Nina Park",
                            email="nina@example.org") -> dict:
    """Create a volunteer and walk them to ACTIVE."""
    volunteer = create_volunteer(chapter_id, full_name=full_name, email=email)
    return activate_volunteer(volunteer["id"])


def create_volunteer_pair(chapter_id, lead_name="Nina Park",
                          lead_email="nina@example.org",
                          second_name="Owen Diaz",
                          second_email="owen@example.org") -> tuple:
    """Two ACTIVE volunteers of one chapter: (lead, second)."""
    lead = create_active_volunteer(chapter_id, lead_name, lead_email)
    second = create_active_volunteer(chapter_id, second_name, second_email)
    return lead, second


def create_volunteer_batch(chapter_id, count, name_prefix="Vol") -> list:
    """Create `count` APPLIED volunteers (for pagination/filter tests)."""
    volunteers = []
    for i in range(1, count + 1):
        volunteers.append(create_volunteer(
            chapter_id,
            full_name=f"{name_prefix} {i:02d}",
            email=f"{name_prefix.lower()}{i:02d}@example.org",
        ))
    return volunteers


def create_referral(**overrides) -> dict:
    """Intake a referral (atomically creates or reuses the child)."""
    resp = api_client.create_referral(create_referral_payload(**overrides),
                                      REFERRAL_SOURCE)
    return _ok(resp, "create_referral")


def get_referral(referral_id) -> dict:
    return _ok(api_client.get_referral(referral_id, ELIGIBILITY_REVIEWER),
               "get_referral")


def get_child(child_id) -> dict:
    return _ok(api_client.get_child(child_id, WISH_COORDINATOR), "get_child")


def certify_referral(referral_id, qualifying_condition="ONCOLOGY",
                     certification_note=None) -> dict:
    payload = create_certify_payload(qualifying_condition)
    if certification_note is not None:
        payload["certification_note"] = certification_note
    resp = api_client.certify_referral(referral_id, payload, MEDICAL_PROVIDER)
    return _ok(resp, "certify_referral")


def determine_referral(referral_id, decision="APPROVED", denial_reason=None) -> dict:
    payload = create_determine_payload(decision)
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    resp = api_client.determine_referral(referral_id, payload, ELIGIBILITY_REVIEWER)
    return _ok(resp, "determine_referral")


def get_wish(wish_id) -> dict:
    return _ok(api_client.get_wish(wish_id, WISH_COORDINATOR), "get_wish")


def get_wish_version(wish_id) -> int:
    """Fresh Wish.version — the OCC expected_wish_version source."""
    return get_wish(wish_id)["version"]


def get_donation_offer(offer_id) -> dict:
    return _ok(api_client.get_donation_offer(offer_id, IN_KIND_OFFICER),
               "get_donation_offer")


def get_fulfillment_plan(plan_id) -> dict:
    return _ok(api_client.get_fulfillment_plan(plan_id, WISH_COORDINATOR),
               "get_fulfillment_plan")


def get_wish_team(team_id) -> dict:
    return _ok(api_client.get_wish_team(team_id, WISH_COORDINATOR),
               "get_wish_team")


# ===========================================================================
# Tier 1 — referral-to-wish progression
# ===========================================================================

def create_approved_wish(chapter=None, chapter_overrides=None,
                         zip_code=CANONICAL_CHILD_ZIP,
                         child_full_name=CANONICAL_CHILD_NAME,
                         child_date_of_birth=CANONICAL_CHILD_DOB,
                         source_type="FAMILY", prognosis_months=12,
                         qualifying_condition="ONCOLOGY",
                         diagnosis_summary="leukemia",
                         parent_email="monroe@example.org") -> dict:
    """Referral -> certify -> determine APPROVED. Returns
    {"chapter", "referral", "child_id", "wish"}; wish is CREATED version 1.

    When `chapter` is None a chapter is created whose territory prefix is the
    zip's first three digits (override via chapter_overrides).
    """
    if chapter is None:
        chapter_payload_overrides = {"territory_zip_prefixes": [zip_code[:3]]}
        if chapter_overrides:
            chapter_payload_overrides.update(chapter_overrides)
        chapter = create_chapter(**chapter_payload_overrides)
    referral = create_referral(
        child_full_name=child_full_name,
        child_date_of_birth=child_date_of_birth,
        child_zip_code=zip_code,
        parent_email=parent_email,
        diagnosis_summary=diagnosis_summary,
        source_type=source_type,
        prognosis_months=prognosis_months,
    )
    certify_referral(referral["id"], qualifying_condition)
    determined = determine_referral(referral["id"], "APPROVED")
    wish = get_wish(determined["wish_id"])
    return {
        "chapter": chapter,
        "referral": determined,
        "child_id": determined["child_id"],
        "wish": wish,
    }


def create_wish_team(wish_id, lead_volunteer_id, second_volunteer_id,
                     expected_wish_version=None, headers=None) -> dict:
    """Create (or replace) a wish's determination team under OCC.

    expected_wish_version defaults to the wish's current version (re-read
    immediately before the write); pass an explicit value for stale-version
    tests. Moves the wish CREATED -> DETERMINATION_PENDING (or self-loops on
    replacement) and bumps Wish.version by 1.
    """
    if expected_wish_version is None:
        expected_wish_version = get_wish_version(wish_id)
    payload = create_wish_team_payload(wish_id, lead_volunteer_id,
                                       second_volunteer_id,
                                       expected_wish_version)
    resp = api_client.create_wish_team(payload, headers or WISH_COORDINATOR)
    return _ok(resp, "create_wish_team")


def schedule_visit(team_id, acting_volunteer_id,
                   scheduled_start=DEFAULT_VISIT_START,
                   scheduled_end=DEFAULT_VISIT_END,
                   visit_method="PLAY_BASED") -> dict:
    """Schedule a visit; the acting volunteer must be the team's lead/second."""
    payload = create_wish_visit_payload(
        team_id, scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        visit_method=visit_method)
    resp = api_client.create_wish_visit(
        payload, make_volunteer_headers(acting_volunteer_id))
    return _ok(resp, "schedule_visit")


def conclude_visit_completed(visit_id, acting_volunteer_id,
                             captured_true_wish="a treehouse",
                             captured_wish_type="RECEIVE_ITEM") -> dict:
    """Conclude COMPLETED: visit -> COMPLETED, team -> COMPLETED, the team's
    other SCHEDULED visits -> CANCELLED, wish -> DETERMINED."""
    payload = create_conclude_completed_payload(captured_true_wish,
                                                captured_wish_type)
    resp = api_client.conclude_wish_visit(
        visit_id, payload, make_volunteer_headers(acting_volunteer_id))
    return _ok(resp, "conclude_visit_completed")


def conclude_visit_no_show(visit_id, acting_volunteer_id) -> dict:
    """Conclude NO_SHOW: only the visit changes (team stays ACTIVE)."""
    resp = api_client.conclude_wish_visit(
        visit_id, create_conclude_payload("NO_SHOW"),
        make_volunteer_headers(acting_volunteer_id))
    return _ok(resp, "conclude_visit_no_show")


# ===========================================================================
# Tier 2 — determined wish (the workhorse preamble)
# ===========================================================================

def setup_determined_wish(wish_type="RECEIVE_ITEM",
                          captured_true_wish="a treehouse",
                          prognosis_months=12,
                          chapter=None, chapter_overrides=None,
                          zip_code=CANONICAL_CHILD_ZIP,
                          child_full_name=CANONICAL_CHILD_NAME,
                          child_date_of_birth=CANONICAL_CHILD_DOB,
                          source_type="FAMILY",
                          qualifying_condition="ONCOLOGY",
                          visit_method="PLAY_BASED",
                          visit_start=DEFAULT_VISIT_START,
                          visit_end=DEFAULT_VISIT_END,
                          lead=None, second=None,
                          set_clock_first=True) -> dict:
    """Full chain to a DETERMINED wish.

    Keys: chapter, lead, second, referral, child_id, wish, team, visit.
    `wish` is re-read after the conclude, so its version is current (OCC-ready
    for plan creation).
    """
    if set_clock_first:
        set_clock()
    ctx = create_approved_wish(
        chapter=chapter, chapter_overrides=chapter_overrides,
        zip_code=zip_code, child_full_name=child_full_name,
        child_date_of_birth=child_date_of_birth, source_type=source_type,
        prognosis_months=prognosis_months,
        qualifying_condition=qualifying_condition,
    )
    chapter = ctx["chapter"]
    if lead is None or second is None:
        lead, second = create_volunteer_pair(chapter["id"])
    wish = ctx["wish"]
    team = create_wish_team(wish["id"], lead["id"], second["id"])
    visit = schedule_visit(team["id"], lead["id"],
                           scheduled_start=visit_start, scheduled_end=visit_end,
                           visit_method=visit_method)
    conclude_visit_completed(visit["id"], lead["id"], captured_true_wish,
                             wish_type)
    return {
        "chapter": chapter,
        "lead": lead,
        "second": second,
        "referral": ctx["referral"],
        "child_id": ctx["child_id"],
        "wish": get_wish(wish["id"]),
        "team": get_wish_team(team["id"]),
        "visit": visit,
    }


# ===========================================================================
# Tier 3 — donation offers and plan lifecycle
# ===========================================================================

def create_donation_offer(**overrides) -> dict:
    """Create an offer. Defaults: RETAILER / RETAIL_BASIS, qty 10,
    unit 12000, window 2026-08-01..2026-12-31."""
    resp = api_client.create_donation_offer(create_donation_offer_payload(**overrides),
                                            IN_KIND_OFFICER)
    return _ok(resp, "create_donation_offer")


def create_draft_plan(wish_id, cash_cost_cents=100000,
                      expected_wish_version=None, creator_headers=None,
                      notes=None) -> dict:
    """Create a DRAFT plan under OCC (auto-reads the wish version).

    Default creator is the "coord-1" WishCoordinator; the default approver in
    approve_plan() is the distinct "dir-1" ChapterDirector, so segregation of
    duties holds out of the box.
    """
    if expected_wish_version is None:
        expected_wish_version = get_wish_version(wish_id)
    payload = create_fulfillment_plan_payload(wish_id, expected_wish_version,
                                              cash_cost_cents)
    if notes is not None:
        payload["notes"] = notes
    resp = api_client.create_fulfillment_plan(
        payload, creator_headers or WISH_COORDINATOR)
    return _ok(resp, "create_draft_plan")


def add_line_item(plan_id, offer_id, quantity=1, headers=None) -> dict:
    """Reserve `quantity` units of an offer into a DRAFT plan."""
    resp = api_client.create_plan_line_item(
        plan_id, create_line_item_payload(offer_id, quantity),
        headers or WISH_COORDINATOR)
    return _ok(resp, "add_line_item")


def submit_plan(plan_id, headers=None) -> dict:
    resp = api_client.submit_plan(plan_id, headers or WISH_COORDINATOR)
    return _ok(resp, "submit_plan")


def approve_plan(plan_id, approver_headers=None) -> dict:
    """Approve a PENDING_APPROVAL plan. Default approver is ChapterDirector
    "dir-1"; pass NATIONAL_DIRECTOR headers when escalation is required."""
    resp = api_client.approve_plan(plan_id, approver_headers or CHAPTER_DIRECTOR)
    return _ok(resp, "approve_plan")


def abort_plan(plan_id, headers=None, reason=None) -> dict:
    """Abort a PENDING_APPROVAL or APPROVED plan (ChapterDirector)."""
    resp = api_client.abort_plan(plan_id, create_abort_payload(reason),
                                 headers or CHAPTER_DIRECTOR)
    return _ok(resp, "abort_plan")


# ===========================================================================
# Tier 4 — planning scenarios (draft / approved plans with offers and lines)
# ===========================================================================

def _build_offers_and_lines(plan_id, offer_specs):
    """offer_specs: list of dicts; each is offer-payload overrides plus an
    optional "quantity" (default 1) reserved into the plan."""
    offers, lines = [], []
    for spec in offer_specs or []:
        spec = dict(spec)
        quantity = spec.pop("quantity", 1)
        offer = create_donation_offer(**spec)
        line = add_line_item(plan_id, offer["id"], quantity)
        offers.append(offer)
        lines.append(line)
    return offers, lines


def setup_planning_wish(wish_type="RECEIVE_ITEM",
                        captured_true_wish="a treehouse",
                        prognosis_months=12,
                        cash_cost_cents=100000,
                        offer_specs=None,
                        creator_headers=None,
                        **determined_kwargs) -> dict:
    """DETERMINED wish + DRAFT plan (+ reserved lines per offer_specs).

    Keys: everything from setup_determined_wish plus plan, offers, lines.
    The wish is PLANNING afterwards; plan version/totals are current.
    """
    ctx = setup_determined_wish(
        wish_type=wish_type, captured_true_wish=captured_true_wish,
        prognosis_months=prognosis_months, **determined_kwargs)
    plan = create_draft_plan(ctx["wish"]["id"], cash_cost_cents,
                             creator_headers=creator_headers)
    offers, lines = _build_offers_and_lines(plan["id"], offer_specs)
    ctx.update({
        "plan": get_fulfillment_plan(plan["id"]),
        "offers": offers,
        "lines": lines,
        "wish": get_wish(ctx["wish"]["id"]),
    })
    return ctx


def setup_approved_wish(wish_type="RECEIVE_ITEM",
                        captured_true_wish="a treehouse",
                        prognosis_months=12,
                        cash_cost_cents=100000,
                        offer_specs=None,
                        creator_headers=None,
                        approver_headers=None,
                        **determined_kwargs) -> dict:
    """Planning wish + submit + approve.

    Non-TRAVEL wishes land in READY_TO_SCHEDULE (the approval satisfies their
    ready gate); TRAVEL wishes wait in PLAN_APPROVED for a medical clearance.
    Keys add plan (APPROVED, current), offers, lines, wish (current).
    """
    ctx = setup_planning_wish(
        wish_type=wish_type, captured_true_wish=captured_true_wish,
        prognosis_months=prognosis_months, cash_cost_cents=cash_cost_cents,
        offer_specs=offer_specs, creator_headers=creator_headers,
        **determined_kwargs)
    submit_plan(ctx["plan"]["id"], headers=creator_headers)
    approve_plan(ctx["plan"]["id"], approver_headers=approver_headers)
    ctx.update({
        "plan": get_fulfillment_plan(ctx["plan"]["id"]),
        "wish": get_wish(ctx["wish"]["id"]),
        "chapter": get_chapter(ctx["chapter"]["id"]),
        "lines": [line for line in ctx["lines"]],
    })
    return ctx


# ===========================================================================
# Tier 4b — medical clearance and scheduling lifecycle
# ===========================================================================

def request_clearance(wish_id, headers=None) -> dict:
    """Request a medical clearance for a TRAVEL wish (lands PENDING)."""
    resp = api_client.create_medical_clearance(
        create_medical_clearance_payload(wish_id), headers or WISH_COORDINATOR)
    return _ok(resp, "request_clearance")


def decide_clearance(clearance_id, decision, valid_until=None,
                     accommodations=None, decision_note=None,
                     headers=None) -> dict:
    payload = create_decide_payload(decision)
    if valid_until is not None:
        payload["valid_until"] = valid_until
    if accommodations is not None:
        payload["accommodations"] = accommodations
    if decision_note is not None:
        payload["decision_note"] = decision_note
    resp = api_client.decide_clearance(clearance_id, payload,
                                       headers or MEDICAL_PROVIDER)
    return _ok(resp, "decide_clearance")


def clear_travel_wish(wish_id, decision="CLEARED",
                      valid_until=DEFAULT_OFFER_VALID_UNTIL,
                      accommodations=None) -> dict:
    """Request + decide a clearance so the TRAVEL ready gate opens.

    A CLEARED or CONDITIONAL ruling advances PLAN_APPROVED ->
    READY_TO_SCHEDULE (or lifts MEDICAL_HOLD) in the same request.
    """
    clearance = request_clearance(wish_id)
    return decide_clearance(clearance["id"], decision, valid_until=valid_until,
                            accommodations=accommodations)


def revoke_clearance(clearance_id, decision_note="new treatment cycle") -> dict:
    """REVOKED from CLEARED/CONDITIONAL: the TRAVEL wish drops to MEDICAL_HOLD
    and its SCHEDULED events are cancelled."""
    return decide_clearance(clearance_id, "REVOKED", decision_note=decision_note)


def _event_dates_for(prognosis_months, event_start_date, event_end_date):
    """RAPID wishes must start within determined_at + 14 days; at the default
    clock the deadline is 2026-09-15, so RAPID defaults differ from STANDARD."""
    if event_start_date is not None and event_end_date is not None:
        return event_start_date, event_end_date
    if prognosis_months is not None and prognosis_months <= URGENT_PROGNOSIS_MONTHS:
        return (event_start_date or "2026-09-10", event_end_date or "2026-09-11")
    return (event_start_date or DEFAULT_EVENT_START_DATE,
            event_end_date or DEFAULT_EVENT_END_DATE)


def setup_ready_to_schedule_wish(wish_type="RECEIVE_ITEM",
                                 clearance_valid_until=DEFAULT_OFFER_VALID_UNTIL,
                                 clearance_decision="CLEARED",
                                 accommodations=None,
                                 **approved_kwargs) -> dict:
    """Approved wish in READY_TO_SCHEDULE.

    For TRAVEL this adds a clearance decided CLEARED/CONDITIONAL so the ready
    gate opens; other types arrive here directly from plan approval.
    Keys add clearance (TRAVEL only), wish (READY_TO_SCHEDULE).
    """
    ctx = setup_approved_wish(wish_type=wish_type, **approved_kwargs)
    if wish_type == "TRAVEL":
        clearance = clear_travel_wish(
            ctx["wish"]["id"], decision=clearance_decision,
            valid_until=clearance_valid_until, accommodations=accommodations)
        ctx["clearance"] = clearance
    ctx["wish"] = get_wish(ctx["wish"]["id"])
    return ctx


def schedule_event(wish_id, event_start_date=DEFAULT_EVENT_START_DATE,
                   event_end_date=DEFAULT_EVENT_END_DATE, headers=None) -> dict:
    """Create the SCHEDULED wish event; wish must be READY_TO_SCHEDULE."""
    resp = api_client.create_wish_event(
        create_wish_event_payload(wish_id, event_start_date, event_end_date),
        headers or WISH_COORDINATOR)
    return _ok(resp, "schedule_event")


def complete_event(event_id, headers=None) -> dict:
    """Complete a SCHEDULED event: runs the grant cascade (wish GRANTED, plan
    COMPLETED, lines CONSUMED, offers consumed, chapter aggregates recomputed)."""
    resp = api_client.complete_wish_event(event_id, headers or WISH_COORDINATOR)
    return _ok(resp, "complete_event")


def setup_scheduled_wish(wish_type="RECEIVE_ITEM",
                         event_start_date=None, event_end_date=None,
                         **ready_kwargs) -> dict:
    """READY_TO_SCHEDULE wish + event created; the wish lands SCHEDULED.

    Keys add event, wish (SCHEDULED).
    """
    ctx = setup_ready_to_schedule_wish(wish_type=wish_type, **ready_kwargs)
    start, end = _event_dates_for(ready_kwargs.get("prognosis_months", 12),
                                  event_start_date, event_end_date)
    event = schedule_event(ctx["wish"]["id"], start, end)
    ctx.update({"event": event, "wish": get_wish(ctx["wish"]["id"])})
    return ctx


# ===========================================================================
# Tier 5 — terminal state (granted wish) and fiscal-history scenarios
# ===========================================================================

def setup_granted_wish(wish_type="RECEIVE_ITEM",
                       event_start_date=None, event_end_date=None,
                       **scheduled_kwargs) -> dict:
    """Full lifecycle through GRANTED: determination, plan approval,
    (clearance for TRAVEL), event scheduled and completed.

    Keys add event (COMPLETED), wish (GRANTED), chapter (recomputed),
    plan (COMPLETED), lines/offers re-read where available.
    """
    ctx = setup_scheduled_wish(wish_type=wish_type,
                               event_start_date=event_start_date,
                               event_end_date=event_end_date,
                               **scheduled_kwargs)
    event = complete_event(ctx["event"]["id"])
    ctx.update({
        "event": event,
        "wish": get_wish(ctx["wish"]["id"]),
        "chapter": get_chapter(ctx["chapter"]["id"]),
        "plan": get_fulfillment_plan(ctx["plan"]["id"]),
        "offers": [get_donation_offer(o["id"]) for o in ctx.get("offers", [])],
    })
    return ctx


def setup_chapter_with_granted_wish(chapter_overrides=None,
                                    granted_cash_cents=600000,
                                    zip_prefix="800",
                                    granted_zip=None) -> dict:
    """A chapter carrying one granted cash-only wish in the current logical
    calendar year: granted_wish_count == 1 and the granted totals equal the
    plan's amounts. The volunteer pair is returned for reuse by later wishes.

    Keys: chapter, lead, second, plus the granted wish's context under
    "granted" (the setup_granted_wish dict).
    """
    overrides = {"territory_zip_prefixes": [zip_prefix],
                 "fiscal_year_budget_cents": 5000000,
                 "target_avg_cost_per_wish_cents": 800000,
                 "name": "Gulf Chapter"}
    if chapter_overrides:
        overrides.update(chapter_overrides)
    set_clock()
    chapter = create_chapter(**overrides)
    lead, second = create_volunteer_pair(chapter["id"])
    ctx = setup_granted_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a gaming pc",
        prognosis_months=12, chapter=chapter,
        zip_code=granted_zip or f"{zip_prefix}12",
        cash_cost_cents=granted_cash_cents, offer_specs=None,
        lead=lead, second=second, set_clock_first=False,
    )
    return {
        "chapter": get_chapter(chapter["id"]),
        "lead": lead,
        "second": second,
        "granted": ctx,
    }


def setup_frozen_chapter(fiscal_year_budget_cents=2000000,
                         target_avg_cost_per_wish_cents=800000,
                         plan_amounts=(950000, 950000),
                         zip_prefix="500") -> dict:
    """A chapter driven FROZEN: cash-only plans approved (by NationalDirector,
    since each projects above the target) until committed reaches/exceeds
    floor(budget * 95 / 100). Returns chapter (re-read), lead, second, and
    the per-wish contexts under "wishes".
    """
    set_clock()
    chapter = create_chapter(
        name="Sierra Chapter",
        territory_zip_prefixes=[zip_prefix],
        fiscal_year_budget_cents=fiscal_year_budget_cents,
        target_avg_cost_per_wish_cents=target_avg_cost_per_wish_cents,
    )
    lead, second = create_volunteer_pair(chapter["id"])
    wishes = []
    names = [("Lila Monroe", CANONICAL_CHILD_DOB, f"{zip_prefix}12"),
             ("Theo Alvarez", "2015-06-15", f"{zip_prefix}44")]
    for i, amount in enumerate(plan_amounts):
        name, dob, zip_code = names[i % len(names)]
        ctx = setup_approved_wish(
            wish_type="RECEIVE_ITEM", captured_true_wish="a shopping spree",
            prognosis_months=12, chapter=chapter, zip_code=zip_code,
            child_full_name=name, child_date_of_birth=dob,
            cash_cost_cents=amount, offer_specs=None,
            lead=lead, second=second, set_clock_first=False,
            approver_headers=NATIONAL_DIRECTOR,
            visit_start=f"2026-09-0{5 + i}T09:00:00Z",
            visit_end=f"2026-09-0{5 + i}T11:00:00Z",
        )
        wishes.append(ctx)
    return {
        "chapter": get_chapter(chapter["id"]),
        "lead": lead,
        "second": second,
        "wishes": wishes,
    }
