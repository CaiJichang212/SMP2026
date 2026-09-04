#!/usr/bin/env python3
"""Convert a StarNet JSONL runtime trace into a human-readable Markdown report."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
import json
from pathlib import Path
from typing import Any


ACTION_LABELS = {
    "scan": "扫描节点",
    "comm": "沟通节点",
    "cut": "切断边",
    "shield": "隔离节点",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="输入的 JSONL 轨迹文件")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Markdown 输出文件（默认：将输入文件扩展名替换为 .md）",
    )
    return parser.parse_args(argv)


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read non-empty JSONL rows and reject malformed records with line context."""
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"无法读取轨迹文件：{exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"第 {line_number} 行不是合法 JSON：{exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"第 {line_number} 行必须是 JSON 对象")
        records.append(record)

    if not records:
        raise ValueError("轨迹文件不包含任何 JSON 事件")
    return records


def mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def display(value: object) -> str:
    """Format a scalar for a table cell without exposing Python representations."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".6g")
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping) or isinstance(value, Sequence):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def cell(value: object) -> str:
    """Make arbitrary trace data safe inside a Markdown table cell."""
    return display(value).replace("|", "\\|").replace("\n", "<br>")


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return lines


def event_name(record: Mapping[str, Any]) -> str:
    value = record.get("event")
    return value if isinstance(value, str) and value else "unknown"


def event_data(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return mapping(record.get("data"))


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_text(start: object, end: object) -> str:
    start_time = parse_timestamp(start)
    end_time = parse_timestamp(end)
    if start_time is None or end_time is None:
        return "-"
    seconds = max(0, round((end_time - start_time).total_seconds(), 3))
    if seconds < 60:
        return f"{seconds:g} 秒"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分 {remaining_seconds} 秒"
    return f"{minutes} 分 {remaining_seconds} 秒"


def numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def format_budget_change(before: object, after: object) -> str:
    before_number = numeric(before)
    after_number = numeric(after)
    if before_number is None or after_number is None:
        return f"{display(before)} -> {display(after)}"
    spent = before_number - after_number
    if abs(spent) < 1e-9:
        return display(before_number)
    return f"{display(before_number)} -> {display(after_number)} (消耗 {display(spent)})"


def format_node(node_id: object, details: Mapping[str, Any]) -> str:
    parts = [f"节点 {display(node_id)}"]
    persona = details.get("persona")
    if persona is not None:
        parts.append(display(persona))
    weight = details.get("w")
    if weight is not None:
        parts.append(f"w={display(weight)}")
    comm_left = details.get("comm_left")
    if comm_left is not None:
        parts.append(f"剩余沟通={display(comm_left)}")
    return "，".join(parts)


def format_edge(value: object) -> str:
    items = sequence(value)
    if len(items) == 2:
        return f"{display(items[0])} - {display(items[1])}"
    return display(value)


def format_action(action: Mapping[str, Any]) -> str:
    kind = action.get("kind")
    label = ACTION_LABELS.get(kind, display(kind))
    first = action.get("target_node_1")
    second = action.get("target_node_2")
    if kind == "cut":
        return f"{label} {display(first)} - {display(second)}"
    text = f"{label} {display(first)}" if first is not None else label
    prompt_id = action.get("prompt_id")
    if prompt_id is not None:
        text += f"（提示词 {display(prompt_id)}）"
    return text


def change_summary(data: Mapping[str, Any]) -> str:
    """Summarize the blackboard delta carried by an action result."""
    delta = mapping(data.get("blackboard_delta"))
    if not delta:
        rejected = data.get("rejected_reason")
        return f"拒绝原因：{display(rejected)}" if rejected else "无状态变化"

    parts: list[str] = []
    added_nodes = mapping(delta.get("added_nodes"))
    for node_id, details in added_nodes.items():
        parts.append("发现" + format_node(node_id, mapping(details)))

    added_edges = [format_edge(edge) for edge in sequence(delta.get("added_edges"))]
    if added_edges:
        parts.append("新增边 " + "、".join(added_edges))

    dead_nodes = [display(node_id) for node_id in sequence(delta.get("added_dead_nodes"))]
    if dead_nodes:
        parts.append("隔离节点 " + "、".join(dead_nodes))

    removed_nodes = mapping(delta.get("removed_nodes"))
    if removed_nodes:
        parts.append("移除节点 " + "、".join(display(node_id) for node_id in removed_nodes))

    removed_edges = [format_edge(edge) for edge in sequence(delta.get("removed_edges"))]
    if removed_edges:
        parts.append("移除边 " + "、".join(removed_edges))

    updates = mapping(delta.get("updated_nodes"))
    for node_id, update in updates.items():
        before = mapping(mapping(update).get("before"))
        after = mapping(mapping(update).get("after"))
        fields: list[str] = []
        for field, label in (("w", "w"), ("comm_left", "剩余沟通"), ("persona", "角色")):
            if before.get(field) != after.get(field):
                fields.append(f"{label} {display(before.get(field))} -> {display(after.get(field))}")
        parts.append(f"节点 {display(node_id)} 更新：" + ("，".join(fields) or "属性变化"))

    return "；".join(parts) if parts else "无状态变化"


def action_rows(records: Sequence[Mapping[str, Any]]) -> list[list[object]]:
    rows: list[list[object]] = []
    for record in records:
        event = event_name(record)
        if event not in {"action.completed", "action.failed"}:
            continue
        data = event_data(record)
        action = mapping(data.get("action"))
        success = data.get("success")
        result = "成功" if success is True else "失败" if success is False else event
        rows.append(
            [
                record.get("seq"),
                record.get("step"),
                record.get("state"),
                format_action(action),
                result,
                format_budget_change(record.get("budget_before"), record.get("budget_after")),
                change_summary(data),
            ]
        )
    return rows


def candidate_summary(candidates: object) -> str:
    items = sequence(candidates)
    if not items:
        return "无合法候选"
    rendered: list[str] = []
    for candidate in items[:5]:
        details = mapping(candidate)
        candidate_id = display(details.get("candidate_id"))
        score = details.get("score")
        rendered.append(f"{candidate_id}（分数 {display(score)}）")
    if len(items) > len(rendered):
        rendered.append(f"另有 {len(items) - len(rendered)} 个")
    return "、".join(rendered)


def analysis_rows(records: Sequence[Mapping[str, Any]]) -> list[list[object]]:
    candidates_by_step = {
        record.get("step"): event_data(record)
        for record in records
        if event_name(record) == "candidates.generated"
    }
    rows: list[list[object]] = []
    for record in records:
        if event_name(record) != "analysis.completed":
            continue
        data = event_data(record)
        candidates = candidates_by_step.get(record.get("step"), {})
        graph = (
            f"{display(data.get('node_count'))} 节点，{display(data.get('edge_count'))} 边，"
            f"{display(data.get('community_count'))} 社区"
        )
        rows.append(
            [
                record.get("step"),
                data.get("phase"),
                graph,
                candidates.get("filtered_count", 0),
                candidate_summary(candidates.get("candidates")),
            ]
        )
    return rows


def selected_candidates(data: Mapping[str, Any]) -> str:
    values = sequence(data.get("selected_candidate_ids"))
    return "、".join(display(value) for value in values) if values else "无"


def plan_rows(records: Sequence[Mapping[str, Any]]) -> list[list[object]]:
    rows: list[list[object]] = []
    for record in records:
        if event_name(record) != "plan.created":
            continue
        data = event_data(record)
        rows.append(
            [
                record.get("step"),
                data.get("source"),
                selected_candidates(data),
                data.get("fallback_reason") or "-",
            ]
        )
    return rows


def llm_rows(records: Sequence[Mapping[str, Any]]) -> list[list[object]]:
    rows: list[list[object]] = []
    for record in records:
        event = event_name(record)
        if event not in {"llm.completed", "llm.failed"}:
            continue
        data = event_data(record)
        if event == "llm.completed":
            parsed = mapping(data.get("parsed"))
            raw_output = mapping(data.get("raw_output"))
            decision = "接受" if parsed.get("accepted") is True else "拒绝"
            candidates = "、".join(display(item) for item in sequence(parsed.get("candidate_ids"))) or "无"
            detail = raw_output.get("reason") or parsed.get("fallback_reason") or "-"
            rows.append([record.get("step"), data.get("llm_calls"), decision, candidates, detail])
        else:
            rows.append(
                [
                    record.get("step"),
                    data.get("llm_calls"),
                    "未调用，使用回退",
                    "-",
                    data.get("fallback_reason") or data.get("source") or "-",
                ]
            )
    return rows


def transition_rows(records: Sequence[Mapping[str, Any]]) -> list[list[object]]:
    rows: list[list[object]] = []
    for record in records:
        if event_name(record) != "state.transition":
            continue
        data = event_data(record)
        rows.append([record.get("seq"), record.get("step"), data.get("old_state"), data.get("new_state"), data.get("reason")])
    return rows


def stable_node_items(nodes: Mapping[str, Any]) -> list[tuple[str, Any]]:
    def sort_key(item: tuple[str, Any]) -> tuple[int, object]:
        try:
            return (0, int(item[0]))
        except (TypeError, ValueError):
            return (1, item[0])

    return sorted(nodes.items(), key=sort_key)


def render_markdown(records: Sequence[Mapping[str, Any]], source_name: str) -> str:
    """Render a complete Markdown report from schema-v1 trace records."""
    first = records[0]
    started = next((record for record in records if event_name(record) == "run.started"), first)
    stopped = next((record for record in reversed(records) if event_name(record) == "run.stopped"), records[-1])
    evaluation = next((record for record in reversed(records) if event_name(record) == "evaluation.completed"), None)
    end_record = evaluation or stopped
    stop_data = event_data(stopped)
    evaluation_data = event_data(evaluation) if evaluation else {}
    event_counts = Counter(event_name(record) for record in records)
    initial_budget = started.get("budget_after", started.get("budget_before"))
    final_budget = end_record.get("budget_after", end_record.get("budget_before"))

    lines = ["# StarNet 运行轨迹报告", "", "## 运行概览", ""]
    lines.extend(
        table(
            ["项目", "值"],
            [
                ["轨迹文件", source_name],
                ["运行 ID", started.get("run_id", "-")],
                ["种子 ID", started.get("seed_id", "-")],
                ["Schema 版本", started.get("schema_version", "-")],
                ["开始时间", started.get("timestamp", "-")],
                ["结束时间", end_record.get("timestamp", "-")],
                ["运行时长", duration_text(started.get("timestamp"), end_record.get("timestamp"))],
                ["事件数", len(records)],
                ["最大步骤", max((numeric(record.get("step")) or 0 for record in records), default=0)],
                ["状态", f"{display(started.get('state'))} -> {display(end_record.get('state'))}"],
                ["预算", format_budget_change(initial_budget, final_budget)],
            ],
        )
    )

    lines.extend(["", "## 结果", ""])
    result_rows: list[list[object]] = [
        ["停止原因", stop_data.get("reason") or evaluation_data.get("stop_reason") or "-"],
        ["得分", evaluation_data.get("score", "未记录")],
        ["剩余预算", evaluation_data.get("remaining_budget", stop_data.get("remaining_budget", final_budget))],
        ["动作尝试 / 成功 / 失败", f"{display(stop_data.get('action_attempts'))} / {display(stop_data.get('action_successes'))} / {display(stop_data.get('action_failures'))}"],
        ["LLM 调用次数", stop_data.get("llm_calls", evaluation_data.get("llm_calls", "-"))],
    ]
    lines.extend(table(["项目", "值"], result_rows))

    actions = action_rows(records)
    lines.extend(["", "## 动作时间线", ""])
    if actions:
        action_counter = Counter(row[3].split(" ", 1)[0] for row in actions)
        lines.append("动作汇总：" + "，".join(f"{kind} {count} 次" for kind, count in action_counter.items()) + "。")
        lines.append("")
        lines.extend(table(["序号", "步骤", "状态", "动作", "结果", "预算变化", "环境状态变化"], actions))
    else:
        lines.append("未记录动作完成或失败事件。")

    analysis = analysis_rows(records)
    lines.extend(["", "## 分析与候选", ""])
    if analysis:
        lines.extend(table(["步骤", "阶段", "图快照", "候选数", "候选（最多显示 5 个）"], analysis))
    else:
        lines.append("未记录图分析事件。")

    plans = plan_rows(records)
    lines.extend(["", "## 计划与 LLM 决策", ""])
    if plans:
        lines.append("### 执行计划")
        lines.append("")
        lines.extend(table(["步骤", "选择来源", "选择的候选", "回退原因"], plans))
        lines.append("")
    llm = llm_rows(records)
    if llm:
        lines.append("### LLM 调用")
        lines.append("")
        lines.extend(table(["步骤", "累计调用", "结果", "候选", "原因 / 回退原因"], llm))
    if not plans and not llm:
        lines.append("未记录计划或 LLM 决策事件。")

    transitions = transition_rows(records)
    lines.extend(["", "## 状态流转", ""])
    if transitions:
        lines.extend(table(["序号", "步骤", "原状态", "新状态", "原因"], transitions))
    else:
        lines.append("未记录状态流转事件。")

    blackboard = mapping(stop_data.get("blackboard"))
    nodes = mapping(blackboard.get("nodes"))
    edges = sequence(blackboard.get("edges"))
    dead_nodes = sequence(blackboard.get("dead_nodes"))
    lines.extend(["", "## 最终网络状态", ""])
    if blackboard:
        lines.append(f"存活节点 {len(nodes)} 个，边 {len(edges)} 条。")
        if dead_nodes:
            lines.append("已隔离节点：" + "、".join(display(node_id) for node_id in dead_nodes) + "。")
        if edges:
            lines.append("剩余边：" + "、".join(format_edge(edge) for edge in edges) + "。")
        if nodes:
            lines.append("")
            node_rows = [
                [node_id, details.get("persona"), details.get("w"), details.get("comm_left")]
                for node_id, raw_details in stable_node_items(nodes)
                for details in [mapping(raw_details)]
            ]
            lines.extend(table(["节点", "角色", "权重 w", "剩余沟通次数"], node_rows))
    else:
        lines.append("停止事件未携带最终 Blackboard 快照。")

    lines.extend(["", "## 事件计数", ""])
    lines.extend(table(["事件", "次数"], [[name, count] for name, count in sorted(event_counts.items())]))
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        records = read_records(args.trace)
    except ValueError as exc:
        raise SystemExit(f"错误：{exc}") from exc

    output = args.output or args.trace.with_suffix(".md")
    report = render_markdown(records, args.trace.name)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"错误：无法写入报告 {output}：{exc}") from exc
    print(f"已生成 Markdown 报告：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
