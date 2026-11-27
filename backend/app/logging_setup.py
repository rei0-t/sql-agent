"""日志配置。

只给 `app` 这棵 logger 挂一个 handler，并关掉向上传播——
避免和 uvicorn 自己的 access log 重复打印。业务代码用
`logging.getLogger(__name__)` 即可，名字天然以 `app.` 开头。
"""

from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger("app")
    if logger.handlers:  # 幂等：重复导入不会叠加 handler
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False