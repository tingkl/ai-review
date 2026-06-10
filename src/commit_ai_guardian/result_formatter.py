"""审核结果格式化与终端展示模块

使用 Rich 库将 ReviewResult 列表渲染为彩色、结构化的终端输出。

文件名和行号采用 VS Code 终端可识别格式：
  相对路径:行号  → 如 src/auth.ts:145（diff 模式下是第一个变更行号）
  VS Code 终端会自动识别为可点击链接（cmd/ctrl+click 跳转）
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, List

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box

if TYPE_CHECKING:
    from .ai_engine import ReviewResult, ReviewIssue
    from .config import Config


class ResultFormatter:
    """审核结果格式化器 — 精致的终端输出"""

    # ── 严重级别样式 ──
    SEVERITY_STYLES = {
        "critical": "bold red",
        "error": "red",
        "warning": "yellow",
        "info": "blue",
    }
    SEVERITY_LABELS = {"critical": "严重", "error": "错误", "warning": "警告", "info": "提示"}
    SEVERITY_ICONS = {"critical": "🔴", "error": "🟠", "warning": "🟡", "info": "🔵"}
    CATEGORY_ICONS = {"bug": "🐛", "security": "🔒", "style": "🎨", "performance": "⚡", "best-practice": "📋", "documentation": "📝"}

    # 背景色（用于标签高亮）
    SEVERITY_BG = {
        "critical": "on_red",
        "error": "on_bright_red",
        "warning": "on_yellow",
        "info": "on_blue",
    }

    def __init__(self, config: "Config", repo_path: str = "."):
        self.config = config
        self.repo_path = os.path.abspath(repo_path)
        self.console = Console()

    # ═══════════════════════════════════════════════════════════════
    #  主入口
    # ═══════════════════════════════════════════════════════════════

    def format_and_display(self, results: List["ReviewResult"]) -> bool:
        """格式化并展示完整的审核报告"""
        if not results:
            self._render_empty_report()
            return True

        self._render_header(len(results))

        all_passed = True
        for result in results:
            if not self._render_file_card(result):
                all_passed = False

        self._render_summary(results)
        self._render_footer(results, all_passed)

        return all_passed

    # ═══════════════════════════════════════════════════════════════
    #  报告头部
    # ═══════════════════════════════════════════════════════════════

    def _render_header(self, file_count: int) -> None:
        """渲染报告标题 — 精致的双线标题栏"""
        header_table = Table(
            box=box.DOUBLE_EDGE,
            show_header=False,
            expand=True,
            padding=(0, 2),
            border_style="bright_cyan",
        )
        header_table.add_column(justify="center")

        title_text = Text()
        title_text.append("🔍  ", style="")
        title_text.append("AI 代码审核报告", style="bold bright_cyan")
        header_table.add_row(title_text)

        subtitle_text = Text()
        subtitle_text.append(f"共审核 {file_count} 个文件  •  ", style="dim")
        subtitle_text.append(f"模型: {getattr(self.config, 'model', 'gpt-4o-mini')}  •  ", style="dim")
        subtitle_text.append(f"阈值: {getattr(self.config, 'severity_threshold', 'warning')}", style="dim")
        header_table.add_row(subtitle_text)

        self.console.print()
        self.console.print(header_table)
        self.console.print()

    def _render_empty_report(self) -> None:
        """没有文件时的空报告"""
        self.console.print(Panel(
            "[green]没有找到需要审核的代码文件[/green]",
            title="🔍 AI 代码审核报告",
            border_style="green",
        ))

    # ═══════════════════════════════════════════════════════════════
    #  文件卡片
    # ═══════════════════════════════════════════════════════════════

    def _render_file_card(self, result: "ReviewResult") -> bool:
        """渲染单个文件的审核结果 — 卡片式布局"""

        # ── 文件状态标签 ──
        if not result.passed:
            status_text = Text(" 未通过 ", style="bold white on_red")
            border_style = "red"
        elif result.issues:
            status_text = Text(" 有警告 ", style="bold black on_yellow")
            border_style = "yellow"
        else:
            status_text = Text(" 已通过 ", style="bold white on_green")
            border_style = "green"

        # ── 文件头：状态标签 + 文件名 ──
        file_header = Text()
        file_header.append_text(status_text)
        file_header.append("  ")
        file_header.append(result.filename, style="bold white underline")

        # 缓存路径（小字、折叠到一行末尾）
        if result.cache_md5:
            cache_file = f"{result.cache_md5}.json"
            file_header.append("  ")
            file_header.append(f"💾 {cache_file}", style="dim cyan")

        # 总结语（如果有且没有具体问题时才显示）
        summary_line = None
        if result.summary and not result.issues:
            summary_line = Text(f"  {result.summary}", style="dim italic")

        # ── 问题表格 ──
        if result.issues:
            issue_table = self._build_issue_table(result)
            content = Group(file_header, Text(), issue_table)
        elif summary_line:
            content = Group(file_header, summary_line)
        else:
            content = file_header

        panel = Panel(
            content,
            box=box.ROUNDED,
            border_style=border_style,
            padding=(1, 2),
        )
        self.console.print(panel)
        self.console.print()

        return result.passed

    def _build_issue_table(self, result: "ReviewResult") -> Table:
        """构建问题详情表格 — 列对齐，精致边框"""
        table = Table(
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold bright_cyan",
            border_style="dim",
            padding=(0, 1),
            expand=True,
        )

        table.add_column("级别", min_width=6, max_width=8, justify="center")
        table.add_column("类别", min_width=4, max_width=4, justify="center")
        table.add_column("位置", min_width=25, max_width=35, no_wrap=True)
        table.add_column("问题描述", ratio=2, no_wrap=False)
        table.add_column("修复建议", ratio=2, no_wrap=False, style="green")

        for issue in result.issues:
            sev = issue.severity
            sev_label = self.SEVERITY_LABELS.get(sev, sev)
            sev_bg = self.SEVERITY_BG.get(sev, "on_white")
            cat_icon = self.CATEGORY_ICONS.get(issue.category, "📌")
            sev_style = self.SEVERITY_STYLES.get(sev, "white")

            # 级别标签：彩色背景 + 白色文字
            level_cell = Text(f" {sev_label} ", style=f"bold white {sev_bg}")

            # 类别图标
            category_cell = Text(cat_icon)

            # 位置：文件名:行号（VS Code 可点击）
            if issue.line_number:
                location = f"{result.filename}:{issue.line_number}"
            else:
                location = result.filename
            location_cell = Text(location, style=f"{sev_style} underline")

            # 问题描述
            message_cell = Text(issue.message or "-", style="bold white")

            # 修复建议
            suggestion_cell = Text(issue.suggestion or "-", style="green")

            # 代码片段（如果有，附加到问题描述后面）
            if issue.code_snippet:
                snippet = issue.code_snippet.strip()
                if len(snippet) > 60:
                    snippet = snippet[:57] + "..."
                message_cell.append("\n", style="")
                message_cell.append(f"  {snippet}", style="dim")

            table.add_row(level_cell, category_cell, location_cell, message_cell, suggestion_cell)

        return table

    # ═══════════════════════════════════════════════════════════════
    #  汇总区
    # ═══════════════════════════════════════════════════════════════

    def _render_summary(self, results: List["ReviewResult"]) -> None:
        """渲染审核汇总 — 数据统计卡片"""
        total_files = len(results)
        passed_files = sum(1 for r in results if r.passed)
        failed_files = total_files - passed_files
        total_issues = sum(len(r.issues) for r in results)

        # ── 顶部统计行 ──
        stats = Table(
            box=box.SIMPLE_HEAVY,
            show_header=False,
            expand=True,
            border_style="bright_cyan",
            padding=(1, 0),
        )
        stats.add_column(justify="center", ratio=1)
        stats.add_column(justify="center", ratio=1)
        stats.add_column(justify="center", ratio=1)
        stats.add_column(justify="center", ratio=1)

        # 文件数
        # 文件数
        f1 = Text()
        f1.append(f"{total_files}\n", style="bold bright_cyan")
        f1.append("━" * len("文件总数") + "\n", style="dim cyan")
        f1.append("文件总数", style="dim")
        # 通过
        f2 = Text()
        f2.append(f"{passed_files}\n", style="bold green")
        f2.append("━" * len("通过") + "\n", style="dim green")
        f2.append("通过", style="dim")
        # 未通过
        f3 = Text()
        f3.append(f"{failed_files}\n", style=("bold red" if failed_files > 0 else "bold white"))
        f3.append("━" * len("未通过") + "\n", style=("dim red" if failed_files > 0 else "dim"))
        f3.append("未通过", style="dim")
        # 问题数
        f4 = Text()
        f4.append(f"{total_issues}\n", style=("bold yellow" if total_issues > 0 else "bold white"))
        f4.append("━" * len("问题总数") + "\n", style=("dim yellow" if total_issues > 0 else "dim"))
        f4.append("问题总数", style="dim")

        stats.add_row(f1, f2, f3, f4)
        self.console.print(stats)
        self.console.print()

        # ── 严重级别分布 ──
        sev_counts = {"critical": 0, "error": 0, "warning": 0, "info": 0}
        for r in results:
            for i in r.issues:
                sev_counts[i.severity] = sev_counts.get(i.severity, 0) + 1

        if total_issues > 0:
            sev_table = Table(
                box=box.SIMPLE_HEAVY,
                show_header=True,
                header_style="bold",
                expand=True,
                padding=(0, 1),
            )
            sev_table.add_column("严重级别", width=12)
            sev_table.add_column("数量", width=8, justify="right")
            sev_table.add_column("可视化", ratio=1)

            max_count = max(sev_counts.values()) if any(sev_counts.values()) else 1
            for sev in ["critical", "error", "warning", "info"]:
                count = sev_counts[sev]
                if count == 0:
                    continue
                label = self.SEVERITY_LABELS[sev]
                icon = self.SEVERITY_ICONS[sev]
                style = self.SEVERITY_STYLES[sev]

                # 条形图
                bar_width = max(1, int(count / max_count * 30))
                bar = "█" * bar_width

                sev_table.add_row(
                    Text(f"{icon} {label}", style=style),
                    Text(str(count), style=f"bold {style}"),
                    Text(bar, style=style),
                )

            self.console.print(Panel(sev_table, title="📈 严重级别分布", border_style="cyan", padding=(0, 1)))
            self.console.print()

    # ═══════════════════════════════════════════════════════════════
    #  底部
    # ═══════════════════════════════════════════════════════════════

    def _render_footer(self, results: List["ReviewResult"], all_passed: bool) -> None:
        """渲染底部最终结果 — 大号通过/未通过标识"""
        if all_passed:
            footer = Table(
                box=box.DOUBLE_EDGE,
                show_header=False,
                expand=True,
                border_style="green",
                padding=(1, 0),
            )
            footer.add_column(justify="center")
            t = Text()
            t.append("✅ 审核通过\n", style="bold green")
            t.append("所有文件符合代码质量标准", style="dim green")
            footer.add_row(t)
            self.console.print(footer)
        else:
            failed = sum(1 for r in results if not r.passed)
            footer = Table(
                box=box.DOUBLE_EDGE,
                show_header=False,
                expand=True,
                border_style="red",
                padding=(1, 0),
            )
            footer.add_column(justify="center")
            t = Text()
            t.append("❌ 审核未通过\n", style="bold red")
            t.append(f"{failed} 个文件存在问题，请修复后重试", style="dim red")
            footer.add_row(t)
            self.console.print(footer)

        self.console.print()

    # ═══════════════════════════════════════════════════════════════
    #  便捷方法
    # ═══════════════════════════════════════════════════════════════

    def display_error(self, message: str) -> None:
        self.console.print(Panel(f"[bold red]❌ {message}[/bold red]", border_style="red"))

    def display_info(self, message: str) -> None:
        self.console.print(f"[cyan]ℹ️ {message}[/cyan]")

    def display_success(self, message: str) -> None:
        self.console.print(f"[green]✅ {message}[/green]")
