# 中文人文社科论文写作 Skill

`law-paper-writing` 是一套中文学术写作 Skill。它可以从研究问题进入，也可以单独审查贡献、论证、案例可比性和脚注。法学部分重视法源效力、个案的证明范围和引注位置，文史、哲学与社会科学研究可以调用各自的方法说明。

开发版 **v0.4.8** · [下载已发布的 v0.4.2 安装包](https://github.com/tedoverlearn/law-paper-writing/releases/download/v0.4.2/law-paper-writing-v0.4.2.zip) · [查看 Skill 入口](law-paper-writing/SKILL.md)

## 安装

1. 下载并解压 ZIP，得到 `law-paper-writing` 目录。
2. 将该目录放到项目根目录的 `.agents/skills/`。如果想在本机多个项目使用，可以放到用户主目录的 `.agents/skills/`。保留 Skill 内部目录结构。
3. 在 Codex 输入 `$law-paper-writing`，说明你要处理的材料和环节。

[Codex 官方安装位置说明](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)

## 使用示例

> 用 $law-paper-writing 审查引言的研究贡献。根据附上的三篇文章，说明哪篇最接近本文、差别发生在哪个论证环节，以及现有材料支持什么表述。

> 用 $law-paper-writing 核对脚注 12 至 18。逐条核对版本、页码和正文归因，指出有待取得的原始材料。

> 用 $law-paper-writing 润色这一节。删掉只用于预防质疑的句子，保留会改变结论范围的条件、作者判断和脚注落点。

## 主要功能

- **研究设计与贡献。** 比较最接近的研究，给出可检验的增量、二级提纲和各节所需证据。
- **分析与写作。** 按法学解释、文史细读、哲学论证或社会科学方法推进。遇到反例时，定位它影响的前提或推论。
- **段落起草与重写。** 六组合成片段展示引言、文献对话、案例、教义论证、反例回应和结语的写法。每组给出原稿、逐句诊断、改写和理由。[中文写作工艺](law-paper-writing/references/writing-workshop.md)
- **民法示范。** 逐项检索请求权，核对要件事实、抗辩及证明责任。用合成买卖例检查履行顺序如何改变处理结果。[民法请求权分析](law-paper-writing/references/doctrinal-civil.md)
- **引注核验与返修。** 把关键主张对应到来源版本和原文位置。材料变化时，可用主张表查找受影响的段落。

[研究方法](law-paper-writing/references/methods.md) · [来源与引注](law-paper-writing/references/sources-and-citations.md) · [论证审查](law-paper-writing/references/argument-and-review.md) · [主张复查](law-paper-writing/references/evidence-maintenance.md)

## 稿件交付检查

全稿按硬门禁核对关键命题、引注取得范围、摘要和各章结论强度、待核项及作者授权。[交付前硬门禁](law-paper-writing/references/argument-and-review.md#交付前硬门禁)

只读脚本扫描保留标题、注号与参考文献的 UTF-8 Markdown 或纯文本。返回码 0 为通过、1 为有复读候选、2 为有阻断项或输入无法读取。加 `--check-hedging` 可定位缓冲、连续让步和自谦候选。

```sh
python -X utf8 law-paper-writing/scripts/check_manuscript.py manuscript.md --check-hedging
```

法学引注按材料类型收集字段，按实际取得的正式条文和提交要求定稿。[第二版字段表与核验状态](law-paper-writing/references/citation-profiles.md#法学引注手册第二版工作稿字段表)

如需核对工作稿和主张表，在正文使用 `〔C01〕` 这样的标记，再运行下面的只读命令。报告列出双向缺项及位置。[编号覆盖检查](law-paper-writing/references/evidence-maintenance.md#核对稿件编号覆盖)

```sh
python -B law-paper-writing/scripts/check_claim_register.py claims.tsv --check-coverage manuscript.md
```

## 检查与打包

15 道合成题可用于比较启用和停用 Skill 的原始回答。两道起草题另做版本盲评，检查判断是否清楚、写法是否回避、证据能支持多强的结论。按原文位置记录失分后，可生成 JSON 对比报告。[行为评测题库与操作步骤](law-paper-writing/evaluations/behavioral/README.md)

在仓库根目录用 Python 3.10 或更新版本运行。Word 脚注测试会生成临时 DOCX 包，无需安装 Word。

```sh
python law-paper-writing/scripts/build_release.py --check
python law-paper-writing/scripts/build_release.py --output law-paper-writing.zip
python -X utf8 law-paper-writing/evaluations/run_behavioral.py check
python -B -m unittest discover -s law-paper-writing/evaluations -p "test_*.py" -v
```

