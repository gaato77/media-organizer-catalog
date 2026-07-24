from media_catalog_builder.cli import _coerce_exit_code, main


def test_cli_requires_command(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err.lower()


def test_cli_rejects_unknown_command(capsys):
    assert main(["unknown"]) == 2
    assert "invalid choice" in capsys.readouterr().err.lower()


def test_exit_code_preserves_integer_status():
    assert _coerce_exit_code(2) == 2


def test_exit_code_treats_none_as_success():
    assert _coerce_exit_code(None) == 0


def test_exit_code_treats_string_message_as_failure():
    assert _coerce_exit_code("failure message") == 1
