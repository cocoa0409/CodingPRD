"""Who may act, and on which half of a shared row.

Every refusal below is paired with the identical request made by the principal the PRD
does authorise, so the difference between the two calls is never anything but identity.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import (
    make_coder_headers,
    make_interventionalist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCESS_PLACED_ON = "2026-03-01"
READING_AT = "2026-07-25T08:00:00Z"
INFO_NOTE = "please attach the last three flow trends"
RESUBMITTED_NARRATIVE = "trends attached, flow stable at 900"
RECOVERY_AT = "2026-08-01T13:40:00Z"


def _a_held_referral_owned_by_its_facility(api):
    """A referral pushed to INFO_REQUESTED, so resubmission is state-legal for its facility."""
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_PLACED_ON,
    )
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        reading_at=READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    referral = fx.seed_referral(
        api,
        access["id"],
        center["facility_id"],
        suspected_problem="STENOSIS",
        clinical_narrative="the referral lifecycle is split between two roles",
        missed_treatment_count=0,
    )
    held = fx.request_info(api, referral["id"], info_request_note=INFO_NOTE)
    assert held["status"] == "INFO_REQUESTED"
    assert held["hold_reason"] == "COORDINATOR_REQUEST"
    assert held["info_request_count"] == 1
    return center, held


def test_01_neither_side_of_the_referral_lifecycle_may_take_the_other_s_step(api):
    """The facility may not triage, the centre may not resubmit, and both then succeed.

    The PRD reserves each step to one role. Of resubmission it states:
    "`FacilityCoordinator` speaks only for its own facility, and is the only role permitted
    to resubmit a held referral." Of triage it states that an `AccessCoordinator` "triages
    and declines referrals, requests more information, books and cancels cases, manages
    accesses and conversion plans, and may read everything except the reimbursement
    preview."

    The facility's refusal is an authorization refusal rather than a state refusal, which
    matters because the referral is `INFO_REQUESTED` and could not have been triaged in any
    case: the PRD orders the checks so that "**Authorization.** The acting role appears in
    the called operation's authorized-role list, otherwise `ERR_UNAUTHORIZED`" precedes the
    declared-state rung.

    Design: Corner/rbac/facility_coordinator_cannot_triage_and_access_coordinator_cannot_resubmit
    """
    center, held = _a_held_referral_owned_by_its_facility(api)

    facility_triage = api.triage_referral(held["id"], center["facility_headers"])
    validate_error(facility_triage, "ERR_UNAUTHORIZED", 403)
    assert facility_triage.json()["data"]["error_id"] != "ERR_REFERRAL_STATE_INVALID"

    centre_resubmit = api.resubmit_referral(
        held["id"],
        {
            "clinical_narrative": "coordinator tries to resubmit on the facility's behalf",
            "missed_treatment_count": 0,
        },
        fx.COORDINATOR,
    )
    validate_error(centre_resubmit, "ERR_UNAUTHORIZED", 403)

    still_held = fx.read_referral(api, held["id"])
    assert still_held["status"] == "INFO_REQUESTED"
    assert still_held["version"] == held["version"]

    resubmitted = fx.resubmit(
        api,
        held["id"],
        center["facility_headers"],
        clinical_narrative=RESUBMITTED_NARRATIVE,
        missed_treatment_count=0,
    )
    assertions.assert_referral(resubmitted)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["clinical_narrative"] == RESUBMITTED_NARRATIVE
    assert resubmitted["hold_reason"] is None
    assert resubmitted["info_request_count"] == 1

    triaged = fx.triage(api, held["id"])
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_score"] == 0
    assert triaged["urgency"] == "ROUTINE"


def test_02_the_administrator_may_not_author_the_lines_it_bills(api):
    """The money path is split in two, and each half refuses the other's principal.

    The PRD states: "**Filing a code line** is exclusive to a `Coder`." It states of the
    administrator that "it alone may set the logical clock, run the expiry sweep, register
    facilities, clinicians, procedure rooms and device lots, quarantine and release lots,
    and bill, deny or rebill a procedure", and of the coder that it "files procedural code
    lines and may never attest, bill, deny or rebill."

    The coder's refusal is not a state refusal: the case is `ATTESTED` and would otherwise
    bill, so only the role can be what refuses it.

    Design: Corner/rbac/center_admin_cannot_post_code_lines_and_coder_cannot_bill
    """
    bundle = fx.seed_aborted_case(api)
    line = {
        "hcpcs_code": "36902",
        "code_family": "ANGIOPLASTY",
        "base_allowed_cents": 180000,
        "rank": 1,
    }

    admin_codes = api.create_procedure_code(bundle["procedure_id"], line, fx.ADMIN)
    validate_error(admin_codes, "ERR_UNAUTHORIZED", 403)
    assert fx.read_procedure(api, bundle["procedure_id"])["coding_status"] == "UNCODED"

    coded = validate_success(
        api.create_procedure_code(
            bundle["procedure_id"], line, bundle["coder_headers"]
        ),
        201,
    )
    assertions.assert_procedure_code(coded)
    priced = fx.read_procedure(api, bundle["procedure_id"])
    assert priced["coding_status"] == "CODED"
    assert priced["allowed_amount_cents"] == 180000

    attested = fx.attest(api, bundle)
    assert attested["coding_status"] == "ATTESTED"

    coder_bills = api.bill_procedure(bundle["procedure_id"], bundle["coder_headers"])
    validate_error(coder_bills, "ERR_UNAUTHORIZED", 403)

    unbilled = fx.read_procedure(api, bundle["procedure_id"])
    assert unbilled["coding_status"] == "ATTESTED"
    assert unbilled["billed_amount_cents"] == 0
    assert unbilled["net_receivable_cents"] == 0
    assert unbilled["version"] == attested["version"]


def test_03_the_operating_interventionalist_cannot_code_his_own_case(api):
    """The role header is right and the identity is wrong, and identity is what is checked.

    The PRD states: "The clinician who ran the case may never code it: when the acting
    `X-User-ID` on code-line filing equals either the procedure's `primary_operator_id` or
    its `sedation_rn_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

    The refused request carries the `Coder` role, so the authorization rung passes and only
    the segregation rung can fire. The accepted request differs from it in nothing but the
    `X-User-ID`, and its money follows the patient, because the PRD states: "The variant is
    chosen from the payer model of the patient reached through the procedure's referral and
    its access: a `payer_program` of `BUNDLED_ESRD` selects the bundled variant, and
    `FEE_FOR_SERVICE` selects the fee-for-service variant."

    Design: Corner/rbac/the_operating_interventionalist_cannot_code_his_own_case
    """
    bundle = fx.seed_aborted_case(api)
    line = {
        "hcpcs_code": "36902",
        "code_family": "ANGIOPLASTY",
        "base_allowed_cents": 180000,
        "rank": 1,
    }
    assert bundle["patient"]["payer_program"] == "FEE_FOR_SERVICE"

    own_case = api.create_procedure_code(
        bundle["procedure_id"], line, make_coder_headers(bundle["operator_id"])
    )
    validate_error(own_case, "ERR_SEGREGATION_OF_DUTIES", 403)

    uncoded = fx.read_procedure(api, bundle["procedure_id"])
    assert uncoded["coding_status"] == "UNCODED"
    assert uncoded["allowed_amount_cents"] == 0
    empty, empty_meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], fx.ADMIN)
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    accepted = validate_success(
        api.create_procedure_code(
            bundle["procedure_id"], line, make_coder_headers(bundle["coder_id"])
        ),
        201,
    )
    assertions.assert_procedure_code(accepted)
    assert accepted["allowed_cents"] == 180000

    coded = fx.read_procedure(api, bundle["procedure_id"])
    assert coded["coding_status"] == "CODED"
    assert coded["allowed_amount_cents"] == 180000
    assert coded["reimbursement_variant"] == "FEE_FOR_SERVICE"
    assertions.assert_money_ledger(coded)


def test_04_a_peer_interventionalist_is_refused_at_every_room_step(api):
    """Credentials are not the question; the procedure names one operator and means it.

    The PRD states: "**Starting** a case is exclusive to an `Interventionalist`, and the
    acting `X-User-ID` must equal the procedure's `primary_operator_id` — any other
    interventionalist is refused with `ERR_NOT_ASSIGNED_CLINICIAN`."

    The guard covers the whole room sequence, not merely its first step: the PRD states
    "**Moving to recovery** is likewise the assigned primary operator's act, requires
    `clinical_status` of `IN_ROOM` (otherwise `ERR_PROCEDURE_NOT_IN_ROOM`), and carries the
    single field `sedation_end_at` — the instant sedation actually stopped."

    The assigned operator's start is byte-identical to the refused one, so the only variable
    between the 403 and the 200 is the acting identity.

    Design: Corner/rbac/a_second_interventionalist_cannot_start_another_operators_case
    """
    bundle = fx.seed_scheduled_case(api)
    peer = fx.seed_interventionalist(api)
    peer_headers = make_interventionalist_headers(peer["id"])
    assert peer["clinician_role"] == "INTERVENTIONALIST"
    assert peer["id"] != bundle["operator_id"]

    peer_start = api.start_procedure(bundle["procedure_id"], peer_headers)
    validate_error(peer_start, "ERR_NOT_ASSIGNED_CLINICIAN", 403)

    still_scheduled = fx.read_procedure(api, bundle["procedure_id"])
    assert still_scheduled["clinical_status"] == "SCHEDULED"
    assert still_scheduled["version"] == bundle["procedure"]["version"]

    in_room = validate_success(
        api.start_procedure(bundle["procedure_id"], bundle["operator_headers"])
    )
    assertions.assert_procedure(in_room)
    assert in_room["clinical_status"] == "IN_ROOM"

    peer_recovery = api.move_procedure_to_recovery(
        bundle["procedure_id"], {"sedation_end_at": RECOVERY_AT}, peer_headers
    )
    validate_error(peer_recovery, "ERR_NOT_ASSIGNED_CLINICIAN", 403)

    unmoved = fx.read_procedure(api, bundle["procedure_id"])
    assert unmoved["clinical_status"] == "IN_ROOM"
    assert unmoved["sedation_end_at"] is None
    assert unmoved["version"] == in_room["version"]
