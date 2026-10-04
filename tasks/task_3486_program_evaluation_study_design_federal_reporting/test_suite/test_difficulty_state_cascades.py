"""Difficulty queue — cyclic state machines, transitive cascades, and the
compensating invariants (enrollment counts, contract funds)."""
from datetime import datetime, timezone

from test_helpers import (
    TEST_USERS,
    add_participant,
    add_record,
    assert_contract_funds_invariant,
    create_design_plan,
    create_study_payload,
    create_wave,
    design_plan_decision_payload,
    get_contract,
    get_participant,
    get_study,
    get_wave,
    irb_decision_payload,
    make_participant_headers,
    open_wave,
    set_clock,
    setup_active_site_study,
    setup_contract,
    setup_published_report,
    setup_study_with_sites,
    terminate_contract_payload,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
DM = TEST_USERS["data_manager_headers"]
IRB = TEST_USERS["irb_reviewer_headers"]


def _find(items, entity_id):
    return next(e for e in items if e["id"] == entity_id)


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_design_plan_revision_cycle(api):
    """PRD §3.2: "A `decision` of `RETURNED` instead moves the plan to
    `RETURNED_FOR_REVISION`, from which a `PrincipalInvestigator` reopens it as
    `DRAFT` by revising; revising increments `revision_number` by one, keeps
    every design parameter unchanged, and is itself allowed only from
    `RETURNED_FOR_REVISION` (otherwise `ERR_DESIGN_PLAN_INVALID_STATE`)."
    PRD §3.2: "A `decision` of `APPROVED` moves the plan to `AGENCY_APPROVED`,
    and if at that moment at least one site of the study is already `RECRUITED`
    or `ACTIVE`, the plan continues immediately, within the same request, to
    `LOCKED` — and the study, if still in `DESIGN`, advances to `RECRUITMENT`
    in the same breath."

    Design: Difficulty/non_linear_state_machine/design_plan_revision_cycle
    """
    ctx = setup_study_with_sites(
        site_specs=((60, "RECRUITED"), (300, "CONTACTED"), (300, "CONTACTED"))
    )
    study_id = ctx["study"]["id"]
    plan = create_design_plan(study_id)
    plan_id = plan["id"]
    assert plan["revision_number"] == 1

    plan = validate_success(api.submit_design_plan(plan_id, PI), 200)
    plan = validate_success(
        api.design_plan_agency_decision(plan_id, design_plan_decision_payload("RETURNED"), AO),
        200,
    )
    assert plan["status"] == "RETURNED_FOR_REVISION"

    plan = validate_success(api.revise_design_plan(plan_id, PI), 200)
    assert plan["status"] == "DRAFT"
    assert plan["revision_number"] == 2, f"revision loop increments: {plan['revision_number']}"

    plan = validate_success(api.submit_design_plan(plan_id, PI), 200)
    plan = validate_success(
        api.design_plan_agency_decision(plan_id, design_plan_decision_payload("APPROVED"), AO),
        200,
    )
    assert plan["status"] == "LOCKED", (
        f"site A already RECRUITED, so approval auto-locks in the same request; got {plan['status']}"
    )
    assert get_study(study_id)["status"] == "RECRUITMENT"


def test_wave_suspend_resume_cycle_on_irb_expiry(api):
    """PRD §3.3: "An `EXPIRED` protocol is not terminal — it can be resubmitted
    as described above — but until a protocol of the study is approved again,
    every IRB-gated operation fails."
    PRD §3.6: "When a `SUSPENDED` wave is reopened after re-approval, its
    records that the expiry cascade quarantined remain `QUARANTINED` — there is
    no auto-restore, by the quarantine principle of §2.6."

    Design: Difficulty/non_linear_state_machine/wave_suspend_resume_cycle_on_irb_expiry
    """
    ctx = setup_active_site_study()
    study_id = ctx["study"]["id"]
    irb_id = ctx["irb"]["id"]
    p1 = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)
    wave = create_wave(
        study_id, wave_type="SURVEY",
        open_at="2026-10-01T00:00:00Z", close_at="2028-06-01T00:00:00Z",
    )
    wave = open_wave(wave["id"], clock="2026-10-15T00:00:00Z")
    rec = add_record(wave["id"], p1["id"], instrument_minutes=45, payload_ref="survey-1")

    set_clock("2027-09-01T00:00:00Z")
    protocols, _ = validate_paginated(api.list_irb_protocols(study_id, PI))
    assert _find(protocols, irb_id)["status"] == "EXPIRED", (
        "half-open window ends exactly at approval_end"
    )
    assert get_wave(wave["id"])["status"] == "SUSPENDED"
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert _find(records, rec["id"])["status"] == "QUARANTINED"

    validate_success(api.submit_irb_protocol(irb_id, PI), 200)
    irb = validate_success(
        api.irb_decision(
            irb_id,
            irb_decision_payload(
                "APPROVED",
                approval_start="2027-09-01T00:00:00Z",
                approval_end="2028-08-31T00:00:00Z",
            ),
            IRB,
        ),
        200,
    )
    assert irb["status"] == "APPROVED"
    assert _parse(irb["approval_start"]) == datetime(2027, 9, 1, tzinfo=timezone.utc)
    assert _parse(irb["approval_end"]) == datetime(2028, 8, 31, tzinfo=timezone.utc)

    # Clock still reads 2027-09-01, inside both the new IRB window and the wave
    # window, so the SUSPENDED wave reopens.
    wave = validate_success(api.open_wave(wave["id"], DM), 200)
    assert wave["status"] == "OPEN"
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert _find(records, rec["id"])["status"] == "QUARANTINED", "no auto-restore on resume"


def test_irb_expiry_cascade_three_levels(api):
    """PRD §3.3: "When the logical clock of §2.4 reaches or passes an
    `APPROVED` protocol's `approval_end` — at exactly `approval_end` the
    protocol is already expired, because the window is half-open — the protocol
    moves to `EXPIRED` and the cascade fires in the same instant: every `OPEN`
    wave of the study moves to `SUSPENDED`, and every `RECEIVED` or `VALIDATED`
    response record of each newly suspended wave moves to `QUARANTINED`, with
    the study's `quarantined_record_count` recomputed to include them."

    Design: Difficulty/transitive_cascade/irb_expiry_cascade_three_levels
    """
    ctx = setup_active_site_study()
    study_id = ctx["study"]["id"]
    irb_id = ctx["irb"]["id"]
    p1 = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)
    wave = create_wave(study_id)
    wave = open_wave(wave["id"])
    rec = add_record(wave["id"], p1["id"], instrument_minutes=45, payload_ref="survey-1")

    set_clock("2027-09-01T00:00:00Z")

    protocols, _ = validate_paginated(api.list_irb_protocols(study_id, PI))
    assert _find(protocols, irb_id)["status"] == "EXPIRED"  # level 1
    assert get_wave(wave["id"])["status"] == "SUSPENDED"    # level 2
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert _find(records, rec["id"])["status"] == "QUARANTINED"  # level 3
    assert get_study(study_id)["quarantined_record_count"] == 1  # derived


def test_site_withdrawal_cascade_enrollment_quarantine(api):
    """PRD §3.4: "Withdrawal cascades: every non-terminal participant of the
    site moves to `WITHDRAWN` with `withdrawal_reason` `SITE_WITHDRAWN`, each
    such participant withdrawal quarantines that participant's `RECEIVED` or
    `VALIDATED` records and, when the participant had consented, decrements the
    site's `enrolled_count`, exactly as §3.5 specifies for participant
    withdrawal."
    PRD §3.4: "The study's `committed_projected_n`, `pipeline_projected_n`,
    `enrolled_total`, and `sample_adequacy` are then recomputed — and because a
    withdrawn site contributes nothing, adequacy can flip from `ADEQUATE` back
    to `UNDERPOWERED`."

    Design: Difficulty/transitive_cascade/site_withdrawal_cascade_enrollment_quarantine
    """
    ctx = setup_active_site_study(
        site_specs=((60, "RECRUITED"), (300, "CONTACTED"), (300, "CONTACTED"))
    )
    study_id = ctx["study"]["id"]
    site_a = ctx["site"]
    p1 = add_participant(site_a["id"], external_ref="P001", consent=True)
    wave = create_wave(study_id)
    wave = open_wave(wave["id"])
    rec = add_record(wave["id"], p1["id"], instrument_minutes=45, payload_ref="survey-1")

    validate_success(api.withdraw_site(site_a["id"], SD, {"reason": "Site lost funding"}), 200)

    sites, _ = validate_paginated(api.list_sites(study_id, SD))
    assert _find(sites, site_a["id"])["status"] == "WITHDRAWN"  # level 1
    p1 = get_participant(p1["id"])  # level 2
    assert p1["status"] == "WITHDRAWN"
    assert p1["withdrawal_reason"] == "SITE_WITHDRAWN"
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert _find(records, rec["id"])["status"] == "QUARANTINED"  # level 3
    study = get_study(study_id)  # derived
    assert study["enrolled_total"] == 0
    assert study["quarantined_record_count"] == 1
    assert study["sample_adequacy"] == "UNDERPOWERED"  # pipeline 210 < required 214


def test_enrollment_conservation_consent_withdraw_cycle(api):
    """PRD §3.5: "The enrollment counters obey a strict reconciliation
    invariant: at every observable instant, the sum of `enrolled_count` over a
    study's sites equals the study's `enrolled_total`, and both equal a direct
    recount of the participants in the three counted statuses — `CONSENTED`,
    `RANDOMIZED_TREATMENT`, and `RANDOMIZED_CONTROL`."
    PRD §3.5: "`PARTICIPANT_INITIATED` when the participant or a study director
    initiated it directly."

    Design: Difficulty/compensating_invariant/enrollment_conservation_consent_withdraw_cycle
    """
    ctx = setup_active_site_study(
        site_specs=((10, "RECRUITED"), (300, "CONTACTED"), (300, "CONTACTED"))
    )
    study_id = ctx["study"]["id"]
    site_a = ctx["site"]
    p1 = add_participant(site_a["id"], external_ref="P001")
    p2 = add_participant(site_a["id"], external_ref="P002")
    p3 = add_participant(site_a["id"], external_ref="P003")

    def enrolled_pair():
        sites, _ = validate_paginated(api.list_sites(study_id, SD))
        site_now = _find(sites, site_a["id"])
        return site_now["enrolled_count"], get_study(study_id)["enrolled_total"]

    p1 = validate_success(
        api.consent_participant(p1["id"], {"consent_form_version": 1},
                                make_participant_headers(p1["id"])), 200)
    assert enrolled_pair() == (1, 1)
    p2 = validate_success(
        api.consent_participant(p2["id"], {"consent_form_version": 1},
                                make_participant_headers(p2["id"])), 200)
    assert enrolled_pair() == (2, 2)

    p1 = validate_success(
        api.withdraw_participant(p1["id"], make_participant_headers(p1["id"]),
                                 {"reason": "Changed mind"}), 200)
    assert p1["status"] == "WITHDRAWN"
    assert p1["withdrawal_reason"] == "PARTICIPANT_INITIATED"
    assert enrolled_pair() == (1, 1), "withdrawal compensates the earlier consent"

    p3 = validate_success(
        api.consent_participant(p3["id"], {"consent_form_version": 1},
                                make_participant_headers(p3["id"])), 200)
    site_count, total = enrolled_pair()
    assert (site_count, total) == (2, 2)
    participants, _ = validate_paginated(
        api.list_participants(PI, params={"site_id": site_a["id"], "status": "CONSENTED"})
    )
    assert len(participants) == 2, "direct recount matches the counters (P2, P3)"


def test_contract_funds_conservation_publish_and_terminate(api):
    """PRD §3.1: "The contract's three ledger fields form a single invariant
    that holds at every observable instant: the disbursed amount plus the
    forfeited amount plus the remaining amount always equals the award amount."
    PRD §3.1: "Termination or closeout of the contract forfeits whatever
    remains undisbursed: in both cases `forfeited_cents` is set to the
    then-current `remaining_cents` and `remaining_cents` becomes zero, so the
    invariant is preserved."

    Design: Difficulty/compensating_invariant/contract_funds_conservation_publish_and_terminate
    """
    ctx = setup_published_report()  # award 90000000, milestone 30000000 disbursed
    contract_a = get_contract(ctx["contract"]["id"])
    assert contract_a["disbursed_cents"] == 30000000
    assert contract_a["forfeited_cents"] == 0
    assert contract_a["remaining_cents"] == 60000000
    assert_contract_funds_invariant(contract_a)

    contract_b = setup_contract(award_amount_cents=50000000)
    study_b = validate_success(
        api.create_study(
            contract_b["id"],
            create_study_payload(title="Secondary Study", research_question="Exploratory"),
            PI,
        ),
        201,
    )
    validate_success(
        api.terminate_contract(contract_b["id"], terminate_contract_payload("Agency descope"), AO),
        200,
    )

    contract_b = get_contract(contract_b["id"])
    assert contract_b["status"] == "TERMINATED"
    assert contract_b["disbursed_cents"] == 0
    assert contract_b["forfeited_cents"] == 50000000
    assert contract_b["remaining_cents"] == 0
    assert_contract_funds_invariant(contract_b)
    assert get_study(study_b["id"])["status"] == "TERMINATED"

    contract_a = get_contract(contract_a["id"])
    assert contract_a["disbursed_cents"] == 30000000
    assert contract_a["remaining_cents"] == 60000000
    assert_contract_funds_invariant(contract_a)
