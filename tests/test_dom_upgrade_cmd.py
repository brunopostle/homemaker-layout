"""`homemaker-dom-upgrade` (`homemaker-py-8b2u.3`): verified v1 <-> v2 conversion.

What the command promises is negative as much as positive: it never overwrites
its input, it never guesses a v1 file's convention, and it writes nothing it
could not verify.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from homemaker_layout import dom, dom_upgrade_cmd as cmd, dom_v2, geometry

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"
ARTEFACT = "coldstart-1a24b6a+orth-500000-s0.dom"

pytestmark = pytest.mark.skipif(not (PH / ARTEFACT).is_file(),
                                reason="corpus artefact absent")


@pytest.fixture
def work(tmp_path):
    shutil.copy(PH / ARTEFACT, tmp_path / ARTEFACT)
    return tmp_path


def test_help_renders(capsys):
    """Python 3.14 expands help strings when the option is defined (§39.82)."""
    with pytest.raises(SystemExit) as e:
        cmd.main(["--help"])
    assert e.value.code == 0
    assert "--to-v1" in capsys.readouterr().out


def test_upgrade_writes_a_verified_v2_beside_the_input(work, capsys):
    src = work / ARTEFACT
    before = src.read_bytes()
    assert cmd.main([str(src)]) == 0
    out = work / ARTEFACT.replace(".dom", ".v2.dom")
    doc = yaml.safe_load(out.read_text())
    assert (doc["format"], doc["version"]) == ("homemaker-dom", 2)
    assert doc["meta"]["converted_from"] == ARTEFACT
    assert src.read_bytes() == before                 # a record, not rewritten
    assert "verified" in capsys.readouterr().out
    assert geometry.ORTHOGONAL_DIVISION is False      # the switch is put back


def test_v2_back_to_v1_holds_the_same_cells(work, monkeypatch):
    src = work / ARTEFACT
    assert cmd.main([str(src)]) == 0
    v2 = work / ARTEFACT.replace(".dom", ".v2.dom")
    assert cmd.main(["--to-v1", str(v2)]) == 0
    v1 = work / ARTEFACT.replace(".dom", ".v1.dom")
    assert "format" not in yaml.safe_load(v1.read_text())
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    assert cmd.unmatched_cells(dom.load(str(src)), dom.load(str(v1))) == 0


def test_a_v1_file_that_does_not_say_is_refused(work, capsys):
    plain = work / "working.dom"
    shutil.copy(work / ARTEFACT, plain)
    assert cmd.main([str(plain)]) == 1
    assert "NOT WRITTEN" in capsys.readouterr().out
    assert not (work / "working.v2.dom").exists()
    assert cmd.main(["--orthogonal", str(plain)]) == 0
    assert (work / "working.v2.dom").exists()


def test_an_existing_output_is_not_replaced_without_force(work):
    src = work / ARTEFACT
    out = work / ARTEFACT.replace(".dom", ".v2.dom")
    out.write_text("mine\n")
    assert cmd.main([str(src)]) == 1
    assert out.read_text() == "mine\n"
    assert cmd.main(["--force", str(src)]) == 0
    assert out.read_text() != "mine\n"
    assert cmd.main(["-o", str(src), str(src)]) == 1      # never onto the input


def test_wrong_direction_is_refused(work):
    src = work / ARTEFACT
    assert cmd.main(["--to-v1", str(src)]) == 1            # it is already v1
    assert cmd.main([str(src)]) == 0
    v2 = work / ARTEFACT.replace(".dom", ".v2.dom")
    assert cmd.main([str(v2)]) == 1                        # it is already v2


def test_nothing_is_written_when_verification_fails(work, monkeypatch, capsys):
    """Negative control: a reader that builds a slightly different building
    must stop the write. Without this the 'verified' in the output is a word."""
    real = dom_v2.from_document

    def nudged(doc):
        doc["storeys"][0]["tree"]["at"] += 1e-3
        return real(doc)

    monkeypatch.setattr(dom_v2, "from_document", nudged)
    assert cmd.main([str(work / ARTEFACT)]) == 1
    assert "verification failed" in capsys.readouterr().out
    assert not (work / ARTEFACT.replace(".dom", ".v2.dom")).exists()
