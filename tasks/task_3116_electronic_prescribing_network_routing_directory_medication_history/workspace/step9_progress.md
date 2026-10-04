# task_3116 — step 9 progress (PRD_COMPLETED.md)

Base: `cp PRD_FINALIZED.md PRD_COMPLETED.md` (both 386 lines / 87435 chars at base).
Edits are in-place line replacements (line count stays ~386).

## Verified impl facts (from reading implementation/)
- `ERR_ENDPOINT_NOT_ROUTED_ATTEMPT` NEVER raised (report undeliverable always degrades the attempt's own target_endpoint_id) — prescriptions.py:745-751.
- `ERR_FALLBACK_NOT_PERMITTED` NEVER reached: `PATIENT_UNKNOWN`/`BENEFIT_EXHAUSTED` are outside UNDELIVERABLE_FAILURE_CODES, so line 733-734 raises ERR_INVALID_STATE first — prescriptions.py:733-736.
- Suspension: PRD_FINALIZED:200 already has no `ERROR_ROUTE_NO_ENDPOINT` (step 8 removed it). Nothing to do.
- Route path recomputes endpoint counters and degrades winner when ratio<0.90, then recomputes directory_listed — prescriptions.py:355-358.
- Benefit resolve: PAYER -> (NON_PREFERRED, ACTIVE); else (UNKNOWN, UNKNOWN) — benefit.py:38-48.
- Dedupe rank 3rd key `fill_date` ASCENDING (earlier wins) — history.py:165-171. PRD says "later fill_date wins" -> MISMATCH.
- 404/405 route-level refusals return ERR_INVALID_REQUEST at 404/405 (not 400) and never name a field — app.py:57-89.
- auth: open paths (path=="/network/" or startswith "/_") skip missing-role refusal AND entity-resolution; unrecognized role still 401 — request_context.py:41-65.
- sign: clinical_status must be DRAFT/SIGNED (extra precondition) — prescriptions.py:241-242.
- report-rejected sets routing_status ROUTE_FAILED when in ROUTED/BACKUP_SELECTION/FALLBACK_SENT/FALLBACK_PENDING — prescriptions.py:845-847.
- benefit estimate needs ACTIVE BENEFIT_CHECK/BOTH consent else ERR_CONSENT_REQUIRED — benefit.py:53-55.

## Edits APPLIED (16 changed lines)
1. §2.9 — 404/405 statuses + route-level refusals name no field (app.py:57-89)
2. §2.1 — open paths skip missing-role + entity resolution (request_context.py:41-65)
3. §2.6 — degrade gate now also on the route path, not only reporting (prescriptions.py:355-358)
4. §3.3 — sign requires clinical_status DRAFT/SIGNED, non-consuming refusal (prescriptions.py:241-242)
5. §3.4 — route recomputes winner counters + directory_listed (prescriptions.py:355-358)
6. §3.5 — PATIENT_UNKNOWN/BENEFIT_EXHAUSTED outside the vocab; exception unreachable (prescriptions.py:733-736)
7. §3.5 — ERR_ENDPOINT_NOT_ROUTED_ATTEMPT never raised; single-endpoint degrade exempt (prescriptions.py:745-751; directory.py:166-189)
8. §3.5 rejection — routing_status -> ROUTE_FAILED band (prescriptions.py:845-847)
9. §3.8 — dedupe fill_date ASCENDING = earlier wins (MISMATCH) (history.py:165-171)
10. §3.9 — PAYER -> NON_PREFERRED/ACTIVE; else UNKNOWN/UNKNOWN (benefit.py:38-48)
11. §3.9 — missing benefit consent -> ERR_CONSENT_REQUIRED (benefit.py:53-55)
12. §2.6 — last-active guard only when another ACTIVE endpoint remains (certification.py:169-196)
13. §3.6 — same guard, same pin (certification.py:169-196)
14. §3.7 — settled_count vs chargeable_sum read split (billing.py:75-95,234)
15. §3.7 — correction row's own transaction_count/fee_cents (billing.py:258-276)
16. §3.5 cancel — clinical-status branch first + significance gate in safety band (prescriptions.py:429-450)
17. §3.2 — endpoint-row requirement evaluated first, no status barred (certification.py:49-83)
18. §3.8 — consent gate before status band for aggregate (history.py:199-224)
19. §3.8 — deductible advance = payer's plan_copay_cents, saturating (history.py:265-286)

## Verified by in-process probe (no ports)
- 404 body: `ERR_INVALID_REQUEST` @404, message "No route is declared for GET /network/nope."; 405: `ERR_INVALID_REQUEST` @405; `DELETE /network/participants?limit=999` -> 405 (no field named).
- participant with ACTIVE NEW_RX + ACTIVE BENEFIT_COST: disabling the NEW_RX one -> 200, DISABLED, directory_listed still True (guard did not fire).
- suspend: attempt outcome=UNDELIVERABLE failure_code=NO_ROUTE, wire keys do NOT include `error_code_returned` value (None) and no ERROR_ROUTE_NO_ENDPOINT.
- fee cell: CHARGE POSTED tc=500, then two PARTIAL CHARGE tc=1, then the second ack's CORRECTION tc=0 prev=500 new=501; all rows pnet=3600.

## Status
- [x] edits applied (19 edits over 15 changed lines)
- [x] verified by probe
- [x] summary written

## Counts
- ambiguity pins: 15
- mismatch revisions: 4 (§2.9 404/405; §3.5 ERR_FALLBACK_NOT_PERMITTED; §3.5 ERR_ENDPOINT_NOT_ROUTED_ATTEMPT; §3.8 dedupe fill_date)
- line count 386 -> 386; char delta +4648 (87435 -> 92110)
- Step-8 leads NOT acted on: suspension ERROR_ROUTE_NO_ENDPOINT — PRD_FINALIZED line 200 already omitted it (step 8 removed it), so nothing to pin.