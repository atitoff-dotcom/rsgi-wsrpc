# -*- coding: utf-8 -*-
"""
Генератор 64-битных уникальных идентификаторов сессий (Snowflake-style).
Гарантирует отсутствие коллизий между несколькими воркерами Granian и после перезапусков.
"""

import os
import time
from itertools import count

# 10 бит на ID воркера (до 1024 воркеров / PID)
_WORKER_ID = os.getpid() & 0x3FF
# Циклический счетчик внутри текущей миллисекунды (12 бит, до 4096 соединений/мс на 1 воркер)
_COUNTER = count()


def generate_session_id() -> int:
    """
    Генерирует уникальный 64-битный целое число:
    - 42 бита: timestamp в миллисекундах (хватит более чем на 100 лет)
    - 10 бит: ID процесса воркера (_WORKER_ID)
    - 12 бит: инкрементальный счетчик (_COUNTER)
    """
    ts = int(time.time() * 1000) & 0x3FFFFFFFFFF
    seq = next(_COUNTER) & 0xFFF
    return (ts << 22) | (_WORKER_ID << 12) | seq
