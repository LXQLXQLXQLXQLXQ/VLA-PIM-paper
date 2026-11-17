VLA-PIM 论文初稿（全英文正文）

主文件：conference_101719.tex
编译器：默认 pdfLaTeX；也支持 XeLaTeX/LuaLaTeX。
格式：原版 IEEEtran conference 双栏，IEEEtran.cls 未修改。

Motivation 沿用用户从 Overleaf 推送的 05a7804 英文版本。
从 System Overview 到 Conclusion，正文逐段采用 Google Docs《Methodology 翻译》的英文原句。
仅转换 LaTeX、数学公式、排版与交叉引用，不自行翻译中文或改写英文。
Thor/Ramulator 实验设置段因缺少原文英文，按用户指示暂移至 notes/experimental-setup-awaiting-english.txt。
摘要、Introduction 和匿名作者栏沿用上游；methodology-zh-v3.md 仅为历史中文备份，不参与编译。
来源及核对记录见 notes/methodology-sync-2026-11-17.txt 和 notes/english-source-audit-2026-11-17.json。

图片：
- 系统概览（figures/system-overview.tex）；
- 输入预装载微架构（figures/microarchitecture.tex）；
- 单步执行时间线（figures/timeline.tex）；
- DQ 空隙分布（figures/dq-gaps.tex）；
- 解耦频率（figures/decoupled-rates.tex）。
图 6 已按用户要求删除，RD 字段格式合入 Table II 的单行注释。
Table II 采用已确认的 v3：BG/BA、Cmd.、Operation、Function 四列，RD/WR 指令逐行列出。
表格和章节自动编号；图片保留 4、5、7、8、10 的编号，共五张图、四张表。

原英文版备份：backup/english-2026-11-16-7e7442d 分支。
本次修改前的完整源码归档位置见 notes/methodology-sync-2026-11-17.txt。
Overleaf：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。
