#!/usr/bin/env python
"""
RQ worker process.
Start with:  python worker_main.py
Or via Docker: CMD ["python", "worker_main.py"]
"""
import logging
import sys

import redis
from rq import Queue, Worker

from app.config import settings

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

if __name__ == "__main__":
    conn = redis.from_url(settings.REDIS_URL)
    q = Queue("orders", connection=conn)
    worker = Worker([q], connection=conn)
    logging.info("Worker started, listening on queue 'orders'")
    worker.work(with_scheduler=False)
