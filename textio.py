"""Чтение входных файлов пайплайна с понятными ошибками вместо traceback.

Модуль без torch и без num2words — по той же причине, что и `chunking.py`:
тесты (`tests/test_normalize.py`) проверяют сообщения и коды возврата, не грузя
модель и не скачивая её из сети (ограничение 0.6 в `play-tasks.md`).

Правило поведения (T6/D7): отсутствующий файл и файл не в UTF-8 — это
`InputError`, который вызывающий превращает в одну строку в stderr и `exit 1`.
Пустой файл — не ошибка: `read_text_file` вернёт `""`, а предупреждение
«Пустой вход» печатает вызывающий (`txtproc.py`).
"""

from __future__ import annotations

import codecs

# BOM допустим: txtproc пишет выход без BOM, идемпотентность это не ломает.
ENCODING = "utf-8-sig"


class InputError(Exception):
    """Входной файл недоступен или не читается как UTF-8."""


def read_text_file(path: str) -> str:
    """Содержимое `path` как текст. Ошибки — `InputError` с готовым сообщением."""
    try:
        with open(path, "r", encoding=ENCODING) as f:
            return f.read()
    except FileNotFoundError:
        raise InputError(f"Нет входного файла: {path}") from None
    except IsADirectoryError:
        raise InputError(f"Это каталог, а не текстовый файл: {path}") from None
    except PermissionError:
        raise InputError(f"Нет доступа к файлу: {path}") from None
    except OSError as e:
        raise InputError(f"Не удалось прочитать {path}: {e.strerror or e}") from None
    except UnicodeDecodeError as e:
        raise InputError(describe_decode_error(path, e)) from None


def describe_decode_error(path: str, e: UnicodeDecodeError) -> str:
    """Сообщение про кодировку: байт из файла, позиция и подсказка про iconv.

    Отдельная функция, чтобы текст сообщения был общим у `txtproc.py` и
    `silero10.py` и его можно было проверить без torch. Байт берётся по
    `e.start`: при ошибке в начале последовательности (`\xff\xfe`) `e.object`
    доступен целиком, но обрезан при ошибке в конце файла.
    """
    byte = e.object[e.start] if e.start < len(e.object) else 0
    line = e.object.count(b"\n", 0, e.start) + 1
    hint = (
        "похоже на UTF-16 (BOM в начале файла), нужен UTF-8"
        if looks_like_utf16(bytes(e.object[:4]))
        else f"нужен UTF-8, например: iconv -f WINDOWS-1251 -t UTF-8 {path}"
    )
    return (
        f"Файл {path} не в UTF-8: байт {byte:02x} в позиции {e.start}, "
        f"строка {line}; {hint}"
    )


def looks_like_utf16(data: bytes) -> bool:
    """True, если файл похож на UTF-16 с BOM — частая причина не-UTF-8 входа."""
    return data.startswith(
        (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE, codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)
    )
