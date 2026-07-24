from media_catalog_builder.model import MediaType, SourceRecord
from media_catalog_builder.names import to_catalog_record


def test_latin_original_is_canonical():
    result = to_catalog_record(
        SourceRecord(1, MediaType.MOVIE, 2001, ("Amélie",), "Amelie", "Amélie")
    )
    assert result is not None
    assert result.canonical_title == "Amélie"
    assert result.names == ("amelie",)


def test_non_latin_original_uses_latin_source_label():
    result = to_catalog_record(
        SourceRecord(
            2,
            MediaType.MOVIE,
            2001,
            ("千と千尋の神隠し",),
            "Sen to Chihiro no Kamikakushi",
            "El viaje de Chihiro",
        )
    )
    assert result is not None
    assert result.canonical_title == "Sen to Chihiro no Kamikakushi"
    assert result.names == (
        "sen to chihiro no kamikakushi",
        "千と千尋の神隠し",
        "el viaje de chihiro",
    )


def test_non_latin_without_english_uses_spanish_latin_fallback():
    result = to_catalog_record(
        SourceRecord(3, MediaType.SERIES, 2020, ("테스트",), None, "Serie de prueba")
    )
    assert result is not None
    assert result.canonical_title == "Serie de prueba"


def test_record_without_usable_latin_output_is_rejected():
    result = to_catalog_record(
        SourceRecord(4, MediaType.MOVIE, 2020, ("千と千尋",), None, None)
    )
    assert result is None


def test_names_are_normalized_deduplicated_and_limited_to_four():
    result = to_catalog_record(
        SourceRecord(
            5,
            MediaType.MOVIE,
            2000,
            ("Example", "Example!", "Ejemplo nativo extra"),
            "Example",
            "Ejemplo",
        )
    )
    assert result is not None
    assert result.names == ("example", "ejemplo")
    assert len(result.names) <= 4
