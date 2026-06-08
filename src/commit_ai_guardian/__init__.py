"""Commit AI Guardian - Git Pre-commit AI 代码审核工具

使用方式：
    方式一（自动）：install → git commit 时自动触发审核
    方式二（手动）：review -f file.py / -d src/ 审核指定文件

主入口：cli.py 的 main() 函数
"""

__version__ = "0.1.0"
__author__ = "Commit AI Guardian"
__description__ = "在 Git commit 前自动触发 AI 代码审核"
