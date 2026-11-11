# Silero TTS pipeline

Русский текст → нормализация (`txtproc.py`) → Silero v5 (`silero10.py`) → `silero_output/out_NNNN.wav` → воспроизведение через `ffplay`.

    ./play.sh              # скорость 3 (medium), с проигрыванием
    ./play.sh 4 --no-play  # fast, только синтез
    ./play.sh --help       # usage (в stderr, exit 0)

Полное описание, установка с нуля и известные грабли — `play.md`. Аудит, по которому шлись правки, — `play-audit.md` (артефакт, не меняется).

Регрессии без GPU, сети и модели:

    ~/.pyenv/versions/silero/bin/python tests/test_normalize.py
