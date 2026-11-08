# DCMA parity fixtures

Synthetic schedules (no client data) with the results `references/DCMA_DEFINITION.md` gives, worked out by hand from that text. `make_dcma_parity.py` writes the XERs and `expected.json`; it is deterministic, and `tests/test_dcma_parity_fixtures.py` fails if the committed files drift from it.

## expected.json

`{fixture: {"current": file, "baseline": file or null, "checks": {"<n>": {"status", "num", "den"} or {"status", "value"}}}}`

`status` is `PASS`, `FAIL` or `NS` (not scored). Only the checks a fixture is built to exercise are listed. `num` and `den` mean:

| # | num | den |
|---|---|---|
| 1 | activities with a missing predecessor or successor (each once) | incomplete ordinary activities and incomplete milestones |
| 2 | leads | live relationships |
| 3 | positive lags | live relationships |
| 4 | Finish-to-Start relationships | live relationships |
| 5 | hard-constrained activities | incomplete ordinary activities |
| 6 | float above 44 working days | incomplete ordinary activities with a computed float |
| 7 | negative float | as #6 |
| 8 | duration above 44 working days | incomplete ordinary activities with a readable original duration |
| 9 | activities with an invalid date | ordinary activities and milestones, complete included |
| 10 | resourced activities | incomplete ordinary activities of at least 1 working day |
| 11 | missed | due baseline activities, less those whose lateness is unknown |
| 14 | complete as of the data date | due baseline activities |

#12 is compared on status only. #13 carries `value` (the CPLI), compared to within 0.01.

## Engine scope

- **Validator**: every check as listed.
- **Dashboard**: renders every fixture; a fixture with no baseline is rendered with the current file as its own baseline (the dashboard always takes two), so #11 and #14 are not compared there. #13 is: with no real baseline the dashboard reads the completion activity’s P6 float, as the definition says.
- **CPP Lens**: scores 1 to 11 and #12 FAIL-only, so #13 and #14 are expected NOT SCORED, and #12 is expected NOT SCORED unless the fixture expects FAIL.

## Fixtures

| Fixture | Built to test |
|---|---|
| p1_logic | #1 positional milestone rule and LOE links; #2 to #4 on live relationships only (a lead into finished work is history) |
| p2_activities | #5 On or Before and secondary constraints; #6/#7 blank float and calendar inheritance (blank activity calendar on a 10-hour project calendar); #8 on a 10-hour calendar; #10 zero-hour assignment and the 1-day floor; an interim mandatory milestone that is not the completion |
| p3_current + p3_baseline | #8 baseline basis; #11 late, open, deleted, unknown lateness, due later on the data date, ambiguous ID (one shared with a level-of-effort row); #13 against the same activity's baseline; #14 early completion and ambiguous ID |
| p4_cycle | #12 FAIL on a logic loop |
| p5_mandatory | #12 FAIL on a mandatory completion; #13 not scored on it; a constrained milestone outside #5 |
| p6_two_projects | D0: an older project in the same file is not read |
| p7_as_built | every incomplete-work check not scored; #9 still scored on actuals |
| p8_no_links | #1 with no relationships; #2 to #4 not scored |
| p9_data_date | D14: a blank data date is the planned start (#9 scored against it); D0: a single-project file is read whole, an activity with a stray project ID included |
| p10_late_no_baseline | #13 with no baseline: a deadline on the completion is measured as working time to its date (CPLI 0.5, FAIL) |
| p11_short_day | #13 working time (D13) on a short Monday and a holiday |
| p12_exact_095 | a CPLI of exactly 0.95 passes (D7) |
| p13_current + p13_baseline | a baseline sharing no Activity ID is not used (D9): #11, #13, #14 not scored, #8 on current durations |
| p14_current + p14_baseline | #8: a blank duration left out; a baseline activity's duration on its own inherited calendar; a blank baseline duration reads the current one |
| p15_no_forecasts | #9: an actual after the data date fails even when the incomplete work carries no forecasts |
| p16_as_built_mandatory | #12: a finished completion's Mandatory Finish decides nothing (not scored, no cycle) |
| p17_shift_hours | D3: a calendar whose shifts work 10 h a day but declares 8 converts on the 10 |
| p18_empty_calendar | D3: a calendar record with no shift data is P6's 8-hour Standard, whatever it declares |
| p19_calendar_mix | #13 with no baseline: a named deadline's float is working time on the project calendar, not the completion's own-calendar P6 float |
| p20_cross_project_links | D4: a link to another project, by relationship or by P6's external date, counts for #1 |
| p21_zero_duration | D1: a zero-duration activity is a milestone for the populations (#5, #8); #4 names a Start-to-Finish |
| p22_mandatory_mid_path | #12, the 600-day test: a Mandatory Start part way along the driving path stops the delay (FAIL); p1, p2 and p10 pass it. A result marked `by: test` needs the recalculation; a view without one reads NOT SCORED |
| p23_start_link_soft_constraint | #12: the first activity drives the path through its start and carries a Start On or After at the data date; the start delay moves it and the completion by 600 (PASS) |
| p24_start_link_mandatory | #12: as p23 with a Mandatory Start on that activity's own start; its start cannot take the delay (FAIL) |
| p25_tied_completion | D11, #12, #13: two finish milestones finish on one instant and the first leads to the second; the completion is the end of the network (the second), which a Mandatory Finish pins: #12 FAIL without a recalculation, #13 NOT SCORED |
| p26_tied_deadline | #13, D11: as p10, but the deadline (Finish On or Before) sits on the milestone that feeds the completion on the same instant; #13 reads it from the tie: CPLI 0.5 (FAIL) |

Working-day counts assume the fixtures' calendars, which carry no holidays except the one p11_short_day tests.
