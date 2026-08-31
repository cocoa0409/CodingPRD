"""Payload factories -- input fields only, exactly as the PRD names them."""

import copy

# ---------------------------------------------------------------------------
# The documented ranking criteria used throughout the suite.  Weights sum to
# exactly 100, as the PRD demands, and codes never repeat.
# ---------------------------------------------------------------------------
STANDARD_CRITERIA = [
    {
        "criterion_code": "PERFORMANCE",
        "weight_pct": 50,
        "description": "Most recent performance rating",
    },
    {
        "criterion_code": "CRITICAL_SKILLS",
        "weight_pct": 30,
        "description": "Retained-skill criticality",
    },
    {
        "criterion_code": "TENURE",
        "weight_pct": 20,
        "description": "Length of continuous service",
    },
]

# 72*50/100 + 55*30/100 + 88*20/100 = 70.10
STANDARD_SCORES = [
    {"criterion_code": "PERFORMANCE", "score": 72},
    {"criterion_code": "CRITICAL_SKILLS", "score": 55},
    {"criterion_code": "TENURE", "score": 88},
]
STANDARD_COMPOSITE_SCORE = 70.10


# ---------------------------------------------------------------------------
# Roster people.  Each template is a complete roster-import entry / employee
# creation body minus site_id.
# ---------------------------------------------------------------------------
ALICE = {
    "full_name": "Alice Nunez",
    "job_title": "Senior Analyst",
    "birth_date": "1978-05-10",
    "hire_date": "2015-04-01",
    "annual_base_cents": 8700000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_A",
    "monthly_premium_cents": 90000,
}
BEN = {
    "full_name": "Ben Okafor",
    "job_title": "Analyst",
    "birth_date": "1990-02-20",
    "hire_date": "2020-01-15",
    "annual_base_cents": 6240000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_A",
    "monthly_premium_cents": 90000,
}
CARLA = {
    "full_name": "Carla Reyes",
    "job_title": "Ops Manager",
    "birth_date": "1972-11-05",
    "hire_date": "2018-06-01",
    "annual_base_cents": 7280000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_B",
    "monthly_premium_cents": 90000,
}
DAN = {
    "full_name": "Dan Whitfield",
    "job_title": "Ops Specialist",
    "birth_date": "1985-03-15",
    "hire_date": "2021-09-01",
    "annual_base_cents": 5720000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_B",
    "monthly_premium_cents": 90000,
}
ELENA = {
    "full_name": "Elena Torres",
    "job_title": "Ops Specialist",
    "birth_date": "1968-07-22",
    "hire_date": "2019-02-01",
    "annual_base_cents": 2600000,
    "weekly_hours": 16,
    "demographic_code": "CLASS_B",
    "monthly_premium_cents": 45000,
}
FARID = {
    "full_name": "Farid Haddad",
    "job_title": "Junior Analyst",
    "birth_date": "1995-01-30",
    "hire_date": "2026-07-01",
    "annual_base_cents": 5200000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_C",
    "monthly_premium_cents": 90000,
}
# Grace as the high-salary rounding-order subject (8 completed years).
GRACE = {
    "full_name": "Grace Lindqvist",
    "job_title": "Principal Engineer",
    "birth_date": "1980-12-01",
    "hire_date": "2018-06-01",
    "annual_base_cents": 9455000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_A",
    "monthly_premium_cents": 90000,
}
# Grace as the CLASS_C member of the eight-person analysis pool.
GRACE_CLASS_C = {
    "full_name": "Grace Lindqvist",
    "job_title": "Principal Engineer",
    "birth_date": "1980-12-01",
    "hire_date": "2017-03-20",
    "annual_base_cents": 9880000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_C",
    "monthly_premium_cents": 90000,
}
HIRO = {
    "full_name": "Hiro Tanaka",
    "job_title": "Analyst",
    "birth_date": "1993-06-18",
    "hire_date": "2022-08-08",
    "annual_base_cents": 6760000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_A",
    "monthly_premium_cents": 90000,
}
# Ivy's annual base divides to exactly 95000 cents a week.
IVY = {
    "full_name": "Ivy Sorensen",
    "job_title": "Staff Engineer",
    "birth_date": "1978-05-10",
    "hire_date": "2019-02-01",
    "annual_base_cents": 4940000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_A",
    "monthly_premium_cents": 90000,
}
OMAR = {
    "full_name": "Omar Diallo",
    "job_title": "Ops Specialist II",
    "birth_date": "1988-04-04",
    "hire_date": "2019-02-01",
    "annual_base_cents": 3120000,
    "weekly_hours": 20,
    "demographic_code": "CLASS_B",
    "monthly_premium_cents": 45000,
}
PRIYA = {
    "full_name": "Priya Raman",
    "job_title": "Senior Analyst",
    "birth_date": "1992-09-09",
    "hire_date": "2026-08-01",
    "annual_base_cents": 8320000,
    "weekly_hours": 40,
    "demographic_code": "CLASS_C",
    "monthly_premium_cents": 90000,
}

# A CLASS_B twin of Ben.  The adverse-impact pool needs at least two
# demographic classes before a reference group exists at all, so scenarios that
# select a single CLASS_A person pair them with this person and leave that
# second proposal undecided: a PROPOSED selection joins the analysis pool while
# touching no headcount, no site counter and no plan selected_count.
BEN_CLASS_B = dict(BEN, demographic_code="CLASS_B")


def employee_entry(template: dict, **overrides) -> dict:
    """A roster-import entry built from one of the people templates."""
    entry = copy.deepcopy(template)
    entry.update(overrides)
    return entry


def create_employee_payload(site_id: str, template: dict = None, **overrides) -> dict:
    """Body for POST /employees."""
    payload = copy.deepcopy(template if template is not None else ALICE)
    payload["site_id"] = site_id
    payload.update(overrides)
    return payload


def create_site_payload(**overrides) -> dict:
    payload = {"name": "Austin Campus", "state_code": "TX", "is_single_site": True}
    payload.update(overrides)
    return payload


def create_reduction_plan_payload(**overrides) -> dict:
    payload = {
        "name": "Austin Reduction",
        "decisional_unit_name": "Austin Operations",
        "selection_criteria": copy.deepcopy(STANDARD_CRITERIA),
        "severance_budget_cents": 20000000,
    }
    payload.update(overrides)
    return payload


def create_selection_payload(plan_id: str, employee_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "employee_id": employee_id,
        "proposed_separation_date": "2026-12-01",
        "criterion_scores": copy.deepcopy(STANDARD_SCORES),
    }
    payload.update(overrides)
    return payload


def selection_batch_payload(employee_ids, **overrides) -> dict:
    payload = {
        "employee_ids": list(employee_ids),
        "proposed_separation_date": "2026-12-01",
        "criterion_scores": copy.deepcopy(STANDARD_SCORES),
    }
    payload.update(overrides)
    return payload


def roster_import_payload(entries) -> dict:
    return {"entries": [copy.deepcopy(e) for e in entries]}


# ---------------------------------------------------------------------------
# WARN statute rows
# ---------------------------------------------------------------------------
def federal_rule_payload(**overrides) -> dict:
    payload = {
        "jurisdiction": "FEDERAL",
        "state_code": "US",
        "rule_code": "FED-WARN-1988",
        "min_loss_count": 3,
        "min_percent": 33.0,
        "absolute_count": 20,
        "notice_days": 60,
        "window_days": 90,
        "counts_part_time": False,
        "min_service_days": 180,
        "required_content_codes": [
            "EMPLOYER_NAME",
            "SITE_ADDRESS",
            "SEPARATION_DATE",
        ],
    }
    payload.update(overrides)
    return payload


def ny_state_rule_payload(**overrides) -> dict:
    payload = {
        "jurisdiction": "STATE",
        "state_code": "NY",
        "rule_code": "NY-MINI-WARN",
        "min_loss_count": 2,
        "min_percent": 25.0,
        "absolute_count": 10,
        "notice_days": 90,
        "window_days": 30,
        "counts_part_time": True,
        "min_service_days": 0,
        "required_content_codes": [
            "EMPLOYER_NAME",
            "SITE_ADDRESS",
            "SEPARATION_DATE",
            "UNION_NOTICE",
            "JOB_TITLES_AFFECTED",
        ],
    }
    payload.update(overrides)
    return payload


def tx_state_rule_payload(**overrides) -> dict:
    payload = {
        "jurisdiction": "STATE",
        "state_code": "TX",
        "rule_code": "TX-MINI-WARN",
        "min_loss_count": 1,
        "min_percent": 50.00,
        "absolute_count": 0,
        "notice_days": 60,
        "window_days": 60,
        "counts_part_time": True,
        "min_service_days": 0,
        "required_content_codes": ["EMPLOYER_NAME", "SITE_ADDRESS"],
    }
    payload.update(overrides)
    return payload


NY_NOTICE_CONTENT = [
    "EMPLOYER_NAME",
    "SITE_ADDRESS",
    "SEPARATION_DATE",
    "UNION_NOTICE",
    "JOB_TITLES_AFFECTED",
]
FEDERAL_NOTICE_CONTENT = ["EMPLOYER_NAME", "SITE_ADDRESS", "SEPARATION_DATE"]
TX_NOTICE_CONTENT = ["EMPLOYER_NAME", "SITE_ADDRESS"]


def warn_notice_payload(plan_id, site_id, jurisdiction, content_codes) -> dict:
    return {
        "plan_id": plan_id,
        "site_id": site_id,
        "jurisdiction": jurisdiction,
        "content_codes": list(content_codes),
    }
