"""CLI 命令模块 - 提供命令行接口."""

import sys
from pathlib import Path

import click

from .config import ConfigManager
from .hook_installer import HookInstaller
from .diff_collector import DiffCollector
from .ai_engine import AIEngine
from .result_formatter import ResultFormatter


@click.group()
@click.version_option(version='0.1.0')
def main():
    """🛡️ AI 代码审核系统 - 在 Git commit 前自动审核代码"""
    pass


@main.command()
@click.option('--repo', default='.', help='目标 Git 仓库路径', type=click.Path(exists=True))
@click.option('--force', is_flag=True, help='强制覆盖已存在的 hook')
def install(repo, force):
    """在指定 Git 仓库安装 pre-commit hook"""
    try:
        installer = HookInstaller(repo)
        if installer.install(force=force):
            click.echo("✅ Hook 安装成功！在每次 git commit 时将自动触发 AI 代码审核。")
            click.echo(f"   Hook 路径: {installer.get_hook_path()}")
        else:
            click.echo("❌ Hook 安装失败。")
            sys.exit(1)
    except RuntimeError as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(1)


@main.command()
@click.option('--repo', default='.', help='目标 Git 仓库路径', type=click.Path(exists=True))
def uninstall(repo):
    """卸载 pre-commit hook"""
    try:
        installer = HookInstaller(repo)
        if installer.uninstall():
            click.echo("✅ Hook 卸载成功。")
        else:
            click.echo("⚠️ 卸载未完成，请查看上方提示。")
    except RuntimeError as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(1)


@main.command()
@click.option('--repo', default='.', help='Git 仓库路径', type=click.Path(exists=True))
@click.option('--output', type=click.Choice(['terminal', 'json']), default='terminal')
@click.option('--config', 'config_path', help='指定配置文件路径')
def audit(repo, output, config_path):
    """手动运行代码审核（被 hook 调用）"""
    try:
        # 加载配置
        config_manager = ConfigManager(config_path)
        config = config_manager.load()
        
        # 检查 API Key
        if not config.api_key:
            click.echo("❌ 未配置 API Key。请运行 'commit-ai-guardian config' 进行配置。")
            sys.exit(2)
        
        # 采集 diff
        collector = DiffCollector(repo)
        file_diffs = collector.get_staged_diffs(
            ignore_patterns=config.ignore_patterns,
            max_file_size=config.max_file_size
        )
        
        if not file_diffs:
            click.echo("📭 暂存区没有需要审核的代码变更。")
            sys.exit(0)
        
        click.echo(f"🔍 发现 {len(file_diffs)} 个文件变更，正在审核中...\n")
        
        # AI 审核
        engine = AIEngine(config)
        results = engine.review_batch(file_diffs)
        
        # 展示结果
        formatter = ResultFormatter(config)
        all_passed = formatter.format_and_display(results)
        
        # 根据严重程度阈值判断
        threshold_level = config.severity_threshold
        threshold_map = {"info": 0, "warning": 1, "error": 2, "critical": 3}
        threshold_value = threshold_map.get(threshold_level, 1)
        
        has_blocking_issue = False
        for result in results:
            for issue in result.issues:
                issue_value = threshold_map.get(issue.severity, 0)
                if issue_value >= threshold_value and issue.severity in ("error", "critical"):
                    has_blocking_issue = True
                    break
            if has_blocking_issue:
                break
        
        if not all_passed and has_blocking_issue:
            sys.exit(1)
        sys.exit(0)
        
    except RuntimeError as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        click.echo("\n⚠️ 审核已取消")
        sys.exit(130)


@main.command()
@click.option('--file', '-f', multiple=True, help='指定要审核的文件路径（可多次使用）')
@click.option('--dir', '-d', multiple=True, help='指定要审核的目录（可多次使用）')
@click.option('--pattern', '-p', multiple=True, help='Glob 模式匹配文件（如 "src/**/*.py"）')
@click.option('--recursive/--no-recursive', default=True, help='目录是否递归扫描（默认递归）')
@click.option('--max-files', default=50, help='最大审核文件数（默认 50）')
@click.option('--output', type=click.Choice(['terminal', 'json']), default='terminal')
@click.option('--config', 'config_path', help='指定配置文件路径')
def review(file, dir, pattern, recursive, max_files, output, config_path):
    """直接审核指定文件/目录的完整代码内容（不依赖 Git diff）"""
    try:
        # 加载配置
        config_manager = ConfigManager(config_path)
        config = config_manager.load()
        
        # 检查 API Key
        if not config.api_key:
            click.echo("❌ 未配置 API Key。请运行 'commit-ai-guardian configure' 进行配置。")
            sys.exit(2)
        
        # 校验至少提供一个输入源
        if not file and not dir and not pattern:
            click.echo("❌ 请至少指定一个文件/目录/模式。")
            click.echo("   示例:")
            click.echo("     commit-ai-guardian review -f src/main.py")
            click.echo("     commit-ai-guardian review -d src/ -d tests/")
            click.echo("     commit-ai-guardian review -p 'src/**/*.py'")
            click.echo("     commit-ai-guardian review -d src/ --no-recursive")
            sys.exit(2)
        
        # 导入文件采集器
        from .file_collector import FileCollector
        
        collector = FileCollector(
            ignore_patterns=config.ignore_patterns,
            max_file_size=config.max_file_size
        )
        
        # 采集文件
        source_files = collector.collect(
            files=list(file) if file else None,
            dirs=list(dir) if dir else None,
            patterns=list(pattern) if pattern else None,
            recursive=recursive
        )
        
        if not source_files:
            click.echo("📭 没有找到符合条件的代码文件。")
            sys.exit(0)
        
        # 限制最大文件数
        if len(source_files) > max_files:
            click.echo(f"⚠️ 发现 {len(source_files)} 个文件，超过最大限制 {max_files}，只审核前 {max_files} 个。")
            source_files = source_files[:max_files]
        
        click.echo(f"🔍 发现 {len(source_files)} 个代码文件，正在审核中...\n")
        
        # AI 审核
        engine = AIEngine(config)
        results = engine.review_source_batch(source_files)
        
        # 展示结果
        formatter = ResultFormatter(config)
        all_passed = formatter.format_and_display(results)
        
        # 非阻塞模式（review 命令不阻断任何东西，exit 0 即可）
        sys.exit(0)
        
    except RuntimeError as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        click.echo("\n⚠️ 审核已取消")
        sys.exit(130)


@main.command()
@click.option('--config', 'config_path', help='指定配置文件路径')
def configure(config_path):
    """交互式配置管理"""
    config_manager = ConfigManager(config_path)
    config = config_manager.load()
    
    click.echo("🛠️ AI 代码审核系统 - 配置管理\n")
    click.echo(f"当前配置文件: {config_manager.get_default_config_path()}\n")
    
    # API Key
    if config.api_key:
        masked_key = config.api_key[:8] + "..." + config.api_key[-4:]
        click.echo(f"当前 API Key: {masked_key}")
    new_key = click.prompt("请输入 API Key", default=config.api_key, show_default=False, hide_input=True)
    if new_key:
        config.api_key = new_key
    
    # API Base
    config.api_base = click.prompt("请输入 API Base URL", default=config.api_base)
    
    # Model
    config.model = click.prompt("请输入模型名称", default=config.model)
    
    # Language
    config.language = click.prompt("请输入审核语言 (zh-CN/en)", default=config.language)
    
    # Severity Threshold
    config.severity_threshold = click.prompt(
        "请输入阻止提交的最低严重级别 (info/warning/error/critical)",
        default=config.severity_threshold,
        type=click.Choice(["info", "warning", "error", "critical"], case_sensitive=False)
    )
    
    # Max File Size
    config.max_file_size = click.prompt("请输入最大审核文件大小 (KB)", default=config.max_file_size, type=int)
    
    # Timeout
    config.timeout = click.prompt("请输入 API 超时时间 (秒)", default=config.timeout, type=int)
    
    # Proxy
    proxy = click.prompt("请输入代理地址 (留空表示不使用)", default=config.proxy or "", show_default=False)
    config.proxy = proxy if proxy else None
    
    # Save
    config_manager.save(config)
    click.echo(f"\n✅ 配置已保存到: {config_manager.get_default_config_path()}")


@main.command()
def status():
    """查看当前配置和安装状态"""
    try:
        config_manager = ConfigManager()
        config = config_manager.load()
        
        installer = HookInstaller('.')
        
        click.echo("📊 系统状态\n")
        click.echo(f"配置文件: {config_manager.get_default_config_path()}")
        click.echo(f"  - API Key: {'已配置 ✅' if config.api_key else '未配置 ❌'}")
        click.echo(f"  - API Base: {config.api_base}")
        click.echo(f"  - Model: {config.model}")
        click.echo(f"  - Language: {config.language}")
        click.echo(f"  - Severity Threshold: {config.severity_threshold}")
        click.echo(f"  - Max File Size: {config.max_file_size} KB")
        click.echo(f"  - Timeout: {config.timeout} 秒")
        click.echo(f"  - Proxy: {config.proxy or '未配置'}")
        
        click.echo()
        if installer.is_git_repo():
            if installer.is_hook_installed():
                click.echo(f"Git Hook: ✅ 已安装 ({installer.get_hook_path()})")
            else:
                click.echo(f"Git Hook: ❌ 未安装 (运行 'commit-ai-guardian install' 安装)")
        else:
            click.echo("Git Hook: ⚠️ 当前目录不是 Git 仓库")
            
    except Exception as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
