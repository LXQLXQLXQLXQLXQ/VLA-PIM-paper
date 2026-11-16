VLA-PIM 论文初稿

主文件：conference_101719.tex
编译器：默认 pdfLaTeX 即可；源码同时保留 XeLaTeX/LuaLaTeX 的按引擎加载分支。
格式：用户提供的 IEEEtran conference 双栏模板，类文件未修改。

已按 Google Docs 原稿填入摘要、Introduction、背景与动机、架构设计、数据流与调度、评估和结论。
原有中英文内容、数据、表格、公式及待核标记保留。
第 III–VII 节（架构设计至结论）已按 essay/ActPIM_初稿_v3.md 改写为英文，并排入图片（figures/）：
输入预装载微架构图、单步执行时间线、DQ 空隙分布、解耦频率；数据图由 essay/figures/plot_paper_figures.py 生成，图内系统名为 VLA-PIM。
第 I–II 节保持此前迁移的内容。尚无图像的系统概览图与 RD 命令格式图以 [TBD] 标注，不放缺图框。
没有额外添加作者占位、关键词或红色 Draft 提示；没有限制页数。sections/99-references.tex 列出第 III–V 节引用的文献，Samsung LPDDR5X-PIM 一项待补。

Overleaf 同步：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。
sections/：按章节拆分的正文。
tables/：原生 LaTeX 表格（第 III–V 节五张，英文）。
figures/：第 III–V 节用图。
notes/numeric-provenance.txt：原稿注明“不进论文”的数字出处。
