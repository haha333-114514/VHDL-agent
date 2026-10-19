# 知电实验报告：ROM 与文件驱动验证

- 实验编号：692b29037ed749799ecab9de2cffa70d
- 时间：2026-10-19T10:11:46+08:00
- 模式：本地证据诊断
- 源码 SHA-256：`c7a38d3fd4b5752d781fcc413ca65a6302216b5215e3374a0c9523b15e996d1a`
- 教学参考版本：否

## 任务约束

- 地址为 0–15，输出为地址的平方
- 候选电路本身不访问文件；文件读写由固定测试平台完成
- 可下载测试平台、输入向量与实际输出，核对 endfile / readline / writeline 流程

## 实际运行结果

30 / 32 个检查点通过，2 个不符合参考值。

覆盖范围：全部 16 地址及倒序重读；实际生成并核对文件 I/O 结果

诊断：ROM 表项与文件中的参考值不一致

测试平台实际读取了地址与参考值，并采样 ROM 输出。检查失败地址的常量表项。

## 失败检查点（最多前 20 个）

| 检查点 | 时间/ns | 输入 | 预期 | 实际 |
| --- | --- | --- | --- | --- |
| 10 | 100 | addr=9 | 81 | 0 |
| 23 | 230 | addr=9 | 81 | 0 |

## 运行轨迹

- 读取实验约束：固定接口、参考模型与测试平台；本次源码单独保存。
- 基础检查已完成：4 / 4 个检查点通过，0 个不符合参考值。
- 完整测试已完成：30 / 32 个检查点通过，2 个不符合参考值。
- 整理仿真证据：保留 32 个检查点、原始日志及实际生成的 VCD。
- 生成学习建议：ROM 表项与文件中的参考值不一致

## 被测源码

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity square_rom is
  port(addr : in unsigned(3 downto 0); data : out unsigned(7 downto 0));
end entity;
architecture rtl of square_rom is
  type rom_array is array(0 to 15) of unsigned(7 downto 0);
  constant rom : rom_array := (0 => to_unsigned(0,8), 1 => to_unsigned(1,8), 2 => to_unsigned(4,8), 3 => to_unsigned(9,8), 4 => to_unsigned(16,8), 5 => to_unsigned(25,8), 6 => to_unsigned(36,8), 7 => to_unsigned(49,8), 8 => to_unsigned(64,8), 9 => to_unsigned(0,8), 10 => to_unsigned(100,8), 11 => to_unsigned(121,8), 12 => to_unsigned(144,8), 13 => to_unsigned(169,8), 14 => to_unsigned(196,8), 15 => to_unsigned(225,8));
begin
  data <= rom(to_integer(addr));
end architecture;
```

## 原始工具输出

```text
$ ghdl -a --std=08 --workdir=. candidate.vhd

$ ghdl -a --std=08 --workdir=. zd_tb.vhd

$ ghdl -e --std=08 --workdir=. zd_tb

$ ghdl -r --std=08 --workdir=. zd_tb --vcd=wave.vcd --stop-time=10us --stop-delta=1000 --assert-level=failure --max-stack-alloc=1024
zd_tb.vhd:27:13:@10ns:(report note): ZD_CHECK|1|10|rom|0|0|addr=0
zd_tb.vhd:27:13:@20ns:(report note): ZD_CHECK|2|20|rom|1|1|addr=1
zd_tb.vhd:27:13:@30ns:(report note): ZD_CHECK|3|30|rom|4|4|addr=2
zd_tb.vhd:27:13:@40ns:(report note): ZD_CHECK|4|40|rom|9|9|addr=3
zd_tb.vhd:27:13:@50ns:(report note): ZD_CHECK|5|50|rom|16|16|addr=4
zd_tb.vhd:27:13:@60ns:(report note): ZD_CHECK|6|60|rom|25|25|addr=5
zd_tb.vhd:27:13:@70ns:(report note): ZD_CHECK|7|70|rom|36|36|addr=6
zd_tb.vhd:27:13:@80ns:(report note): ZD_CHECK|8|80|rom|49|49|addr=7
zd_tb.vhd:27:13:@90ns:(report note): ZD_CHECK|9|90|rom|64|64|addr=8
zd_tb.vhd:27:13:@100ns:(report note): ZD_CHECK|10|100|rom|0|81|addr=9
zd_tb.vhd:30:15:@100ns:(assertion warning): ZD_MISMATCH|rom
zd_tb.vhd:27:13:@110ns:(report note): ZD_CHECK|11|110|rom|100|100|addr=10
zd_tb.vhd:27:13:@120ns:(report note): ZD_CHECK|12|120|rom|121|121|addr=11
zd_tb.vhd:27:13:@130ns:(report note): ZD_CHECK|13|130|rom|144|144|addr=12
zd_tb.vhd:27:13:@140ns:(report note): ZD_CHECK|14|140|rom|169|169|addr=13
zd_tb.vhd:27:13:@150ns:(report note): ZD_CHECK|15|150|rom|196|196|addr=14
zd_tb.vhd:27:13:@160ns:(report note): ZD_CHECK|16|160|rom|225|225|addr=15
zd_tb.vhd:27:13:@170ns:(report note): ZD_CHECK|17|170|rom|225|225|addr=15
zd_tb.vhd:27:13:@180ns:(report note): ZD_CHECK|18|180|rom|196|196|addr=14
zd_tb.vhd:27:13:@190ns:(report note): ZD_CHECK|19|190|rom|169|169|addr=13
zd_tb.vhd:27:13:@200ns:(report note): ZD_CHECK|20|200|rom|144|144|addr=12
zd_tb.vhd:27:13:@210ns:(report note): ZD_CHECK|21|210|rom|121|121|addr=11
zd_tb.vhd:27:13:@220ns:(report note): ZD_CHECK|22|220|rom|100|100|addr=10
zd_tb.vhd:27:13:@230ns:(report note): ZD_CHECK|23|230|rom|0|81|addr=9
zd_tb.vhd:30:15:@230ns:(assertion warning): ZD_MISMATCH|rom
zd_tb.vhd:27:13:@240ns:(report note): ZD_CHECK|24|240|rom|64|64|addr=8
zd_tb.vhd:27:13:@250ns:(report note): ZD_CHECK|25|250|rom|49|49|addr=7
zd_tb.vhd:27:13:@260ns:(report note): ZD_CHECK|26|260|rom|36|36|addr=6
zd_tb.vhd:27:13:@270ns:(report note): ZD_CHECK|27|270|rom|25|25|addr=5
zd_tb.vhd:27:13:@280ns:(report note): ZD_CHECK|28|280|rom|16|16|addr=4
zd_tb.vhd:27:13:@290ns:(report note): ZD_CHECK|29|290|rom|9|9|addr=3
zd_tb.vhd:27:13:@300ns:(report note): ZD_CHECK|30|300|rom|4|4|addr=2
zd_tb.vhd:27:13:@310ns:(report note): ZD_CHECK|31|310|rom|1|1|addr=1
zd_tb.vhd:27:13:@320ns:(report note): ZD_CHECK|32|320|rom|0|0|addr=0
zd_tb.vhd:44:11:@320ns:(report note): ZD_DONE|32|2
simulation stopped @320ns
```

## 验证边界

当前结果来自 GHDL 仿真与固定参考模型，不包含形式化证明、器件综合、布局布线、时序收敛或实际板级测试。波形图展示离散检查点，完整事件波形见同目录 VCD。答题记录与仿真通过分开保存，不将参考代码通过视作学生已掌握。
