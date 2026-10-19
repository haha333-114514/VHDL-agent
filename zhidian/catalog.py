"""Original teaching circuits, immutable contracts, and independent test vectors."""

from __future__ import annotations

import random
import textwrap


def clean(source: str) -> str:
    return textwrap.dedent(source).strip() + "\n"


TASKS = {
    "counter": {
        "id": "counter", "number": "01", "title": "计数器的优先级", "category": "时序逻辑",
        "subtitle": "能计数，不代表边界正确。", "entity": "counter4", "filename": "counter4.vhd",
        "level": "入门", "concept": "reset_priority", "concept_name": "同步复位与控制优先级",
        "description": "设计一个 4 位同步计数器。上升沿到来时，复位优先于使能；未使能时保持，15 后回到 0。",
        "requirements": ["reset 高电平同步复位，优先级高于 en", "仅上升沿更新 q；en=0 时保持", "q 为 4 位无符号数，按模 16 计数"],
        "ports": "clk, reset, en : in std_logic; q : out unsigned(3 downto 0)",
        "coverage": "复位、保持、计数、15→0 回绕、reset 与 en 同时有效、非时钟沿保持",
        "starter": clean('''
            library ieee;
            use ieee.std_logic_1164.all;
            use ieee.numeric_std.all;

            entity counter4 is
              port (clk, reset, en : in std_logic;
                    q : out unsigned(3 downto 0));
            end entity;

            architecture rtl of counter4 is
              signal count : unsigned(3 downto 0) := (others => '0');
            begin
              process(clk)
              begin
                if rising_edge(clk) then
                  if en = '1' then
                    count <= count + 1;
                  elsif reset = '1' then
                    count <= (others => '0');
                  end if;
                end if;
              end process;
              q <= count;
            end architecture;
        '''),
        "solution": clean('''
            library ieee;
            use ieee.std_logic_1164.all;
            use ieee.numeric_std.all;

            entity counter4 is
              port (clk, reset, en : in std_logic;
                    q : out unsigned(3 downto 0));
            end entity;

            architecture rtl of counter4 is
              signal count : unsigned(3 downto 0) := (others => '0');
            begin
              process(clk)
              begin
                if rising_edge(clk) then
                  if reset = '1' then
                    count <= (others => '0');
                  elsif en = '1' then
                    count <= count + 1;
                  end if;
                end if;
              end process;
              q <= count;
            end architecture;
        '''),
        "hints": [
            "观察第一个失败检查点：reset 和 en 此时是否同时为 1？先根据任务约束，手算这一拍的 q。",
            "if / elsif 只执行第一个满足条件的分支。同步进程中，分支顺序表达了控制优先级。",
            "在 rising_edge(clk) 内先判断 reset，再判断 en；两者都为 0 时不赋值，让寄存器保持。参考版本可以独立仿真后再应用。"
        ],
        "diagnoses": {
            "priority": ("复位与使能冲突时，输出偏离约定", "失败发生在 reset=en=1 的上升沿。请检查控制分支的优先级；这条证据支持优先级相关的候选原因。", "if en"),
            "hold": ("保持条件下输出发生变化", "en=0 且 reset=0 时应保持。检查是否无条件计数，或把保持条件写反。", "count <="),
            "sync": ("同步复位在非上升沿改变了输出", "本题要求同步复位。检查是否在 rising_edge 外部处理 reset，或把 reset 放入异步复位分支。", "process"),
            "wrap": ("计数回绕结果不符合模 16", "4 位无符号数加 1 应从 15 回到 0。检查位宽、类型与边界判断。", "count +"),
        },
    },
    "majority": {
        "id": "majority", "number": "02", "title": "五人表决的边界", "category": "组合逻辑",
        "subtitle": "32 种输入，让条件无处遗漏。", "entity": "majority5", "filename": "majority5.vhd",
        "level": "入门", "concept": "threshold", "concept_name": "组合逻辑与阈值边界",
        "description": "五个输入表示五人的赞成票。至少三人赞成时输出 f=1，否则 f=0。输出应随输入组合变化。",
        "requirements": ["din 为 5 位投票输入，每位只测试 0 或 1", "赞成票数 ≥3 时 f=1，否则 f=0", "组合逻辑应覆盖全部路径，不引入锁存器"],
        "ports": "din : in std_logic_vector(4 downto 0); f : out std_logic",
        "coverage": "全部 32 种二值输入组合，特别覆盖恰好 2 票与恰好 3 票",
        "starter": clean('''
            library ieee;
            use ieee.std_logic_1164.all;

            entity majority5 is
              port (din : in std_logic_vector(4 downto 0); f : out std_logic);
            end entity;

            architecture rtl of majority5 is
            begin
              process(din)
                variable votes : integer range 0 to 5;
              begin
                votes := 0;
                for i in din'range loop
                  if din(i) = '1' then
                    votes := votes + 1;
                  end if;
                end loop;
                if votes >= 2 then
                  f <= '1';
                else
                  f <= '0';
                end if;
              end process;
            end architecture;
        '''),
        "solution": "",  # Defined below without duplicating the teaching circuit.
        "hints": [
            "先看失败输入中恰好有几个 1，再比较 f 的实际值和预期值。",
            "把五个输入当作五张票计数。二进制数值和 1 的个数是两件事，边界是 2 票与 3 票。",
            "在本题约束下，成立条件应为 votes >= 3。组合进程的两个分支都需要给 f 赋值。"
        ],
        "diagnoses": {
            "threshold": ("两票 / 三票交界处出现反例", "至少三票才通过。当前反例位于阈值附近；检查比较运算符、阈值与计票方式。", "if votes"),
        },
    },
    "sequence": {
        "id": "sequence", "number": "03", "title": "序列检测的重叠", "category": "状态机",
        "subtitle": "10101 里，有几次 101？", "entity": "sequence101", "filename": "sequence101.vhd",
        "level": "进阶", "concept": "overlap", "concept_name": "状态机的重叠匹配",
        "description": "在每个时钟上升沿读取一位 din。最近三位为 101 时 matched 输出一拍高电平，允许重叠匹配。",
        "requirements": ["reset 高电平同步复位", "检测 101，matched 为寄存输出的一拍脉冲", "允许重叠：输入 10101，第 3 和第 5 拍均应命中"],
        "ports": "clk, reset, din : in std_logic; matched : out std_logic",
        "coverage": "独立匹配、连续 1、重叠 10101、复位后重启、固定种子随机序列",
        "starter": clean('''
            library ieee;
            use ieee.std_logic_1164.all;

            entity sequence101 is
              port (clk, reset, din : in std_logic; matched : out std_logic);
            end entity;

            architecture rtl of sequence101 is
              signal state : integer range 0 to 2 := 0;
            begin
              process(clk)
              begin
                if rising_edge(clk) then
                  matched <= '0';
                  if reset = '1' then
                    state <= 0;
                  else
                    case state is
                      when 0 =>
                        if din = '1' then state <= 1; end if;
                      when 1 =>
                        if din = '0' then state <= 2; end if;
                      when 2 =>
                        if din = '1' then
                          matched <= '1';
                          state <= 0;
                        else
                          state <= 0;
                        end if;
                    end case;
                  end if;
                end if;
              end process;
            end architecture;
        '''),
        "solution": "",
        "hints": [
            "在纸上圈出 10101 中所有 101。两个命中是否共用了一位输入？",
            "命中 101 时，最后一个 1 同时可以成为下一次匹配的开头。下一状态应保存这个信息。",
            "在 state=2 且 din=1 的命中分支中，matched 置 1 后，应进入代表“已收到 1”的状态，而非空状态。"
        ],
        "diagnoses": {
            "overlap": ("独立序列通过，重叠匹配被遗漏", "在连续输入的重叠部分未命中。检查完成一次 101 后，是否保留了末位 1 对下一次匹配的贡献。", "matched <= '1'"),
            "reset": ("复位后的状态或输出不符合约定", "同步复位应清除状态和匹配脉冲，后续匹配应从空历史开始。", "reset ="),
        },
    },
    "fir": {
        "id": "fir", "number": "04", "title": "FIR 的历史样本", "category": "数字信号处理",
        "subtitle": "用一个冲激，看清每一拍。", "entity": "fir3", "filename": "fir3.vhd",
        "level": "进阶", "concept": "signal_history", "concept_name": "信号更新与 FIR 历史样本",
        "description": "实现三抽头整数 FIR。每个上升沿更新输出 y[n]=x[n]+2x[n−1]−x[n−2]；同步复位清零历史和输出。",
        "requirements": ["系数依次为 (1, 2, -1)", "上升沿使用当前 x 与前两拍的历史样本", "reset 高电平同步清零历史和输出；输入结束后补零观察尾部"],
        "ports": "clk, reset : in std_logic; x : in integer; y : out integer",
        "coverage": "单位冲激及尾部、负冲激、常量、混合正负、运行中复位、固定种子随机输入",
        "starter": clean('''
            library ieee;
            use ieee.std_logic_1164.all;

            entity fir3 is
              port (clk, reset : in std_logic; x : in integer; y : out integer);
            end entity;

            architecture rtl of fir3 is
              signal d1, d2 : integer := 0;
            begin
              process(clk)
              begin
                if rising_edge(clk) then
                  if reset = '1' then
                    d1 <= 0;
                    d2 <= 0;
                    y <= 0;
                  else
                    y <= x + 2*d2 - d1;
                    d2 <= d1;
                    d1 <= x;
                  end if;
                end if;
              end process;
            end architecture;
        '''),
        "solution": "",
        "hints": [
            "沿着单位冲激的检查点读输出。输入 1 后持续输入 0，应依次看到哪些系数？",
            "同一进程中的信号赋值在进程暂停后更新。因此本拍表达式中的 d1、d2 仍代表旧历史值。",
            "d1 保存前一拍输入，d2 保存前两拍输入。输出表达式应为 x + 2*d1 - d2；然后安排 d2 <= d1、d1 <= x。"
        ],
        "diagnoses": {
            "impulse": ("冲激尾部与 FIR 系数不一致", "冲激后的非零输出没有按 (1, 2, -1) 排列。检查历史样本与系数的对应关系，再检查采样时刻。", "y <= x"),
            "reset": ("复位未清除全部历史", "复位后出现了旧样本残留。检查输出寄存器与两个历史寄存器是否一起清零。", "reset ="),
        },
    },
}

TASKS["majority"]["solution"] = TASKS["majority"]["starter"].replace("votes >= 2", "votes >= 3")
TASKS["sequence"]["solution"] = TASKS["sequence"]["starter"].replace("matched <= '1';\n              state <= 0;", "matched <= '1';\n              state <= 1;")
TASKS["fir"]["solution"] = TASKS["fir"]["starter"].replace("x + 2*d2 - d1", "x + 2*d1 - d2")

from .extended_catalog import EXTENDED_TASKS, EXTENDED_QUIZZES, extended_vectors, extended_testbench
TASKS.update(EXTENDED_TASKS)


QUIZZES = {
    "counter_priority": {"task_id": "counter", "concept": "reset_priority", "question": "上升沿前 q=7，reset=1 且 en=1。本题约束下，更新后的 q 是？", "options": ["8，使能优先", "0，复位优先", "7，两个信号抵消", "无法确定"], "answer": 1, "explanation": "本题明确约定复位优先，因此进入 reset 分支，q 变为 0。优先级来自规格，不能仅凭习惯判断。"},
    "counter_sync": {"task_id": "counter", "concept": "reset_priority", "question": "变式：q=6，在两个上升沿之间将同步 reset 拉高，尚未到下一上升沿。q 应如何变化？", "options": ["立即变为 0", "立即变为 7", "保持 6，直到上升沿才处理复位", "变为未知态"], "answer": 2, "explanation": "同步复位只在有效时钟沿处理。若要立即清零，需要另一种异步复位规格。"},
    "majority_threshold": {"task_id": "majority", "concept": "threshold", "question": "din=10010，五人表决输出 f 应为？", "options": ["1，因为二进制数值大于 3", "1，因为有两个 1", "0，因为只有两票赞成", "取决于上一拍"], "answer": 2, "explanation": "10010 中有两个 1，未达到三票。组合表决比较的是 1 的数量，不是向量的数值。"},
    "majority_variant": {"task_id": "majority", "concept": "threshold", "question": "变式：改为七人严格过半表决，最少几票赞成才能通过？", "options": ["3 票", "4 票", "5 票", "7 票"], "answer": 1, "explanation": "严格过半要求票数大于 7/2，最少为 4。测试应重点覆盖 3 票与 4 票。"},
    "sequence_overlap": {"task_id": "sequence", "concept": "overlap", "question": "允许重叠时，输入序列 1010101 总共命中几次 101？", "options": ["1 次", "2 次", "3 次", "4 次"], "answer": 2, "explanation": "命中结束于第 3、5、7 位，共三次。末尾的 1 可以复用为下一段的开头。"},
    "sequence_variant": {"task_id": "sequence", "concept": "overlap", "question": "变式：检测 110，刚命中 110 后，其末尾还有能充当下一次 110 开头的非空后缀吗？", "options": ["有，保留 1", "有，保留 11", "没有，应回到空匹配状态", "直接再次命中"], "answer": 2, "explanation": "110 的非空后缀为 0、10、110，前两者都不是目标的前缀。完整命中后没有可复用的部分前缀。"},
    "fir_signal": {"task_id": "fir", "concept": "signal_history", "question": "时钟进程中先写 d1 <= x，再写 y <= x + 2*d1 - d2，y 表达式里的 d1 是？", "options": ["刚赋给它的新 x", "进程此次执行前的旧 d1", "随机的新旧值", "总是 0"], "answer": 1, "explanation": "信号赋值安排后续更新；同次进程执行中仍读取旧 d1。将语句换序不会让它像变量一样立即更新。"},
    "fir_variant": {"task_id": "fir", "concept": "signal_history", "question": "变式：系数改为 (2, -1, 3)，清零后输入 1,0,0,0，逐拍输出应为？", "options": ["1,0,0,0", "2,3,-1,0", "2,-1,3,0", "0,2,-1,3"], "answer": 2, "explanation": "按本题在上升沿前稳定输入、沿后采样输出的约定，单位冲激直接展示系数次序：2、-1、3，再归零。"},
}


QUIZZES.update(EXTENDED_QUIZZES)


def public_task(task: dict) -> dict:
    return {key: value for key, value in task.items() if key not in {"solution", "diagnoses", "hints"}}


def vectors(task_id: str, suite: str, seed: int | None = None) -> list[dict]:
    """Golden outputs use simple Python specifications, independently of candidate VHDL."""
    if task_id in EXTENDED_TASKS:
        return extended_vectors(task_id,suite,seed)
    challenge = suite == "challenge"
    if challenge:
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("盲测需要可复现的 32 位整数种子。")
        suite = "full"
    if suite not in {"smoke", "boundary", "full"}:
        raise ValueError("不支持的测试集")
    rows: list[dict] = []
    if task_id == "majority":
        inputs = [0, 1, 7, 31] if suite == "smoke" else list(range(32))
        if challenge:
            random.Random(seed).shuffle(inputs)
        for value in inputs:
            votes = value.bit_count()
            rows.append({"din": value, "expected": int(votes >= 3), "case": "threshold" if votes in (2, 3) else "combination", "input": f"din={value:05b}, votes={votes}"})
    elif task_id == "counter":
        controls = [(1, 0)] + [(0, 1)] * 3 + [(0, 0)] * 2
        if suite != "smoke":
            controls += [(1, 1), (0, 0)] + [(0, 1)] * 18 + [(1, 0), (0, 0)]
        if suite == "full":
            rng = random.Random(seed if challenge else 20261018)
            controls += [(rng.randrange(2), rng.randrange(2)) for _ in range(96 if challenge else 24)]
        q = 0
        for reset, enable in controls:
            old = q
            q = 0 if reset else ((q + 1) % 16 if enable else q)
            kind = "priority" if reset and enable else "reset" if reset else "hold" if not enable else "wrap" if old == 15 else "count"
            rows.append({"reset": reset, "en": enable, "expected": q, "case": kind, "input": f"reset={reset}, en={enable}", "pre_expected": old})
    elif task_id == "sequence":
        streams = ["101000101"] if suite == "smoke" else ["101000101", "10101", "111010101", "00000"]
        if suite == "full":
            rng = random.Random(seed if challenge else 42)
            streams.append("".join(str(rng.randrange(2)) for _ in range(128 if challenge else 40)))
        for index, stream in enumerate(streams):
            rows.append({"reset": 1, "din": 0, "expected": 0, "case": "reset", "input": "reset=1, din=0"})
            history = ""
            for bit in stream:
                history += bit
                rows.append({"reset": 0, "din": int(bit), "expected": int(history.endswith("101")), "case": "overlap" if index in (1, 2) else "stream", "input": f"din={bit}, recent={history[-7:]}"})
    elif task_id == "fir":
        streams = [[1]] if suite == "smoke" else [[1, 0, 0, 0], [-2, 0, 0, 0], [3, 3, 3, 0, 0], [1, -3, 5, -2, 0, 0]]
        if suite == "full":
            rng = random.Random(seed if challenge else 7)
            if challenge:
                streams.append([31, 0, 0, -32, 0, 0])
            streams.append([rng.randint(-32 if challenge else -12, 32 if challenge else 12) for _ in range(96 if challenge else 24)] + [0, 0])
        for group, stream in enumerate(streams):
            rows.append({"reset": 1, "x": 0, "expected": 0, "case": "reset", "input": "reset=1, x=0"})
            for n, sample in enumerate(stream):
                expected = sum((1, 2, -1)[k] * stream[n-k] for k in range(3) if n-k >= 0)
                rows.append({"reset": 0, "x": sample, "expected": expected, "case": "impulse" if group < 2 else "samples", "input": f"x={sample}, sample={n}"})
    else:
        raise ValueError("未知实验")
    return rows


def testbench(task_id: str, suite: str, seed: int | None = None) -> str:
    if task_id in EXTENDED_TASKS:
        return extended_testbench(task_id,suite,seed)
    task = TASKS[task_id]
    rows = vectors(task_id, suite, seed)
    if task_id == "majority":
        signals = "signal din : std_logic_vector(4 downto 0) := (others => '0'); signal f : std_logic;"
        ports, actual = "din => din, f => f", "bit_int(f)"
    elif task_id == "counter":
        signals = "signal clk, reset, en : std_logic := '0'; signal q : unsigned(3 downto 0);"
        ports, actual = "clk => clk, reset => reset, en => en, q => q", "to_integer(q)"
    elif task_id == "sequence":
        signals = "signal clk, reset, din : std_logic := '0'; signal matched : std_logic;"
        ports, actual = "clk => clk, reset => reset, din => din, matched => matched", "bit_int(matched)"
    else:
        signals = "signal clk, reset : std_logic := '0'; signal x : integer := 0; signal y : integer;"
        ports, actual = "clk => clk, reset => reset, x => x, y => y", "y"
    body = []
    for row_index, row in enumerate(rows):
        if task_id == "majority":
            body.append(f"din <= std_logic_vector(to_unsigned({row['din']},5)); wait for 10 ns;")
        else:
            body.append(f"clk <= '0'; reset <= '{row['reset']}';")
            if task_id == "counter":
                body.append(f"en <= '{row['en']}'; wait for 2 ns;")
                if suite != "smoke" and row_index > 0:
                    body.append(f'check_value("sync", {row["pre_expected"]}, "before rising edge");')
                body.append("wait for 3 ns;")
            elif task_id == "sequence":
                body.append(f"din <= '{row['din']}'; wait for 5 ns;")
            else:
                body.append(f"x <= {row['x']}; wait for 5 ns;")
            body.append("clk <= '1'; wait for 1 ns;")
        body.append(f'check_value("{row["case"]}", {row["expected"]}, "{row["input"]}");')
        if task_id != "majority":
            body.append("wait for 4 ns; clk <= '0';")
    return clean(f'''
        library ieee;
        use ieee.std_logic_1164.all;
        use ieee.numeric_std.all;
        use std.env.all;
        entity zd_tb is end;
        architecture test of zd_tb is
          {signals}
          function bit_int(v : std_logic) return integer is
          begin
            if v='0' then return 0; elsif v='1' then return 1; else return -999; end if;
          end;
        begin
          dut: entity work.{task['entity']} port map ({ports});
          stimulus: process
            variable total, failed : integer := 0;
            procedure check_value(kind : string; expected : integer; inputs : string) is
              variable actual : integer;
            begin
              actual := {actual};
              total := total + 1;
              report "ZD_CHECK|" & integer'image(total) & "|" & integer'image(now / 1 ns) & "|" & kind & "|" & integer'image(actual) & "|" & integer'image(expected) & "|" & inputs;
              if actual /= expected then
                failed := failed + 1;
                assert false report "ZD_MISMATCH|" & kind severity warning;
              end if;
            end;
          begin
            {chr(10).join(body)}
            report "ZD_DONE|" & integer'image(total) & "|" & integer'image(failed);
            stop;
            wait;
          end process;
        end;
    ''')
