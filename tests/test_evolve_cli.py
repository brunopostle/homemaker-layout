"""CLI argument wiring for homemaker-evolve (homemaker-py-x3b)."""

from pathlib import Path

from homemaker_layout.evolve import _parse_args


def test_leaf_sharing_defaults_on():
    args = _parse_args(["seed.dom"])
    assert args.leaf_sharing is True
    assert args.leaf_share_factor == 3
    assert args.seed_dom == Path("seed.dom")


def test_no_leaf_sharing_flag():
    args = _parse_args(["seed.dom", "--no-leaf-sharing"])
    assert args.leaf_sharing is False


def test_leaf_share_factor_opt_in_mode():
    args = _parse_args(["seed.dom", "--leaf-share-factor", "0"])
    assert args.leaf_share_factor == 0
    assert args.leaf_sharing is True


def test_leaf_sharing_env_default(monkeypatch):
    monkeypatch.setenv("HOMEMAKER_LEAF_SHARING", "0")
    monkeypatch.setenv("HOMEMAKER_LEAF_SHARE_FACTOR", "5")
    args = _parse_args(["seed.dom"])
    assert args.leaf_sharing is False
    assert args.leaf_share_factor == 5
    # explicit flag still wins over the env default
    assert _parse_args(["seed.dom", "--leaf-sharing"]).leaf_sharing is True


def test_help_renders(capsys):
    """Every help string must survive argparse's %-formatting.

    Python 3.14 checks this at add_argument time, so a bare ``%`` in a help
    string made ``_parse_args`` raise on EVERY call and homemaker-evolve could
    not start at all; older Pythons only fail on ``--help``. Asking for
    ``--help`` catches it on any version.
    """
    import pytest
    with pytest.raises(SystemExit) as exc:
        _parse_args(["--help"])
    assert exc.value.code == 0
    assert "6-14% of draws" in capsys.readouterr().out
