"""Path and body foreign-key resolution (validation ladder rungs 5 and 7)."""

import db
import errors
import middleware


def _resolve(collection, entity_id, error_id):
    entity = collection.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise errors.ApiError(error_id)
    return entity


def get_program(program_id):
    return _resolve(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")


def get_dealer(dealer_id):
    return _resolve(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")


def get_objective(objective_id):
    return _resolve(db.objectives, objective_id, "ERR_OBJECTIVE_NOT_FOUND")


def get_protest(protest_id):
    return _resolve(db.protests, protest_id, "ERR_PROTEST_NOT_FOUND")


def get_delivery(delivery_id):
    return _resolve(db.deliveries, delivery_id, "ERR_DELIVERY_NOT_FOUND")


def get_claim(claim_id):
    return _resolve(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")


def get_chargeback(chargeback_id):
    return _resolve(db.chargebacks, chargeback_id, "ERR_CHARGEBACK_NOT_FOUND")


def get_batch(batch_id):
    return _resolve(db.payment_batches, batch_id, "ERR_BATCH_NOT_FOUND")


def require_dealer_ownership(dealer_id):
    """Rung 4: a Dealer caller may only act on its own resources."""
    if middleware.caller_role() != middleware.ROLE_DEALER:
        return
    if dealer_id != middleware.caller_id():
        raise errors.ApiError("ERR_DEALER_MISMATCH")


def require_good_standing(dealer):
    """Rung 17: a TERMINATED dealer is cut off at the top of the funnel."""
    if dealer["status"] == "TERMINATED":
        raise errors.ApiError("ERR_DEALER_NOT_IN_GOOD_STANDING")
