"""Route blueprints, one module per resource group."""

from . import clock, universities, students, employers, approvals, postings, events, signups, applications, outreach

BLUEPRINTS = [
    clock.bp,
    universities.bp,
    students.bp,
    employers.bp,
    approvals.bp,
    postings.bp,
    events.bp,
    signups.bp,
    applications.bp,
    outreach.bp,
]
