"""Seven bounded experiments inferred from chapter titles, not unseen slide contents."""

from __future__ import annotations

import random
from .grading import BINARY_HELPER
import textwrap


def clean(source):
    return textwrap.dedent(source).strip() + "\n"


HEADER = "library ieee;\nuse ieee.std_logic_1164.all;\nuse ieee.numeric_std.all;\n\n"


def task(number, task_id, title, category, subtitle, entity, concept, description, requirements, ports, coverage, source, old, new, hints, diagnosis, chapter, limitation):
    starter = HEADER + clean(source)
    if old not in starter:
        raise ValueError(f"Missing teaching mutation: {task_id}")
    return {"id": task_id, "number": str(number).zfill(2), "title": title, "category": category,
            "subtitle": subtitle, "entity": entity, "filename": entity + ".vhd", "level": "进阶",
            "concept": task_id, "concept_name": concept, "description": description,
            "requirements": requirements, "ports": ports, "coverage": coverage,
            "starter": starter, "solution": starter.replace(old, new, 1), "hints": hints,
            "diagnoses": diagnosis, "chapter": chapter, "basis": "依据用户截图中的章节标题推测；未读取对应 PPT 正文。",
            "verification_limit": limitation}


EXTENDED_TASKS = {}
EXTENDED_TASKS["signed_add"] = task(
    5, "signed_add", "有符号数的位宽", "数据类型", "先扩位，还是先相加？", "signed_adder", "signed 类型与加法位宽",
    "两个 8 位二进制补码数相加，用 9 位 signed 精确保留结果，不能先在 8 位中溢出再扩位。",
    ["a、b 为 signed(7 downto 0)，y 为 signed(8 downto 0)", "保留精确数学和，范围 −256 至 254", "使用 numeric_std，明确类型转换与扩位顺序"],
    "a,b : in signed(7 downto 0); y : out signed(8 downto 0)",
    "正负极值组合、跨越 8 位范围、混合正负、固定种子随机输入",
    '''
    entity signed_adder is
      port(a,b : in signed(7 downto 0); y : out signed(8 downto 0));
    end entity;
    architecture rtl of signed_adder is
    begin
      y <= resize(a + b, 9);
    end architecture;
    ''', "resize(a + b, 9)", "resize(a, 9) + resize(b, 9)",
    ["先用十进制计算 127+1，再看当前输出符号。9 位输出是否真的避免了中间溢出？", "numeric_std 的加法结果宽度受操作数宽度影响。事后 resize 无法恢复已经丢失的信息。", "把两个操作数先符号扩展到 9 位，再相加：resize(a,9)+resize(b,9)。"],
    {"overflow": ("扩位之前已经发生截断", "参考和超出了 8 位 signed 范围。检查加法在哪个位宽进行，候选原因是先相加后扩位。", "y <=")},
    "CH06 数据类型、数据对象及运算", "验证 signed 加法语义，不包含目标 FPGA 加法器的器件时序与资源测量。")

EXTENDED_TASKS["adder_tree"] = task(
    6, "adder_tree", "并行加法树的位宽", "结构生成", "四路并行，每一级都要留余量。", "adder_tree4", "generate、数组与中间结果位宽",
    "通过 generate 解包四路无符号输入，构建两层组合加法树。默认每路 4 位，结果需 6 位。",
    ["WORD_WIDTH 默认 4；din 从低位起依次为四路输入", "每个两路局部和用 WORD_WIDTH+1 位，最终和用 WORD_WIDTH+2 位", "generate 表示并行硬件展开；当前网页验证默认 WORD_WIDTH=4"],
    "generic WORD_WIDTH=4; din : std_logic_vector(4*WORD_WIDTH-1 downto 0); y : unsigned(WORD_WIDTH+1 downto 0)",
    "四路最大值、混合路序、单路激励、确定性随机向量；仅验证默认 4 位实例",
    '''
    entity adder_tree4 is
      generic(WORD_WIDTH : positive := 4);
      port(din : in std_logic_vector(4*WORD_WIDTH-1 downto 0);
           y : out unsigned(WORD_WIDTH+1 downto 0));
    end entity;
    architecture rtl of adder_tree4 is
      type lane_array is array(0 to 3) of unsigned(WORD_WIDTH-1 downto 0);
      signal lane : lane_array;
      signal left_sum, right_sum : unsigned(WORD_WIDTH downto 0);
    begin
      lanes: for i in 0 to 3 generate
        lane(i) <= unsigned(din((i+1)*WORD_WIDTH-1 downto i*WORD_WIDTH));
      end generate;
      left_sum <= resize(lane(0),WORD_WIDTH+1) + resize(lane(1),WORD_WIDTH+1);
      right_sum <= resize(lane(2),WORD_WIDTH+1) + resize(lane(3),WORD_WIDTH+1);
      y <= resize(left_sum + right_sum, WORD_WIDTH+2);
    end architecture;
    ''', "resize(left_sum + right_sum, WORD_WIDTH+2)", "resize(left_sum, WORD_WIDTH+2) + resize(right_sum, WORD_WIDTH+2)",
    ["四路都为 15 时，和是多少？先分别计算两个局部和，再看最后一级加法的位宽。", "generate 已展开四条并行连线；错误仍可能发生在树的最后一级。两个 5 位数相加可能需要 6 位。", "将两个局部和先扩展到 WORD_WIDTH+2 位，再执行最终加法。"],
    {"width": ("最后一级加法丢失进位", "失败向量的总和越过局部和的位宽。检查最终加法的操作数是否先扩位。", "y <=")},
    "CH07 复杂结构生成；CH04 设计优化", "只验证默认实例的功能；树形结构不等于已经测得更高 Fmax，未测器件资源。")

rom_values = [n*n for n in range(16)]
rom_source_values = [0 if n == 9 else value for n, value in enumerate(rom_values)]
rom_constant = ", ".join(f"{n} => to_unsigned({value},8)" for n, value in enumerate(rom_source_values))
EXTENDED_TASKS["file_rom"] = task(
    7, "file_rom", "ROM 与文件驱动验证", "文件与验证", "读入向量，写出真实观察值。", "square_rom", "textio 文件回归与 ROM 地址覆盖",
    "实现 16×8 的平方查表 ROM。受控测试平台用 textio 读取 vectors.txt，并将实际输出写入 observed.txt。",
    ["地址为 0–15，输出为地址的平方", "候选电路本身不访问文件；文件读写由固定测试平台完成", "可下载测试平台、输入向量与实际输出，核对 endfile / readline / writeline 流程"],
    "addr : in unsigned(3 downto 0); data : out unsigned(7 downto 0)",
    "全部 16 地址及倒序重读；实际生成并核对文件 I/O 结果",
    f'''
    entity square_rom is
      port(addr : in unsigned(3 downto 0); data : out unsigned(7 downto 0));
    end entity;
    architecture rtl of square_rom is
      type rom_array is array(0 to 15) of unsigned(7 downto 0);
      constant rom : rom_array := ({rom_constant});
    begin
      data <= rom(to_integer(addr));
    end architecture;
    ''', "9 => to_unsigned(0,8)", "9 => to_unsigned(81,8)",
    ["把首个失败地址与 vectors.txt 对照，确认读到的参考值是否等于地址的平方。", "检查 ROM 常量表中该地址的初始化值。输入覆盖完整时，单个表项错误也能被检出。", "地址 9 的表项应为 81。修正表项后重新运行，并核对 observed.txt 与日志。"],
    {"rom": ("ROM 表项与文件中的参考值不一致", "测试平台实际读取了地址与参考值，并采样 ROM 输出。检查失败地址的常量表项。", "constant rom")},
    "CH07 文件操作；CH08 测试验证平台设计", "textio 在受控仿真测试平台中执行，不代表 FPGA 运行时可以访问电脑文本文件。")

EXTENDED_TASKS["lut"] = task(
    8, "lut", "LUT 真值表的地址", "PLD 架构", "同一张表，位序决定逻辑。", "lut4_logic", "LUT 查表、位序与逻辑等价",
    "用 4 输入 LUT 的 16 位 INIT 表表达 f=(a0 and not a1) or (a2 and a3)。逐项核对查表与布尔表达式等价。",
    ["din(0)=a0，din(3)=a3；INIT(地址) 对应该输入组合", "默认 INIT=x\"F222\"，最低地址对应 INIT(0)", "当前验证功能模型，不宣称为某款 Lattice 原语的真实位流布局"],
    "generic INIT : bit_vector(15 downto 0)=x\"F222\"; din : std_logic_vector(3 downto 0); f : std_logic",
    "全部 16 种输入，按独立布尔表达式核对查表结果",
    '''
    entity lut4_logic is
      generic(INIT : bit_vector(15 downto 0) := x"F222");
      port(din : in std_logic_vector(3 downto 0); f : out std_logic);
    end entity;
    architecture rtl of lut4_logic is
      signal address_bits : std_logic_vector(3 downto 0);
    begin
      address_bits <= din(0) & din(1) & din(2) & din(3);
      f <= '1' when INIT(to_integer(unsigned(address_bits))) = '1' else '0';
    end architecture;
    ''', "din(0) & din(1) & din(2) & din(3)", "din",
    ["全 0 与全 1 看不出位序错误。看第一个不对称的失败输入，手工计算 LUT 地址。", "向量拼接的左侧成为高位。din(0)&din(1)&din(2)&din(3) 会翻转原地址位序。", "按本题 INIT 约定，地址位应直接使用 din。逐项核对 16 行真值表。"],
    {"lut_address": ("LUT 地址位序与真值表约定不一致", "不对称输入下，实际输出不同于独立布尔参考。检查拼接后哪个信号成为最高地址位。", "address_bits <=")},
    "SPLD 概述；FPGA 架构概述", "验证 LUT 抽象功能，不证明芯片原语映射、布局布线或配置存储的物理组织。")

EXTENDED_TASKS["ram"] = task(
    9, "ram", "RAM 的同地址读写", "存储结构", "写入这一拍，读到旧值还是新值？", "read_first_ram", "RAM 读写模式与时钟采样",
    "建立 8×8 的同步单端口 RAM 功能模型。在上升沿读取地址；若同时写入，输出该地址写入前的旧值。",
    ["本教学模型明确规定 RAM 初始值全 0", "read-first：同地址写入时，本拍 dout 为旧值，下一拍再读可见新值", "读写均在上升沿；实际器件支持何种模式需查具体手册"],
    "clk,we : in std_logic; addr : unsigned(2 downto 0); din,dout : unsigned(7 downto 0)",
    "同地址冲突、写后读、首尾地址、重复写、固定种子随机读写",
    '''
    entity read_first_ram is
      port(clk,we : in std_logic; addr : in unsigned(2 downto 0);
           din : in unsigned(7 downto 0); dout : out unsigned(7 downto 0));
    end entity;
    architecture rtl of read_first_ram is
      type ram_array is array(0 to 7) of unsigned(7 downto 0);
      signal memory : ram_array := (others => (others => '0'));
    begin
      process(clk)
      begin
        if rising_edge(clk) then
          dout <= memory(to_integer(addr));
          if we = '1' then
            memory(to_integer(addr)) <= din;
            dout <= din;
          end if;
        end if;
      end process;
    end architecture;
    ''', "        dout <= din;\n", "",
    ["看 we=1 的失败拍：参考值是旧存储内容还是本次 din？再看下一拍读取结果。", "同一进程内对同一信号多次赋值，最后执行的安排会覆盖前面的安排。检查写分支里的 dout。", "本题要求 read-first。保留 dout<=memory(addr)，写分支只更新 memory，删除额外的 dout<=din。"],
    {"read_during_write": ("同地址写入时输出了新值", "任务要求 read-first，实际候选行为接近 write-first。检查写分支是否覆盖了读出的旧值。", "dout <= din")},
    "FPGA 架构；Lattice PLD 芯片特性", "这是明确约定的行为模型，不代表已成功推断某款 FPGA 的块 RAM 或验证其碰撞规则。")

EXTENDED_TASKS["pipeline"] = task(
    10, "pipeline", "流水线的延迟对齐", "速度优化", "结果对，也要出现在正确的一拍。", "pipeline_sum", "流水寄存、延迟与吞吐",
    "用两个寄存层计算四路整数之和。上升沿 n 采样的输入，在上升沿 n+1 后出现在 y；同步复位清空两个层级。",
    ["第一级寄存 a+b、c+d，第二级寄存两项之和", "每拍都接收输入；复位后首拍输出 0，随后输出上一拍输入的和", "两级寄存表示两层流水结构；尚未测量具体器件 Fmax"],
    "clk,reset : in std_logic; a,b,c,d : in integer; y : out integer",
    "非零首拍、连续输入、负数、冲洗尾部、运行中复位、固定种子随机输入",
    '''
    entity pipeline_sum is
      port(clk,reset : in std_logic; a,b,c,d : in integer; y : out integer);
    end entity;
    architecture rtl of pipeline_sum is
      signal pair_ab, pair_cd : integer := 0;
    begin
      process(clk)
      begin
        if rising_edge(clk) then
          if reset = '1' then
            pair_ab <= 0; pair_cd <= 0; y <= 0;
          else
            pair_ab <= a+b;
            pair_cd <= c+d;
            y <= a+b+c+d;
          end if;
        end if;
      end process;
    end architecture;
    ''', "y <= a+b+c+d;", "y <= pair_ab + pair_cd;",
    ["先比较当前输入之和与上一拍输入之和。反例是数值算错，还是出现在错误的拍？", "第二级应读取第一级寄存器的旧值。直接读取当前 a,b,c,d 会绕过预期的一级延迟。", "用 y<=pair_ab+pair_cd 作为第二级。复位后首拍输出 0，第二拍才输出首拍输入之和。"],
    {"latency": ("输出数值没有按流水延迟对齐", "实际输出更接近当前输入和，参考值来自上一拍。检查是否绕过第一级寄存结果。", "y <= a+b+c+d")},
    "CH04 Speed opt；算法综合", "验证功能延迟与每拍接收的接口语义，不宣称实测频率、吞吐提升比例或时序收敛。")

EXTENDED_TASKS["serial_mul"] = task(
    11, "serial_mul", "迭代乘法与资源复用", "算法综合", "八次移位相加，何时交付结果？", "serial_multiplier", "迭代数据通路与信号旧值",
    "使用单个移位相加数据通路完成 8×8 无符号乘法。空闲时接收 start，之后第八个上升沿更新 product。",
    ["复位同步清零输出并中止在途运算", "start 只在空闲时接收；运算中的 start 与输入变化被忽略", "接收拍之后再经过 8 个上升沿输出结果，其他时刻保持上次 product"],
    "clk,reset,start : in std_logic; a,b : unsigned(7 downto 0); product : unsigned(15 downto 0)",
    "低位乘数、高位乘数、全 255、零值、在途 start、输出保持、运算中复位",
    '''
    entity serial_multiplier is
      port(clk,reset,start : in std_logic; a,b : in unsigned(7 downto 0);
           product : out unsigned(15 downto 0));
    end entity;
    architecture rtl of serial_multiplier is
      signal busy : std_logic := '0';
      signal count : integer range 0 to 7 := 0;
      signal acc, multiplicand : unsigned(15 downto 0) := (others => '0');
      signal multiplier : unsigned(7 downto 0) := (others => '0');
    begin
      process(clk)
        variable next_acc : unsigned(15 downto 0);
      begin
        if rising_edge(clk) then
          if reset = '1' then
            busy <= '0'; count <= 0; acc <= (others => '0');
            multiplicand <= (others => '0'); multiplier <= (others => '0');
            product <= (others => '0');
          elsif busy = '1' then
            next_acc := acc;
            if multiplier(0) = '1' then next_acc := acc + multiplicand; end if;
            acc <= next_acc;
            multiplicand <= shift_left(multiplicand,1);
            multiplier <= shift_right(multiplier,1);
            if count = 7 then
              product <= acc;
              busy <= '0';
            else
              count <= count + 1;
            end if;
          elsif start = '1' then
            acc <= (others => '0'); multiplicand <= resize(a,16);
            multiplier <= b; count <= 0; busy <= '1';
          end if;
        end if;
      end process;
    end architecture;
    ''', "product <= acc;", "product <= next_acc;",
    ["检查失败乘数的最高位。最后一次迭代是否还需要把移位后的被乘数累加进去？", "acc<=next_acc 并不立即更新 acc。在最后一次迭代把 acc 送到 product，会丢掉本拍的新累加值。", "结束拍将 next_acc 送到 product。保持 8 次迭代，并保留 busy 分支优先于 start 的协议。"],
    {"completion": ("最终输出缺少最后一次累加", "第八次迭代完成时输出与数学乘积不一致。结合乘数最高位检查旧信号与新变量的使用。", "product <= acc")},
    "算法综合；PLD 设计优化", "验证迭代算法及周期协议；资源复用结构可在源码中观察，但未测芯片面积、功耗或速度。")


def extended_vectors(task_id, suite, seed=None):
    challenge = suite == "challenge"
    if challenge:
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("盲测需要可复现的 32 位整数种子。")
        suite = "full"
    if suite not in {"smoke", "boundary", "full"}:
        raise ValueError("不支持的测试集")
    rows = []
    if task_id == "signed_add":
        cases = [(0, 0), (5, 7), (-2, 3)]
        if suite != "smoke":
            values = [-128, -127, -1, 0, 1, 126, 127]
            cases = [(a, b) for a in values for b in values]
        if suite == "full":
            rng = random.Random(seed if challenge else 61)
            cases += [(rng.randint(-128,127), rng.randint(-128,127)) for _ in range(96 if challenge else 24)]
        for a, b in cases:
            total = a+b
            rows.append({"a": a, "b": b, "expected": total, "case": "overflow" if total < -128 or total > 127 else "addition", "input": f"a={a}, b={b}"})
    elif task_id == "adder_tree":
        cases = [(0,0,0,0), (1,2,3,4)]
        if suite != "smoke":
            cases += [(15,15,15,15), (15,0,0,0), (0,15,0,0), (0,0,15,0), (0,0,0,15), (15,15,1,1)]
        if suite == "full":
            rng = random.Random(seed if challenge else 62)
            cases += [tuple(rng.randint(0,15) for _ in range(4)) for _ in range(96 if challenge else 40)]
        for lanes in cases:
            packed = sum(value << (4*index) for index, value in enumerate(lanes))
            rows.append({"din": packed, "expected": sum(lanes), "case": "width", "input": "lanes=" + ",".join(map(str,lanes))})
    elif task_id == "file_rom":
        addresses = [0,1,4,15] if suite == "smoke" else list(range(16)) + list(reversed(range(16)))
        if challenge:
            random.Random(seed).shuffle(addresses)
        rows = [{"addr": address, "expected": address**2, "case": "rom", "input": f"addr={address}"} for address in addresses]
    elif task_id == "lut":
        inputs = [0,15] if suite == "smoke" else list(range(16))
        if challenge:
            random.Random(seed).shuffle(inputs)
        for value in inputs:
            a0, a1, a2, a3 = [(value >> bit) & 1 for bit in range(4)]
            rows.append({"din": value, "expected": int((a0 and not a1) or (a2 and a3)), "case": "lut_address", "input": f"din={value:04b}, INIT=F222"})
    elif task_id == "ram":
        memory = [0]*8
        cases = [(0,0,0), (7,0,0)]
        if suite != "smoke":
            cases += [(3,1,17),(3,0,0),(3,1,29),(3,0,0),(7,1,255),(7,0,0),(0,1,11),(0,0,0)]
        if suite == "full":
            rng = random.Random(seed if challenge else 63)
            cases += [(rng.randrange(8),rng.randrange(2),rng.randrange(256)) for _ in range(96 if challenge else 32)]
        for address, write, data in cases:
            expected = memory[address]
            if write:
                memory[address] = data
            rows.append({"addr": address, "we": write, "din": data, "expected": expected, "case": "read_during_write" if write else "readback", "input": f"addr={address}, we={write}, din={data}"})
    elif task_id == "pipeline":
        cases = [(1,(0,0,0,0))] + [(0,(0,0,0,0))]*4
        if suite != "smoke":
            cases = [(1,(0,0,0,0)),(0,(1,2,3,4)),(0,(2,0,-2,5)),(0,(-8,4,1,2)),(0,(0,0,0,0)),(0,(0,0,0,0)),(1,(9,9,9,9)),(0,(3,3,3,3)),(0,(0,0,0,0))]
        if suite == "full":
            rng = random.Random(seed if challenge else 64)
            cases += [(int(challenge and rng.randrange(10) == 0),tuple(rng.randint(-128,127) for _ in range(4))) for _ in range(96 if challenge else 24)] + [(0,(0,0,0,0))]*2
        previous_sum = 0
        for reset, values in cases:
            expected = 0 if reset else previous_sum
            previous_sum = 0 if reset else sum(values)
            rows.append({"reset": reset, "values": values, "expected": expected, "case": "reset" if reset else "latency", "input": f"reset={reset}, abcd=" + ",".join(map(str,values))})
    elif task_id == "serial_mul":
        # Reference is an operation schedule plus Python multiplication, not shift/add RTL.
        tick, due, pending_product, product = -1, None, 0, 0
        def step(reset=0, start=0, a=0, b=0):
            nonlocal tick, due, pending_product, product
            tick += 1
            kind = "hold"
            if reset:
                due, product, kind = None, 0, "reset"
            elif due is not None:
                kind = "busy"
                if tick == due:
                    product, due, kind = pending_product, None, "completion"
            elif start:
                pending_product, due, kind = a*b, tick+8, "accept"
            rows.append({"reset": reset, "start": start, "a": a, "b": b, "expected": product, "case": kind, "input": f"reset={reset}, start={start}, a={a}, b={b}, cycle={tick}"})
        step(reset=1)
        cases = [(7,3)] if suite == "smoke" else [(3,5),(7,128),(255,255),(0,255),(128,2),(13,170)]
        if suite == "full":
            rng = random.Random(seed if challenge else 65)
            cases += [(rng.randrange(256),rng.randrange(256)) for _ in range(12 if challenge else 4)]
        for a, b in cases:
            step(start=1,a=a,b=b)
            for cycle in range(8):
                step(start=int(cycle == 2 and suite != "smoke"),a=99,b=101)
            step(); step()
        if suite != "smoke":
            step(start=1,a=255,b=255)
            for _ in range(3): step()
            step(reset=1)
            for _ in range(8): step()
            step(start=1,a=9,b=129)
            for _ in range(8): step()
            step()
    else:
        raise ValueError("未知扩展实验")
    return rows


def fixture_files(task_id, suite, seed=None):
    if task_id != "file_rom":
        return {}
    return {"vectors.txt": "".join(f"{row['addr']} {row['expected']}\n" for row in extended_vectors(task_id,suite,seed))}


def extended_testbench(task_id, suite, seed=None):
    task = EXTENDED_TASKS[task_id]
    rows = extended_vectors(task_id,suite,seed)
    setups = {
        "signed_add": ("signal a,b : signed(7 downto 0) := (others=>'0'); signal y : signed(8 downto 0);", "a=>a,b=>b,y=>y", "to_integer(y)"),
        "adder_tree": ("signal din : std_logic_vector(15 downto 0) := (others=>'0'); signal y : unsigned(5 downto 0);", "din=>din,y=>y", "to_integer(y)"),
        "file_rom": ("signal addr : unsigned(3 downto 0) := (others=>'0'); signal data : unsigned(7 downto 0);", "addr=>addr,data=>data", "to_integer(data)"),
        "lut": ("signal din : std_logic_vector(3 downto 0) := (others=>'0'); signal f : std_logic;", "din=>din,f=>f", "bit_int(f)"),
        "ram": ("signal clk,we : std_logic := '0'; signal addr : unsigned(2 downto 0) := (others=>'0'); signal din,dout : unsigned(7 downto 0);", "clk=>clk,we=>we,addr=>addr,din=>din,dout=>dout", "to_integer(dout)"),
        "pipeline": ("signal clk,reset : std_logic := '0'; signal a,b,c,d : integer := 0; signal y : integer;", "clk=>clk,reset=>reset,a=>a,b=>b,c=>c,d=>d,y=>y", "y"),
        "serial_mul": ("signal clk,reset,start : std_logic := '0'; signal a,b : unsigned(7 downto 0) := (others=>'0'); signal product : unsigned(15 downto 0);", "clk=>clk,reset=>reset,start=>start,a=>a,b=>b,product=>product", "to_integer(product)"),
    }
    signals, ports, actual = setups[task_id]
    defined = {"signed_add": "bits_defined(std_logic_vector(y))", "adder_tree": "bits_defined(std_logic_vector(y))", "file_rom": "bits_defined(std_logic_vector(data))", "lut": "f='0' or f='1'", "ram": "bits_defined(std_logic_vector(dout))", "pipeline": "true", "serial_mul": "bits_defined(std_logic_vector(product))"}[task_id]
    body = []
    declarations, imports = "", ""
    if task_id == "file_rom":
        imports = "use std.textio.all;"
        declarations = '''file vector_file : text open read_mode is "vectors.txt";
          file observed_file : text open write_mode is "observed.txt";
          variable input_line, output_line : line;
          variable address_value, expected_value : integer;'''
        body = ['''while not endfile(vector_file) loop
          readline(vector_file,input_line);
          read(input_line,address_value); read(input_line,expected_value);
          addr <= to_unsigned(address_value,4); wait for 10 ns;
          check_value("rom",expected_value,"addr=" & integer'image(address_value));
          write(output_line,address_value); write(output_line,string'(" "));
          write(output_line,to_integer(data)); write(output_line,string'(" "));
          write(output_line,expected_value); writeline(observed_file,output_line);
        end loop;
        file_close(vector_file); file_close(observed_file);''']
    else:
        clocked = task_id in {"ram","pipeline","serial_mul"}
        for row in rows:
            if clocked: body.append("clk <= '0';")
            if task_id == "signed_add":
                body.append(f"a <= to_signed({row['a']},8); b <= to_signed({row['b']},8);")
            elif task_id == "adder_tree":
                body.append(f"din <= std_logic_vector(to_unsigned({row['din']},16));")
            elif task_id == "lut":
                body.append(f"din <= std_logic_vector(to_unsigned({row['din']},4));")
            elif task_id == "ram":
                body.append(f"addr <= to_unsigned({row['addr']},3); we <= '{row['we']}'; din <= to_unsigned({row['din']},8);")
            elif task_id == "pipeline":
                body.append(f"reset <= '{row['reset']}';")
                body.extend(f"{name} <= {value};" for name, value in zip("abcd",row["values"]))
            elif task_id == "serial_mul":
                body.append(f"reset <= '{row['reset']}'; start <= '{row['start']}'; a <= to_unsigned({row['a']},8); b <= to_unsigned({row['b']},8);")
            body.append("wait for 5 ns; clk <= '1'; wait for 1 ns;" if clocked else "wait for 10 ns;")
            body.append(f'check_value("{row["case"]}",{row["expected"]},"{row["input"]}");')
            if clocked: body.append("wait for 4 ns; clk <= '0';")
    return clean(f'''{HEADER}
      use std.env.all;
      {imports}
      entity zd_tb is end;
      architecture test of zd_tb is
        {signals}
        {BINARY_HELPER}
        function bit_int(v : std_logic) return integer is
        begin
          if v='0' then return 0; elsif v='1' then return 1; else return -999; end if;
        end;
      begin
        dut: entity work.{task['entity']} port map({ports});
        stimulus: process
          variable total, failed : integer := 0;
          {declarations}
          procedure check_value(kind : string; expected : integer; inputs : string) is
            variable actual : integer;
            variable defined : boolean;
          begin
            total := total+1;
            defined := {defined};
            if defined then actual := {actual}; else
              actual := 0;
              report "ZD_INVALID|" & integer'image(total);
            end if;
            report "ZD_CHECK|" & integer'image(total) & "|" & integer'image(now/1 ns) & "|" & kind & "|" & integer'image(actual) & "|" & integer'image(expected) & "|" & inputs;
            if not defined or actual /= expected then
              failed := failed+1;
              assert false report "ZD_MISMATCH|" & kind severity warning;
            end if;
          end;
        begin
          {chr(10).join(body)}
          report "ZD_DONE|" & integer'image(total) & "|" & integer'image(failed);
          stop; wait;
        end process;
      end;
    ''')


def quiz(task_id, question, options, answer, explanation):
    return {"task_id":task_id,"concept":task_id,"question":question,"options":options,"answer":answer,"explanation":explanation}


EXTENDED_QUIZZES = {
    "signed_width": quiz("signed_add","127 与 1 在 8 位 signed 中先相加，再扩为 9 位，能否恢复精确的 128？",["能，输出有 9 位就足够","不能，8 位中已经溢出","能，只要改为 unsigned","取决于语句顺序"],1,"必须在运算前扩展操作数。已经溢出的中间结果无法靠事后扩位恢复。"),
    "signed_variant": quiz("signed_add","变式：两个任意 8 位 unsigned 数的精确和，至少需要几位？",["8 位","9 位","16 位","7 位"],1,"最大和为 255+255=510，9 位可表示 0–511。"),
    "tree_generate": quiz("adder_tree","for generate 中写出四个并行加法分支，通常表达什么？",["同一个加法器顺序算四次","在展开时形成四个并行实例","循环体每四拍执行一次","自动生成四个时钟"],1,"generate 在设计展开时形成并行结构，不提供按时钟复用运算器的调度。实际资源需综合确认。"),
    "tree_width": quiz("adder_tree","变式：四路 5 位 unsigned 输入求精确和，最终至少需要几位？",["5 位","6 位","7 位","10 位"],2,"最大和 4×31=124，需要 7 位。"),
    "rom_textio": quiz("file_rom","本实验中，textio 的文件读写实际发生在哪里？",["FPGA 配置存储器内部","电脑上的仿真测试平台","每个 LUT 自动访问磁盘","实际引脚接口中"],1,"这里的 textio 属于主机仿真测试平台，不代表综合后的 FPGA 可直接访问电脑文件。"),
    "rom_endfile": quiz("file_rom","变式：逐行读取向量文件时，应在 readline 前检查什么？",["时钟是否为低电平","文件是否已到末尾 endfile","输出是否为 0","数组方向是否升序"],1,"endfile 用于避免越过文件末尾。数据格式与读取成功还需由测试平台单独核验。"),
    "lut_address": quiz("lut","din(3 downto 0)=0001，直接作为 LUT 地址时读 INIT 的哪一位？",["INIT(8)","INIT(1)","INIT(0)","INIT(15)"],1,"本题按 unsigned(din) 解释地址，0001 对应索引 1。"),
    "lut_variant": quiz("lut","变式：用单个 K 输入 LUT 表示任意一位输出布尔函数，真值表需要几位？",["K 位","2K 位","2 的 K 次方位","K 的平方位"],2,"K 个二值输入有 2^K 种组合，每种组合保存一位结果。这里只描述抽象 LUT。"),
    "ram_readfirst": quiz("ram","某地址旧值为 17，同拍写入 29。本题 read-first 模型沿后的 dout 是？",["29","17","0","固定为未知值"],1,"本题约定先观察旧内容；写后下一拍重新读取才得到 29。具体芯片模式须另外核对。"),
    "ram_variant": quiz("ram","变式：若任务明确改为 write-first，同地址写入拍应该输出？",["旧值","本次写入的新值","上一地址的值","始终为 0"],1,"write-first 在写入拍展示新值。名称相近的器件也必须核对具体模式和接口条件。"),
    "pipeline_latency": quiz("pipeline","两层寄存的本题中，第 n 拍输入的和何时出现在 y？",["第 n 拍沿前","第 n 拍沿后","第 n+1 拍沿后","必须等待四拍"],2,"第 n 拍进入局部和寄存器，第 n+1 拍进入输出寄存器。每拍仍可接收一组新输入。"),
    "pipeline_variant": quiz("pipeline","变式：添加流水级后功能仿真通过，能否直接宣称芯片 Fmax 提高一倍？",["能，级数加倍即可","不能，还需目标器件综合和时序分析","能，只看波形周期","不能使用流水线"],1,"流水结构可能缩短组合路径，但实际时序由逻辑、寄存器、布线与器件决定。"),
    "serial_oldvalue": quiz("serial_mul","同一进程先 acc<=next_acc，再 product<=acc，product 读取哪个值？",["新 next_acc","此次进程执行前的旧 acc","两者自动求和","固定为 0"],1,"信号赋值安排后续更新。若要交付本次计算的新累加值，应使用变量 next_acc。"),
    "serial_variant": quiz("serial_mul","变式：把并行运算改成迭代复用，最需要同时约定什么？",["只要最终数值相同即可","输入接受时刻、完成延迟和在途请求处理","只要变量名相同","只要代码更短"],1,"资源复用引入时间调度，必须把周期与接口协议作为功能规格的一部分，并分别实测资源和时序。"),
}
