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
    severity_threshold: str = "warning"      # 阻断级别
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
    timeout: int = 60                        # API 超时（秒）
    max_tokens: int = 4096                   # AI 最大返回长度（token 数）
    proxy: Optional[str] = None              # HTTP 代理

    def __post_init__(self):
        """校验配置值"""
        valid_thresholds = ["info", "warning", "error", "critical"]
        if self.severity_threshold not in valid_thresholds:
            self.severity_threshold = "warning"
        valid_diff_modes = ["full", "diff"]
        if self.diff_mode not in valid_diff_modes:
            self.diff_mode = "full"
        if self.max_file_size < 1:
            self.max_file_size = 500
        if self.timeout < 1:
            self.timeout = 60
        if self.max_tokens < 256:
            self.max_tokens = 4096
        if self.max_tokens > 8192:
            self.max_tokens = 8192
    
    def merge(self, other: 'Config') -> 'Config':
        """合并另一个配置，非空字段覆盖当前配置
        
        用于：项目配置覆盖全局配置。
        other 中非空/非默认的字段会覆盖 self 中的对应字段。
        
        Args:
            other: 另一个 Config 对象（项目配置）
            
        Returns:
            新的 Config 对象（合并后的结果）
        """
        # 获取当前配置的字典
        result_dict = asdict(self)
        other_dict = asdict(other)
        
        # other 中非"未配置"的字段覆盖 result
        # 未配置 = None / "" / []
        # 注意：False 和 0 是有效配置（如 enabled=false），不能跳过
        for key, value in other_dict.items():
            if value is not None and value != "" and value != []:
                result_dict[key] = value
        
        return Config(**result_dict)


def _parse_token_size(value: str) -> int:
    """解析 token 大小字符串，支持单位写法
    
    支持的格式:
        "4K" → 4096
        "8k" → 8192
        "4096" → 4096
        "1.5k" → 1536
    
    不支持或解析失败返回 0（Config 校验会 fallback 到 4096）
    
    Args:
        value: 用户输入的字符串，如 "4K"
        
    Returns:
        解析后的整数 token 数
    """
    value = value.strip().lower()
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
    
    def _load_single(self, path: Path) -> Optional[Config]:
        """从单个文件加载配置
        
        Args:
            path: 配置文件路径
            
        Returns:
            Config 对象，或 None（文件不存在或解析失败）
        """
        if not path.exists():
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            # 过滤非法字段
            valid_fields = {f.name for f in fields(Config)}
            filtered_data = {k: v for k, v in data.items() if k in valid_fields}
            
            # 处理 max_tokens 单位写法：4K = 4096, 8K = 8192
            if 'max_tokens' in filtered_data and isinstance(filtered_data['max_tokens'], str):
                filtered_data['max_tokens'] = _parse_token_size(filtered_data['max_tokens'])
            
            return Config(**filtered_data)
        except Exception:
            return None
    
    def load(self) -> Config:
        """加载配置（自动合并两级配置）
        
        逻辑：
        1. 加载全局配置（不存在则创建默认）
        2. 如果指定了 repo_path，加载项目配置
        3. 项目配置非空字段覆盖全局配置
        4. 返回合并后的配置
        
        Returns:
            Config 对象（合并后的最终配置）
        """
        # 1. 加载全局配置
        global_config = self._load_single(self.global_path)
        if global_config is None:
            # 全局配置不存在，创建默认的
            global_config = Config()
            self.save(global_config, level="global")
        
        # 2. 如果没有项目路径，直接返回全局配置
        if not self.project_path:
            self._log_final_config(global_config, "全局")
            return global_config
        
        # 3. 加载项目配置
        project_config = self._load_single(self.project_path)
        if project_config is None:
            # 项目配置不存在，只用全局配置
            self._log_final_config(global_config, "全局")
            return global_config
        
        # 4. 合并：项目配置覆盖全局配置
        merged = global_config.merge(project_config)
        
        # 打印提示，让用户知道哪些配置来自项目
        self._log_merge_info(global_config, project_config)
        self._log_final_config(merged, "合并后")
        
        return merged
    
    def _log_merge_info(self, global_cfg: Config, project_cfg: Config) -> None:
        """打印合并信息（哪些字段被项目配置覆盖了）"""
        overridden = []
        for f in fields(Config):
            key = f.name
            global_val = getattr(global_cfg, key)
            project_val = getattr(project_cfg, key)
            if project_val and project_val != global_val:
                # 不打印敏感信息（api_key）
                if key == "api_key":
                    overridden.append(f"{key}: ***覆盖***")
                else:
                    overridden.append(f"{key}: {global_val} → {project_val}")
        
        if overridden:
            print(f"[信息] 使用项目配置覆盖: {', '.join(overridden)}")
    
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
        lines.append(f"  diff_mode: {config.diff_mode} (full=完整文件, diff=只审变更)")
        lines.append(f"  proxy: {config.proxy or '(未配置)'}")
        
        print("\n".join(lines) + "\n")
    
    def save(self, config: Config, level: str = "global") -> None:
        """保存配置
        
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
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(asdict(config), f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except OSError as e:
            raise RuntimeError(f"无法保存配置文件: {e}") from e
