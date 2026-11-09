"""The cli.run(main) shim: executes when FreeCAD runs the file, silent on import."""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "freecad-3dprint", "kit", "fcp")
sys.path.insert(0, KIT)

import cli  # noqa: E402

CALLED = []


def _main():
    CALLED.append(1)


class _FakeFrame:
    def __init__(self, name):
        self.frame = type("F", (), {"f_globals": {"__name__": name}})()


def test_should_run_true_for_main_under_any_stack():
    assert cli.should_run("__main__", []) is True


def test_should_run_false_when_a_main_frame_is_on_the_stack():
    assert cli.should_run("gate", []) is True                     # FreeCAD entry: no __main__
    assert cli.should_run("gate", [_FakeFrame("__main__")]) is False  # imported by a program


def test_run_passes_module_name_through(monkeypatch):
    monkeypatch.delenv("FCP_NO_MAIN", raising=False)
    CALLED.clear()
    cli.run(_main, module_name="__main__", _stack=[])
    assert CALLED == [1]
    CALLED.clear()
    cli.run(_main, module_name="gate", _stack=[])
    assert CALLED == [1]
    CALLED.clear()
    cli.run(_main, module_name="gate", _stack=[_FakeFrame("__main__")])
    assert CALLED == []


def _freecad_exe():
    """FreeCADCmd.exe, from the env, PATH, or the standard install location."""
    import glob
    import shutil
    return (os.environ.get("FREECAD_CMD")
            or shutil.which("FreeCADCmd") or shutil.which("freecadcmd")
            or next(iter(sorted(glob.glob(r"C:\Program Files\FreeCAD*\bin\FreeCADCmd.exe"))), "")
            or "")


def test_freecadcmd_really_runs_the_script_and_python_does_not_on_import(tmp_path):
    """Pins all four cases the predicate must separate, on a machine with FreeCAD."""
    exe = _freecad_exe()
    if not exe:
        pytest.skip("freecadcmd not installed")
    (tmp_path / "victim.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, %r)\n"
        "import cli\n"
        "def main(): print('MAIN_RAN')\n"
        "cli.run(main, module_name=__name__)\n" % KIT)
    (tmp_path / "importer.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, %r)\n"
        "import victim\n"
        "print('IMPORT_DONE')\n" % tmp_path.as_posix())
    env = {k: v for k, v in os.environ.items() if k != "FCP_NO_MAIN"}

    out = subprocess.run([exe, str(tmp_path / "victim.py")],
                         capture_output=True, text=True, timeout=180, env=env)
    assert "MAIN_RAN" in (out.stdout + out.stderr)          # FreeCAD entry point runs

    out = subprocess.run([sys.executable, str(tmp_path / "victim.py")],
                         capture_output=True, text=True, timeout=180, env=env)
    assert "MAIN_RAN" in out.stdout                          # python script.py runs

    out = subprocess.run([sys.executable, str(tmp_path / "importer.py")],
                         capture_output=True, text=True, timeout=180, env=env)
    assert "IMPORT_DONE" in out.stdout
    assert "MAIN_RAN" not in out.stdout                      # an import stays silent

    env["FCP_NO_MAIN"] = "1"
    out = subprocess.run([exe, str(tmp_path / "victim.py")],
                         capture_output=True, text=True, timeout=180, env=env)
    assert "MAIN_RAN" not in (out.stdout + out.stderr)       # override wins


def test_run_calls_main_when_freecad_executes_the_file(monkeypatch):
    monkeypatch.setattr(cli, "main_calls", lambda *a, **k: True)
    monkeypatch.delenv("FCP_NO_MAIN", raising=False)
    CALLED.clear()
    cli.run(_main)
    assert CALLED == [1]


def test_run_is_silent_on_import(monkeypatch):
    monkeypatch.setattr(cli, "main_calls", lambda *a, **k: False)
    monkeypatch.delenv("FCP_NO_MAIN", raising=False)
    CALLED.clear()
    cli.run(_main)
    assert CALLED == []


def test_fcp_no_main_wins_over_everything(monkeypatch):
    monkeypatch.setenv("FCP_NO_MAIN", "1")
    CALLED.clear()
    cli.run(_main, module_name="__main__", _stack=[])
    assert CALLED == []


def test_importing_gate_has_no_side_effects_without_fcp_no_main(tmp_path):
    """The exact regression: importing a pass-1 kit module must not run its main()."""
    env = {k: v for k, v in os.environ.items() if k != "FCP_NO_MAIN"}
    env["FCP_PROJECT"] = str(tmp_path)            # empty workspace: a run would write here
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import gate, status, release, slice, doctor" % KIT],
        env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert not (tmp_path / ".out").exists(), "importing a kit module wrote to FCP_PROJECT"


def test_render_views_import_runs_nothing(tmp_path):
    """The spike's bug: importing render_views re-rendered the real .out/views mid-run."""
    env = {k: v for k, v in os.environ.items() if k != "FCP_NO_MAIN"}
    env["FCP_PROJECT"] = str(tmp_path)
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import render_views, check_print" % KIT],
        env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert not (tmp_path / ".out").exists()


def test_check_print_module_helper_restores_the_previous_value(monkeypatch):
    sys.path.insert(0, KIT)
    import render_views
    monkeypatch.delenv("FCP_NO_MAIN", raising=False)
    render_views._check_print_module()
    assert "FCP_NO_MAIN" not in os.environ
    monkeypatch.setenv("FCP_NO_MAIN", "0")
    render_views._check_print_module()
    assert os.environ["FCP_NO_MAIN"] == "0"
