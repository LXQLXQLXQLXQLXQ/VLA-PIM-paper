VLA-PIM 论文初稿（全英文正文）

主文件：conference_101719.tex
编译器：默认 pdfLaTeX；也支持 XeLaTeX/LuaLaTeX。
格式：原版 IEEEtran conference 双栏，IEEEtran.cls 未修改。

Motivation 沿用用户从 Overleaf 推送的 05a7804 英文版本。
第 III 节至结论更新自 Google Docs《Methodology 翻译》（2026-11-17）。
摘要、Introduction 和匿名作者栏沿用上游；methodology-zh-v3.md 仅为历史中文备份，不参与编译。
来源、图表口径与保留的待补项见 notes/methodology-sync-2026-11-17.txt。

图片：
- 系统概览（figures/system-overview.tex），依据方法描述绘制；
- 输入预装载微架构（figures/microarchitecture.tex）；
- RD 命令逻辑字段复用（figures/command-fields.tex），不表示实际 C/A 引脚或周期顺序；
- 单步执行时间线（figures/timeline.tex）；
- DQ 空隙分布（figures/dq-gaps.tex）；
- 解耦频率（figures/decoupled-rates.tex）。
全部图注、四张表及公式已同步为英文。
DQ 图已去掉统一 15 CK 门限标记，可用 figures/plot-dq-gaps.py 和提交的统计快照再生成。
表格和章节自动编号；图片保留原稿 4、5、6、7、8、10 的编号。

原英文版备份：backup/english-2026-11-16-7e7442d 分支。
Overleaf：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。
