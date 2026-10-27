# Entry point for PyInstaller.
import multiprocessing
import os
import sys

# The windowed exe has no console. Give stdout/stderr somewhere to go before anything (including the
# multiprocessing child that runs the speech model) tries to write to them.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if __name__ == "__main__":
    multiprocessing.freeze_support()  # the model process starts here and never returns
    from bensvoice.__main__ import main
    sys.exit(main())
