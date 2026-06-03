"""配置管理模块 - 负责加载、保存和管理 AI 代码审核系统的配置."""

import os
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class Config:
    """AI 代码审核系统配置"""
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    language: str = "zh-CN"
    auto_fix: bool = True
    severity_threshold: str = "warning"  # info / warning / error / critical
    max_file_size: int = 500  # KB
    ignore_patterns: List[str] = field(default_factory=lambda: [
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
    timeout: int = 60  # seconds
    proxy: Optional[str] = None

    def __post_init__(self):
        """验证配置值有效性"""
        valid_thresholds = ["info", "warning", "error", "critical"]
        if self.severity_threshold not in valid_thresholds:
            self.severity_threshold = "warning"
        if self.max_file_size < 1:
            self.max_file_size = 500
        if self.timeout < 1:
            self.timeout = 60


class ConfigManager:
    """配置管理器 - 负责配置的加载和持久化"""
    
    DEFAULT_CONFIG_DIR = ".commit-ai-guardian"
    DEFAULT_CONFIG_FILE = "config.yaml"
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 自定义配置文件路径，默认使用 ~/.commit-ai-guardian/config.yaml
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            home = Path.home()
            self.config_path = home / self.DEFAULT_CONFIG_DIR / self.DEFAULT_CONFIG_FILE
    
    def get_default_config_path(self) -> str:
        """获取默认配置文件路径"""
        return str(self.config_path)
    
    def load(self) -> Config:
        """
        加载配置，如果配置文件不存在则创建默认配置并保存
        
        Returns:
            Config 配置对象
        """
        if not self.config_path.exists():
            default_config = Config()
            self.save(default_config)
            return default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            # 过滤掉 Config 中不存在的字段
            valid_fields = {f.name for f in Config.__dataclass_fields__.values()}
            filtered_data = {k: v for k, v in data.items() if k in valid_fields}
            
            return Config(**filtered_data)
        except (yaml.YAMLError, TypeError, ValueError) as e:
            print(f"[警告] 配置文件解析失败 ({e})，使用默认配置")
            default_config = Config()
            self.save(default_config)
            return default_config
    
    def save(self, config: Config) -> None:
        """
        保存配置到文件
        
        Args:
            config: 要保存的配置对象
        """
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(asdict(config), f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except OSError as e:
            raise RuntimeError(f"无法保存配置文件: {e}") from e
