VLA-PIM 论文

标题：VLA-PIM: LPDDR-PIM Architecture–Dataflow Co-Design for Heterogeneous Acceleration of Edge VLA Inference
主文件：conference_101719.tex
编译器：pdfLaTeX
格式：用户提供的 IEEEtran conference 双栏模板，IEEEtran.cls 未修改。
作者栏：Anonymous Authors / Paper under double-blind review。

当前排入八张图；前四张使用用户 2026-11-18 提供的 PDF，原 PDF 每页完整对应一张图：
1. PDF 第1页 → figures/execution-overview.pdf / .tex：Introduction。
2. PDF 第2页 → figures/vla-characterization.pdf / .tex：Background and Motivation。
3. PDF 第3页 → figures/system-overview.pdf / .tex：Architecture Design / System Overview（双栏）。
4. PDF 第4页 → figures/microarchitecture.pdf / .tex：Architecture Design / Input-preloaded microarch（单栏）。
5. KV 布局与 DQ 流量 → figures/layout-dq.tex（单栏）。
6. 单步执行时间线 → figures/timeline.tex（双栏）。
7. 总体性能对比 → figures/async-vla-performance.tex（单栏）。
8. 解耦频率 → figures/decoupled-rates.tex（单栏）。

图5–8统一使用Arial，包括数学符号和下标；PNG/TIFF位图均为600 dpi，TIFF采用无损LZW压缩。
四个绘图脚本共用 figures/figure_style.py。重绘时需在系统中安装Arial，或将 VLA_PIM_FONT_DIR 指向含Arial常规、斜体、粗体和粗斜体字体文件的目录；缺少Arial时脚本会报错。

总体性能图已扩展为单列宽度内的左右两张独立小图：(a) π0.5；(b) GR00T N1.6。
两图共用纵轴刻度，指标标注为 T_Async，a-s/a-d 表示串行/双流 GPU 基线。
GR00T 数据来自 Important data/gr00t-n16-h15-640x480-2026-11-18；原 n16-b/c/d/f 映射为 b/c/d/e，不含 RoPE。
GR00T 串行基线由归档 AE/VLM 单跑均值相加得到 104.13 ms（†）；双流柱补入用户指定的 compile AE p50 98.27 ms（柱顶按整数显示 98）。
最终配置的 AE rate 倍率：π0.5 为 1.82× / 1.76×（相对串行/双流），GR00T 为 1.40×（相对推导串行基线）。
绘图脚本：figures/plot-async-vla-performance.py；数据快照：figures/data/async-vla-performance.json。
原始数据来源和验证见 notes/performance-chart-gr00t-2026-11-18.json；双流补充数据见 figures/data/gr00t-dual-stream-cache-snapshot-20261118.json。
π0.5 六组结果已与 H=16 原始 Thor/仿真归档逐项核对，修正 JSON 中误写的 horizon=50；图注和正文已明确 H=16。
核对依据和原始文件哈希见 notes/performance-chart-pi05-h16-2026-11-18.json。

前四张分别为独立单页 PDF，仅修改页框去除外围空白；每页内部的子图保持完整，不拆分、不拼接。
原始 PDF 保存在 figures/sources/figures1107-20261118.pdf。
图1、3、4保留原矢量文字和路径；图2在源 PDF 中本来就是1474×1119位图，原嵌入图像流也未经重编码。
裁剪没有进行栅格化或重采样，页面内容流与原页逐字节一致；288 dpi 渲染核对与源页相同区域完全一致。
本次来源、校验和、裁剪坐标及精度核验见 notes/first-four-pdf-assets-2026-11-18.json。
旧 PNG/TIFF 转换记录 notes/figures1107-manifest.json 保留为历史记录，前四张的排版已改用 PDF。
图片采用自动编号，正文相应引用已更新。

后四张图已从 c8e45c5 恢复原版 PDF/PNG 和 LaTeX 包装文件，并恢复正文引用。
所有图统一自动编号为 1–8；时间线仍采用已确认的双栏版本。
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
