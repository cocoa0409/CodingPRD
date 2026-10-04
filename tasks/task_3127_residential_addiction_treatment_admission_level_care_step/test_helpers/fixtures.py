"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls go
through the lenient validator so a broken precondition reports itself as a setup
failure instead of a confusing assertion failure.

The helpers are layered:

  * Tier 1 — a licensed, accredited site (:func:`setup_site`).
  * Tier 2 — an episode placed by an assessment and holding an approved
    authorization (:func:`setup_claimed_episode`).
  * Tier 3 — an admitted, in-treatment episode with a signed plan
    (:func:`setup_admitted_episode`).
  * Tier 4 — an episode already carrying accumulated days and attendance
    (:func:`setup_accumulated_episode`, :func:`setup_curriculum_episode`).
"""

from prd_bench_local_runner.testing import get_success_data

from datetime import datetime, timedelta

from . import constants as C
from . import factories
from .api_client import api_client
from .test_users import (
    ALUMNI_COORDINATOR_HEADERS,
    CLINICAL_DIRECTOR_HEADERS,
    INTAKE_NURSE_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    READ_HEADERS,
    UTILIZATION_REVIEWER_HEADERS,
    make_clinician_headers,
)


# ---------------------------------------------------------------- read helpers

def read_facility(facility_id, headers=None) -> dict:
    return get_success_data(api_client.get_facility(facility_id, headers or READ_HEADERS))


def read_episode(episode_id, headers=None) -> dict:
    return get_success_data(api_client.get_episode(episode_id, headers or READ_HEADERS))


def read_authorization(authorization_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_authorization(authorization_id, headers or READ_HEADERS)
    )


def read_assessment(facility_id, episode_id, assessment_id, headers=None) -> dict:
    """Assessments have no single read, so the nested list is filtered by id."""
    rows, _ = list_episode_assessments(facility_id, episode_id)
    for row in rows:
        if row["id"] == assessment_id:
            return row
    raise AssertionError(f"assessment {assessment_id} not returned by the episode's list")


def read_plan(plan_id, headers=None) -> dict:
    return get_success_data(api_client.get_treatment_plan(plan_id, headers or READ_HEADERS))


def read_change(change_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_level_of_care_change(change_id, headers or READ_HEADERS)
    )


def read_session(session_id, headers=None) -> dict:
    return get_success_data(api_client.get_session(session_id, headers or READ_HEADERS))


def read_accreditation(accreditation_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_accreditation(accreditation_id, headers or READ_HEADERS)
    )


def read_housing(housing_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_recovery_housing(housing_id, headers or READ_HEADERS)
    )


def read_clearance(facility_id, episode_id, clearance_id, headers=None) -> dict:
    rows, _ = list_episode_clearances(facility_id, episode_id)
    for row in rows:
        if row["id"] == clearance_id:
            return row
    raise AssertionError(f"clearance {clearance_id} not returned by the episode's list")


def read_withdrawal(facility_id, episode_id, plan_id, headers=None) -> dict:
    rows, _ = list_episode_withdrawal(facility_id, episode_id)
    for row in rows:
        if row["id"] == plan_id:
            return row
    raise AssertionError(f"withdrawal record {plan_id} not returned by the episode's list")


def list_page(response) -> tuple:
    """Return (rows, meta) from a 200 list response during setup."""
    body = response.json()
    assert response.status_code == 200, (
        f"Setup list call failed with HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]


def list_episodes(facility_id, **params) -> tuple:
    return list_page(
        api_client.list_episodes(
            facility_id, READ_HEADERS, params=params or None
        )
    )


def list_accreditations(facility_id, **params) -> tuple:
    return list_page(
        api_client.list_accreditations(facility_id, READ_HEADERS, params=params or None)
    )


def list_beds(facility_id, **params) -> tuple:
    return list_page(api_client.list_beds(facility_id, READ_HEADERS, params=params or None))


def list_episode_assessments(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_assessments(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def list_episode_authorizations(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_authorizations(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def list_episode_clearances(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_clearances(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def list_episode_withdrawal(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_withdrawal_management(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def list_episode_sessions(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_sessions(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def list_episode_changes(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_level_of_care_changes(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def list_episode_contacts(facility_id, episode_id, **params) -> tuple:
    return list_page(
        api_client.list_episode_alumni_contacts(
            facility_id, episode_id, READ_HEADERS, params=params or None
        )
    )


def utilization_summary(episode_id, authorization_id=None, headers=None) -> dict:
    params = {"authorization_id": authorization_id} if authorization_id else None
    return get_success_data(
        api_client.get_utilization_summary(episode_id, headers or READ_HEADERS, params=params)
    )


# ------------------------------------------------------------------ primitives

def set_clock(current_utc=C.CLOCK_2026_09_01) -> dict:
    """Move the network's single logical clock (PRD §2.11)."""
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, PLATFORM_ADMIN_HEADERS)
    )


def create_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(factories.facility_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def grant_accreditation(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_accreditation(
            facility_id, factories.accreditation_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def grant_state_license(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_accreditation(
            facility_id, factories.state_license_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_bed(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bed(facility_id, factories.bed_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_service(facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_offering(
            facility_id, factories.service_offering_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_clinician(**overrides) -> dict:
    return get_success_data(
        api_client.create_clinician(factories.clinician_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def grant_facility_credential(clinician_id, facility_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_clinician_facility_credential(
            clinician_id,
            factories.facility_credential_payload(facility_id, **overrides),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def create_payer(**overrides) -> dict:
    return get_success_data(
        api_client.create_payer(factories.payer_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def run_ops(facility_id, headers=None) -> dict:
    return get_success_data(
        api_client.run_facility_ops(facility_id, {}, headers or PLATFORM_ADMIN_HEADERS)
    )


def revoke_accreditation(facility_id, accreditation_id, headers=None) -> dict:
    return get_success_data(
        api_client.revoke_accreditation(
            facility_id, accreditation_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


# ------------------------------------------------------------------ tier 1: site

class Site:
    """A licensed, body-accredited Minnesota facility with its equipment roster."""

    def __init__(self, facility, beds, services, clinician, clinician_headers, payer, accreditations):
        self.facility = facility
        self.beds = beds
        self.services = services
        self.clinician = clinician
        self.clinician_headers = clinician_headers
        self.payer = payer
        self.accreditations = accreditations

    @property
    def id(self):
        return self.facility["id"]

    @property
    def bed_35(self):
        return self.beds["ASAM_3_5"]

    @property
    def bed_31(self):
        return self.beds["ASAM_3_1"]

    @property
    def bed_21(self):
        return self.beds["ASAM_2_1"]

    @property
    def service_35(self):
        return self.services["ASAM_3_5"]

    @property
    def service_31(self):
        return self.services["ASAM_3_1"]

    @property
    def body_accreditation_id(self):
        return self.accreditations["ACCREDITATION_BODY"]["id"]


def setup_site(
    clock=C.CLOCK_2026_09_01,
    name=C.FACILITY_NAME,
    state_code=C.FACILITY_STATE,
    license_level_max="ASAM_3_5",
    credential_tier_min="TIER_3_LICENSED",
    body_accreditation_expires_at=C.CREDENTIAL_EXPIRES_AT,
    extra_body_accreditations=(),
    with_beds=True,
    with_payer=True,
    clinician_tier="TIER_4_INDEPENDENT",
):
    """Clock + licensed MN facility + accredited body + beds + services + clinician + payer.

    This is the preamble shared by nearly every claim in the suite.
    """
    set_clock(clock)
    facility = create_facility(name=name, state_code=state_code)

    body = grant_accreditation(
        facility["id"],
        accreditation_class="ACCREDITATION_BODY",
        granting_body="CARF",
        expires_at=body_accreditation_expires_at,
    )
    # A facility may hold several accreditations of the same class from distinct granting
    # bodies (PRD §2.5), which is how the ledger's lapsed-row term is scaled.
    for extra_body in extra_body_accreditations:
        grant_accreditation(
            facility["id"],
            accreditation_class="ACCREDITATION_BODY",
            granting_body=extra_body,
            expires_at=body_accreditation_expires_at,
        )
    license_row = grant_state_license(
        facility["id"],
        license_level_max=license_level_max,
        credential_tier_min=credential_tier_min,
    )

    beds = {}
    services = {}
    if with_beds:
        # A step-down from the resident level lands on a bed at the *target* level, and
        # the appointment supplies that target as `bed_id`. The three bed labels differ
        # by construction, so each drawn target is a distinct row and no two claims share
        # a bed row — while MN-B-03 additionally carries a zero-hour turnaround, which is
        # what makes the zero-barrier adjacency case reachable.
        beds["ASAM_3_5"] = create_bed(
            facility["id"],
            bed_label=C.BED_LABEL_35,
            level_of_care="ASAM_3_5",
            cleaning_turnaround_hours=C.CLEANING_HOURS_35,
        )
        beds["ASAM_3_1"] = create_bed(
            facility["id"],
            bed_label=C.BED_LABEL_31,
            level_of_care="ASAM_3_1",
            cleaning_turnaround_hours=C.CLEANING_HOURS_31,
        )
        beds["ASAM_2_1"] = create_bed(
            facility["id"],
            bed_label=C.BED_LABEL_21,
            level_of_care="ASAM_2_1",
            cleaning_turnaround_hours=C.CLEANING_HOURS_21,
        )
        services["ASAM_3_5"] = create_service(
            facility["id"],
            service_code=C.SERVICE_CODE_RES,
            level_of_care="ASAM_3_5",
            required_min_credential_tier="TIER_3_LICENSED",
        )
        services["ASAM_3_1"] = create_service(
            facility["id"],
            service_code=C.SERVICE_CODE_IOP,
            level_of_care="ASAM_3_1",
            required_min_credential_tier="TIER_3_LICENSED",
        )

    clinician = create_clinician(credential_tier=clinician_tier, is_medical_provider=True)
    grant_facility_credential(clinician["id"], facility["id"])

    payer = create_payer() if with_payer else None

    return Site(
        facility=facility,
        beds=beds,
        services=services,
        clinician=clinician,
        clinician_headers=make_clinician_headers(clinician["id"]),
        payer=payer,
        accreditations={"ACCREDITATION_BODY": body, "STATE_LICENSE": license_row},
    )


def setup_bare_site(clock=C.CLOCK_2026_09_01, **overrides):
    """A facility with no beds, services or clinician — for creation-shape claims."""
    set_clock(clock)
    facility = create_facility(**overrides)
    return facility


# ------------------------------------------------------- tier 2: claimed episode

class ClaimedEpisode:
    """An episode placed by a completed assessment and holding a bed-held authorization."""

    def __init__(self, site, episode, assessment, authorizations, clearances=None):
        self.site = site
        self.episode = episode
        self.assessment = assessment
        self.authorizations = authorizations
        self.clearances = clearances or {}

    @property
    def id(self):
        return self.episode["id"]

    @property
    def facility_id(self):
        return self.site.id

    @property
    def auth(self):
        return self.authorizations[0]

    @property
    def auth_id(self):
        return self.authorizations[0]["id"]


def open_episode(site, patient_ref=C.PATIENT_REF, **overrides) -> dict:
    payload = factories.episode_payload(patient_ref=patient_ref, **overrides)
    return get_success_data(
        api_client.create_episode(site.id, payload, INTAKE_NURSE_HEADERS)
    )


def start_assessment(site, episode_id, scores=None, placement_basis=None, **overrides) -> dict:
    payload = factories.assessment_payload(
        site.clinician["id"], dimension_scores=dict(scores or C.SCORES_ASAM_3_5), **overrides
    )
    if placement_basis is not None:
        payload["placement_basis"] = placement_basis
    return get_success_data(
        api_client.create_assessment(site.id, episode_id, payload, INTAKE_NURSE_HEADERS)
    )


def complete_assessment(site, assessment_id) -> dict:
    return get_success_data(
        api_client.complete_assessment(
            site.id, assessment_id, {}, site.clinician_headers
        )
    )


def cancel_assessment(site, assessment_id, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_assessment(
            site.id, assessment_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def place_episode(site, episode_id, scores=None, placement_basis=None) -> tuple:
    """Open an assessment and complete it. Returns (assessment_completed, episode)."""
    assessment = start_assessment(site, episode_id, scores=scores, placement_basis=placement_basis)
    completed = complete_assessment(site, assessment["id"])
    return completed, read_episode(episode_id)


def request_authorization(
    site, episode_id, requested_level="ASAM_3_5", bed_id=None, payer_id=None
) -> dict:
    payload = factories.authorization_payload(
        payer_id or site.payer["id"], requested_level=requested_level
    )
    if bed_id is not None:
        payload["bed_id"] = bed_id
    return get_success_data(
        api_client.create_authorization(site.id, episode_id, payload, UTILIZATION_REVIEWER_HEADERS)
    )


def approve_authorization(site, authorization_id) -> dict:
    return get_success_data(
        api_client.approve_authorization(
            site.id, authorization_id, {}, UTILIZATION_REVIEWER_HEADERS
        )
    )


def deny_authorization(site, authorization_id) -> dict:
    return get_success_data(
        api_client.deny_authorization(
            site.id, authorization_id, {}, UTILIZATION_REVIEWER_HEADERS
        )
    )


def submit_concurrent_review(site, authorization_id) -> dict:
    return get_success_data(
        api_client.submit_concurrent_review(
            site.id, authorization_id, {}, UTILIZATION_REVIEWER_HEADERS
        )
    )


def order_clearance(site, episode_id, clearance_type="MEDICAL") -> dict:
    return get_success_data(
        api_client.create_clearance(
            site.id, episode_id, factories.clearance_payload(clearance_type), INTAKE_NURSE_HEADERS
        )
    )


def clear_clearance(site, clearance_id, headers=None) -> dict:
    return get_success_data(
        api_client.clear_clearance(site.id, clearance_id, {}, headers or site.clinician_headers)
    )


def order_and_clear(site, episode_id, clearance_type="MEDICAL") -> dict:
    row = order_clearance(site, episode_id, clearance_type)
    return clear_clearance(site, row["id"])


def author_withdrawal_management(site, episode_id, status=None, ciwa_score=12, **overrides) -> dict:
    payload = factories.withdrawal_management_payload(ciwa_score=ciwa_score, **overrides)
    row = get_success_data(
        api_client.create_withdrawal_management(
            site.id, episode_id, payload, site.clinician_headers
        )
    )
    if status is not None:
        row = update_withdrawal_status(site, row["id"], status)
    return row


def update_withdrawal_status(site, withdrawal_id, status) -> dict:
    return get_success_data(
        api_client.update_withdrawal_management(
            site.id, withdrawal_id, {"status": status}, site.clinician_headers
        )
    )


def draft_plan(site, episode_id, expected_version=None, **overrides) -> dict:
    if expected_version is None:
        expected_version = read_episode(episode_id)["version"]
    payload = factories.treatment_plan_payload(
        site.clinician["id"], expected_version, **overrides
    )
    return get_success_data(
        api_client.create_treatment_plan(site.id, episode_id, payload, site.clinician_headers)
    )


def submit_plan_for_cosign(site, plan_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_plan_for_cosign(
            site.id, plan_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def schedule_session(site, episode_id, service_id=None, scheduled_at=None, duration_minutes=60, **overrides):
    payload = factories.session_payload(
        service_id or site.service_35["id"],
        site.clinician["id"],
        scheduled_at or C.CLOCK_2026_09_02,
        duration_minutes=duration_minutes,
        **overrides,
    )
    return get_success_data(
        api_client.create_session(site.id, episode_id, payload, INTAKE_NURSE_HEADERS)
    )


def record_attendance(site, session_id, attended=True) -> dict:
    return get_success_data(
        api_client.record_attendance(
            site.id, session_id, {"attended": attended}, site.clinician_headers
        )
    )


def setup_claimed_episode(
    site=None,
    scores=None,
    requested_level="ASAM_3_5",
    hold_bed=True,
    admit=True,
    withdrawal_status="MEDICALLY_STABLE",
) -> ClaimedEpisode:
    """A placed, funded episode holding a bed — admitted by default.

    ``admit=False`` stops at the staging state and returns the same object shape, so
    a claim can exercise the admission gate's own precondition failures. The fully
    admitted form is what admits, schedules, changes and discharges all operate on.
    """
    if site is None:
        site = setup_site()
    episode = open_episode(site)
    assessment, _ = place_episode(site, episode["id"], scores=scores)

    bed = site.beds[requested_level] if hold_bed and requested_level in site.beds else None
    auth = request_authorization(
        site, episode["id"], requested_level=requested_level,
        bed_id=bed["id"] if bed else None,
    )

    # Clearances first: the approval's own promotion test reads every clearance, so
    # both must already be recorded for the episode to reach AWAITING_ADMISSION.
    clearances = {
        "MEDICAL": order_and_clear(site, episode["id"], "MEDICAL"),
        "TB_SCREEN": order_and_clear(site, episode["id"], "TB_SCREEN"),
    }
    auth = approve_authorization(site, auth["id"])

    if not admit:
        return ClaimedEpisode(site, read_episode(episode["id"]), assessment, [auth], clearances)

    withdrawal = author_withdrawal_management(site, episode["id"], ciwa_score=12)
    plan = draft_plan(site, episode["id"])
    plan = submit_plan_for_cosign(site, plan["id"])
    admitted = get_success_data(
        api_client.admit_episode(site.id, episode["id"], {}, INTAKE_NURSE_HEADERS)
    )
    # PRD §3.3 requires ACTIVE at the admission gate while PRD §3.7 requires
    # MEDICALLY_STABLE for completion and discharge, so the move happens after.
    if withdrawal_status is not None:
        withdrawal = update_withdrawal_status(site, withdrawal["id"], withdrawal_status)

    claim = ClaimedEpisode(site, admitted, assessment, [auth], clearances)
    claim.plan = plan
    claim.withdrawal = withdrawal
    claim.bed = bed
    return claim


def setup_staged_episode(
    site=None, scores=None, requested_level="ASAM_3_5", hold_bed=True,
) -> ClaimedEpisode:
    """A funded episode resting at ``AWAITING_ADMISSION`` — the admission gate's own state."""
    return setup_claimed_episode(
        site=site, scores=scores, requested_level=requested_level,
        hold_bed=hold_bed, admit=False,
    )


# ------------------------------------------------------- tier 3: admitted episode

class AdmittedEpisode:
    """An in-treatment episode with a signed plan, stable withdrawal and a bed."""

    def __init__(self, site, episode, assessment, authorization, plan, withdrawal,
                 clearances, bed):
        self.site = site
        self.episode = episode
        self.assessment = assessment
        self.authorization = authorization
        self.plan = plan
        self.withdrawal = withdrawal
        self.clearances = clearances
        self.bed = bed

    @property
    def id(self):
        return self.episode["id"]

    @property
    def facility_id(self):
        return self.site.id

    @property
    def auth_id(self):
        return self.authorization["id"]

    @property
    def plan_id(self):
        return self.plan["id"]

    @property
    def bed_id(self):
        return self.bed["id"] if self.bed else None

    def refresh(self):
        self.episode = read_episode(self.id)
        self.authorization = read_authorization(self.auth_id)
        self.plan = read_plan(self.plan_id)
        return self


def setup_admitted_episode(
    site=None,
    requested_level="ASAM_3_5",
    scores=None,
    admit_clock=None,
    withdrawal_status="MEDICALLY_STABLE",
    body_accreditation_expires_at=C.CREDENTIAL_EXPIRES_AT,
    burn_after_admission=None,
) -> AdmittedEpisode:
    """Full preamble through ``IN_TREATMENT``: site → claim → plan → clearances → admit."""
    if site is None:
        site = setup_site(body_accreditation_expires_at=body_accreditation_expires_at)

    episode = open_episode(site)
    assessment, _ = place_episode(site, episode["id"], scores=scores or C.SCORES_ASAM_3_5)

    bed = site.beds.get(requested_level)
    auth = request_authorization(
        site, episode["id"], requested_level=requested_level,
        bed_id=bed["id"] if bed else None,
    )

    # Clearances first: the approval's own promotion is gated on every clearance still
    # reading CLEARED, so both must already be recorded for the episode to reach
    # AWAITING_ADMISSION. The withdrawal-management record is then authored at that
    # state, followed by the treatment plan the admission gate also requires.
    clearances = {
        "MEDICAL": order_and_clear(site, episode["id"], "MEDICAL"),
        "TB_SCREEN": order_and_clear(site, episode["id"], "TB_SCREEN"),
    }
    auth = approve_authorization(site, auth["id"])

    withdrawal = author_withdrawal_management(site, episode["id"], ciwa_score=12)

    plan = draft_plan(site, episode["id"])
    plan = submit_plan_for_cosign(site, plan["id"])

    if admit_clock is not None:
        set_clock(admit_clock)
    admitted = get_success_data(
        api_client.admit_episode(site.id, episode["id"], {}, INTAKE_NURSE_HEADERS)
    )

    # PRD §3.3 requires the withdrawal-management record to read ACTIVE at the
    # admission gate, while PRD §3.7 requires MEDICALLY_STABLE for treatment
    # completion and discharge. The status move therefore has to happen *after*
    # admission, never before it, or the admission gate would correctly refuse.
    if withdrawal_status is not None:
        withdrawal = update_withdrawal_status(site, withdrawal["id"], withdrawal_status)

    # ``burn_after_admission`` moves the clock on and runs one facility-ops epoch once
    # the episode is IN_TREATMENT. The day-bank burn for the step-down pressure score
    # only advances once the episode is IN_TREATMENT (PRD §2.8), so a caller that wants
    # ``days_used`` off zero without disturbing the admission path asks for it here.
    if burn_after_admission is not None:
        set_clock(burn_after_admission)
        run_ops(site.id)

    return AdmittedEpisode(
        site=site,
        episode=admitted,
        assessment=assessment,
        authorization=auth,
        plan=plan,
        withdrawal=withdrawal,
        clearances=clearances,
        bed=bed,
    )


# ------------------------------------------------ tier 4: accumulation / boundary

def setup_accumulated_episode(
    site=None, requested_level="ASAM_3_5", admitted_at=C.CLOCK_2026_09_02,
    burn_clock=C.CLOCK_2026_09_08, burns=1, closes_interval=False,
    interval_burn_clock=C.CLOCK_2026_09_09,
) -> AdmittedEpisode:
    """Admit, move the clock forward and burn ``burns`` facility-ops epochs.

    Used by the day-bank boundary claims, which need an exact ``days_used``.

    ``closes_interval`` additionally burns the *last whole day* of the grant's
    concurrent-review interval. PRD §2.8 declares the posture rule over the whole
    interval — "a `days_remaining` at or below the payer's
    `concurrent_review_interval_days` makes the posture `CONCURRENT_REVIEW_DUE`" —
    while the grant for this payer is 14 days against a 7-day interval, so the only
    reachable review-due instant sits one whole day below the interval and the
    interval-wide reading cannot be observed without this extra burn.
    """
    if site is None:
        site = setup_site()
    setup = setup_admitted_episode(site=site, requested_level=requested_level, admit_clock=admitted_at)
    clock = burn_clock
    for _ in range(burns):
        set_clock(clock)
        run_ops(site.id)
    if closes_interval:
        set_clock(interval_burn_clock)
        run_ops(site.id)
    return setup.refresh()


def setup_curriculum_episode(
    site=None, attended_sessions=14, service_level="ASAM_3_5",
    admitted_at=C.CLOCK_2026_09_02,
    schedule_start=None, schedule_hours_per_day=None, clock=None,
) -> AdmittedEpisode:
    """Admit an episode and record exactly ``attended_sessions`` attended sessions.

    The sessions are spread across the treatment week containing the admission
    instant, so the aggregate can land exactly on the level's requirement.

    ``schedule_start`` and ``schedule_hours_per_day`` pin the spread. The defaults
    lay rows down from 2026-09-02 across at most 16 hours per calendar day, which
    keeps every row inside the admission week. A week whose logical now has been
    moved later (e.g. to burn the day bank for the step-down pressure score) needs a
    tighter spread so that rows past the week boundary do not fall out of the
    ``[admitted_at + 7n, admitted_at + 7(n+1))`` window the curriculum counts over.
    """
    setup = setup_admitted_episode(site=site, requested_level=service_level, admit_clock=admitted_at)
    site = setup.site
    service = site.services[service_level]
    if clock is not None:
        set_clock(clock)
    start = schedule_start or datetime(2026, 9, 2)
    hours_per_day = schedule_hours_per_day or 16
    for i in range(attended_sessions):
        hour = 6 + (i % hours_per_day)
        day_offset = i // hours_per_day
        scheduled_at = (start + timedelta(days=day_offset)).replace(
            hour=hour
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        session = schedule_session(
            site, setup.id, service_id=service["id"], scheduled_at=scheduled_at
        )
        record_attendance(site, session["id"], attended=True)
    setup.refresh()
    return setup


# ------------------------------------------------ tier 5: continuing care / discharge

def create_recovery_house(site, **overrides) -> dict:
    return get_success_data(
        api_client.create_recovery_housing(
            site.id, factories.recovery_housing_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def grant_recovery_house_license(site, expires_at=C.CREDENTIAL_EXPIRES_AT) -> dict:
    return grant_accreditation(
        site.id,
        accreditation_class="RECOVERY_HOUSE",
        granting_body="MN-HOUSING",
        expires_at=expires_at,
    )


def draft_continuing_care_plan(site, episode_id, expected_version=None, **overrides) -> dict:
    if expected_version is None:
        expected_version = read_episode(episode_id)["version"]
    payload = factories.continuing_care_plan_payload(
        site.clinician["id"], expected_version, **overrides
    )
    return get_success_data(
        api_client.create_continuing_care_plan(
            site.id, episode_id, payload, CLINICAL_DIRECTOR_HEADERS
        )
    )


def activate_continuing_care_plan(site, care_plan_id, headers=None) -> dict:
    return get_success_data(
        api_client.activate_continuing_care_plan(
            site.id, care_plan_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def setup_discharge_ready_episode(
    site=None, attended_sessions=14, house_kwargs=None, clock=None,
) -> AdmittedEpisode:
    """An admitted ASAM_3_5 episode with a licensed house and an ACTIVE continuing-care plan."""
    site = site or setup_site()
    grant_recovery_house_license(site)
    create_recovery_house(site, **(house_kwargs or {"capacity_beds": 4}))
    setup = setup_curriculum_episode(
        site=site, attended_sessions=attended_sessions, clock="2026-09-02T00:00:00Z"
    )
    if clock is not None:
        set_clock(clock)
    plan = draft_continuing_care_plan(site, setup.id)
    activate_continuing_care_plan(site, plan["id"])
    setup.refresh()
    return setup


def complete_treatment(site, episode_id, headers=None) -> dict:
    return get_success_data(
        api_client.complete_treatment(
            site.id, episode_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def discharge_episode(site, episode_id, headers=None) -> dict:
    return get_success_data(
        api_client.discharge_episode(
            site.id, episode_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


# ------------------------------------------------------------------ level changes

def appoint_level_change(
    site, episode_id, authorization_id, to_level, effective_at,
    bed_id=None, expected_version=None, headers=None,
) -> dict:
    if expected_version is None:
        expected_version = read_episode(episode_id)["version"]
    payload = factories.level_of_care_change_payload(
        authorization_id, to_level, effective_at, expected_version
    )
    if bed_id is not None:
        payload["bed_id"] = bed_id
    return get_success_data(
        api_client.create_level_of_care_change(
            site.id, episode_id, payload, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def complete_level_change(site, change_id, headers=None) -> dict:
    return get_success_data(
        api_client.complete_level_of_care_change(
            site.id, change_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def cancel_level_change(site, change_id, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_level_of_care_change(
            site.id, change_id, {}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def step_up_level_change(site, change_id, bed_id, headers=None) -> dict:
    return get_success_data(
        api_client.step_up_level_of_care_change(
            site.id, change_id, {"bed_id": bed_id}, headers or CLINICAL_DIRECTOR_HEADERS
        )
    )


def fund_step_down_authorization(
    site, setup, to_level, burn_clock=C.CLOCK_2026_09_09, bed_id=None, approve=True,
    second_burn_clock=C.CLOCK_2026_09_10,
):
    """Fund ``to_level`` with an authorization burnt enough to fund a step-down.

    PRD §3.6 refuses a step-down whose authorization has ``days_used`` of exactly 0
    (``ERR_AUTHORIZATION_UNUSED``), and PRD §2.8 only burns days inside the episode's
    ``IN_TREATMENT`` period, so the clock must be moved a whole day past the last ops
    instant before the funding authorization can qualify. If the first ops run opens
    and closes its burn window in the same instant — which happens when the grant is
    approved at the very instant the run reads — a further day and a further run are
    burned so ``days_used`` is strictly greater than 0.
    """
    target = request_authorization(site, setup.id, requested_level=to_level, bed_id=bed_id)
    if approve:
        target = approve_authorization(site, target["id"])
    set_clock(burn_clock)
    run_ops(site.id)
    setup.refresh()
    target = read_authorization(target["id"])
    if approve and target["days_used"] <= 0:
        set_clock(second_burn_clock)
        run_ops(site.id)
        setup.refresh()
        target = read_authorization(target["id"])
    if approve and target["posture"] != "APPROVED":
        # PRD §2.8 re-derives the posture on every ops run, so a grant funded for only
        # 8 days reads CONCURRENT_REVIEW_DUE as soon as the burn lands. A concurrent
        # review extends the grant and restores APPROVED, which is what the completion
        # branch's gate requires.
        target = submit_concurrent_review(site, target["id"])
    setup.target_authorization = target
    return target


def setup_non_residential_stepdown(
    site=None, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08,
    to_level="ASAM_2_1", effective_at=C.CLOCK_2026_09_09,
    funding_burn_clock=C.CLOCK_2026_09_09,
):
    """An admitted ASAM_3_5 episode holding a completed non-residential step-down.

    PRD §3.6's first completion branch covers a change that is "not a step-down onto
    a bed — either its `to_level` is `ASAM_1_0` or `ASAM_2_1`, or no `bed_id` was
    supplied"; it passes through ``PENDING_DISCHARGE_ORDER`` and reaches
    ``COMPLETED`` once the funding authorization is approved. That transition does
    not allocate a target bed, so the source bed stays ``OCCUPIED`` and the
    committed-bed-night count is the conserved quantity under test — the same
    invariant that the second, bed-allocating branch expresses by dropping the
    count by one.
    """
    site = site or setup_site()
    setup = setup_accumulated_episode(
        site=site, requested_level="ASAM_3_5", admitted_at=admitted_at, burn_clock=burn_clock
    )

    target_auth = fund_step_down_authorization(
        site, setup, to_level, burn_clock=funding_burn_clock, bed_id=None
    )
    change = appoint_level_change(
        site, setup.id, target_auth["id"], to_level=to_level, effective_at=effective_at,
        bed_id=None,
    )
    change = complete_level_change(site, change["id"])
    setup.refresh()
    setup.change = change
    setup.target_authorization = target_auth
    return setup


# ------------------------------------------------------------------ alumni

def file_ad_hoc_contact(site, episode_id, scheduled_for, attempt_number) -> dict:
    return get_success_data(
        api_client.create_alumni_contact(
            site.id,
            episode_id,
            factories.alumni_contact_payload(scheduled_for, attempt_number),
            ALUMNI_COORDINATOR_HEADERS,
        )
    )


def record_alumni_outcome(site, contact_id, outcome="REACHED", abstinent=True, headers=None) -> dict:
    payload = {"outcome": outcome}
    if outcome == "REACHED":
        payload["abstinent_at_contact"] = abstinent
    return get_success_data(
        api_client.record_alumni_outcome(
            site.id, contact_id, payload, headers or ALUMNI_COORDINATOR_HEADERS
        )
    )


# ------------------------------------------------- cascades and ops-ledger claims

def setup_cascade_site(
    clock=C.CLOCK_2026_09_15,
    body_accreditation_expires_at=C.CLOCK_2026_09_15,
):
    """A licensed MN site whose ACCREDITATION_BODY lapses at ``clock``.

    Expiring the body accreditation also trips the missing-class term, so the
    compliance score moves and the ops cycle's FROZEN-response stage fires.
    """
    return setup_site(
        clock=clock,
        body_accreditation_expires_at=body_accreditation_expires_at,
    )


def admit_episode(site, episode_id, headers=None) -> dict:
    return get_success_data(
        api_client.admit_episode(
            site.id, episode_id, {}, headers or INTAKE_NURSE_HEADERS
        )
    )


def setup_cascade_episode(
    site=None,
    admit_clock=C.CLOCK_2026_09_02,
    first_run_clock=C.CLOCK_2026_09_08,
    body_accreditation_expires_at=C.CLOCK_2026_09_15,
    future_session_times=("2026-09-16T09:00:00Z", "2026-09-17T09:00:00Z"),
    second_run_clock=None,
):
    """An admitted ASAM_3_5 episode whose site's body accreditation lapses later.

    One ops epoch is already burnt (moving ``days_used`` off zero), and any
    ``future_session_times`` are scheduled beyond the lapse so the FROZEN-response
    stage can rewrite them.
    """
    site = site or setup_cascade_site(
        clock=admit_clock, body_accreditation_expires_at=body_accreditation_expires_at
    )
    setup = setup_admitted_episode(
        site=site,
        requested_level="ASAM_3_5",
        admit_clock=admit_clock,
        body_accreditation_expires_at=body_accreditation_expires_at,
    )

    sessions = [
        schedule_session(site, setup.id, scheduled_at=t) for t in future_session_times
    ]

    set_clock(first_run_clock)
    run_ops(site.id)
    if second_run_clock is not None:
        # A second burn carries the day bank to the edge of the 14-day grant before
        # the run that lands on the expiry instant, so that run finds the
        # authorization exactly exhausted rather than one day short of it.
        set_clock(second_run_clock)
        run_ops(site.id)
    return setup.refresh(), sessions


def setup_exhausted_episode(
    site=None,
    admit_clock=C.CLOCK_2026_09_01,
    granted_level="ASAM_3_1",
    payer_grant_days=0,
):
    """An episode at the admission gate whose authorization has exactly 0 days left.

    The episode's own payer funds ``granted_level`` for zero days, so the grant made
    at approval already reads ``days_remaining`` of exactly 0 — the boundary PRD §3.3
    refuses with ``ERR_AUTHORIZATION_DAYS_EXHAUSTED`` (HTTP 402). Every other
    admission condition is satisfied: both clearances read CLEARED and are unexpired
    at the current instant, the withdrawal-management record is ACTIVE, the treatment
    plan is ACTIVE, the facility is licensed and body-accredited, and the
    authorization's bed hold is still OCCUPIED. No facility-ops run is needed, so the
    fiscal rule is the only condition left unsatisfied and the episode really can
    reach the gate.
    """
    site = site or setup_site()
    set_clock(admit_clock)
    payer = create_payer(
        initial_authorized_days_by_loc={granted_level: payer_grant_days}
    )
    bed = site.beds.get(granted_level)

    episode = open_episode(site)
    place_episode(site, episode["id"], scores=C.SCORES_ASAM_3_5)
    auth = request_authorization(
        site, episode["id"], requested_level=granted_level,
        bed_id=bed["id"] if bed else None, payer_id=payer["id"],
    )
    order_and_clear(site, episode["id"], "MEDICAL")
    order_and_clear(site, episode["id"], "TB_SCREEN")
    auth = approve_authorization(site, auth["id"])
    assert auth["days_remaining"] == payer_grant_days
    author_withdrawal_management(site, episode["id"])
    plan = draft_plan(site, episode["id"])
    plan = submit_plan_for_cosign(site, plan["id"])

    return ClaimedEpisode(site, read_episode(episode["id"]), None, [auth], {})


def setup_unreachable_episode(
    site=None,
    requested_level="ASAM_3_5",
    admit_clock=C.CLOCK_2026_09_01,
    burn_clock=C.CLOCK_2026_09_15,
):
    """An AWAITING_ADMISSION episode whose bed hold is on a bed that has gone away.

    The episode holds its authorization's bed, then the site's licensing lapses
    so the bed's own row is the only thing left that could satisfy the hold.
    """
    site = site or setup_cascade_site(clock=admit_clock)
    episode = open_episode(site)
    assessment, _ = place_episode(site, episode["id"], scores=C.SCORES_ASAM_3_5)
    auth = request_authorization(
        site, episode["id"], requested_level=requested_level,
        bed_id=site.beds[requested_level]["id"],
    )
    # Clearances first, then the approval (which promotes to AWAITING_ADMISSION), then
    # the withdrawal-management record and the treatment plan the admission gate needs.
    order_and_clear(site, episode["id"], "MEDICAL")
    order_and_clear(site, episode["id"], "TB_SCREEN")
    auth = approve_authorization(site, auth["id"])
    withdraw = author_withdrawal_management(site, episode["id"])
    plan = draft_plan(site, episode["id"])
    submit_plan_for_cosign(site, plan["id"])
    return site, read_episode(episode["id"]), auth, withdraw, plan


def setup_curriculum_episode_with_plan(site, setup, attended_sessions, level="ASAM_3_5"):
    """Add exactly ``attended_sessions`` attended rows inside the current treatment week."""
    service = site.services[level]
    for i in range(attended_sessions):
        hour = 6 + (i % 16)
        day = 2 + (i // 16)
        session = schedule_session(
            site, setup.id, service_id=service["id"],
            scheduled_at=f"2026-09-{day:02d}T{hour:02d}:00:00Z",
        )
        record_attendance(site, session["id"], attended=True)
    setup.refresh()
    return setup
