"""支持 ``python -m agentos`` 调用方式。"""

from agentos.cli import main

if __name__ == "__main__":
    raise SystemExit(main())