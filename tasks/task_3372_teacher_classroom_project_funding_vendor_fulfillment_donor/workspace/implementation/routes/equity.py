"""Equity funds: create with closed-interval overlap-or-touch guard; read;
allocate (waterfall selector)."""
import store
from envelope import ok
from errors import bad_request, conflict, invalid_state, not_found, unprocessable
from security import actor, require_roles
from serializers import donation_json, equity_fund_json
from services import funding as funding_service
from util_time import parse_dt
from validators import (
    SUBJECTS,
    as_enum,
    as_int,
    as_num,
    as_str,
    json_body,
    require_present,
)


def register(app):
    @app.route("/giving/equity-funds", methods=["POST"])
    def create_fund():
        data = json_body()
        name = as_str(require_present(data, "name"), "name")
        state_code = as_str(require_present(data, "state_code"), "state_code")
        min_poverty_pct = as_num(require_present(data, "min_poverty_pct"), "min_poverty_pct")
        if not (0.0 <= min_poverty_pct <= 100.0):
            raise bad_request("min_poverty_pct must lie between 0.0 and 100.0 inclusive")
        budget_cents = as_int(require_present(data, "budget_cents"), "budget_cents")
        if budget_cents < 1:
            raise bad_request("budget_cents must be at least 1")
        window_start = parse_dt(require_present(data, "window_start"))
        if window_start is None:
            raise bad_request("window_start must be an ISO 8601 timestamp")
        window_end = parse_dt(require_present(data, "window_end"))
        if window_end is None:
            raise bad_request("window_end must be an ISO 8601 timestamp")
        subject = None
        if "subject" in data and data["subject"] is not None:
            subject = as_enum(data["subject"], "subject", SUBJECTS)
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        # Closed interval: overlap OR touch conflicts (sharing a boundary day
        # already conflicts). Only ACTIVE funds block.
        for existing in store.equity_funds.values():
            if (
                existing["status"] == "ACTIVE"
                and existing["state_code"] == state_code
                and existing["window_start"] <= window_end
                and window_start <= existing["window_end"]
            ):
                raise conflict(
                    "ERR_EQUITY_WINDOW_OVERLAP",
                    "Window overlaps or touches an ACTIVE fund with the same state_code",
                )
        rec = store.base_record()
        rec.update({
            "name": name,
            "state_code": state_code,
            "subject": subject,
            "min_poverty_pct": float(min_poverty_pct),
            "budget_cents": budget_cents,
            "remaining_cents": budget_cents,
            "window_start": window_start,
            "window_end": window_end,
            "status": "ACTIVE",
        })
        store.equity_funds[rec["id"]] = rec
        return ok(equity_fund_json(rec), 201)

    @app.route("/giving/equity-funds/<fund_id>", methods=["GET"])
    def get_fund(fund_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Reviewer", "Donor"))
        fund = store.equity_funds.get(fund_id)
        if fund is None:
            raise not_found("Equity fund not found")
        return ok(equity_fund_json(fund), 200)

    @app.route("/giving/equity-funds/<fund_id>/allocate", methods=["POST"])
    def allocate(fund_id):
        json_body()  # no request body is required; ignore any payload
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        fund = store.equity_funds.get(fund_id)
        if fund is None:
            raise not_found("Equity fund not found")
        if fund["status"] != "ACTIVE":
            raise invalid_state("Only an ACTIVE fund can allocate")
        now = store.logical_now()
        if not (fund["window_start"] <= now <= fund["window_end"]):
            raise conflict("ERR_EQUITY_WINDOW_CLOSED", "The fund's window does not cover now")
        candidates = []
        for project in store.projects.values():
            if project["status"] != "FUNDING":
                continue
            if project["funding_deadline"] is None or not (now < project["funding_deadline"]):
                continue
            school = store.schools.get(project["school_id"])
            if school is None:
                continue
            if school["state_code"] != fund["state_code"]:
                continue
            if not (school["poverty_pct"] >= fund["min_poverty_pct"]):
                continue
            if fund["subject"] is not None and project["subject"] != fund["subject"]:
                continue
            candidates.append((project, school))
        if not candidates:
            raise unprocessable("ERR_NO_ELIGIBLE_PROJECT", "No eligible FUNDING project")
        # Weighted equity score DESC, project created_at ASC (only tie-break).
        candidates.sort(
            key=lambda pair: (
                -pair[1]["equity_score_weighted"],
                pair[0]["created_at"],
                pair[0]["_seq"],
            )
        )
        project, _ = candidates[0]
        amount = min(
            project["goal_cents"] - funding_service.funded_cents(project),
            fund["remaining_cents"],
        )
        rec = store.base_record()
        rec.update({
            "project_id": project["id"],
            "donor_id": None,
            "kind": "EQUITY_GRANT",
            "amount_cents": amount,
            "match_campaign_id": None,
            "matched_cents": 0,
            "equity_fund_id": fund["id"],
            "status": "CAPTURED",
            "choice_deadline": None,
            "refund_reason": None,
        })
        store.donations[rec["id"]] = rec
        fund["remaining_cents"] -= amount
        if fund["remaining_cents"] == 0:
            fund["status"] = "DEPLETED"
        store.touch(fund)
        funding_service.check_funded(project, now)
        return ok(donation_json(rec), 200)
