"""MdfAllocation, MdfClaim and ProofOfPerformance endpoints."""
from flask import g

import calc
import cascades
import serialize
import store
import validate as v
from auth import acting_partner_scope, endpoint
from constants import MAX_PROOF_ROUNDS
from errors import ApiError
from guards import (allocation_of_claim, check_allocation_open,
                    check_no_overdue_audit, check_not_suspended, find,
                    find_allocation, find_claim, find_partner,
                    find_proof_of_claim, invalid_state, partner_of_claim)
from response import created, filtered, listing, object_response


def _recompute_marketing_only(partner):
    """Verification recomputes the rollups but drives no standing transition."""
    before = (partner["marketing_qualified_spend_cents"],
              partner["marketing_attainment_pct"])
    calc.recompute_marketing(partner)
    after = (partner["marketing_qualified_spend_cents"],
             partner["marketing_attainment_pct"])
    if before != after:
        store.touch(partner)


def register(app):
    # -----------------------------------------------------------------
    # fund periods
    # -----------------------------------------------------------------
    @app.route("/mdf-allocations", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def create_allocation():
        body = v.body()
        # existence (3)
        partner_ref = v.fk_candidate(body, "partner_id")
        partner = find_partner(partner_ref) if partner_ref is not None else None
        # request shape (5)
        partner_id = v.req_string(body, "partner_id")
        period_start = v.req_instant(body, "period_start")
        period_end = v.req_instant(body, "period_end")
        v.interval(period_start, period_end, "period_start", "period_end")
        # program standing (13)
        check_not_suspended(partner)
        tier = partner["tier"]
        basis = calc.mdf_basis_revenue(partner["id"], period_start)
        allocated = calc.mdf_allocation_sizing(tier, basis)
        # annual fund capacity (28)
        overlap_total = 0
        for other in store.all_rows("allocations"):
            if other["partner_id"] != partner["id"]:
                continue
            if calc.periods_intersect(period_start, period_end,
                                      other["period_start"], other["period_end"]):
                overlap_total += other["allocated_cents"]
        if allocated + overlap_total > calc.annual_cap_for(tier):
            raise ApiError("ERR_MDF_PERIOD_CAPACITY_EXCEEDED",
                           "The period would breach the tier's annual fund cap.")
        row = {
            "partner_id": partner_id,
            "period_start": period_start,
            "period_end": period_end,
            "basis_revenue_cents": basis,
            "allocated_cents": allocated,
            "committed_cents": 0,
            "paid_cents": 0,
            "expired_cents": 0,
            "available_cents": allocated,
            "status": "OPEN",
            "closed_at": None,
        }
        store.insert("allocations", row)
        return created(serialize.allocation(row))

    @app.route("/mdf-allocations", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_allocations():
        rows = store.ordered(store.all_rows("allocations"))
        rows = filtered(rows, [("partner_id", "partner_id"), ("status", "status")])
        return listing(rows, serialize.allocation)

    @app.route("/mdf-allocations/<allocation_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_allocation(allocation_id):
        row = find_allocation(allocation_id)
        return object_response(serialize.allocation(row))

    @app.route("/mdf-allocations/<allocation_id>/close", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def close_allocation(allocation_id):
        allocation = find_allocation(allocation_id)
        v.body()
        # fund period open (10)
        check_allocation_open(allocation)
        cascades.cascade_c(allocation)
        return object_response(serialize.allocation(allocation))

    @app.route("/mdf-allocations/<allocation_id>/mdf-claims", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_allocation_claims(allocation_id):
        allocation = find_allocation(allocation_id)
        rows = [c for c in store.ordered(store.all_rows("claims"))
                if c["allocation_id"] == allocation["id"]]
        rows = filtered(rows, [("validation_state", "validation_state"),
                               ("settlement_state", "settlement_state")])
        return listing(rows, serialize.claim)

    # -----------------------------------------------------------------
    # claims
    # -----------------------------------------------------------------
    @app.route("/mdf-claims", methods=["POST"])
    @endpoint("Partner")
    def create_claim():
        body = v.body()
        # existence (3)
        allocation_ref = v.fk_candidate(body, "allocation_id")
        allocation = (find_allocation(allocation_ref)
                      if allocation_ref is not None else None)
        # partner scoping (4) - the partner of the period the claim draws on
        if allocation is not None:
            acting_partner_scope(allocation["partner_id"])
        # request shape (5)
        allocation_id = v.req_string(body, "allocation_id")
        activity_type = v.req_enum(body, "activity_type",
                                   ("EVENT", "DIGITAL_CAMPAIGN", "CONTENT_SYNDICATION"))
        requested_cents = v.req_int(body, "requested_cents", minimum=1)
        # fund period open (10)
        check_allocation_open(allocation)
        partner = store.get("partners", allocation["partner_id"])
        # program standing (13)
        check_not_suspended(partner)
        # audit remediation (14)
        check_no_overdue_audit(partner)
        # fund availability (27)
        calc.recompute_available(allocation)
        if requested_cents > allocation["available_cents"]:
            raise ApiError("ERR_MDF_ALLOCATION_INSUFFICIENT",
                           "The fund period cannot cover the requested amount.")
        row = {
            "allocation_id": allocation_id,
            "activity_type": activity_type,
            "requested_cents": requested_cents,
            "validation_state": "SUBMITTED",
            "settlement_state": "UNPAID",
            "matched_total_cents": None,
            "approved_cents": None,
            "proof_round": 0,
            "validated_by_user_id": None,
            "settled_by_user_id": None,
            "rejection_reason": None,
        }
        store.insert("claims", row)
        allocation["committed_cents"] = allocation["committed_cents"] + requested_cents
        calc.recompute_available(allocation)
        store.touch(allocation)
        return created(serialize.claim(row))

    @app.route("/mdf-claims", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_claims():
        rows = store.ordered(store.all_rows("claims"))
        rows = filtered(rows, [("allocation_id", "allocation_id"),
                               ("validation_state", "validation_state"),
                               ("settlement_state", "settlement_state"),
                               ("activity_type", "activity_type")])
        return listing(rows, serialize.claim)

    @app.route("/mdf-claims/<claim_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_claim(claim_id):
        row = find_claim(claim_id)
        return object_response(serialize.claim(row))

    # -----------------------------------------------------------------
    # proof documents
    # -----------------------------------------------------------------
    @app.route("/mdf-claims/<claim_id>/proofs", methods=["POST"])
    @endpoint("Partner")
    def attach_proof(claim_id):
        claim = find_claim(claim_id)
        allocation = allocation_of_claim(claim)
        # partner scoping (4)
        if allocation is not None:
            acting_partner_scope(allocation["partner_id"])
        body = v.body()
        doc_type = v.req_enum(body, "doc_type",
                              ("INVOICE", "ATTENDEE_LIST", "SCREENSHOT", "LEAD_REPORT"))
        spend_amount_cents = v.req_int(body, "spend_amount_cents", minimum=1)
        audience_reach = v.opt_int(body, "audience_reach", minimum=0)
        # state precondition (9)
        if claim["validation_state"] not in ("SUBMITTED", "PROOF_REQUESTED"):
            raise invalid_state(
                "Evidence attaches only to a SUBMITTED or PROOF_REQUESTED claim.")
        # fund period open (10)
        check_allocation_open(allocation)
        row = {
            "claim_id": claim["id"],
            "doc_type": doc_type,
            "spend_amount_cents": spend_amount_cents,
            "audience_reach": audience_reach,
            "verified": False,
            "verified_at": None,
            "verified_by_user_id": None,
            "matched_line_cents": None,
        }
        store.insert("proofs", row)
        # PROOF_REQUESTED closes the loop; SUBMITTED is a self-loop that
        # consumes no round.
        if claim["validation_state"] == "PROOF_REQUESTED":
            claim["validation_state"] = "SUBMITTED"
        store.touch(claim)
        return created(serialize.proof(row))

    @app.route("/mdf-claims/<claim_id>/proofs", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def list_claim_proofs(claim_id):
        claim = find_claim(claim_id)
        rows = [p for p in store.ordered(store.all_rows("proofs"))
                if p["claim_id"] == claim["id"]]
        wanted = v.bool_query("verified")
        if wanted is not None:
            rows = [p for p in rows if p["verified"] is wanted]
        return listing(rows, serialize.proof)

    @app.route("/proofs/<proof_id>", methods=["GET"])
    @endpoint("ChannelOpsAnalyst", "ChannelDirector", "Partner")
    def read_proof(proof_id):
        row = find("proofs", proof_id)
        return object_response(serialize.proof(row))

    @app.route("/mdf-claims/<claim_id>/proofs/<proof_id>/verify", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def verify_proof(claim_id, proof_id):
        claim = find_claim(claim_id)
        proof = find_proof_of_claim(claim, proof_id)
        v.body()
        allocation = allocation_of_claim(claim)
        # fund period open (10)
        check_allocation_open(allocation)
        # verification not repeatable (23)
        if proof["verified"]:
            raise ApiError("ERR_PROOF_ALREADY_VERIFIED",
                           "This document has already been verified.")
        proof["verified"] = True
        proof["verified_at"] = store.now()
        proof["verified_by_user_id"] = g.user_id
        store.touch(proof)
        if claim["validation_state"] == "VALIDATED":
            partner = partner_of_claim(claim)
            if partner is not None:
                _recompute_marketing_only(partner)
        return object_response(serialize.proof(proof))

    # -----------------------------------------------------------------
    # the validation dimension
    # -----------------------------------------------------------------
    @app.route("/mdf-claims/<claim_id>/validate", methods=["POST"])
    @endpoint("ChannelOpsAnalyst")
    def validate_claim(claim_id):
        claim = find_claim(claim_id)
        body = v.body()
        decision = v.req_enum(body, "decision",
                              ("VALIDATE", "REQUEST_PROOF", "REJECT"))
        rejection_reason = None
        if decision == "REJECT":
            rejection_reason = v.req_string(body, "rejection_reason")
        allocation = allocation_of_claim(claim)
        partner = partner_of_claim(claim)
        state = claim["validation_state"]

        if decision == "REQUEST_PROOF":
            # state precondition (9), loop cap included
            if state != "SUBMITTED":
                raise invalid_state("Proof is requested only from SUBMITTED.")
            if claim["proof_round"] >= MAX_PROOF_ROUNDS:
                raise invalid_state("The proof-round cap has been reached.")
            # fund period open (10)
            check_allocation_open(allocation)
            claim["validation_state"] = "PROOF_REQUESTED"
            claim["proof_round"] = claim["proof_round"] + 1
            store.touch(claim)
        elif decision == "VALIDATE":
            # state precondition (9)
            if state != "SUBMITTED":
                raise invalid_state("A claim is validated only from SUBMITTED.")
            # fund period open (10)
            check_allocation_open(allocation)
            # verified proof present (22)
            if not calc.claim_has_verified_proof(claim["id"]):
                raise ApiError("ERR_NO_VERIFIED_PROOF",
                               "The claim carries no verified proof document.")
            matched_total, approved = calc.claim_matching(claim, partner["tier"])
            remainder = claim["requested_cents"] - approved
            claim["validation_state"] = "VALIDATED"
            claim["matched_total_cents"] = matched_total
            claim["approved_cents"] = approved
            claim["validated_by_user_id"] = g.user_id
            store.touch(claim)
            if remainder:
                allocation["committed_cents"] = (allocation["committed_cents"]
                                                 - remainder)
                calc.recompute_available(allocation)
                store.touch(allocation)
            calc.apply_marketing_standing(partner, "up")
        else:
            # state precondition (9)
            if state == "VALIDATED":
                if claim["settlement_state"] != "UNPAID":
                    raise invalid_state(
                        "A settled claim can no longer be clawed back.")
                cascades.cascade_b(claim, allocation, partner,
                                   rejection_reason, g.user_id)
                store.touch(claim)
            elif state in ("SUBMITTED", "PROOF_REQUESTED"):
                claim["validation_state"] = "REJECTED"
                claim["approved_cents"] = 0
                claim["rejection_reason"] = rejection_reason
                claim["validated_by_user_id"] = g.user_id
                store.touch(claim)
                allocation["committed_cents"] = (allocation["committed_cents"]
                                                 - claim["requested_cents"])
                calc.recompute_available(allocation)
                store.touch(allocation)
            else:
                raise invalid_state("The claim has already been rejected.")
        return object_response(serialize.claim(claim))

    # -----------------------------------------------------------------
    # the settlement dimension
    # -----------------------------------------------------------------
    @app.route("/mdf-claims/<claim_id>/settlement", methods=["POST"])
    @endpoint("ChannelDirector")
    def settle_claim(claim_id):
        claim = find_claim(claim_id)
        body = v.body()
        action = v.req_enum(body, "action",
                            ("APPROVE_PAYMENT", "PAY", "WRITE_OFF"))
        allocation = allocation_of_claim(claim)
        settlement = claim["settlement_state"]
        # state precondition (9) - the settlement dimension only
        if action == "APPROVE_PAYMENT":
            if settlement != "UNPAID":
                raise invalid_state("Payment is approved only from UNPAID.")
        elif action == "PAY":
            if settlement != "APPROVED_FOR_PAYMENT":
                raise invalid_state("Payment runs only from APPROVED_FOR_PAYMENT.")
        else:
            if settlement not in ("UNPAID", "APPROVED_FOR_PAYMENT"):
                raise invalid_state("The claim is already settled.")
        # fund period open (10)
        if action in ("APPROVE_PAYMENT", "PAY"):
            check_allocation_open(allocation)
        # claim validated before settlement (11)
        if action == "APPROVE_PAYMENT" or (action == "WRITE_OFF"
                                           and settlement == "UNPAID"):
            if claim["validation_state"] != "VALIDATED":
                raise ApiError("ERR_CLAIM_NOT_VALIDATED",
                               "The claim has not been validated.")
        # segregation of duties (15)
        if claim["validated_by_user_id"] is not None \
                and g.user_id == claim["validated_by_user_id"]:
            raise ApiError("ERR_SOD_SAME_ACTOR",
                           "The operator who validated the claim may not settle it.")
        approved = claim["approved_cents"] or 0
        if action == "APPROVE_PAYMENT":
            claim["settlement_state"] = "APPROVED_FOR_PAYMENT"
        elif action == "PAY":
            claim["settlement_state"] = "PAID"
            allocation["committed_cents"] = allocation["committed_cents"] - approved
            allocation["paid_cents"] = allocation["paid_cents"] + approved
            calc.recompute_available(allocation)
            store.touch(allocation)
        else:
            claim["settlement_state"] = "WRITTEN_OFF"
            claim["rejection_reason"] = "WRITTEN_OFF"
            allocation["committed_cents"] = allocation["committed_cents"] - approved
            allocation["expired_cents"] = allocation["expired_cents"] + approved
            calc.recompute_available(allocation)
            store.touch(allocation)
        claim["settled_by_user_id"] = g.user_id
        store.touch(claim)
        return object_response(serialize.claim(claim))
