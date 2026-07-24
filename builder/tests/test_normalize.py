from media_catalog_builder.normalize import is_latin_output_candidate, normalize_lookup


def test_normalization_removes_accents_and_punctuation():
    assert normalize_lookup("Amélie: Le Fabuleux Destin") == "amelie le fabuleux destin"


def test_normalization_expands_ampersand_and_collapses_spaces():
    assert normalize_lookup("  Law  &  Order  ") == "law and order"


def test_normalization_keeps_non_latin_letters_for_lookup():
    assert normalize_lookup("千と千尋の神隠し") == "千と千尋の神隠し"


def test_latin_candidate_accepts_accented_latin_title():
    assert is_latin_output_candidate("Amélie") is True


def test_latin_candidate_rejects_native_japanese_title():
    assert is_latin_output_candidate("千と千尋の神隠し") is False
