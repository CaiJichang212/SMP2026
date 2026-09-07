# P2.3 结构策略配对实验结果

总门禁：`False`。

| 对比 | seed block | 均值 Δ | 中位 Δ | 95% CI | 最差拓扑族 | 判定 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| `b3_single_structure-b1_persuasion` | 24 | 101.731 | 34.500 | [43.440, 165.115] | -9.255 | False |
| `b4_beam_structure-b1_persuasion` | 24 | 101.052 | 30.665 | [44.274, 162.663] | -9.255 | False |
| `b4_beam_structure-b3_single_structure` | 24 | -0.679 | 0.000 | [-6.864, 5.138] | -13.345 | False |

可比失败数：`0`；结构动作记录：`{'b1_persuasion': 0, 'b3_single_structure': 60, 'b4_beam_structure': 60}`。
