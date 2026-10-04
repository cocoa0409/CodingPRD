"""Composite setup helpers for the cohort-scholar domain (PRD §3).

The server is relaunched before every test, so every fixture builds its
preconditions from scratch through PRD-declared endpoints. Setup calls use a
lenient validator and raise AssertionError prefixed "Setup failed" so a broken
precondition never masquerades as a failed assertion under test.

Identity threading (PRD §2.1): ownership-gated calls always use per-instance
headers built from the real entity id — Nominator -> NominatingPartner.id,
Nominee -> Nominee.id (offer.nominee_id), FacultyMentor -> Mentor.id,
Scholar -> Scholar.id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ASSESSOR_A,
    ASSESSOR_B,
    DEFAULT_COHORT_SIZE,
    DEFAULT_CYCLE,
    DEFAULT_TUITION_CENTS,
    PASSING_SCORE,
)
from .factories import (
    create_city_program_payload,
    create_cohort_payload,
    create_evaluation_payload,
    create_mentor_payload,
    create_nominee_payload,
    create_nominating_partner_payload,
    create_offer_payload,
    create_partner_agreement_payload,
    create_partner_college_payload,
    decision_payload,
    lifecycle_payload,
    renewal_review_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_assessor_headers,
    make_nominator_headers,
    make_nominee_headers,
    make_scholar_headers,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OFFICER = TEST_USERS["selection_officer_headers"]
_DIRECTOR = TEST_USERS["career_director_headers"]


def _ok(resp, what):
    """Lenient setup validator: any 2xx is fine, anything else is a fixture bug."""
    if resp.status_code >= 300:
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return get_success_data(resp)


def _list(resp, what):
    if resp.status_code >= 300:
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601):
    """Advance the logical clock (ProgramAdmin only, PRD §2.4)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN)
    return _ok(resp, f"set clock to {to_iso8601}")


# ---------------------------------------------------------------------------
# Tier 1: city programs, partners, nominees
# ---------------------------------------------------------------------------
def setup_city_program(**overrides):
    resp = api_client.create_city_program(create_city_program_payload(**overrides), _ADMIN)
    return _ok(resp, "create city program")


def create_partner(city_program_id, **overrides):
    resp = api_client.create_nominating_partner(
        create_nominating_partner_payload(city_program_id, **overrides), _ADMIN
    )
    return _ok(resp, "create nominating partner")


def setup_city_with_partner(quota=20, program_overrides=None, partner_overrides=None):
    program = setup_city_program(**(program_overrides or {}))
    partner = create_partner(program["id"], nomination_quota=quota, **(partner_overrides or {}))
    return program, partner


def nominate(program, partner, full_name, by_nominator=False, **overrides):
    """Create a nominee. by_nominator=True sends Nominator headers keyed to the
    partner id with no nominator_id in the body; otherwise ProgramAdmin with an
    explicit nominator_id (PRD §3.1)."""
    if by_nominator:
        payload = create_nominee_payload(program["id"], full_name, **overrides)
        resp = api_client.create_nominee(payload, make_nominator_headers(partner["id"]))
    else:
        payload = create_nominee_payload(
            program["id"], full_name, nominator_id=partner["id"], **overrides
        )
        resp = api_client.create_nominee(payload, _ADMIN)
    return _ok(resp, f"nominate {full_name}")


def get_nominee(nominee_id):
    return _ok(api_client.get_nominee(nominee_id, _ADMIN), f"get nominee {nominee_id}")


def decide(nominee_id, decision):
    resp = api_client.decide_nominee(nominee_id, decision_payload(decision), _OFFICER)
    return _ok(resp, f"decision {decision} on {nominee_id}")


def submit_evaluation(nominee_id, round_number, leadership, teamwork, group_presence,
                      assessor_ref):
    resp = api_client.create_evaluation(
        create_evaluation_payload(nominee_id, round_number, leadership, teamwork, group_presence),
        make_assessor_headers(assessor_ref),
    )
    return _ok(resp, f"evaluation r{round_number} on {nominee_id} by {assessor_ref}")


def submit_round_evals(nominee_id, round_number, score=PASSING_SCORE):
    """The standard two-assessor passing block for one round."""
    submit_evaluation(nominee_id, round_number, score, score, score, ASSESSOR_A)
    return submit_evaluation(nominee_id, round_number, score, score, score, ASSESSOR_B)


def submit_round_evals_pair(nominee_id, round_number, triple_a, triple_b):
    """Two evaluations with per-assessor dimension triples."""
    submit_evaluation(nominee_id, round_number, *triple_a, ASSESSOR_A)
    submit_evaluation(nominee_id, round_number, *triple_b, ASSESSOR_B)


# ---------------------------------------------------------------------------
# Tier 2: college, agreement, mentor, cohort
# ---------------------------------------------------------------------------
def setup_college(name=None):
    payload = create_partner_college_payload() if name is None else create_partner_college_payload(name=name)
    return _ok(api_client.create_partner_college(payload, _ADMIN), "create partner college")


def get_college(college_id):
    return _ok(api_client.get_partner_college(college_id, _ADMIN), f"get college {college_id}")


def draft_agreement(college, cycle=DEFAULT_CYCLE, cohort_size=DEFAULT_COHORT_SIZE,
                    tuition_annual_cents=DEFAULT_TUITION_CENTS, expected_college_version=None):
    """Draft an agreement, OCC-guarded (PRD §2.6). When no expected version is
    supplied, the college is re-read so the fixture never goes stale."""
    if expected_college_version is None:
        expected_college_version = get_college(college["id"])["version"]
    resp = api_client.create_partner_agreement(
        create_partner_agreement_payload(
            college["id"], expected_college_version,
            admissions_cycle=cycle, cohort_size=cohort_size,
            tuition_annual_cents=tuition_annual_cents,
        ),
        _ADMIN,
    )
    return _ok(resp, f"draft agreement for college {college['id']} cycle {cycle}")


def activate_agreement(agreement_id):
    return _ok(api_client.activate_agreement(agreement_id, _ADMIN), f"activate {agreement_id}")


def create_mentor(college_id, full_name=None):
    overrides = {} if full_name is None else {"full_name": full_name}
    resp = api_client.create_mentor(create_mentor_payload(college_id, **overrides), _ADMIN)
    return _ok(resp, "create mentor")


def create_cohort(agreement, city_program, mentor):
    resp = api_client.create_cohort(
        create_cohort_payload(agreement["id"], city_program["id"], mentor["id"]), _ADMIN
    )
    return _ok(resp, "create cohort")


def setup_cohort_foundation(cohort_size=DEFAULT_COHORT_SIZE, tuition_annual_cents=DEFAULT_TUITION_CENTS,
                          cycle=DEFAULT_CYCLE, quota=20, program_overrides=None):
    """City program + partner + college + ACTIVE agreement + mentor + cohort.

    Returns a ctx dict: program, partner, college, agreement, mentor, cohort."""
    program, partner = setup_city_with_partner(quota=quota, program_overrides=program_overrides)
    college = setup_college()
    agreement = draft_agreement(
        college, cycle=cycle, cohort_size=cohort_size, tuition_annual_cents=tuition_annual_cents
    )
    activate_agreement(agreement["id"])
    mentor = create_mentor(college["id"])
    cohort = create_cohort(agreement, program, mentor)
    return {
        "program": program,
        "partner": partner,
        "college": college,
        "agreement": agreement,
        "mentor": mentor,
        "cohort": cohort,
    }


# ---------------------------------------------------------------------------
# Tier 3: nominee pipeline (assessment rounds)
# ---------------------------------------------------------------------------
def create_nominee_at_round_1(program, partner, full_name, by_nominator=False):
    """Nominee advanced NOMINATED -> ROUND_1 (ungated first step, PRD §3.2)."""
    nominee = nominate(program, partner, full_name, by_nominator=by_nominator)
    decide(nominee["id"], "ADVANCE")
    return get_nominee(nominee["id"])


def create_selected_nominee(program, partner, full_name, score=PASSING_SCORE):
    """Full pipeline to SELECTED: three rounds, two passing evaluations each,
    every cutoff cleared (PRD §3.2). Returns the SELECTED nominee."""
    nominee = create_nominee_at_round_1(program, partner, full_name)
    for round_number in (1, 2, 3):
        submit_round_evals(nominee["id"], round_number, score=score)
        decide(nominee["id"], "ADVANCE")
    return get_nominee(nominee["id"])


def create_waitlisted_nominee(program, partner, full_name, score=PASSING_SCORE):
    """Full pipeline to ROUND_3 then WAITLIST (no cutoff, PRD §3.2).
    Returns the WAITLISTED nominee."""
    nominee = create_nominee_at_round_1(program, partner, full_name)
    for round_number in (1, 2):
        submit_round_evals(nominee["id"], round_number, score=score)
        decide(nominee["id"], "ADVANCE")
    submit_round_evals(nominee["id"], 3, score=score)
    decide(nominee["id"], "WAITLIST")
    return get_nominee(nominee["id"])


# ---------------------------------------------------------------------------
# Tier 4: offers, scholars, training
# ---------------------------------------------------------------------------
def create_offer(nominee_id, cohort_id):
    resp = api_client.create_offer(create_offer_payload(nominee_id, cohort_id), _OFFICER)
    return _ok(resp, f"offer for {nominee_id} in {cohort_id}")


def accept_offer(offer):
    """Nominee accepts its own offer (ownership: X-User-ID == offer.nominee_id)."""
    resp = api_client.accept_offer(offer["id"], make_nominee_headers(offer["nominee_id"]))
    return _ok(resp, f"accept offer {offer['id']}")


def decline_offer(offer):
    resp = api_client.decline_offer(offer["id"], make_nominee_headers(offer["nominee_id"]))
    return _ok(resp, f"decline offer {offer['id']}")


def get_offer(offer_id):
    return _ok(api_client.get_offer(offer_id, _ADMIN), f"get offer {offer_id}")


def get_cohort(cohort_id):
    return _ok(api_client.get_cohort(cohort_id, _ADMIN), f"get cohort {cohort_id}")


def get_scholar_for_nominee(nominee_id):
    scholars = _list(
        api_client.list_scholars(_ADMIN, params={"nominee_id": nominee_id}),
        f"scholar for nominee {nominee_id}",
    )
    assert len(scholars) == 1, f"expected exactly one scholar for nominee {nominee_id}"
    return scholars[0]


def get_scholar(scholar_id):
    return _ok(api_client.get_scholar(scholar_id, _ADMIN), f"get scholar {scholar_id}")


def list_training_records(scholar_id):
    return _list(
        api_client.list_training_records(scholar_id, _ADMIN),
        f"training records for {scholar_id}",
    )


def complete_all_training(scholar_id):
    """Complete all eight training modules (T1..T8) for the scholar (PRD §3.7)."""
    for record in list_training_records(scholar_id):
        _ok(
            api_client.complete_training_record(record["id"], _ADMIN),
            f"complete training {record['id']}",
        )


def scholar_lifecycle(scholar_id, to_enrollment_status=None, to_standing=None, as_self=False):
    """Drive a lifecycle call as ProgramAdmin (default) or as the scholar self."""
    headers = make_scholar_headers(scholar_id) if as_self else _ADMIN
    resp = api_client.scholar_lifecycle(
        scholar_id, lifecycle_payload(to_enrollment_status, to_standing), headers
    )
    return _ok(resp, f"lifecycle on scholar {scholar_id}")


# ---------------------------------------------------------------------------
# Tier 5: full cohort lifecycles
# ---------------------------------------------------------------------------
def setup_locked_cohort(cohort_size=DEFAULT_COHORT_SIZE, tuition_annual_cents=DEFAULT_TUITION_CENTS,
                        nominee_names=None):
    """Foundation + `cohort_size` SELECTED nominees, each offered and accepted:
    the cohort ends LOCKED with a full seat ledger (PRD §3.4-3.5).

    Returns ctx dict extended with nominees, offers, scholars (parallel lists
    in creation order)."""
    size = cohort_size
    names = nominee_names or [f"Nom {i}" for i in range(1, size + 1)]
    assert len(names) == size
    ctx = setup_cohort_foundation(cohort_size=size, tuition_annual_cents=tuition_annual_cents,
                                quota=max(20, size))
    nominees, offers, scholars = [], [], []
    for name in names:
        nominee = create_selected_nominee(ctx["program"], ctx["partner"], name)
        offer = create_offer(nominee["id"], ctx["cohort"]["id"])
        accept_offer(offer)
        scholars.append(get_scholar_for_nominee(nominee["id"]))
        nominees.append(nominee)
        offers.append(get_offer(offer["id"]))
    ctx.update({"nominees": nominees, "offers": offers, "scholars": scholars})
    return ctx


def setup_matriculated_cohort(trained_count=DEFAULT_COHORT_SIZE,
                              cohort_size=DEFAULT_COHORT_SIZE,
                              tuition_annual_cents=DEFAULT_TUITION_CENTS):
    """LOCKED cohort, then `trained_count` scholars fully trained, then
    matriculated (PRD §3.6). Scholars beyond trained_count are withdrawn by the
    training gate. Returns the ctx from setup_locked_cohort plus the
    post-matriculation cohort under key "cohort_after"."""
    ctx = setup_locked_cohort(cohort_size=cohort_size, tuition_annual_cents=tuition_annual_cents)
    for scholar in ctx["scholars"][:trained_count]:
        complete_all_training(scholar["id"])
    cohort_after = _ok(
        api_client.matriculate_cohort(ctx["cohort"]["id"], _ADMIN),
        f"matriculate {ctx['cohort']['id']}",
    )
    ctx["cohort_after"] = cohort_after
    ctx["scholars"] = [get_scholar(s["id"]) for s in ctx["scholars"]]
    return ctx


def setup_completed_cohort_all_graduated(cohort_size=DEFAULT_COHORT_SIZE,
                                         tuition_annual_cents=DEFAULT_TUITION_CENTS):
    """Full happy path: every scholar trained, matriculated, RETAINED, then
    GRADUATED; the final graduation completes the cohort (PRD §3.7)."""
    ctx = setup_matriculated_cohort(trained_count=cohort_size, cohort_size=cohort_size,
                                    tuition_annual_cents=tuition_annual_cents)
    for scholar in ctx["scholars"]:
        scholar_lifecycle(scholar["id"], to_enrollment_status="RETAINED")
        scholar_lifecycle(scholar["id"], to_enrollment_status="GRADUATED")
    ctx["cohort_after"] = get_cohort(ctx["cohort"]["id"])
    return ctx


def renewal_review(college_id, decision):
    resp = api_client.renewal_review(college_id, renewal_review_payload(decision), _ADMIN)
    return _ok(resp, f"renewal {decision} on {college_id}")
