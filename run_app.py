from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("TAX_ASSISTANT_HOST", "127.0.0.1")
    port = int(os.getenv("TAX_ASSISTANT_PORT", "8000"))
    reload = os.getenv("TAX_ASSISTANT_RELOAD", "1") not in {"0", "false", "False"}
    uvicorn.run("tax_assistant.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
