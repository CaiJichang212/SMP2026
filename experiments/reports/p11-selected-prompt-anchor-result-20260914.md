# P11 selected-prompt response anchor development result

This compound development experiment retained the frozen low-degree node and
prompt `1,2,3` sequence for hidden-ID identification. After selecting a
positive prompt, it spent two additional budget units on that known prompt at
the highest public component-influence untouched eligible node. Unknown-node
response magnitude then used only distinct post-calibration selected-prompt
returns; the low identification probe magnitude was excluded. Concrete observed
nodes continued to use their own first-equivalent response.

The 36 consumed legacy/base-permutation pairs passed every preregistered screen:

| Metric | Anchor minus frozen low P11 |
| --- | ---: |
| Symmetric mean | +34.2151 |
| Minimum / maximum | 0.0000 / +85.7701 |
| Win / tie / loss | 18 / 18 / 0 |
| Prompt-1-best mean | +34.3151 |
| Prompt-1-best win / tie / loss | 6 / 6 / 0 |

Family means were:

| Family | Mean |
| --- | ---: |
| `er_balanced` | 0.0000 |
| `ba_negative_hubs` | +85.0599 |
| `ws_peace_majority` | 0.0000 |
| `sbm_negative_bridges` | 0.0000 |
| `sbm_violent_cluster` | +60.0193 |
| `three_sparse_components` | +60.2113 |

All six family means were nonnegative and the minimum pair exceeded the `-10`
floor. Every case used one low identification node (6 budget) and one successful
uncensored selected-prompt anchor (2 budget), correctly identified the best ID,
issued at most one action per host step, and had zero action, P8, P11 planning,
or runtime errors.

The earlier high-node identification selector failed because it exposed a high
impact node to an unknown possibly harmful prompt and produced ER losses down to
`-22.47`. The anchor design avoided that failure: all ER cases tied frozen P11,
while BA, violent-SBM, and sparse-component cases retained large gains.
Persuasion later erased by shielding fell from 42 actions (84 budget units) to
18 actions (36 units).

This is not a pure selector effect. It changes both the selected-prompt anchor
action and the population prior used by subsequent unknown-node candidates, so
it can reorder communication and structure decisions. The result is a passed
development screen only. It does not enable production, combine with the 0.9
prior-discount experiment, or open repetitions 1401-1403. A separately frozen
fresh confirmation is required before any release decision.

Machine report:
`experiments/reports/p11-selected-prompt-anchor-development-20260914.json`,
SHA-256 `741ac3b7bb842091e06432eeb229d06a9ee26d6ce9114bee36713e51ff871f3a`.

Frozen identities:

- anchor subclass SHA-256: `f75796c6d46ff3cbb6e6461950e517d6cae7e10482a84fd09bb8641c1918c04e`
- runner SHA-256: `8746160eaf6198532c9f15ddbf4d37ee59b6145df8efbae41721dc93bb8d9865`
- frozen P11 runtime SHA-256: `98ae3471bd5eb9d024bd96ac678f19a6807877cccb45df53622b70a614880612`
- raw report SHA-256: `779ef6e430cc670eb5039c349aba19f4b954d61755cf479380e25f53ab00b7a2`
