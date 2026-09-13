# Coverage13 saturated-hubs failure attribution

This is a post-hoc diagnosis on three already consumed development failures.
It is not new validation, does not open confirmation, and cannot qualify or
promote coverage13. The complete action logs, decisions, original initial16
rows, source identities, and action-set differences are retained in
`p9-coverage-saturated-failure-attribution-20260913.json` (SHA-256
`e83fffddb4369abe207f59d1c2520aab94f8949dbadc405853c03ca53f3cde1c`).

| Consumed case | Bounded | Coverage13 | Official best | Coverage - bounded | Coverage - official |
| --- | ---: | ---: | ---: | ---: | ---: |
| BA / 901 / saturated | 2071.3959 | 2084.6886 | 2173.6953 | +13.2926 | -89.0067 |
| BA / 902 / saturated | 2317.9647 | 2355.7891 | 2428.1305 | +37.8244 | -72.3414 |
| WS / 902 / saturated | 1702.0688 | 1715.6497 | 1704.4583 | +13.5808 | +11.1914 |

Coverage13 improved all three cases. Mean gain over bounded was `+21.5660`;
the original mean gap from bounded to official-best was `71.6182`. This shows
that public candidate prefiltering explains a material part of these failures,
but it does not explain the complete two-case BA deficit.

Each case selected exactly two `audited_excluded_structure` cuts. Every one of
those six cuts also appears in the corresponding official-best trajectory:

- BA901: `cut 26-42` and `cut 1-12`; predicted selection/audit minima were
  `6.0531/6.0531` and `4.0411/4.0411`.
- BA902: `cut 19-37` and `cut 18-23`; predicted selection/audit minima were
  `0.9856/2.4040` and `4.2342/2.6366`.
- WS902: `cut 18-45` and `cut 25-36`; predicted selection/audit minima were
  `5.8148/0.8101` and `0.3849/0.3849`.

Relative to bounded, coverage changed the intervention mix from
`2 shield / 2 cut / 29 comm` to `2 / 3 / 28` in BA901 and WS902, and from
`1 / 6 / 26` to `1 / 8 / 23` in BA902. The first coverage divergence occurred
at intervention 23, 5, and 24 respectively. These are late or middle-stage
candidate omissions rather than a failure to activate P8.

Official-best remained much more structure-heavy: it executed 13, 16, and 15
structure actions in the three cases, compared with coverage13's 5, 9, and 5.
Coverage recovered about 13.0% of the BA901 gap and 34.3% of the BA902 gap; it
more than closed WS902's small 2.3895-point gap. A broader or less conservative
structure policy is therefore a plausible next research direction, while this
three-case retrospective result is insufficient evidence to release it.

The run was serial (`workers=1`) and called the existing
`run_p9_distribution_validation._run_coverage` with P8 SHA-256
`30326ab80cee936c6feb57ec01722eafa0994e2d171d606e6f439a3106f334ca`
and coverage13 SHA-256
`55cc2895dd14fa934fc7bddc3fc406de7019d873e2b80548c461a0a61f121736`.
