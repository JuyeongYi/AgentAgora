"""체크박스 다중 선택 — tty면 화살표+스페이스, 비-tty/미지원이면 번호 입력 폴백.

순수 stdlib(msvcrt/termios + ANSI). 화살표 경로는 실제 터미널에서만 동작하며 자동
테스트 대상이 아니다 — `_toggle_step`(순수 토글 로직)과 번호 폴백이 테스트로 가드되고,
tty가 아니거나 raw 모드/VT가 실패하면 번호 입력으로 자동 폴백한다.
"""
from __future__ import annotations

import sys


def _toggle_step(n: int, cursor: int, checked: set[int], key: str):
    """키 한 번 적용 → (cursor, checked, done). 순수 함수."""
    if key == "up":
        cursor = (cursor - 1) % n
    elif key == "down":
        cursor = (cursor + 1) % n
    elif key == "space":
        checked = set(checked) ^ {cursor}
    elif key == "enter":
        return cursor, checked, True
    return cursor, checked, False


def _is_interactive(stdin, stdout) -> bool:
    try:
        return bool(stdin.isatty() and stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _numbered_fallback(options, stdin, stdout, prompt):
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o}", file=stdout)
    print(f"{prompt} (번호 쉼표구분, 예 1,3; 빈칸=없음): ", end="", file=stdout, flush=True)
    line = stdin.readline()
    picked: list = []
    for tok in (line or "").split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(options):
            opt = options[int(tok) - 1]
            if opt not in picked:
                picked.append(opt)
    return picked


def _read_key(stdin):
    """tty에서 키 한 번 → 'up'/'down'/'space'/'enter'/'quit'/None."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):          # 특수키(화살표) prefix
            ch2 = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(ch2)
        if ch == " ":
            return "space"
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("\x03", "\x1b", "q"):
            return "quit"
        return None
    import termios
    import tty as _tty
    fd = stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        _tty.setraw(fd)
        ch = stdin.read(1)
        if ch == "\x1b":                    # ESC 시퀀스(화살표)
            seq = stdin.read(2)
            return {"[A": "up", "[B": "down"}.get(seq)
        if ch == " ":
            return "space"
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("\x03", "q"):
            return "quit"
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _enable_vt():
    """Windows 콘솔 VT(ANSI) 활성화. 실패는 무시."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32          # type: ignore[attr-defined]
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint()
        k.GetConsoleMode(h, ctypes.byref(mode))
        k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _render(options, checked, cursor, stdout, prompt, first):
    if not first:
        stdout.write(f"\033[{len(options) + 1}A")   # 그렸던 줄 수만큼 커서 위로
    stdout.write(f"{prompt} (↑↓ 이동, 스페이스 체크, 엔터 확정)\033[K\n")
    for i, o in enumerate(options):
        mark = "x" if i in checked else " "
        pointer = ">" if i == cursor else " "
        stdout.write(f"{pointer} [{mark}] {o}\033[K\n")
    stdout.flush()


def _arrow_checkbox(options, stdin, stdout, prompt):
    _enable_vt()
    cursor, checked = 0, set()
    n = len(options)
    first = True
    while True:
        _render(options, checked, cursor, stdout, prompt, first)
        first = False
        key = _read_key(stdin)
        if key == "quit":
            checked = set()
            break
        if key:
            cursor, checked, done = _toggle_step(n, cursor, checked, key)
            if done:
                break
    return [o for i, o in enumerate(options) if i in checked]


def checkbox_select(options, *, stdin=None, stdout=None, prompt="선택"):
    """options(라벨)에서 다중 선택. tty면 화살표 체크박스, 아니면 번호 입력 폴백.
    선택된 라벨 리스트를 반환한다."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if not options:
        return []
    if _is_interactive(stdin, stdout):
        try:
            return _arrow_checkbox(options, stdin, stdout, prompt)
        except Exception:               # raw 모드/키 입력 실패 → 폴백
            pass
    return _numbered_fallback(options, stdin, stdout, prompt)
