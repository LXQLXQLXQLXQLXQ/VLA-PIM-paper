# π0.5 / GR00T N1.6 功耗与能耗数据

这里保存 2026-11-18 完成的功耗比较，以及 2026-11-19 整理到论文仓库的
数据和脚本。π0.5 沿用 2026-11-17 的结果；GR00T 使用新完成的 Thor 实测和
完整原生仿真。所有比值均为 **基线 ÷ 方案**。

| 模型 | 基线 VIN / W | GPU 代理 / W | DRAM / W | PIM 逻辑 / W | g 合计 / W | 功耗比 | 能耗比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| π0.5 | 98.852 | 50.358 | 12.677 | 5.409 | 68.445 | 1.444× | 2.524× |
| GR00T N1.6 | 82.820 | 43.629 | 7.466 | 5.409 | 56.504 | 1.466× | 1.860× |

| 模型 | 基线完成周期 / ms | g 单 pair / ms | 基线能耗 / J | g 能耗 / J |
|---|---:|---:|---:|---:|
| π0.5 | 135.747 | 77.678 | 13.4188 | 5.3166 |
| GR00T N1.6 | 94.439 | 74.410 | 7.8214 | 4.2045 |

## 文件入口

- 图表：[PNG](../../figures/power-energy-ratios.png)、
  [矢量 PDF](../../figures/power-energy-ratios.pdf)、
  [SVG](../../figures/power-energy-ratios.svg)。
- 汇总：[JSON](../../figures/data/power-energy-comparison.json)、
  [CSV](../../figures/data/power-energy-comparison.csv)、
  [详细说明](../../figures/data/power-energy-comparison.zh-CN.md)。
- [相对路径绘图及汇总脚本](../../figures/plot-power-energy-ratios.py)。
- `models/{pi05,gr00t}/`：完整原生 raw 结果、DRAM 状态/命令统计、逐项 IDD
  报告、Thor 测量 JSON 及原始 tegrastats；较大原始文件以无损 gzip 保存。
- `configs/`：两次计算实际使用的时序、Micron IDD、PIM 逻辑参数及原仿真配置。
- `scripts/g_power_report.py`：原生统计审计及 DRAM 功耗公式实现，逐字节副本。
- `scripts/verify_power_data.py`：校验原始字节、独立积分两模型 Thor 采样，
  并从完整状态统计重算两份 IDD 报告及最终比值；仅依赖 Python 标准库。
- `scripts/thor/`：GR00T Thor 功耗测量代码及本次使用的辅助代码；
  `scripts/pi05/bench_power.py` 是此前 π0.5 测量入口。
- `scripts/observer/`：被动原生功耗观察器、控制器和前端源码快照。
- `original/`：原报告、原绘图脚本、提交清单、资源记录和 Thor/Slurm 启动脚本。
  这些是保留现场路径的历史记录；原 Slurm 脚本不适合作为新的直接提交入口。
- `SOURCE-MANIFEST.json`：每个原始副本的来源、原始 SHA-256 和压缩后 SHA-256。

## 离线复算和绘图

在论文仓库根目录执行，Python 3.10 或更新版本：

```bash
PYTHONDONTWRITEBYTECODE=1 python notes/power-energy-2026-11-18/scripts/verify_power_data.py
python figures/plot-power-energy-ratios.py --no-plot
```

绘图还需安装 `requirements-plot.txt` 中的 matplotlib / numpy。建议使用已有
绘图虚拟环境；安装位置由使用者指定。在本工作区安装时，环境置于 `/fact_data`，
可丢弃安装缓存和临时文件置于 `/scratch`。随后执行：

```bash
python figures/plot-power-energy-ratios.py
```

脚本将重算 JSON/CSV/说明并导出 PNG/PDF/SVG；使用 `--output-root PATH` 可将
全部产物输出到另一目录。输入路径相对于仓库，不依赖原实验机器的目录。
Matplotlib 缓存默认在输出目录的 `figures/.cache/`，也可通过
`MPLCONFIGDIR` 指定可丢弃缓存路径。

验证脚本不启动 Thor、模型或仿真，也不提交 Slurm 作业。论文仓库没有包含
模型权重、编译后的仿真器、完整模型运行环境、217 MB 指令程序或训练数据；
这些不是从已归档计数复算功耗和重绘图所必需的。若重做采集/仿真，需另外
准备原模型依赖、checkpoint、仿真器完整源码/构建及输入程序，并调整现场
路径；原始输入和二进制哈希可查 `original/manifest-native.json`。

## 计算口径和限制

```text
P_g = P_GPU,fresh-cache + P_DRAM,IDD + P_PIM-logic
R_power = P_board,VIN / P_g
R_energy = (P_board,VIN × T_baseline) / (P_g × T_g)
```

两模型的 Thor 基线均为 AE 等待自身最新 VLM cache 的 `fresh_cache` 模式，
各取三轮 30 秒，积分 VIN 和 VDD_GPU 得到平均功耗。π0.5 共完成 663 个 AE
chunk；GR00T 共完成 953 个。基线时间是稳态完成周期；g 时间是一个原生
GPU/PIM pair 的完成时间。GR00T 无 RoPE，完整输入预装载配置原名 `n16-f`，
在此次任务中对应完整 g。

π0.5 继承原测量中的 BF16、H=16、10 步 synthetic physical MHA8 配置：
基于原 checkpoint 将 K/V 权重物理展开为 8 个头，其他参数保持原配置。
该转换的完整元数据保存在 `models/pi05/thor/measurements.json` 的
`workload.conversion` 中。GR00T 使用 N1.6 checkpoint、BF16、H=15、4 步去噪、
三路 640×480 原图及默认预处理后的 ViT 输入。

DRAM 模型计入 **8 package × 2 channels/package × 2 ranks/channel × 16 banks
= 512 DRAM banks**，其中 PIM rank 共 **256 banks**。512 bank 已包含在
DRAM 报告中，不再将其总功耗额外乘 8。逻辑采用用户提供的 ASAP7、0.7 V、
约 533 MHz 全活动参考：**21.13 mW × 256 = 5.40928 W**。该数值不是按 trace
活动率加权的实际平均功耗；GR00T 虽无 RoPE 指令，此固定硬件参考仍保留
RoPE 模块份额。图中分项四舍五入之和 21.14 mW 与给定合计 21.13 mW 的
差异保留在原配置中；计算统一采用给定合计，不乘面积倍率或额外 lane 数。

Micron 参数使用 16-Gbit 单 die 的 IDD 作为未改动的 8-Gbit 仿真组织的代理。
rho=0.5，PIM 内部列访问能量未由厂商标定；ACT/PRE 使用每次有效 ACT 的
联合增量能量，不能解读为独立标定的 ACT 与 PRE 能量。公式对齐 DRAMPower
的 LPDDR5 计算方法，是本地实现，并非直接运行上游 DRAMPower 库。

**这些比值属于约定的简化估算。** 分子为实测整板 VIN，分母只有 GPU 代理、
DRAM 和指定 PIM 逻辑，缺少其他 CPU/SoC/载板功耗，且两侧时间定义不同。
不能将结果表述为统一范围、已测量的整板能效提升。

GR00T 原生重跑用时 23:30.66，退出码 0，输出与未加观察器的原版逐字节一致。
Slurm 2075142 整体状态为 FAILED/1:0，原因是最后绘图阶段缺 matplotlib；
仿真和 DRAM 报告均成功，补齐隔离的绘图依赖后，后处理已成功完成。

## Overleaf

GitHub 中的数据、图和脚本通过 Overleaf 的 **Integrations → GitHub → Pull
GitHub changes into Overleaf** 同步。本次添加复现资料，未改动论文正文或
自动插入新图。
