# 两个需求

## 1. 空指针规则回退为宽松版 (prompt_loader.py)
- 加回一条规则：除非明显是空指针，否则不要审核空指针问题
- 明显的空指针：obj.a.b.c 其中 obj.a 已知为 null、显式 null 赋值等

## 2. 新增 use_cache 配置项
### config.py
- Config dataclass 加 `use_cache: bool = True`
- `_log_final_config` 中打印 use_cache

### ai_engine.py
- `review_file()` 中缓存检查/保存前判断 use_cache
- `_review_file_no_cache()` 中保存前判断 use_cache
- `review_source()` 中缓存检查/保存前判断 use_cache
- `_review_source_no_cache()` 中保存前判断 use_cache
- `review_batch()` 中批量缓存检查前判断 use_cache
- `review_source_batch()` 中批量缓存检查前判断 use_cache
