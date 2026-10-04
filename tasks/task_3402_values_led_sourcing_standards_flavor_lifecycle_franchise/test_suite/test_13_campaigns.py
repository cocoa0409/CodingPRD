"""Activism campaigns under dual governance (PRD §3.7, §2.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_campaign_payload,
    make_campaign, decide_campaign, make_approved_campaign,
    make_scheduled_campaign, make_launched_campaign,
    make_independent_board_member_headers,
)

POC = TEST_USERS["parent_ops_controller_headers"]


def test_campaign_board_reject_blocks_schedule(api):
    """PRD §3.7: "rejecting moves it to the terminal `BOARD_REJECTED`" and
    "`BOARD_REJECTED` and `WITHDRAWN` are the terminal states; nothing leaves
    them."
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/campaign_board_reject_blocks_schedule
    """
    campaign = make_campaign(impact="LOW", title="Doomed Drive",
                             proposer_id="board-1")
    rejected = decide_campaign(campaign["id"], False, decider_id="board-2")
    assert rejected["approval_status"] == "BOARD_REJECTED"
    resp = api.schedule_ops(campaign["id"], POC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_campaign_launch_with_pending_notices_rejected(api):
    """PRD §3.7: "launching while `retail_notice_status` is still `PENDING`
    fails with `ERR_RETAIL_NOTICES_PENDING` (HTTP 409), so a campaign whose
    impact is `NONE` (notices `NOT_REQUIRED`) launches freely, while any `LOW`
    or `HIGH` impact campaign must have its notices dispatched first."

    Design: Corner/state_machines/campaign_launch_with_pending_notices_rejected
    """
    campaign = make_scheduled_campaign(impact="HIGH", title="Shelf Shock",
                                       proposer_id="board-1")
    assert campaign["retail_notice_status"] == "PENDING"
    resp = api.launch_campaign(campaign["id"], POC)
    validate_error(resp, ApiErrorId.ERR_RETAIL_NOTICES_PENDING)


def test_campaign_dispatch_before_approval_rejected(api):
    """PRD §3.7: "dispatches retail-partner notices — defined for a campaign in
    `BOARD_APPROVED` or `OPS_SCHEDULED` — moving `retail_notice_status` from `PENDING` to `DISPATCHED`"
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/campaign_dispatch_before_approval_rejected
    """
    campaign = make_campaign(impact="LOW", title="Early Notices",
                             proposer_id="board-1")
    assert campaign["approval_status"] == "BOARD_REVIEW"
    resp = api.dispatch_retail_notices(campaign["id"], POC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_campaign_veto_withdraws_launched_campaign(api):
    """PRD §3.7: "An `IndependentBoardMember` may veto a campaign in
    `BOARD_APPROVED`, `OPS_SCHEDULED`, or `LAUNCHED`, withdrawing it to the
    terminal `WITHDRAWN` — the independent board's veto overrides the parent
    company's operational scheduling even after launch."

    Design: Corner/state_machines/campaign_veto_withdraws_launched_campaign
    """
    campaign = make_launched_campaign(impact="NONE", title="Veto Bait",
                                      proposer_id="board-1")
    assert campaign["approval_status"] == "LAUNCHED"
    resp = api.veto_campaign(
        campaign["id"], make_independent_board_member_headers("board-3"))
    data = validate_success(resp)
    assert data["approval_status"] == "WITHDRAWN"


def test_campaign_none_impact_launches_without_notices(api):
    """PRD §3.7: "launching while `retail_notice_status` is still `PENDING`
    fails with `ERR_RETAIL_NOTICES_PENDING` (HTTP 409), so a campaign whose
    impact is `NONE` (notices `NOT_REQUIRED`) launches freely".

    Design: Corner/endpoints/campaign_none_impact_launches_without_notices
    """
    campaign = make_scheduled_campaign(impact="NONE", title="Silent Launch",
                                       proposer_id="board-1")
    assert campaign["retail_notice_status"] == "NOT_REQUIRED"
    launched = validate_success(api.launch_campaign(campaign["id"], POC))
    assert launched["approval_status"] == "LAUNCHED"


def test_campaign_proposer_cannot_decide_sod(api):
    """PRD §2.9: "The board member who casts a campaign's board decision must
    not be the member who proposed it. If the decider's `X-User-ID` equals the
    campaign's `proposer_user_id`, the decision is rejected with
    `ERR_SOD_CAMPAIGN_PROPOSER` (HTTP 403)."

    Design: Corner/validations/campaign_proposer_cannot_decide_sod
    """
    campaign = make_campaign(impact="NONE", title="Self Approve",
                             proposer_id="board-1")
    resp = api.board_decision(
        campaign["id"], {"approve": True},
        make_independent_board_member_headers("board-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_CAMPAIGN_PROPOSER)


def test_parent_ops_cannot_cast_board_decision(api):
    """PRD §2.9: "Neither role can perform the other's exclusive operations, and
    a role not listed for an operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.7: "The board decision belongs to a different board member than the
    proposer".

    Design: Corner/rbac/parent_ops_cannot_cast_board_decision
    """
    campaign = make_campaign(impact="NONE", title="Who Decides",
                             proposer_id="board-1")
    resp = api.board_decision(campaign["id"], {"approve": True}, POC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_board_member_cannot_schedule_ops(api):
    """PRD §2.9: "Neither role can perform the other's exclusive operations, and
    a role not listed for an operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.7: "From `BOARD_APPROVED`, operational control passes to the parent."

    Design: Corner/rbac/board_member_cannot_schedule_ops
    """
    campaign = make_approved_campaign(impact="NONE", title="Mirror Gate",
                                      proposer_id="board-1")
    resp = api.schedule_ops(
        campaign["id"], make_independent_board_member_headers("board-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
