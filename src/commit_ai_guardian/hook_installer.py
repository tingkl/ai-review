"""Git Hook 安装器

负责在目标仓库的 .git/hooks/pre-commit 位置写入/删除 hook 脚本。

安全机制：
- 通过 HOOK_MARKER 识别"本工具生成的 hook" vs "用户自定义的 hook"
- 覆盖用户 hook 前自动备份为 .backup
- 卸载时自动恢复备份
"""

import os
import shutil
import stat
from pathlib import Path
from typing import Optional


class HookInstaller:
    """Git pre-commit hook 安装管理器
    
    操作路径：<repo>/.git/hooks/pre-commit
    
    三种场景的处理：
    1. 没有 pre-commit → 直接创建
    2. 有 pre-commit，且包含 HOOK_MARKER → 直接覆盖（是我们之前装的）
    3. 有 pre-commit，但没有 HOOK_MARKER → 拒绝操作（保护用户自定义 hook）
    """
    
    # 统一 marker，用于识别"本工具生成的 hook"
    # .git/hooks/pre-commit 和 .husky/pre-commit 都用同一个
    HOOK_MARKER = "# === commit-ai-guardian ==="
    
    def __init__(self, repo_path: str = "."):
        """初始化
        
        Args:
            repo_path: Git 仓库路径，默认当前目录
        """
        self.repo_path = Path(repo_path).resolve()
        self.git_dir = self.repo_path / ".git"           # .git 目录
        self.hooks_dir = self.git_dir / "hooks"          # hooks 目录
        self.hook_path = self.hooks_dir / "pre-commit"   # pre-commit 文件路径
        
        # 检测 husky：如果 core.hooksPath 指向 .husky/_，说明用了 husky
        self._detect_husky()
    
    def _detect_husky(self):
        """检测是否安装了 husky（通过 core.hooksPath）
        
        husky v9+ 会设置 core.hooksPath = .husky/_
        此时 Git 不再执行 .git/hooks/pre-commit，而是执行 .husky/_/pre-commit
        
        检测到 husky 时，我们的命令要追加到 .husky/pre-commit，而不是 .git/hooks/pre-commit
        """
        self.husky_dir = None          # .husky/ 目录
        self.husky_hook_path = None    # .husky/pre-commit 文件路径
        self.has_husky = False
        
        try:
            import subprocess
            result = subprocess.run(
                ["git", "-C", str(self.repo_path), "config", "core.hooksPath"],
                capture_output=True, text=True, timeout=5
            )
            hooks_path = result.stdout.strip() if result.returncode == 0 else ""
            
            # husky v9+ 设置 core.hooksPath = .husky/_
            if hooks_path and ".husky" in hooks_path:
                # 解析 hooksPath（可能是相对路径或绝对路径）
                if hooks_path.startswith("/"):
                    husky_base = Path(hooks_path).parent  # .husky/_/ → .husky
                else:
                    husky_base = self.repo_path / hooks_path.replace("/_", "").replace("/_default", "")
                
                self.husky_dir = husky_base
                self.husky_hook_path = husky_base / "pre-commit"
                self.has_husky = True
        except Exception:
            pass  # git 命令失败，当作没有 husky
    
    def is_git_repo(self) -> bool:
        """检查目标路径是否为 Git 仓库（判断依据：有没有 .git/ 目录）"""
        return self.git_dir.is_dir()
    
    def get_hook_path(self) -> str:
        """获取 pre-commit hook 的绝对路径
        
        有 husky 时返回 .husky/pre-commit，无 husky 时返回 .git/hooks/pre-commit
        """
        if self.has_husky and self.husky_hook_path:
            return str(self.husky_hook_path)
        return str(self.hook_path)
    
    def is_hook_installed(self) -> bool:
        """检查 pre-commit hook 是否已由本工具安装
        
        判断逻辑：
        - 有 husky：检查 .husky/pre-commit 是否包含我们的 marker
        - 无 husky：检查 .git/hooks/pre-commit 是否包含 HOOK_MARKER
        
        Returns:
            True = 是本工具安装的，可以安全覆盖/卸载
            False = 不存在 或 是其他工具/用户自定义的
        """
        # 场景 A：有 husky，检查 .husky/pre-commit
        if self.has_husky and self.husky_hook_path and self.husky_hook_path.exists():
            try:
                content = self.husky_hook_path.read_text(encoding='utf-8')
                return self.HOOK_MARKER in content
            except (OSError, UnicodeDecodeError):
                return False
        
        # 场景 B：无 husky，检查 .git/hooks/pre-commit
        if not self.hook_path.exists():
            return False
        try:
            content = self.hook_path.read_text(encoding='utf-8')
            return self.HOOK_MARKER in content
        except (OSError, UnicodeDecodeError):
            return False
    
    def install(self, force: bool = False) -> bool:
        """安装 pre-commit hook
        
        执行流程：
        1. 检查是否为 Git 仓库
        2. 检测 husky：如果用了 husky v9+，命令追加到 .husky/pre-commit
        3. 如果没有 husky，写入 .git/hooks/pre-commit
        4. chmod +x 赋予执行权限
        
        Args:
            force: True = 强制覆盖已有 hook（会自动备份）
            
        Returns:
            True = 安装成功
            False = 安装失败（如已有用户 hook 且未加 --force）
            
        Raises:
            RuntimeError: 目标路径不是 Git 仓库
        """
        if not self.is_git_repo():
            raise RuntimeError(f"'{self.repo_path}' 不是 Git 仓库")
        
        # 场景 A：检测到 husky v9+（core.hooksPath 指向 .husky/_）
        if self.has_husky and self.husky_hook_path:
            return self._install_to_husky(force=force)
        
        # 场景 B：没有 husky，直接写入 .git/hooks/pre-commit
        return self._install_to_git_hooks(force=force)
    
    def _install_to_husky(self, force: bool = False) -> bool:
        """安装到 husky 的 .husky/pre-commit（husky v9+ 兼容）
        
        husky v9+ 设置 core.hooksPath = .husky/_
        Git 执行的是 .husky/_/pre-commit，它会调用 .husky/pre-commit
        所以我们的命令要追加到 .husky/pre-commit
        
        多命令共存策略：
        - lint-staged 等工具通常写在 .husky/pre-commit
        - 我们追加 `commit-ai-guardian audit`，确保 lint-staged 之后再审核
        """
        husky_file = self.husky_hook_path
        
        # 确保 .husky/ 目录存在
        husky_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 读取现有内容（可能有 lint-staged 等命令）
        existing = ""
        if husky_file.exists():
            existing = husky_file.read_text(encoding='utf-8').strip()
        
        # 检查是否已安装
        marker = "# === commit-ai-guardian ==="
        if marker in existing:
            if not force:
                print(f"[信息] commit-ai-guardian 已在 husky 中安装")
                print(f"        路径: {husky_file}")
                print(f"        使用 --force 重新安装")
                return False
            # force：去掉旧的，重新追加
            lines = existing.split('\n')
            new_lines = []
            old_cag_block = []
            skip = False
            for line in lines:
                if line.strip() == marker:
                    skip = True
                    old_cag_block.append(line)
                    continue
                if skip and line.startswith('# === end ') and 'commit-ai-guardian' in line:
                    skip = False
                    old_cag_block.append(line)
                    continue
                if skip:
                    old_cag_block.append(line)
                    continue
                if not skip:
                    new_lines.append(line)
            existing = '\n'.join(new_lines).strip()
            
            # 生成新的命令块，和旧的比较
            command = self._get_husky_command(marker)
            if '\n'.join(old_cag_block).strip() == command.strip():
                print(f"[信息] commit-ai-guardian 已是最新版本，无需更新")
                self._init_review_dir(force=force)
                return True
            # 内容不一样：备份整个 husky 文件
            backup_path = husky_file.with_suffix('.backup')
            shutil.copy2(husky_file, backup_path)
            print(f"[信息] 原 husky 文件已备份到: {backup_path}")
        
        # 修正 lint-staged：如果没有保存 exit code，自动补全
        # （lint-staged 简化版只有一行命令，追加其他命令后 exit code 会丢失）
        if existing:
            existing = self._fix_lint_staged_if_needed(existing)
        
        # 生成要追加的命令
        command = self._get_husky_command(marker)
        
        # 追加到文件末尾
        if existing:
            new_content = existing + "\n" + command
        else:
            new_content = command.lstrip()
        
        husky_file.write_text(new_content + "\n", encoding='utf-8')
        husky_file.chmod(husky_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        print(f"[成功] commit-ai-guardian 已追加到 husky: {husky_file}")
        if existing:
            print(f"[信息] 已保留现有命令（如 lint-staged），追加在末尾")
        
        # 安装 hook 时顺便初始化 .ai-review/ 案例目录
        self._init_review_dir(force=force)
        
        return True
    
    @staticmethod
    def _get_husky_command(marker: str = "# === commit-ai-guardian ===") -> str:
        """生成要追加到 husky 的命令块（用于内容比对）"""
        return f"""
{marker}
commit-ai-guardian audit
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "提示: 使用 git commit --no-verify 跳过 AI 审核（不推荐）"
    exit $EXIT_CODE
fi
# === end commit-ai-guardian ==="""
    
    def _fix_lint_staged_if_needed(self, content: str) -> str:
        """检测 lint-staged 是否保存了 exit code，如果没有则自动修正
        
        问题场景：lint-staged 简写为 `npx lint-staged` 一行，没有保存 exit code。
        当后面追加了其他命令（如本工具），lint-staged 失败时不会阻断 commit。
        
        检测方式：找到 lint-staged 命令行，检查其后 3 行内是否有 $?
        保存或 if 判断。没有则自动修正为完整版（保存 exit code + if 判断）。
        
        支持的命令格式：
            npx lint-staged
            yarn lint-staged
            pnpm lint-staged / pnpm exec lint-staged
            bunx lint-staged
            ./node_modules/.bin/lint-staged
        
        Args:
            content: .husky/pre-commit 的现有内容
            
        Returns:
            修正后的内容（如果不需要修正则原样返回）
        """
        lines = content.split('\n')
        
        # 匹配 lint-staged 命令行（排除注释和空行）
        lint_staged_pattern = re.compile(
            r'^(\s*)((?:npx|yarn|pnpm|pnpm exec|bunx)\s+lint-staged'
            r'|\.\/node_modules\/\.bin\/lint-staged'
            r'|lint-staged\b)'
        )
        
        # 已保存 exit code 的标志
        exit_code_saved_pattern = re.compile(
            r'(\$\?|\bLINT_EXIT\b|\bexit\b|\bif\b)'
        )
        
        for i, line in enumerate(lines):
            if lint_staged_pattern.match(line):
                # 找到了 lint-staged 命令，检查后面几行是否保存了 exit code
                # 看后面 3 行（跳过空行和注释）
                found_save = False
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line or next_line.startswith('#'):
                        continue
                    if exit_code_saved_pattern.search(next_line):
                        found_save = True
                        break
                
                if not found_save:
                    # lint-staged 没有保存 exit code，自动修正为完整版
                    indent = lint_staged_pattern.match(line).group(1)
                    fixed_lines = [
                        line,  # 原 lint-staged 命令
                        f"{indent}LINT_EXIT=$?",
                        f"{indent}if [ $LINT_EXIT -ne 0 ]; then",
                        f"{indent}    exit $LINT_EXIT",
                        f"{indent}fi",
                    ]
                    lines[i:i+1] = fixed_lines
                    print(f"[信息] 自动修正 lint-staged：补充 exit code 保存逻辑")
                    return '\n'.join(lines)
        
        # 没有找到 lint-staged，或已经保存了 exit code
        return content
    
    def _install_to_git_hooks(self, force: bool = False) -> bool:
        """安装到 .git/hooks/pre-commit（传统方式，无 husky）"""
        # 确保 hooks 目录存在（mkdir -p 的效果）
        self.hooks_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取新脚本内容（提前读取，用于内容比对）
        hook_script = self._get_hook_script()
        
        # 场景：已有用户自定义 hook（不含 HOOK_MARKER）
        if self.hook_path.exists() and not self.is_hook_installed():
            if not force:
                print(f"[警告] 已存在自定义 pre-commit hook")
                print(f"        路径: {self.hook_path}")
                print(f"        使用 --force 覆盖，或先手动备份")
                return False
            # 加 --force：备份原 hook，然后覆盖
            backup_path = self.hook_path.with_suffix('.backup')
            shutil.copy2(self.hook_path, backup_path)
            print(f"[信息] 原 hook 已备份到: {backup_path}")
        elif self.hook_path.exists() and self.is_hook_installed():
            # 是 cag 装的：内容一样就跳过，不一样备份后覆盖
            existing_script = self.hook_path.read_text(encoding='utf-8')
            if existing_script.strip() == hook_script.strip():
                print(f"[信息] pre-commit hook 已是最新版本，无需更新")
                self._init_review_dir(force=force)
                return True
            # 内容不一样：备份旧的，写入新的
            backup_path = self.hook_path.with_suffix('.backup')
            shutil.copy2(self.hook_path, backup_path)
            print(f"[信息] 原 hook 已备份到: {backup_path}")
        
        # 写入脚本
        self.hook_path.write_text(hook_script, encoding='utf-8')
        
        # Git 要求 hook 必须有执行权限
        self.hook_path.chmod(self.hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        print(f"[成功] pre-commit hook 已安装到: {self.hook_path}")
        
        # 安装 hook 时顺便初始化 .ai-review/ 案例目录
        self._init_review_dir(force=force)
        
        return True
    
    def uninstall(self) -> bool:
        """卸载 pre-commit hook
        
        执行流程：
        1. 如果检测到 husky → 从 .husky/pre-commit 移除命令块
        2. 如果没有 husky → 删除 .git/hooks/pre-commit
        3. 如果 hook 不是本工具生成的 → 拒绝删除（保护用户配置）
        
        Returns:
            True = 卸载成功（或无需卸载）
            False = 卸载失败
        """
        # 场景 A：检测到 husky → 从 .husky/pre-commit 移除命令块
        if self.has_husky and self.husky_hook_path and self.husky_hook_path.exists():
            return self._uninstall_from_husky()
        
        # 场景 B：没有 husky → 删除 .git/hooks/pre-commit
        return self._uninstall_from_git_hooks()
    
    def _uninstall_from_husky(self) -> bool:
        """从 husky 的 .husky/pre-commit 移除命令块"""
        husky_file = self.husky_hook_path
        
        if not husky_file.exists():
            print("[信息] husky pre-commit 不存在，无需卸载")
            return True
        
        content = husky_file.read_text(encoding='utf-8')
        marker = "# === commit-ai-guardian ==="
        
        if marker not in content:
            print("[信息] commit-ai-guardian 不在 husky pre-commit 中")
            return True
        
        # 移除命令块（保留其他命令如 lint-staged）
        lines = content.split('\n')
        new_lines = []
        skip = False
        for line in lines:
            if line.strip() == marker:
                skip = True
                continue
            if skip and line.startswith('# === end ') and 'commit-ai-guardian' in line:
                skip = False
                continue
            if not skip:
                new_lines.append(line)
        
        new_content = '\n'.join(new_lines).strip()
        if new_content:
            husky_file.write_text(new_content + "\n", encoding='utf-8')
        else:
            husky_file.unlink()
        
        print(f"[成功] 已从 husky 卸载: {husky_file}")
        print("[信息] 保留了其他命令（如 lint-staged）")
        return True
    
    def _uninstall_from_git_hooks(self) -> bool:
        """卸载 .git/hooks/pre-commit"""
        # 场景 1：没有 hook
        if not self.hook_path.exists():
            print("[信息] 没有找到 pre-commit hook，无需卸载")
            return True
        
        # 场景 3：用户自定义 hook → 不碰
        if not self.is_hook_installed():
            print("[警告] pre-commit hook 不是由本工具生成的，不会自动卸载")
            print(f"        如需手动删除，请执行: rm {self.hook_path}")
            return False
        
        # 场景 2：本工具生成的 → 删除，并恢复备份（如果有）
        try:
            self.hook_path.unlink()
            print("[成功] pre-commit hook 已卸载")
            
            # 卸载时恢复之前备份的自定义 hook（如果存在）
            backup_path = self.hook_path.with_suffix('.backup')
            if backup_path.exists():
                shutil.move(backup_path, self.hook_path)
                print(f"[信息] 原 hook 已从备份恢复")
            
            return True
        except OSError as e:
            print(f"[错误] 卸载失败: {e}")
            return False
    
    def _init_review_dir(self, force: bool = False) -> bool:
        """在目标仓库初始化 .ai-review/ 项目配置目录（install 时自动调用）
        
        创建 .ai-review/cases/ 目录，并复制示例案例文件。
        用户可以根据项目需求修改这些示例。
        
        Returns:
            True = 初始化成功（或已存在）
            False = 失败
        """
        if not self.is_git_repo():
            print(f"[错误] '{self.repo_path}' 不是 Git 仓库")
            return False
        
        # 创建 .ai-review/ 下的目录结构
        review_dir = self.repo_path / ".ai-review"
        cases_dir = review_dir / "cases"      # ← 用户把需要启用的案例放这里
        example_dir = review_dir / "examples"  # ← 工具自带的示例模板放这里
        prompts_dir = review_dir / "prompts"  # ← prompt 模板（用户可以自定义审核行为）
        cache_dir = review_dir / "cache"      # ← 审核结果缓存（MD5 → 结果）
        logs_dir = review_dir / "logs"        # ← 审核日志（prompt/ai 响应）
        
        try:
            # 创建 cases/（空目录，用户自己添加案例）
            cases_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建 examples/（放示例模板，不参与审核）
            is_new_example = not example_dir.exists()
            example_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建 prompts/（放 prompt 模板，install 时写入默认模板）
            prompts_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建 cache/（审核结果缓存，MD5 → 结果）
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建 logs/（审核日志目录：{md5}.ai.log / {md5}.json_fix.log）
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建 .ai-review/.gitignore（忽略自动生成的 cache/ 和 logs/）
            gitignore_file = review_dir / ".gitignore"
            if not gitignore_file.exists():
                gitignore_file.write_text(
                    "# 自动生成的文件，不需要提交到 Git\n"
                    "cache/\n"
                    "logs/\n",
                    encoding='utf-8'
                )
            
            # 复制示例案例文件到 cases/（按语言子目录组织）
            examples_source = Path(__file__).parent / "templates" / "examples"
            copied = 0
            if examples_source.exists():
                for example_file in sorted(examples_source.rglob("*.md")):
                    # 保持子目录结构：cases/js/xxx.md
                    rel_path = example_file.relative_to(examples_source)
                    target = example_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        import shutil
                        shutil.copy2(example_file, target)
                        copied += 1
            
            # 写入默认 prompt 模板（用户可以修改来自定义审核行为）
            from .prompt_loader import PromptLoader
            template_files = PromptLoader.get_default_template_files()
            for template_name, template_content in template_files.items():
                template_path = prompts_dir / template_name
                if not template_path.exists():
                    # 文件不存在，直接写入
                    template_path.write_text(template_content, encoding='utf-8')
                else:
                    # 文件已存在，比对内容
                    existing_content = template_path.read_text(encoding='utf-8')
                    if existing_content.strip() == template_content.strip():
                        # 内容一样，跳过
                        continue
                    # 内容不一样，备份后覆盖
                    import shutil
                    backup_path = template_path.with_suffix('.backup')
                    shutil.copy2(template_path, backup_path)
                    template_path.write_text(template_content, encoding='utf-8')
                    print(f"[信息] prompt 模板已更新: {template_name}（原文件备份到: {backup_path}）")
            
            # 创建用户自定义 prompt 文件（custom_prompt.md）
            # 此文件不会被 install --force 覆盖，用户可在此添加自己的审核规则
            custom_prompt_path = prompts_dir / "custom_prompt.md"
            if not custom_prompt_path.exists():
                custom_prompt_path.write_text(
                    "<!-- 自定义审核规则 -->\n"
                    "<!-- 此文件内容会在每次审核前作为 system message 的一部分发送给 AI -->\n"
                    "<!-- 可以在此添加团队特定的编码规范、业务规则等 -->\n"
                    "\n"
                    "## 团队自定义规则\n"
                    "\n"
                    "在此添加你的自定义审核规则...\n",
                    encoding='utf-8'
                )
                print(f"[信息] 自定义 prompt 模板已创建: custom_prompt.md（不会被覆盖）")
            
            # 创建或补全项目配置文件 config.yaml
            self._ensure_config_file(review_dir / "config.yaml")
            
            # 只在第一次创建时打印提示
            if is_new_example:
                print(f"\n[信息] 案例目录已初始化: {review_dir}")
                if copied > 0:
                    print(f"        {copied} 个示例模板已放到 examples/（不参与审核）")
                print(f"        启用案例: 从 examples/ 复制 .yaml 文件到 cases/")
                print(f"        共享给团队: git add .ai-review/ && git commit")
            return True
            
        except OSError as e:
            print(f"[错误] 初始化失败: {e}")
            return False
    
    # config.yaml 的完整字段定义（key: (默认值, 注释)）
    _CONFIG_FIELDS = {
        'api_key': ('""', 'AI API 密钥'),
        'api_base': ('""', 'API 地址'),
        'model': ('""', '模型名称'),
        'language': ('""', '审核报告语言 (zh-CN/en)'),
        'enabled': ('true', '是否启用 AI 审核（false=跳过，直接通过）'),
        'severity_threshold': ('""', '阻断级别 (info/warning/error/critical)'),
        'diff_mode': ('""', 'diff 审核模式: full=完整文件(默认), diff=只审变更'),
        'max_file_size': ('0', '最大审核文件大小 (KB)'),
        'cache_ttl': ('"1d"', '缓存存活时间（1d=1天, 12h=12小时, 30m=30分钟）'),
        'log_ttl': ('"1h"', '日志存活时间（1h=1小时, 30m=30分钟, 0=不清理）'),
        'include_patterns': ('["*"]', '要审核的目录/文件模式（glob，如 ["src/**", "app/**"]）'),
        'ignore_patterns': (r'["*.lock", "*.md", "*.txt", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.woff", "*.woff2", "*.ttf", "*.eot", "*.otf", "*.mp3", "*.mp4", "*.avi", "*.pdf", "*.doc", "*.docx", "*.zip", "*.tar", "*.gz", "*.rar", "*.7z", "*.exe", "*.dll", "*.so", "*.dylib", "*.class", "*.jar", "*.ear", "*.egg", "*.whl", "*.parquet", "*.pkl", "*.pickle", "*.model", "*.bin", "*.onnx", "*.pb"]', '忽略的文件模式（glob 格式）'),
        'case_format': ('"default"', '案例格式化级别: default=全部(默认), compact=精简, minimal=最小'),
        'timeout': ('0', 'API 超时 (秒)'),
        'max_tokens': ('0', 'AI 最大返回长度 (token 数，支持 4K/8K 写法)'),
        'temperature': ('0.3', 'AI 随机性 (0=最保守, 0.3=平衡, 0.7=灵活)'),
        'proxy': ('""', 'HTTP 代理地址'),
        'json_fix_history_mode': ('"full"', 'JSON 修复 AI 上下文模式: full=完整历史(默认), last=只带上一次'),
    }
    
    def _ensure_config_file(self, config_file: Path) -> None:
        """确保 config.yaml 存在且包含所有字段
        
        - 文件不存在：创建完整的新文件
        - 文件存在：读取现有内容，补全缺失的字段
        
        Args:
            config_file: config.yaml 的路径
        """
        try:
            if config_file.exists():
                # 文件已存在，读取并补全缺失字段
                existing = config_file.read_text(encoding='utf-8')
                
                try:
                    import yaml
                    data = yaml.safe_load(existing) or {}
                except Exception:
                    data = {}
                
                # 找出缺失的字段
                missing = []
                for key, (default, comment) in self._CONFIG_FIELDS.items():
                    if key not in data:
                        missing.append((key, default, comment))
                
                if missing:
                    # 追加缺失字段到文件
                    lines = ["\n# === 以下字段由 install --force 自动补全 ===\n"]
                    for key, default, comment in missing:
                        lines.append(f"\n# {comment}\n{key}: {default}\n")
                    
                    config_file.write_text(existing + "\n".join(lines), encoding='utf-8')
                    print(f"[信息] config.yaml 已补全 {len(missing)} 个缺失字段")
            else:
                # 文件不存在，创建完整的新文件
                lines = [
                    "# 项目级别配置文件\n",
                    "# 只填写需要覆盖全局配置的项，留空则使用全局配置\n",
                    "# 全局配置位置: ~/.commit-ai-guardian/config.yaml\n",
                ]
                for key, (default, comment) in self._CONFIG_FIELDS.items():
                    lines.append(f"\n# {comment}\n{key}: {default}\n")
                
                config_file.write_text("".join(lines), encoding='utf-8')
        
        except OSError as e:
            print(f"[警告] config.yaml 处理失败: {e}")

    def _get_hook_script(self) -> str:
        """获取 hook 脚本内容
        
        优先从 templates/pre-commit-hook-template 文件读取。
        如果模板文件丢失（比如被误删），返回内置的默认脚本作为兜底。
        
        Path(__file__).parent = 当前 Python 文件所在的目录
        拼接 /templates/pre-commit-hook-template 得到模板文件的绝对路径
        """
        template_path = Path(__file__).parent / "templates" / "pre-commit-hook-template"
        if template_path.exists():
            return template_path.read_text(encoding='utf-8')
        
        # 模板文件不存在时的兜底方案（理论上不会发生）
        return '''#!/bin/bash
# AI Code Review Hook — generated by commit-ai-guardian
# 此文件由工具自动生成，请勿手动修改

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 跳过 merge/rebase 操作（别人的代码不审核）
if [ -f "$REPO_ROOT/.git/MERGE_HEAD" ]; then
    echo "[信息] 处于 merge 状态，跳过 AI 审核"
    exit 0
fi
if [ -d "$REPO_ROOT/.git/rebase-merge" ] || [ -d "$REPO_ROOT/.git/rebase-apply" ]; then
    echo "[信息] 处于 rebase 状态，跳过 AI 审核"
    exit 0
fi

# 直接调用 commit-ai-guardian 命令（通过 uv tool install 已加入 PATH）
# 不用 'python -m' 或 'uv run'，避免目标仓库的 Python 环境问题
commit-ai-guardian audit --repo "$REPO_ROOT"

# 获取退出码
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "提示: 使用 git commit --no-verify 跳过 AI 审核（不推荐）"
    exit $EXIT_CODE
fi

exit 0
'''
