import multiprocessing

# PyInstaller worker processes must be diverted before importing Qt or other
# heavy modules; otherwise Windows can enter a recursive spawn loop.
if __name__ == "__main__":
    multiprocessing.freeze_support()

if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        from lieferschein_suche.selftest import run_self_test

        raise SystemExit(run_self_test())
    from lieferschein_suche.__main__ import main

    raise SystemExit(main())
