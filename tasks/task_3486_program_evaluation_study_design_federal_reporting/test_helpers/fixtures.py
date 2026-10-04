"""Composite setup helpers.

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch via PRD-declared endpoints. Setup calls use the
lenient get_success_data validator so failures surface as clear "Setup step
failed" errors.

Canonical chain (shared by most recipes):
  contract -> study -> site(s) walked to RECRUITED -> design plan (OCC create
  -> submit -> agency APPROVED; auto-LOCKED because a site is RECRUITED, which
  advances the study DESIGN -> RECRUITMENT) -> IRB protocol approved with the
  default 2026-09-01..2027-09-01 window -> site activated -> participants
  consented -> analysis plan registered BEFORE any wave closes -> waves opened
  with the clock set inside their window -> records -> report lifecycle ->
  restricted-use file -> dissemination -> study completion -> contract closeout.

Identity threading: consent/self-withdraw/self-read calls always use
make_participant_headers(participant["id"]); opaque roles use the shared
TEST_USERS constants (pi-1 submits, irb-1/peer-1/ao-1 decide, dm-1 prepares).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_WITHIN_WAVE,
    IRB_APPROVAL_END,
    IRB_APPROVAL_START,
    MAX_TOTAL_BURDEN_MINUTES,
    WAVE_CLOSE_AT,
    WAVE_OPEN_AT,
)
from .factories import (
    amend_analysis_plan_payload,
    consent_payload,
    create_analysis_plan_payload,
    create_contract_payload,
    create_design_plan_payload,
    create_dissemination_activity_payload,
    create_irb_protocol_payload,
    create_participant_payload,
    create_record_payload,
    create_report_payload,
    create_restricted_use_file_payload,
    create_site_payload,
    create_study_payload,
    create_wave_payload,
    design_plan_decision_payload,
    irb_decision_payload,
    report_decision_payload,
    ruf_review_decision_payload,
    set_clock_payload,
    site_outreach_payload,
)
from .test_users import TEST_USERS, make_participant_headers

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
DM = TEST_USERS["data_manager_headers"]
IRB = TEST_USERS["irb_reviewer_headers"]
PEER = TEST_USERS["peer_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: platform clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (endpoint is outside /evaluation)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: contract / study / site pipeline
# ---------------------------------------------------------------------------

def setup_contract(**overrides) -> dict:
    """Award a contract (starts ACTIVE). Returns the contract."""
    resp = api_client.create_contract(create_contract_payload(**overrides), AO)
    return get_success_data(resp)


def setup_contract_with_study(contract_overrides=None, **study_overrides) -> dict:
    """Contract + study (DESIGN, all counters 0, UNASSESSED)."""
    contract = setup_contract(**(contract_overrides or {}))
    resp = api_client.create_study(contract["id"], create_study_payload(**study_overrides), PI)
    study = get_success_data(resp)
    return {"contract": contract, "study": study}


def get_study(study_id: str) -> dict:
    """Fresh read of a study (also the way to obtain its OCC version)."""
    return get_success_data(api_client.get_study(study_id, PI))


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, AO))


def get_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, PI))


def get_wave(wave_id: str) -> dict:
    return get_success_data(api_client.get_wave(wave_id, DM))


def add_site(study_id: str, name="Site A", max_participants=250, target_state="PROSPECTED") -> dict:
    """Create a site and walk it to PROSPECTED, CONTACTED, DECLINED, or RECRUITED.

    ACTIVE is intentionally not handled here — activation needs a LOCKED plan
    and live IRB coverage, provided by setup_active_site_study.
    """
    site = get_success_data(
        api_client.create_site(study_id, create_site_payload(name=name, max_participants=max_participants), SD)
    )
    if target_state == "PROSPECTED":
        return site
    if target_state in ("CONTACTED", "RECRUITED", "DECLINED"):
        outcome = "DECLINED" if target_state == "DECLINED" else "CONTACTED"
        site = get_success_data(api_client.site_outreach(site["id"], site_outreach_payload(outcome), SD))
        if target_state == "RECRUITED":
            site = get_success_data(api_client.sign_mou(site["id"], SD))
        return site
    raise ValueError(f"unsupported site target_state {target_state!r}")


def setup_study_with_sites(site_specs=((250, "RECRUITED"),), **kwargs) -> dict:
    """Contract + study + sites walked per (max_participants, target_state) specs.

    Default: one RECRUITED site of capacity 250 (covers the default plan's
    required_total_n of 214 so the feasibility gate passes at submit).
    """
    ctx = setup_contract_with_study(**kwargs)
    ctx["sites"] = [
        add_site(ctx["study"]["id"], name=f"Site {chr(65 + i)}", max_participants=cap, target_state=state)
        for i, (cap, state) in enumerate(site_specs)
    ]
    ctx["site"] = ctx["sites"][0]
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: design plan lifecycle (OCC-guarded create; revision loop)
# ---------------------------------------------------------------------------

def create_design_plan(study_id: str, expected_study_version=None, **overrides) -> dict:
    """Create a DRAFT design plan. Fetches the study version when not given."""
    if expected_study_version is None:
        expected_study_version = get_study(study_id)["version"]
    resp = api_client.create_design_plan(
        study_id,
        create_design_plan_payload(expected_study_version=expected_study_version, **overrides),
        PI,
    )
    return get_success_data(resp)


def setup_study_with_locked_plan(site_specs=((250, "RECRUITED"),), plan_overrides=None, **kwargs) -> dict:
    """Sites per specs + plan created/submitted/APPROVED.

    Because a RECRUITED site exists at approval time, the plan auto-locks to
    LOCKED in the same request and the study advances DESIGN -> RECRUITMENT.
    Returns ctx with keys: contract, study (re-read, RECRUITMENT), sites, site, plan.
    """
    ctx = setup_study_with_sites(site_specs=site_specs, **kwargs)
    plan = create_design_plan(ctx["study"]["id"], **(plan_overrides or {}))
    plan = get_success_data(api_client.submit_design_plan(plan["id"], PI))
    plan = get_success_data(
        api_client.design_plan_agency_decision(plan["id"], design_plan_decision_payload("APPROVED"), AO)
    )
    ctx["plan"] = plan
    ctx["study"] = get_study(ctx["study"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: IRB approval and site activation
# ---------------------------------------------------------------------------

def approve_irb_protocol(study_id: str, with_modifications_cycle=False,
                         approval_start=IRB_APPROVAL_START, approval_end=IRB_APPROVAL_END,
                         estimated_burden_minutes=300) -> dict:
    """Create + submit + approve an IRB protocol. pi-1 submits, irb-1 decides
    (segregation of duties). with_modifications_cycle=True routes through a
    MODIFICATIONS_REQUIRED decision first, so consent_form_version ends at 2."""
    irb = get_success_data(
        api_client.create_irb_protocol(
            study_id, create_irb_protocol_payload(estimated_burden_minutes=estimated_burden_minutes), PI)
    )
    irb = get_success_data(api_client.submit_irb_protocol(irb["id"], PI))
    if with_modifications_cycle:
        irb = get_success_data(
            api_client.irb_decision(irb["id"], irb_decision_payload("MODIFICATIONS_REQUIRED"), IRB))
        irb = get_success_data(api_client.submit_irb_protocol(irb["id"], PI))
    irb = get_success_data(
        api_client.irb_decision(
            irb["id"],
            irb_decision_payload("APPROVED", approval_start=approval_start, approval_end=approval_end),
            IRB,
        )
    )
    return irb


def setup_active_site_study(site_capacity=250, site_specs=None, activate_index=0,
                            with_modifications_cycle=False,
                            irb_overrides=None, **kwargs) -> dict:
    """Full human-subjects-ready chain: LOCKED plan + APPROVED IRB covering the
    default clock + site walked to ACTIVE. Study is in RECRUITMENT.
    Pass site_specs (e.g. ((2, "RECRUITED"), (300, "CONTACTED"), ...)) when a
    small-capacity ACTIVE site still needs pipeline yield from other sites to
    clear the feasibility gate. ctx['site'] is the activated site.
    Returns ctx: contract, study, sites, site, plan, irb."""
    if site_specs is None:
        site_specs = ((site_capacity, "RECRUITED"),)
    ctx = setup_study_with_locked_plan(site_specs=site_specs, **kwargs)
    ctx["irb"] = approve_irb_protocol(
        ctx["study"]["id"],
        with_modifications_cycle=with_modifications_cycle,
        **(irb_overrides or {}),
    )
    target = ctx["sites"][activate_index]
    target = get_success_data(api_client.activate_site(target["id"], SD))
    ctx["sites"][activate_index] = target
    ctx["site"] = target
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: participants (consent is self-service; ownership-threaded headers)
# ---------------------------------------------------------------------------

def add_participant(site_id: str, external_ref="P001", consent=False,
                    consent_form_version=None, randomize=False) -> dict:
    """Identify a participant; optionally consent (as the participant themself)
    and randomize (as the PI). consent_form_version defaults to the value the
    active-site fixture's IRB approval produced (1, or 2 after a modifications
    cycle) — pass explicitly whenever the fixture used one."""
    p = get_success_data(
        api_client.create_participant(site_id, create_participant_payload(external_ref=external_ref), SD)
    )
    if consent:
        version = 1 if consent_form_version is None else consent_form_version
        p = get_success_data(
            api_client.consent_participant(
                p["id"], consent_payload(version), make_participant_headers(p["id"]))
        )
    if randomize:
        p = get_success_data(api_client.randomize_participant(p["id"], PI))
    return p


# ---------------------------------------------------------------------------
# Tier 5: waves and response records (clock set inside the wave window)
# ---------------------------------------------------------------------------

def create_wave(study_id: str, wave_type="SURVEY", site_id=None,
                open_at=WAVE_OPEN_AT, close_at=WAVE_CLOSE_AT) -> dict:
    """Plan a wave (PLANNED). site_id only for SITE_VISIT waves."""
    payload = create_wave_payload(wave_type=wave_type, open_at=open_at, close_at=close_at)
    if site_id is not None:
        payload["site_id"] = site_id
    return get_success_data(api_client.create_wave(study_id, payload, DM))


def open_wave(wave_id: str, clock=CLOCK_WITHIN_WAVE) -> dict:
    """Set the logical clock inside the wave window, then open the wave."""
    set_clock(clock)
    return get_success_data(api_client.open_wave(wave_id, DM))


def setup_open_wave(ctx: dict, wave_type="SURVEY", site_id=None,
                   open_at=WAVE_OPEN_AT, close_at=WAVE_CLOSE_AT,
                   clock=CLOCK_WITHIN_WAVE) -> dict:
    """Create + open a wave; the study must be RECRUITMENT or DATA_COLLECTION.
    First OPEN wave advances the study RECRUITMENT -> DATA_COLLECTION."""
    wave = create_wave(ctx["study"]["id"], wave_type=wave_type, site_id=site_id,
                       open_at=open_at, close_at=close_at)
    return open_wave(wave["id"], clock=clock)


def add_record(wave_id: str, participant_id: str, instrument_minutes=45,
               payload_ref="payload-1") -> dict:
    """Add a RECEIVED record to an OPEN wave."""
    return get_success_data(
        api_client.create_record(
            wave_id,
            create_record_payload(participant_id, instrument_minutes=instrument_minutes,
                                  payload_ref=payload_ref),
            DM,
        )
    )


# ---------------------------------------------------------------------------
# Tier 6: analysis plan (register BEFORE any wave reaches CLOSED/LINKED)
# ---------------------------------------------------------------------------

def setup_registered_analysis_plan(ctx: dict, primary_outcomes=None,
                                   secondary_outcomes=None) -> dict:
    """Create + preregister an analysis plan. Must be called while no wave of
    the study is CLOSED or LINKED yet. Returns the PREREGISTERED plan."""
    payload = create_analysis_plan_payload()
    if primary_outcomes is not None:
        payload["primary_outcomes"] = primary_outcomes
    if secondary_outcomes is not None:
        payload["secondary_outcomes"] = secondary_outcomes
    plan = get_success_data(api_client.create_analysis_plan(ctx["study"]["id"], payload, PI))
    return get_success_data(api_client.register_analysis_plan(plan["id"], PI))


# ---------------------------------------------------------------------------
# Tier 7: full data-collection and reporting lifecycles
# ---------------------------------------------------------------------------

def setup_study_in_analysis(**kwargs) -> dict:
    """Active-site chain + registered analysis plan + one SURVEY wave opened
    and closed (clock inside its window) -> study ANALYSIS.
    ctx keys: contract, study, sites, site, plan, irb, analysis_plan, wave."""
    ctx = setup_active_site_study(**kwargs)
    ctx["analysis_plan"] = setup_registered_analysis_plan(ctx)
    wave = create_wave(ctx["study"]["id"])
    ctx["wave"] = open_wave(wave["id"])
    ctx["wave"] = get_success_data(api_client.close_wave(ctx["wave"]["id"], DM))
    ctx["study"] = get_study(ctx["study"]["id"])
    return ctx


def create_report(study_id: str, **overrides) -> dict:
    """Draft a report (study ANALYSIS -> REPORTING on first creation)."""
    return get_success_data(api_client.create_report(study_id, create_report_payload(**overrides), PI))


def setup_study_with_draft_report(report_overrides=None, **kwargs) -> dict:
    """Study in REPORTING with a DRAFT report. Adds ctx['report']."""
    ctx = setup_study_in_analysis(**kwargs)
    ctx["report"] = create_report(ctx["study"]["id"], **(report_overrides or {}))
    ctx["study"] = get_study(ctx["study"]["id"])
    return ctx


def setup_submitted_report(**kwargs) -> dict:
    """Report SUBMITTED (pi-1 submits; submitted_at/peer_review_due stamped)."""
    ctx = setup_study_with_draft_report(**kwargs)
    ctx["report"] = get_success_data(api_client.submit_report(ctx["report"]["id"], PI))
    return ctx


def setup_peer_reviewed_report(**kwargs) -> dict:
    """Report PEER_REVIEWED (peer-1 reviews; != submitter pi-1)."""
    ctx = setup_submitted_report(**kwargs)
    ctx["report"] = get_success_data(api_client.review_report(ctx["report"]["id"], PEER))
    return ctx


def setup_report_in_revision(**kwargs) -> dict:
    """Report in REVISION: agency REVISION_REQUIRED at the current clock, so
    revision_due == clock-now + 60 days and revision_count == 1."""
    ctx = setup_peer_reviewed_report(**kwargs)
    ctx["report"] = get_success_data(
        api_client.report_agency_decision(ctx["report"]["id"], report_decision_payload("REVISION_REQUIRED"), AO)
    )
    return ctx


def setup_accepted_report(**kwargs) -> dict:
    """Report ACCEPTED (accepted_at stamped; publication_due = +90 days)."""
    ctx = setup_peer_reviewed_report(**kwargs)
    ctx["report"] = get_success_data(
        api_client.report_agency_decision(ctx["report"]["id"], report_decision_payload("ACCEPTED"), AO)
    )
    return ctx


def setup_published_report(**kwargs) -> dict:
    """Report PUBLISHED; milestone disbursed; study REPORTING -> DISSEMINATION."""
    ctx = setup_accepted_report(**kwargs)
    ctx["report"] = get_success_data(api_client.publish_report(ctx["report"]["id"], AO))
    ctx["study"] = get_study(ctx["study"]["id"])
    ctx["contract"] = get_contract(ctx["contract"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 8: dissemination and study completion
# ---------------------------------------------------------------------------

def setup_completed_study(**kwargs) -> dict:
    """Published FINAL report + one COMPLETED dissemination activity. With the
    default deliverable_report_count of 1 the study reaches COMPLETED and its
    ACTIVE site cascades to COMPLETED. Adds ctx['activity']."""
    ctx = setup_published_report(**kwargs)
    activity = get_success_data(
        api_client.create_dissemination_activity(
            ctx["study"]["id"], create_dissemination_activity_payload(), PI)
    )
    ctx["activity"] = get_success_data(
        api_client.complete_dissemination_activity(activity["id"], PI))
    ctx["study"] = get_study(ctx["study"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 9: restricted-use files (require a PUBLISHED report on the study)
# ---------------------------------------------------------------------------

def create_restricted_use_file(study_id: str, **overrides) -> dict:
    """Prepare a DRAFT restricted-use file (dm-1 recorded as preparer)."""
    return get_success_data(
        api_client.create_restricted_use_file(
            study_id, create_restricted_use_file_payload(**overrides), DM)
    )


def setup_ruf_in_review(ruf_overrides=None, **kwargs) -> dict:
    """Study DISSEMINATION + file moved DRAFT -> DISCLOSURE_REVIEW, so
    suppressed_cell_count/max_risk/mean_risk are computed. Adds ctx['ruf']."""
    ctx = setup_published_report(**kwargs)
    ctx["ruf"] = create_restricted_use_file(ctx["study"]["id"], **(ruf_overrides or {}))
    ctx["ruf"] = get_success_data(api_client.submit_ruf_review(ctx["ruf"]["id"], DM))
    return ctx


def setup_released_ruf(**kwargs) -> dict:
    """File RELEASED (ao-1 decides; != preparer dm-1; default cell structure
    has max_risk exactly 0.20 which passes the gate)."""
    ctx = setup_ruf_in_review(**kwargs)
    ctx["ruf"] = get_success_data(
        api_client.ruf_review_decision(ctx["ruf"]["id"], ruf_review_decision_payload("APPROVE"), AO)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 10: PRD worked-example scenarios (literals match the PRD illustrations)
# ---------------------------------------------------------------------------

def add_consented_participants(site_id: str, count: int, consent_form_version=1,
                               ref_prefix="P") -> list:
    """Identify + consent N participants at an ACTIVE site (each consents as
    themself). Deterministic-allocation tests then randomize them in order."""
    return [
        add_participant(site_id, external_ref=f"{ref_prefix}{i:03d}",
                        consent=True, consent_form_version=consent_form_version)
        for i in range(1, count + 1)
    ]


def setup_pipeline_projection_scenario() -> dict:
    """PRD feasibility illustration: site A RECRUITED capacity 60 plus sites B
    and C CONTACTED capacity 300 each -> committed_projected_n 60 and
    pipeline_projected_n 270 (60 + 105 + 105). A DRAFT RCT plan with the
    worked-example parameters (required_total_n 214) makes the study ADEQUATE;
    withdrawing site A drops the pipeline to 210 (UNDERPOWERED)."""
    ctx = setup_study_with_sites(
        site_specs=((60, "RECRUITED"), (300, "CONTACTED"), (300, "CONTACTED"))
    )
    ctx["plan"] = create_design_plan(ctx["study"]["id"])
    ctx["study"] = get_study(ctx["study"]["id"])
    return ctx


def setup_burden_rounding_scenario(site_capacity=250) -> dict:
    """PRD burden illustration setup: ACTIVE site with consented participant
    P1, an OPEN SITE_VISIT wave and an OPEN SURVEY wave (windows
    2026-10-01..2026-11-01, clock set to 2026-10-15). Two 45-minute SITE_VISIT
    records plus one 45-minute SURVEY record bill 56+56+45 = 157 (per-record
    round-half-up; the rejected sum-first order would give 158).
    Adds ctx keys: participant, wave_visit, wave_survey."""
    ctx = setup_active_site_study(site_capacity=site_capacity)
    ctx["participant"] = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)
    ctx["wave_visit"] = setup_open_wave(ctx, wave_type="SITE_VISIT", site_id=ctx["site"]["id"])
    ctx["wave_survey"] = setup_open_wave(ctx, wave_type="SURVEY")
    return ctx


def setup_participant_at_burden_cap(site_capacity=250) -> dict:
    """Participant CONSENTED at an ACTIVE site with burden_total_minutes exactly
    MAX_TOTAL_BURDEN_MINUTES (480): one SITE_VISIT record of 384 raw minutes
    bills round_half_up(384 * 1.25) = 480, landing exactly on the cap (allowed).
    The visit wave stays OPEN; ctx keys: participant, wave_visit, record."""
    ctx = setup_active_site_study(site_capacity=site_capacity)
    ctx["participant"] = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)
    ctx["wave_visit"] = setup_open_wave(ctx, wave_type="SITE_VISIT", site_id=ctx["site"]["id"])
    ctx["record"] = add_record(
        ctx["wave_visit"]["id"], ctx["participant"]["id"],
        instrument_minutes=int(MAX_TOTAL_BURDEN_MINUTES / 1.25),  # 384 -> 480 billed
    )
    ctx["participant"] = get_participant(ctx["participant"]["id"])
    return ctx


def setup_worked_disclosure_risk_scenario() -> dict:
    """PRD disclosure illustration: published report + file with cell_counts
    [5, 4, 12, 30] and weights [1.0, 1.0, 0.5, 0.5] moved to DISCLOSURE_REVIEW.
    The cell of 4 is suppressed; max_risk 0.20 (exactly the gate, passes) and
    mean_risk 0.0426. Equivalent to setup_ruf_in_review() defaults."""
    return setup_ruf_in_review()
