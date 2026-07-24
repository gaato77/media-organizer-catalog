from pathlib import Path

import pytest

from media_catalog_builder.config import CatalogConfig


CONFIG_PATH = Path(__file__).parents[1] / "config" / "catalog.toml"


def test_config_preserves_hard_limits():
    config = CatalogConfig.load(CONFIG_PATH)
    assert config.schema_version == 1
    assert config.languages == ("en", "es")
    assert config.max_names_per_work == 4
    assert config.max_compressed_mib == 100
    assert config.max_installed_mib == 250


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "schema_version must be 1"),
        ("max_names_per_work", 5, "max_names_per_work cannot exceed 4"),
        ("max_compressed_mib", 101, "max_compressed_mib cannot exceed 100"),
        ("max_installed_mib", 251, "max_installed_mib cannot exceed 250"),
    ],
)
def test_config_rejects_values_above_approved_limits(tmp_path, field, value, message):
    text = CONFIG_PATH.read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith(f"{field} ="):
            lines.append(f"{field} = {value}")
        else:
            lines.append(line)
    candidate = tmp_path / "catalog.toml"
    candidate.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        CatalogConfig.load(candidate)
