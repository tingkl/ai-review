"""CLI 命令模块 - 所有用户命令的入口，相当于"总指挥" """

# sys: 用于获取命令行参数、控制退出码
# Path: 用于处理文件路径（比字符串拼接更可靠）
# click: Python 的命令行框架，用装饰器定义命令和选项

import re
import sys
from pathlib import Path

import click
from rich.console import Console

from .config import ConfigManager
from .hook_installer import HookInstaller
from .diff_collector import DiffCollector
from .ai_engine import AIEngine, parse_ai_response
from .result_formatter import ResultFormatter

# Rich 控制台实例（用于 loading 动画和彩色输出）
console = Console()


def _find_repo_path(start_path: str = ".") -> str:
    """从指定路径向上查找 Git 仓库根目录
    
    用于 review 命令：即使用户审核的是单个文件/目录，
    也能找到所在的 Git 仓库，加载 .ai-review/cases/ 项目级别案例。
    
    Args:
        start_path: 起始路径（文件或目录）
        
    Returns:
        Git 仓库根目录路径，找不到则返回 start_path
    """
    current = Path(start_path).resolve()
    
    # 如果 start_path 是文件，从父目录开始
    if current.is_file():
        current = current.parent
    
    # 逐级向上查找 .git/ 目录
    while current != current.parent:  # 到达根目录时停止
        if (current / ".git").is_dir():
            return str(current)
        current = current.parent
    
    # 找不到 Git 仓库，返回原路径
    return start_path


@click.group()
@click.version_option(version='0.1.0')
def main():
    """🛡️ AI 代码审核系统 - 在 Git commit 前自动审核代码"""
    pass


@main.command()
@click.option('--repo', default='.', help='目标 Git 仓库路径', type=click.Path(exists=True))
@click.option('--force', is_flag=True, help='强制覆盖已存在的 hook')
def install(repo, force):
    """在指定 Git 仓库安装 pre-commit hook，同时初始化 .ai-review/ 案例目录"""
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
def upgrade():
    """升级 commit-ai-guardian 到最新版本 (uv tool upgrade)"""
    import subprocess
    
    click.echo("🔄 正在升级 commit-ai-guardian...")
    
    try:
        result = subprocess.run(
            ["uv", "tool", "upgrade", "commit-ai-guardian"],
            capture_output=True, text=True, check=True
        )
        click.echo("✅ 升级成功!")
    except subprocess.CalledProcessError as e:
        click.echo("❌ 升级失败:")
        click.echo(e.stderr)
        sys.exit(1)


@main.command()
@click.option('--repo', default='.', help='Git 仓库路径', type=click.Path(exists=True))
@click.option('--output', type=click.Choice(['terminal', 'json']), default='terminal')
@click.option('--config', 'config_path', help='指定配置文件路径')
def audit(repo, output, config_path):
    """手动运行代码审核（被 hook 调用）"""
    try:
        # Step 1: 加载配置（优先加载项目级别 .ai-review/config.yaml，覆盖全局配置）
        config_manager = ConfigManager(config_path, repo_path=repo)
        config = config_manager.load()
        
        # 检查 enabled 配置（false=禁用审核，直接跳过）
        if not config.enabled:
            click.echo("[信息] AI 审核已禁用（enabled=false），跳过审核")
            sys.exit(0)  # 正常退出，不阻断
        
        # 检查 API Key 是否已配置（没有这个就无法调用 AI）
        if not config.api_key:
            click.echo("❌ 未配置 API Key")
            click.echo("   配置方式（二选一）:")
            click.echo("   1. 项目级别: 编辑 .ai-review/config.yaml，设置 api_key: \"your-key\"")
            click.echo("   2. 全局级别: 运行 'commit-ai-guardian configure' 交互式配置")
            sys.exit(2)
        
        # Step 2: 采集 diff（从 Git 暂存区获取变更内容）
        collector = DiffCollector(repo)
        
        # 合并忽略模式：默认 .ai-review/ 目录 + 用户配置
        all_ignore_patterns = [".ai-review/*"] + config.ignore_patterns
        
        file_diffs = collector.get_staged_diffs(
            include_patterns=config.include_patterns,  # 只审核白名单内的文件/目录
            ignore_patterns=all_ignore_patterns,       # 过滤掉 .ai-review/ + 配置中的模式
            max_file_size=config.max_file_size         # 过滤掉超过 500KB 的文件
        )
        
        if not file_diffs:
            click.echo("📭 暂存区没有需要审核的代码变更。")
            sys.exit(0)
        
        # 有文件变更，打印配置信息
        config_manager.log_config(config, "合并后")
        
        click.echo(f"🔍 发现 {len(file_diffs)} 个文件变更\n")
        
        # Step 3: AI 审核（逐个文件调用 AI API，获取审核结果）
        # 用 Rich 的 status 显示旋转 loading 动画，让用户知道正在进行
        engine = AIEngine(config, repo_path=repo)
        with console.status("[bold cyan]AI 正在审核代码，请稍候..."):
            results = engine.review_batch(file_diffs)
        
        # Step 4: 终端展示（用 Rich 库美化输出审核报告）
        formatter = ResultFormatter(config, repo_path=repo)
        all_passed = formatter.format_and_display(results)
        
        # Step 5: 判断是否阻断 commit
        # 只有 severity >= error 的问题才会阻断（默认 threshold 是 warning，但 error 才阻断）
        threshold_level = config.severity_threshold
        threshold_map = {"info": 0, "warning": 1, "error": 2, "critical": 3}
        threshold_value = threshold_map.get(threshold_level, 1)
        
        # 判断是否阻断 commit
        # 逻辑1：只要有一个 issue 的严重级别 >= threshold 就阻断
        # 逻辑2（兜底）：result.passed=False 时也阻断（JSON解析失败/API异常等）
        # severity_threshold=warning 时：warning/error/critical 都阻断
        # severity_threshold=error 时：error/critical 阻断
        has_blocking_issue = False
        has_system_error = False
        for result in results:
            # 检查1：AI 审核未通过（passed=False）→ 阻断
            # 这包括 JSON 解析失败、API 异常、字段缺失等所有非成功场景
            if not result.passed:
                has_system_error = True
                # 打印具体原因（帮助用户定位问题）
                if not result.issues:
                    click.echo(f"  ⚠️  {result.filename}: {result.summary}")
                break
            # 检查2：有 issue 且 severity >= threshold → 阻断
            for issue in result.issues:
                issue_value = threshold_map.get(issue.severity, 0)
                if issue_value >= threshold_value:
                    has_blocking_issue = True
                    break
            if has_blocking_issue:
                break
        
        # exit(0) = 放行，exit(1) = 阻断 commit
        if has_system_error:
            click.echo("\n❌ 审核过程中出现系统异常，已阻断提交")
            click.echo("   请查看上方日志定位问题，或运行 'cag debug-log .ai-review/logs/xxx.ai.log' 调试")
            sys.exit(1)
        if has_blocking_issue:
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
        # Step 1: 加载配置（尝试从被审核文件所在的 Git 仓库加载项目配置）
        search_path = file[0] if file else (dir[0] if dir else ".")
        repo_path = _find_repo_path(search_path)
        config_manager = ConfigManager(config_path, repo_path=repo_path)
        config = config_manager.load()
        
        # 检查 enabled 配置（false=禁用审核，直接跳过）
        if not config.enabled:
            click.echo("[信息] AI 审核已禁用（enabled=false），跳过审核")
            sys.exit(0)  # 正常退出，不阻断
        
        # 检查 API Key
        if not config.api_key:
            click.echo("❌ 未配置 API Key")
            click.echo("   配置方式（二选一）:")
            click.echo("   1. 项目级别: 编辑 .ai-review/config.yaml，设置 api_key: \"your-key\"")
            click.echo("   2. 全局级别: 运行 'commit-ai-guardian configure' 交互式配置")
            sys.exit(2)
        
        # Step 2: 校验输入（至少提供一个文件/目录/模式）
        if not file and not dir and not pattern:
            click.echo("❌ 请至少指定一个文件/目录/模式。")
            click.echo("   示例:")
            click.echo("     commit-ai-guardian review -f src/main.py")
            click.echo("     commit-ai-guardian review -d src/ -d tests/")
            click.echo("     commit-ai-guardian review -p 'src/**/*.py'")
            click.echo("     commit-ai-guardian review -d src/ --no-recursive")
            sys.exit(2)
        
        # Step 3: 采集文件（从文件系统读取，不经过 Git）
        from .file_collector import FileCollector
        
        # 合并忽略模式：默认 .ai-review/ 目录 + 用户配置
        all_ignore_patterns = [".ai-review/*"] + config.ignore_patterns
        
        collector = FileCollector(
            include_patterns=config.include_patterns,  # 只审核白名单内的文件/目录
            ignore_patterns=all_ignore_patterns,       # 过滤 .ai-review/ + 配置
            max_file_size=config.max_file_size         # 大小限制
        )
        
        # collect() 支持三种来源同时采集，自动去重
        source_files = collector.collect(
            files=list(file) if file else None,         # 单文件列表
            dirs=list(dir) if dir else None,            # 目录列表
            patterns=list(pattern) if pattern else None, # glob 模式列表
            recursive=recursive                          # 是否递归子目录
        )
        
        if not source_files:
            click.echo("📭 没有找到符合条件的代码文件。")
            sys.exit(0)
        
        # 限制最大文件数（防止一次提交太多文件导致 API 超时）
        if len(source_files) > max_files:
            click.echo(f"⚠️ 发现 {len(source_files)} 个文件，超过最大限制 {max_files}，只审核前 {max_files} 个。")
            source_files = source_files[:max_files]
        
        click.echo(f"🔍 发现 {len(source_files)} 个代码文件\n")
        
        # Step 4: AI 审核（调用完整文件审核模式，不是 diff 模式）
        # 用 Rich 的 status 显示旋转 loading 动画
        search_path = file[0] if file else (dir[0] if dir else ".")
        repo_path = _find_repo_path(search_path)
        
        engine = AIEngine(config, repo_path=repo_path)
        with console.status("[bold cyan]AI 正在审核代码，请稍候..."):
            results = engine.review_source_batch(source_files)
        
        # Step 5: 终端展示
        # 传入 repo_path 让文件名/行号变成可点击的 IDE 链接
        formatter = ResultFormatter(config, repo_path=repo_path)
        all_passed = formatter.format_and_display(results)
        
        # review 命令永远不阻断（不像 audit 会 exit(1) 阻断 commit）
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
    click.echo(f"当前配置文件: {config_manager.get_global_path()}\n")
    
    # API Key
    if config.api_key:
        masked_key = config.api_key[:8] + "..." + config.api_key[-4:]
        click.echo(f"当前 API Key: {masked_key}")
    new_key = click.prompt("请输入 API Key", default=config.api_key, show_default=False, hide_input=True)
    if new_key:
        config.api_key = new_key
    
    # API Base
    click.echo("")
    click.echo("  主流模型 API Base URL 参考：")
    click.echo("  +-----------------+-----------------------------------------------+")
    click.echo("  | 服务商          | API Base URL                                  |")
    click.echo("  +-----------------+-----------------------------------------------+")
    click.echo("  | OpenAI          | https://api.openai.com/v1                     |")
    click.echo("  | MiniMax(国际)   | https://api.minimax.io/v1                     |")
    click.echo("  | MiniMax(国内)   | https://api.minimaxi.com/v1                   |")
    click.echo("  | DeepSeek        | https://api.deepseek.com/v1                   |")
    click.echo("  | Moonshot(Kimi)  | https://api.moonshot.cn/v1                    |")
    click.echo("  +-----------------+-----------------------------------------------+")
    click.echo("")
    config.api_base = click.prompt("  API Base URL", default=config.api_base)
    
    # 根据 api_base 推荐模型
    api_base_lower = config.api_base.lower()
    click.echo("")
    if "minimax" in api_base_lower:
        click.echo("  MiniMax 推荐模型：")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | 模型名称            | 说明                                      |")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | MiniMax-M3          | 最新编程模型，1M 上下文，最强代码能力      |")
        click.echo("  | MiniMax-M2.7        | 递归自改进，200K 上下文，通用场景首选      |")
        click.echo("  | MiniMax-M2.5        | 性价比之选，200K 上下文                    |")
        click.echo("  | MiniMax-M2.1        | 编程专项，适合代码审查场景                 |")
        click.echo("  +---------------------+-------------------------------------------+")
    elif "deepseek" in api_base_lower:
        click.echo("  DeepSeek 推荐模型：")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | 模型名称            | 说明                                      |")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | deepseek-v4-pro     | 最新版本，推荐                             |")
        click.echo("  | deepseek-v3         | 通用场景，性价比高                         |")
        click.echo("  | deepseek-reasoner   | 推理模型，适合复杂逻辑审查                 |")
        click.echo("  | deepseek-chat       | 基础对话模型                               |")
        click.echo("  +---------------------+-------------------------------------------+")
    elif "moonshot" in api_base_lower:
        click.echo("  Moonshot(Kimi) 推荐模型：")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | 模型名称            | 说明                                      |")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | kimi-k2             | 最新版本，超长上下文 200K                  |")
        click.echo("  | kimi-k2.5           | 平衡性能与速度                             |")
        click.echo("  | kimi-k2-thinking    | 推理模型，适合复杂代码分析                 |")
        click.echo("  +---------------------+-------------------------------------------+")
    elif "openai" in api_base_lower:
        click.echo("  OpenAI 推荐模型：")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | 模型名称            | 说明                                      |")
        click.echo("  +---------------------+-------------------------------------------+")
        click.echo("  | gpt-4o              | 最强模型，适合复杂审查                     |")
        click.echo("  | gpt-4o-mini         | 性价比之选，速度快                         |")
        click.echo("  | gpt-3.5-turbo       | 基础模型，成本低                           |")
        click.echo("  +---------------------+-------------------------------------------+")
    else:
        click.echo("  模型名称示例：gpt-4o, MiniMax-M2.7, deepseek-v4-pro, kimi-k2")
    click.echo("")
    
    # Model
    config.model = click.prompt("  模型名称", default=config.model)
    
    # Language
    config.language = click.prompt("请输入审核报告语言 (zh-CN/en)", default=config.language)
    
    # Severity Threshold
    config.severity_threshold = click.prompt(
        "请输入阻止提交的最低严重级别 (info/warning/error/critical)",
        default=config.severity_threshold,
        type=click.Choice(["info", "warning", "error", "critical"], case_sensitive=False)
    )
    
    # Diff Mode
    config.diff_mode = click.prompt(
        "请输入 diff 审核模式 (full=完整文件, diff=只审变更)",
        default=config.diff_mode,
        type=click.Choice(["full", "diff"], case_sensitive=False)
    )
    
    # Max File Size
    config.max_file_size = click.prompt("请输入最大审核文件大小 (KB)", default=config.max_file_size, type=int)
    
    # Timeout
    config.timeout = click.prompt("请输入 API 超时时间 (秒)", default=config.timeout, type=int)
    
    # Max Tokens（支持简写：8K=8192, 16k=16384, 128k=131072）
    click.echo("")
    click.echo("  主流模型 max_tokens 参考：")
    click.echo("  +-----------------+------------+--------+--------+")
    click.echo("  | 模型            | 默认       | 最大   | 建议值 |")
    click.echo("  +-----------------+------------+--------+--------+")
    click.echo("  | MiniMax M3/M2.x | 很小(截断) | 128K   | 16K    |")
    click.echo("  | DeepSeek        | 4,096      | 8K     | 8K     |")
    click.echo("  | Kimi K2.x       | 32K        | 128K   | 16K    |")
    click.echo("  | GPT-4o          | ~4K        | 16K    | 8K     |")
    click.echo("  +-----------------+------------+--------+--------+")
    click.echo("  支持简写: 8K=8192, 16k=16384, 128k=131072")
    click.echo("")
    max_tokens_input = click.prompt("  AI 最大返回长度", default=str(config.max_tokens), type=str)
    try:
        config.max_tokens = int(max_tokens_input)
    except ValueError:
        from .config import _parse_token_size
        config.max_tokens = _parse_token_size(max_tokens_input)
    
    # Temperature
    click.echo("")
    click.echo("  Temperature 说明：")
    click.echo("    0.0 = 最保守，输出最确定、最一致")
    click.echo("    0.3 = 平衡，适合代码审核（默认）")
    click.echo("    0.7 = 更灵活，可能发现更多问题")
    click.echo("    1.0+ = 最随机，不推荐用于审核")
    click.echo("")
    config.temperature = click.prompt("  Temperature", default=config.temperature, type=float)
    
    # Proxy
    proxy = click.prompt("请输入代理地址 (留空表示不使用)", default=config.proxy or "", show_default=False)
    config.proxy = proxy if proxy else None
    
    # Save
    config_manager.save(config)
    click.echo(f"\n✅ 配置已保存到: {config_manager.get_global_path()}")


@main.command()
@click.option('--repo', default='.', help='目标代码仓库路径', type=click.Path(exists=True))
def status(repo):
    """查看当前配置和安装状态"""
    try:
        # 加载两级配置（显示合并后的最终值）
        config_manager = ConfigManager(repo_path=repo)
        config = config_manager.load()
        
        installer = HookInstaller(repo)
        
        click.echo("📊 系统状态\n")
        
        # 显示两级配置路径
        click.echo(f"全局配置: {config_manager.get_global_path()}")
        project_path = config_manager.get_project_path()
        if project_path:
            if Path(project_path).exists():
                click.echo(f"项目配置: {project_path} ✅")
            else:
                click.echo(f"项目配置: {project_path} ❌ 不存在")
                click.echo(f"          (创建 .ai-review/config.yaml 可覆盖全局配置)")
        
        click.echo()
        click.echo(f"  - API Key: {'已配置 ✅' if config.api_key else '未配置 ❌'}")
        click.echo(f"  - API Base: {config.api_base}")
        click.echo(f"  - Model: {config.model}")
        click.echo(f"  - Language: {config.language}")
        click.echo(f"  - Severity Threshold: {config.severity_threshold}")
        click.echo(f"  - Diff Mode: {config.diff_mode} (full=完整文件, diff=只审变更)")
        click.echo(f"  - Max File Size: {config.max_file_size} KB")
        click.echo(f"  - Cache TTL: {config.cache_ttl}")
        click.echo(f"  - Log TTL: {config.log_ttl}")
        click.echo(f"  - Timeout: {config.timeout} 秒")
        click.echo(f"  - Max Tokens: {config.max_tokens}")
        click.echo(f"  - Temperature: {config.temperature} (0=保守, 0.3=平衡, 0.7=灵活)")
        click.echo(f"  - Proxy: {config.proxy or '未配置'}")
        
        click.echo()
        if installer.is_git_repo():
            if installer.is_hook_installed():
                click.echo(f"Git Hook: ✅ 已安装 ({installer.get_hook_path()})")
            else:
                click.echo(f"Git Hook: ❌ 未安装 (运行 'commit-ai-guardian install' 安装)")
            
            # 检查 .ai-review/ 目录
            review_dir = Path(repo) / ".ai-review"
            if review_dir.exists():
                cases_dir = review_dir / "cases"
                case_files = list(cases_dir.glob("*.md")) if cases_dir.exists() else []
                click.echo(f"案例目录: ✅ {cases_dir} ({len(case_files)} 个案例)")
        else:
            click.echo("Git Hook: ⚠️ 当前目录不是 Git 仓库")
            
    except Exception as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(1)


@main.command('validate-cases')
@click.option('--repo', default='.', help='目标代码仓库路径', type=click.Path(exists=True))
def validate_cases(repo):
    """校验 .ai-review/cases/ 下的案例文件格式是否正确"""
    from .case_validator import validate_all_cases, print_summary
    
    cases_dir = Path(repo) / ".ai-review" / "cases"
    results = validate_all_cases(cases_dir)
    
    if results:
        all_passed = print_summary(results)
        if not all_passed:
            sys.exit(1)
    else:
        sys.exit(1)


@main.command('debug-log')
@click.argument('log_file', type=click.Path(exists=True))
@click.option('--filename', '-f', default=None, help='模拟的文件名（仅 ai.log 有效，默认从 header 提取）')
@click.option('--repo', default='.', help='项目路径（用于加载配置）')
def debug_log(log_file, filename, repo):
    """调试日志 - 传入 ai.log 或 json_fix.log，自动识别并解析（不调用 AI）

    根据文件名后缀自动判断日志类型：
    - xxx.ai.log → 调试主审核 AI 响应（格式化展示审核结果）
    - xxx.json_fix.log → 调试 JSON 修复 AI 响应（逐次验证提取/解析/schema）

    用法:
        cag debug-log .ai-review/logs/xxx.ai.log
        cag debug-log .ai-review/logs/xxx.json_fix.log
    """
    log_path = Path(log_file)
    if not log_path.exists():
        click.echo(f"❌ 文件不存在: {os.path.relpath(log_path) if log_path.is_absolute() else log_file}")
        sys.exit(1)

    log_name = log_path.name

    # === 模式 A: json_fix.log ===
    if log_name.endswith('.json_fix.log'):
        _debug_json_fix_log(log_path)
        return

    # === 模式 B: ai.log ===
    if log_name.endswith('.ai.log'):
        _debug_ai_log(log_path, filename, repo)
        return

    # 不支持的类型
    click.echo(f"❌ 不支持的日志类型: {log_name}")
    click.echo("   请传入 .ai.log（主审核日志）或 .json_fix.log（JSON 修复日志）")
    sys.exit(1)


def _debug_ai_log(log_path, filename, repo):
    """调试主审核 AI 响应日志（内部函数）"""
    try:
        log_content = log_path.read_text(encoding='utf-8')
        click.echo(f"📄 日志文件: {os.path.relpath(log_path)}")
        click.echo(f"📄 文件大小: {len(log_content)} 字符\n")

        # 从 ai.log header 中提取文件名（如未指定 --filename）
        if filename is None:
            file_match = re.search(r'# 文件: (.+)', log_content)
            filename = file_match.group(1).strip() if file_match else 'unknown'

        # 从 ai.log 中提取 --- AI RESPONSE --- 后面的内容
        ai_response_match = re.search(
            r'--- AI RESPONSE ---\n={40,}\n\n(.*)',
            log_content, re.DOTALL
        )
        if ai_response_match:
            raw_response = ai_response_match.group(1).strip()
            click.echo(f"📄 AI 响应长度: {len(raw_response)} 字符\n")
        elif '<result>' in log_content:
            raw_response = log_content
            click.echo("📄 使用兼容模式（旧格式 ai.log）\n")
        else:
            raw_response = log_content

        # 使用与线上完全一致的解析逻辑
        result = parse_ai_response(raw_response, filename)

        # 用 ResultFormatter 渲染（与 audit/review 命令的展示完全一致）
        config_manager = ConfigManager(repo_path=repo)
        config = config_manager.load()
        formatter = ResultFormatter(config, repo_path=repo)
        formatter.format_and_display([result])

        # 打印原始响应摘要（方便调试）
        click.echo(f"\n[调试] passed={result.passed}, issues={len(result.issues)}, summary={result.summary}")

    except Exception as e:
        click.echo(f"❌ 错误: {e}")
        sys.exit(2)


def _debug_json_fix_log(log_path):
    """调试 JSON 修复 AI 响应日志（内部函数）"""
    import json
    click.echo(f"📄 读取: {os.path.relpath(log_path)}\n")
    content = log_path.read_text(encoding='utf-8')

    # 分割出每次尝试
    attempts = re.split(r'--- 尝试 (\d+) ---', content)

    found_pass = False
    for i in range(1, len(attempts), 2):
        attempt_num = attempts[i]
        attempt_content = attempts[i + 1] if i + 1 < len(attempts) else ""

        click.echo(f"{'='*60}")
        click.echo(f"尝试 {attempt_num}")
        click.echo(f"{'='*60}")

        # 步骤 1: 过滤 <think>
        filtered = re.sub(r'<think>.*?</think>', '', attempt_content, flags=re.DOTALL).strip()
        has_think = '<think>' in attempt_content
        click.echo(f"1. <think> 标签: {'有 (已过滤)' if has_think else '无'}")

        # 步骤 2: 提取 JSON
        # 策略 0: <result>
        m = re.search(r'<result>(.*?)</result>', filtered, re.DOTALL)
        if m:
            extracted = m.group(1).strip()
            click.echo(f"2. 提取: <result> 标签匹配 ({len(extracted)} 字符)")
        else:
            # 策略 1: ```json
            m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', filtered, re.DOTALL)
            if m:
                extracted = m.group(1).strip()
                click.echo(f"2. 提取: ```json 代码块匹配 ({len(extracted)} 字符)")
            else:
                # 策略 2: 第一个 {...}
                m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', filtered, re.DOTALL)
                if m:
                    extracted = m.group(0).strip()
                    click.echo(f"2. 提取: fallback 正则匹配 ({len(extracted)} 字符)")
                else:
                    click.echo("❌ 2. 提取失败: 未找到 JSON")
                    continue

        # 步骤 3: 解析 JSON
        try:
            parsed = json.loads(extracted)
            click.echo(f"3. JSON 解析: ✅ type={type(parsed).__name__}")
        except json.JSONDecodeError as e:
            click.echo(f"❌ 3. JSON 解析失败: {e}")
            start = max(0, e.pos - 20)
            end = min(len(extracted), e.pos + 20)
            click.echo(f"   错误位置 [{e.pos}]: ...{repr(extracted[start:end])}...")
            continue

        # 步骤 4: schema 校验
        if not isinstance(parsed, dict):
            click.echo(f"❌ 4. Schema: 不是对象，是 {type(parsed).__name__}")
            continue

        missing = [f for f in ['summary', 'passed', 'issues'] if f not in parsed]
        if missing:
            click.echo(f"❌ 4. Schema 失败: 缺少字段 {missing}")
            click.echo(f"   实际 keys: {list(parsed.keys())}")
            continue

        click.echo(f"4. Schema: ✅ summary={repr(parsed['summary'])}, passed={parsed['passed']}, issues={len(parsed.get('issues', []))}")

        if parsed.get('issues'):
            sev_count = {}
            for issue in parsed['issues']:
                sev = issue.get('severity', 'unknown')
                sev_count[sev] = sev_count.get(sev, 0) + 1
            click.echo(f"   severity 分布: {sev_count}")

        found_pass = True

    # 最终结果
    click.echo(f"\n{'='*60}")
    if "全部 3 次尝试均失败" in content:
        click.echo("⚠️ 日志结论: 全部 3 次尝试均失败")
    elif found_pass:
        click.echo("✅ 至少有一次提取+解析+Schema 全部通过")
    else:
        click.echo("⚠️ 未找到成功的尝试")


if __name__ == '__main__':
    main()