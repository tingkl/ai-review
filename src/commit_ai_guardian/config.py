"""配置管理模块

支持两级配置（优先级从高到低）：
1. 项目级别: <repo>/.ai-review/config.yaml  （项目特定配置）
2. 全局级别: ~/.commit-ai-guardian/config.yaml  （默认配置）

项目配置覆盖全局配置。例如全局配置了 api_key，项目里可以覆盖用不同的 key。

用法：
    # audit/review 场景（传入 repo_path）
    manager = ConfigManager(repo_path="/path/to/repo")
    config = manager.load()  # 自动合并两级配置
    
    # configure 命令（只操作全局配置）
    manager = ConfigManager()
    config = manager.load()
"""

import os
import yaml
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Config:
    """AI 代码审核系统的配置项"""
    api_key: str = ""                         # AI API 密钥
    api_base: str = "https://api.openai.com/v1"  # API 地址
    model: str = "gpt-4o-mini"               # 模型名称
    language: str = "zh-CN"                  # 审核报告语言（默认中文）
    enabled: bool = True                     # 是否启用 AI 审核（false=跳过，直接通过）
    severity_threshold: str = "warning"      # 阻断级别 (info/warning/error/critical)
    diff_mode: str = "full"                  # diff 审核模式: full=完整文件, diff=只审变更
    max_file_size: int = 500                 # 最大文件大小（KB）
    cache_ttl: str = "1d"                    # 缓存存活时间（1d=1天, 12h=12小时, 30m=30分钟）
    log_ttl: str = "1h"                      # 日志存活时间（1h=1小时, 30m=30分钟, 0=不清理）
    include_patterns: List[str] = field(default_factory=lambda: ["*"])
    ignore_patterns: List[str] = field(default_factory=lambda: [
        # 配置文件
        "*.gitignore", "*.lock", "*.json", "*.yaml", "*.yml",
        # 文档
        "*.md", "*.txt",
        # 图片
        "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico",
        # 字体
        "*.woff", "*.woff2", "*.ttf", "*.eot", "*.otf",
        # 媒体
        "*.mp3", "*.mp4", "*.avi",
        # 文档/压缩包/二进制
        "*.pdf", "*.doc", "*.docx", "*.zip", "*.tar",
        "*.gz", "*.rar", "*.7z", "*.exe", "*.dll",
        "*.so", "*.dylib", "*.class", "*.jar", "*.war",
        "*.ear", "*.egg", "*.whl", "*.parquet", "*.pkl",
        "*.pickle", "*.model", "*.bin", "*.onnx", "*.pb",
    ])
    case_format: str = "compact"            # 案例格式化级别: default=全部, compact=精简(默认), minimal=最小
    timeout: int = 60                        # API 超时（秒）
    max_tokens: int = 8192                   # AI 最大返回长度（token 数）
    temperature: float = 0.3                 # AI 随机性 (0=最确定, 1=最随机, 2=最大)
    proxy: Optional[str] = None              # HTTP 代理
    use_cache: bool = True                   # 是否使用缓存 (false=不检查缓存、不写入缓存)
    json_fix_history_mode: str = "full"      # JSON 修复 AI 上下文模式: full=完整历史(默认), last=只带上一次

    def __post_init__(self):
        """校验配置值（类型不安全时静默回退到默认值）
        
        注意：0 是合法值，只在 < 0（负值/类型错误）时回退。
        timeout=0 表示"不超时"，max_file_size=0 在调用处兜底。
        """
        valid_thresholds = ["info", "warning", "error", "critical"]
        if self.severity_threshold not in valid_thresholds:
            self.severity_threshold = "warning"
        valid_diff_modes = ["full", "diff"]
        if self.diff_mode not in valid_diff_modes:
            self.diff_mode = "full"
        # 数值校验：负值或类型错误时回退默认值（0 是合法值）
        try:
            if self.max_file_size < 0:
                self.max_file_size = 500
        except TypeError:
            self.max_file_size = 500
        try:
            if self.timeout < 0:
                self.timeout = 60
        except TypeError:
            self.timeout = 60
        try:
            if self.max_tokens < 0:
                self.max_tokens = 8192
            # 上限 128K
            if self.max_tokens > 131072:
                self.max_tokens = 131072
        except TypeError:
            self.max_tokens = 8192
        try:
            if self.temperature < 0:
                self.temperature = 0.3
            if self.temperature > 2:
                self.temperature = 2.0
        except TypeError:
            self.temperature = 0.3
        # case_format 校验
        if self.case_format not in ("default", "compact", "minimal"):
            self.case_format = "compact"
        
        # json_fix_history_mode 校验
        if self.json_fix_history_mode not in ("full", "last"):
            self.json_fix_history_mode = "full"
    
    def merge(self, other: 'Config', explicit_fields: set = None) -> 'Config':
        """合并另一个配置，非空字段覆盖当前配置
        
        用于：项目配置覆盖全局配置。
        只有 explicit_fields 中列出的字段才会覆盖，避免缺失字段的默认值
        错误覆盖全局配置。
        
        Args:
            other: 另一个 Config 对象（项目配置）
            explicit_fields: 用户明确配置的字段名集合（从 YAML 实际读取的字段）
                             为 None 时回退到旧行为（全部比较）
            
        Returns:
            新的 Config 对象（合并后的结果）
        """
        # 获取当前配置的字典
        result_dict = asdict(self)
        other_dict = asdict(other)
        
        # other 中非"未配置"的字段覆盖 result
        # 未配置 = None / "" / [] / 0（数值型字段的 0 视为未配置）
        # False 是有效配置（enabled=false），不能跳过
        for key, value in other_dict.items():
            # 如果提供了 explicit_fields，只覆盖明确配置的字段
            if explicit_fields is not None and key not in explicit_fields:
                continue
            
            if value is not None and value != "" and value != []:
                # 数值型字段（max_file_size, timeout, max_tokens）：0 视为未配置
                if key in ("max_file_size", "timeout", "max_tokens") and value == 0:
                    continue
                result_dict[key] = value
        
        return Config(**result_dict)


def _parse_token_size(value) -> int:
    """解析 token 大小字符串，支持单位写法
    
    支持的格式:
        "4K" → 4096
        "8k" → 8192
        "16k" → 16384
        "64k" → 65536
        "128k" → 131072
        "4096" → 4096
        "1.5k" → 1536
    
    不支持或解析失败返回 0（Config 校验会 fallback 到 4096）
    
    Args:
        value: 用户输入的字符串/数字，如 "4K"、8192
        
    Returns:
        解析后的整数 token 数
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    value = str(value).strip().lower()
    if not value:
        return 0
    
    try:
        if value.endswith('k'):
            num = float(value[:-1])
            return int(num * 1024)
        return int(value)
    except (ValueError, TypeError):
        return 0


class ConfigManager:
    """配置管理器
    
    支持两级配置加载：
    - 全局：~/.commit-ai-guardian/config.yaml
    - 项目：<repo>/.ai-review/config.yaml（优先级更高）
    """
    
    GLOBAL_CONFIG_DIR = ".commit-ai-guardian"
    GLOBAL_CONFIG_FILE = "config.yaml"
    PROJECT_CONFIG_DIR = ".ai-review"
    PROJECT_CONFIG_FILE = "config.yaml"
    
    def __init__(self, config_path: Optional[str] = None, repo_path: Optional[str] = None):
        """初始化
        
        Args:
            config_path: 自定义配置文件路径（优先级最高，一般用于测试）
            repo_path: 代码仓库路径（用于加载项目级别配置）
        """
        self.custom_path = Path(config_path) if config_path else None
        self.repo_path = Path(repo_path) if repo_path else None
        
        # 确定各级配置路径
        if config_path:
            self.global_path = Path(config_path)
            self.project_path = None
        else:
            home = Path.home()
            self.global_path = home / self.GLOBAL_CONFIG_DIR / self.GLOBAL_CONFIG_FILE
            if repo_path:
                self.project_path = Path(repo_path) / self.PROJECT_CONFIG_DIR / self.PROJECT_CONFIG_FILE
            else:
                self.project_path = None
    
    def get_global_path(self) -> str:
        """获取全局配置文件路径"""
        return str(self.global_path)
    
    def get_project_path(self) -> Optional[str]:
        """获取项目配置文件路径（可能为 None）"""
        return str(self.project_path) if self.project_path else None
    
    def _load_single(self, path: Path) -> Optional[tuple[Config, set]]:
        """从单个文件加载配置
        
        Args:
            path: 配置文件路径
            
        Returns:
            (Config 对象, 明确配置的字段名集合)，或 None（文件不存在或解析失败）
            字段名集合 = YAML 中实际存在的合法字段，用于 merge() 区分"用户配置"和"默认值"
        """
        if not path.exists():
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            # 过滤非法字段
            valid_fields = {f.name for f in fields(Config)}
            filtered_data = {k: v for k, v in data.items() if k in valid_fields}
            
            # 记录用户明确配置的字段（YAML 中实际存在的合法字段）
            explicit_fields = set(filtered_data.keys())
            
            # 处理 max_tokens 单位写法：4K = 4096, 8K = 8192
            if 'max_tokens' in filtered_data and isinstance(filtered_data['max_tokens'], str):
                filtered_data['max_tokens'] = _parse_token_size(filtered_data['max_tokens'])
            
            return Config(**filtered_data), explicit_fields
        except Exception:
            return None
    
    def load(self) -> Config:
        """加载配置（自动合并两级配置）
        
        逻辑：
        1. 加载全局配置（不存在则创建默认）
        2. 如果指定了 repo_path，加载项目配置
        3. 项目配置非空字段覆盖全局配置（只覆盖 YAML 中明确配置的字段）
        4. 返回合并后的配置
        
        Returns:
            Config 对象（合并后的最终配置）
        """
        # 1. 加载全局配置
        global_result = self._load_single(self.global_path)
        if global_result is None:
            # 全局配置不存在，创建默认的
            global_config = Config()
            self.save(global_config, level="global")
            global_explicit = set()
        else:
            global_config, global_explicit = global_result
        
        # 2. 如果没有项目路径，直接返回全局配置
        if not self.project_path:
            return global_config
        
        # 3. 加载项目配置
        project_result = self._load_single(self.project_path)
        if project_result is None:
            # 项目配置不存在，只用全局配置
            return global_config
        
        project_config, project_explicit = project_result
        
        # 4. 合并：项目配置覆盖全局配置（只覆盖明确配置的字段）
        merged = global_config.merge(project_config, explicit_fields=project_explicit)
        
        return merged
    
    def log_config(self, config: Config, source: str = "") -> None:
        """打印配置信息（由调用方决定何时打印）
        
        Args:
            config: 配置对象
            source: 配置来源说明
        """
        self._log_final_config(config, source)
    
    def _log_final_config(self, config: Config, source: str) -> None:
        """打印最终生效的配置信息（每次审核时显示）
        
        Args:
            config: 最终生效的 Config 对象
            source: 配置来源说明（"全局"/"合并后"）
        """
        lines = [f"[配置] {source}配置:"]
        
        # API Key（脱敏）
        if config.api_key:
            masked = config.api_key[:4] + "****" + config.api_key[-4:] if len(config.api_key) > 8 else "****"
            lines.append(f"  api_key: {masked}")
        else:
            lines.append(f"  api_key: (未配置)")
        
        # 其他关键配置
        lines.append(f"  api_base: {config.api_base}")
        lines.append(f"  model: {config.model}")
        lines.append(f"  language: {config.language}")
        lines.append(f"  enabled: {config.enabled} (false=跳过审核)")
        lines.append(f"  severity_threshold: {config.severity_threshold}")
        lines.append(f"  max_file_size: {config.max_file_size} KB")
        lines.append(f"  timeout: {config.timeout} 秒")
        lines.append(f"  max_tokens: {config.max_tokens}")
        lines.append(f"  temperature: {config.temperature} (0=保守, 0.3=平衡, 0.7=灵活)")
        lines.append(f"  case_format: {config.case_format} (default=完整, compact=精简, minimal=最小)")
        lines.append(f"  json_fix_history_mode: {config.json_fix_history_mode} (full=完整历史, last=只带上一次)")
        lines.append(f"  diff_mode: {config.diff_mode} (full=完整文件, diff=只审变更)")
        lines.append(f"  use_cache: {config.use_cache} (false=不命中缓存)")
        lines.append(f"  proxy: {config.proxy or '(未配置)'}")
        lines.append(f"  include_patterns: {config.include_patterns or '(未配置, 审核所有文件)'}")
        lines.append(f"  ignore_patterns: {config.ignore_patterns or '(未配置)'}")
        
        print("\n".join(lines) + "\n")
    
    def save(self, config: Config, level: str = "global") -> None:
        """保存配置（只保存与默认值不同的字段）
        
        避免把 0/默认值写入 YAML，覆盖全局配置的非零值。
        
        Args:
            config: Config 对象
            level: "global" 或 "project"，决定保存到哪个位置
        """
        if level == "project" and self.project_path:
            path = self.project_path
        else:
            path = self.global_path
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # 获取当前配置和默认值
            config_dict = asdict(config)
            defaults = Config()  # 创建默认配置对象
            default_dict = asdict(defaults)
            
            # 只保存与默认值不同的字段
            # 这样不会把 0/默认值写入 YAML，避免覆盖全局配置
            non_default = {}
            for key, value in config_dict.items():
                if value != default_dict[key]:
                    non_default[key] = value
            
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(non_default, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except OSError as e:
            raise RuntimeError(f"无法保存配置文件: {e}") from e
