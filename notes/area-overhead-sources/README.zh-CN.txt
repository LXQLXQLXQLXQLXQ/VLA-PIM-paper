ActPIM：DRAM 工艺面积折算（2026-11-15）

主结论（16-bank/die 文献归一化口径）
所评估四项块总计 12.252 mm²/die，占裸DRAM参考面积 20.11%。
匹配原有PIM块：4.156 mm²/die，占裸DRAM参考面积 6.82%。
新增：8.096 mm²/die，占裸DRAM参考面积 13.29%。
以“已有PIM die = 裸DRAM + 匹配基线块”为分母：新增 12.44%。
只以原PIM块作分母，增长 194.8%，不是整个die增幅。

计算
A_total = 每bank面积合计 × N × s / 1e6；A_base同式；A_increment = A_total - A_base。
总overhead=A_total/D；新增/裸DRAM=A_increment/D；新增/已有PIM die=A_increment/(D+A_base)。

工艺假设
AttAcc 4.1节（印刷页109）报告同一softmax单元1z-nm DRAM估计63.4mm²；7.7节（印刷页115）给7nm逻辑面积1.38mm²。
据此反推 s=63.4/1.38=45.94202899。这是本报告推导的有效倍率，原文没有把它声明为适用所有电路的通用常数。
把该倍率统一用于当前算术和DFF阵列是粗估假设，不能称为实测LPDDR外围工艺标定。
原文10倍密度差指相同特征尺寸，不能等同于全部7nm到1z缩放，也不能在45.94倍之后再乘10。
本报告不把“1z”指定为精确几何纳米数。

面积分母与物理组织
D=60.92mm²，采用LP-Spec V-A节用于16Gb LPDDR5的参考值；其引用Y.-H. Kim等ISSCC 2021论文25.2。
本轮核对的是LP-Spec引用数值，没有独立取得原ISSCC die照片。
主表假设每物理die16个bank/PE，与草稿单x16 die口径一致，属于16Gb参考归一化。
当前仿真器是8Gb/channel-rank，不能把60.92mm²默认为该8Gb块的实测die面积；channel-rank不一定等于物理die。
用户Micron文档含双x16 die。若两个通道都部署16套PE，则32套/die；固定同一参考面积时，总开销 40.22%，新增/裸DRAM 26.58%，新增/已有PIM die 23.39%。
只在一个通道安装PIM时按实际安装数计；电路禁用不免除面积。
假设8Gb die面积减半至30.46mm²时，裸DRAM归一化比例翻倍；这只是敏感度场景，不是8Gb实测数据。

匹配原有PIM基线
相同BF16/FP32 MAC（retime_k2）；无RoPE；输入512B、输出128B，端口配置与目标相同。
目标输入1KiB、输出2KiB、每bank一个RoPE。容量参考Samsung公开规格，但不是商业Samsung器件复刻。
Buffer全部使用实际综合的DFF阵列，包括读写选择和输出寄存器，没有替换为理想SRAM或按位数估算。
MAC新增面积为0，相同MAC只计一次。

范围与时序
总开销仅指所评估四项块，不含rank控制器、跨bank广播/归约、PHY、时钟树和布线；不代表遗漏成本为0。
采用原始cell area，无P&R utilization加成。面积缩放不说明DRAM上的频率、时序或功耗。
MAC533MHz setup初步通过；RoPE1.066GHz仍缺70ps。报告不是已实现LPDDR芯片的签核结果。
建议表题：Estimated DRAM-process area of evaluated bank-local blocks；正文：reference-normalized area estimate。

敏感度
有效倍率±25%（非置信区间）时，总约 15.08%–25.14%；新增/裸DRAM约 9.97%–16.61%。
主要成本来自Buffer（77.3%）；当前结果不足以支持“整个设计只增加几个百分点”。

交付
main.tex：英文预览；table.tex：论文表，需booktabs；methods.tex：英文方法与结果段落；references.bib：引用。
area_table.csv、sensitivity.csv、calculation.json：完整输入和计算结果；calculate.py：标准库重算脚本。
在本目录运行 python3 calculate.py 可从上级原始综合JSON重算；不执行EDA、不修改原始数据。
