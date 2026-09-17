import multiprocessing
import sys

from lieferschein_suche.__main__ import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--self-test" in sys.argv:
        from lieferschein_suche.selftest import run_self_test

        raise SystemExit(run_self_test())
    raise SystemExit(main())
