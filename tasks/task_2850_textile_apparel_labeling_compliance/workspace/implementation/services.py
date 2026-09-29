"""Shared state-transition services and the cascade discipline of PRD 2.9."""
import calc
from store import db, ordered, touch

CASCADE_PERMANENT_STATES = ("PENDING_APPROVAL", "APPROVED", "PUBLISHED")
CASCADE_HANGTAG_STATES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "PUBLISHED")


def _withdraw(spec, reason):
    spec["state"] = "WITHDRAWN"
    spec["withdrawn_reason"] = reason
    touch(spec)


def withdraw_hangtags_of(parent_ids):
    """Final hop of every cascade: pull the hangtags of the pulled parents."""
    for spec in ordered(list(db.label_specs.values())):
        if spec["artifact_type"] != "HANGTAG":
            continue
        if spec["parent_label_spec_id"] not in parent_ids:
            continue
        if spec["state"] in CASCADE_HANGTAG_STATES:
            _withdraw(spec, "AUTO_PARENT_WITHDRAWN")


def fiber_misstated_cascade(style):
    """HOP 2..4 of the fiber-misstatement cascade (PRD 3.4)."""
    style["substantiation_state"] = "FIBER_MISSTATED"
    touch(style)
    pulled = []
    for spec in ordered(list(db.label_specs.values())):
        if (spec["style_id"] == style["id"]
                and spec["artifact_type"] == "PERMANENT_LABEL"
                and spec["state"] in CASCADE_PERMANENT_STATES):
            _withdraw(spec, "AUTO_FIBER_MISSTATED")
            pulled.append(spec["id"])
    withdraw_hangtags_of(set(pulled))


def origin_void_cascade(style):
    """HOP 2..4 of the origin-void cascade (PRD 3.3)."""
    determination = calc.current_issued_determination(style["id"])
    if determination is None:
        return
    determination["state"] = "VOID"
    touch(determination)
    pulled = []
    for spec in ordered(list(db.label_specs.values())):
        if (spec["origin_determination_id"] == determination["id"]
                and spec["state"] in CASCADE_PERMANENT_STATES):
            _withdraw(spec, "AUTO_ORIGIN_VOIDED")
            pulled.append(spec["id"])
    withdraw_hangtags_of(set(pulled))


def supersede_passed_fiber_tests(style_id, except_id=None):
    for test in ordered(list(db.lab_tests.values())):
        if (test["style_id"] == style_id and test["test_type"] == "FIBER_CONTENT"
                and test["state"] == "PASSED" and test["id"] != except_id):
            test["state"] = "SUPERSEDED"
            touch(test)


def supersede_passed_tests(style_id, test_type, except_id=None):
    for test in ordered(list(db.lab_tests.values())):
        if (test["style_id"] == style_id and test["test_type"] == test_type
                and test["state"] == "PASSED" and test["id"] != except_id):
            test["state"] = "SUPERSEDED"
            touch(test)


def brand_of_record_row(brand_id):
    brand = db.brands.get(brand_id)
    if brand is None:
        return None
    return db.brands.get(calc.responsible_of(brand))


def live_permanent_labels(style_id):
    """Permanent labels of a style that have already asserted the declaration."""
    return [s for s in db.label_specs.values()
            if s["style_id"] == style_id and s["artifact_type"] == "PERMANENT_LABEL"
            and s["state"] in CASCADE_PERMANENT_STATES]
