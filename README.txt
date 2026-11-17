VLA-PIM 论文初稿（全英文正文）

主文件：conference_101719.tex
编译器：默认 pdfLaTeX；也支持 XeLaTeX/LuaLaTeX。
格式：原版 IEEEtran conference 双栏，IEEEtran.cls 未修改。

Motivation 沿用用户从 Overleaf 推送的 05a7804 英文版本。
从 System Overview 到 Conclusion，正文逐段采用 Google Docs《Methodology 翻译》的英文原句。
英文同步以原文为准；Overall Performance 已按用户本次要求重写为 a--e 五组配置的分析。
Thor/Ramulator 实验设置段因缺少原文英文，按用户指示暂移至 notes/experimental-setup-awaiting-english.txt。
摘要、Introduction 和匿名作者栏沿用上游；methodology-zh-v3.md 仅为历史中文备份，不参与编译。
来源及核对记录见 notes/methodology-sync-2026-11-17.txt 和 notes/english-source-audit-2026-11-17.json。

图片：
- 系统概览（figures/system-overview.tex）；
- 输入预装载微架构（figures/microarchitecture.tex）；
- KV 布局与外部 DQ 流量（figures/layout-dq.tex，IV-A 的单栏图 6）；
- 单步执行时间线（figures/timeline.tex）；
- 解耦频率（figures/decoupled-rates.tex）。
原 RD 字段图已删除，字段格式合入 Table II 的单行注释；新增图 6 为用户确认的 KV 布局与 DQ 流量图。
Table II 采用已确认的 v3：BG/BA、Cmd.、Operation、Function 四列，RD/WR 指令逐行列出。
原性能表已替换为图 9：仅画 T_async VLA（async 与 VLA 之间用空格），a 的 serial/dual 两根柱及 b、c、d、e 各一根柱。
原 e、g 配置分别重命名为 d、e；原 d、f 不再出现在配置列表或正文分析中。
图 9 采用单栏布局，柱宽统一收窄、间距相等；图内仅保留配置编号，图注和正文按 b--e 的累加顺序交代新增方法。
单个箭头标注最终 e 相对 a-serial / a-dual 的 AE rate 倍率 1.82× / 1.76×。
原 Table III 内存配置表已删除；关键时序以“参数=数值”的紧凑形式列在 Table I 下方注释中，单位为 CK，数值沿用 LPDDR5X-8533 配置。
表格和章节自动编号；图片采用 4、5、6、7、9、10 的编号，共六张图、两张表。

原英文版备份：backup/english-2026-11-16-7e7442d 分支。
本次图表修改前另有 79239f0 源码归档，见 notes/figure-revision-2026-11-17.txt。
图 7、图 10 的矢量 PDF 与 600 dpi PNG 可用 figures/plot-timeline-rates.py 从已提交快照重绘。
图 9 的矢量 PDF 与 600 dpi PNG 可用 figures/plot-async-vla-performance.py 从原性能表数值重绘。
图 6 的 PDF/SVG 与 PNG 可用 figures/plot-layout-dq.py 从已提交字节计数快照重绘；插入与核验记录见 notes/layout-dq-insertion-2026-11-17.txt。
Overleaf：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。

图 7 绘图源码与原数据已按类别整理到 figures/fig7/，详见其中 README.md：
- scripts/：绘图、原数据校验与处理脚本，以及依赖版本；
- data/raw/：Streaming input / Input preloading 两组完整原始实验输出的无损压缩包、时序矩阵和 SHA-256 清单；
- data/processed/：从原数据重建的绘图 JSON。PDF/PNG 成图仍位于 figures/。
可直接执行 figures/fig7/scripts/plot_figure.py 绘图；rebuild_data.py 可在不依赖仓库外文件的情况下重新生成输入数据。
原 figures/plot-timeline-rates.py 和 figures/analyze-streaming-gaps.py 入口继续保留。
