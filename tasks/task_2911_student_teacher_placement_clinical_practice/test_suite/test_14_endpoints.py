"""The surface's own behaviours: its one PATCH, its read-time derivations and
its conditional money action.

The supervisor adjustment is the only update endpoint in the API and it must
re-resolve two derived fields in the same request; the supervisor read must
re-derive the caseload without any write at all; the stipend transition must
refuse a payout that the variant does not permit; and a placement read must
expose every association routing created, so that one response is enough to
verify the whole link structure.
"""
from test_helpers import (
    ERR_PROVISIONAL_STIPEND_NOT_PAYABLE,
    PROGRAM_ADMIN,
    SUPERVISION_LEAD,
    assert_caseload,
    assert_date_equals,
    factories as f,
    read_agreement,
    read_placement,
    read_supervisor,
    setup_active_placement,
    setup_proposed_placement,
    validate_error,
    validate_success,
)

TIGHTER_OVERRIDE = {"max_caseload_points_override": 1}
PROVISIONAL_GROSS_CENTS = 181468


def test_lowering_the_override_closes_the_supervisor_to_new_placements(api):
    """An override of 1 under 2 accrued points flips the acceptance flag.

    PRD §3.4: "when an override is present, the effective ceiling is the smaller
    of the employment-type figure and the override ... `accepting_new_placements`
    ... is additionally forced to false by any caseload recomputation that finds
    `caseload_points` at or above `max_caseload_points`".  PRD §3.4: "a
    `SupervisionLead` may later adjust any of `max_caseload_points_override`,
    `max_travel_miles` and `accepting_new_placements` through the
    supervisor-adjustment capability, which re-resolves the ceiling and the
    availability flag".

    Design: Corner/endpoints/patching_the_supervisor_override_lowers_the_acceptance_flag
    """
    scenario = setup_proposed_placement(api)
    before = read_supervisor(api, scenario.supervisor_id)
    assert_caseload(before, 2, max_caseload_points=24)
    assert before["accepting_new_placements"] is True

    adjusted = validate_success(api.update_supervisor(
        scenario.supervisor_id, f.supervisor_update_payload(**TIGHTER_OVERRIDE),
        SUPERVISION_LEAD))

    assert adjusted["max_caseload_points_override"] == 1
    assert adjusted["max_caseload_points"] == 1
    assert adjusted["accepting_new_placements"] is False
    assert adjusted["caseload_points"] == 2, (
        "the override changes the cap, not the accrued points")


def test_reading_a_supervisor_re_derives_the_caseload_without_a_write(api):
    """A plain GET already reports the ACTIVE base plus the distance surcharge.

    PRD §3.4: "Caseload is recomputed on every placement creation, confirmation,
    reroute-void, removal request, removal decision and completion, and reading a
    single supervisor re-derives `caseload_points`, `max_caseload_points` and
    `accepting_new_placements` before answering."  PRD §3.4: "0 points when that
    distance is 15 miles or less, 1 point when it is from 16 through 40 miles".

    Design: Corner/endpoints/reading_a_supervisor_recomputes_the_caseload_points
    """
    scenario = setup_active_placement(api)

    supervisor = read_supervisor(api, scenario.supervisor_id)

    assert_caseload(supervisor, 3, max_caseload_points=24)
    assert supervisor["accepting_new_placements"] is True
    assert supervisor["max_travel_miles"] == 60


def test_a_provisional_accrual_may_not_be_paid_even_once_approved(api):
    """APPROVED is reachable while running; PAID is not, because the estimate stands.

    PRD §3.9: "`APPROVED → PAID` requires `stipend_variant` to be `FINAL`: a
    provisional accrual is an estimate and may never leave the program, so a
    payment attempt on a provisional figure is refused with
    `ERR_PROVISIONAL_STIPEND_NOT_PAYABLE`."

    Design: Corner/endpoints/paying_a_provisional_stipend_returns_provisional_stipend_not_payable
    """
    scenario = setup_active_placement(api)
    validate_success(api.transition_stipend(
        scenario.placement_id,
        f.stipend_transition_payload("APPROVED", note="Mid-term approval."),
        PROGRAM_ADMIN))

    validate_error(api.transition_stipend(
        scenario.placement_id,
        f.stipend_transition_payload("PAID",
                                     note="Attempting an early payout."),
        PROGRAM_ADMIN), ERR_PROVISIONAL_STIPEND_NOT_PAYABLE, 422)

    placement = read_placement(api, scenario.placement_id)
    assert placement["stipend_status"] == "APPROVED"
    assert placement["stipend_variant"] == "PROVISIONAL"
    assert placement["stipend_gross_cents"] == PROVISIONAL_GROSS_CENTS
    assert read_agreement(api, scenario.agreement_id)[
        "stipend_committed_cents"] == PROVISIONAL_GROSS_CENTS


def test_a_placement_read_exposes_every_association_routing_created(api):
    """Five foreign keys, the copied match terms and the computed commute.

    PRD §3.5: "A placement is created in `PROPOSED` ... carrying the ids of the
    request, the candidate, the teacher, the agreement and the supervisor, the
    `subject` and `grade_band` copied from the request, `start_date` and
    `end_date` copied from the request's term, `weeks_scheduled`, the computed
    `commute_miles`, `supervisor_points` at the proposed stage and a null
    `replaces_placement_id`."

    Design: Corner/endpoints/reading_a_placement_exposes_every_foreign_key_it_links
    """
    scenario = setup_proposed_placement(api)

    placement = read_placement(api, scenario.placement_id)

    assert placement["request_id"] == scenario.request_id
    assert placement["candidate_id"] == scenario.candidate_id
    assert placement["cooperating_teacher_id"] == scenario.teacher_id
    assert placement["agreement_id"] == scenario.agreement_id
    assert placement["supervisor_id"] == scenario.supervisor_id
    assert placement["subject"] == "MATH"
    assert placement["grade_band"] == "HS_9_12"
    assert_date_equals(placement["start_date"], "2026-09-01", "start_date")
    assert_date_equals(placement["end_date"], "2026-12-07", "end_date")
    assert placement["weeks_scheduled"] == 14
    assert placement["commute_miles"] == 14
    assert placement["supervisor_points"] == 2
    assert placement["replaces_placement_id"] is None
