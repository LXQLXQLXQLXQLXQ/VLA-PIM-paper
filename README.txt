VLA-PIM 论文

标题：VLA-PIM: LPDDR-PIM Architecture–Dataflow Co-Design for Heterogeneous Acceleration of Edge VLA Inference
主文件：conference_101719.tex
编译器：pdfLaTeX
格式：用户提供的 IEEEtran conference 双栏模板，IEEEtran.cls 未修改。
作者栏：Anonymous Authors / Paper under double-blind review。

当前只排入用户提供的 figures1107 四张图：
1. 幻燈片1.tif → figures/execution-overview.tex：Introduction 结束处。
2. 幻燈片2.tif → figures/vla-characterization.tex：Background and Motivation。
3. 幻燈片3.tif → figures/system-overview.tex：Architecture Design / System Overview（双栏）。
4. 幻燈片4.tif → figures/microarchitecture.tex：Architecture Design / Input-preloaded microarch（单栏）。

TIFF 无损转换为全分辨率 PNG，图中内容与像素未重画、未缩放。
原幻灯片的大块白边仅由 LaTeX 的 trim/clip 裁去；PNG 本身保留完整画布。
源文件映射、校验和、裁切坐标见 notes/figures1107-manifest.json。
图片采用自动编号，正文相应引用已更新。

暂缓插入的图：KV 布局、单步时间线、总体性能对比、解耦频率。
这些缺失的输入和纯图示引用已在源码中注释或改为不依赖图号的表述，避免缺文件/未定义引用；未放空白占位框。
以后收到对应图片后再恢复相应插图。

已移除 Architecture 中意外残留的空嵌套 href 命令。
正文论述、实验数值及已有待补条目保留；只调整与图片绑定的交叉引用。
构建验证记录见 notes/verification.json。
历史修改和原始数据来源记录仍保存在 notes/ 与 Git 历史中。

Overleaf：Integrations → GitHub → Pull GitHub changes into Overleaf，然后重新编译。
