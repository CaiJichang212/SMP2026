# 实验资源约束

2026-09-14 用户要求控制 CPU 使用，避免服务器卡死。当前服务器为 2 核、约 3.6 GiB 内存。

后续实验和重型检查遵守：

- 同时只运行一个计算任务；新矩阵默认 `--workers 1`。子 Agent 不自行启动并行重算。
- 用 systemd 对整个任务进程树设置 `CPUQuota=75%`，即合计最多 0.75 核，约为本机总算力的 37.5%。这不是每个 worker 各 75%。
- 设置 `Nice=19`，优先让出 CPU；当前机器可绑定 CPU 1，为其他工作留出 CPU 0。
- 设置 `MemoryHigh=1G` 作为内存软约束，持续观察内存和 swap；不使用会直接杀死正在保存数据的进程的激进硬限额。
- 保存可恢复进度；若需要暂停，先保留检查点。资源限额改变只影响实验速度，不用它调整策略参数或门槛。

本机已验证的启动方式（以 ubuntu 用户运行，不生成 root 所有的项目资产）：

```bash
sudo -n systemd-run --unit=smp2026-<本次唯一任务名> --uid=ubuntu --wait --pipe --collect \
  -p CPUQuota=75% -p MemoryHigh=1G -p Nice=19 -p CPUAffinity=1 \
  -p WorkingDirectory=/home/ubuntu/SMP2026casevo/SMP2026 \
  /home/ubuntu/.local/bin/uv run python <脚本与参数>
```

仅限制本任务，不能给整个用户会话或服务器的其他服务统一降速。当前进行中的 P11 确认
为保留进度仍有两个 worker，它们已经移入同一个受限 scope，共享上述总配额。
后续不要再另外启动一个同样配额的重任务，造成总用量叠加。
