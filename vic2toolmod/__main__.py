"""Allow ``python -m vic2toolmod``."""

from vic2toolmod.cli import main

if __name__ == "__main__":  # not when a helper process imports it
    raise SystemExit(main())
