# 行为评测与人工盲评

评测的对象是一份实际回答。每题的 `task.md` 是用户原话，`materials/` 内是自写的模拟稿件、记录或来源摘录。评审者另读 `expected.md` 和 `rubric.md`。题中的日期、页码、数值和署名只用于复算与归因。

## 从哪一题开始

| 用例 | 检查回答时看什么 |
| --- | --- |
| [01 历史时点](01-historical-law/task.md) | 修订跨期时能否按过渡条款选择受理日、条号和期限 |
| [02 摘要与全文](02-abstract-only/task.md) | 能否辨认检索平台的速读卡，给出摘要支持的综述句 |
| [03 同案两审](03-appeals/task.md) | 四份文书、三个案件与两个可核结局能否分别计数 |
| [04 引文归因](04-attribution/task.md) | 能否分清原作者、转引者、印刷页和 PDF 顺序页 |
| [05 指令内的反例](05-counterexample/task.md) | 能否用登记为零却改案的记录检验必要条件 |
| [06 撤回主张](06-withdrawal/task.md) | 能否沿主张表查到摘要，再回稿件找到未登记的图注和结语 |
| [07 频率与因果](07-causal-leap/task.md) | 能否保留样本内的比例，辨明分母和回访分派的影响 |
| [08 跨章引注](08-citation-drift/task.md) | 调换注号之后，能否再检查归因和原文支持的谓词 |
| [09 两套体例](09-style-conflict/task.md) | 本轮按组会稿要求交付，另说清送刊时的转换 |
| [10 制度建议](10-normative-leap/task.md) | 能否从记录中区分超期原因，并论证时效与防错的取舍 |
| [11 材料身份](11-material-identity/task.md) | 能否分别处理作者原稿、范文和历史稿 |
| [12 史料异读](12-interpretation/task.md) | 能否辨认传本依存、补字与眉批，区分代领和代署 |
| [13 田野段落润色](13-prose-revision/task.md) | 能否保住观察、转述、引语和注号，删去防御性句子 |
| [W1 充分材料起草](14-w1-direct-claim/task.md) | 能否直接提出证据已经支持的判断，给出可用的论证段 |
| [W2 有限材料起草](15-w2-bounded-claim/task.md) | 能否给出现有材料支持的判断，同时保留决定命题强度的条件 |

## 准备与作答

1. **确定比较。** 测量 Skill 的作用用 `design=ab`，A 不加载 Skill，B 加载待测版本。比较改动前后用 `design=regression`，A、B 分别加载旧、新版本。记下两臂各自的提交或快照标识、共同的模型、设置、工具权限，以及运行日期。公开题库适合重复验收；要检验迁移能力，另留新材料作盲测。
2. **预选题目。** 完整评测跑全部题，也可预先指定子集。版本语言验收同时选 W1、W2。每题每臂各开空白会话，给同样的用户原话和材料，固定采样设置与作答次数。模型只读本题输入及本臂指定的运行时 Skill。评审文件、答案、另一臂的回答、前一题的对话均由主持人另存。保留第一次作答；需要复测时另开一轮。
3. **封存与盲评。** 保存原始回答，为每题独立打乱左右顺序并取匿名编号。主持人另存编号与 A/B 的对应关系。评审者只收到编号答案、题面、期望要点与评分表。先锁定逐项判断和依据，再揭盲写入 JSON 的 A、B。语言验收的 `blind_review` 填写可追溯的盲评记录位置或编号。两位评审有分歧时，保留各自理由，以复核后的判定入表。

## 人工怎么打分

每行是一个可观察的标准。达到要求填 `true`，失分填 `false`；对否决项，出现所列行为填 `false`。每个失分项在 `notes` 里用同一编号注明原回答中的句子或遗漏的位置，例如 `"M2": "将平台卡片归给论文作者，见回答第二句。"`。同义表述按实质判分。

| 级别 | 对单题结果的影响 |
| --- | --- |
| critical 且 veto=yes | 任一项失分，单题记 veto。C1 编造来源或引注，C2 未取得原文却写成已核实，C3 未经授权改变核心立场，C4 删去必要限定导致过度断言。 |
| critical 且 veto=no，或 major | 任一项失分，单题记 fail。W1 将有充分证据的判断稀释为猜测属于 critical。 |
| minor | 记录具体失分。其余项通过时，单题记 pass。 |

**W1、W2 另评三项。** 每份匿名答案分别打 1–5 分并写下可定位的理由。2、4 表示介于相邻锚点。

| 字段 | 1 分 | 3 分 | 5 分 |
| --- | --- | --- | --- |
| clarity 作者判断清晰可见 | 找不到作者判断 | 能复述判断，但须从多句拼出 | 能圈出一句主体、判断动词、所断之事都清楚的主张 |
| evasion 含糊回避 | 直接作判断，限定各有依据 | 一处冗余缓冲稀释了已有判断 | 全段用让步、姿态或局限绕过可以成立的判断 |
| match 结论强度与证据匹配 | 漏掉决定范围的条件，或把可确定的事实写成猜测 | 主要判断准确，局部措辞失准 | 主张达到材料支持的强度，法域、样本或取得范围等必要条件落在相应判断处 |

## 运行与读报告

在源码仓库根目录使用 Python 3.10 或以上版本。先在题库外建一个本轮目录，例如 `review`，在其中建立 `answers/`。下例选择两道语言题；做全套时在生成模板和比较两步同时去掉两个 `--case` 参数。

```sh
python -X utf8 law-paper-writing/evaluations/run_behavioral.py check
python -X utf8 law-paper-writing/evaluations/run_behavioral.py template --case 14-w1-direct-claim --case 15-w2-bounded-claim --output review/scores.json
```

把原始回答按模板的相对路径放入 `review/answers/`。填写评分表的版本、模型、设置、评审人及各项判断。语言题每臂另填 `language` 对象中的 `clarity`、`evasion`、`match` 三个整数及 `evidence` 文字依据。比较版本时将默认的 `ab` 改为 `regression` 并填写 A、B 的真实版本。再运行：

```sh
python -X utf8 law-paper-writing/evaluations/run_behavioral.py compare --case 14-w1-direct-claim --case 15-w2-bounded-claim --scores review/scores.json --output review/report.json
python -B -m unittest discover -s law-paper-writing/evaluations -p "test_*.py" -v
```

报告给出题库与回答的指纹、评审记录、逐题得失和 A/B 通过数。`scope` 与 `case_count` 说明覆盖范围。题本、材料或 rubric 改动后，重新成对作答和评分。评分表仍有空项、失分没有依据、原始回答缺失时，补齐记录再生成报告。命令成功表示报告写成，验收结果读报告字段。

**行为回归。** 逐项比较同题同标准。A 达到而 B 失去的 critical 或 major 列入 `blocking_losses`。任一此类退步，或 B 任一题 fail/veto，本轮覆盖范围不能通过验收。minor 变化保留在各题的 `changes` 中。对外报告分子、分母、选题方式与版本。

**语言回归。** 对两题各算三项 B−A。任一题出现清晰度下降、回避上升或证据匹配下降，即判回归，其他题的进步不能抵消。两题均无反向变化、候选写作题通过，且两题合计清晰度上升、回避下降、匹配持平或提高，才能认定这次改动达到了语言目标。持平记为尚未观察到改善。改版验收按 `language_comparison.status` 读取，`improved` 表示达标，`blocked` 表示候选题失分或出现反向变化。普通 A/B、缺一题、自动测试和词频统计均不能替代改版人工盲评。
