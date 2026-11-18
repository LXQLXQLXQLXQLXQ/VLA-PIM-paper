VLA-PIM 论文

标题：VLA-PIM: LPDDR-PIM Architecture–Dataflow Co-Design for Heterogeneous Acceleration of Edge VLA Inference
主文件：conference_101719.tex
编译器：pdfLaTeX
格式：用户提供的 IEEEtran conference 双栏模板，IEEEtran.cls 未修改。
作者栏：Anonymous Authors / Paper under double-blind review。

当前排入八张图，其中图2为用户提供的高清版本：
1. 幻燈片1.tif → figures/execution-overview.tex：Introduction 结束处。
2. 用户新上传的高清 PNG → figures/vla-characterization.tex：Background and Motivation（已替换原幻燈片2）。
3. 幻燈片3.tif → figures/system-overview.tex：Architecture Design / System Overview（双栏）。
4. 幻燈片4.tif → figures/microarchitecture.tex：Architecture Design / Input-preloaded microarch（单栏）。
5. KV 布局与 DQ 流量 → figures/layout-dq.tex（单栏）。
6. 单步执行时间线 → figures/timeline.tex（双栏）。
7. 总体性能对比 → figures/async-vla-performance.tex（单栏）。
8. 解耦频率 → figures/decoupled-rates.tex（单栏）。

总体性能图已扩展为单列宽度内的左右两张独立小图：(a) π0.5；(b) GR00T N1.6。
两图共用纵轴刻度，指标为 T_async VLA（async 与 VLA 之间为空格），a-s/a-d 表示串行/双流 GPU 基线。
GR00T 数据来自 Important data/gr00t-n16-h15-640x480-2026-11-18；原 n16-b/c/d/f 映射为 b/c/d/e，不含 RoPE。
GR00T 串行基线由归档 AE/VLM 单跑均值相加得到 104.13 ms（†）；双流基线缺测，标为 N/A。
最终配置的 AE rate 倍率：π0.5 为 1.82× / 1.76×（相对串行/双流），GR00T 为 1.40×（相对推导串行基线）。
绘图脚本：figures/plot-async-vla-performance.py；数据快照：figures/data/async-vla-performance.json。
数据来源和验证见 notes/performance-chart-gr00t-2026-11-18.json。

图1、3、4由 TIFF 无损转换为全分辨率 PNG，大块白边仅由 LaTeX 的 trim/clip 裁去。
图2直接使用用户新上传的 1474×1119 PNG，逐字节复制原图，不缩放或裁切。
上述四张用户提供图片的内容均未重画。
源文件映射、校验和、裁切坐标见 notes/figures1107-manifest.json。
图片采用自动编号，正文相应引用已更新。

后四张图已从 c8e45c5 恢复原版 PDF/PNG 和 LaTeX 包装文件，并恢复正文引用。
所有图统一自动编号为 1–8；时间线仍采用已确认的双栏版本。
恢复记录见 notes/restored-back-figures-2026-11-17.txt。

Table I 已按每个 x64 PIM 封装补齐 VLA-PIM、LP-Spec、AHASD 和 Samsung 四种方案。
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
