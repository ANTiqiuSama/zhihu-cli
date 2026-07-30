from zhihu_cli import main as main_module


class _FakeStream:
    def __init__(self) -> None:
        self.errors = None

    def reconfigure(self, *, errors: str) -> None:
        self.errors = errors


def test_standard_streams_replace_unencodable_characters(monkeypatch):
    stdout = _FakeStream()
    stderr = _FakeStream()
    monkeypatch.setattr(main_module.sys, "stdout", stdout)
    monkeypatch.setattr(main_module.sys, "stderr", stderr)

    main_module._configure_standard_streams()

    assert stdout.errors == "replace"
    assert stderr.errors == "replace"
