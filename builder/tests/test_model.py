import pytest

from media_catalog_builder.model import CatalogRecord, MediaType


def test_record_rejects_five_names():
    with pytest.raises(ValueError, match="at most 4"):
        CatalogRecord(1, MediaType.MOVIE, 2000, "Example", ("a", "b", "c", "d", "e"))


def test_record_rejects_duplicate_names():
    with pytest.raises(ValueError, match="unique"):
        CatalogRecord(1, MediaType.MOVIE, 2000, "Example", ("example", "example"))


def test_record_requires_positive_qid():
    with pytest.raises(ValueError, match="positive"):
        CatalogRecord(0, MediaType.MOVIE, 2000, "Example", ("example",))


def test_record_requires_supported_year():
    with pytest.raises(ValueError, match="supported range"):
        CatalogRecord(1, MediaType.MOVIE, 1700, "Example", ("example",))


def test_record_requires_canonical_title():
    with pytest.raises(ValueError, match="required"):
        CatalogRecord(1, MediaType.MOVIE, 2000, "   ", ("example",))


def test_record_requires_at_least_one_name():
    with pytest.raises(ValueError, match="at least 1"):
        CatalogRecord(1, MediaType.MOVIE, 2000, "Example", ())
