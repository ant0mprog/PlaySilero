"""Нарезка текста на фрагменты для Silero TTS.

Модуль без torch и сети: тесты (`tests/test_normalize.py`) импортируют его
напрямую, не тянуть же ради `split_into_sentences` загрузку torch.
"""

import re

# Куски длиннее этого Silero v5_6_ru не осилит (падение около 1000 символов).
MAX_CHUNK_CHARS = 500
# Короче этого фрагмент склеивается с соседом, чтобы не получать WAV из одного слова.
MIN_GLUE_CHARS = 25

_OPEN_QUOTES = {"«": "»", "“": "”", "„": "“", '"': '"'}
# Символы, которыми кавычка может «закрыться» вместе с точкой: «...!» и т. п.
_AFTER_QUOTE = "\"»”)]"
# Конец предложения: .!? без пробела сразу за ними.
_SENTENCE_END_RE = re.compile(r"[.!?](?!\S)")


def _is_phrase_end(text, k):
    """k — позиция сразу за цепочкой .!? и кавычек — это конец предложения?"""
    return k >= len(text) or text[k].isspace()


def _skip_quotes(text, k):
    while k < len(text) and text[k] in _AFTER_QUOTE:
        k += 1
    return k


def _phrase_end_before(text, start, stop):
    """Есть ли конец предложения строго между start и stop.

    Конец предложения — .!? без пробела сразу за ними. Точка внутри цитаты
    (««что? да»») границей не считается: реплика остаётся единой.
    """
    pos = start
    while True:
        m = _SENTENCE_END_RE.search(text, pos)
        if m is None or m.end() >= stop:
            return False
        if _is_phrase_end(text, m.end()):
            return True
        pos = m.end()


def _quote_is_closed(text, i, closer):
    """Настоящая ли кавычка открыта в позиции i (а не опечатка).

    Режим «внутри реплики» включается, только если цитата закрывается корректно:

      * закрывающей кавычки нет вовсе («Он сказал «привет. Как дела.») — опечатка:
        режим склеил бы весь абзац, и `split_long_chunks` резал бы его по запятой
        где попало;
      * закрывающая кавычка прилипла к середине фразы (сразу за ней буква или
        цифра) — это не пара нашей кавычке, режим уехал бы через границу
        предложений.

    Перевод строки — граница абзаца (контракт `play.md`: silero10 режет по ним),
    поэтому цитата, закрывающаяся только в следующем абзаце, режим не включает:
    иначе следующий абзац приклеился бы к предыдущему и потерял свою озвучку.
    Разорванную опечаткой цитату всё равно слышно — зато соседний абзац цел.

    Корректно закрытая цитата («что? да», «Где ты был? Почему молчал?» — она)
    озвучивается одной репликой, как и раньше.
    """
    j = text.find(closer, i + 1)
    if j < 0:
        return False
    nl = text.find("\n", i)
    if 0 <= nl < j:
        return False
    k = _skip_quotes(text, j + 1)
    return k >= len(text) or text[k].isspace()


def split_into_sentences(text: str):
    """Режет по .!? и переводам строк. Внутри корректно закрытой кавычки не режет.

    Кавычка включает режим «внутри реплики» только если она настоящая (см.
    `_quote_is_closed`): иначе опечатка в одной кавычке склеивает весь абзац, и
    `split_long_chunks` режет его по запятой где попало.

    Символы кавычек после точки входят во фрагмент ровно один раз: раньше их
    добавляли в буфер и затем ещё раз прочитывали с позиции j, из-за чего в
    озвучку попадало «помещение?»?».
    """
    text = text.strip()
    if not text:
        return []
    chunks = []
    buf = []
    closer = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if closer is not None:
            buf.append(ch)
            if ch == closer:
                closer = None
            i += 1
            continue
        if ch in _OPEN_QUOTES and _quote_is_closed(text, i, _OPEN_QUOTES[ch]):
            closer = _OPEN_QUOTES[ch]
            buf.append(ch)
            i += 1
            continue
        if ch == "\n":
            # Абзац кончился — режим кавычки не переносим, иначе следующий абзац
            # приклеился бы к предыдущему и потерял свою озвучку.
            closer = None
            piece = "".join(buf).strip()
            if piece:
                chunks.append(piece)
            buf = []
            i += 1
            continue
        if ch in ".!?":
            # Символы кавычек после точки принадлежат этому фрагменту, но ровно
            # один раз: раньше их добавляли в буфер и затем ещё раз прочитывали с
            # позиции j — на выходе появлялось «помещение?»?».
            j = i + 1
            while j < n and text[j] in _AFTER_QUOTE:
                j += 1
            # «??!» — одна граница фразы, а не три: за цепочкой .!? тоже смотрим
            # на следующий символ, иначе «Франции??! А что» резалось по одному
            # знаку и озвучка получалась обрывками.
            while j < n and text[j] in ".!?":
                k = _skip_quotes(text, j + 1)
                if not _is_phrase_end(text, k):
                    break   # граница не подтверждена: j остаётся на месте, символы не теряются
                j = k
            if _is_phrase_end(text, j):
                buf.append(ch)
                buf.extend(text[i + 1 : j])
                piece = "".join(buf).strip()
                if piece:
                    chunks.append(piece)
                buf = []
                i = j
                while i < n and text[i] in " \t":
                    i += 1
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        chunks.append(tail)
    return chunks


def _split_long_one(text: str, limit: int, depth: int = 0):
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit or depth > 40:
        return [text]
    min_pos = max(20, limit // 3)
    cut = -1
    for sep in (";", ":", ",", " "):
        pos = text.rfind(sep, min_pos, limit + 1)
        if pos >= min_pos:
            cut = pos
            break
    if cut < 0:
        cut = text.rfind(" ", 0, limit + 1)
    if cut <= 0:
        left = text[:limit].strip()
        right = text[limit:].strip()
    else:
        if text[cut] in ";:":
            left = text[: cut + 1].strip()
        else:
            left = text[:cut].strip()
        right = text[cut + 1 :].strip()
    if not left or left == text:
        left = text[:limit].strip()
        right = text[limit:].strip()
    out = []
    if left:
        out.extend(_split_long_one(left, limit, depth + 1) if len(left) > limit else [left])
    if right:
        out.extend(_split_long_one(right, limit, depth + 1))
    return out


def split_long_chunks(sentences, limit: int = MAX_CHUNK_CHARS):
    out = []
    for sentence in sentences:
        out.extend(_split_long_one(sentence, limit))
    return out


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?", "…"))


def glue_short_sentences(sentences, min_len: int = MIN_GLUE_CHARS, max_len: int = MAX_CHUNK_CHARS):
    """Короткий фрагмент с точкой клеится к соседу.

    Фрагмент без .!? — заголовок: к следующему куску не клеится.
    """
    out = []
    buf = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if not buf:
            buf = sentence
            continue
        # Заголовок без .!? не склеивается ни с предыдущим, ни со следующим.
        if not _ends_sentence(buf) or not _ends_sentence(sentence):
            out.append(buf)
            buf = sentence
            continue
        if len(buf) < min_len or len(sentence) < min_len:
            merged = f"{buf} {sentence}".strip()
            if len(merged) <= max_len:
                buf = merged
                continue
        out.append(buf)
        buf = sentence
    if buf:
        out.append(buf)
    return out


def prepare_chunks(text: str):
    return split_long_chunks(glue_short_sentences(split_into_sentences(text)))
