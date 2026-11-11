#!/usr/bin/env python3
"""Регрессии normalize_text и нарезки. Модель, torch и сеть не нужны.

Нарезка импортируется из chunking.py — он без torch, поэтому раннер запускается
на машине без GPU и без скачанной модели (ограничение 0.6 в play-tasks.md).
silero10 остаётся источником render_sentences: проверка ошибок синтеза идёт
через заглушку, модель не грузится.
Громкость (T12) проверяется настоящей записью через soundfile: пик готового WAV не
должен упираться в 0 dBFS.
Запись WAV и `--resume` (T14) проверяются заглушкой модели: `render_sentences`
с SILERO_RESUME=1 и `save_atomic` — без torch.hub и без GPU.
Ошибки входа (T6) проверяются дважды: хелперами из textio.py и реальным запуском
`txtproc.py` / `silero10.py` как скриптов — сообщение и код возврата важнее,
чем исключение в вакууме.
"""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chunking import (  # noqa: E402
    MAX_CHUNK_CHARS,
    prepare_chunks,
    split_into_sentences,
)
from silero10 import (  # noqa: E402
    CLIPPING_LEVEL,
    HEADROOM_DB,
    is_resume_enabled,
    normalize_peak,
    render_sentences,
    save_atomic,
)
from textio import InputError, read_text_file  # noqa: E402
from txtproc import normalize_text  # noqa: E402


def load_cases(path: Path):
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        src, expected = line.split("\t", 1)
        cases.append((src, expected))
    return cases


def run_script(name, env_extra):
    """Запуск txtproc.py / silero10.py как скрипта: (rc, stdout, stderr)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **env_extra)
    proc = subprocess.run(
        [sys.executable, str(ROOT / name)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_input_errors(tmp: Path):
    """T6/D7: нет файла и не UTF-8 — сообщение в stderr и exit 1, без трейсбека.

    Выходы обоих скриптов перенаправлены в tmp: рабочие `silero_input.txt` и
    `silero_output/` трогать нельзя (ограничение 0.7 в play-tasks.md).
    """
    missing = tmp / "net-takogo-faila.txt"
    cp1251 = tmp / "cp1251.txt"
    cp1251.write_bytes("прайсор прайм".encode("cp1251"))
    utf16 = tmp / "utf16.txt"
    utf16.write_bytes("привет мир".encode("utf-16"))
    empty = tmp / "empty.txt"
    empty.write_text("", encoding="utf-8")

    # --- unit: текст сообщения доступен без torch ---
    for path, needle in ((str(missing), "Нет входного файла"), (str(cp1251), "не в UTF-8")):
        try:
            read_text_file(path)
        except InputError as e:
            assert needle in str(e), (path, str(e))
        else:  # pragma: no cover - сюда не доходим при живой ФС
            raise AssertionError(f"ожидался InputError для {path}")
    assert read_text_file(str(empty)) == "", "пустой файл — не ошибка чтения"

    # --- CLI txtproc.py ---
    out = tmp / "txtproc-out.txt"
    cases = (
        (str(missing), "нет файла", ("Нет входного файла",)),
        (str(cp1251), "не UTF-8", ("не в UTF-8", "iconv")),
        (str(utf16), "UTF-16", ("не в UTF-8", "UTF-16")),
    )
    for env_input, src, needles in cases:
        out.write_text("старое", encoding="utf-8")
        rc, so, se = run_script(
            "txtproc.py", {"TTS_INPUT": env_input, "SILERO_INPUT": str(out)}
        )
        assert rc == 1, (src, rc, so, se)
        for needle in needles:
            assert needle in se, (src, needle, se)
        assert "Traceback" not in se and "UnicodeDecodeError" not in se, (src, se)
        assert out.read_text(encoding="utf-8") == "старое", (src, "выход не перезаписан")

    # пустой вход — предупреждение, но rc=0 и пустой выход (контракт play.sh: 0)
    rc, so, se = run_script("txtproc.py", {"TTS_INPUT": str(empty), "SILERO_INPUT": str(out)})
    assert rc == 0, (rc, so, se)
    assert "Пустой вход" in se, se
    assert out.read_text(encoding="utf-8") == "", repr(out.read_text(encoding="utf-8"))

    # --- CLI silero10.py: ошибки входа до makedirs и до загрузки модели ---
    for env_input, src, needles in (
        (str(missing), "нет файла", ("Нет входного файла",)),
        (str(utf16), "UTF-16", ("не в UTF-8",)),
    ):
        outdir = tmp / f"out-{src}"
        rc, so, se = run_script(
            "silero10.py", {"SILERO_INPUT": env_input, "SILERO_OUTPUT_DIR": str(outdir)}
        )
        assert rc == 1, (src, rc, so, se)
        for needle in needles:
            assert needle in se, (src, needle, se)
        assert "Traceback" not in se and "FileNotFoundError" not in se, (src, se)
        assert not outdir.exists(), (src, "каталог выхода не создаётся при ошибке входа")


def check_headroom(out: Path):
    """T12/D12: пик WAV обязан укладываться в запас по громкости.

    Проверка идёт по-настоящему записанному файлу, а не только функции: дефект D12
    жил именно на границе `sf.write` + PCM_16, где 1.0 превращается в клиппинг.
    """
    target = 10.0 ** (HEADROOM_DB / 20.0)

    class Fake:
        def apply_tts(self, **kwargs):
            # модель v5_6_ru отдаёт torch.Tensor с пиком впритык к 0 dBFS. Пикин
            # заведомо выше цели, иначе правка свелась бы к умножению на единицу:
            # при пике ровно 1.0 коэффициент limit/peak совпадает с самим limit,
            # и ошибка в расчёте пика стала бы невидимой.
            return torch.tensor([0.4, -0.25, 0.2, 0.0], dtype=torch.float32)

    def real_writer(path, audio, sr):
        sf.write(path, audio, sr)  # subtype по умолчанию — PCM_16, как в бою

    for name in out.glob("*.wav"):
        name.unlink()
    ok_count, errors, _ = render_sentences(
        Fake(), ["громко."], "medium", str(out), 48000, "aidar", writer=real_writer
    )
    assert (ok_count, errors) == (1, 0), (ok_count, errors)
    written, sr = sf.read(str(out / "out_0001.wav"), dtype="float32")
    peak = float(np.max(np.abs(written)))
    assert peak < CLIPPING_LEVEL, f"клиппинг: пик {peak}"
    # пик подтянут к цели, а не обрезан и не усреднён: форма сохранена с одним коэффициентом
    assert abs(peak - target) < 1e-3, (peak, target)
    assert sr == 48000, sr
    assert written[1] / written[0] == pytest_approx(-0.625), written  # пропорции те же

    # тихий фрагмент усиливается до той же цели, а не остаётся шёпотом
    quiet = np.array([0.2, -0.1], dtype="float32")
    assert abs(float(np.max(np.abs(normalize_peak(quiet)))) - target) < 1e-6

    # отключение: SILERO_HEADROOM_DB=0 -> волна уходит как есть (контракт «поведение не изменилось»)
    loud = np.array([1.0, -1.0], dtype="float32")
    assert normalize_peak(loud, 0) is loud or float(np.max(np.abs(normalize_peak(loud, 0)))) == 1.0
    assert float(np.max(np.abs(normalize_peak(loud, 3)))) == 1.0, "положительный headroom отключает правку"

    # тишину не выдумываем: ноль остаётся нулём (и деления на ноль нет)
    zeros = np.zeros(8, dtype="float32")
    assert float(np.max(np.abs(normalize_peak(zeros)))) == 0.0
    assert len(normalize_peak(np.array([], dtype="float32"))) == 0

    # torch.Tensor: тип сохраняется (apply_tts отдаёт именно его) и пик считается
    # по abs().max(), а не по numpy-овской версии
    tensor_out = normalize_peak(torch.tensor([1.0, -0.5]))
    assert type(tensor_out).__name__ == "Tensor", type(tensor_out).__name__
    assert abs(float(tensor_out.abs().max()) - target) < 1e-6, tensor_out
    # тишина в тензоре остаётся тишиной (иначе из паузы получился бы шум)
    silence = normalize_peak(torch.zeros(4))
    assert float(silence.abs().max()) == 0.0, silence

    # знак: пик считается по модулю, иначе минус 0.4 ушёл бы как «пик +0.1» и
    # фрагмент остался бы клиппующим после усиления
    negative = normalize_peak(torch.tensor([-0.4, 0.1]))
    assert abs(float(negative.abs().max()) - target) < 1e-6, negative
    negative_np = normalize_peak(np.array([-0.4, 0.1], dtype="float32"))
    assert abs(float(np.max(np.abs(negative_np))) - target) < 1e-6, negative_np


def pytest_approx(value):
    class Approx:
        def __eq__(self, other):
            return abs(other - value) < 1e-4

        def __repr__(self):
            return f"~{value}"

    return Approx()


def check_resume_and_atomic(tmp: Path):
    """T14: `--resume` (SILERO_RESUME=1) и атомарная запись WAV.

    Модель не грузится: render_sentences вызывается с заглушкой, writer — свой,
    поэтому проверка работает без GPU и без сети (ограничение 0.6).
    """
    out = tmp / "resume-out"
    out.mkdir(exist_ok=True)
    for name in out.glob("*.wav"):
        name.unlink()
    # флаг читается ровно в одном месте и только из SILERO_RESUME=1
    os.environ.pop("SILERO_RESUME", None)
    assert is_resume_enabled() is False, "без SILERO_RESUME resume выключен"
    os.environ["SILERO_RESUME"] = "1"
    assert is_resume_enabled() is True, "SILERO_RESUME=1 включает resume"
    os.environ["SILERO_RESUME"] = "0"
    assert is_resume_enabled() is False, "SILERO_RESUME=0 — не resume"
    os.environ.pop("SILERO_RESUME", None)

    written = []

    class Fake:
        def apply_tts(self, **kwargs):
            return [0] * 4800

    def writer(path, audio, sr):
        # writer получает путь временного файла (иначе os.replace нечего двигать),
        # поэтому считаем не имена, а факт записи: сколько раз реально писали
        Path(path).write_bytes(b"RIFF")
        written.append(path)

    sentences = ["раз.", "два.", "три."]
    os.environ["SILERO_RESUME"] = "1"
    try:
        # первый прогон: файлов нет — пишутся все три
        ok, errors, _ = render_sentences(Fake(), sentences, "medium", str(out), 48000, "aidar", writer=writer)
        assert (ok, errors) == (3, 0), (ok, errors)
        assert len(written) == 3, written
        assert sorted(p.name for p in out.glob("out_*.wav")) == [
            "out_0001.wav",
            "out_0002.wav",
            "out_0003.wav",
        ], sorted(p.name for p in out.iterdir())

        # второй прогон: всё готово — не пишется ничего, ошибок нет, rc-сигнал тот же
        written.clear()
        ok, errors, _ = render_sentences(Fake(), sentences, "medium", str(out), 48000, "aidar", writer=writer)
        assert (ok, errors) == (0, 0), (ok, errors)
        assert written == [], written  # ни одной записи — всё уже на месте

        # дырка: удалили средний файл — до synthesизируется только он
        (out / "out_0002.wav").unlink()
        written.clear()
        ok, errors, _ = render_sentences(Fake(), sentences, "medium", str(out), 48000, "aidar", writer=writer)
        assert (ok, errors) == (1, 0), (ok, errors)
        assert len(written) == 1, written
        assert (out / "out_0002.wav").read_bytes() == b"RIFF"

        # без SILERO_RESUME поведение не изменилось: пишутся заново все
        os.environ.pop("SILERO_RESUME", None)
        written.clear()
        ok, errors, _ = render_sentences(Fake(), sentences, "medium", str(out), 48000, "aidar", writer=writer)
        assert (ok, errors) == (3, 0), (ok, errors)
        assert len(written) == 3, written  # без флага пишутся заново все
    finally:
        os.environ.pop("SILERO_RESUME", None)

    # --- T12: headroom против клиппинга (D12) ---
    check_headroom(out)

    # --- save_atomic: ошибка записи не оставляет временных файлов и не трогает цель ---
    target = out / "out_0001.wav"
    before = target.read_bytes()

    def boom(path, audio, sr):
        # writer обязан получить путь временного файла, а не финальный
        assert os.path.basename(path).startswith(".out_"), path
        Path(path).write_bytes(b"half-written")
        raise RuntimeError("модель упала в середине записи")

    try:
        save_atomic(boom, str(target), [0] * 10, 48000)
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("save_atomic обязан пробрасывать ошибку записи")
    assert target.read_bytes() == before, "прежний WAV перезаписан при ошибке"
    assert not list(out.glob(".out_*")), "остался временный файл"

    def ok_writer(path, audio, sr):
        assert os.path.basename(path).startswith(".out_"), path
        Path(path).write_bytes(b"NEW")

    save_atomic(ok_writer, str(target), [0] * 10, 48000)
    assert target.read_bytes() == b"NEW", "успешная запись не подменила файл"
    assert not list(out.glob(".out_*")), "остался временный файл после успеха"

    # имя временного файла не должно попадать в шаблон out_NNNN.wav: play.sh собирает
    # список и предупреждения по имени, а полузаписанный .out_*.wav не должен
    # считаться готовым фрагментом ни при --resume, ни при обычной нарезке списка
    tmp_seen = []

    def names(path, audio, sr):
        tmp_seen.append(os.path.basename(path))
        Path(path).write_bytes(b"x")

    render_sentences(Fake(), ["фраза."], "medium", str(out), 48000, "aidar", writer=names)
    assert tmp_seen and tmp_seen[0].startswith(".") and not tmp_seen[0].startswith("out_"), tmp_seen
    assert not [p.name for p in out.iterdir() if p.name.startswith(".out_") and p.name.endswith(".wav")]

    # жёсткая ссылка на «рабочий» файл (ситуация --resume): прежнее содержимое цело
    working = tmp / "working.wav"
    working.write_bytes(b"OLD")
    link = out / "linked.wav"
    if link.exists():
        link.unlink()
    os.link(working, link)
    save_atomic(ok_writer, str(link), [0] * 10, 48000)
    assert working.read_bytes() == b"OLD", "жёсткая ссылка на рабочий WAV перезаписана"
    assert link.read_bytes() == b"NEW"


def main():
    # каталог для проверок без риска для рабочих артефактов (ограничение 0.7)
    tmp = Path("/tmp/play-t6-tests")
    tmp.mkdir(exist_ok=True)

    cases = load_cases(Path(__file__).with_name("cases.txt"))
    failed = 0
    for src, expected in cases:
        got = normalize_text(src)
        if got != expected:
            failed += 1
            print(f"FAIL {src!r}\n  got {got!r}\n  exp {expected!r}")
        elif normalize_text(got) != got:
            failed += 1
            print(f"NOT IDEMPOTENT {src!r}\n  {got!r}")
    if failed:
        print(f"{failed} normalize failures")
        return 1

    heading = prepare_chunks(
        "Что происходит на фронте\nНа шесть ноября началось длинное наступление на город."
    )
    assert heading[0] == "Что происходит на фронте", heading
    assert len(heading) == 2, heading

    cities = prepare_chunks("Славянск.\nКраматорск.\nДружковка.\nКонстантиновка.")
    assert cities == ["Славянск. Краматорск. Дружковка. Константиновка."], cities

    quoted = (
        "Он сказал «что? да» и продолжил довольно длинную фразу дальше. "
        "Она ушла в другую комнату совсем одна."
    )
    parts = split_into_sentences(quoted)
    assert len(parts) == 2 and "что?" in parts[0], parts

    long = prepare_chunks(("альфа бета, " * 200).strip())
    assert len(long) > 1 and all(len(part) <= MAX_CHUNK_CHARS for part in long), [
        len(part) for part in long
    ]

    # --- T7: незакрытая кавычка не склеивает абзац ---
    quoted_open = "Он сказал «привет. Как дела. " + "y" * 40 + ". конец"
    parts = split_into_sentences(quoted_open)
    assert len(parts) >= 2, parts
    assert all(len(part) <= MAX_CHUNK_CHARS for part in parts), [len(p) for p in parts]
    assert any(part.startswith("Как дела.") for part in parts), parts

    # перевод строки закрывает цитату: соседний абзац не приклеивается
    assert split_into_sentences("Он сказал «привет. Как дела.\nВторой абзац. ещё.") == [
        "Он сказал «привет.",
        "Как дела.",
        "Второй абзац.",
        "ещё.",
    ], split_into_sentences("Он сказал «привет. Как дела.\nВторой абзац. ещё.")

    # одиночная прямая кавычка и парная — обе ведут себя как раньше для валидного текста
    assert len(split_into_sentences('Он сказал "привет. И ушёл.')) == 2
    assert split_into_sentences('Она ответила "нет" и молчала. Потом ушла.') == [
        'Она ответила "нет" и молчала.',
        "Потом ушла.",
    ]

    # --- T7: дефекты исходной нарезки (дубли символов, потеря переносов) ---
    assert split_into_sentences("Из Франции??! А что он там делает?") == [
        "Из Франции??!",
        "А что он там делает?",
    ], split_into_sentences("Из Франции??! А что он там делает?")
    assert split_into_sentences("он уехал..— Слишком занят.") == [
        "он уехал..— Слишком занят."
    ], split_into_sentences("он уехал..— Слишком занят.")
    assert split_into_sentences("А.С. Пушкин") == ["А.С.", "Пушкин"]
    assert split_into_sentences('«быстро— и\nнизколетящего объёма».') == [
        "«быстро— и",
        "низколетящего объёма».",
    ]

    # T9.1: градус после словесного числа. Именительный («минус пять °C») и
    # составные слова обрабатывает только цифровое правило — фиксируем как
    # известное ограничение, чтобы правка транслитерации не «улучшила» его молча.
    assert normalize_text("до минус пяти °C") == "до минус пяти градусов Цельсия"
    assert "°к" in normalize_text("минус пять °C")

    # известное ограничение: закрытие цитаты стоит после конца предложения —
    # режим не включается, цитата режется как обычный текст
    assert len(
        split_into_sentences("«Первая строка цитаты, вторая строка. Третья.» И конец.")
    ) == 1

    class Boom:
        def apply_tts(self, **kwargs):
            if "плохо" in kwargs["ssml_text"]:
                raise RuntimeError("too long")
            # ненулевой сигнал: иначе normalize_peak резала бы из тишины шум
            return [0.5] * 4800

    # имена проверяем по содержимому каталога: save_atomic пишет во временный
    # файл и переименовывает, поэтому writer видит .out_*, а на выходе out_NNNN.wav
    paths = []
    synth_dir = tmp / "synth"
    synth_dir.mkdir(exist_ok=True)
    for stale in synth_dir.glob("*"):
        stale.unlink()
    ok, errors, _dur = render_sentences(
        Boom(),
        ["привет", "плохо", "ещё"],
        "medium",
        str(synth_dir),
        48000,
        "aidar",
        # writer подменяет содержимое по имени временного файла, а имя проверяем
        # уже после os.replace — как это делает save_atomic в бою
        writer=lambda path, audio, sr: (Path(path).write_bytes(b"x"), paths.append(path)),
    )
    assert (ok, errors) == (2, 1), (ok, errors)
    written = sorted(p.name for p in synth_dir.iterdir())
    assert written == ["out_0001.wav", "out_0003.wav"], written
    assert not [p for p in synth_dir.iterdir() if p.name.startswith(".out_")], "остался временный файл"

    # --- T6: ошибки входа (нет файла, не UTF-8, пустой вход) ---
    check_input_errors(tmp)
    check_resume_and_atomic(tmp)

    print(f"OK {len(cases)} cases, chunks, synthesis errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
