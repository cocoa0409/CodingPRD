"""Error catalogue for the accelerator allocation API.

Every error id and HTTP status is taken from SCAFFOLD.yaml `errors:` and
PRD.md section 5.  Nothing here is invented.
"""


class CatalogError(Exception):
    """Raised anywhere in the request path; converted into the error envelope."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = STATUS.get(error_id, 400)
        self.message = message or MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


# --------------------------------------------------------------------------
# Error id constants
# --------------------------------------------------------------------------
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"
ERR_EXPORT_CONTROL_RESTRICTED = "ERR_EXPORT_CONTROL_RESTRICTED"
ERR_EXPORT_LICENSE_REQUIRED = "ERR_EXPORT_LICENSE_REQUIRED"
ERR_NDA_NOT_BOUND = "ERR_NDA_NOT_BOUND"
ERR_PARTNER_NOT_FOUND = "ERR_PARTNER_NOT_FOUND"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_BLUEPRINT_NOT_FOUND = "ERR_BLUEPRINT_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_HOLD_TIER_EXCEEDS_BAND = "ERR_HOLD_TIER_EXCEEDS_BAND"
ERR_NODE_NOT_OPEN_FOR_ALLOCATION = "ERR_NODE_NOT_OPEN_FOR_ALLOCATION"
ERR_NO_OPEN_EPOCH = "ERR_NO_OPEN_EPOCH"
ERR_GROUP_NOT_SATISFIED = "ERR_GROUP_NOT_SATISFIED"
ERR_FORECAST_NOT_COMMITTED = "ERR_FORECAST_NOT_COMMITTED"
ERR_FORECAST_DEADLINE_PASSED = "ERR_FORECAST_DEADLINE_PASSED"
ERR_CONTRACT_WINDOW_OVERLAP = "ERR_CONTRACT_WINDOW_OVERLAP"
ERR_PREVIEW_GRANT_WINDOW_OVERLAP = "ERR_PREVIEW_GRANT_WINDOW_OVERLAP"
ERR_NDA_WINDOW_OVERLAP = "ERR_NDA_WINDOW_OVERLAP"
ERR_LIFECYCLE_UNITS_UNCOMMITTED = "ERR_LIFECYCLE_UNITS_UNCOMMITTED"
ERR_NO_COVERING_SUBSCRIPTION = "ERR_NO_COVERING_SUBSCRIPTION"
ERR_ENTITLEMENT_UNITS_EXCEEDED = "ERR_ENTITLEMENT_UNITS_EXCEEDED"
ERR_SUPPLY_CEILING_EXCEEDED = "ERR_SUPPLY_CEILING_EXCEEDED"
ERR_RESERVED_FOR_EVALUATION = "ERR_RESERVED_FOR_EVALUATION"
ERR_NO_ALLOCATION_CANDIDATE = "ERR_NO_ALLOCATION_CANDIDATE"
ERR_SAME_ACTOR_DEPLOYMENT_CHAIN = "ERR_SAME_ACTOR_DEPLOYMENT_CHAIN"
ERR_EPOCH_ALREADY_CLOSED = "ERR_EPOCH_ALREADY_CLOSED"
ERR_LICENSE_GROUP_DUPLICATE_MEMBER = "ERR_LICENSE_GROUP_DUPLICATE_MEMBER"
ERR_BLUEPRINT_NOT_CERTIFIED = "ERR_BLUEPRINT_NOT_CERTIFIED"
ERR_ALLOCATED_UNITS_CHANGED = "ERR_ALLOCATED_UNITS_CHANGED"
ERR_STALE_PARTNER_VERSION = "ERR_STALE_PARTNER_VERSION"
ERR_STALE_SUBSCRIPTION_VERSION = "ERR_STALE_SUBSCRIPTION_VERSION"
ERR_QUALIFICATION_NOT_MET = "ERR_QUALIFICATION_NOT_MET"
ERR_LIFECYCLE_HORIZON_TOO_SHORT = "ERR_LIFECYCLE_HORIZON_TOO_SHORT"
ERR_LICENSE_GROUP_UNRESOLVED = "ERR_LICENSE_GROUP_UNRESOLVED"
ERR_EVIDENCE_INSUFFICIENT = "ERR_EVIDENCE_INSUFFICIENT"

# The licence-hold-group spec spells this error with a C while every other
# occurrence in the scaffold uses an S.  Both spellings are real ids in the
# upstream documents, so the alias is accepted as an input and reported back
# under whichever spelling the caller used.
ERR_LICENCE_GROUP_DUPLICATE_MEMBER = "ERR_LICENCE_GROUP_DUPLICATE_MEMBER"


STATUS = {
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: 400,
    ERR_INVALID_REQUEST: 400,
    ERR_FORBIDDEN_FOR_ROLE: 403,
    ERR_EXPORT_CONTROL_RESTRICTED: 403,
    ERR_EXPORT_LICENSE_REQUIRED: 403,
    ERR_NDA_NOT_BOUND: 403,
    ERR_PARTNER_NOT_FOUND: 404,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_BLUEPRINT_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_HOLD_TIER_EXCEEDS_BAND: 409,
    ERR_NODE_NOT_OPEN_FOR_ALLOCATION: 409,
    ERR_NO_OPEN_EPOCH: 409,
    ERR_GROUP_NOT_SATISFIED: 409,
    ERR_FORECAST_NOT_COMMITTED: 409,
    ERR_FORECAST_DEADLINE_PASSED: 409,
    ERR_CONTRACT_WINDOW_OVERLAP: 409,
    ERR_PREVIEW_GRANT_WINDOW_OVERLAP: 409,
    ERR_NDA_WINDOW_OVERLAP: 409,
    ERR_LIFECYCLE_UNITS_UNCOMMITTED: 409,
    ERR_NO_COVERING_SUBSCRIPTION: 409,
    ERR_ENTITLEMENT_UNITS_EXCEEDED: 409,
    ERR_SUPPLY_CEILING_EXCEEDED: 409,
    ERR_RESERVED_FOR_EVALUATION: 409,
    ERR_NO_ALLOCATION_CANDIDATE: 409,
    ERR_SAME_ACTOR_DEPLOYMENT_CHAIN: 409,
    ERR_EPOCH_ALREADY_CLOSED: 409,
    ERR_LICENSE_GROUP_DUPLICATE_MEMBER: 409,
    ERR_LICENCE_GROUP_DUPLICATE_MEMBER: 409,
    ERR_BLUEPRINT_NOT_CERTIFIED: 409,
    ERR_ALLOCATED_UNITS_CHANGED: 412,
    ERR_STALE_PARTNER_VERSION: 412,
    ERR_STALE_SUBSCRIPTION_VERSION: 412,
    ERR_QUALIFICATION_NOT_MET: 422,
    ERR_LIFECYCLE_HORIZON_TOO_SHORT: 422,
    ERR_LICENSE_GROUP_UNRESOLVED: 422,
    ERR_EVIDENCE_INSUFFICIENT: 422,
}


MESSAGES = {
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: (
        "X-User-ID and X-User-Role are mandatory and X-User-Role must name a declared role."
    ),
    ERR_FORBIDDEN_FOR_ROLE: "The caller's role is not permitted for this operation.",
    ERR_PARTNER_NOT_FOUND: "The partner named in the path does not exist.",
    ERR_RESOURCE_NOT_FOUND: "The resource named in the path does not exist.",
    ERR_BLUEPRINT_NOT_FOUND: "The referenced solution blueprint does not exist.",
    ERR_INVALID_STATE: "The resource's current state does not admit the requested trigger.",
    ERR_INVALID_REQUEST: "The request body is malformed.",
    ERR_QUALIFICATION_NOT_MET: "The partner is not QUALIFIED for this program.",
    ERR_EXPORT_CONTROL_RESTRICTED: "The destination is prohibited by export control.",
    ERR_EXPORT_LICENSE_REQUIRED: "An active export licence grant is required for this destination.",
    ERR_NDA_NOT_BOUND: "A bound confidentiality acknowledgement is required for preview software.",
    ERR_HOLD_TIER_EXCEEDS_BAND: "The hold friction tier ranks above the pool's temperature ceiling.",
    ERR_NODE_NOT_OPEN_FOR_ALLOCATION: "The supply pool is not open for allocation.",
    ERR_NO_OPEN_EPOCH: "No allocation epoch is currently open.",
    ERR_GROUP_NOT_SATISFIED: "The group is not fully satisfied.",
    ERR_FORECAST_NOT_COMMITTED: "The named forecast is not ACTIVE or COMMITTED for this partner and SKU.",
    ERR_FORECAST_DEADLINE_PASSED: "The forecast commit arrived at or after the eligibility deadline.",
    ERR_CONTRACT_WINDOW_OVERLAP: "The supply contract window overlaps an existing contract on the SKU.",
    ERR_PREVIEW_GRANT_WINDOW_OVERLAP: "The preview grant window overlaps an existing grant.",
    ERR_NDA_WINDOW_OVERLAP: "The acknowledgement window overlaps an existing acknowledgement.",
    ERR_LIFECYCLE_HORIZON_TOO_SHORT: "The requested horizon is shorter than the lifecycle grace period.",
    ERR_LIFECYCLE_UNITS_UNCOMMITTED: "The covered units exceed the product's available units.",
    ERR_NO_COVERING_SUBSCRIPTION: "The deployment has no covering subscription.",
    ERR_LICENSE_GROUP_UNRESOLVED: "A licence group member targets a different product SKU.",
    ERR_ENTITLEMENT_UNITS_EXCEEDED: "The entitlement ceiling would be breached.",
    ERR_SUPPLY_CEILING_EXCEEDED: "The partner's committed volume ceiling would be breached.",
    ERR_RESERVED_FOR_EVALUATION: "The loan exceeds the product's reserved evaluation units.",
    ERR_NO_ALLOCATION_CANDIDATE: "The displacing allocation found an empty candidate set.",
    ERR_ALLOCATED_UNITS_CHANGED: "The observed allocated units no longer match the product.",
    ERR_STALE_PARTNER_VERSION: "The partner version supplied is stale.",
    ERR_STALE_SUBSCRIPTION_VERSION: "The subscription version supplied is stale.",
    ERR_SAME_ACTOR_DEPLOYMENT_CHAIN: "The terminating actor activated this deployment.",
    ERR_EPOCH_ALREADY_CLOSED: "The epoch is already closed.",
    ERR_LICENSE_GROUP_DUPLICATE_MEMBER: "A licence group names the same stack license twice.",
    ERR_LICENCE_GROUP_DUPLICATE_MEMBER: "A licence group names the same stack license twice.",
    ERR_BLUEPRINT_NOT_CERTIFIED: "The blueprint is RETIRED and refuses new evidence.",
    ERR_EVIDENCE_INSUFFICIENT: "The evidence records fewer minutes than the blueprint requires.",
}