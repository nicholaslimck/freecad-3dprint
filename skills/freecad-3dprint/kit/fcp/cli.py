"""Decide whether a kit script's main() should run.

FreeCADCmd does NOT set __name__ == "__main__": it imports the file, so
__name__ is the file stem ('fcp-maincheck') and the module has a normal
ModuleSpec. A user's build.py importing the same kit module also sees
__name__ != "__main__" and a ModuleSpec. So neither __name__ nor __spec__
can tell "FreeCAD ran this file" from "someone imported it".

The one signal that does separate them, measured on FreeCAD 1.1.4: when a
real program is running, a __main__ frame is on the stack; when FreeCAD has
loaded a script as its entry point, no __main__ frame exists at all.

Each script therefore passes its own __name__ in explicitly. Do NOT try to
recover the caller with sys._getframe inside this module: the immediate
caller of main_calls() is run(), whose globals are cli's, so a frame walk
here answers 'cli' every time.

FCP_NO_MAIN set (to anything, including "0", as today) is an absolute
"do not run".
"""
import inspect
import os


def should_run(module_name, stack):
    """True when `module_name` is the outermost code a program is executing."""
    if module_name == "__main__":
        return True                       # python script.py, python -c
    return not any(fr.frame.f_globals.get("__name__") == "__main__" for fr in stack)


def main_calls(module_name, _stack=None):
    """Whether the script that owns `module_name` should run its main().

    `module_name` is REQUIRED. There is no frame-walking fallback: `run` is
    always the immediate caller, so a fallback would inspect cli's own globals
    and answer with the calling script's module name only by luck. Omitting the
    argument must be a TypeError at import, never a silent re-run of main().
    """
    if os.environ.get("FCP_NO_MAIN"):
        return False
    return should_run(module_name, _stack if _stack is not None else inspect.stack())


def run(main, module_name, _stack=None):
    """Run `main` when this file is the entry point; do nothing when imported."""
    if main_calls(module_name, _stack):
        main()
