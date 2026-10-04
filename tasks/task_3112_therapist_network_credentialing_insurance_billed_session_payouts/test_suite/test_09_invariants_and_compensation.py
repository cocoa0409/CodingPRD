"""Compensating pairs that conserve a quantity: retiring and rebuilding a payout
batch, and transferring an assignment between clinicians."""
from test_helpers import (
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    adjudicate,
    api_client,
    assert_payout_line,
    assert_payout_line_invariants,
    attach_billable_clinician,
    get_batch,
    get_batch_lines,
    get_clinician,
    get_clinician_payout_lines,
    get_patient,
    make_completed_session,
    make_payer,
    make_rate,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    submit_claim,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]


def _two_session_scenario() -> dict:
    """One billable clinician, two completed sessions in one WEEKLY window, one
    claim paid and one denied, both resolving against the same 15000-cent rate."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(
        payer["id"],
        availability_blocks=[
            {"weekday": 2, "start_minute": 480, "end_minute": 1080},
            {"weekday": 3, "start_minute": 480, "end_minute": 1080},
        ],
    )
    clinician = attached["clinician"]
    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"], full_name="Marcus Cole", member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    set_clock(CLOCK_DELIVERY)
    q1 = make_completed_session(
        clinician["id"], pat_a["id"], "2026-06-02T14:00:00Z", "2026-06-02T15:00:00Z",
        stripe_note="Narrative for the first session of the invariant pair.",
    )
    q2 = make_completed_session(
        clinician["id"], pat_b["id"], "2026-06-03T14:00:00Z", "2026-06-03T15:00:00Z",
        stripe_note="Narrative for the second session of the invariant pair.",
    )
    claim_q1 = submit_claim(q1["id"])
    claim_q2 = submit_claim(q2["id"])
    adjudicate(claim_q1["id"], "PAID")
    adjudicate(claim_q2["id"], "DENIED", "NOT_COVERED")
    return {"payer": payer, "clinician": clinician, "q1": q1, "q2": q2,
            "claim_q1": claim_q1, "claim_q2": claim_q2}


def test_superseding_an_open_batch_voids_its_lines_and_zeroes_its_totals():
    """PRD §3.6: "A batch may also be retired explicitly before it is locked by
    an `OpsAdmin` whose observed `version` of that open batch still matches, which
    moves it to `SKIPPED` and voids its non-voided lines"
    PRD §3.6: "Voided lines are excluded entirely — a batch all of whose lines
    were voided by supersession has a line count of zero and all totals of zero."

    Design: Difficulty/compensating_invariant/superseding_a_batch_moves_earnings_without_creating_or_losing_a_cent
    """
    batch_b1 = open_and_lock_batch(
        "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY", lock=False
    )
    assert batch_b1["status"] == "OPEN"
    assert batch_b1["line_count"] == 0, (
        "lines are materialized at lock time, not at opening"
    )

    superseded = validate_success(
        api_client.supersede_payout_batch(
            batch_b1["id"], {"expected_open_batch_version": batch_b1["version"]}, OPS
        )
    )
    assert superseded["status"] == "SKIPPED"
    assert superseded["total_gross_cents"] == 0
    assert superseded["total_adjustment_cents"] == 0
    assert superseded["total_net_cents"] == 0
    assert superseded["line_count"] == 0
    for line in get_batch_lines(batch_b1["id"]):
        assert line["line_status"] == "VOIDED", (
            "every non-voided line on the retired batch is voided"
        )


def test_the_replacement_batch_carries_the_whole_amount_and_the_sum_is_conserved():
    """PRD §3.6: "a batch is paid on its schedule whether or not the payers
    behind its claims have remitted"
    PRD §3.6: "the total gross is the sum of the included lines' `gross_cents`,
    the total adjustment is the signed sum of their `adjustment_cents`, the total
    net is the sum of their `net_cents`, and the line count is the number of
    included lines."
    PRD §3.6: "Because a `PAID` line's net may go negative when a clawback exceeds
    its gross and the floor applies only to pending lines, that negative value
    flows into the balance unchanged."

    Design: Difficulty/compensating_invariant/superseding_a_batch_moves_earnings_without_creating_or_losing_a_cent
    """
    scenario = _two_session_scenario()
    clinician_id = scenario["clinician"]["id"]
    batch_b1 = open_and_lock_batch(
        "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY", lock=False
    )
    batch_b1 = get_batch(batch_b1["id"])
    validate_success(
        api_client.supersede_payout_batch(
            batch_b1["id"], {"expected_open_batch_version": batch_b1["version"]}, OPS
        )
    )

    batch_b2 = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    assert batch_b2["total_gross_cents"] == 30_000, (
        "the scheduled basis counts both sessions, paid and denied alike"
    )
    assert batch_b2["total_adjustment_cents"] == 0
    assert batch_b2["total_net_cents"] == 30_000
    assert batch_b2["line_count"] == 1
    assert batch_b2["supersedes_batch_id"] is None, (
        "the retired batch was already SKIPPED, so only an OPEN overlap sets this link"
    )

    pending_lines = get_clinician_payout_lines(
        clinician_id, {"line_status": "PENDING", "limit": 10, "offset": 0}
    )
    assert len(pending_lines) == 1, "no earning was duplicated onto a second line"
    assert pending_lines[0]["net_cents"] == 30_000
    assert set(pending_lines[0]["session_ids"]) == {scenario["q1"]["id"], scenario["q2"]["id"]}
    assert_payout_line(pending_lines[0])
    assert_payout_line_invariants(pending_lines[0])
    assert get_clinician(clinician_id)["payout_balance_cents"] == 0, (
        "no batch was ever paid, so the balance has not moved"
    )


def _reassignment_scenario() -> dict:
    """Dana carrying two matched patients while Zara is held out of the pool;
    a departing clinician's plan names Zara as successor for one of them."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    dana = attach_billable_clinician(
        payer["id"], full_name="Dana Reyes", weekly_caseload_target=4,
        license_number="LCSW-CA-77120",
    )["clinician"]
    # PRD §3.7 ranks by ascending `created_at` as its third key, so the two
    # candidates have to be created at distinguishable instants or they tie and
    # the match is refused with `ERR_MATCH_TIE_UNRESOLVABLE`.
    set_clock("2026-03-02T00:00:00Z")
    zara = attach_billable_clinician(
        payer["id"], full_name="Zara Whitfield", weekly_caseload_target=4,
        specialty_tags=["GRIEF"],
        license_number="LCSW-CA-90211",
        availability_blocks=[{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
    )["clinician"]
    set_clock("2026-03-03T00:00:00Z")
    nadia = api_client.create_clinician(
        {
            "full_name": "Nadia Okonkwo",
            "license_type": "LMFT",
            "primary_state": "CA",
            "specialty_tags": ["ANXIETY"],
            "weekly_caseload_target": 4,
            "availability_blocks": [{"weekday": 4, "start_minute": 480, "end_minute": 1080}],
        },
        OPS,
    ).json()["data"]

    priya = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    marcus = make_verified_patient(
        payer["id"], full_name="Marcus Cole", member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    for patient in (priya, marcus):
        matched = validate_success(
            api_client.match_patient(patient["id"], {"specialty_tags": ["ANXIETY"]}, OPS)
        )
        assert matched["matched_clinician_id"] == dana["id"], (
            "Zara is tagged only for GRIEF, so the ANXIETY request leaves Dana "
            "as the sole candidate; Nadia holds no EFFECTIVE enrollment"
        )
    plan = validate_success(
        api_client.create_continuity_plan(
            {"clinician_id": nadia["id"], "patient_id": priya["id"],
             "reason": "OFFBOARDING", "successor_clinician_id": zara["id"]},
            OPS,
        ), 201
    )
    return {"payer": payer, "dana": dana, "zara": zara, "nadia": nadia,
            "priya": priya, "marcus": marcus, "plan": plan}


def test_patient_reassignment_conserves_the_summed_assigned_patient_count():
    """PRD §3.7: "Accepting moves the plan to `ACCEPTED`, transfers the patient's
    `matched_clinician_id` to the successor, decrements the prior clinician's
    `active_patient_count` and increments the successor's, and clears the
    patient's `swap_requested` flag."

    Design: Difficulty/compensating_invariant/patient_reassignment_conserves_the_networks_total_assigned_patient_count
    """
    scenario = _reassignment_scenario()
    dana_id = scenario["dana"]["id"]
    zara_id = scenario["zara"]["id"]

    dana_before = get_clinician(dana_id)["active_patient_count"]
    zara_before = get_clinician(zara_id)["active_patient_count"]
    assert dana_before == 2 and zara_before == 0
    assert dana_before + zara_before == 2

    accepted = validate_success(
        api_client.accept_continuity_plan(
            scenario["plan"]["id"], make_clinician_headers(zara_id)
        )
    )
    assert accepted["status"] == "ACCEPTED"

    dana_after = get_clinician(dana_id)["active_patient_count"]
    zara_after = get_clinician(zara_id)["active_patient_count"]
    assert dana_after == 1 and zara_after == 1
    assert dana_before + zara_before == dana_after + zara_after == 2, (
        "the transfer moved one patient rather than creating or destroying one"
    )
    assert get_patient(scenario["priya"]["id"])["matched_clinician_id"] == zara_id
    assert get_patient(scenario["priya"]["id"])["swap_requested"] is False


def test_matching_the_previously_unmatched_patient_keeps_the_identity_on_a_larger_count():
    """PRD §3.7: "the clinician's `active_patient_count` is strictly less than
    their `weekly_caseload_target`"
    PRD §3.7: "An empty candidate set is rejected with `ERR_NO_ELIGIBLE_CLINICIAN`
    at HTTP 422 and no match is written."

    Design: Difficulty/compensating_invariant/patient_reassignment_conserves_the_networks_total_assigned_patient_count
    """
    scenario = _reassignment_scenario()
    dana_id = scenario["dana"]["id"]
    zara_id = scenario["zara"]["id"]

    validate_success(
        api_client.accept_continuity_plan(
            scenario["plan"]["id"], make_clinician_headers(zara_id)
        )
    )
    validate_success(
        api_client.update_clinician(zara_id, {"specialty_tags": ["ANXIETY"]}, OPS)
    )
    elena = make_verified_patient(
        scenario["payer"]["id"], full_name="Elena Vargas", member_id="MBR-6031",
        verification={"deductible_remaining_cents": 20_000},
    )
    matched = validate_success(
        api_client.match_patient(elena["id"], {"specialty_tags": ["ANXIETY"]}, OPS)
    )
    assert matched["matched_clinician_id"] in (dana_id, zara_id), (
        "the selector's third rank key decides between two otherwise tied candidates"
    )
    dana_after = get_clinician(dana_id)["active_patient_count"]
    zara_after = get_clinician(zara_id)["active_patient_count"]
    assert dana_after + zara_after == 3, (
        "the identity holds at three once the previously unmatched patient is assigned"
    )
    assert get_patient(elena["id"])["matched_clinician_id"] is not None