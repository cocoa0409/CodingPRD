"""Nothing in this model is eventually consistent.

Every derived value this API stores is computed inside the transaction that
caused it, so the response that performed a write already carries the recomputed
fields, and the very next request — detail read, list projection, or filtered
index — agrees with it. The two mechanisms most likely to lag in a careless
implementation are exercised here: the priced consideration chain written by
board review, and `readiness_posture`, a denormalised aggregate over a
collection the acquisition does not own.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.constants import (
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_DILIGENCE,
    NOVATION_ACTION_DENY,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_DENIED,
    NOVATION_NOTICE_SENT,
    NPI_B,
    OPINION_STATUS_ACCEPTED,
    PHYSICIAN_NAME_B,
    POSTURE_AT_RISK,
    POSTURE_BLOCKED,
    POSTURE_READY,
    SPECIALTY_CARDIOLOGY,
    TASK_COMPLIANCE_TRAINING,
    TASK_PATIENT_NOTIFICATION,
    TASK_PAYER_CREDENTIALING,
    TASK_REVENUE_CYCLE_GO_LIVE,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_FAILED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
    USER_INTEGRATION_MANAGER,
)
from test_helpers.constants import POLICY_FORM_CLAIMS_MADE
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    accepted_cr_opinion,
    accepted_market_fmv,
    advance_deal_status,
    board_review_deal,
    create_cardiology_acquisition,
    create_payer_contract,
    create_physician,
    create_task,
    diligence_deal,
    read_acquisition,
    read_task,
    reset_clock,
    set_task_status,
)

# --- The priced cardiology deal ---------------------------------------------

TAIL_COVERAGE_MONTHS = 72
CARDIOLOGY_EBITDA_CENTS = 240_000_000
CARDIOLOGY_MULTIPLE_BPS = 65_000

# 240000000 * 65000 / 10000 = 1560000000.
PURCHASE_PRICE_CENTS = 1_560_000_000
# 9600000 * 22500 / 10000 * 72 / 60 = 25920000, rounded once at the end.
TAIL_PREMIUM_CENTS = 25_920_000
# 1560000000 * 350 / 10000, levied on the base alone.
INTEGRATION_RESERVE_CENTS = 54_600_000
# base + reserve + tail + escrow_committed_cents, which is still 0 here.
GROSS_CONSIDERATION_CENTS = 1_640_520_000
# 1640520000 sits in the 1500000000-to-2500000000 tier.
SYNERGY_CREDIT_BPS = 275
SYNERGY_CREDIT_CENTS = 45_114_300
NET_CONSIDERATION_CENTS = 1_595_405_700

CONSIDERATION_FIELDS = (
    "purchase_price_cents",
    "integration_reserve_cents",
    "gross_consideration_cents",
    "synergy_credit_bps",
    "synergy_credit_cents",
    "net_consideration_cents",
    "tail_premium_cents",
)

# --- Readiness checklist dates ----------------------------------------------

TRAINING_DUE_ON = "2026-10-25"
GO_LIVE_DUE_ON = "2026-10-28"
NOTIFICATION_DUE_ON = "2026-10-30"
CREDENTIALING_DUE_ON = "2026-10-22"

DENIAL_NOTE = "Payer refused to novate the agreement"


def _priced_deal(api: ApiClient) -> dict:
    """A CLAIMS_MADE cardiology deal carried through board review in one call.

    The returned `priced` entity is the body of the transition response itself,
    never a re-read, so the assertions can tell the two apart.
    """
    reset_clock(api)
    acquisition = create_cardiology_acquisition(
        api,
        malpractice_policy_form=POLICY_FORM_CLAIMS_MADE,
        tail_coverage_months=TAIL_COVERAGE_MONTHS,
    )
    acquisition_id = acquisition["id"]
    assert acquisition["tail_coverage_required"] is True
    a.assert_consideration_all_null(acquisition)

    physician = create_physician(
        api,
        acquisition_id,
        npi=NPI_B,
        full_name=PHYSICIAN_NAME_B,
        specialty=SPECIALTY_CARDIOLOGY,
    )
    advance_deal_status(api, acquisition_id, DEAL_STATUS_DILIGENCE)

    fmv = accepted_market_fmv(
        api,
        acquisition_id,
        officer_headers=COMPLIANCE_OFFICER,
        normalized_ebitda_cents=CARDIOLOGY_EBITDA_CENTS,
        market_multiple_bps=CARDIOLOGY_MULTIPLE_BPS,
    )
    cr = accepted_cr_opinion(api, acquisition_id, officer_headers=COMPLIANCE_OFFICER_ALT)

    priced = validate_success(
        api.set_acquisition_status(
            acquisition_id,
            f.acquisition_status_payload(DEAL_STATUS_BOARD_REVIEW),
            DEAL_LEAD,
        )
    )
    return {
        "acquisition_id": acquisition_id,
        "physician": physician,
        "fmv": fmv,
        "cr": cr,
        "priced": priced,
    }


# ---------------------------------------------------------------------------
# Board review prices the deal inside the response that moved it
# ---------------------------------------------------------------------------


def test_the_board_review_response_already_carries_the_whole_priced_deal(api: ApiClient):
    """Five derived money fields, correct in the body of the transition itself.

    PRD: "Successful reads and successful state-changing actions return HTTP 200
    with the affected resource — for an action endpoint, the resource whose state
    changed, refreshed to include every field the action recomputed."

    PRD: "`tail_premium_cents` is then `annual_malpractice_premium_cents`
    multiplied by that rate, divided by 10000, multiplied by
    `tail_coverage_months`, divided by 60, with the whole expression rounded half
    up to a whole cent exactly once at the end."

    PRD: "`gross_consideration_cents` is then the sum of four terms: the base,
    `integration_reserve_cents`, `tail_premium_cents`, and
    `escrow_committed_cents` as it stands at the moment of the transition."

    Design: Corner/consistency_model/board_review_side_effects_are_visible_in_the_triggering_response
    """
    fixture = _priced_deal(api)
    acquisition_id = fixture["acquisition_id"]
    priced = fixture["priced"]

    a.assert_status(priced, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_money_equals(
        priced["tail_premium_cents"], TAIL_PREMIUM_CENTS, "tail_premium_cents"
    )
    a.assert_consideration_chain(
        priced,
        PURCHASE_PRICE_CENTS,
        INTEGRATION_RESERVE_CENTS,
        GROSS_CONSIDERATION_CENTS,
        SYNERGY_CREDIT_BPS,
        SYNERGY_CREDIT_CENTS,
        NET_CONSIDERATION_CENTS,
    )

    immediately_after = read_acquisition(api, acquisition_id)
    a.assert_consideration_chain(
        immediately_after,
        PURCHASE_PRICE_CENTS,
        INTEGRATION_RESERVE_CENTS,
        GROSS_CONSIDERATION_CENTS,
        SYNERGY_CREDIT_BPS,
        SYNERGY_CREDIT_CENTS,
        NET_CONSIDERATION_CENTS,
    )
    for field in CONSIDERATION_FIELDS:
        assert immediately_after[field] == priced[field], (
            f"{field} differs between the transition response and the next read"
        )

    read_again = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    for field in CONSIDERATION_FIELDS:
        assert read_again[field] == priced[field], (
            f"{field} moved on a repeated read, so the value was not settled"
        )


def test_the_pin_and_the_filtered_indexes_are_current_on_the_next_request(api: ApiClient):
    """The child write and every index over it are visible immediately.

    PRD: "The accepted `FMV` opinion has `is_pinned` set to true; it is now the
    single opinion the rest of the deal is measured against."

    PRD: "Every list response populates all four pagination fields in `meta`:
    `limit` and `offset` echo the effective values actually applied,
    `total_count` reports the number of rows matching the filter before
    pagination is applied, and `has_more` is true exactly when the sum of
    `offset` and the number of rows returned in this page is less than
    `total_count`."

    Design: Corner/consistency_model/board_review_side_effects_are_visible_in_the_triggering_response
    """
    fixture = _priced_deal(api)
    acquisition_id = fixture["acquisition_id"]
    fmv_id = fixture["fmv"]["id"]
    cr_id = fixture["cr"]["id"]

    pinned = get_success_data(api.get_valuation_opinion(fmv_id, VALUATION_ANALYST))
    assert pinned["is_pinned"] is True
    a.assert_status(pinned, OPINION_STATUS_ACCEPTED)

    pinned_rows = a.assert_total_count(
        api.list_valuation_opinions(
            {"acquisition_id": acquisition_id, "is_pinned": True}, VALUATION_ANALYST
        ),
        1,
    )
    a.assert_contains_id(pinned_rows, fmv_id)
    a.assert_excludes_id(pinned_rows, cr_id)

    commercial = get_success_data(api.get_valuation_opinion(cr_id, VALUATION_ANALYST))
    assert commercial["is_pinned"] is False
    unpinned_rows = a.assert_total_count(
        api.list_valuation_opinions(
            {"acquisition_id": acquisition_id, "is_pinned": False}, VALUATION_ANALYST
        ),
        1,
    )
    a.assert_contains_id(unpinned_rows, cr_id)

    listed = a.assert_total_count(
        api.list_acquisitions({"deal_status": DEAL_STATUS_BOARD_REVIEW}, DEAL_LEAD), 1
    )
    a.assert_contains_id(listed, acquisition_id)
    a.assert_money_equals(
        listed[0]["net_consideration_cents"],
        NET_CONSIDERATION_CENTS,
        "net_consideration_cents in the list projection",
    )
    a.assert_money_equals(
        listed[0]["tail_premium_cents"], TAIL_PREMIUM_CENTS, "tail_premium_cents"
    )


# ---------------------------------------------------------------------------
# The posture aggregate never lags the collection it is derived from
# ---------------------------------------------------------------------------


def test_completing_the_last_blocking_line_flips_the_posture_for_the_next_reader(
    api: ApiClient,
):
    """A checklist write is visible in the parent's derived field and its index.

    PRD: "Unlike the other two it is never set by a request: it is recomputed by
    the server from the acquisition's blocking day-one checklist lines every time
    one of them changes, every time one is added, and on the workflow
    transitions into `DILIGENCE` and into `SIGNED`."

    PRD: "Completion stores the caller's `X-User-ID` in `verified_by_user_id` and
    recomputes the posture."

    PRD: "Only lines with `is_blocking` true participate; non-blocking lines
    never affect the posture, in any status."

    Design: Corner/consistency_model/readiness_posture_is_current_in_the_next_request
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    task_a = create_task(
        api,
        acquisition_id,
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    task_b = create_task(
        api,
        acquisition_id,
        task_code=TASK_REVENUE_CYCLE_GO_LIVE,
        is_blocking=True,
        due_on=GO_LIVE_DUE_ON,
    )
    task_c = create_task(
        api,
        acquisition_id,
        task_code=TASK_PATIENT_NOTIFICATION,
        is_blocking=False,
        due_on=NOTIFICATION_DUE_ON,
    )
    set_task_status(api, task_a["id"], TASK_STATUS_IN_PROGRESS)
    set_task_status(api, task_a["id"], TASK_STATUS_COMPLETE)
    set_task_status(api, task_b["id"], TASK_STATUS_IN_PROGRESS)

    before = read_acquisition(api, acquisition_id)
    a.assert_status(before, POSTURE_AT_RISK, "readiness_posture")
    at_risk_rows = a.assert_total_count(
        api.list_acquisitions({"readiness_posture": POSTURE_AT_RISK}, DEAL_LEAD), 1
    )
    a.assert_contains_id(at_risk_rows, acquisition_id)

    completed = validate_success(
        api.set_readiness_task_status(
            task_b["id"], f.task_status_payload(TASK_STATUS_COMPLETE), INTEGRATION_MANAGER
        )
    )
    a.assert_status(completed, TASK_STATUS_COMPLETE)
    assert completed["verified_by_user_id"] == USER_INTEGRATION_MANAGER

    after = read_acquisition(api, acquisition_id)
    a.assert_status(after, POSTURE_READY, "readiness_posture")
    ready_rows = a.assert_total_count(
        api.list_acquisitions({"readiness_posture": POSTURE_READY}, DEAL_LEAD), 1
    )
    a.assert_contains_id(ready_rows, acquisition_id)
    stale_rows = a.assert_total_count(
        api.list_acquisitions({"readiness_posture": POSTURE_AT_RISK}, DEAL_LEAD), 0
    )
    a.assert_excludes_id(stale_rows, acquisition_id)

    idle = read_task(api, task_c["id"])
    a.assert_status(idle, TASK_STATUS_OPEN)
    assert idle["is_blocking"] is False
    a.assert_status(
        read_acquisition(api, acquisition_id), POSTURE_READY, "readiness_posture"
    )


def test_a_cascade_from_a_payer_denial_reaches_the_next_reader(api: ApiClient):
    """The posture drops on a write to a contract two subtrees away.

    PRD: "The acquisition's readiness checklist line with `task_code`
    `PAYER_CREDENTIALING` is set to `FAILED` when it is currently in
    `IN_PROGRESS` or in `COMPLETE`, and its `failure_reason` is recorded."

    PRD: "And the acquisition's `readiness_posture` is recomputed, which will
    read `BLOCKED` for as long as that failed line stands."

    PRD: "Otherwise, if any blocking line is in `FAILED`, the posture is
    `BLOCKED`."

    Design: Corner/consistency_model/readiness_posture_is_current_in_the_next_request
    """
    reset_clock(api)
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    task = create_task(
        api,
        acquisition_id,
        task_code=TASK_PAYER_CREDENTIALING,
        is_blocking=True,
        due_on=CREDENTIALING_DUE_ON,
    )
    set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    a.assert_status(
        read_acquisition(api, acquisition_id), POSTURE_AT_RISK, "readiness_posture"
    )

    contract = create_payer_contract(api, acquisition_id)
    noticed = validate_success(
        api.act_on_novation(
            contract["id"],
            f.novation_payload(NOVATION_ACTION_SEND_NOTICE),
            INTEGRATION_MANAGER,
        )
    )
    a.assert_status(noticed, NOVATION_NOTICE_SENT, "novation_status")

    denied = validate_success(
        api.act_on_novation(
            contract["id"],
            f.novation_payload(NOVATION_ACTION_DENY, note=DENIAL_NOTE),
            INTEGRATION_MANAGER,
        )
    )
    a.assert_status(denied, NOVATION_DENIED, "novation_status")

    a.assert_status(read_task(api, task["id"]), TASK_STATUS_FAILED)
    blocked = read_acquisition(api, acquisition_id)
    a.assert_status(blocked, POSTURE_BLOCKED, "readiness_posture")

    blocked_rows = a.assert_total_count(
        api.list_acquisitions({"readiness_posture": POSTURE_BLOCKED}, DEAL_LEAD), 1
    )
    a.assert_contains_id(blocked_rows, acquisition_id)
    a.assert_total_count(
        api.list_acquisitions({"readiness_posture": POSTURE_AT_RISK}, DEAL_LEAD), 0
    )
