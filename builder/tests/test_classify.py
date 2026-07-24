from media_catalog_builder.classify import binding_to_source, parse_qid
from media_catalog_builder.model import MediaType


def _value(value: str) -> dict[str, str]:
    return {"type": "literal", "value": value}


def test_parse_qid_accepts_wikidata_item_uri():
    assert parse_qid("http://www.wikidata.org/entity/Q12345") == 12345


def test_parse_qid_rejects_non_item_uri():
    assert parse_qid("http://www.wikidata.org/entity/P31") is None


def test_binding_to_source_reads_grouped_titles_and_year():
    binding = {
        "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q42"},
        "releaseDate": _value("2001-07-20T00:00:00Z"),
        "originals": _value("Original\u001fTítulo original"),
        "enLabel": _value("English title"),
        "esLabel": _value("Título español"),
        "modified": _value("2026-07-24T12:00:00Z"),
    }

    record = binding_to_source(binding, MediaType.MOVIE)

    assert record is not None
    assert record.qid == 42
    assert record.year == 2001
    assert record.original_titles == ("Original", "Título original")
    assert record.english_label == "English title"
    assert record.spanish_label == "Título español"
    assert record.modified_at == "2026-07-24T12:00:00Z"


def test_binding_to_source_rejects_missing_or_invalid_year():
    missing = {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q42"}}
    invalid = {
        **missing,
        "releaseDate": _value("not-a-date"),
    }

    assert binding_to_source(missing, MediaType.SERIES) is None
    assert binding_to_source(invalid, MediaType.SERIES) is None
