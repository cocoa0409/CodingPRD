# task_3116 — step 8 progress (PRD_FINALIZED.md)

Base copy made: `cp PRD.md PRD_FINALIZED.md` (both 386 lines at base; both 386 after — edits are in-place line replacements).

## Edits APPLIED (27 changed lines) — all verified against implementation by reading + in-process Flask test-client probes

| # | Line | Section | Edit | impl anchor |
|---|------|---------|------|-------------|
| 1 | 45 | §2.2 | api_request_timestamp: read=logical clock, write=wall time; whole-second instants compact | clock.py:108-133, 40-55 |
| 2 | 47 | §2.2 | three `/…/active-attempt`,`/routed-endpoint`,`/signature-session` reads are one-element arrays | prescriptions.py:177,186,205; serializers.py:66-68 |
| 3 | 78 | §2.3 | same-instant creation ties broken by insertion sequence | request_context.py:188-190 |
| 4 | 84 | §2.4 | degradation gate now described as share of still-reachable endpoints | directory.py:166-189 |
| 5 | 90 | §2.5 | `version` reads 1 on a fresh resource; timestamps compact-when-whole-second | db.py:77-91; clock.py:40-55 |
| 6 | 98 | §2.6 | endpoint-overlap key adds `service_level` | routes/participants.py:278-281 |
| 7 | 100 | §2.6 | coverage invariant counts ACTIVE+DEGRADED, exempts a directory of one; last-active guard excludes the disabled endpoint | certification.py:148-196; directory.py:166-189 |
| 8 | 106 | §2.7 | `period_net_total_cents` write model: restamped across the participant-month | billing.py:205-210 |
| 9 | 120 | §2.9 | sign's controlled-order precondition is the stricter restatement; 404/405/body parsing | prescriptions.py:238-239; app.py:57-89 |
| 10 | 136 | §2.11 | directory-chain hops widened to SIGNED/ROUTED + NOT_ROUTED/ROUTED/BACKUP_SELECTION; hop 4 unconditional | certification.py:250-279 |
| 11 | 150 | §3.2 | CERTIFIED reopen turns on endpoint-row requirement alone (no FAIL can accumulate) | certification.py:56-75 |
| 12 | 158 | §3.1 | the order inherits the prescriber's fallback_channel/fax_number | prescriptions.py:120-124 |
| 13 | 174 | §3.4 | reliability key never consults the identifier (ratios separated by ≥0.0001) | routing.py:52-61 |
| 14 | 176 | §3.4 | backup nomination excludes DEGRADED and every already-probed endpoint | routing.py:88-110 |
| 15 | 180 | §3.4 | re-route admits DELIVERED/REJECTED and returns the order to ROUTED | prescriptions.py:315-323,348 |
| 16 | 188 | §3.5 | report-undeliverable re-entrant on an ACKNOWLEDGED network attempt | prescriptions.py:724-730 |
| 17 | 190 | §3.5 | degrade share = ACTIVE+DEGRADED; backup requires an in-window ACTIVE, unprobed, non-DEGRADED endpoint | prescriptions.py:739; routing.py:64-126 |
| 18 | 194 | §3.5 | route-fallback precondition order (failed attempt → channel → routing status); gate counts ACTIVE only | prescriptions.py:371-397; routing.py:113-126 |
| 19 | 200 | §3.6 | suspend cascade hops widened + hop 4 unconditional + no ERROR_ROUTE_NO_ENDPOINT stamp | certification.py:250-279 |
| 20 | 202 | §3.6 | disable guard excludes the disabled endpoint; four-hop cascade; hop-4 unconditional | certification.py:169-207,250-279 |
| 21 | 210 | §3.7 | CORRECTION `previous_count` basis = settled count | billing.py:88-95,234 |
| 22 | 220 | §3.7 | settlement stores the charged amount in `fee_cents`; reserve exposed separately; net-of-reserve shown as the illustration's final | billing.py:131-163 |
| 23 | 222 | §3.7 | compensating row is itself `REVERSED`, self-identifying; reverse reply root = compensating row + `reversal_source` | billing.py:298-343; transaction_fees.py:97 |
| 24 | 228 | §3.8 | consent scope coverage (BOTH collides with both singles, singles don't), expired window not live | history.py:37-72 |
| 25 | 230 | §3.8 | history-source gate tests the named source; Pharmacy names itself, HubOperator may name any | routes/patients.py:183-191 |
| 26 | 232 | §3.8 | `source_record_count_reflects the certified live set (impl recomputes it on settle) | history.py:238-256 |
| 27 | 236 | §3.8 | `subscription_generation` increments on the settle out of PENDING too | history.py:207-217 |

## Verified by in-process probe (no ports)
version==1; fee row keys include reserve_cents/final_amount_cents/reserve_basis_count/chargeable_count;
fee_cents 3600 / reserve 1080 / final 2520; reverse root status REVERSED + entry_type MANUAL_REVERSAL +
self reversal_entry_id + reversal_source;
UNCERTIFIED-no-endpoint reopen → ERR_CERT_NO_ENDPOINT; SUSPENDED reopen → IN_CERTIFICATION;
CERTIFIED reopen with no FAIL → IN_CERTIFICATION;
uncertified history source → ERR_HISTORY_SOURCE_UNCERTIFIED (both Pharmacy and HubOperator identities);
BOTH under live MEDICATION_HISTORY → ERR_CONSENT_INTERVAL_OVERLAP; BENEFIT_CHECK → ACTIVE.

## Left UNCHANGED (under-determined; Step 9 may pin — a false universal claim is worse)
- §3.6 hop-1 widened bands / hop-4 unconditional — now WRITTEN to match impl (edits 10/19/20).
- §3.5 ERR_ENDPOINT_NOT_ROUTED_ATTEMPT (impl never raises) — left.
- §3.5 ERR_FALLBACK_NOT_PERMITTED semantics differ from impl — left.
- §3.6 suspension attempt error_code_returned ERROR_ROUTE_NO_ENDPOINT (impl never stamps) — left.
- §3.4 route-degrade-on-ratio not stated in PRD; impl does it — left under-determined.
- §3.9 benefit resolve always NON_PREFERRED/ACTIVE for a PAYER — left.
- §3.8 dedupe rank third key `fill_date` ascending vs PRD "later fill_date wins" — left.
- §2.7 feature/value enum vocabulary — left (unexercised).
- §2.3 limit>100 validation message — left (unexercised).

## Status
- [x] Edits applied (27 lines)
- [x] Progress + summary written