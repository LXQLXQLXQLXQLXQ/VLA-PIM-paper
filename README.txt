VLA-PIM — IEEE conference working draft

导入 Overleaf
1. 已关联此 GitHub 仓库的 Overleaf 项目：Integrations → GitHub → Pull GitHub changes into Overleaf。
   单独使用 ZIP：New Project → Upload Project。
2. Main document 选择 conference_101719.tex。
3. Compiler 选择 XeLaTeX。原稿主体仍含中文，因此不能使用 pdfLaTeX。
4. 点击 Recompile。

工程结构
conference_101719.tex：入口，沿用原 ZIP 的 IEEEtran conference 双栏版式与原有英文标题。
IEEEtran.cls：来自用户提供的 ZIP，未修改。
sections/：七个独立部分（摘要、引言、背景、架构、数据流与调度、评估、结论）。
tables/：四张可编辑的原生 LaTeX 表格。
figures/：需要补入的图像清单。放入同名原图后，缺图框会自动变成图片。
references.bib：待补文献；目前没有虚构条目。
notes/numeric-provenance.txt：原稿中的数字出处，仅供写作核查，不参与论文编译。
notes/editorial-checklist.txt：原稿已有的待核事项。
latexmkrc：XeLaTeX 构建设置。

已完成
- 用 2026-11-16 Google Docs 导出内容替换旧模板中的旧摘要、旧引言与示例正文。
- 保持现有英文/中文语言状态，保留原文数据和占位提醒。
- 数学符号与 AE 间隔公式转换为原生 LaTeX 数学。
- 章节、表、现有插图位置使用自动编号与交叉引用。
- 移除示例作者、示例经费脚注、无关参考文献、示例图和说明正文。
- 提供作者/单位和参考文献的明确工作稿提示。

格式边界
此项目遵循用户 ZIP 所提供的通用 IEEEtran conference 模板。
提供的模板没有具体会议/年份的投稿说明，故未额外推断页数限制、匿名规则、版权和提交编号。
中文支持使用 XeLaTeX + Fandol；英文正文使用 Times 风格的 TeX Gyre Termes。
没有修改 IEEEtran.cls、页边距、栏宽、正文基础字号或行距。
目前是可继续编辑的论文工作稿，图像、引用、作者信息以及源稿待核项仍需补齐。

GitHub/Overleaf 同步需在 Overleaf 手动触发；仅 git push 不代表在线项目已经更新。

构建验证
已编译为 6 页 PDF，LaTeX 警告 0，overfull/underfull box 均为 0。
逐页检查已完成，详见 notes/verification.json。
源稿中的未完成内容详见 notes/editorial-checklist.txt。
