"""Corporate contracts and negotiated-fare traceability (PRD 3.4)."""
from flask import Blueprint

import validators as v
from auth import (ALL_ROLES, ROLE_AGENCY, ROLE_COMPLIANCE_AUDITOR,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_PLATFORM_ADMIN, authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from serializers import contract_out
from services import contract_validity_state
from store import common_fields, db, get_or_404, sort_key

bp = Blueprint("contracts", __name__)

VALIDITY_STATES = ("PENDING", "IN_EFFECT", "LAPSED")
DEFAULT_TRACKING_REF_PREFIX = "CORP-"


@bp.post("/corporate-contracts")
def create_contract():
    authenticate([ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    corporate_partner_id = v.req_string(body, "corporate_partner_id", 1, None)
    negotiated_fare_filing_id = v.req_string(body, "negotiated_fare_filing_id", 1, None)
    account_code = v.req_string(body, "account_code", 1, 24)
    max_offer_total_cents = v.req_int(body, "max_offer_total_cents", 1, None)
    traceability_required = v.opt_bool(body, "traceability_required", True)
    tracking_ref_prefix = v.opt_string(body, "tracking_ref_prefix", 1, 12,
                                       DEFAULT_TRACKING_REF_PREFIX)
    # Negotiated content is withheld from RESTRICTED channels by default.
    min_content_tier_rank = v.opt_int(body, "min_content_tier_rank", 1, 3, 2)
    effective_from = v.req_instant(body, "effective_from")
    effective_to = v.req_instant(body, "effective_to")
    if effective_from >= effective_to:
        v.bad("effective_to must be strictly after effective_from.")

    partner = db.partners.get(corporate_partner_id)
    if partner is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND",
                       "corporate_partner_id does not resolve.")
    filing = db.fare_filings.get(negotiated_fare_filing_id)
    if filing is None:
        raise ApiError("ERR_FARE_FILING_NOT_FOUND",
                       "negotiated_fare_filing_id does not resolve.")
    if partner["partner_type"] != "CORPORATE":
        raise ApiError("ERR_PARTNER_TYPE_NOT_ELIGIBLE",
                       "Only a CORPORATE partner may hold a contract.")

    contract = common_fields()
    contract.update({
        "corporate_partner_id": partner["id"],
        "negotiated_fare_filing_id": filing["id"],
        "account_code": account_code,
        "max_offer_total_cents": max_offer_total_cents,
        "traceability_required": traceability_required,
        "tracking_ref_prefix": tracking_ref_prefix,
        "min_content_tier_rank": min_content_tier_rank,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    db.contracts[contract["id"]] = contract
    return respond_object(contract_out(contract, contract_validity_state(contract)), 201)


@bp.get("/corporate-contracts/<contract_id>")
def read_contract(contract_id):
    authenticate(ALL_ROLES)
    contract = get_or_404(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    return respond_object(contract_out(contract, contract_validity_state(contract)))


@bp.get("/corporate-contracts")
def list_contracts():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY])
    limit, offset = pagination()
    corporate_partner_id = v.query_string("corporate_partner_id")
    negotiated_fare_filing_id = v.query_string("negotiated_fare_filing_id")
    validity_state = v.query_enum("validity_state", VALIDITY_STATES)

    rows = []
    for contract in db.contracts.values():
        if (corporate_partner_id is not None
                and contract["corporate_partner_id"] != corporate_partner_id):
            continue
        if (negotiated_fare_filing_id is not None
                and contract["negotiated_fare_filing_id"] != negotiated_fare_filing_id):
            continue
        # The validity filter is evaluated against the clock as the list is served.
        if (validity_state is not None
                and contract_validity_state(contract) != validity_state):
            continue
        rows.append(contract)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list(
        [contract_out(c, contract_validity_state(c)) for c in page],
        limit, offset, total)
