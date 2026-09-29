"""
Declared lifecycles: initial states, the transitions that fire once, the ones that are
refused from the wrong state, and the side effects a single legal edge drags with it.

Each case drives one edge of one declared state machine and then re-reads every row the
edge was supposed to touch — and every row it was supposed to leave alone.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_DONOR_STATE_INVALID,
    ERR_RECOVERY_STATE_INVALID,
    LAB_TECHNICIAN_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    T_NOW,
    assert_instant_equals,
    factories,
    fixtures,
    get_success_data,
    make_recovery_technician_headers,
    validate_error,
)


def _referred_donor(pinned_api, donor_code):
    """A bare referral: no screening answers, no consent, no serology."""
    return fixtures.create_donor(
        pinned_api,
        donor_code=donor_code,
        referral_source="HOSPITAL",
        death_at="2026-08-03T02:00:00.000Z",
        death_time_basis="ASYSTOLE",
        body_cooled_at=None,
        age_years=52,
        cause_of_death_category="CARDIAC",
    )


def test_donor_initial_state_is_referred_on_creation(pinned_api):
    """
    A freshly created donor sits in the declared initial state with version 1 and none of the
    later-lifecycle fields populated.

    PRD 2.7: "A `Donor`'s `status` runs over `REFERRED`, `SCREENING`, `CONSENT_OBTAINED`,
    `APPROVED_FOR_RECOVERY`, `RECOVERED`, `DEFERRED` and `RULED_OUT`, starting at `REFERRED`,
    with `RECOVERED` and `RULED_OUT` terminal, and with a `DEFERRED` back to `SCREENING`
    revision cycle."

    PRD 3.1: "A newly registered donor is created with `status` `REFERRED`, `consent_type`
    and `consent_scope` both `NONE`, `authorizing_party_name` and `consent_obtained_at` both
    null, `serology_status` `PENDING`, `screening_risk_score` 0, `screening_risk_variant`
    `INTERVIEW_ONLY`, `deferral_reason` null, `lookback_flag` false,
    `tissues_recovered_count` 0 and `version` 1."

    Design: Corner/state_machines/donor_initial_state_is_referred_on_creation
    """
    created = _referred_donor(pinned_api, "D-2846-S01")

    donor = get_success_data(
        pinned_api.get_donor(created["id"], MEDICAL_DIRECTOR_HEADERS)
    )

    assert donor["status"] == "REFERRED"
    assert donor["version"] == 1
    assert donor["consent_obtained_at"] is None
    assert donor["deferral_reason"] is None


def test_only_the_first_screening_record_moves_the_donor_referred_to_screening(pinned_api):
    """
    The first answer fires the transition and the second does not, yet both recompute the
    risk score and both bump the donor's version.

    PRD 3.1: "The **first** screening record for a donor advances that donor from `REFERRED`
    to `SCREENING`; second and later records leave `status` untouched but still trigger a full
    recomputation of the risk score."

    PRD 3.1: "The weights encode the bank's clinical priorities: a family history of
    Creutzfeldt–Jakob disease (`CJD_FAMILY`) is worth 60 points, unexplained neurological
    death (`UNEXPLAINED_NEURO`) 50, intravenous drug use (`IV_DRUG_USE`) 40, HIV risk
    behaviour (`HIV_RISK`) 35, a hepatitis B or C history (`HEP_B_C_HISTORY`) 30, sepsis
    (`SEPSIS`) 25, incarceration within the last twelve months (`INCARCERATION_12M`) 15 and a
    tattoo within the last twelve months (`TATTOO_12M`) 10."

    Design: Corner/state_machines/only_the_first_screening_record_moves_the_donor_referred_to_screening
    """
    donor = _referred_donor(pinned_api, "D-2846-S02")

    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")

    after_first = fixtures.read_donor(pinned_api, donor["id"])
    assert after_first["status"] == "SCREENING"
    assert after_first["version"] == 2
    assert after_first["screening_risk_score"] == 0

    fixtures.add_screening(pinned_api, donor["id"], "HIV_RISK", "YES", "SIBLING")

    after_second = fixtures.read_donor(pinned_api, donor["id"])
    assert after_second["status"] == "SCREENING"
    assert after_second["version"] == 3
    assert after_second["screening_risk_score"] == 35


def test_consent_before_any_screening_record_yields_err_donor_state_invalid(pinned_api):
    """
    Consent has exactly one legal from-state, so a referral that has never been interviewed
    cannot be authorized.

    PRD 3.2: "Recording consent requires the donor to be in `SCREENING`, and a scope of
    `NONE` is not a legitimate value to submit here — a request that supplies it is rejected
    as an invalid request."

    PRD 2.10: "The donor's `status` permits the operation — otherwise
    `ERR_DONOR_STATE_INVALID` (409). Applies to consent, approval for recovery, deferral,
    reinstatement and recovery dispatch."

    Design: Corner/state_machines/consent_before_any_screening_record_yields_err_donor_state_invalid
    """
    donor = _referred_donor(pinned_api, "D-2846-S03")

    response = pinned_api.record_consent(
        donor["id"],
        factories.consent_payload("NEXT_OF_KIN", "TRANSPLANT_ONLY", "Aunt Mirela"),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_DONOR_STATE_INVALID, 409)
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["status"] == "REFERRED"
    assert reread["consent_scope"] == "NONE"
    assert reread["consent_type"] == "NONE"
    assert reread["consent_obtained_at"] is None
    assert reread["version"] == 1


def test_a_second_consent_on_a_consented_donor_yields_err_donor_state_invalid(pinned_api):
    """
    Re-running the consent call from CONSENT_OBTAINED is refused rather than silently
    re-stamping the authorization, so neither the party name nor the version moves.

    PRD 3.2: "Recording consent requires the donor to be in `SCREENING`, and a scope of
    `NONE` is not a legitimate value to submit here — a request that supplies it is rejected
    as an invalid request."

    PRD 3.2: "On success the four consent fields are written, `consent_obtained_at` is
    stamped with the current logical instant, and the donor advances `SCREENING →
    CONSENT_OBTAINED`."

    Design: Corner/state_machines/a_second_consent_on_a_consented_donor_yields_err_donor_state_invalid
    """
    donor = _referred_donor(pinned_api, "D-2846-S04")
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    consented = fixtures.record_consent(
        pinned_api,
        donor["id"],
        consent_type="NEXT_OF_KIN",
        consent_scope="TRANSPLANT_ONLY",
        authorizing_party_name="Aunt Mirela",
    )
    assert consented["version"] == 3
    assert_instant_equals(consented["consent_obtained_at"], T_NOW, "consent_obtained_at")

    response = pinned_api.record_consent(
        donor["id"],
        factories.consent_payload(
            "FIRST_PERSON", "TRANSPLANT_AND_RESEARCH", "Donor Registry"
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_DONOR_STATE_INVALID, 409)
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["consent_type"] == "NEXT_OF_KIN"
    assert reread["consent_scope"] == "TRANSPLANT_ONLY"
    assert reread["authorizing_party_name"] == "Aunt Mirela"
    assert reread["status"] == "CONSENT_OBTAINED"
    assert reread["version"] == 3
    assert_instant_equals(reread["consent_obtained_at"], T_NOW, "consent_obtained_at")


def test_approve_recovery_on_a_ruled_out_donor_yields_err_donor_state_invalid(pinned_api):
    """
    A reactive HIV marker drives the donor into the terminal RULED_OUT status, after which
    the release attempt reports the state conflict rather than the reactive-serology refusal.

    PRD 3.2: "A donor in `SCREENING`, `CONSENT_OBTAINED`, `APPROVED_FOR_RECOVERY` or
    `DEFERRED` moves to `RULED_OUT`, which is terminal — the bank will recover nothing from
    that donor."

    PRD 3.2: "It requires the donor to be in `CONSENT_OBTAINED` — any other status is
    `ERR_DONOR_STATE_INVALID` — and requires `serology_status` to be anything other than
    `REACTIVE`, a reactive donor being refused with `ERR_SEROLOGY_REACTIVE`."

    PRD 2.10: "And because every state gate (rungs 11 to 20) precedes every business-safety
    gate (rungs 21 onward), an operation attempted from the wrong state reports the state
    conflict even when a safety rule would also have refused it."

    Design: Corner/state_machines/approve_recovery_on_a_ruled_out_donor_yields_err_donor_state_invalid
    """
    donor = _referred_donor(pinned_api, "D-2846-S05")
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(pinned_api, donor["id"])
    panel = fixtures.draw_panel(pinned_api, donor["id"], drawn_at="2026-08-03T04:00:00.000Z")
    resulted = fixtures.post_results(pinned_api, panel["id"], hiv_result="REACTIVE")
    assert resulted["overall_result"] == "REACTIVE"
    assert fixtures.read_donor(pinned_api, donor["id"])["status"] == "RULED_OUT"

    response = pinned_api.approve_recovery(donor["id"], None, MEDICAL_DIRECTOR_HEADERS)

    validate_error(response, ERR_DONOR_STATE_INVALID, 409)
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["status"] == "RULED_OUT"
    assert reread["serology_status"] == "REACTIVE"


def test_deferring_an_approved_donor_aborts_the_open_dispatch_and_frees_the_technician(
    pinned_api,
):
    """
    One deferral of an approved donor aborts the live dispatch with the literal
    DONOR_DEFERRED reason and hands the technician's slot back.

    PRD 3.2: "Deferral, available to a coordinator and to a medical director alike, is legal
    from `SCREENING`, `CONSENT_OBTAINED` or `APPROVED_FOR_RECOVERY`; it records
    `deferral_reason` and moves the donor to `DEFERRED`."

    PRD 3.2: "Deferring a donor who was already approved has teeth: **every** recovery of
    that donor whose `status` is `DISPATCHED` or `ON_SITE` is aborted, processed in ascending
    `created_at` order, with `abort_reason` set to the literal `DONOR_DEFERRED`; each abort
    decrements `open_dispatch_count` on that recovery's technician and increments that
    technician's `version` by 1."

    Design: Corner/state_machines/deferring_an_approved_donor_aborts_the_open_dispatch_and_frees_the_technician
    """
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    donor = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-S06",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(pinned_api, donor["id"])
    panel = fixtures.draw_panel(pinned_api, donor["id"], drawn_at="2026-08-03T04:00:00.000Z")
    fixtures.post_results(pinned_api, panel["id"])
    fixtures.approve_recovery(pinned_api, donor["id"])
    recovery = fixtures.create_recovery(
        pinned_api,
        donor["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
    )
    before = fixtures.read_technician(pinned_api, technician["id"])
    assert before["open_dispatch_count"] == 1
    assert before["version"] == 2

    deferred = fixtures.defer_donor(
        pinned_api,
        donor["id"],
        deferral_reason="Awaiting hospital chart review",
        headers=MEDICAL_DIRECTOR_HEADERS,
    )

    assert deferred["status"] == "DEFERRED"
    assert deferred["deferral_reason"] == "Awaiting hospital chart review"
    aborted = fixtures.read_recovery(pinned_api, recovery["id"])
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == "DONOR_DEFERRED"
    after = fixtures.read_technician(pinned_api, technician["id"])
    assert after["open_dispatch_count"] == 0
    assert after["version"] == 3


def test_a_newer_serology_panel_invalidates_the_earlier_panel_and_resets_the_donor(
    pinned_api,
):
    """
    Drawing a second specimen supersedes the resulted first panel and drags the donor's
    serology status and risk variant back to their pre-result values.

    PRD 3.2: "Creating it is destructive to the donor's serologic history in a controlled
    way: **every** earlier panel of the same donor, whether it was still `DRAWN` or already
    `RESULTED`, moves to `INVALIDATED` with `superseded_at` stamped at the current logical
    instant and its own `version` incremented."

    PRD 3.2: "Because no resulted, non-invalidated panel then remains, the donor's
    `serology_status` reverts to `PENDING`, `screening_risk_variant` reverts to
    `INTERVIEW_ONLY`, and `screening_risk_score` is recomputed under that variant — an
    `UNKNOWN`-heavy donor's score can therefore fall when a fresh specimen is drawn."

    PRD 3.2: "The donor's `version` is incremented, and the new panel's
    `donor_version_after` captures the donor's `version` once that cascade has settled."

    Design: Corner/state_machines/a_newer_serology_panel_invalidates_the_earlier_panel_and_resets_the_donor
    """
    donor = _referred_donor(pinned_api, "D-2846-S07")
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(pinned_api, donor["id"])
    first_panel = fixtures.draw_panel(
        pinned_api, donor["id"], drawn_at="2026-08-03T04:00:00.000Z"
    )
    fixtures.post_results(pinned_api, first_panel["id"])
    before = fixtures.read_donor(pinned_api, donor["id"])
    assert before["serology_status"] == "NEGATIVE"
    assert before["screening_risk_variant"] == "POST_SEROLOGY_RECONCILED"

    second_panel = fixtures.draw_panel(
        pinned_api,
        donor["id"],
        expected_donor_version=before["version"],
        specimen_type="PRE_MORTEM",
        drawn_at="2026-08-03T05:00:00.000Z",
        hemodilution_pct=12.50,
    )

    assert second_panel["status"] == "DRAWN"
    assert second_panel["superseded_at"] is None
    panels = get_success_data(
        pinned_api.list_serology_panels(donor["id"], LAB_TECHNICIAN_HEADERS)
    )
    assert [row["id"] for row in panels] == [second_panel["id"], first_panel["id"]]
    assert panels[1]["status"] == "INVALIDATED"
    assert_instant_equals(panels[1]["superseded_at"], T_NOW, "superseded_at")

    after = fixtures.read_donor(pinned_api, donor["id"])
    assert after["serology_status"] == "PENDING"
    assert after["screening_risk_variant"] == "INTERVIEW_ONLY"
    assert second_panel["donor_version_after"] == after["version"]


def test_a_second_arrive_on_an_on_site_recovery_yields_err_recovery_state_invalid(
    pinned_api,
):
    """
    Arrival is legal only from DISPATCHED, so a second arrival is refused and the recorded
    arrival instant is not overwritten.

    PRD 3.3: "The dispatched technician marks arrival by supplying `arrival_at`, which moves
    the recovery `DISPATCHED → ON_SITE` and increments its `version`; the technician
    performing this must be the technician named in the recovery's `technician_id`, and any
    other technician is refused with `ERR_NOT_RESOURCE_OWNER`."

    PRD 2.10: "The recovery's `status` permits the operation — `DISPATCHED` for arrival,
    `ON_SITE` for completion, either `DISPATCHED` or `ON_SITE` for abort — otherwise
    `ERR_RECOVERY_STATE_INVALID` (409)."

    Design: Corner/state_machines/a_second_arrive_on_an_on_site_recovery_yields_err_recovery_state_invalid
    """
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    donor = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-S08",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(pinned_api, donor["id"])
    panel = fixtures.draw_panel(pinned_api, donor["id"], drawn_at="2026-08-03T04:00:00.000Z")
    fixtures.post_results(pinned_api, panel["id"])
    fixtures.approve_recovery(pinned_api, donor["id"])
    recovery = fixtures.create_recovery(
        pinned_api,
        donor["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
    )
    on_site = fixtures.arrive(
        pinned_api, recovery["id"], technician["id"], "2026-08-03T07:00:00.000Z"
    )
    assert on_site["status"] == "ON_SITE"
    assert_instant_equals(on_site["arrival_at"], "2026-08-03T07:00:00.000Z", "arrival_at")
    assert on_site["version"] == 2

    response = pinned_api.arrive_recovery(
        recovery["id"],
        factories.arrive_payload("2026-08-03T08:00:00.000Z"),
        make_recovery_technician_headers(technician["id"]),
    )

    validate_error(response, ERR_RECOVERY_STATE_INVALID, 409)
    reread = fixtures.read_recovery(pinned_api, recovery["id"])
    assert reread["status"] == "ON_SITE"
    assert_instant_equals(reread["arrival_at"], "2026-08-03T07:00:00.000Z", "arrival_at")
    assert reread["version"] == 2
