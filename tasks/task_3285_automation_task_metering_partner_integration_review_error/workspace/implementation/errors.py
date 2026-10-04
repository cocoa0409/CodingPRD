"""Error catalogue for the automation-task-metering API."""

# error_id -> HTTP status (scaffold §1.6 / PRD §5)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_WORKFLOW_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_CONNECTION_NOT_FOUND": 404,
    "ERR_INTEGRATION_NOT_FOUND": 404,
    "ERR_INTEGRATION_VERSION_NOT_FOUND": 404,
    "ERR_WORKFLOW_INVALID_STATE": 409,
    "ERR_ACTION_NOT_REPLAYABLE": 409,
    "ERR_CONNECTION_INVALID_STATE": 409,
    "ERR_INTEGRATION_NOT_IN_REVIEW": 409,
    "ERR_INTEGRATION_ALREADY_REJECTED": 409,
    "ERR_WORKFLOW_VERSION_NOT_MIGRATABLE": 409,
    "ERR_AUTH_METHOD_NOT_OAUTH2": 422,
    "ERR_INTEGRATION_COVERAGE_INSUFFICIENT": 422,
    "ERR_MISSING_ERROR_SEMANTICS": 422,
    "ERR_CONNECTION_TOKEN_EXPIRED": 422,
    "ERR_TASK_ALLOWANCE_EXHAUSTED": 402,
    "ERR_DUPLICATE_FOLDER_NAME": 409,
    "ERR_DUPLICATE_ACTION_POSITION": 409,
    "ERR_VERSION_NOT_MONOTONIC": 409,
    "ERR_DUPLICATE_GRANT": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_STALE_WORKFLOW_VERSION": 412,
    "ERR_FOLDER_NOT_PERMITTED": 403,
    "ERR_CONNECTION_ACCOUNT_MISMATCH": 422,
    "ERR_WORKFLOW_MAX_STEPS_EXCEEDED": 422,
    "ERR_NO_RUNNABLE_ACTION": 409,
    "ERR_DUPLICATE_EPOCH_STEP": 409,
    "ERR_TOKEN_REFRESH_CAP_EXHAUSTED": 409,
    "ERR_REPLAY_DEFERRED": 409,
}

MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the declared role is not recognized.",
    "ERR_FORBIDDEN": "The acting role is not permitted to perform this operation.",
    "ERR_ACCOUNT_NOT_FOUND": "The referenced team account does not exist.",
    "ERR_WORKFLOW_NOT_FOUND": "The referenced workflow does not exist.",
    "ERR_MEMBER_NOT_FOUND": "The referenced member does not exist.",
    "ERR_CONNECTION_NOT_FOUND": "The referenced connection does not exist.",
    "ERR_INTEGRATION_NOT_FOUND": "The referenced integration does not exist.",
    "ERR_INTEGRATION_VERSION_NOT_FOUND": "The referenced integration version does not exist.",
    "ERR_WORKFLOW_INVALID_STATE": "The workflow is not in a state that permits the requested operation.",
    "ERR_ACTION_NOT_REPLAYABLE": "The action is not in a replayable state.",
    "ERR_CONNECTION_INVALID_STATE": "The connection is not in the state the requested operation requires.",
    "ERR_INTEGRATION_NOT_IN_REVIEW": "The integration is not awaiting a review decision.",
    "ERR_INTEGRATION_ALREADY_REJECTED": "The integration was already rejected in this review cycle.",
    "ERR_WORKFLOW_VERSION_NOT_MIGRATABLE": "The workflow snapshot is not migrateable at this time.",
    "ERR_AUTH_METHOD_NOT_OAUTH2": "Reviewers only accept OAUTH2 integrations.",
    "ERR_INTEGRATION_COVERAGE_INSUFFICIENT": "The integration's endpoint coverage is below 0.8.",
    "ERR_MISSING_ERROR_SEMANTICS": "A declared endpoint lacks a response schema.",
    "ERR_CONNECTION_TOKEN_EXPIRED": "The connection's token is expired.",
    "ERR_TASK_ALLOWANCE_EXHAUSTED": "The charge would exceed the account's task allowance.",
    "ERR_DUPLICATE_FOLDER_NAME": "A folder with this name already exists in the account.",
    "ERR_DUPLICATE_ACTION_POSITION": "An action already occupies this position in the workflow.",
    "ERR_VERSION_NOT_MONOTONIC": "The published version number is not strictly greater than the existing maximum.",
    "ERR_DUPLICATE_GRANT": "The member already holds a grant on this folder.",
    "ERR_STALE_ACCOUNT_VERSION": "The expected account version is stale.",
    "ERR_STALE_WORKFLOW_VERSION": "The expected workflow version is stale.",
    "ERR_FOLDER_NOT_PERMITTED": "The acting member cannot reach this folder.",
    "ERR_CONNECTION_ACCOUNT_MISMATCH": "The connection belongs to a different account than the workflow.",
    "ERR_WORKFLOW_MAX_STEPS_EXCEEDED": "A single run may not require more than 10 actions.",
    "ERR_NO_RUNNABLE_ACTION": "No action is eligible to execute for the requested charge.",
    "ERR_DUPLICATE_EPOCH_STEP": "This metering epoch step was already consumed on this account.",
    "ERR_TOKEN_REFRESH_CAP_EXHAUSTED": "The connection's lifetime refresh cap is exhausted.",
    "ERR_REPLAY_DEFERRED": "The refund grant cannot be consumed while the connection is not connected.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        super().__init__(self.message)