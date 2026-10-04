# Worklog — task_3497_detention_demurrage_complaint_adjudication_carrier_filings

Scenario: Detention and Demurrage Complaint Adjudication & Carrier Filings (Federal Maritime Commission) — tariff/service contract filing + publication, D&D complaint intake with incentive-principle framework, invoice billing-practice requirements + dispute timelines, ombuds informal resolution + formal adjudication with reparations, carrier agreement filing/review with monitoring reports, OTI licensing with bonding, unreasonable practice determinations + civil penalties, port congestion / carrier performance data collection.

Difficulty instruction passed to scaffold generator: "Generate task much harder than expert level!"

## Step 1: Create Task Directory — 2026-10-02T18:33:00.000Z

Pre-allocated directory `tasks/task_3497_detention_demurrage_complaint_adjudication_carrier_filings/` verified present with `workspace/` inside (mkdir -p, idempotent; no new index computed, no other task_* dir created).

## Step 2: Scaffold Generation — 2026-10-02T19:20:00.000Z

Orchestrator note: archetype compliance_audit + ledger_reconciliation; segregation_of_duties role model; logical clock default 2026-09-01T00:00:00Z. Subagent's verbatim hand-back report follows:

Scaffold generation complete. Final summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3497_detention_demurrage_complaint_adjudication_carrier_filings/SCAFFOLD.yaml` — 1389 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3497_detention_demurrage_complaint_adjudication_carrier_filings/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1117 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3497_detention_demurrage_complaint_adjudication_carrier_filings/SCAFFOLD_CORNER_DESIGN.yaml` — 2631 lines

## Counts
- **11 entities** (CarrierOrganization, ShipperAccount, TariffPublication, ServiceContract, CarrierAgreement with embedded monitoring reports, OTILicense with embedded surety bonds, DemurrageDetentionInvoice, InvoiceDispute, Complaint absorbing ombuds+adjudication lifecycle, EnforcementProceeding, append-only PortCongestionReport)
- **41 endpoints** (40 business under `/fmc` + `POST /_clock/set_current_utc` outside the prefix, default 2026-09-01T00:00:00Z)
- **57 error codes**, all wired to validations/transitions and exercised by at least one design instance
- 7 calculations, 10 state machines, 16 ordered validation rows, 2 OCC concurrency rules, 8 roles (2 entity-backed, segregation_of_duties between OmbudsOfficer and AdministrativeLawJudge)
- **§1.8: 18 instances** (9 rules × 2, all with structured replayable recipes and pre-computed literal asserts)
- **§1.9: 64 non-stub instances + 4 excluded_because stubs** across all nine taxonomy sections

Lint verdict (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(41 endpoints, 11 entities, 18 + 64 instances, 780 calls scanned, exit 0.)

## Difficulty mechanisms (beyond-expert via density)
- Dual-variant calcs in two domains: invoice accrual CALENDAR vs WORKING_DAY (105000 vs 60000 on identical inputs); reparation OUT_OF_POCKET vs FLUIDITY_WEIGHTED selected by a frozen incentive-principle score (110250 vs 200000-capped)
- Combinatorial modes (a)+(b): civil penalty `vc × 1M × willful×2 × repeat×1.5, min-cap 100M`; HHI with pinned nested rounding (5555.60 vs naive 5555.56)
- Cyclic machines: Complaint ombuds rounds (limit 2), Invoice ISSUED⇄DISPUTED; branching fork DECIDED→{APPEALED→FINAL|REVERSED}
- Depth-5 enforcement cascade (determine→score→carrier SUSPENDED→tariffs→invoices VOIDED→disputes auto-waived) and depth-3 bond cascade (draw→EXHAUSTED→license SUSPENDED→contracts SUSPENDED) with compensating reversal paths
- Boundary pins: dispute deadline exact-second, bond coverage ==, HHI ≥ 2500 at exactly 2500.00, score < 600 at exactly 600, all filing windows inclusive-at-deadline

## Interpretations chosen for ambiguous scenario text
1. **Bonds and monitoring reports are embedded arrays** on OTILicense/CarrierAgreement (kept endpoint count at the 40 safety line); bond_ref is filer-chosen (unique per license) so draws need no server-minted bond id.
2. **Complaint absorbs ombuds + adjudication** as lifecycle dimensions (1:1 in practice), carrying `ombuds_officer_id`/`presiding_judge_id` for the segregation-of-duties rule (the complaint's latest ombuds officer may not adjudicate it).
3. **Late dispute response** is not an error: any respond after `filed_at + 30d` is accepted but forced to UPHELD_WAIVED, voids the invoice, and docks the carrier 25 score points (mirrors the FMC billing-rule remedy).
4. **Concrete constants pinned** where the scenario only gestured: 30-day invoice issuance / dispute response / service-contract filing / appeal windows, 45-day agreement waiting period, 180-day complaint window, NVOCC $75k / OFF $50k bonds, HHI 2500, port-week capacity 672 berth-hours (per-terminal reports capped at 168).
5. **Cascade voids only non-terminal invoices** (PAID survives), and complaint intake **freezes** the incentive score against later-filed congestion data.
6. Fixed two authoring incidents en route: a mangled heredoc injected 2 garbage lines (removed, revalidated), and an over-range per-report occupancy fixture (580/672 in one report violated the ≤168 per-terminal cap — split into multi-terminal reports summing to 572/672, preserving the intended 0.85 threshold crossing).

Orchestrator verification after Step 2: all three YAMLs parse (yaml.safe_load), correct top-level keys (SCAFFOLD.yaml lacks both design keys; design files carry their single keys), domain markers dense (293/358/691 demurrage|detention|fmc|carrier|ombuds hits), api_prefix=/fmc with `/_clock/set_current_utc` unprefixed as reported. No foreign-domain contamination.

## Step 3: Copy Shared Files — 2026-10-02T20:06:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: PRD Generation — 2026-10-02T20:20:00.000Z

Subagent's verbatim hand-back report follows:

All checks pass on the final file. The PRD is complete and verified.

## Report

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3497_detention_demurrage_complaint_adjudication_carrier_filings/workspace/PRD.md` — 336 lines.

**Sections:** §1 Introduction (2 paragraphs, regulatory-context angle); §2 Global Specifications with 10 subsections (2.1 RBAC, 2.2 API Response Structure [byte-identical to `section-2.2-response-structure.md` — verified by diff], 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Monetary Values/Integer Cents/Rounding, 2.7 Validation Discipline: Ordering and First Failure Wins, 2.8 Nested Resource Retrieval, 2.9 Optimistic Concurrency Control, 2.10 Compliance Standing and Automatic Enforcement Cascades); §3 Business Logic with 9 domain-derived subsections (registration → tariffs → contracts → licensing/bonds → invoicing → disputes → complaints → agreements/monitoring → enforcement/congestion-data); §4 Endpoint table (41 rows, 4 columns); §5 Error catalogue (57 rows, 2 columns).

**Hard Contract results (mechanically audited against SCAFFOLD.yaml):**
- Contract 1, field coverage: entities 96/96, request-body 73/73, query-param 11/11, path-param 11/11 — 0 missing. PASS.
- Contract 2, rule coverage: 16 validation-priority rungs expressed as an ordered first-failure ladder (§2.7, including within-rung-6.5 ordering and OCC-last); 2/2 OCC rules with `expected_carrier_version`/`expected_license_version` + `ERR_STALE_VERSION` (412) in pure stale-version framing; 26/26 state transitions with preconditions and side effects; 7/7 calculations in precise prose (pinned rounding orders for HHI and reparations, pinned penalty order, both accrual variants); 57/57 error ids matchable to triggers in §2/§3 prose; sibling branches (WAIVE/REDUCE/DENY, SETTLED/FAILED, AFFIRM/REVERSE, VIOLATION_FOUND/NO_VIOLATION, CALENDAR/WORKING_DAY, OUT_OF_POCKET/FLUIDITY_WEIGHTED) rendered at equal density. PASS.
- Contract 3, §3 path purity: 459 backtick tokens scanned, 0 violations (no paths, no bare methods, no method+path). PASS.
- Supplementary: 65/65 state and enum strings present verbatim; zero fuzzy words; zero pseudocode operators outside fences.

**KNOWN-AMBIGUITY sites** (for the downstream Step-4/Step-8 ambiguity feed):

1. **§2.7 rung 3 vs rung 4** (validations priority 3 vs 4): numeric priority puts ownership before existence, but the scaffold check text defers ownership when a path id doesn't resolve. I rendered the explicit deferral (404 precedes ownership comparison). A reader keying on numeric order alone could invert them.
2. **§3.8 agreement membership** (`member_carrier_ids` constraint vs `ERR_INVALID_AGREEMENT_MEMBERSHIP` condition): entity constraint says "distinct VOCCs + filer is member"; error catalog adds "/ACTIVE". I rendered the union (distinct, all VOCC *and* ACTIVE, filer included).
3. **§3.4 bond-cascade restore asymmetry** (OTILicense `PENDING_BOND→ACTIVE` vs `SUSPENDED→ACTIVE` side effects): scaffold restores "contracts suspended by this license's coverage loss" on first activation but *all* SUSPENDED contracts on reactivation. Rendered verbatim; a reader could uniformize in either direction.
4. **§3.3/§3.5 license gating multiplicity** (priority 6.5): scaffold doesn't state whether a carrier may hold multiple OTI licenses or which one gates. Rendered existentially: "must hold an ACTIVE OTI license" — absence of any ACTIVE license (none, or only PENDING_BOND/SUSPENDED) fails uniformly with `ERR_LICENSE_NOT_ACTIVE`.
5. **§3.5 date-coherence "now"** (priority 5.5, `ERR_INVALID_INVOICE_DATES`): rendered as "no later than the issuance instant" read from the logical clock.
6. **§3.6 timely/late boundary** (`clock <= response_due_at`): pinned "on or before the deadline is timely; any instant after is late" — boundary inclusivity is the classic divergent reading here.
7. **§3.7 complaint filing window anchor** (`max(subject issued_at) + 180 days`): rendered as "180 days after the most recently issued of its subject invoices" — latest-vs-earliest anchor is a plausible misreading.
8. **§3.7 ombuds round limit** (`ombuds_rounds < 2`): rendered "permitted only while below two" — equality at 2 rejects.
9. **List-filter combination semantics**: scaffold never states how multiple query filters combine; §3.5 says invoice filters "may be combined to narrow the result set" (implicit AND), other listings just name their filters.
10. **Cascade mutation bookkeeping**: scaffold side_effects don't state per-resource `version`/`updated_at` bumps inside cascades; §2.5/§2.10 assert every mutation including cascade-driven ones refreshes `updated_at` and increments `version`, generalized from the common-fields contract.
11. **`repeat_offender` ordering** (EnforcementProceeding): "determination order, not wall-clock ordering, decides" rendered as-is in §3.9; depends on server processing order.
12. **Clock endpoint placement**: §2.4 states it is "mounted outside the `/fmc` business surface" (startup value `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc` named); the literal path `/_clock/set_current_utc` appears only in §4 per Contract 3.

Orchestrator verification after Step 4: PRD.md present at 336 lines, 93 lines mention ERR_* ids, logical-clock + 3-fractional-digit api_request_timestamp rendering present.

## Step 5: Unit Test Generation — 2026-10-02T20:55:00.000Z

Subagent's verbatim hand-back report follows:

All verification passes are green. Final summary:

## Summary

**Measured queue sizes (parsed from the YAMLs myself):**
- Queue A (difficulty): **18 instances** across 9 rules, all non-stub
- Queue B (corner): **64 non-stub instances** + 4 `excluded_because:` stubs (all 4 stub cross-references resolve to real queue-A instances; not translated)

**Tests emitted: 98 total** — 34 for queue A (17 instances × 2) + 64 for queue B (64 × 1).

**Instances skipped (PRD-first two-condition filter):**
1. `Difficulty/combinatorial_formula/monitoring_hhi_nested_rounding_order_pinned` (both of its queue-A tests) — fails **unique derivability**. The instance's pre-computed literals (contribution 4444.49, HHI 5555.60) contradict the PRD §3.8 pinned formula for its own inputs (volumes [1,2] of 3): share round-half-up to 4dp gives 33.3333/66.6667, squares to 2dp give 1111.11/4444.45, sum **5555.56** — identical to the raw-unrounded result the instance calls non-conformant (5555.56). 4444.49 would require a 3-decimal share (66.667), violating the PRD's 4-decimal rule. The instance's distinguishing claim is arithmetically false; asserting its literal would fail a correct PRD implementation, and asserting the PRD-derived value would be a different test. Gap stays a gap.

**Deliberate adjudication (not a skip):** `carrier_create_..._system_defaults` asserts `version == 1` in the YAML, but the PRD says only "starts at creation and increments by one" without pinning the initial literal — I assert presence/type there and use relative (v+1) assertions in the OCC tests, which are PRD-pinned.

**Files written:**
- `test_helpers/`: `types.py`, `api_client.py` (clock endpoint correctly mounted outside `/fmc`), `api_errors.py` (48 errors registered with the framework status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance builders for the entity-backed CarrierRep/ShipperRep roles), `fixtures.py` (tiered composite setups), `__init__.py`
- `test_suite/`: `conftest.py` + `test_01_registration_envelope.py` … `test_11_congestion_and_listings.py` (11 files, domain-clustered)

**Verification results:**
- **AST tag audit:** 98 tests, 0 untagged, 0 dual-tagged, 0 dangling tags, every `Design:` line is the docstring's final line; queue B 64/64 covered, queue A 17/18 at ≥2 (the one shortfall is the documented skip).
- **Citation sweep (C1):** 159 quoted docstring fragments extracted via AST — all grep verbatim against `workspace/PRD.md` (1 initially failing fragment had a stray period; fixed and re-verified to 0 failures).
- **`pytest --collect-only -q` (PYTHONPATH=.):** 98 tests collected, 0 errors — the package graph has no dangling imports.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- Clock discipline: every fixture drives `POST /_clock/set_current_utc` starting from 2026-09-01T00:00:00Z; creates asserted at 201; `api_request_timestamp`/`created_at`/`updated_at` asserted with the 3-fractional-digit format while domain timestamps (`filed_at`, `response_due_at`, `waiting_period_ends_at`, `decided_at`, `appeal_deadline`) are asserted as the clock reads (e.g. `"2026-10-10T09:30:00Z"`), never a uniform serializer.

Orchestrator verification after Step 5: test_helpers/ has all 9 expected files + test_suite/ has conftest.py + 11 domain test files; grep counts 98 test functions and 98 Design tags; independent `pytest --collect-only` collects 98 tests with 0 errors. NOTE for Step 7/8: the skipped HHI instance means SCAFFOLD_DIFFICULTY_DESIGN's pre-computed HHI literal (5555.60) contradicts the PRD §3.8 formula result (5555.56) for the same inputs — PRD wins; if any HHI failure appears at Step 7, re-derive from PRD before touching tests or impl.

## Step 6: Implementation Generation — 2026-10-02T21:30:00.000Z

Subagent's verbatim hand-back report follows:

All checks pass and the environment is clean. The implementation is complete.

## Files written (all under `.../workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded `pip install`, `exec python3 app.py`, `PORT` default 10000, binds 0.0.0.0 |
| `requirements.txt` | 1 | flask |
| `app.py` | 53 | Flask entry, blueprint registration, ApiError handler |
| `clock.py` | 73 | Logical clock (boot default 2026-09-01T00:00:00Z), two timestamp rendering families |
| `errors.py` | 90 | Full 57-id catalog with HTTP statuses; `fail()` looks up status from catalog |
| `constants.py` | 52 | All pinned calculation constants (Fractions/Decimals where precision matters) |
| `store.py` | 48 | In-memory dicts only, no seeding; dashed `str(uuid.uuid4())` ids; `touch()` |
| `envelope.py` | 75 | `meta`/`response_type`/`data` envelope, pagination (`limit`/`offset`/`total_count`/`has_more`) |
| `auth.py` | 43 | Rung-1 header check + rung-2 role gate (8 roles) |
| `util.py` | 86 | Body/scalar/enum/datetime validators |
| `serialization.py` | 230 | Explicit per-entity serializers (internal keys never leak) |
| `services/calc.py` | 141 | Invoice day-count (CALENDAR/WORKING_DAY), incentive score, reparation award, HHI, penalty, score delta |
| `services/cascades.py` | 92 | Carrier-suspension cascade, bond-coverage ledger + license/contract cascade |
| `routes/carriers.py` `tariffs.py` `contracts.py` `agreements.py` `licenses.py` `invoices.py` `disputes.py` `complaints.py` `enforcement.py` `congestion.py` `clock_route.py` | 66–283 each | One module per domain cluster; all 41 endpoints implemented; ladder ordering (headers → role → path existence → ownership → body refs → shape → carrier-active → from-state → temporal → cross-ref → uniqueness → empty-subject → bond fiscal → SoD → competitive → OCC) enforced per endpoint |

## Self-smoke-test evidence
- Booted on port 29876 (`PORT=29876 bash start.sh &`), ran 31 assertions (`/tmp/smoke3497.py`), **all PASS**: clock 400-without-headers / 200-with-admin (unprefixed `/_clock/set_current_utc`), carrier+shipper registration (201, version 1, `created_at` with `.000Z`, dashed UUID), role-gate 403, tariff filing with OCC (carrier version 1→2), stale OCC → 412, publish window → 422 then 200 after clock advance, invoice issuance (free_time 2d, CALENDAR, 3.5-day window → billable_days 4, amount 40000, client-supplied rate fields ignored), dispute open (response_due_at = +30d), REDUCE-not-lower → 400, REDUCE 20000 → UPHELD_REDUCED + invoice back to ISSUED, complaint intake (score frozen 100, DOCKETED), mark-paid, open-adjudication, decide → OUT_OF_POCKET 20000 + 5% interest = 21000 with appeal_deadline +30d, shipper ledger 21000, list-envelope pagination meta.
- Fresh-reboot check: killed the exact PID I started (found via `ss -tlnp` on 29876 — note: `bash start.sh &` + `kill $!` left a grandchild orphan on the first attempt; identified and killed the real listener PID, re-verified), rebooted → empty store (random UUID → ERR_CARRIER_NOT_FOUND) and clock back at `2026-09-01T00:00:00Z`. Port left free.

## Audits
- `python3 -m compileall` clean; live boot proves the import graph.
- Error-id audit: all 57 catalog ids have ≥1 raise site outside `errors.py`; no raise site references a non-catalog id; HTTP statuses come from the catalog dict (single definition).
- UUID audit: only `str(uuid.uuid4())` for resource ids (`uuid4().hex` appears solely in a comment and for the `req_…` request id, which is not a UUID field).
- No seeding; storage is dicts only.

## Interpretations chosen (for the fix-loop hand-off)
1. **`version` starts at 1** (PRD §2.5 "starts at creation" read as 1; a fresh carrier files a tariff with `expected_carrier_version: 1`).
2. **Two timestamp families**: `created_at`/`updated_at`/`api_request_timestamp` always exactly 3 fractional digits; all domain timestamps render "as the clock reads" — the fractional-digit style of the most recent `to_iso8601` (boot default: none, `2026-09-01T00:00:00Z`). Input datetimes re-render canonically in that style.
3. **Clock endpoint is enveloped** (`data.current_utc`) and role-gated (CommissionAdmin); only the path is outside `/fmc`.
4. **Monitoring-report ownership = agreement membership** (PRD §3.8 "the members file …"), not just the filer: caller ∉ members → ERR_FORBIDDEN_RESOURCE_ACCESS.
5. **`member_volumes.carrier_id` gets no table-404** (scaffold: integrity flows through the agreement) — nonexistent entry id → ERR_MEMBER_SET_MISMATCH 422, never ERR_CARRIER_NOT_FOUND.
6. **Complaint intake requires the caller's ShipperAccount to exist** → ERR_SHIPPER_NOT_FOUND at the body-refs rung (PRD silent on a dangling ShipperRep identity).
7. **Complaint cross-refs per invoice in order**: party check then respondent check per subject invoice (not all-party-then-all-carrier).
8. **close-ombuds on a non-OMBUDS complaint** → ERR_INVALID_REQUEST (no dedicated catalog id exists).
9. **NO_VIOLATION sets `determined_at`**, leaves `violation_count`/`willful`/`repeat_offender`/`penalty_cents`/`score_delta` null (input ignored).
10. **`expected_carrier_version`/`expected_license_version` are required** (absent → ERR_INVALID_REQUEST; mismatch → ERR_STALE_VERSION, checked last).
11. **Pagination bounds are validated** (limit int 1–100, offset int ≥0 → else ERR_INVALID_REQUEST), not clamped.
12. **Zero-amount draws allowed** as no-op movements (still bump license version); unknown `bond_ref` → ERR_INVALID_REQUEST.
13. **`coverage_cents` ≥ 1** on bond append; **`reporting_period_end > start`** required (half-open non-empty), overlap uses strict half-open intersection (adjacency allowed).
14. **HHI algorithm over the comment's arithmetic**: scaffold §1.3's parenthetical says volumes [1,2] of 3 → 5555.60 pinned; the pinned algorithm (share 4dp → square 2dp → sum → 2dp) yields **5555.54** (33.3333²→1111.09 + 66.6667²→4444.45). Implemented the algorithm as stated in PRD §3.8 — if Step 7 flags HHI, this is the site.
15. **One version bump per mutation event**: a determination changing penalties+score+status is one carrier touch; cascaded children bump individually; suspension folds into the same event.
16. **Bond cascade restores only the contracts that license's own coverage loss suspended** (tracked per license); a license leaving ACTIVE suspends all of the carrier's EFFECTIVE contracts even if another license is ACTIVE (literal PRD reading).
17. **SUSPENDED carrier may still file tariffs/agreements/licenses/bonds** — ERR_CARRIER_NOT_ACTIVE applies only to invoice creation, service-contract creation, and tariff publish (scaffold priority 6 applies_to).
18. **`denial_justification` empty string accepted** (presence+type only); `settlement_amount_cents` unbounded beyond presence/integer; late dispute response ignores resolution-specific requirements entirely (forced waiver).

Orchestrator verification after Step 6 (hand-back claims spot-checked against source):
- HHI: executed impl `monitoring_hhi([1,2] of 3)` → **5555.56**; PRD §3.8 pins share-4dp → square-2dp → sum → 2dp half-up, which arithmetically yields 5555.56 (33.3333²=1111.11, 66.6667²=4444.45). Impl CODE is PRD-conformant; the report's "5555.54/1111.09" sentence is a report-text arithmetic slip, not a code bug. Scaffold design instance's 5555.60 remains the outlier (already skipped at Step 5).
- uuid4: `str(uuid.uuid4())` for resource ids (store.py:30); only `.hex` use is the `req_` request-id prefix — acceptable.
- Clock: `routes/clock_route.py:14` mounts `/_clock/set_current_utc` unprefixed — correct.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T22:05:00.000Z

Subagent's verbatim hand-back report follows:

All 8 rounds pass 98/98. Sweep artifacts `results.1.json`–`results.8.json` remain in `workspace/implementation/` per the output contract.

## Summary

- **Iterations run**: 2 (initial sweep: 95/98 × 8 rounds, identical 3 deterministic failures everywhere — no flakiness; post-fix sweep: 98/98 × 8 rounds, all pass).
- **Tests deleted**: none. All three failing rules are verbatim PRD-covered and uniquely determined; all three failures were test-side defects.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**:
  1. `test_suite/test_05_disputes.py` — `test_response_at_exact_deadline_is_timely_and_deny_stands`: `resolved_amount_cents` expectation 5000 → 10000. The standard fixture's invoice is 2 billable days × 5000 = 10000 cents (pinned by two passing sibling tests in the same file); 5000 was a copy-paste of the second invoice's amount. PRD §3.6: a timely DENY takes "the invoice's full `amount_cents`".
  2. Same file — `test_reduce_not_lower_and_deny_without_justification_rejected`: added the missing `cid` positional to the `respond_dispute(d1["id"], cid, {...})` call (helper signature is `(dispute_id, carrier_id, payload)`); the TypeError was a pure call-arity bug.
  3. `test_suite/test_07_adjudication_appeals.py` — `test_decide_without_open_adjudication_returns_not_adjudicating`: expected error `ERR_COMPLAINT_NOT_ADJUDICATING` → `ERR_FORBIDDEN_RESOURCE_ACCESS`, docstring extended. PRD §2.7's numbered ladder puts the assigned-officer ownership check (rung 3: "decide caller == complaint.presiding_judge_id") before complaint from-state (rung 8), first failure wins; on a DOCKETED complaint `presiding_judge_id` is unset so every caller fails rung 3. The corner design instance's 409 contradicted the scaffold's own priority table (SCAFFOLD.yaml line 714 vs 749); PRD rendered the ladder verbatim, not the instance's outcome. The impl's sibling endpoint close-ombuds uses the identical ordering, confirming consistency.
- **Fixes applied to `implementation/`**: none — the implementation was PRD-conformant on all three sites.
- **Unasserted sibling path noted**: `ERR_COMPLAINT_NOT_ADJUDICATING` remains reachable only via a presiding judge deciding an already-decided complaint; no test in the suite covers that path after the correction above.

Orchestrator verification after Step 7: all 8 `results.{i}.json` present in workspace/implementation/, each independently parsed showing passed=98 total=98 failed=0.

## Step 8: PRD Finalization — 2026-10-02T22:40:00.000Z

Subagent's verbatim hand-back report follows:

Done. `PRD_FINALIZED.md` is written and is a **byte-identical copy of PRD.md** — the zero-edit outcome, verified by `diff -q`.

## Line counts

- PRD.md: 336 lines; PRD_FINALIZED.md: 336 lines; delta 0 lines (0.0%).
- **Changes: zero edits.** All three Step 7 items are pure test-side bugs; the PRD already uniquely determines the implementation's behavior at every site.

## Per-item analysis log

**Item 1 — test_05_disputes.py, resolved_amount_cents 5000 → 10000 on timely DENY at exact deadline**
- (a) Verdict: **pure test bug** (fixture arithmetic: the standard invoice is 2 billable days × 5000 = 10000; 5000 was copied from the second, 1-billable-day invoice).
- (b) Impl paths read: `implementation/routes/disputes.py` (full file) — `respond_dispute` DENY branch at lines 142-149 sets `d["resolved_amount_cents"] = inv["amount_cents"]` verbatim; timeliness gate at line 114 (`if now > d["response_due_at"]`) makes an exactly-at-deadline response timely. Sibling writers of `resolved_amount_cents` enumerated: WAIVE branch (line 129, =0), REDUCE branch (line 138, =reduced figure), late-response forced waiver (line 119, =0), cascade path in `services/cascades.py` (referenced from disputes.py line 23; §2.10 pins cascade =0). Also read `test_suite/test_05_disputes.py` lines 23-35, 96-119 (fixture + fixed test, whose docstring now quotes §3.6 verbatim).
- (c) No wording adjustment: PRD §3.6 already states "a timely `DENY` ... resolves the dispute as `DENIED`: `resolved_amount_cents` takes the invoice's full `amount_cents`" — unique determination, impl-conformant.

**Item 2 — test_05_disputes.py, missing `cid` positional in respond_dispute call**
- (a) Verdict: **pure test bug** (call-arity).
- (b) Paths checked: `test_helpers/fixtures.py:117` — signature is `respond_dispute(dispute_id, carrier_id, payload)`; grep of all 7 call sites in test_05_disputes.py confirms the corrected call matches. No implementation behavior involved at all.
- (c) No wording adjustment: test-helper arity is outside PRD scope by definition.

**Item 3 — test_07_adjudication_appeals.py, expected error ERR_COMPLAINT_NOT_ADJUDICATING → ERR_FORBIDDEN_RESOURCE_ACCESS on decide over a DOCKETED complaint**
- (a) Verdict: **pure test bug** (test ignored the §2.7 ladder the PRD already pins).
- (b) Impl paths read: `implementation/routes/complaints.py` (full file). `decide` at lines 211-222 orders: role → not-found → ownership (`uid != c["presiding_judge_id"]` → ERR_FORBIDDEN_RESOURCE_ACCESS, line 217) → from-state (ERR_COMPLAINT_NOT_ADJUDICATING, line 220). Since `file_complaint` (line 105) births `presiding_judge_id=None`, every caller fails the ownership rung on a DOCKETED complaint. Sibling paths enumerated per the no-new-mismatch rule: `close_ombuds` (officer check line 167 before state check line 176 — identical ordering, as Step 7 noted), `appeal` (party check lines 246-252 before state line 253), `open_adjudication` (state line 198 before segregation-of-duties line 201, matching rungs 8 < 14), `resolve_appeal` (no ownership rung — correct, CommissionAdmin is an opaque identity with no assigned-officer field). Also confirmed ERR_COMPLAINT_NOT_ADJUDICATING remains reachable: a presiding judge (field populated, uid matches) deciding an already-decided complaint passes rung 3 and fails rung 8.
- (c) No wording adjustment: PRD §2.7 fixes the ordered ladder with first-failure-wins (rung 3 "assigned-officer checks where a workflow names a responsible individual; failures carry ERR_FORBIDDEN_RESOURCE_ACCESS" strictly before rung 8 from-state), §3.7's decide sentence presents the rejections in that same order ("belongs to the presiding judge alone — a different caller is rejected with ERR_FORBIDDEN_RESOURCE_ACCESS — and only while ... ADJUDICATION_OPEN, otherwise ERR_COMPLAINT_NOT_ADJUDICATING"), and §3.7 intake pins `presiding_judge_id` unset until adjudication opens. Composed, these uniquely determine the impl behavior; the original test's contrary expectation required not applying the ladder. Any clarifying edit would also risk overclaiming against the sibling endpoints above, so per the under-determination preference the prose stays verbatim.

No writes were made to `implementation/`, `test_suite/`, or `test_helpers/`; the only write target touched was `workspace/PRD_FINALIZED.md`.

Orchestrator verification after Step 8: `diff -q` confirms PRD_FINALIZED.md byte-identical to PRD.md. Newest source mtimes (test_07 22:27:52, test_05 22:27:37, impl newest 22:09:15) all predate the oldest sweep artifact (results.7.json 22:30:54) — no post-sweep writes; the green sweep remains valid.

## Step 9: PRD Completeness Scan — 2026-10-02T23:20:00.000Z

Subagent's verbatim hand-back report follows:

All edits are in and verified. Final state: `workspace/PRD_COMPLETED.md` written; source untouched elsewhere.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` 336 lines / 55,109 chars → `workspace/PRD_COMPLETED.md` 338 lines / 59,359 chars (char-delta +4,250; 19 source paragraphs revised, 1 paragraph + 1 blank line inserted). No writes to `implementation/`, `test_suite/`, or `test_helpers/`.

**Counts:** 16 edit sites, all ambiguity-pins (27 individual behaviors pinned); 0 mismatch-revisions.

**Changes (one bullet each):**
- §2.3 — insert — ambiguity — invalid/non-integer `limit`/`offset` (limit outside 1–100, negative offset) rejected `ERR_INVALID_REQUEST`; list order pinned as creation order (coincides with `created_at` asc, ties in creation sequence); `total_count` = filtered set size, `has_more` ⇔ offset+returned < total — `implementation/envelope.py:49-75`
- §2.4 — insert — ambiguity — invalid `to_iso8601` → `ERR_INVALID_REQUEST`; any valid instant accepted, no monotonicity constraint; `current_utc` rendered in the fractional style just supplied — `implementation/routes/clock_route.py:14-24`, `implementation/clock.py:56-66`
- §2.5 — revise+insert — ambiguity — `version` starts at 1; new paragraph pinning domain-timestamp rendering (UTC, fractional style of most recent clock set; 3-digit rule only for `created_at`/`updated_at`/`api_request_timestamp`; client instants normalized on output) — `implementation/store.py:33-42`, `implementation/clock.py:64-70`, `implementation/serialization.py:16-17`
- §2.7 rung 6 — insert — ambiguity — missing/unparseable JSON body treated as `{}`; non-object body → `ERR_INVALID_REQUEST` — `implementation/util.py:8-16`
- §2.8 — insert — ambiguity — `target_carrier_id` added to the body-reference 404 list — `implementation/routes/enforcement.py:35-37`
- §3.3 — insert — ambiguity — only lateness policed; future `agreed_at` files fine — `implementation/routes/contracts.py:61-64`
- §3.4 — insert — ambiguity — unknown `bond_ref` on a draw → `ERR_INVALID_REQUEST`; zero `amount_cents` accepted as a no-op that still bumps license version; `reason` not persisted — `implementation/routes/licenses.py:110-130`, `implementation/serialization.py:113-121`
- §3.4 — revise — ambiguity — license returning to `ACTIVE` restores only the contracts its own coverage loss suspended (per-license tracked set) — `implementation/services/cascades.py:61-85`
- §3.5 — insert — ambiguity — other-basis reference (`service_contract_id` on TARIFF invoice / vice versa) not stored, reads back null — `implementation/routes/invoices.py:148-149`
- §3.6 — insert — ambiguity — `responded_at`/`requested_resolution` recorded once sanity+`PENDING` pass; a response then rejected (`ERR_REDUCED_AMOUNT_NOT_LOWER`, `ERR_JUSTIFICATION_REQUIRED`) leaves both recorded on the still-`PENDING` dispute with `version`/`updated_at` unchanged — `implementation/routes/disputes.py:107-150`
- §3.6 — revise — ambiguity — `denial_justification`: absent → `ERR_JUSTIFICATION_REQUIRED`, non-string → `ERR_INVALID_REQUEST`, any string (even empty) accepted — `implementation/routes/disputes.py:104-106,143-145`
- §3.6 — insert — ambiguity — late-response forced waiver applies only after payload passes scalar sanity — `implementation/routes/disputes.py:98-114`
- §3.7 — insert — ambiguity — complaint filing requires caller's shipper account to exist, else `ERR_SHIPPER_NOT_FOUND` — `implementation/routes/complaints.py:48-49`
- §3.7 — insert — ambiguity — `subject_invoice_ids` used as supplied; a repeated id counts once per occurrence in scoring and award — `implementation/routes/complaints.py:64,91-93,223-226`
- §3.7 — insert — ambiguity — close-ombuds on non-`OMBUDS` complaint → `ERR_INVALID_REQUEST`; `settlement_amount_cents` must be an integer but zero/negative accepted; settlement supplied with `FAILED` ignored — `implementation/routes/complaints.py:171-189`
- §3.8 — insert — ambiguity — `member_carrier_ids` stored as supplied (duplicates retained); two-member minimum judged on distinct — `implementation/routes/agreements.py:58-77`
- §3.8 — insert — ambiguity — monitoring report scalars (`total_market_teus` positive int, `carried_teus` non-negative int, end strictly after start) → `ERR_INVALID_REQUEST`; append responds 201 with the updated agreement; embedded report carries exactly the five documented fields, no id/timestamps — `implementation/routes/agreements.py:143-186`, `implementation/serialization.py:78-88`
- §3.9 — revise — ambiguity — NO_VIOLATION leaves `violation_count`/`willful`/`repeat_offender` unset too, and values supplied for them are ignored (not validated) — `implementation/routes/enforcement.py:90-109`

## IMPL BUGS

None found. Audited sites:
- **Dead-code/shadowed checks:** all seven `calc.py` functions and all five `cascades.py` functions are called from routes; guard-field writers traced (`ombuds_officer_id` ← refer-ombuds only, `presiding_judge_id` ← open-adjudication only, `appeal_deadline` ← decide only, `competitive_concern_flag`/`market_concentration_hhi` ← monitoring append only); no guard is unreachable or dead.
- **Prose-only uniqueness rules:** only two exist (bond_ref within license; port+terminal+week triple) — both have catalog error_ids and both are enforced; no unpinned uniqueness rule was dropped.
- **Nullable-field reads on legal combos:** `market_concentration_hhi`/report `hhi` None-guarded in `serialization.py:87,104-107`; `presiding_judge_id`/`ombuds_officer_id` None-safe comparisons (`complaints.py:167,201,217`); `appeal_deadline` read only in `ADJUDICATION_DECIDED` (always set by decide); `penalty_cents`/`score_delta` stay None on DISMISSED and are serializer-only; subject-invoice/shipper/carrier derefs (`complaints.py:223,233,277`, `disputes.py:92,122`, `enforcement.py:111`) target entities validated at creation and never deletable — no reachable 500/KeyError/TypeError on a PRD-legal path.
- **Recording-vs-annotation:** the only unpersisted request field is the draw `reason`, which PRD phrases as request content ("the request names ... a free-text `reason`") with no recording language — legitimately annotation-only; pinned in §3.4 anyway.
- **Clock mounting re-check:** `POST /_clock/set_current_utc` confirmed unprefixed (`implementation/routes/clock_route.py:14`, registered prefix-free in `app.py:41`).
- **Error catalogue:** PRD §5 and `implementation/errors.py` CATALOG are identical — 57 ids, zero status mismatches (verified programmatically).
- **Ladder ordering:** every endpoint's check order verified against §2.7 rungs (including rung-12 `ERR_EMPTY_SUBJECT_SET` placement, rung-13-before-16 on draws, rung-15 last-ish on go-effective); all conform.

One adjudication note: §3.4's third restoration sentence ("restores the carrier's suspended contracts") was classified as ambiguity, not mismatch, because the immediately preceding sentence pins the same per-license-tracked semantics for first-time activation — the qualifier's absence reads as shorthand, so I revised rather than reported.

Orchestrator verification after Step 9: PRD_COMPLETED.md differs from PRD_FINALIZED.md (diff exit 1), 338 lines as reported — not a killed-mid-flight no-op. Newest source mtime (22:27:52) still predates oldest sweep artifact (22:30:54) — no code writes during Steps 8/9, green sweep remains valid. All 8 results.{i}.json present.

## Pipeline Complete — 2026-10-02T23:25:00.000Z

Final state: 98/98 tests passing × 8 parallel stability rounds (results.1–8.json in workspace/implementation/). Artifacts: SCAFFOLD.yaml + both design indices, PRD.md (336 lines), PRD_FINALIZED.md (byte-identical, zero-edit Step 8), PRD_COMPLETED.md (338 lines, 16 ambiguity-pins), test_helpers/ (9 files), test_suite/ (11 files, 98 tests, 98 Design tags), implementation/ (17 files, 41 endpoints, in-memory Flask).
