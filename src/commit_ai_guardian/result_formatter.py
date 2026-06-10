"""审核结果格式化与终端展示模块

使用 Rich 库将 ReviewResult 列表渲染为彩色、结构化的终端输出。

文件名和行号采用 VS Code 终端可识别格式：
  相对路径:行号  → 如 src/auth.ts:145（diff 模式下是第一个变更行号）
  VS Code 终端会自动识别为可点击链接（cmd/ctrl+click 跳转）
"""

import os
from typing import TYPE_CHECKING, List

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

if TYPE_CHECKING:
    from .ai_engine import ReviewResult, ReviewIssue
    from .config import Config


class ResultFormatter:
    """审核结果格式化器"""
    
    SEVERITY_STYLES = {
        "critical": "bold red",
        "error": "red",
        "warning": "yellow",
        "info": "blue",
    }
    
    SEVERITY_LABELS = {"critical": "严重", "error": "错误", "warning": "警告", "info": "提示"}
    CATEGORY_ICONS = {"bug": "🐛", "security": "🔒", "style": "🎨", "performance": "⚡", "best-practice": "📋", "documentation": "📝"}
    SEVERITY_ICONS = {"critical": "🔴", "error": "🟠", "warning": "🟡", "info": "🔵"}
    
    def __init__(self, config: "Config", repo_path: str = "."):
        self.config = config
        self.repo_path = os.path.abspath(repo_path)
        self.console = Console()
    
    def format_and_display(self, results: List["ReviewResult"]) -> bool:
        """格式化并展示完整的审核报告"""
        if not results:
            self.console.print(Panel(
                "[green]没有找到需要审核的代码文件[/green]",
                title="🔍 AI 代码审核报告",
                border_style="green"
            ))
            return True
        
        self.console.print()
        self.console.print(Panel(
            "[bold cyan]AI 驱动的代码质量审核[/bold cyan]",
            title="🔍 AI 代码审核报告",
            border_style="cyan",
            subtitle=f"共审核 {len(results)} 个文件"
        ))
        self.console.print()
        
        all_passed = True
        for result in results:
            if not self._format_file_result(result):
                all_passed = False
        
        self._format_summary(results)
        
        self.console.print()
        if all_passed:
            self.console.print(Panel("[bold green]✅ 审核通过 - 所有文件符合代码质量标准[/bold green]", border_style="green"))
        else:
            failed = sum(1 for r in results if not r.passed)
            self.console.print(Panel(
                f"[bold red]❌ 审核未通过 - {failed} 个文件存在问题[/bold red]\n"
                f"[dim]使用 git commit --no-verify 可跳过审核（不推荐）[/dim]",
                border_style="red"
            ))
        self.console.print()
        
        return all_passed
    
    def _format_file_result(self, result: "ReviewResult") -> bool:
        """格式化单个文件的审核结果"""
        if not result.passed:
            border_style, status_icon = "red", "❌"
        elif result.issues:
            border_style, status_icon = "yellow", "🟡"
        else:
            border_style, status_icon = "green", "✅"
        
        # === 文件头：文件名用 VS Code 可识别格式（文件名:行号）===
        # VS Code 终端自动识别 "path/to/file.ts:145" 为可点击链接
        # 有 issue 时用第一个 issue 的实际行号，否则用 first_line_number 或 1
        header = Text()
        header.append(f"{status_icon} ", style="bold")
        if result.issues and result.issues[0].line_number:
            line_num = result.issues[0].line_number
        else:
            line_num = result.first_line_number or 1
        # 文件名:行号 [MD5: abc123...]
        md5_str = f" [{result.cache_key[:8]}...]" if result.cache_key else ""
        header.append(f"{result.filename}:{line_num}{md5_str}", style="bold white underline")
        if result.summary:
            header.append(f"\n{result.summary}", style="dim")
        
        # === 问题列表 ===
        if result.issues:
            issue_lines = Text()
            issue_lines.append("\n")
            
            for issue in result.issues:
                sev_style = self.SEVERITY_STYLES.get(issue.severity, "white")
                sev_label = self.SEVERITY_LABELS.get(issue.severity, issue.severity)
                sev_icon = self.SEVERITY_ICONS.get(issue.severity, "⚪")
                cat_icon = self.CATEGORY_ICONS.get(issue.category, "📌")
                
                # 行号用 "文件名:行号" 格式，VS Code 可点击跳转
                if issue.line_number:
                    location = f"{result.filename}:{issue.line_number}"
                else:
                    location = result.filename
                
                # === 分隔线（每个问题之间用虚线分隔，更清晰）===
                issue_lines.append(f"\n  {'─' * 50}\n", style="dim")
                
                # === 第1行: 严重级别标签 + 类别 + 位置 ===
                # 严重级别用背景色高亮（如 red background），非常醒目
                bg_colors = {
                    "critical": "on_red",
                    "error": "on_bright_red",
                    "warning": "on_yellow",
                    "info": "on_blue",
                }
                bg = bg_colors.get(issue.severity, "on_white")
                issue_lines.append(f"  {sev_icon} ", style="")
                issue_lines.append(f"[{sev_label}]", style=f"bold white {bg}")
                issue_lines.append(f"  {cat_icon} ", style="")
                issue_lines.append(location, style=f"bold {sev_style} underline")
                issue_lines.append("\n")
                
                # === 第2行: 问题描述（message）—— 最醒目的部分 ===
                # 用 >> 符号 + 加粗 + 颜色，让问题原因一目了然
                issue_lines.append(f"     >> ", style=f"bold {sev_style}")
                issue_lines.append(f"{issue.message or '-'}\n", style=f"bold white")
                
                # === 第3行: 修复建议 ===
                if issue.suggestion:
                    issue_lines.append(f"     💡 ", style="bold green")
                    issue_lines.append(f"{issue.suggestion}\n", style="green")
                
                # === 第4行: 代码片段 ===
                if issue.code_snippet:
                    snippet = issue.code_snippet.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    issue_lines.append(f"     📍 ", style="dim")
                    issue_lines.append(f"{snippet}\n", style="dim")
            
            content = Group(header, issue_lines)
        else:
            content = header
        
        self.console.print(Panel(content, border_style=border_style, padding=(1, 2)))
        return result.passed
    
    def _format_summary(self, results: List["ReviewResult"]) -> None:
        """展示审核汇总"""
        total_files = len(results)
        passed_files = sum(1 for r in results if r.passed)
        failed_files = total_files - passed_files
        total_issues = sum(len(r.issues) for r in results)
        
        sev_counts = {"critical": 0, "error": 0, "warning": 0, "info": 0}
        cat_counts = {"bug": 0, "security": 0, "style": 0, "performance": 0, "best-practice": 0, "documentation": 0}
        for r in results:
            for i in r.issues:
                sev_counts[i.severity] = sev_counts.get(i.severity, 0) + 1
                cat_counts[i.category] = cat_counts.get(i.category, 0) + 1
        
        summary = Text()
        summary.append("📊 审核统计\n", style="bold cyan")
        summary.append(f"文件总数: {total_files}  |  ")
        summary.append(f"通过: ", style="bold")
        summary.append(f"{passed_files}  ", style="green" if passed_files == total_files else "white")
        summary.append(f"未通过: ", style="bold")
        summary.append(f"{failed_files}  ", style="red" if failed_files > 0 else "white")
        summary.append(f"问题总数: ", style="bold")
        summary.append(f"{total_issues}\n", style="yellow" if total_issues > 0 else "white")
        
        summary.append(f"\n📈 问题严重级别分布\n", style="bold")
        for sev, count in sev_counts.items():
            if count > 0:
                summary.append(f"  {self.SEVERITY_LABELS.get(sev, sev)}: ", style="bold")
                summary.append(f"{count}\n", style=self.SEVERITY_STYLES.get(sev, "white"))
        
        if total_issues > 0:
            summary.append(f"\n📋 问题类别分布\n", style="bold")
            for cat, count in cat_counts.items():
                if count > 0:
                    summary.append(f"  {self.CATEGORY_ICONS.get(cat, '📌')} {cat}: {count}\n")
        
        self.console.print(Panel(summary, title="📊 审核汇总", border_style="cyan", padding=(1, 2)))
    
    def display_error(self, message: str) -> None:
        self.console.print(Panel(f"[bold red]❌ {message}[/bold red]", border_style="red"))
    
    def display_info(self, message: str) -> None:
        self.console.print(f"[cyan]ℹ️ {message}[/cyan]")
    
    def display_success(self, message: str) -> None:
        self.console.print(f"[green]✅ {message}[/green]")
