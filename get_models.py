"""Download every AI model UbiClipper uses, once, during setup.

run_windows.bat runs this before the first start so nothing big downloads in
the middle of your first analysis. Safe to run again: finished models are
skipped and an interrupted download continues where it stopped.

    python get_models.py            # everything (about 6 GB the first time)
    python get_models.py --no-judge # skip the 4 GB AI judge
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def line(msg: str) -> None:
    sys.stdout.write("\r" + msg[:100].ljust(100))
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--whisper", default="large-v3-turbo")
    a = ap.parse_args()
    failed = []

    print("UbiClipper: downloading AI models (one time).\n")

    print("1/4  Speech to text (Whisper, ~1.6 GB)")
    try:
        from clipper.transcribe import import_whisper
        import_whisper()
        from faster_whisper.utils import download_model
        download_model(a.whisper)
        print("     ready")
    except Exception as e:
        failed.append("Whisper")
        print(f"     skipped: {e}\n     (it downloads on the first export instead)")

    print("2/4  Listening AI (48 MB)")
    try:
        from clipper import listen
        listen.model_files(line)
        print("\r     ready".ljust(100))
    except Exception as e:
        failed.append("listening AI")
        print(f"\r     skipped: {e}")

    print("3/4  Voice model for speaker colours (26 MB)")
    try:
        from clipper import speakers
        speakers.model_path(report=lambda m, f: line("     " + m))
        print("\r     ready".ljust(100))
    except Exception as e:
        failed.append("voice model")
        print(f"\r     skipped: {e}")

    if a.no_judge:
        print("4/4  AI judge: skipped (--no-judge)")
    else:
        print("4/4  AI judge (~4 GB, the big one: grab a drink)")
        try:
            from clipper import judge
            judge.download(lambda m: line("     " + m))
            print("\r     ready".ljust(100))
        except Exception as e:
            failed.append("AI judge")
            print(f"\r     skipped: {e}\n     (it resumes on the next start)")

    print()
    if failed:
        print("Not downloaded yet: " + ", ".join(failed) + ". UbiClipper still starts; "
              "these download when first needed.")
        return 1
    print("All models ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
