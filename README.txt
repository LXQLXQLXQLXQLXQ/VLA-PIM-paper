VLA-PIM 论文

标题：VLA-PIM: LPDDR-PIM Architecture–Dataflow Co-Design for Heterogeneous Acceleration of Edge VLA Inference
主文件：conference_101719.tex
编译器：pdfLaTeX
格式：用户提供的 IEEEtran conference 双栏模板，IEEEtran.cls 未修改。
作者栏：Anonymous Authors / Paper under double-blind review。

当前排入七张图；图1、3、4沿用用户PDF的对应完整页面，图2重新从原始矢量版导出高清PNG：
1. 2026-11-19 新导出的 figures1107.pdf 第1页 → figures/execution-overview.pdf / .tex：Introduction（新版含时间轴）。
2. 原始矢量版 v17 → figures/vla-characterization.png / .tex：Background and Motivation（1200 dpi，4914×3733）。
3. 2026-11-19 最新PDF（r2）第3页 → figures/system-overview.pdf / .tex：Architecture Design / System Overview（双栏）。
4. figures1107(3).pdf（2026-11-19） → figures/microarchitecture.pdf / .tex：Architecture Design / Input-preloaded microarch（单栏；新版bank内部微架构）。
5. KV 布局与 DQ 流量 → figures/layout-dq.tex（单栏）。
6. 单步执行时间线 → figures/timeline.tex（双栏）。
7. 评估三联图 → figures/evaluation-summary.tex（双栏）：(a) 异步周期，(b) 每个 AE chunk 的能耗，(c) 解耦频率。

排版调整（2026-11-19）：Fig6提前到第5页，Fig7仍在第6页；完整PDF共7页（含参考文献）。
按用户要求，将单栏/双栏浮动图表与正文的间距设为10pt plus 2pt minus 2pt；字号、行距、页边距和图片尺寸保持不变。
Fig6在 sections/03-architecture.tex 中提前入队，Fig7在 sections/05-evaluation.tex 开头入队；图注和正文内容保留。
验证记录：notes/fig6-placement-spacing-2026-11-19.json。

图5–7统一使用Arial，包括数学符号和下标；PNG/TIFF位图均为600 dpi，TIFF采用无损LZW压缩。
三个绘图脚本共用 figures/figure_style.py。重绘时需在系统中安装Arial，或将 VLA_PIM_FONT_DIR 指向含Arial常规、斜体、粗体和粗斜体字体文件的目录；缺少Arial时脚本会报错。

Fig7(a) 中的 π0.5 和 GR00T N1.6 共用纵轴刻度，指标标注为 T_Async，a-s/a-d 表示串行/双流 GPU 基线。
GR00T 数据来自 Important data/gr00t-n16-h15-640x480-2026-11-18；原 n16-b/c/d/f 映射为 b/c/d/e，不含 RoPE。
GR00T 串行基线由归档 AE/VLM 单跑均值相加得到 104.13 ms；双流柱补入用户指定的 compile AE p50 98.27 ms（柱顶按整数显示 98）。
最终配置的 AE rate 倍率：π0.5 为 1.82× / 1.76×（相对串行/双流），GR00T 为 1.40×（相对推导串行基线）。
绘图脚本：figures/plot-evaluation-summary.py；周期数据快照：figures/data/async-vla-performance.json。
原始数据来源和验证见 notes/performance-chart-gr00t-2026-11-18.json；双流补充数据见 figures/data/gr00t-dual-stream-cache-snapshot-20261118.json。
π0.5 六组结果已与 H=16 原始 Thor/仿真归档逐项核对，修正 JSON 中误写的 horizon=50；图注和正文已明确 H=16。
核对依据和原始文件哈希见 notes/performance-chart-pi05-h16-2026-11-18.json。

图1、3、4分别为独立单页PDF，仅裁外围空白，保留原矢量文字、路径和完整子图。
图1采用新导出的 figures1107.pdf 第1页，等比例缩放到原图的排版高度；图3采用 figures/sources/figures1107-20261119-r2.pdf 第3页。
图4来自 figures/sources/figures1107-3-20261119.pdf 的完整单页，仅裁外围空白，保留全部文字、矢量内容和原始嵌入位图。
图4图注已对应新版bank内部微架构；本次更新沿用原575.25×495 pt图框；裁剪及编译验证记录见 notes/fig4-replacement-2026-11-19.json。
新版PDF第2页仍是旧的1474×1119位图；图2采用本地新版矢量母版 figures/sources/vla-characterization-v17.pdf 直接导出PNG，横轴改为 Operational intensity (FLOP/B)。
当前图2为1200 dpi、4914×3733无损PNG，未放大旧位图，未经过JPEG压缩；数据、标签、配色和布局保留。
运行 python figures/export-vla-characterization.py --dpi 1200 可重新导出（需pypdfium2和Pillow）。
本次图1、3替换与验证记录见 notes/figures-1-3-refresh-2026-11-19.json；此前图1–3更新记录见 notes/figures-1-3-update-2026-11-19.json；历史记录见 notes/first-four-pdf-assets-2026-11-18.json 和 notes/fig2-native-bitmap-2026-11-18.json。
旧PNG/TIFF及四页PDF转换记录保留为历史记录；图2的LaTeX当前明确引用PNG，其余三张仍引用PDF。
图片采用自动编号，正文相应引用已更新。

后四张图已从 c8e45c5 恢复原版 PDF/PNG 和 LaTeX 包装文件，并恢复正文引用。
恢复时所有图统一自动编号为 1–8；时间线仍采用已确认的双栏版本。
恢复记录见 notes/restored-back-figures-2026-11-17.txt。

Table I 已按四个 x16 PIM 裸片（x64）统一归一化，比较 VLA-PIM、LP-Spec、AHASD 和 Samsung 四种方案。
参考器件已更正为 Micron MT62F2G32D4DS；实际每封装含两个 PIM 裸片、32 个 PIM bank，与表中归一化口径分别注明。
保留 BF16-equivalent 折算、AHASD 统计范围假设、缓冲区来源和时序说明；引用改为正式文献。
详见 notes/tableI-completion-2026-11-17.txt。

已移除 Architecture 中意外残留的空嵌套 href 命令。
正文论述、实验数值及已有待补条目保留；只调整与图片绑定的交叉引用。
构建验证记录见 notes/verification.json。
历史修改和原始数据来源记录仍保存在 notes/ 与 Git 历史中。

Overleaf：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。

完整面积数据已放在文末功耗/能耗说明之后，独立附录 Complete Area Overhead Data（第9–10页）。
- sections/area-overhead-complete.tex：四模块分项、全部十组综合记录、匹配基线、DRAM折算、物理组织与敏感度、时序和验证条件。
- notes/area-overhead-sources/：两份原始报告逐字节副本；notes/area-overhead-synthesis.csv：全部综合记录；notes/area-overhead-data.json：输入和计算结果。
- 正文 M11 仅填入20.11%，正文其他文字、最新图表及功耗/能耗说明保持不变。

π0.5 / GR00T 功耗与能耗数据及复现脚本（2026-11-19）：
- 数据归档、原始采样、DRAM统计、计算假设和复算说明：notes/power-energy-2026-11-18/README.md。
- 汇总数据：figures/data/power-energy-comparison.json、.csv、.zh-CN.md。
- 图：figures/power-energy-ratios.png、.pdf、.svg；绘图入口：figures/plot-power-energy-ratios.py。
- 标准库核对入口：notes/power-energy-2026-11-18/scripts/verify_power_data.py。
- 正文 Fig7(b) 使用上述能耗数据；单独的功耗比图保留在归档中。

Fig5–7 绘图脚本与数据

所有路径均相对仓库根目录；这三张图可仅使用本仓库中的脚本和JSON快照重绘，无需父目录中的仿真仓库或实验结果。
- Fig5：figures/plot-layout-dq.py；数据 figures/data/layout-dq-20261117.json。
- Fig6（当前双面板、VLM kernel 编号版）：figures/plot-timeline.py；数据 figures/data/timeline-vlm-priority.json。
- Fig7：figures/plot-evaluation-summary.py；三个面板分别使用 figures/data/ 下的 async-vla-performance.json、power-energy-comparison.json 和 decoupled-rates.json。
- 共用模块：figures/figure_style.py，配置Arial文字/公式字体并导出600 dpi无损TIFF。
- 历史Fig6数据：figures/data/timeline.json、figures/data/streaming-input-gap.json，为旧版带DQ放大图保留，当前脚本不读取这两份快照。

运行环境：Python 3.10+、Matplotlib 3.10+、NumPy、Pillow，以及Arial字体（常规、斜体、粗体、粗斜体）。
Arial字体文件不随仓库分发；若系统未安装Arial，先将环境变量 VLA_PIM_FONT_DIR 指向字体文件目录。
在仓库根目录运行：
  python figures/plot-layout-dq.py
  python figures/plot-timeline.py
  python figures/plot-evaluation-summary.py --out figures
默认输出到 figures/；可加 --out 输出目录，以便预览而不覆盖现有图片。
注意：Fig6脚本保留历史文件名 fig7_step_timeline.pdf/png/svg；论文实际使用的位图别名为 fig6_timeline.png/tif。
Overleaf从GitHub拉取后会保存这些源文件；LaTeX编译使用已导出的图片，不会自动执行Python脚本。
