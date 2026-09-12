# P7 response-stress structure gate development audit

## Conclusion

Neither P7 response-stress variant passed the frozen 13-family development
gate. The experiment remains offline-only and is not enabled in production or
included in the submission build. Robust variants were not run on repetitions
401--405. The separately frozen mean-rollout confirmation uses those repetitions.

The initial `strict` and `bounded` gates improved the 39-pair mean by 4.5549
and 5.5683 respectively, but both had negative family means for
`double_bridge_communities` and `two_block_bridge`. The subsequent anchored
variants included the current public-greedy first structure action in every
scenario control. This removed the `two_block_bridge` loss, but it did not
remove the `double_bridge_communities` loss. No variant therefore qualifies
for confirmation or production promotion.

## Design and evidence boundary

All arms used the same 13 known topology families, 50 nodes, and development
repetitions 301--303. Each seed was paired with the current `public_greedy`
control. The policy received only a scanned `Blackboard`, remaining budget,
remaining steps, and successful public communication responses. The local
environment retained each seed's hidden response factor; it was never passed
to `robust_experiment.py`.

Unknown first responses were stressed at 3.0, 12.75, and 22.5. A known target
used its own first successful public response with the published diminishing
multipliers. Hypothetical opinions and topology existed only in
`PredictiveState`. Every real action was followed by a fresh plan.

The initial variants compared a P6 depth-two structure prefix plus its complete
communication tail with the equal-resource no-structure communication tail:

- `strict`: accept only when all three scenario deltas are nonnegative.
- `bounded`: accept when the scenario mean is positive and the minimum delta is
  at least -5.

Development revealed that this control omitted a stronger current
`public_greedy` structure action. Commit `a1ade69` therefore added separately
named `strict_anchor` and `bounded_anchor` variants. For these variants the
scenario control is the maximum of the no-structure tail and the current
public-greedy first structure action followed by the same communication tail.
The original variants remain reproducible; their reports were not overwritten.

## Local results

| Variant | Pairs | Mean delta | Family bootstrap 95% interval | Win/tie/loss | Minimum | Family gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| P6 depth 2 | 39 | +8.7217 | [2.6561, 17.1040] | 21/12/6 | -24.9724 | fail |
| strict | 39 | +4.5549 | [-1.2292, 13.4638] | 9/26/4 | -19.6485 | fail |
| bounded | 39 | +5.5683 | [-0.0596, 13.8097] | 14/21/4 | -19.6485 | fail |
| strict_anchor | 39 | +4.9367 | [-0.7288, 13.6731] | 9/27/3 | -19.6485 | fail |
| bounded_anchor | 39 | +5.9501 | [0.4705, 14.0167] | 14/22/3 | -19.6485 | fail |

All candidate sessions had zero action failures and passed the budget and step
audit. `bounded_anchor` had a positive family-bootstrap interval, but its
`double_bridge_communities` family mean was -7.0189. The predeclared gate
requires both a positive interval and every family mean to be nonnegative.

The anchor variants retained evidence of useful specialization:
`ba_negative_hubs` improved by +51.4340 under `strict_anchor` and +47.8417
under `bounded_anchor`; `tree_broom` improved by +14.4716 under both. These
development effects do not override the failed family gate.

## First divergence audit

The first `double_bridge_communities` divergence occurred in repetition 301,
at intervention decision 2 with budget 70 and no observed responses. The
control and public-greedy fallback selected `shield:4`. P6 proposed the prefix
`shield:7, shield:1`, so the robust arm executed `shield:7` and replanned.

Relative to the maximum of no structure and `shield:4` followed by a pure
communication tail, the P6 prefix had scenario deltas +42.8663, +27.8036, and
+12.7409. Both anchored gates therefore accepted it. The final paired score
was nevertheless -7.5197 below public greedy; repetition 303 lost -19.6485.

The mismatch is in the policy continuation being compared. The anchored
control models one public-greedy structure action followed only by
communication, while the real public-greedy policy can choose more structure
actions after every public result. The P6 proposal is also executed one action
at a time and replanned. A one-action anchor does not compare these two dynamic
continuation policies on the same response path, so it cannot exclude this
loss.

## Official custom-seed check

The official custom-seed sandbox pair for `ba_negative_hubs`, repetition 301,
returned 297.01 for public greedy and 401.34 for `strict_anchor`, a gain of
+104.33. Both arms had zero failures. Local replay scores were 297.03497 and
401.37438; the settlement residual magnitudes were below 0.035 and the maximum
per-action response error was zero. This validates the public action replay on
one favorable mechanism case. It does not estimate hidden-seed performance or
repair the failed 13-family development gate.

## Read-only rollout review

The separate rollout policy does not receive a seed response factor. Its
runner passes the seed only to `LocalPublicEnvironment`, while policy rollout
responses are generated internally and revealed to a simulated policy only
after the corresponding communication. Candidate and baseline rollouts start
with the same budget and remaining-step allowance, use common responses, and
debit the public action costs. No hidden-response leak or paired-resource
mismatch was found.

The fixed-mean arm uses response factor 0.85 for every unknown target and is
not affected by sampling-key bias. The three-scenario sampled arm derives each
draw only from node ID and scenario number, so identically numbered nodes use
the same hypothetical factor in every family and repetition. Because several
graph generators assign structural roles to stable ID ranges, sampled results
may confound those roles with the fixed hypothetical response map. This is a
limitation of the sampled arm only; it must not be attributed to the completed
fixed-mean development result.

At review time, direct execution of `scripts/run_rollout_search.py` failed
before argument parsing because its package import lacked the fallback used by
the other experiment runners. This is a runner reproducibility defect, not a
policy result. The CLI also had no explicit development/confirmation range
guard. Mean-rollout repetitions 401--405 were subsequently authorized by the
main agent after freezing manifest commit `36a7098`; a CLI
guard would be protocol hardening rather than a correction to existing data.
Direct invocation was repaired in runner-only commit `cecfab6`; the frozen
policy was not changed.

The runner records terminal comparisons and resource totals but not each
rollout decision's baseline action, selected action, or paired scenario
deltas. This limits diagnosis of a future negative case without changing the
selection logic.

## Reproduction

The initial implementation was frozen at `b7fe36f`; anchored variants were
added at `a1ade69`.

```bash
uv run python scripts/run_robust_search.py --block existing --start 301 --repetitions 3 --output experiments/reports/p7-robust-existing-dev-20260912.json
uv run python scripts/run_robust_search.py --block independent --start 301 --repetitions 3 --output experiments/reports/p7-robust-independent-dev-20260912.json
uv run python scripts/run_robust_search.py --block holdout --start 301 --repetitions 3 --output experiments/reports/p7-robust-holdout-dev-20260912.json

uv run python scripts/run_robust_search.py --block existing --start 301 --repetitions 3 --variants strict_anchor bounded_anchor --output experiments/reports/p7-robust-anchor-existing-dev-20260912.json
uv run python scripts/run_robust_search.py --block independent --start 301 --repetitions 3 --variants strict_anchor bounded_anchor --output experiments/reports/p7-robust-anchor-independent-dev-20260912.json
uv run python scripts/run_robust_search.py --block holdout --start 301 --repetitions 3 --variants strict_anchor bounded_anchor --output experiments/reports/p7-robust-anchor-holdout-dev-20260912.json

uv run python scripts/summarize_p7_search.py \
  experiments/reports/p7-robust-anchor-existing-dev-20260912.json \
  experiments/reports/p7-robust-anchor-independent-dev-20260912.json \
  experiments/reports/p7-robust-anchor-holdout-dev-20260912.json \
  --repetitions 301 302 303 \
  --output experiments/reports/p7-robust-anchor-audited-summary-20260912.json
```

The paired/blocking design follows the procedural guidance in Timothy Kassis,
Vinayak Agarwal, Yuhuan He, Darshil Patel, and Aubrey M. Brueckner,
"Scientific Agent Skills: A Library of Procedural Knowledge for Research
Agents," arXiv:2609.00065, 2026, https://doi.org/10.48550/arXiv.2609.00065.
