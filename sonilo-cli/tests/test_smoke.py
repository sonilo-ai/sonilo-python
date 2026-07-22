import pytest

import sonilo_cli
from sonilo_cli.__main__ import main


def test_version_is_a_string():
    assert isinstance(sonilo_cli.__version__, str)
    assert sonilo_cli.__version__.count(".") == 2


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert sonilo_cli.__version__ in capsys.readouterr().out
