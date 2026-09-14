# P10 depth-two structure-prefix result

P9 bounded-response scored the same `761.9467` on the official platform. This
follow-up tested whether `budget_plan(depth=2)` loses value because the prior
experiment evaluated and executed only its first structure action.

The P10 experiment fixed two attribution errors before measurement:

- Prefix rollout now keeps scenario-local latent first response separate from
  the clipped public response visible to the simulated planner, matching the
  corrected P8 transition semantics.
- Rejected or unavailable prefixes execute the current bounded P8 conservative
  decision. They no longer fall back to public greedy and discard existing P8
  value.

The protocol and implementation were frozen in commit `1727748` before results.
No production source, config, qualification, or new holdout was opened.

## Staged results

| Stage | Cases | Full vs bounded mean | Win/tie/loss | Full vs first mean | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Diagnostic four families / 501 | 4 | +1.2045 | 1/3/0 | +1.2045 | 0 |
| All 22 families / 501 | 22 | +0.6683 | 2/20/0 | +0.2190 | 0 |
| All 22 families / 502-503 | 44 | +0.4415 | 1/43/0 | +0.4415 | 0 |
| All 22 families / 501-503 | 66 | +0.5171 | 3/63/0 | +0.3674 | 0 |

Across 66 cases, the planner exposed 437 states with a genuine two-action
structure prefix and accepted five full prefixes. Only three cases changed the
terminal score:

- `ba_negative_hubs/501`: full `+4.8179`; first-only `0.0`.
- `ba_negative_hubs/502`: full `+19.4274`; first-only `0.0`.
- `lollipop/501`: full and first-only both `+9.8849`, so this gain came from
  discovery of the first structure action rather than second-action synergy.

`ba_negative_hubs/503` did not accept a prefix. The two other accepted-prefix
episodes (`sbm_violent_cluster/501` and `degree_corrected_sbm/503`) ended at the
same score as bounded P8. Every non-improving case preserved the bounded score;
there were no action failures or terminal regressions.

## Decision

The mechanism is real but too sparse for promotion: only 3/66 consumed cases
improved, only two repetitions showed second-action synergy, and no fresh
validation distribution was used. Its `+0.5171` mean is also materially smaller
than the independently developed deeper complete-plan candidate. P10 depth-two
prefix therefore remains a diagnostic result and will not enter qualification
or submission packaging. No additional prefix variant or holdout will be run.

Machine reports:

- `p10-prefix-diagnostic4-501-20260914.json`, SHA-256
  `ac0e95cf7989b53790efc888027919fe6b5b3ab205b18b945409514abf34d813`
- `p10-prefix-old22-501-20260914.json`, SHA-256
  `c5aeaf12adee9f3f57d10a5a50a7ff97007a9bc4d054a6263483bd700660d3e2`
- `p10-prefix-old22-502-503-20260914.json`, SHA-256
  `65e50ff6c1843f8253ae1f732d964ebfeee60eb1b62eeacdc7a3d580acb3c9f1`

Frozen identities:

- Prefix experiment SHA-256:
  `f802fff428cdf2c266f56740a11a26643440aa1aafbc201253f454ccbafb4d93`
- P9 bounded comparator SHA-256:
  `30326ab80cee936c6feb57ec01722eafa0994e2d171d606e6f439a3106f334ca`
