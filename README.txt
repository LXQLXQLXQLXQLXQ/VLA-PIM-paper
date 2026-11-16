VLA-PIM 论文初稿（中文 Methodology 及之后）

主文件：conference_101719.tex
编译器：默认 pdfLaTeX；也支持 XeLaTeX/LuaLaTeX。
格式：原版 IEEEtran conference 双栏，IEEEtran.cls 未修改。

第 III 节至结论恢复为 essay/ActPIM_初稿_v3.md 的中文内容。
methodology-zh-v3.md 保存对应文字稿；Google Docs 的批注锚点和传输元数据未排入论文。
摘要、第 I–II 节、匿名作者栏及原有参考文献保留当前上游版本。

图片：
- 输入预装载微架构（figures/microarchitecture.tex）；
- 单步执行时间线（figures/timeline.tex）；
- DQ 空隙分布（figures/dq-gaps.tex）；
- 解耦频率（figures/decoupled-rates.tex）。
数据图使用上游 PDF 矢量版本，中文图注与正文对应。
正文仍保留待核项；不据批注推断新数据或修改实验结论。
表格和章节采用原有的自动编号，图片保留原稿 5、7、8、10 的编号。

英文版备份：backup/english-2026-11-16-7e7442d 分支（7e7442db239df98b82a372167e82c4453d1ecb74）。
本地 ZIP：essay/backups/VLA-PIM-paper_英文版_2026-11-16_7e7442d.zip。

Overleaf：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。
