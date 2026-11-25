#!/usr/bin/env python3
"""Read a UTF-8 Markdown or plain-text manuscript and report review findings."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import unicodedata


HEDGING_WORDS = (
    "在一定程度上", "某种意义上", "或许", "似乎", "一定程度上", "可能", "不难发现",
    "值得注意的是", "需要指出的是", "应当承认", "不可否认",
)
DISCLAIMER_WORDS = ("本文无意", "不敢妄断", "浅见", "刍议", "抛砖引玉", "笔者才疏学浅")
HEDGING_NOTICE = "以上为候选防御性修辞，需人工核对是否属于必要限定，密度不构成删除依据。"

# Levels are comparable only within a dimension. Terms on the same level are equivalent.
STRENGTH_LEVELS = {
    "证据": (
        ("不足以证明", "尚不能证明", "无法证明", "不能证明", "未能证明", "未证明", "尚待检验"),
        ("或许", "可能", "推测", "提示"),
        ("显示", "表明", "说明"),
        ("充分证明", "证实", "证明", "确证"),
    ),
    "频率": (
        ("个别", "少数", "部分"),
        ("通常", "多数", "大多", "往往"),
        ("所有", "全部", "一律", "始终", "无一例外"),
    ),
    "因果": (
        ("存在关联", "相关", "关联"),
        ("促成", "有助于"),
        ("必然导致", "直接导致", "导致", "决定了"),
    ),
}


def word_pattern(words):
    return re.compile("|".join(re.escape(word) for word in sorted(words, key=len, reverse=True)))


HEDGES = word_pattern(HEDGING_WORDS)
DISCLAIMERS = word_pattern(DISCLAIMER_WORDS)
STRENGTH_RANK = {
    word: (dimension, level)
    for dimension, levels in STRENGTH_LEVELS.items()
    for level, words in enumerate(levels)
    for word in words
}
STRENGTH_WORDS = word_pattern(STRENGTH_RANK)
PLACEHOLDER = re.compile(
    r"(?:待补(?:原文|引文|证据|页码|引注|数据|来源)|待核(?:对原文|原文|页码|引注|来源|数据)"
    r"|(?:待核|待查|待补|待确认)(?=$|[\s:：、，。；;,.?!！？〕】）)\]])"
    r"|(?<![A-Z0-9_])(?:TODO|TBD)(?![A-Z0-9_]))",
    re.IGNORECASE,
)
NOTE = re.compile(r"\[\^(?P<md>[0-9０-９]{1,6})\]|〔注\s*(?P<cn>[0-9０-９]{1,6})\s*〕")
NOTE_LABEL = re.compile(r"^\s*注\s*(?P<num>[0-9０-９]{1,6})\s*[：:]")
BIB_PREFIX = re.compile(r"^\s*(?:\[[0-9]+\]|[0-9]+[.)、]\s*|[-*+]\s+)\s*")
INLINE_LITERAL = re.compile(r"\x60+[^\x60\n]+\x60+|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|《[^》\n]*》")
SENTENCE = re.compile(r"[^。！？!?]+")
CAVEAT = re.compile(
    r"^\s*(?:虽然|尽管|固然|诚然|当然|即使|应当承认|不可否认|限于|受限于|尚待|尚需|仍需|有待"
    r"|就[^，,]{1,24}而言|在[^，,]{1,24}范围内"
    r"|(?:现有|目前|本次|本文|本研究)\s*(?:取得的|所用的)?"
    r"(?:资料|材料|文书|样本|调查|研究|观察)?\s*(?:仅|只|尚|有待))"
)
CLAIM_LINK = re.compile(
    r"[，,；;]\s*(?:但是?|然而|却|仍|可见|因此|据此|故"
    r"|(?:本文|本研究|法院|法官|材料|结果|数据)[^，,；;]{0,12}"
    r"(?:认为|认定|驳回|排除|适用|显示|表明|证明|支持|记录))"
)
FENCE = re.compile(r"^ {0,3}(\x60{3,}|~{3,})(.*)$")
MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
ORDINAL = re.compile(r"^(?:[一二三四五六七八九十百]+[、.．]\s*|第[一二三四五六七八九十百0-9]+[章节]\s+)")
SECTIONS = {
    "摘要": "abstract", "内容提要": "abstract", "中文摘要": "abstract", "abstract": "abstract",
    "引言": "intro", "绪论": "intro", "导论": "intro", "introduction": "intro",
    "正文": "body", "结论": "conclusion", "结语": "conclusion", "结论与讨论": "conclusion",
    "conclusion": "conclusion", "参考文献": "bibliography", "引用文献": "bibliography",
    "bibliography": "bibliography", "references": "bibliography",
    "注释": "notes", "脚注": "notes", "尾注": "notes", "notes": "notes",
    "关键词": "body", "关键字": "body", "致谢": "other", "附录": "other",
}
PROSE = {"abstract", "intro", "body", "conclusion"}


@dataclass(frozen=True)
class Line:
    number: int
    text: str
    section: str
    column: int = 1


@dataclass(frozen=True)
class Finding:
    line: int
    column: int
    severity: str
    kind: str
    message: str


def mask(pattern, text):
    """Remove a pattern's content without shifting source positions."""
    return pattern.sub(lambda match: " " * len(match.group()), text)


def manuscript_lines(source):
    section = "body"
    section_level = 0
    fence_marker = None
    for number, text in enumerate(source.splitlines(), 1):
        fence = FENCE.match(text)
        if fence_marker:
            if fence and fence[1][0] == fence_marker[0] and len(fence[1]) >= len(fence_marker) and not fence[2].strip():
                fence_marker = None
            yield Line(number, "", section)
            continue
        if fence:
            fence_marker = fence[1]
            yield Line(number, "", section)
            continue
        if text.lstrip().startswith(">"):
            yield Line(number, "", section)
            continue
        heading = MD_HEADING.match(text)
        label = heading[2] if heading else text.strip()
        label = ORDINAL.sub("", label)
        parts = re.split(r"([:：])", label, maxsplit=1)
        name = parts[0].strip().strip("*")
        recognized = SECTIONS.get(name.casefold())
        if recognized:
            section = recognized
            section_level = len(heading[1]) if heading else 0
            if len(parts) == 3:
                start = text.index(parts[1]) + 1
                if text[start:].startswith("**"):
                    start += 2
                yield Line(number, text[start:], section, start + 1)
            else:
                yield Line(number, "", section)
        elif heading:
            if not section_level or len(heading[1]) <= section_level:
                section = "body"
                section_level = 0
            yield Line(number, text, "other")
        elif ORDINAL.match(text.strip()) and section in {"abstract", "intro", "conclusion"}:
            section = "body"
            section_level = 0
            yield Line(number, text, "other")
        else:
            yield Line(number, text, section)


def scan_placeholders(lines):
    for line in lines:
        for match in PLACEHOLDER.finditer(mask(INLINE_LITERAL, line.text)):
            yield Finding(line.number, line.column + match.start(), "critical", "占位", match.group())


def bibliography_key(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = BIB_PREFIX.sub("", text)
    # A space between Latin words is meaningful. Spaces around CJK and punctuation can vary.
    text = re.sub(r"(?<![a-z0-9])\s+|\s+(?![a-z0-9])", "", text)
    return " ".join(text.strip("。., ").split())


def scan_bibliography(lines):
    seen = {}
    for line in lines:
        if line.section != "bibliography":
            continue
        key = bibliography_key(line.text)
        if key in seen:
            yield Finding(line.number, line.column, "major", "参考文献重复",
                          f"与第 {seen[key]} 行著录相同")
        elif key:
            seen[key] = line.number


def scan_notes(lines):
    definitions = {}
    references = {}
    expected = 1
    needs_definition = set()
    for line in lines:
        if line.section == "bibliography":
            continue
        text = mask(INLINE_LITERAL, line.text)
        label = NOTE_LABEL.match(text) if line.section == "notes" else None
        for marker in ([label] if label else NOTE.finditer(text)):
            groups = marker.groupdict()
            identifier = int(next(value for value in groups.values() if value is not None))
            column = line.column + marker.start()
            is_definition = label or (
                not text[:marker.start()].strip() and
                (line.section == "notes" or text[marker.end():].startswith(":"))
            )
            if identifier == 0:
                yield Finding(line.number, column, "critical", "注号", "注号须从正整数开始")
            elif is_definition:
                if identifier in definitions:
                    yield Finding(line.number, column, "critical", "注号",
                                  f"注 {identifier} 重复定义，首个定义在第 {definitions[identifier]} 行")
                else:
                    definitions[identifier] = line.number
            elif line.section in PROSE and identifier not in references:
                references[identifier] = (line.number, column)
                if identifier != expected:
                    yield Finding(line.number, column, "critical", "注号",
                                  f"按首次出现顺序预期注 {expected}，实际为注 {identifier}")
                expected = max(expected, identifier + 1)
            if groups.get("md") and not is_definition and line.section in PROSE:
                needs_definition.add(identifier)
    for identifier, (line, column) in references.items():
        if identifier not in definitions and (definitions or identifier in needs_definition):
            yield Finding(line, column, "critical", "注号", f"注 {identifier} 缺少定义")
    for identifier, line in definitions.items():
        if identifier not in references:
            yield Finding(line, 1, "major", "注号", f"注 {identifier} 没有正文引用")


def paragraphs(lines):
    paragraph = []
    for line in lines:
        if line.section not in PROSE or not line.text.strip():
            if paragraph:
                yield paragraph
                paragraph = []
        else:
            if paragraph and paragraph[-1].section != line.section:
                yield paragraph
                paragraph = []
            paragraph.append(line)
    if paragraph:
        yield paragraph


def prose_sentences(paragraph):
    pieces = []
    offsets = []
    offset = 0
    for line in paragraph:
        text = mask(NOTE, mask(INLINE_LITERAL, line.text))
        # A Markdown note definition can follow a paragraph without a section heading.
        if re.match(r"^\s*\[\^[0-9０-９]{1,6}\]:", line.text):
            text = " " * len(text)
        offsets.append(offset)
        pieces.append(text)
        offset += len(text) + 1

    def locate(index):
        row = bisect_right(offsets, index) - 1
        line = paragraph[row]
        return line.number, line.column + index - offsets[row]

    for match in SENTENCE.finditer("\n".join(pieces)):
        value = match.group().strip()
        if value:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            yield value, start, locate


def scan_strength(lines):
    by_section = {"abstract": [], "body": []}
    for paragraph in paragraphs(lines):
        area = paragraph[0].section
        if area not in by_section:
            continue
        for sentence, start, locate in prose_sentences(paragraph):
            kernel = STRENGTH_WORDS.sub("", sentence)
            kernel = re.sub(r"^(?:本文|本研究|研究结果|结果)[\s：:，,]*", "", kernel)
            kernel = re.sub(r"[\W_]+", "", kernel)
            if len(kernel) < 4:
                continue
            terms = defaultdict(list)
            for match in STRENGTH_WORDS.finditer(sentence):
                dimension, level = STRENGTH_RANK[match.group()]
                terms[dimension].append((match, level))
            for dimension, items in terms.items():
                ranks = {level for _, level in items}
                if len(ranks) == 1:
                    line, column = locate(start + items[0][0].start())
                    words = "、".join(dict.fromkeys(match.group() for match, _ in items))
                    by_section[area].append((kernel, dimension, ranks.pop(), words, line, column))
    body_claims = defaultdict(list)
    for kernel, dimension, rank, words, line, _ in by_section["body"]:
        body_claims[kernel, dimension].append((rank, words, line))
    for kernel, dimension, rank, words, line, column in by_section["abstract"]:
        candidates = body_claims[kernel, dimension]
        for body_rank, body_words, body_line in candidates:
            if body_rank != rank:
                yield Finding(line, column, "major", "结论强度",
                              f"{dimension}相关表述“{words}”与正文第 {body_line} 行“{body_words}”不同")
                break


def scan_hedging(lines):
    for paragraph in paragraphs(lines):
        sentence_locations = []
        for sentence, start, locate in prose_sentences(paragraph):
            words = list(HEDGES.finditer(sentence))
            for word in words:
                line, column = locate(start + word.start())
                yield Finding(line, column, "minor", "缓冲词", word.group())
            if len(words) >= 2:
                line, column = locate(start + words[0].start())
                patterns = "、".join(word.group() for word in words)
                yield Finding(line, column, "major", "单句缓冲词叠加", f"{len(words)} 处，{patterns}")
            for word in DISCLAIMERS.finditer(sentence):
                line, column = locate(start + word.start())
                yield Finding(line, column, "minor", "自谦或免责", word.group())
            sentence_locations.append((CAVEAT.match(sentence) and not CLAIM_LINK.search(sentence),
                                       locate(start)))
        if len(sentence_locations) >= 2 and all(is_caveat for is_caveat, _ in sentence_locations):
            line, column = sentence_locations[0][1]
            yield Finding(line, column, "major", "段落连续限定或让步",
                          f"{len(sentence_locations)} 句均命中限定或让步模式，复核主张句")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manuscript", type=Path, help="UTF-8 .md or .txt to read")
    parser.add_argument("--check-hedging", action="store_true", help="report hedging candidates")
    args = parser.parse_args()
    path = args.manuscript
    try:
        if path.suffix.lower() not in {".md", ".txt"}:
            raise ValueError("请提供保留稿件结构的 UTF-8 .md 或 .txt 文件")
        source = path.read_text(encoding="utf-8-sig")
        lines = list(manuscript_lines(source))
        if not any(line.text.strip() for line in lines if line.section in PROSE):
            raise ValueError("没有可扫描的正文文字")
        findings = [
            *scan_placeholders(lines), *scan_strength(lines),
            *scan_bibliography(lines), *scan_notes(lines),
        ]
        if args.check_hedging:
            findings.extend(scan_hedging(lines))
    except (OSError, ValueError) as error:
        findings = [Finding(1, 1, "critical", "无法扫描", str(error))]

    status = 2 if any(item.severity == "critical" for item in findings) else int(bool(findings))
    output = [
        f"{path.as_posix()}:{item.line}:{item.column} [{item.severity}] {item.kind} | {item.message}"
        for item in sorted(findings, key=lambda item: (item.line, item.column, item.kind))
    ]
    output.append(f"{('通过', '警告', '失败')[status]} | {len(findings)} 项")
    if args.check_hedging:
        hits = sum(item.kind == "缓冲词" for item in findings)
        output.extend((f"缓冲词命中 | {hits} 处", HEDGING_NOTICE))
    sys.stdout.buffer.write(("\n".join(output) + "\n").encode("utf-8"))
    return status


if __name__ == "__main__":
    sys.exit(main())
