"""
Composable setup helpers.

Every helper here drives the public API only -- there is no direct database access and
no mocking anywhere. Helpers are layered:

* tier 1 wraps a single endpoint and returns the created or updated resource;
* tier 2 and 3 chain a handful of calls to reach a named lifecycle position;
* tier 4 and 5 build the canonical donor-to-tissue and tissue-to-shipment chains that
  most tests start from.

Setup helpers use the lenient success reader so that a 200-versus-201 difference in an
implementation never turns a precondition into a spurious failure; the assertions that
matter live in the tests themselves.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    CERTIFICATION_EXPIRES_AT,
    T_ARRIVE,
    T_COOLED,
    T_DEATH,
    T_DISPATCH,
    T_DRAWN,
    T_EVAL_SLIT,
    T_EVAL_SPECULAR,
    T_NOW,
    T_PLANNED_RELEASE,
    T_PRESERVE,
)
from .factories import (
    abort_payload,
    adjudication_payload,
    allocation_payload,
    arrive_payload,
    cancel_allocation_payload,
    cancel_request_payload,
    classify_payload,
    close_payload,
    complete_payload,
    consent_payload,
    credential_payload,
    defer_payload,
    deliver_payload,
    discard_payload,
    dispatch_payload,
    donor_payload,
    lookback_payload,
    panel_payload,
    quarantine_payload,
    reading_payload,
    recovery_payload,
    report_payload,
    request_payload,
    results_payload,
    return_payload,
    screening_payload,
    shipment_payload,
    slit_lamp_payload,
    specular_payload,
    surgeon_payload,
    technician_payload,
    technician_status_payload,
    unique_donor_code,
)
from .test_users import (
    COORDINATOR_HEADERS,
    LAB_TECHNICIAN_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    make_evaluation_technician_headers,
    make_recovery_technician_headers,
    make_surgeon_headers,
)
from .types import GradedTissue, RecoveryChain, RequestChain, ShipmentChain


# ===========================================================================
# Tier 1 -- one endpoint each
# ===========================================================================
def set_clock(api, to_iso8601=T_NOW, headers=None):
    """Move the logical clock and return the resulting current_utc payload."""
    return get_success_data(
        api.set_clock(to_iso8601, headers or COORDINATOR_HEADERS)
    )


def create_technician(
    api,
    full_name="Rosa Field",
    certification_level="RECOVERY_ONLY",
    certification_expires_at=CERTIFICATION_EXPIRES_AT,
    headers=None,
):
    return get_success_data(
        api.create_technician(
            technician_payload(full_name, certification_level, certification_expires_at),
            headers or COORDINATOR_HEADERS,
        )
    )


def set_technician_status(api, technician_id, status, headers=None):
    return get_success_data(
        api.set_technician_status(
            technician_id, technician_status_payload(status), headers or COORDINATOR_HEADERS
        )
    )


def read_technician(api, technician_id, headers=None):
    return get_success_data(
        api.get_technician(technician_id, headers or COORDINATOR_HEADERS)
    )


def create_donor(api, headers=None, **kwargs):
    return get_success_data(
        api.create_donor(donor_payload(**kwargs), headers or COORDINATOR_HEADERS)
    )


def read_donor(api, donor_id, headers=None):
    return get_success_data(api.get_donor(donor_id, headers or COORDINATOR_HEADERS))


def add_screening(
    api,
    donor_id,
    question_code="TATTOO_12M",
    response="NO",
    historian_relationship="SPOUSE",
    headers=None,
):
    return get_success_data(
        api.create_screening_record(
            donor_id,
            screening_payload(question_code, response, historian_relationship),
            headers or COORDINATOR_HEADERS,
        )
    )


def record_consent(
    api,
    donor_id,
    consent_type="FIRST_PERSON",
    consent_scope="TRANSPLANT_ONLY",
    authorizing_party_name="Registry Self-Consent",
    headers=None,
):
    return get_success_data(
        api.record_consent(
            donor_id,
            consent_payload(consent_type, consent_scope, authorizing_party_name),
            headers or COORDINATOR_HEADERS,
        )
    )


def defer_donor(api, donor_id, deferral_reason="AWAITING_MEDICAL_RECORDS", headers=None):
    return get_success_data(
        api.defer_donor(
            donor_id, defer_payload(deferral_reason), headers or MEDICAL_DIRECTOR_HEADERS
        )
    )


def reinstate_donor(api, donor_id, headers=None):
    return get_success_data(
        api.reinstate_donor(donor_id, {}, headers or MEDICAL_DIRECTOR_HEADERS)
    )


def approve_recovery(api, donor_id, headers=None):
    return get_success_data(
        api.approve_recovery(donor_id, {}, headers or MEDICAL_DIRECTOR_HEADERS)
    )


def draw_panel(
    api,
    donor_id,
    expected_donor_version=None,
    specimen_type="POST_MORTEM",
    drawn_at=T_DRAWN,
    hemodilution_pct=0.00,
    headers=None,
):
    """Draw a specimen, reading the donor's current version when none is supplied."""
    if expected_donor_version is None:
        expected_donor_version = read_donor(api, donor_id)["version"]
    return get_success_data(
        api.create_serology_panel(
            donor_id,
            panel_payload(
                expected_donor_version, specimen_type, drawn_at, hemodilution_pct
            ),
            headers or LAB_TECHNICIAN_HEADERS,
        )
    )


def post_results(
    api,
    panel_id,
    hiv_result="NON_REACTIVE",
    hbv_result="NON_REACTIVE",
    hcv_result="NON_REACTIVE",
    syphilis_result="NON_REACTIVE",
    headers=None,
):
    return get_success_data(
        api.post_serology_results(
            panel_id,
            results_payload(hiv_result, hbv_result, hcv_result, syphilis_result),
            headers or LAB_TECHNICIAN_HEADERS,
        )
    )


def create_recovery(
    api,
    donor_id,
    technician_id,
    dispatched_at=T_DISPATCH,
    planned_release_at=T_PLANNED_RELEASE,
    headers=None,
):
    return get_success_data(
        api.create_recovery(
            recovery_payload(donor_id, technician_id, dispatched_at, planned_release_at),
            headers or COORDINATOR_HEADERS,
        )
    )


def arrive(api, recovery_id, technician_id, arrival_at=T_ARRIVE):
    return get_success_data(
        api.arrive_recovery(
            recovery_id,
            arrive_payload(arrival_at),
            make_recovery_technician_headers(technician_id),
        )
    )


def complete_recovery(
    api,
    recovery_id,
    technician_id,
    preservation_at=T_PRESERVE,
    preservation_medium="OPTISOL_GS",
    recovered_lateralities=("OD",),
):
    return get_success_data(
        api.complete_recovery(
            recovery_id,
            complete_payload(preservation_at, preservation_medium, recovered_lateralities),
            make_recovery_technician_headers(technician_id),
        )
    )


def abort_recovery(api, recovery_id, technician_id, abort_reason="FAMILY_WITHDREW"):
    return get_success_data(
        api.abort_recovery(
            recovery_id,
            abort_payload(abort_reason),
            make_recovery_technician_headers(technician_id),
        )
    )


def read_recovery(api, recovery_id, headers=None):
    return get_success_data(
        api.get_recovery(recovery_id, headers or COORDINATOR_HEADERS)
    )


def list_recoveries(api, headers=None, **filters):
    """The items of a recovery listing."""
    response = api.list_recoveries(headers or COORDINATOR_HEADERS, **filters)
    return get_success_data(response)


def count_recoveries(api, headers=None, **filters):
    """The total_count of a filtered recovery listing."""
    response = api.list_recoveries(headers or COORDINATOR_HEADERS, **filters)
    return response.json()["meta"]["total_count"]


def read_tissue(api, tissue_id, headers=None):
    return get_success_data(api.get_tissue(tissue_id, headers or COORDINATOR_HEADERS))


def list_tissues(api, headers=None, **filters):
    """The items of a tissue listing."""
    response = api.list_tissues(headers or COORDINATOR_HEADERS, **filters)
    return get_success_data(response)


def tissues_of_recovery(api, recovery_id, headers=None):
    """Tissues of one recovery, ordered oldest first so laterality order is stable."""
    items = list_tissues(api, headers=headers, recovery_id=recovery_id)
    return sorted(items, key=lambda row: row["created_at"])


def count_tissues(api, headers=None, **filters):
    """The total_count of a filtered tissue listing."""
    response = api.list_tissues(headers or COORDINATOR_HEADERS, **filters)
    return response.json()["meta"]["total_count"]


def record_slit_lamp(
    api,
    tissue_id,
    evaluator_technician_id,
    performed_at=T_EVAL_SLIT,
    expected_tissue_version=None,
    epithelium_defect_grade=0,
    stromal_clarity_grade=0,
    dm_folds_grade=0,
):
    """Record a slit-lamp exam, reading the tissue version when none is supplied."""
    if expected_tissue_version is None:
        expected_tissue_version = read_tissue(api, tissue_id)["version"]
    return get_success_data(
        api.create_tissue_evaluation(
            tissue_id,
            slit_lamp_payload(
                evaluator_technician_id,
                performed_at,
                expected_tissue_version,
                epithelium_defect_grade,
                stromal_clarity_grade,
                dm_folds_grade,
            ),
            make_evaluation_technician_headers(evaluator_technician_id),
        )
    )


def record_specular(
    api,
    tissue_id,
    evaluator_technician_id,
    performed_at=T_EVAL_SPECULAR,
    expected_tissue_version=None,
    guttata_grade=0,
    endothelial_cell_count=3100,
):
    """Record a specular exam, reading the tissue version when none is supplied."""
    if expected_tissue_version is None:
        expected_tissue_version = read_tissue(api, tissue_id)["version"]
    return get_success_data(
        api.create_tissue_evaluation(
            tissue_id,
            specular_payload(
                evaluator_technician_id,
                performed_at,
                expected_tissue_version,
                guttata_grade,
                endothelial_cell_count,
            ),
            make_evaluation_technician_headers(evaluator_technician_id),
        )
    )


def classify(api, tissue_id, intended_use_override=None, headers=None):
    return get_success_data(
        api.classify_tissue(
            tissue_id,
            classify_payload(intended_use_override),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def quarantine(api, tissue_id, quarantine_reason="OPERATOR_HOLD", headers=None):
    return get_success_data(
        api.quarantine_tissue(
            tissue_id,
            quarantine_payload(quarantine_reason),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def release_quarantine(api, tissue_id, headers=None):
    return get_success_data(
        api.release_quarantine(tissue_id, {}, headers or MEDICAL_DIRECTOR_HEADERS)
    )


def discard(api, tissue_id, disposal_method="INCINERATION", headers=None):
    return get_success_data(
        api.discard_tissue(
            tissue_id,
            discard_payload(disposal_method),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def create_surgeon(
    api,
    full_name="Dr Anwar Reed",
    center_code="CTR-01",
    specialty="PK",
    headers=None,
):
    return get_success_data(
        api.create_surgeon(
            surgeon_payload(full_name, center_code, specialty),
            headers or COORDINATOR_HEADERS,
        )
    )


def read_surgeon(api, surgeon_id, headers=None):
    return get_success_data(api.get_surgeon(surgeon_id, headers or COORDINATOR_HEADERS))


def set_credential_status(api, surgeon_id, credential_status, headers=None):
    return get_success_data(
        api.set_credential_status(
            surgeon_id,
            credential_payload(credential_status),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def create_request(
    api,
    surgeon_id,
    procedure_type="PK",
    surgery_date="2026-08-08T00:00:00.000Z",
    min_ecd=2000,
    max_donor_age_years=70,
    laterality_preference="ANY",
    urgency="ROUTINE",
    headers=None,
    as_surgeon=False,
):
    """Open a request, optionally acting as the surgeon rather than a coordinator."""
    if headers is None:
        headers = (
            make_surgeon_headers(surgeon_id) if as_surgeon else COORDINATOR_HEADERS
        )
    return get_success_data(
        api.create_surgeon_request(
            request_payload(
                surgeon_id,
                procedure_type,
                surgery_date,
                min_ecd,
                max_donor_age_years,
                laterality_preference,
                urgency,
            ),
            headers,
        )
    )


def read_request(api, request_id, headers=None):
    return get_success_data(
        api.get_surgeon_request(request_id, headers or COORDINATOR_HEADERS)
    )


def cancel_request(api, request_id, cancel_reason="SURGERY_CANCELLED", headers=None):
    return get_success_data(
        api.cancel_surgeon_request(
            request_id, cancel_request_payload(cancel_reason), headers or COORDINATOR_HEADERS
        )
    )


def allocate(api, tissue_id, request_id, headers=None):
    return get_success_data(
        api.create_allocation(
            allocation_payload(tissue_id, request_id), headers or COORDINATOR_HEADERS
        )
    )


def read_allocation(api, allocation_id, headers=None):
    return get_success_data(
        api.get_allocation(allocation_id, headers or COORDINATOR_HEADERS)
    )


def confirm(api, allocation_id, headers=None):
    return get_success_data(
        api.confirm_allocation(allocation_id, {}, headers or COORDINATOR_HEADERS)
    )


def cancel_allocation(api, allocation_id, cancel_reason="SURGERY_CANCELLED", headers=None):
    return get_success_data(
        api.cancel_allocation(
            allocation_id,
            cancel_allocation_payload(cancel_reason),
            headers or COORDINATOR_HEADERS,
        )
    )


def run_allocation(api, headers=None):
    return get_success_data(
        api.create_allocation_run({}, headers or COORDINATOR_HEADERS)
    )


def prepare_shipment(
    api, allocation_id, carrier="COURIER", replaces_shipment_id=None, headers=None
):
    return get_success_data(
        api.create_shipment(
            shipment_payload(allocation_id, carrier, replaces_shipment_id),
            headers or COORDINATOR_HEADERS,
        )
    )


def read_shipment(api, shipment_id, headers=None):
    return get_success_data(
        api.get_shipment(shipment_id, headers or COORDINATOR_HEADERS)
    )


def add_reading(api, shipment_id, recorded_at, temperature_c=4.0, headers=None):
    return get_success_data(
        api.create_temperature_reading(
            shipment_id,
            reading_payload(recorded_at, temperature_c),
            headers or COORDINATOR_HEADERS,
        )
    )


def dispatch_shipment(api, shipment_id, shipped_at, headers=None):
    return get_success_data(
        api.dispatch_shipment(
            shipment_id, dispatch_payload(shipped_at), headers or COORDINATOR_HEADERS
        )
    )


def deliver_shipment(api, shipment_id, delivered_at, surgeon_id):
    return get_success_data(
        api.deliver_shipment(
            shipment_id,
            deliver_payload(delivered_at),
            make_surgeon_headers(surgeon_id),
        )
    )


def implant(api, tissue_id, surgeon_id):
    return get_success_data(
        api.implant_tissue(tissue_id, {}, make_surgeon_headers(surgeon_id))
    )


def return_tissue(api, tissue_id, surgeon_id, return_reason="SURGERY_POSTPONED"):
    return get_success_data(
        api.return_tissue(
            tissue_id, return_payload(return_reason), make_surgeon_headers(surgeon_id)
        )
    )


def create_report(
    api,
    tissue_id,
    surgeon_id,
    reaction_type="PRIMARY_GRAFT_FAILURE",
    severity="SERIOUS",
    narrative="Graft failed on post-operative day one.",
):
    return get_success_data(
        api.create_adverse_reaction_report(
            report_payload(tissue_id, surgeon_id, reaction_type, severity, narrative),
            make_surgeon_headers(surgeon_id),
        )
    )


def substantiate(
    api,
    report_id,
    adjudication_note="Donor-attributable failure; opening lookback.",
    headers=None,
):
    return get_success_data(
        api.substantiate_report(
            report_id,
            adjudication_payload(adjudication_note),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def dismiss(api, report_id, adjudication_note="No donor attribution found.", headers=None):
    return get_success_data(
        api.dismiss_report(
            report_id,
            adjudication_payload(adjudication_note),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def open_lookback(api, donor_id, source_report_id=None, headers=None):
    return get_success_data(
        api.create_lookback_investigation(
            lookback_payload(donor_id, source_report_id),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def read_investigation(api, investigation_id, headers=None):
    return get_success_data(
        api.get_lookback_investigation(
            investigation_id, headers or MEDICAL_DIRECTOR_HEADERS
        )
    )


def notify_investigation(api, investigation_id, headers=None):
    return get_success_data(
        api.notify_investigation(investigation_id, {}, headers or MEDICAL_DIRECTOR_HEADERS)
    )


def close_investigation(
    api, investigation_id, resolution="NO_ACTION", closure_note="Investigation closed.", headers=None
):
    return get_success_data(
        api.close_investigation(
            investigation_id,
            close_payload(resolution, closure_note),
            headers or MEDICAL_DIRECTOR_HEADERS,
        )
    )


def first_investigation_for_donor(api, donor_id, headers=None):
    """The single lookback investigation opened on a donor, or None."""
    response = api.list_lookback_investigations(
        headers or MEDICAL_DIRECTOR_HEADERS, donor_id=donor_id
    )
    items = get_success_data(response)
    return items[0] if items else None


def allocations_for_request(api, request_id, headers=None):
    response = api.list_allocations(headers or COORDINATOR_HEADERS, request_id=request_id)
    return get_success_data(response)


def allocations_for_tissue(api, tissue_id, headers=None):
    response = api.list_allocations(headers or COORDINATOR_HEADERS, tissue_id=tissue_id)
    return get_success_data(response)


# ===========================================================================
# Tier 2 and 3 -- named lifecycle positions
# ===========================================================================
def canonical_roster(api):
    """Two recovery-only technicians plus one technician certified to grade."""
    rt1 = create_technician(api, "Rosa Field", "RECOVERY_ONLY")
    rt2 = create_technician(api, "Sam Okoro", "RECOVERY_ONLY")
    et = create_technician(api, "Ivo Grader", "RECOVERY_AND_EVAL")
    return rt1, rt2, et


def recovery_technician(api, full_name="Rosa Field"):
    return create_technician(api, full_name, "RECOVERY_ONLY")


def evaluation_technician(api, full_name="Ivo Grader"):
    return create_technician(api, full_name, "RECOVERY_AND_EVAL")


def screened_donor(
    api,
    question_code="TATTOO_12M",
    response="NO",
    historian_relationship="SPOUSE",
    donor_code=None,
    **donor_kwargs,
):
    """A donor advanced from REFERRED to SCREENING by its first screening answer."""
    donor = create_donor(api, donor_code=donor_code or unique_donor_code(), **donor_kwargs)
    add_screening(api, donor["id"], question_code, response, historian_relationship)
    return read_donor(api, donor["id"])


def consented_donor(
    api,
    consent_type="FIRST_PERSON",
    consent_scope="TRANSPLANT_ONLY",
    authorizing_party_name="Registry Self-Consent",
    **kwargs,
):
    """A donor advanced to CONSENT_OBTAINED."""
    donor = screened_donor(api, **kwargs)
    record_consent(
        api, donor["id"], consent_type, consent_scope, authorizing_party_name
    )
    return read_donor(api, donor["id"])


def resulted_panel_for(
    api,
    donor_id,
    hemodilution_pct=0.00,
    drawn_at=T_DRAWN,
    specimen_type="POST_MORTEM",
    hiv_result="NON_REACTIVE",
    hbv_result="NON_REACTIVE",
    hcv_result="NON_REACTIVE",
    syphilis_result="NON_REACTIVE",
):
    """Draw a specimen for an existing donor and post its four marker results."""
    panel = draw_panel(
        api,
        donor_id,
        specimen_type=specimen_type,
        drawn_at=drawn_at,
        hemodilution_pct=hemodilution_pct,
    )
    return post_results(
        api, panel["id"], hiv_result, hbv_result, hcv_result, syphilis_result
    )


def donor_with_serology(
    api,
    consent_scope="TRANSPLANT_ONLY",
    hemodilution_pct=0.00,
    hiv_result="NON_REACTIVE",
    hbv_result="NON_REACTIVE",
    hcv_result="NON_REACTIVE",
    syphilis_result="NON_REACTIVE",
    **kwargs,
):
    """A CONSENT_OBTAINED donor carrying one resulted, non-invalidated panel."""
    donor = consented_donor(api, consent_scope=consent_scope, **kwargs)
    resulted_panel_for(
        api,
        donor["id"],
        hemodilution_pct=hemodilution_pct,
        hiv_result=hiv_result,
        hbv_result=hbv_result,
        hcv_result=hcv_result,
        syphilis_result=syphilis_result,
    )
    return read_donor(api, donor["id"])


def approved_donor(
    api,
    consent_scope="TRANSPLANT_ONLY",
    with_serology=True,
    **kwargs,
):
    """A donor released for recovery, by default with negative serology on file."""
    if with_serology:
        donor = donor_with_serology(api, consent_scope=consent_scope, **kwargs)
    else:
        donor = consented_donor(api, consent_scope=consent_scope, **kwargs)
    approve_recovery(api, donor["id"])
    return read_donor(api, donor["id"])


def recovered_tissues(
    api,
    donor_id,
    technician_id,
    recovered_lateralities=("OD",),
    dispatched_at=T_DISPATCH,
    planned_release_at=T_PLANNED_RELEASE,
    arrival_at=T_ARRIVE,
    preservation_at=T_PRESERVE,
    preservation_medium="OPTISOL_GS",
):
    """Dispatch, arrive and complete one recovery, returning the tissues it created."""
    recovery = create_recovery(
        api, donor_id, technician_id, dispatched_at, planned_release_at
    )
    arrive(api, recovery["id"], technician_id, arrival_at)
    completed = complete_recovery(
        api,
        recovery["id"],
        technician_id,
        preservation_at,
        preservation_medium,
        recovered_lateralities,
    )
    # PRD 3.3 pins creation order to the order the lateralities were listed, but every
    # tissue of one completion shares the same logical-clock created_at and the same
    # preserved_at, so no listing order can distinguish them. Re-impose the requested
    # laterality order here rather than depending on an undetermined tie-break.
    laterality_rank = {lat: i for i, lat in enumerate(recovered_lateralities)}
    tissues = sorted(
        tissues_of_recovery(api, recovery["id"]),
        key=lambda row: laterality_rank.get(row["laterality"], len(laterality_rank)),
    )
    return RecoveryChain(
        donor_id=donor_id,
        technician_id=technician_id,
        recovery=completed,
        recovery_id=recovery["id"],
        tissues=tissues,
    )


def graded_tissue(
    api,
    tissue_id,
    evaluator_technician_id,
    endothelial_cell_count=3100,
    guttata_grade=0,
    epithelium_defect_grade=0,
    stromal_clarity_grade=0,
    dm_folds_grade=0,
    slit_lamp_at=T_EVAL_SLIT,
    specular_at=T_EVAL_SPECULAR,
):
    """Record one slit-lamp and one specular exam on a tissue without classifying it."""
    record_slit_lamp(
        api,
        tissue_id,
        evaluator_technician_id,
        performed_at=slit_lamp_at,
        epithelium_defect_grade=epithelium_defect_grade,
        stromal_clarity_grade=stromal_clarity_grade,
        dm_folds_grade=dm_folds_grade,
    )
    record_specular(
        api,
        tissue_id,
        evaluator_technician_id,
        performed_at=specular_at,
        guttata_grade=guttata_grade,
        endothelial_cell_count=endothelial_cell_count,
    )
    return read_tissue(api, tissue_id)


# ===========================================================================
# Tier 4 and 5 -- the canonical end-to-end chains
# ===========================================================================
def tissue_chain(
    api,
    recovered_lateralities=("OD",),
    endothelial_cell_count=3100,
    guttata_grade=0,
    epithelium_defect_grade=0,
    stromal_clarity_grade=0,
    dm_folds_grade=0,
    consent_scope="TRANSPLANT_ONLY",
    with_serology=True,
    classify_tissues=True,
    donor_code=None,
    donor_kwargs=None,
    dispatched_at=T_DISPATCH,
    planned_release_at=T_PLANNED_RELEASE,
    arrival_at=T_ARRIVE,
    preservation_at=T_PRESERVE,
    preservation_medium="OPTISOL_GS",
    recovery_technician_name="Rosa Field",
    evaluation_technician_name="Ivo Grader",
    roster=None,
):
    """
    Build the whole donor-to-inventory chain in one call.

    Returns a dict carrying every identifier a test may need: ``donor``, ``donor_id``,
    ``recovery_technician_id``, ``evaluator_technician_id``, ``recovery``,
    ``recovery_id``, ``tissues`` (oldest first, i.e. in laterality order) and
    ``tissue_ids``. When ``classify_tissues`` is true every tissue has been classified.
    """
    if roster is None:
        rt = recovery_technician(api, recovery_technician_name)
        et = evaluation_technician(api, evaluation_technician_name)
    else:
        rt, et = roster
    donor = approved_donor(
        api,
        consent_scope=consent_scope,
        with_serology=with_serology,
        donor_code=donor_code,
        **(donor_kwargs or {}),
    )
    chain = recovered_tissues(
        api,
        donor["id"],
        rt["id"],
        recovered_lateralities=recovered_lateralities,
        dispatched_at=dispatched_at,
        planned_release_at=planned_release_at,
        arrival_at=arrival_at,
        preservation_at=preservation_at,
        preservation_medium=preservation_medium,
    )
    for tissue in chain.tissues:
        graded_tissue(
            api,
            tissue["id"],
            et["id"],
            endothelial_cell_count=endothelial_cell_count,
            guttata_grade=guttata_grade,
            epithelium_defect_grade=epithelium_defect_grade,
            stromal_clarity_grade=stromal_clarity_grade,
            dm_folds_grade=dm_folds_grade,
        )
        if classify_tissues:
            classify(api, tissue["id"])
    tissues = tissues_of_recovery(api, chain.recovery_id)
    return {
        "donor": read_donor(api, donor["id"]),
        "donor_id": donor["id"],
        "recovery_technician_id": rt["id"],
        "evaluator_technician_id": et["id"],
        "recovery": chain.recovery,
        "recovery_id": chain.recovery_id,
        "tissues": tissues,
        "tissue_ids": [row["id"] for row in tissues],
    }


def standard_eligible_tissue(api, **kwargs):
    """One ELIGIBLE, transplant-classified tissue plus the ids behind it."""
    chain = tissue_chain(api, **kwargs)
    tissue = chain["tissues"][0]
    return GradedTissue(
        tissue_id=tissue["id"],
        tissue=tissue,
        donor_id=chain["donor_id"],
        recovery_id=chain["recovery_id"],
        evaluator_technician_id=chain["evaluator_technician_id"],
    )


def surgeon_with_request(
    api,
    full_name="Dr Anwar Reed",
    center_code="CTR-01",
    specialty="PK",
    procedure_type="PK",
    surgery_date="2026-08-08T00:00:00.000Z",
    min_ecd=2000,
    max_donor_age_years=70,
    laterality_preference="ANY",
    urgency="ROUTINE",
    as_surgeon=False,
):
    """Register a surgeon and open one request for them."""
    surgeon = create_surgeon(api, full_name, center_code, specialty)
    request = create_request(
        api,
        surgeon["id"],
        procedure_type=procedure_type,
        surgery_date=surgery_date,
        min_ecd=min_ecd,
        max_donor_age_years=max_donor_age_years,
        laterality_preference=laterality_preference,
        urgency=urgency,
        as_surgeon=as_surgeon,
    )
    return RequestChain(
        surgeon_id=surgeon["id"],
        surgeon=surgeon,
        request_id=request["id"],
        request=request,
    )


def reserved_allocation(api, tissue_id, request_id):
    """A RESERVED allocation of one tissue against one open request."""
    return allocate(api, tissue_id, request_id)


def confirmed_allocation(api, tissue_id, request_id):
    """A CONFIRMED allocation -- the point at which the surgeon has been billed."""
    allocation = allocate(api, tissue_id, request_id)
    return confirm(api, allocation["id"])


def prepared_shipment(
    api, tissue_id, request_id, carrier="COURIER", replaces_shipment_id=None
):
    """A PREPARED shipment against a freshly confirmed allocation."""
    allocation = confirmed_allocation(api, tissue_id, request_id)
    shipment = prepare_shipment(
        api, allocation["id"], carrier=carrier, replaces_shipment_id=replaces_shipment_id
    )
    return allocation, shipment


def issued_shipment(
    api,
    tissue_id,
    request_id,
    surgeon_id,
    carrier="COURIER",
    baseline_at="2026-08-03T09:45:00.000Z",
    baseline_temp_c=4.0,
    shipped_at="2026-08-03T10:00:00.000Z",
    replaces_shipment_id=None,
):
    """
    Carry a tissue from ELIGIBLE all the way to IN_TRANSIT: allocate, confirm, prepare,
    record the cold-chain baseline reading and dispatch.
    """
    allocation, shipment = prepared_shipment(
        api,
        tissue_id,
        request_id,
        carrier=carrier,
        replaces_shipment_id=replaces_shipment_id,
    )
    add_reading(api, shipment["id"], baseline_at, baseline_temp_c)
    dispatched = dispatch_shipment(api, shipment["id"], shipped_at)
    return ShipmentChain(
        tissue_id=tissue_id,
        surgeon_id=surgeon_id,
        request_id=request_id,
        allocation_id=allocation["id"],
        shipment_id=shipment["id"],
        shipment=dispatched,
    )


def delivered_tissue(
    api,
    tissue_id,
    request_id,
    surgeon_id,
    readings=(("2026-08-03T10:00:00.000Z", 4.0), ("2026-08-03T11:00:00.000Z", 5.0)),
    baseline_at="2026-08-03T09:45:00.000Z",
    baseline_temp_c=4.0,
    shipped_at="2026-08-03T10:00:00.000Z",
    delivered_at="2026-08-03T12:00:00.000Z",
    carrier="COURIER",
    replaces_shipment_id=None,
):
    """
    Carry a tissue to AT_SURGEON: dispatch it, log the in-transit readings as the
    receiving surgeon and acknowledge arrival.
    """
    chain = issued_shipment(
        api,
        tissue_id,
        request_id,
        surgeon_id,
        carrier=carrier,
        baseline_at=baseline_at,
        baseline_temp_c=baseline_temp_c,
        shipped_at=shipped_at,
        replaces_shipment_id=replaces_shipment_id,
    )
    surgeon_headers = make_surgeon_headers(surgeon_id)
    for recorded_at, temperature_c in readings:
        add_reading(
            api, chain.shipment_id, recorded_at, temperature_c, headers=surgeon_headers
        )
    delivered = deliver_shipment(api, chain.shipment_id, delivered_at, surgeon_id)
    return ShipmentChain(
        tissue_id=chain.tissue_id,
        surgeon_id=surgeon_id,
        request_id=request_id,
        allocation_id=chain.allocation_id,
        shipment_id=chain.shipment_id,
        shipment=delivered,
    )


def implanted_tissue(api, tissue_id, request_id, surgeon_id, **kwargs):
    """Carry a tissue all the way to IMPLANTED with its allocation CONSUMED."""
    chain = delivered_tissue(api, tissue_id, request_id, surgeon_id, **kwargs)
    implant(api, tissue_id, surgeon_id)
    return chain


def returned_tissue_chain(
    api, tissue_id, request_id, surgeon_id, return_reason="SURGERY_POSTPONED", **kwargs
):
    """Carry a tissue out and back: delivered, then returned unused to the bank."""
    chain = delivered_tissue(api, tissue_id, request_id, surgeon_id, **kwargs)
    return_tissue(api, tissue_id, surgeon_id, return_reason)
    return chain
