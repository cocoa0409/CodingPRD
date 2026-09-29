"""Composite setup helpers.

The database is empty before every test, so each scenario has to build its own
world. These helpers layer up from reference data to a fully issued
certificate, and every one of them returns the created records so a test can
assert on ids, versions and derived figures.

Setup calls go through `get_success_data`, so a broken setup step raises a clear
`Setup step failed with HTTP ...` message instead of failing an unrelated
assertion later.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CERTIFICATE_TERMS,
    DECISION_CLOCK,
    DEFAULT_CLOCK,
    ISSUANCE_CLOCK,
    SHEET_B_REV_1,
    SHEET_B_REV_2,
    SHEET_REV_1,
    SHEET_REV_2,
    SHEET_REV_3,
)
from .factories import (
    appeal_payload,
    applicant_payload,
    application_payload,
    batching_cycle_payload,
    certificate_payload,
    health_service_area_payload,
    hearing_room_payload,
    intervention_payload,
    lakeview_applicant_payload,
    letter_of_intent_payload,
    progress_report_payload,
    score_sheet_payload,
    state_plan_formula_payload,
)
from .test_users import (
    REVIEWER_USER_ID_1,
    REVIEWER_USER_ID_2,
    REVIEWER_USER_ID_3,
    TEST_USERS,
    make_applicant_headers,
    make_review_analyst_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_analyst_headers"]
REVIEWER = TEST_USERS["review_analyst_headers"]
OFFICER = TEST_USERS["decision_officer_headers"]
BOARD = TEST_USERS["appeal_board_headers"]
PUBLIC = TEST_USERS["public_participant_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(instant):
    """Move the logical clock to an instant."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


# ─── Tier 1: reference data ───────────────────────────

def seed_health_service_area(**overrides):
    return get_success_data(
        api_client.create_health_service_area(
            health_service_area_payload(**overrides), ADMIN
        ),
        201,
    )


def seed_state_plan_formula(**overrides):
    return get_success_data(
        api_client.create_state_plan_formula(
            state_plan_formula_payload(**overrides), ADMIN
        ),
        201,
    )


def seed_hearing_room(**overrides):
    return get_success_data(
        api_client.create_hearing_room(hearing_room_payload(**overrides), ADMIN), 201
    )


def seed_applicant(**overrides):
    """Register the primary applicant and return the record.

    The returned `id` is the value that has to travel as `X-User-ID` on every
    call this applicant makes.
    """
    return get_success_data(
        api_client.create_applicant(applicant_payload(**overrides), ADMIN), 201
    )


def seed_second_applicant(**overrides):
    """A second, genuinely distinct applicant — its own id, its own headers."""
    return get_success_data(
        api_client.create_applicant(lakeview_applicant_payload(**overrides), ADMIN), 201
    )


def seed_reference_data():
    """The planning area and formula every cycle needs."""
    return {"hsa": seed_health_service_area(), "formula": seed_state_plan_formula()}


# ─── Tier 2: cycles ──────────────────────────────────

def seed_batching_cycle(hsa=None, formula=None, **overrides):
    """Open a cycle over the canonical planning area and formula.

    A newly created cycle is already open for letters of intent, so nothing
    needs to be advanced before an applicant can file.
    """
    if hsa is None:
        hsa = seed_health_service_area()
    if formula is None:
        formula = seed_state_plan_formula()
    cycle = get_success_data(
        api_client.create_batching_cycle(
            batching_cycle_payload(hsa["id"], formula["id"], **overrides), ADMIN
        ),
        201,
    )
    return {"hsa": hsa, "formula": formula, "cycle": cycle}


def advance_cycle(cycle_id, to_status, headers=None):
    """Advance a cycle one stage; the advance belongs to the intake analyst."""
    return get_success_data(
        api_client.advance_batching_cycle(
            cycle_id, to_status, headers if headers is not None else INTAKE
        )
    )


# ─── Tier 3: letters of intent and applications ──────

def file_letter_of_intent(world, applicant=None, **overrides):
    """File an LOI into the cycle as the owning applicant."""
    applicant = applicant or world["applicant"]
    return get_success_data(
        api_client.create_letter_of_intent(
            letter_of_intent_payload(
                applicant["id"], world["hsa"]["id"], world["cycle"]["id"], **overrides
            ),
            make_applicant_headers(applicant["id"]),
        ),
        201,
    )


def seed_loi_filed(loi=None, **overrides):
    """Reference data + applicant + an open cycle + one filed LOI."""
    world = seed_batching_cycle(**overrides)
    world["applicant"] = seed_applicant()
    world["loi"] = file_letter_of_intent(world, **(loi or {}))
    return world


def create_application(world, applicant=None, loi=None, **overrides):
    applicant = applicant or world["applicant"]
    loi = loi or world["loi"]
    return get_success_data(
        api_client.create_application(
            application_payload(loi["id"], **overrides),
            make_applicant_headers(applicant["id"]),
        ),
        201,
    )


def submit_application(application, applicant):
    return get_success_data(
        api_client.submit_application(
            application["id"], make_applicant_headers(applicant["id"])
        )
    )


def seed_draft_application(application=None, **overrides):
    """…plus the DRAFT application converted from the filed letter."""
    world = seed_loi_filed(**overrides)
    world["application"] = create_application(world, **(application or {}))
    return world


def seed_application_submitted(**overrides):
    """…open the application window and submit the draft."""
    world = seed_draft_application(**overrides)
    world["cycle"] = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
    world["application"] = submit_application(
        world["application"], world["applicant"]
    )
    return world


# ─── Tier 4: completeness and scoring ────────────────

def seed_completeness_window(**overrides):
    """…move the cycle into `COMPLETENESS_WINDOW` with the application submitted."""
    world = seed_application_submitted(**overrides)
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPLETENESS_WINDOW")
    world["application"] = refresh_application(world["application"]["id"])
    return world


def issue_deficiency_notice(application, deficiency_items, cure_deadline_at,
                            headers=None):
    return get_success_data(
        api_client.issue_deficiency_notice(
            application["id"],
            {
                "deficiency_items": deficiency_items,
                "cure_deadline_at": cure_deadline_at,
            },
            headers if headers is not None else INTAKE,
        ),
        201,
    )


def file_cure(completeness_review, applicant, cure_response):
    return get_success_data(
        api_client.file_cure(
            completeness_review["id"],
            {"cure_response": cure_response},
            make_applicant_headers(applicant["id"]),
        )
    )


def seed_application_deemed_complete(**overrides):
    """…through the completeness window to `DEEMED_COMPLETE`."""
    world = seed_completeness_window(**overrides)
    world["application"] = get_success_data(
        api_client.deem_application_complete(world["application"]["id"], INTAKE)
    )
    return world


def seed_comparative_review(**overrides):
    """…into `COMPARATIVE_REVIEW`, where score sheets become fileable."""
    world = seed_application_deemed_complete(**overrides)
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPARATIVE_REVIEW")
    world["application"] = refresh_application(world["application"]["id"])
    return world


def file_score_sheet(application, scores, reviewer_user_id, expected_version=None,
                     narrative=None):
    """File one reviewer's sheet, carrying the application version it saw."""
    if expected_version is None:
        expected_version = application["version"]
    payload = score_sheet_payload(application["id"], expected_version, scores)
    if narrative is not None:
        payload["narrative"] = narrative
    return get_success_data(
        api_client.create_score_sheet(
            payload, make_review_analyst_headers(reviewer_user_id)
        ),
        201,
    )


def seed_two_score_sheets(**overrides):
    """Two distinct reviewers' active sheets — the decision's minimum pool."""
    world = seed_comparative_review(**overrides)
    world["sheet_1"] = file_score_sheet(
        world["application"], SHEET_REV_1, REVIEWER_USER_ID_1
    )
    world["application"] = refresh_application(world["application"]["id"])
    world["sheet_2"] = file_score_sheet(
        world["application"], SHEET_REV_2, REVIEWER_USER_ID_2
    )
    world["application"] = refresh_application(world["application"]["id"])
    return world


# ─── Tier 5: decision, certificate, appeal ───────────

def run_comparative_decision(cycle_id, note="Comparative review concluded"):
    return get_success_data(
        api_client.run_comparative_decision(cycle_id, {"decision_note": note}, OFFICER)
    )


def seed_decided_cycle(**overrides):
    """…run the comparative decision at the canonical decision instant."""
    world = seed_two_score_sheets(**overrides)
    set_clock(DECISION_CLOCK)
    world["cycle"] = run_comparative_decision(world["cycle"]["id"])
    world["application"] = refresh_application(world["application"]["id"])
    return world


def issue_certificate(application, **overrides):
    """Issue against an approved application; the appeal window must be shut."""
    terms = dict(CERTIFICATE_TERMS)
    terms.update(overrides)
    return get_success_data(
        api_client.create_certificate(
            certificate_payload(application["id"], **terms), OFFICER
        ),
        201,
    )


def seed_issued_certificate(certificate=None, **overrides):
    """…advance past the appeal window and issue the certificate."""
    world = seed_decided_cycle(**overrides)
    set_clock(ISSUANCE_CLOCK)
    world["certificate"] = issue_certificate(
        world["application"], **(certificate or {})
    )
    return world


def seed_two_application_comparative_review():
    """Two competing applications from two distinct applicants, fully scored.

    Application A (Northside, 12 beds, no partial award) carries three sheets
    and application B (Lakeview, 10 beds, partial award acceptable) carries
    two, so both clear the two-active-sheet quorum.
    """
    set_clock(DEFAULT_CLOCK)
    world = seed_batching_cycle()
    applicant_a = seed_applicant()
    applicant_b = seed_second_applicant()
    world["applicant"] = applicant_a
    world["applicant_a"] = applicant_a
    world["applicant_b"] = applicant_b

    world["loi_a"] = file_letter_of_intent(world, applicant_a)
    world["loi_b"] = file_letter_of_intent(
        world,
        applicant_b,
        project_description="10-bed acute care expansion",
        capital_cost_cents=600000000,
        bed_delta=10,
    )
    world["application_a"] = create_application(
        world, applicant_a, world["loi_a"]
    )
    world["application_b"] = create_application(
        world,
        applicant_b,
        world["loi_b"],
        requested_bed_count=10,
        projected_capital_cost_cents=600000000,
        narrative="Lakeview 10-bed acute care application",
        partial_award_acceptable=True,
    )

    world["cycle"] = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
    world["application_a"] = submit_application(world["application_a"], applicant_a)
    world["application_b"] = submit_application(world["application_b"], applicant_b)
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPLETENESS_WINDOW")
    world["application_a"] = get_success_data(
        api_client.deem_application_complete(world["application_a"]["id"], INTAKE)
    )
    world["application_b"] = get_success_data(
        api_client.deem_application_complete(world["application_b"]["id"], INTAKE)
    )
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPARATIVE_REVIEW")

    for scores, reviewer in (
        (SHEET_REV_1, REVIEWER_USER_ID_1),
        (SHEET_REV_2, REVIEWER_USER_ID_2),
        (SHEET_REV_3, REVIEWER_USER_ID_3),
    ):
        world["application_a"] = refresh_application(world["application_a"]["id"])
        file_score_sheet(world["application_a"], scores, reviewer)
    for scores, reviewer in (
        (SHEET_B_REV_1, REVIEWER_USER_ID_1),
        (SHEET_B_REV_2, REVIEWER_USER_ID_2),
    ):
        world["application_b"] = refresh_application(world["application_b"]["id"])
        file_score_sheet(world["application_b"], scores, reviewer)

    world["application_a"] = refresh_application(world["application_a"]["id"])
    world["application_b"] = refresh_application(world["application_b"]["id"])
    world["application"] = world["application_a"]
    return world


def seed_two_application_decided_cycle():
    """…and run the comparative decision, which awards 12 then 7 of the 19."""
    world = seed_two_application_comparative_review()
    set_clock(DECISION_CLOCK)
    world["cycle"] = run_comparative_decision(world["cycle"]["id"], "Cycle 1 comparative decision")
    world["application_a"] = refresh_application(world["application_a"]["id"])
    world["application_b"] = refresh_application(world["application_b"]["id"])
    world["application"] = world["application_a"]
    return world


def request_intervention(application, affected_party, requested_hearing=False,
                         grounds=None):
    payload = intervention_payload(application["id"], affected_party["id"])
    payload["requested_hearing"] = requested_hearing
    if grounds is not None:
        payload["grounds"] = grounds
    return get_success_data(
        api_client.create_intervention(
            payload, make_applicant_headers(affected_party["id"])
        ),
        201,
    )


def decide_intervention(intervention, decision, denial_reason=None, headers=None):
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.decide_intervention(
            intervention["id"], payload, headers if headers is not None else INTAKE
        )
    )


def seed_granted_intervenor_after_decision():
    """A single approved application plus a granted intervenor with standing.

    The intervenor is a second applicant whose `GRANTED` intervention on the
    application is what gives it standing to appeal.
    """
    set_clock(DEFAULT_CLOCK)
    world = seed_batching_cycle()
    applicant_a = seed_applicant()
    applicant_b = seed_second_applicant()
    world["applicant"] = applicant_a
    world["applicant_a"] = applicant_a
    world["applicant_b"] = applicant_b
    world["loi"] = file_letter_of_intent(world, applicant_a)
    world["application"] = create_application(world, applicant_a, world["loi"])
    world["cycle"] = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
    world["application"] = submit_application(world["application"], applicant_a)

    world["intervention"] = request_intervention(
        world["application"],
        applicant_b,
        grounds="Lakeview serves the same service area and is materially affected",
    )
    world["intervention"] = decide_intervention(world["intervention"], "GRANT")

    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPLETENESS_WINDOW")
    world["application"] = get_success_data(
        api_client.deem_application_complete(world["application"]["id"], INTAKE)
    )
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPARATIVE_REVIEW")

    world["application"] = refresh_application(world["application"]["id"])
    world["sheet_1"] = file_score_sheet(
        world["application"], SHEET_REV_1, REVIEWER_USER_ID_1
    )
    world["application"] = refresh_application(world["application"]["id"])
    world["sheet_2"] = file_score_sheet(
        world["application"], SHEET_REV_2, REVIEWER_USER_ID_2
    )

    set_clock(DECISION_CLOCK)
    world["cycle"] = run_comparative_decision(
        world["cycle"]["id"], "Cycle 1 comparative decision"
    )
    world["application"] = refresh_application(world["application"]["id"])
    return world


def advance_appeal(appeal, to_status):
    return get_success_data(
        api_client.advance_appeal(appeal["id"], to_status, BOARD)
    )


def decide_appeal(appeal, disposition, rationale=None):
    payload = {"disposition": disposition}
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.decide_appeal(appeal["id"], payload, BOARD))


def seed_heard_appeal_with_certificate():
    """…appeal filed by the intervenor, certificate issued, appeal at `HEARD`."""
    world = seed_granted_intervenor_after_decision()
    set_clock("2026-10-01T00:00:00Z")
    world["appeal"] = file_appeal(
        world["application"],
        world["applicant_b"],
        "Need methodology misapplied to the competing project",
    )
    set_clock(ISSUANCE_CLOCK)
    world["certificate"] = issue_certificate(world["application"])
    advance_appeal(world["appeal"], "BRIEFING")
    world["appeal"] = advance_appeal(world["appeal"], "HEARD")
    return world


def file_progress_report(certificate, applicant, expected_version=None, **overrides):
    """File a progress report; only the owning applicant may file one."""
    if expected_version is None:
        expected_version = certificate["version"]
    return get_success_data(
        api_client.create_progress_report(
            progress_report_payload(certificate["id"], expected_version, **overrides),
            make_applicant_headers(applicant["id"]),
        ),
        201,
    )


def file_appeal(application, appellant, grounds=None):
    payload = appeal_payload(application["id"], appellant["id"])
    if grounds is not None:
        payload["grounds"] = grounds
    return get_success_data(
        api_client.create_appeal(payload, make_applicant_headers(appellant["id"])), 201
    )


# ─── Re-reads ────────────────────────────────────────

def refresh_certificate(certificate_id, headers=None):
    return get_success_data(
        api_client.get_certificate(
            certificate_id, headers if headers is not None else OFFICER
        )
    )


def refresh_application(application_id, headers=None):
    return get_success_data(
        api_client.get_application(
            application_id, headers if headers is not None else INTAKE
        )
    )


def refresh_cycle(cycle_id, headers=None):
    return get_success_data(
        api_client.get_batching_cycle(
            cycle_id, headers if headers is not None else ADMIN
        )
    )


def refresh_letter_of_intent(loi_id, headers=None):
    return get_success_data(
        api_client.get_letter_of_intent(
            loi_id, headers if headers is not None else INTAKE
        )
    )


def refresh_health_service_area(hsa_id, headers=None):
    return get_success_data(
        api_client.get_health_service_area(
            hsa_id, headers if headers is not None else ADMIN
        )
    )


def refresh_applicant(applicant_id, headers=None):
    return get_success_data(
        api_client.get_applicant(
            applicant_id, headers if headers is not None else ADMIN
        )
    )


def refresh_appeal(appeal_id, headers=None):
    return get_success_data(
        api_client.get_appeal(appeal_id, headers if headers is not None else BOARD)
    )


def refresh_intervention(intervention_id, headers=None):
    return get_success_data(
        api_client.get_intervention(
            intervention_id, headers if headers is not None else INTAKE
        )
    )


def refresh_public_hearing(hearing_id, headers=None):
    return get_success_data(
        api_client.get_public_hearing(
            hearing_id, headers if headers is not None else INTAKE
        )
    )
