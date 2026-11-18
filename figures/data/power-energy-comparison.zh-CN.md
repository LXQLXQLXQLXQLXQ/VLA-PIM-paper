# pi0.5 与 GR00T 功耗、能耗对比

| 模型 | 基线板上功耗/W | GPU代理/W | DRAM/W | PIM逻辑/W | g合计/W |
|---|---:|---:|---:|---:|---:|
| pi0.5 | 98.852 | 50.358 | 12.677 | 5.409 | 68.445 |
| GR00T N1.6 | 82.820 | 43.629 | 7.466 | 5.409 | 56.504 |

| 模型 | 基线周期/ms | g单pair/ms | 基线能耗/J | g能耗/J | 功耗比 | 能耗比 |
|---|---:|---:|---:|---:|---:|---:|
| pi0.5 | 135.747 | 77.678 | 13.4188 | 5.3166 | 1.444 | 2.524 |
| GR00T N1.6 | 94.439 | 74.410 | 7.8214 | 4.2045 | 1.466 | 1.860 |

比值为基线除以估算方案；大于 1 表示该估算下方案功耗或能耗更低。两图分别给出功耗比和用户此前定义的能耗比。

GR00T：3 轮各 30 秒，共完成 953 个 AE chunk。完整仿真 raw.json 与原 640×480 n16-f 结果逐字节一致。

**此结果为此前约定的简化估算，不是统一范围的整板能效测量。**

- Numerator: measured whole-board VIN. Denominator: baseline VDD_GPU proxy + modeled DRAM + supplied PIM logic reference; other board/CPU/SoC power is omitted.
- Baseline time is measured steady AE completion period. Proposed time is a single simulated combined pair, not a multi-frame steady-state simulation.
- Both models use the same Micron IDD proxy (16-Gbit current data with unchanged 8-Gbit simulated dies), rho=0.5, and uncalibrated PIM internal-column energies.
- PIM logic is the same 5.40928-W, 256-bank full-active ASAP7 reference for both models, not trace-weighted logic power. GR00T has no RoPE operations; the fixed hardware-reference scenario still includes its RoPE allocation.
- pi0.5 reuses its prior frozen measurement/simulation; GR00T uses this newly measured fresh-cache baseline and a byte-identical instrumented rerun of n16-f.
