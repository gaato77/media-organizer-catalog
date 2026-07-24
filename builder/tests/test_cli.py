from media_catalog_builder.cli import main


def test_cli_requires_command(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err.lower()


def test_cli_rejects_unknown_command(capsys):
    assert main(["unknown"]) == 2
    assert "invalid choice" in capsys.readouterr().err.lower()
