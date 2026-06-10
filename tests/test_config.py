"""Tests for commit_ai_guardian.config module

Covers Config dataclass, _parse_token_size helper, and ConfigManager._load_single.
"""

import sys
from dataclasses import fields
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commit_ai_guardian.config import Config, ConfigManager, _parse_token_size


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_with_custom_values():
    """Return a Config with explicit non-default values."""
    return Config(
        api_key="my-key",
        api_base="https://custom.api.com/v1",
        model="gpt-4",
        language="en",
        enabled=False,
        severity_threshold="error",
        diff_mode="diff",
        max_file_size=1000,
        cache_ttl="12h",
        log_ttl="30m",
        include_patterns=["*.py"],
        ignore_patterns=["*.pyc"],
        timeout=30,
        max_tokens=8192,
        proxy="http://proxy:8080",
    )


@pytest.fixture
def empty_config():
    """Return a Config with all default values."""
    return Config()


# ---------------------------------------------------------------------------
# 1. Config default values
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    """Verify that Config fields have the expected default values."""

    def test_default_api_key_is_empty_string(self):
        cfg = Config()
        assert cfg.api_key == ""

    def test_default_api_base_is_openai(self):
        cfg = Config()
        assert cfg.api_base == "https://api.openai.com/v1"

    def test_default_model_is_gpt4o_mini(self):
        cfg = Config()
        assert cfg.model == "gpt-4o-mini"

    def test_default_language_is_zh_cn(self):
        cfg = Config()
        assert cfg.language == "zh-CN"

    def test_default_enabled_is_true(self):
        cfg = Config()
        assert cfg.enabled is True

    def test_default_severity_threshold_is_warning(self):
        cfg = Config()
        assert cfg.severity_threshold == "warning"

    def test_default_diff_mode_is_full(self):
        cfg = Config()
        assert cfg.diff_mode == "full"

    def test_default_max_file_size_is_500(self):
        cfg = Config()
        assert cfg.max_file_size == 500

    def test_default_cache_ttl_is_1d(self):
        cfg = Config()
        assert cfg.cache_ttl == "1d"

    def test_default_log_ttl_is_1h(self):
        cfg = Config()
        assert cfg.log_ttl == "1h"

    def test_default_include_patterns_is_wildcard(self):
        cfg = Config()
        assert cfg.include_patterns == ["*"]

    def test_default_timeout_is_60(self):
        cfg = Config()
        assert cfg.timeout == 60

    def test_default_max_tokens_is_4096(self):
        cfg = Config()
        assert cfg.max_tokens == 4096

    def test_default_proxy_is_none(self):
        cfg = Config()
        assert cfg.proxy is None

    def test_default_ignore_patterns_is_non_empty_list(self):
        cfg = Config()
        assert len(cfg.ignore_patterns) > 0
        assert "*.md" in cfg.ignore_patterns


# ---------------------------------------------------------------------------
# 2. Config.__post_init__ validation
# ---------------------------------------------------------------------------

class TestConfigPostInit:
    """Verify __post_init__ normalisation and guard-rails."""

    # -- severity_threshold --

    def test_valid_severity_thresholds_preserved(self):
        for valid in ["info", "warning", "error", "critical"]:
            cfg = Config(severity_threshold=valid)
            assert cfg.severity_threshold == valid

    def test_invalid_severity_threshold_fallback_to_warning(self):
        cfg = Config(severity_threshold="invalid")
        assert cfg.severity_threshold == "warning"

    def test_empty_severity_threshold_fallback_to_warning(self):
        cfg = Config(severity_threshold="")
        assert cfg.severity_threshold == "warning"

    # -- diff_mode --

    def test_valid_diff_modes_preserved(self):
        for valid in ["full", "diff"]:
            cfg = Config(diff_mode=valid)
            assert cfg.diff_mode == valid

    def test_invalid_diff_mode_fallback_to_full(self):
        cfg = Config(diff_mode="invalid")
        assert cfg.diff_mode == "full"

    # -- max_file_size --

    def test_positive_max_file_size_preserved(self):
        cfg = Config(max_file_size=1024)
        assert cfg.max_file_size == 1024

    def test_zero_max_file_size_allowed(self):
        """0 is a legal value (caller handles it)."""
        cfg = Config(max_file_size=0)
        assert cfg.max_file_size == 0

    def test_negative_max_file_size_fallback_to_500(self):
        cfg = Config(max_file_size=-1)
        assert cfg.max_file_size == 500

    def test_max_file_size_type_error_fallback_to_500(self):
        cfg = Config(max_file_size="bad")
        assert cfg.max_file_size == 500

    # -- timeout --

    def test_positive_timeout_preserved(self):
        cfg = Config(timeout=120)
        assert cfg.timeout == 120

    def test_zero_timeout_allowed(self):
        """0 means 'no timeout'."""
        cfg = Config(timeout=0)
        assert cfg.timeout == 0

    def test_negative_timeout_fallback_to_60(self):
        cfg = Config(timeout=-5)
        assert cfg.timeout == 60

    def test_timeout_type_error_fallback_to_60(self):
        cfg = Config(timeout="bad")
        assert cfg.timeout == 60

    # -- max_tokens --

    def test_positive_max_tokens_preserved(self):
        cfg = Config(max_tokens=8192)
        assert cfg.max_tokens == 8192

    def test_zero_max_tokens_allowed(self):
        cfg = Config(max_tokens=0)
        assert cfg.max_tokens == 0

    def test_negative_max_tokens_fallback_to_4096(self):
        cfg = Config(max_tokens=-100)
        assert cfg.max_tokens == 4096

    def test_max_tokens_type_error_fallback_to_4096(self):
        cfg = Config(max_tokens="bad")
        assert cfg.max_tokens == 4096

    def test_max_tokens_above_131072_clamped_to_131072(self):
        """Max allowed is 128K (131072)."""
        cfg = Config(max_tokens=200000)
        assert cfg.max_tokens == 131072

    def test_max_tokens_exactly_at_131072_boundary(self):
        cfg = Config(max_tokens=131072)
        assert cfg.max_tokens == 131072

    def test_max_tokens_just_above_boundary_clamped(self):
        cfg = Config(max_tokens=131073)
        assert cfg.max_tokens == 131072


# ---------------------------------------------------------------------------
# 3. Config.merge()
# ---------------------------------------------------------------------------

class TestConfigMerge:
    """Verify merge semantics: other overrides self for non-empty values."""

    def test_merge_overrides_string_field(self, empty_config):
        other = Config(api_key="new-key")
        merged = empty_config.merge(other)
        assert merged.api_key == "new-key"

    def test_merge_preserves_untouched_fields(self, empty_config):
        other = Config(api_key="new-key")
        merged = empty_config.merge(other)
        assert merged.model == "gpt-4o-mini"
        assert merged.timeout == 60

    def test_merge_overrides_bool_false(self):
        base = Config(enabled=True)
        other = Config(enabled=False)
        merged = base.merge(other)
        assert merged.enabled is False

    def test_merge_overrides_int_to_zero(self):
        """0 is a valid value and must override the default."""
        base = Config(timeout=60)
        other = Config(timeout=0)
        merged = base.merge(other)
        assert merged.timeout == 0

    def test_merge_overrides_int_positive(self):
        base = Config(timeout=60)
        other = Config(timeout=120)
        merged = base.merge(other)
        assert merged.timeout == 120

    def test_merge_empty_string_in_other_does_not_override(self):
        base = Config(api_key="existing-key")
        other = Config(api_key="")
        merged = base.merge(other)
        assert merged.api_key == "existing-key"

    def test_merge_none_in_other_does_not_override(self):
        base = Config(proxy="http://proxy:8080")
        other = Config(proxy=None)
        merged = base.merge(other)
        assert merged.proxy == "http://proxy:8080"

    def test_merge_empty_list_in_other_does_not_override(self):
        base = Config(include_patterns=["*.py", "*.js"])
        other = Config(include_patterns=[])
        merged = base.merge(other)
        assert merged.include_patterns == ["*.py", "*.js"]

    def test_merge_non_empty_list_overrides(self):
        base = Config(include_patterns=["*"])
        other = Config(include_patterns=["*.py"])
        merged = base.merge(other)
        assert merged.include_patterns == ["*.py"]

    def test_merge_returns_new_instance(self, empty_config):
        other = Config(api_key="new-key")
        merged = empty_config.merge(other)
        assert merged is not empty_config
        assert merged is not other

    def test_merge_all_fields_simultaneously(self, config_with_custom_values):
        base = Config()
        merged = base.merge(config_with_custom_values)
        assert merged.api_key == "my-key"
        assert merged.api_base == "https://custom.api.com/v1"
        assert merged.model == "gpt-4"
        assert merged.language == "en"
        assert merged.enabled is False
        assert merged.severity_threshold == "error"
        assert merged.diff_mode == "diff"
        assert merged.max_file_size == 1000
        assert merged.cache_ttl == "12h"
        assert merged.log_ttl == "30m"
        assert merged.include_patterns == ["*.py"]
        assert merged.ignore_patterns == ["*.pyc"]
        assert merged.timeout == 30
        assert merged.max_tokens == 8192
        assert merged.proxy == "http://proxy:8080"


# ---------------------------------------------------------------------------
# 4. _parse_token_size()
# ---------------------------------------------------------------------------

class TestParseTokenSize:
    """Verify _parse_token_size handles various input formats."""

    def test_none_returns_zero(self):
        assert _parse_token_size(None) == 0

    def test_empty_string_returns_zero(self):
        assert _parse_token_size("") == 0

    def test_whitespace_string_returns_zero(self):
        assert _parse_token_size("   ") == 0

    # -- integer inputs --

    def test_plain_integer_preserved(self):
        assert _parse_token_size(4096) == 4096

    def test_plain_integer_string_preserved(self):
        assert _parse_token_size("4096") == 4096

    def test_float_converted_to_int(self):
        assert _parse_token_size(4096.7) == 4096

    # -- K suffix (case-insensitive) --

    def test_uppercase_4k(self):
        assert _parse_token_size("4K") == 4096

    def test_lowercase_8k(self):
        assert _parse_token_size("8k") == 8192

    def test_lowercase_16k(self):
        assert _parse_token_size("16k") == 16384

    def test_lowercase_64k(self):
        assert _parse_token_size("64k") == 65536

    def test_lowercase_128k(self):
        assert _parse_token_size("128k") == 131072

    def test_decimal_1_point_5k(self):
        assert _parse_token_size("1.5k") == 1536

    def test_decimal_2_point_0k(self):
        assert _parse_token_size("2.0k") == 2048

    # -- malformed inputs --

    def test_gibberish_returns_zero(self):
        assert _parse_token_size("not-a-number") == 0

    def test_k_without_number_returns_zero(self):
        assert _parse_token_size("k") == 0

    def test_special_characters_returns_zero(self):
        assert _parse_token_size("4@K") == 0

    def test_m_suffix_unsupported_returns_int_or_zero(self):
        """Only 'k' suffix is supported; others fall back."""
        result = _parse_token_size("4m")
        assert result == 0


# ---------------------------------------------------------------------------
# 5. ConfigManager._load_single()
# ---------------------------------------------------------------------------

class TestConfigManagerLoadSingle:
    """Verify _load_single handles valid files, missing files, and bad data."""

    def test_load_valid_config_file(self, temp_dir):
        config_path = temp_dir / "config.yaml"
        data = {
            "api_key": "file-key",
            "model": "gpt-4",
            "timeout": 120,
        }
        config_path.write_text(yaml.dump(data), encoding="utf-8")

        mgr = ConfigManager(config_path=str(config_path))
        cfg = mgr._load_single(config_path)

        assert cfg is not None
        assert cfg.api_key == "file-key"
        assert cfg.model == "gpt-4"
        assert cfg.timeout == 120
        # Fields not present in file keep their defaults
        assert cfg.max_file_size == 500

    def test_load_missing_file_returns_none(self, temp_dir):
        missing_path = temp_dir / "nonexistent.yaml"
        mgr = ConfigManager(config_path=str(temp_dir / "dummy.yaml"))
        cfg = mgr._load_single(missing_path)
        assert cfg is None

    def test_load_invalid_yaml_returns_none(self, temp_dir):
        config_path = temp_dir / "bad.yaml"
        config_path.write_text("{ invalid yaml: [", encoding="utf-8")

        mgr = ConfigManager(config_path=str(config_path))
        cfg = mgr._load_single(config_path)
        assert cfg is None

    def test_load_empty_yaml_returns_default_config(self, temp_dir):
        """Empty file → yaml.safe_load returns None → treated as {}."""
        config_path = temp_dir / "empty.yaml"
        config_path.write_text("", encoding="utf-8")

        mgr = ConfigManager(config_path=str(config_path))
        cfg = mgr._load_single(config_path)
        assert cfg is not None
        assert cfg.api_key == ""
        assert cfg.model == "gpt-4o-mini"

    def test_load_ignores_invalid_fields(self, temp_dir):
        """Fields not defined in Config dataclass are silently dropped."""
        config_path = temp_dir / "config.yaml"
        data = {
            "api_key": "key",
            "unknown_field": "should_be_ignored",
            "another_bad": 123,
        }
        config_path.write_text(yaml.dump(data), encoding="utf-8")

        mgr = ConfigManager(config_path=str(config_path))
        cfg = mgr._load_single(config_path)
        assert cfg is not None
        assert cfg.api_key == "key"
        valid_field_names = {f.name for f in fields(Config)}
        assert "unknown_field" not in valid_field_names

    def test_load_parses_max_tokens_string_with_k_suffix(self, temp_dir):
        config_path = temp_dir / "config.yaml"
        config_path.write_text(yaml.dump({"max_tokens": "8k"}), encoding="utf-8")

        mgr = ConfigManager(config_path=str(config_path))
        cfg = mgr._load_single(config_path)
        assert cfg is not None
        assert cfg.max_tokens == 8192

    def test_load_parses_max_tokens_as_integer(self, temp_dir):
        config_path = temp_dir / "config.yaml"
        config_path.write_text(yaml.dump({"max_tokens": 2048}), encoding="utf-8")

        mgr = ConfigManager(config_path=str(config_path))
        cfg = mgr._load_single(config_path)
        assert cfg is not None
        assert cfg.max_tokens == 2048
