import os
import sys
import tempfile
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import soundfile as sf
import torch

# Нарезка живёт в chunking.py: он не тянет torch, поэтому тесты гоняют его без GPU.
from chunking import (
    MAX_CHUNK_CHARS,
    MIN_GLUE_CHARS,
    prepare_chunks,
    split_into_sentences,
    split_long_chunks,
)
from textio import InputError, read_text_file

# ===================== НАСТРОЙКИ =====================
voice = os.environ.get("SILERO_VOICE", "aidar")  # aidar, baya, kseniya, xenia, eugene
input_file = os.environ.get("SILERO_INPUT", "silero_input.txt")
output_dir = os.environ.get("SILERO_OUTPUT_DIR", "silero_output")
language = "ru"
sample_rate = 48000
# Пустая SILERO_DEVICE — cuda, если она есть, иначе cpu.
device = os.environ.get("SILERO_DEVICE") or (
    "cuda" if torch.cuda.is_available() else "cpu"
)

# Запас по громкости (headroom), dBFS. Пик волновой формы подтягивается к этому
# уровню: Silero пишет впритык к 0 dBFS, и в PCM_16 такие сэмплы дают клиппинг
# (D12). Значение ниже нуля работает в обе стороны: громкий фрагмент приглушается
# до цели, тихий усиливается до неё же. 0 отключает правку; положительное значение
# выше 0 dBFS физически невозможно и тоже отключает её. Читается из
# SILERO_HEADROOM_DB — у play.sh своего значения нет, он передаёт окружение как есть.
HEADROOM_DB = float(os.environ.get("SILERO_HEADROOM_DB", "-1"))

# Порог «это уже клиппинг»: 0.999 по модулю — ровно то, что считал аудит (D12).
CLIPPING_LEVEL = 0.999


def normalize_peak(audio, headroom_db=HEADROOM_DB):
    """Подтянуть пик к `headroom_db` одним коэффициентом по всему фрагменту.

    Правка симметрична: громкий приглушается до цели, тихий усиливается до неё же.
    Коэффициент один на весь фрагмент, поэтому тембр, длительность и темп речи не
    меняются (темп задаёт SSML, не здесь). Нулевой пик — тишина — возвращается как
    есть: усиливать нечего, а деление на ноль превратило бы паузу в шум.

    Тип волны сохраняется: `apply_tts` отдаёт torch.Tensor, и soundfile понимает
    его напрямую, поэтому тензор не сворачиваем в ndarray.
    """
    limit = 10.0 ** (headroom_db / 20.0) if headroom_db else 0.0
    if limit <= 0.0 or limit >= 1.0:  # 0 и положительное значение — правка выключена
        return audio

    if hasattr(audio, "abs"):  # torch.Tensor: abs().max() вместо numpy-овского |·|
        peak = float(audio.abs().max())
    else:
        arr = np.asarray(audio)
        peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak <= 0.0:
        return audio

    gain = limit / peak
    if isinstance(audio, (np.ndarray, list, tuple)):
        # список/кортеж по элементу умножается только через numpy (тестовые заглушки)
        return np.asarray(audio, dtype="float32") * gain
    return audio * gain


# Скорость речи Silero SSML: ./play.sh N или python silero10.py N
RATES = {
    1: "x-slow",
    2: "slow",
    3: "medium",
    4: "fast",
    5: "x-fast",
}


def parse_rate(argv):
    if len(argv) < 2:
        return 3, RATES[3]
    try:
        n = int(argv[1])
    except ValueError:
        n = None
    if n not in RATES:
        print("Скорость: 1=x-slow 2=slow 3=medium 4=fast 5=x-fast", file=sys.stderr)
        sys.exit(1)
    if len(argv) > 2:
        print("Скорость: 1=x-slow 2=slow 3=medium 4=fast 5=x-fast", file=sys.stderr)
        sys.exit(1)
    return n, RATES[n]


def is_resume_enabled() -> bool:
    """`--resume` из `play.sh` доходит сюда как SILERO_RESUME=1."""
    return os.environ.get("SILERO_RESUME") == "1"


def save_atomic(writer, filepath, audio, sample_rate):
    """Запись WAV через временный файл в том же каталоге.

    Нужна для `--resume`: в staging уже могут лежать жёсткие ссылки на рабочие
    WAV. Прямая запись в такое имя писала бы поверх прежнего результата, а провал
    посередине оставил бы битый файл и там, и там. Временный файл лежит рядом,
    поэтому os.replace остаётся переименованием в пределах одного ФС.
    """
    directory = os.path.dirname(filepath) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".out_", suffix=".wav", dir=directory)
    os.close(fd)
    try:
        # Писать всегда во временный файл: подмена пути на финальный означала бы
        # запись поверх прежнего WAV, то есть ровно тот дефект, от которого эта
        # функция защищает. Тестовая заглушка смотрит на basename после os.replace.
        writer(tmp_path, audio, sample_rate)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def to_ssml(sentence: str, rate: str) -> str:
    return f'<speak><prosody rate="{rate}">{xml_escape(sentence)}</prosody></speak>'


# split_into_sentences, split_long_chunks, glue_short_sentences и prepare_chunks
# импортированы из chunking.py (там же MAX_CHUNK_CHARS и MIN_GLUE_CHARS).


def render_sentences(
    model,
    sentences,
    speech_rate,
    out_dir,
    sample_rate,
    voice,
    writer=None,
):
    """Пишет out_NNNN.wav. Возвращает (успехи, ошибки, секунды)."""
    if writer is None:
        writer = sf.write
    ok = 0
    errors = 0
    skipped = 0
    total = 0.0
    total_n = len(sentences)
    # SILERO_RESUME=1: файл с этим номером уже лежит в выходном каталоге — пропускаем.
    resume = is_resume_enabled()
    for idx, sentence in enumerate(sentences, start=1):
        if resume and os.path.exists(os.path.join(out_dir, f"out_{idx:04d}.wav")):
            skipped += 1
            continue
        preview = sentence[:120] + ("..." if len(sentence) > 120 else "")
        print(f"[{idx:02d}/{total_n}] Обработка: {preview}")
        try:
            audio = model.apply_tts(
                ssml_text=to_ssml(sentence, speech_rate),
                speaker=voice,
                sample_rate=sample_rate,
                put_accent=True,
                put_yo=True,
            )
            filename = f"out_{idx:04d}.wav"
            filepath = os.path.join(out_dir, filename)
            # длительность считаем по исходной волне: нормализация её не меняет,
            # а вот тип после numpy может быть уже другим
            dur = len(audio) / sample_rate
            save_atomic(writer, filepath, normalize_peak(audio), sample_rate)
            total += dur
            ok += 1
            print(f"   → Сохранено: {filename}  ({dur:.1f} сек)\n")
        except Exception as e:
            errors += 1
            print(f"   ОШИБКА на предложении {idx}: {e}\n", file=sys.stderr)
    if skipped:
        print(f"Пропущено готовых фрагментов: {skipped}")
    return ok, errors, total


def load_model():
    print("Загрузка модели Silero TTS...")
    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language=language,
        speaker="v5_6_ru",
        trust_repo=True,
        verbose=False,
    )
    model.to(device)
    # TTSModelMultiAcc_v3 — обёртка hub, не nn.Module: метода eval() нет.
    print(f"Модель загружена на {device.upper()}!")
    return model


def main(argv=None):
    argv = sys.argv if argv is None else argv
    rate_n, speech_rate = parse_rate(argv)
    # Ошибки входа — сообщение и exit 1 до создания каталога и до загрузки модели.
    try:
        text = read_text_file(input_file).strip()
    except InputError as e:
        print(str(e), file=sys.stderr)
        return 1
    os.makedirs(output_dir, exist_ok=True)
    print(f"Загружен текст длиной {len(text)} символов")
    sentences = prepare_chunks(text)
    print(f"Разбито на {len(sentences)} фрагментов\n")
    if not sentences:
        print("Готово: 0 файлов, 0 ошибок, суммарно 0.0 с")
        return 0
    model = load_model()
    print(f"Начинаю генерацию аудио голосом '{voice}', скорость {rate_n} ({speech_rate})...\n")
    with torch.no_grad():
        ok, errors, total = render_sentences(
            model, sentences, speech_rate, output_dir, sample_rate, voice
        )
    if is_resume_enabled():
        print("Режим --resume: готовые out_NNNN.wav не пересинтезированы")
    if HEADROOM_DB == 0:
        print("Headroom выключен (SILERO_HEADROOM_DB=0): пик пишется как есть")
    print(f"Готово: {ok} файлов, {errors} ошибок, суммарно {total:.1f} с")
    print(f"Каталог: ./{output_dir}/")
    if errors:
        print(
            f"Синтез с ошибками: {ok} файлов, {errors} ошибок",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
