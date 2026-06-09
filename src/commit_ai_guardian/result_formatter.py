"""审核结果格式化与终端展示模块

使用 Rich 库将 ReviewResult 列表渲染为彩色、结构化的终端输出。

输出层次：
1. 标题 Panel（青色边框）
2. 每个文件一个 Panel（绿色=通过/黄色=有建议/红色=未通过）
3. 问题表格（级别/类别/行号/描述/建议）
4. 汇总 Panel（统计数字 + 分布图）
5. 结论 Panel（通过/未通过）
"""

import os
from typing import TYPE_CHECKING, List

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.columns import Columns

if TYPE_CHECKING:
    from .ai_engine import ReviewResult, ReviewIssue
    from .config import Config


class ResultFormatter:
    """审核结果格式化器
    
    将 ReviewResult 列表渲染为终端输出。
    视觉设计：严重级别用颜色区分，类别用图标区分，文件用边框色区分状态。
    """
    
    # === 严重级别 → Rich 颜色样式 ===
    SEVERITY_STYLES = {
        "critical": "bold red",  # 严重 = 粗体红
        "error": "red",          # 错误 = 红
        "warning": "yellow",     # 警告 = 黄
        "info": "blue",          # 提示 = 蓝
    }
    
    # === 严重级别 → 中文标签 ===
    SEVERITY_LABELS = {
        "critical": "严重",
        "error": "错误",
        "warning": "警告",
        "info": "提示",
    }
    
    # === 类别 → 图标 ===
    CATEGORY_ICONS = {
        "bug": "🐛",
        "security": "🔒",
        "style": "🎨",
        "performance": "⚡",
        "best-practice": "📋",
        "documentation": "📝",
    }
    
    # === 类别 → 中文标签 ===
    CATEGORY_LABELS = {
        "bug": "Bug",
        "security": "安全",
        "style": "风格",
        "performance": "性能",
        "best-practice": "最佳实践",
        "documentation": "文档",
    }
    
    def __init__(self, config: "Config", repo_path: str = "."):
        """
        初始化格式化器
        
        Args:
            config: 配置对象
            repo_path: 代码仓库路径（用于生成可点击的文件链接）
        """
        self.config = config
        self.repo_path = os.path.abspath(repo_path)
        self.console = Console()
    
    def format_and_display(self, results: List["ReviewResult"]) -> bool:
        """
        格式化并展示完整的审核报告
        
        Args:
            results: 审核结果列表
            
        Returns:
            True 如果所有文件都通过审核
        """
        if not results:
            self.console.print(Panel(
                "[green]没有找到需要审核的代码文件[/green]",
                title="🔍 AI 代码审核报告",
                border_style="green"
            ))
            return True
        
        # 标题
        self.console.print()
        self.console.print(Panel(
            "[bold cyan]AI 驱动的代码质量审核[/bold cyan]",
            title="🔍 AI 代码审核报告",
            border_style="cyan",
            subtitle=f"共审核 {len(results)} 个文件"
        ))
        self.console.print()
        
        # 每个文件的结果
        all_passed = True
        for result in results:
            if not self._format_file_result(result):
                all_passed = False
        
        # 汇总
        self._format_summary(results)
        
        # 最终结论
        self.console.print()
        if all_passed:
            self.console.print(Panel(
                "[bold green]✅ 审核通过 - 所有文件符合代码质量标准[/bold green]",
                border_style="green"
            ))
        else:
            failed_count = sum(1 for r in results if not r.passed)
            self.console.print(Panel(
                f"[bold red]❌ 审核未通过 - {failed_count} 个文件存在问题[/bold red]\n"
                f"[dim]使用 git commit --no-verify 可跳过审核（不推荐）[/dim]",
                border_style="red"
            ))
        self.console.print()
        
        return all_passed
    
    def _format_file_result(self, result: "ReviewResult") -> bool:
        """
        格式化单个文件的审核结果
        
        Args:
            result: 单个文件的审核结果
            
        Returns:
            True 如果该文件通过审核
        """
        # 决定面板样式
        if not result.passed:
            border_style = "red"
            status_icon = "❌"
        elif result.issues:
            border_style = "yellow"
            status_icon = "🟡"
        else:
            border_style = "green"
            status_icon = "✅"
        
        # 生成绝对路径（用于 IDE 可点击链接）
        abs_path = os.path.abspath(os.path.join(self.repo_path, result.filename))
        file_link = f"file://{abs_path}"
        
        # 文件头信息（文件名做成可点击链接）
        header = Text()
        header.append(f"{status_icon} ", style="bold")
        # 文件名用单独的 Text 对象带 link（append 不支持 link 参数）
        filename_text = Text(result.filename, style="bold white underline", link=file_link)
        header.append(filename_text)
        if hasattr(result, 'summary') and result.summary:
            header.append(f"\n{result.summary}", style="dim")
        
        # 如果有问题，用列表形式展示（每个问题一行，比表格更直观）
        if result.issues:
            issue_lines = Text()
            issue_lines.append("\n")  # 空行分隔文件头和问题列表
            
            for i, issue in enumerate(result.issues, 1):
                severity_style = self.SEVERITY_STYLES.get(issue.severity, "white")
                severity_label = self.SEVERITY_LABELS.get(issue.severity, issue.severity)
                
                # 严重级别图标
                severity_icon = {"critical": "🔴", "error": "🟠", "warning": "🟡", "info": "🔵"}.get(issue.severity, "⚪")
                
                # 行号做成可点击链接
                if issue.line_number:
                    line_link = f"{file_link}:{issue.line_number}"
                    line_display = f"第 {issue.line_number} 行"
                else:
                    line_link = file_link
                    line_display = "全局"
                
                # 问题描述（主信息，加粗）
                issue_lines.append(f"\n  {severity_icon} ", style="")
                issue_lines.append(f"[{line_display}]", style=f"bold {severity_style} underline", link=line_link)
                issue_lines.append(f"  {issue.message or '-'}\n", style=f"bold {severity_style}")
                
                # 建议（缩进显示）
                if issue.suggestion:
                    issue_lines.append(f"     → {issue.suggestion}\n", style="dim green")
                
                # 代码片段（缩进显示，灰色）
                if issue.code_snippet:
                    # 截断过长的代码片段
                    snippet = issue.code_snippet.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    issue_lines.append(f"     {snippet}\n", style="dim")
            
            content = Group(header, issue_lines)
        else:
            content = header
        
        self.console.print(Panel(
            content,
            border_style=border_style,
            padding=(1, 2),
        ))
        
        return result.passed
    
    def _format_summary(self, results: List["ReviewResult"]) -> None:
        """
        展示审核汇总信息
        
        Args:
            results: 审核结果列表
        """
        total_files = len(results)
        passed_files = sum(1 for r in results if r.passed)
        failed_files = total_files - passed_files
        
        total_issues = sum(len(r.issues) for r in results)
        
        # 统计各级别问题数
        severity_counts = {"critical": 0, "error": 0, "warning": 0, "info": 0}
        category_counts = {"bug": 0, "security": 0, "style": 0, "performance": 0, "best-practice": 0, "documentation": 0}
        
        for result in results:
            for issue in result.issues:
                if issue.severity in severity_counts:
                    severity_counts[issue.severity] += 1
                if issue.category in category_counts:
                    category_counts[issue.category] += 1
        
        # 构建汇总文本
        summary_text = Text()
        summary_text.append(f"📊 审核统计\n", style="bold cyan")
        summary_text.append(f"文件总数: {total_files}  |  ")
        summary_text.append(f"通过: ", style="bold")
        summary_text.append(f"{passed_files}  ", style="green" if passed_files == total_files else "white")
        summary_text.append(f"未通过: ", style="bold")
        summary_text.append(f"{failed_files}  ", style="red" if failed_files > 0 else "white")
        summary_text.append(f"问题总数: ", style="bold")
        summary_text.append(f"{total_issues}\n", style="yellow" if total_issues > 0 else "white")
        
        # 严重级别分布
        summary_text.append(f"\n📈 问题严重级别分布\n", style="bold")
        for sev, count in severity_counts.items():
            if count > 0:
                label = self.SEVERITY_LABELS.get(sev, sev)
                style = self.SEVERITY_STYLES.get(sev, "white")
                summary_text.append(f"  {label}: ", style="bold")
                summary_text.append(f"{count}\n", style=style)
        
        # 类别分布
        if total_issues > 0:
            summary_text.append(f"\n📋 问题类别分布\n", style="bold")
            for cat, count in category_counts.items():
                if count > 0:
                    icon = self.CATEGORY_ICONS.get(cat, "📌")
                    label = self.CATEGORY_LABELS.get(cat, cat)
                    summary_text.append(f"  {icon} {label}: {count}\n")
        
        self.console.print(Panel(
            summary_text,
            title="📊 审核汇总",
            border_style="cyan",
            padding=(1, 2),
        ))
    
    def display_error(self, message: str) -> None:
        """
        显示错误信息
        
        Args:
            message: 错误信息
        """
        self.console.print(Panel(
            f"[bold red]❌ {message}[/bold red]",
            border_style="red"
        ))
    
    def display_info(self, message: str) -> None:
        """
        显示信息
        
        Args:
            message: 信息内容
        """
        self.console.print(f"[cyan]ℹ️ {message}[/cyan]")
    
    def display_success(self, message: str) -> None:
        """
        显示成功信息
        
        Args:
            message: 成功信息
        """
        self.console.print(f"[green]✅ {message}[/green]")
