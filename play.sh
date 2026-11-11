#!/usr/bin/env bash
# Оркестратор: txtproc.py → silero10.py → ffprobe (выборочно) → ffplay.
# Интерпретатор: $SILERO_PYTHON или ~/.pyenv/versions/silero/bin/python.
# Скорость 1–5. Лишние аргументы — ошибка. --no-play или PLAY=0 не запускают ffplay.
# Синтез пишется в staging (${SILERO_OUTPUT_DIR}.new) и подменяет рабочий каталог
# только после успеха: упавший прогон оставляет прежние WAV на месте.
# Перед ffplay первый и последний WAV проверяются ffprobe: на битом файле ffplay
# пишет ошибку и возвращает 0, поэтому без проверки битая склейка выглядела бы
# успехом (D8). Код возврата прогона от предпроверки не меняется — как был 0.
# Фаги --voice/--device/--log/--resume только пробрасываются в окружение silero10.py,
# поведение по умолчанию (без них) не изменилось.
export LD_LIBRARY_PATH=$(python -c "import nvidia.cudnn; print(nvidia.cudnn.__path__[0] + '/lib')"):$LD_LIBRARY_PATH
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  local code="${1:-1}"
  echo "Использование: $0 [1-5] [--no-play] [--voice ГОЛОС] [--device cuda|cpu] [--log ФАЙЛ] [--resume]" >&2
  echo "  1  x-slow   очень медленно" >&2
  echo "  2  slow     медленно" >&2
  echo "  3  medium   норма (по умолчанию)" >&2
  echo "  4  fast     быстро" >&2
  echo "  5  x-fast   очень быстро" >&2
  echo "  --no-play   только синтез, без ffplay (то же, что PLAY=0)" >&2
  echo "  --play      включить ffplay обратно" >&2
  echo "  --voice N   голос (aidar, baya, kseniya, xenia, eugene); то же, что SILERO_VOICE=N" >&2
  echo "  --device D  cuda или cpu; то же, что SILERO_DEVICE=D" >&2
  echo "  --log ФАЙЛ  писать вывод прогона в файл (stdout и stderr), плюс в терминал" >&2
  echo "  --resume    не пересинтезировать out_NNNN.wav, которые уже лежат в рабочем каталоге" >&2
  exit "$code"
}

rate=""
play=1
log_file=""
resume_env=""

# Значение флага обязано быть непустым и не походить на другой флаг: иначе `--voice --no-play`
# молча сделало бы голос «--no-play», а пустой `--device ''` перебил бы автовыбор устройства.
flag_value() {
  local name="$1" value="${2:-}"
  if [[ -z "$value" || "$value" == -* ]]; then
    echo "Нужно значение у $name" >&2
    usage
  fi
}

# --log включается до разбора аргументов: всё, что скажут дальше (в том числе usage и
# «Нет интерпретатора»), должно попадать и в файл. Канал проверяется на месте вызова,
# а не здесь: к этому моменту сам прогон ещё не перенаправлял вывод, поэтому
# `./play.sh --log f >/dev/null` — это перенаправление пользователя, а не наше.
open_log() {
  local f="${1:-}"
  if [[ -z "$f" ]]; then
    echo "Нужно значение у --log" >&2
    usage
  fi
  if [[ "$f" == -* ]]; then
    echo "Нужно значение у --log" >&2
    usage
  fi
  local dir; dir=$(dirname -- "$f")
  if [[ ! -d "$dir" ]]; then
    echo "Каталога для лога нет: $dir" >&2
    exit 1
  fi
  # Канал проверяется до tee: при переназначенном stdout копия в терминал невозможна,
  # а писать только в файл означало бы потерять сообщения прогона в этом запуске.
  if [[ ! -t 1 ]]; then
    echo "--log несовместим с перенаправленным stdout — вывод прогона в терминал потеряется" >&2
    exit 1
  fi
  if ! : > "$f" 2>/dev/null; then
    echo "Не записать лог: $f" >&2
    exit 1
  fi
  exec > >(tee -- "$f") 2>&1
}
if [[ "${PLAY:-1}" == "0" ]]; then
  play=0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage 0
      ;;
    --no-play)
      play=0
      shift
      ;;
    --play)
      play=1
      shift
      ;;
    --voice)
      flag_value "--voice" "${2:-}"
      export SILERO_VOICE="$2"
      shift 2
      ;;
    --device)
      flag_value "--device" "${2:-}"
      case "$2" in
        cuda|cpu) export SILERO_DEVICE="$2" ;;
        *) echo "Устройство: cuda или cpu (получено $2)" >&2; usage ;;
      esac
      shift 2
      ;;
    --log)
      open_log "${2:-}"
      shift 2
      ;;
    --resume)
      resume_env=1
      shift
      ;;
    1|2|3|4|5)
      if [[ -n "$rate" ]]; then
        usage
      fi
      rate="$1"
      shift
      ;;
    *)
      usage
      ;;
  esac
done

# Проверка первого и последнего WAV из списка. Возвращает 0, если придраться не к чему:
# нет ffprobe, файл недоступен или проверка прошла. Ненулевой код — «не читается».
probe_first_last() {
  local list="$1" p
  command -v ffprobe >/dev/null 2>&1 || return 0
  mapfile -t probe_paths < <(sed -n "s/^file '\(.*\)'$/\1/p" "$list")
  (( ${#probe_paths[@]} > 0 )) || return 0
  probe_paths=("${probe_paths[0]}" "${probe_paths[-1]}")
  for p in "${probe_paths[@]}"; do
    [[ -f "$p" ]] || continue
    if ! ffprobe -v error -show_entries stream=codec_name -of default=noprint_wrappers=1 \
         "$p" >/dev/null 2>&1; then
      echo "Предупреждение: $p не читается как аудио (ffprobe) — склейка может играть молча" >&2
      return 1
    fi
  done
  return 0
}

rate="${rate:-3}"

PY="${SILERO_PYTHON:-$HOME/.pyenv/versions/silero/bin/python}"
if [[ ! -x "$PY" ]]; then
  echo "Нет интерпретатора $PY" >&2
  exit 1
fi

export TTS_INPUT="${TTS_INPUT:-input.txt}"
export SILERO_INPUT="${SILERO_INPUT:-silero_input.txt}"
export SILERO_OUTPUT_DIR="${SILERO_OUTPUT_DIR:-silero_output}"
export SILERO_LIST="${SILERO_LIST:-list.txt}"

# Прежний результат не трогаем до успеха синтеза: пишем в staging и подменяем в конце.
stage="${SILERO_OUTPUT_DIR}.new"
stale="${SILERO_OUTPUT_DIR}.old"

# Синтез. Ненулевой код возврата — прежние WAV целы, staging убираем (или жалеем).
rm -rf "$stage"; mkdir -p "$stage"
# --resume: рабочие WAV перекидываются жёсткими ссылками, silero10.py перезапишет
# недостающие по тому же имени. Ссылка на рабочий каталог безвредна: содержимое
# файла подменяется только что записанным временным файлом (см. silero10.save_atomic),
# поэтому прежний out_NNNN.wav не портится, даже если прогон упадёт на середине.
if [[ -n "$resume_env" ]]; then
  export SILERO_RESUME=1
fi
if [[ -n "$resume_env" && -d "$SILERO_OUTPUT_DIR" ]]; then
  copied=0
  for f in "$SILERO_OUTPUT_DIR"/out_[0-9][0-9][0-9][0-9].wav; do
    [[ -e "$f" ]] || continue
    if ln -- "$f" "$stage/$(basename "$f")" 2>/dev/null; then
      copied=$((copied + 1))
    else
      echo "--resume: не удалось подхватить $f, он будет синтезирован заново" >&2
    fi
  done
  (( copied > 0 )) && echo "--resume: пропущено готовых фрагментов: $copied" >&2
fi
set +e
"$PY" txtproc.py
txt_rc=$?
if (( txt_rc == 0 )); then
  SILERO_OUTPUT_DIR="$stage" "$PY" silero10.py "$rate"
  rc=$?
else
  rc=$txt_rc
fi
set -e
if (( rc != 0 )); then
  if [[ -d "$SILERO_OUTPUT_DIR" ]]; then
    echo "Предыдущие файлы сохранены в $SILERO_OUTPUT_DIR (синтез не удался)" >&2
  else
    echo "Синтез не удался, $SILERO_OUTPUT_DIR не создавался" >&2
  fi
  # Часть фрагментов могла успеть записаться — оставляем их в staging для разбора.
  shopt -s nullglob
  partial=("$stage"/*.wav)
  shopt -u nullglob
  if (( ${#partial[@]} > 0 )); then
    echo "Частичные файлы синтеза: $stage (${#partial[@]} wav)" >&2
  else
    rm -rf "$stage"
  fi
  exit "$rc"
fi

# Предупреждения о файлах вне шаблона — по содержимому staging, путь печатаем финальный.
shopt -s nullglob
for f in "$stage"/*.wav; do
  base=$(basename "$f")
  if [[ ! "$base" =~ ^out_[0-9]{4}\.wav$ ]]; then
    echo "Предупреждение: $SILERO_OUTPUT_DIR/$base вне шаблона out_NNNN.wav, в склейку не входит" >&2
  fi
done

files=("$stage"/out_[0-9][0-9][0-9][0-9].wav)
if ((${#files[@]} == 0)); then
  echo "Нет файлов ${SILERO_OUTPUT_DIR}/out_NNNN.wav, воспроизведение отменено" >&2
  if [[ -d "$SILERO_OUTPUT_DIR" ]]; then
    echo "Предыдущие файлы сохранены в $SILERO_OUTPUT_DIR (синтез не удался)" >&2
  fi
  rm -rf "$stage"
  exit 1
fi

# Список собирается из staging, но с финальными путями: ffplay читает рабочий каталог.
mapfile -t files < <(printf '%s\n' "${files[@]}" | LC_ALL=C sort -V)
names=()
for f in "${files[@]}"; do
  names+=("$SILERO_OUTPUT_DIR/$(basename "$f")")
done
printf "file '%s'\n" "${names[@]}" > "$SILERO_LIST"

# Подмена рабочего каталога. Снимок старого (.old) удаляется только после успеха.
rm -rf "$stale"
if [[ -d "$SILERO_OUTPUT_DIR" ]]; then
  mv "$SILERO_OUTPUT_DIR" "$stale"
fi
if ! mv "$stage" "$SILERO_OUTPUT_DIR"; then
  echo "Не удалось подменить $SILERO_OUTPUT_DIR" >&2
  if [[ -d "$stale" ]]; then
    mv "$stale" "$SILERO_OUTPUT_DIR"
  fi
  exit 1
fi
rm -rf "$stale"

if [[ "$play" -eq 0 ]]; then
  echo "Воспроизведение выключено. Файлы: $SILERO_OUTPUT_DIR" >&2
  exit 0
fi

if ! command -v ffplay >/dev/null 2>&1; then
  echo "ffplay не найден. WAV готовы в $SILERO_OUTPUT_DIR, воспроизведение пропущено" >&2
  exit 0
fi

# ffplay на битом или недоступном WAV возвращает 0 (D8), поэтому проверяем до него.
probe_first_last "$SILERO_LIST" || true

set +e
ffplay -loglevel error -f concat -safe 0 "$SILERO_LIST" -autoexit
rc=$?
set -e
if [[ "$rc" -ne 0 ]]; then
  echo "ffplay завершился с кодом $rc. WAV уже лежат в $SILERO_OUTPUT_DIR" >&2
  exit 0
fi
