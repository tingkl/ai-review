"""配置管理模块

负责：
- 定义 Config 数据类（所有可配置项）
- 加载 ~/.commit-ai-guardian/config.yaml
- 保存配置到 YAML 文件
- 自动创建默认配置（第一次使用时）
"""

import os
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class Config:
    """AI 代码审核系统的配置项
    
    所有字段都有默认值，第一次使用时会自动创建。
    用户通过 `configure` 命令或编辑 ~/.commit-ai-guardian/config.yaml 修改。
    """
    api_key: str = ""                         # AI API 密钥（必须配置）
    api_base: str = "https://api.openai.com/v1"  # API 地址（支持第三方）
    model: str = "gpt-4o-mini"               # 模型名称
    language: str = "zh-CN"                  # 审核报告语言
    auto_fix: bool = True                    # 是否启用自动修复建议
    severity_threshold: str = "warning"      # 阻断级别: info/warning/error/critical
    max_file_size: int = 500                 # 最大审核文件大小（KB）
    ignore_patterns: List[str] = field(default_factory=lambda: [
        # 默认忽略的文件类型（这些文件通常不需要代码审核）
        "*.lock", "*.json", "*.md", "*.yaml", "*.yml",
        "*.txt", "*.svg", "*.png", "*.jpg", "*.jpeg",
        "*.gif", "*.ico", "*.woff", "*.woff2", "*.ttf",
        "*.eot", "*.otf", "*.mp3", "*.mp4", "*.avi",
        "*.pdf", "*.doc", "*.docx", "*.zip", "*.tar",
        "*.gz", "*.rar", "*.7z", "*.exe", "*.dll",
        "*.so", "*.dylib", "*.class", "*.jar", "*.war",
        "*.ear", "*.egg", "*.whl", "*.parquet", "*.pkl",
        "*.pickle", "*.model", "*.bin", "*.onnx", "*.pb",
    ])
    timeout: int = 60                        # API 请求超时（秒）
    proxy: Optional[str] = None              # HTTP 代理地址

    def __post_init__(self):
        """校验配置值，非法值回退到默认值（防止用户手误改坏配置）"""
        valid_thresholds = ["info", "warning", "error", "critical"]
        if self.severity_threshold not in valid_thresholds:
            self.severity_threshold = "warning"
        if self.max_file_size < 1:
            self.max_file_size = 500
        if self.timeout < 1:
            self.timeout = 60


class ConfigManager:
    """配置管理器
    
    管理 ~/.commit-ai-guardian/config.yaml 的读写。
    第一次使用时会自动创建默认配置文件。
    """
    
    DEFAULT_CONFIG_DIR = ".commit-ai-guardian"   # 配置文件夹名
    DEFAULT_CONFIG_FILE = "config.yaml"            # 配置文件名
    
    def __init__(self, config_path: Optional[str] = None):
        """初始化配置管理器
        
        Args:
            config_path: 自定义配置文件路径。None 则使用默认值 ~/.commit-ai-guardian/config.yaml
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            home = Path.home()
            self.config_path = home / self.DEFAULT_CONFIG_DIR / self.DEFAULT_CONFIG_FILE
    
    def get_default_config_path(self) -> str:
        """获取配置文件完整路径"""
        return str(self.config_path)
    
    def load(self) -> Config:
        """加载配置
        
        逻辑：
        1. 如果配置文件不存在 → 创建默认配置并保存
        2. 如果配置文件存在但解析失败 → 打印警告，使用默认配置
        3. 正常情况 → 从 YAML 读取并转为 Config 对象
        
        过滤机制：YAML 中 Config 不认识的字段会被自动忽略（防止旧配置兼容问题）
        """
        # 第一次使用：配置文件不存在，创建默认的
        if not self.config_path.exists():
            default_config = Config()
            self.save(default_config)
            return default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            # 过滤：只保留 Config 中存在的字段（防止 YAML 里有废字段导致报错）
            valid_fields = {f.name for f in Config.__dataclass_fields__.values()}
            filtered_data = {k: v for k, v in data.items() if k in valid_fields}
            
            return Config(**filtered_data)
        except (yaml.YAMLError, TypeError, ValueError) as e:
            print(f"[警告] 配置文件解析失败 ({e})，使用默认配置")
            default_config = Config()
            self.save(default_config)
            return default_config
    
    def save(self, config: Config) -> None:
        """保存配置到 YAML 文件
        
        Args:
            config: Config 数据对象
        """
        try:
            # mkdir(parents=True) = 如果父目录不存在也一起创建
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                # asdict() 把 dataclass 转字典，再 dump 成 YAML
                yaml.dump(asdict(config), f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except OSError as e:
            raise RuntimeError(f"无法保存配置文件: {e}") from e
