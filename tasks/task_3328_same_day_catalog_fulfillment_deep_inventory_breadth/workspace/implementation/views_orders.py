"""Routes: orders, allocation, picking, cutoff, shipments, returns and claims."""

from flask import request as flask_request

from common import body_json
from db import db
from errors import not_found
from response import ok_object
from route_util import gate, paginated
from serializers import (damage_claim as ser_claim)
from serializers import (order as ser_order)
from serializers import (order_line as ser_line)
from serializers import (pick_task as ser_pick_task)
from serializers import (return_authorization as ser_return)
from serializers import (shipment as ser_shipment)
from svc_dc import get_dc
from svc_orders import (_ownership, approve_return, cancel_order,
                        cancel_return, complete_pick, confirm_cutoff,
                        create_order, create_return, dispatch_shipment,
                        get_claim, get_line, get_order, get_return,
                        lines_of, receive_return, reject_claim, release_order,
                        resolve_claim, resume_claim, start_pick, void_claim)


def _pick_task(task_id):
    record = db.pick_tasks.get(task_id)
    if record is None:
        raise not_found("ERR_INVALID_REQUEST", "No pick task exists for id '%s'." % task_id)
    return record


def _shipment(shipment_id):
    record = db.shipments.get(shipment_id)
    if record is None:
        raise not_found("ERR_INVALID_REQUEST", "No shipment exists for id '%s'." % shipment_id)
    return record


def _line_filters(args):
    def keep(line):
        for field in ("allocated_dc_id", "item_id", "line_status"):
            value = args.get(field)
            if value and line.get(field) != value:
                return False
        return True
    return keep


def register(app):

    # ------------------------------------------------------------- orders
    @app.post("/orders")
    def _order_create():
        user_id, _role = gate("POST", "/orders")
        return ok_object(ser_order(create_order(db, user_id, body_json())), 201)

    @app.get("/orders")
    def _order_list():
        gate("GET", "/orders")
        keep = _line_filters(flask_request.args)
        args = flask_request.args

        def matches(order):
            for field in ("account_id", "allocated_dc_id", "order_status",
                          "fulfillment_status"):
                value = args.get(field)
                if value and order.get(field) != value:
                    return False
            return True

        return paginated([o for o in db.orders.values() if matches(o)], ser_order)

    @app.get("/orders/<order_id>")
    def _order_get(order_id):
        gate("GET", "/orders/<order_id>")
        return ok_object(ser_order(get_order(db, order_id)))

    @app.post("/orders/<order_id>/release")
    def _order_release(order_id):
        user_id, _role = gate("POST", "/orders/<order_id>/release")
        order = get_order(db, order_id)
        _ownership(order, user_id)
        return ok_object(ser_order(release_order(db, order)))

    @app.post("/orders/<order_id>/allocate")
    def _order_allocate(order_id):
        user_id, _role = gate("POST", "/orders/<order_id>/allocate")
        order = get_order(db, order_id)
        _ownership(order, user_id)
        return ok_object(ser_order(allocate(db, order, body_json())))

    @app.post("/orders/<order_id>/cancel")
    def _order_cancel(order_id):
        user_id, _role = gate("POST", "/orders/<order_id>/cancel")
        order = get_order(db, order_id)
        _ownership(order, user_id)
        return ok_object(ser_order(cancel_order(db, order)))

    @app.get("/orders/<order_id>/lines")
    def _order_lines(order_id):
        gate("GET", "/orders/<order_id>/lines")
        get_order(db, order_id)
        keep = _line_filters(flask_request.args)
        return paginated([l for l in lines_of(db, order_id) if keep(l)], ser_line)

    @app.get("/order-lines")
    def _order_lines_all():
        gate("GET", "/order-lines")
        keep = _line_filters(flask_request.args)
        return paginated([l for l in db.order_lines.values() if keep(l)], ser_line)

    @app.get("/distribution-centers/<dc_id>/order-lines")
    def _dc_order_lines(dc_id):
        gate("GET", "/distribution-centers/<dc_id>/order-lines")
        get_dc(db, dc_id)
        keep = _line_filters(flask_request.args)
        rows = [l for l in db.order_lines.values()
                if l.get("allocated_dc_id") == dc_id and keep(l)]
        return paginated(rows, ser_line)

    # ----------------------------------------------------------- picking
    @app.post("/orders/<order_id>/lines/<line_id>/pick")
    def _line_pick(order_id, line_id):
        gate("POST", "/orders/<order_id>/lines/<line_id>/pick")
        order = get_order(db, order_id)
        line = get_line(db, order, line_id)
        return ok_object(ser_pick_task(start_pick(db, order, line, body_json())))

    @app.post("/orders/<order_id>/lines/<line_id>/pick_complete")
    def _line_pick_complete(order_id, line_id):
        gate("POST", "/orders/<order_id>/lines/<line_id>/pick_complete")
        order = get_order(db, order_id)
        line = get_line(db, order, line_id)
        return ok_object(ser_pick_task(complete_pick(db, order, line, body_json())))

    @app.get("/pick-tasks")
    def _pick_tasks():
        gate("GET", "/pick-tasks")
        args = flask_request.args

        def matches(task):
            for field in ("order_id", "line_id", "dc_id", "pick_status"):
                value = args.get(field)
                if value and task.get(field) != value:
                    return False
            return True

        return paginated([t for t in db.pick_tasks.values() if matches(t)], ser_pick_task)

    @app.get("/pick-tasks/<pick_id>")
    def _pick_task_get(pick_id):
        gate("GET", "/pick-tasks/<pick_id>")
        return ok_object(ser_pick_task(_pick_task(pick_id)))

    # --------------------------------------------------------- shipments
    @app.post("/orders/<order_id>/confirm_cutoff")
    def _confirm_cutoff(order_id):
        gate("POST", "/orders/<order_id>/confirm_cutoff")
        return ok_object(ser_shipment(confirm_cutoff(db, get_order(db, order_id), body_json())))

    @app.get("/shipments")
    def _shipments():
        gate("GET", "/shipments")
        args = flask_request.args

        def matches(shipment):
            for field in ("order_id", "dc_id"):
                value = args.get(field)
                if value and shipment.get(field) != value:
                    return False
            return True

        return paginated([s for s in db.shipments.values() if matches(s)], ser_shipment)

    @app.get("/shipments/<shipment_id>")
    def _shipment_get(shipment_id):
        gate("GET", "/shipments/<shipment_id>")
        return ok_object(ser_shipment(_shipment(shipment_id)))

    @app.post("/shipments/<shipment_id>/dispatch")
    def _shipment_dispatch(shipment_id):
        gate("POST", "/shipments/<shipment_id>/dispatch")
        return ok_object(ser_shipment(dispatch_shipment(db, _shipment(shipment_id))))

    # ----------------------------------------------------------- returns
    @app.post("/returns")
    def _return_create():
        user_id, role = gate("POST", "/returns")
        return ok_object(ser_return(create_return(db, user_id, role, body_json())), 201)

    @app.get("/returns")
    def _return_list():
        gate("GET", "/returns")
        args = flask_request.args

        def matches(auth):
            for field in ("order_id", "dc_id", "return_status"):
                value = args.get(field)
                if value and auth.get(field) != value:
                    return False
            return True

        return paginated([r for r in db.return_authorizations.values() if matches(r)],
                         ser_return)

    @app.get("/returns/<return_id>")
    def _return_get(return_id):
        gate("GET", "/returns/<return_id>")
        return ok_object(ser_return(get_return(db, return_id)))

    @app.post("/returns/<return_id>/approve")
    def _return_approve(return_id):
        gate("POST", "/returns/<return_id>/approve")
        return ok_object(ser_return(approve_return(db, get_return(db, return_id))))

    @app.post("/returns/<return_id>/receive")
    def _return_receive(return_id):
        gate("POST", "/returns/<return_id>/receive")
        return ok_object(ser_return(receive_return(db, get_return(db, return_id), body_json())))

    @app.post("/returns/<return_id>/cancel")
    def _return_cancel(return_id):
        gate("POST", "/returns/<return_id>/cancel")
        return ok_object(ser_return(cancel_return(db, get_return(db, return_id))))

    # ----------------------------------------------------- damage claims
    @app.get("/damage-claims")
    def _claims():
        gate("GET", "/damage-claims")
        args = flask_request.args

        def matches(claim):
            for field in ("order_id", "line_id", "claim_status"):
                value = args.get(field)
                if value and claim.get(field) != value:
                    return False
            return True

        return paginated([c for c in db.damage_claims.values() if matches(c)], ser_claim)

    @app.get("/damage-claims/<claim_id>")
    def _claim_get(claim_id):
        gate("GET", "/damage-claims/<claim_id>")
        return ok_object(ser_claim(get_claim(db, claim_id)))

    @app.post("/damage-claims/<claim_id>/resume_fulfillment")
    def _claim_resume(claim_id):
        gate("POST", "/damage-claims/<claim_id>/resume_fulfillment")
        return ok_object(ser_claim(resume_claim(db, get_claim(db, claim_id))))

    @app.post("/damage-claims/<claim_id>/resolve")
    def _claim_resolve(claim_id):
        gate("POST", "/damage-claims/<claim_id>/resolve")
        return ok_object(ser_claim(resolve_claim(db, get_claim(db, claim_id))))

    @app.post("/damage-claims/<claim_id>/reject")
    def _claim_reject(claim_id):
        gate("POST", "/damage-claims/<claim_id>/reject")
        return ok_object(ser_claim(reject_claim(db, get_claim(db, claim_id))))

    @app.post("/damage-claims/<claim_id>/void")
    def _claim_void(claim_id):
        gate("POST", "/damage-claims/<claim_id>/void")
        return ok_object(ser_claim(void_claim(db, get_claim(db, claim_id))))


def allocate(store, order, body):
    from svc_orders import allocate_order
    return allocate_order(store, order, body)