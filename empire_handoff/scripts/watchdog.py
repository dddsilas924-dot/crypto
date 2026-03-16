"""
Empire Monitor Watchdog — プロセス監視 & 自動再起動
main.pyが落ちたら即座に再起動。ログ付き。

Usage: python scripts/watchdog.py
       python scripts/watchdog.py --max-restarts 10
       python scripts/watchdog.py --cooldown 30
"""
import os
import subprocess
import sys
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path

LOG_DIR = Path('vault/logs')
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WATCHDOG] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'watchdog.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger('watchdog')


def _kill_existing_main():
    """既存のmain.pyプロセスを検出して停止"""
    import platform
    my_pid = os.getpid()
    killed = 0
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['wmic', 'process', 'where', "name='python.exe'", 'get', 'ProcessId,CommandLine'],
                capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                if 'main.py' in line and str(my_pid) not in line:
                    parts = line.strip().split()
                    for p in parts:
                        if p.isdigit():
                            try:
                                os.kill(int(p), 9)
                                log.info(f"Killed existing main.py (PID {p})")
                                killed += 1
                            except (ProcessLookupError, PermissionError):
                                pass
                if 'watchdog.py' in line and str(my_pid) not in line:
                    parts = line.strip().split()
                    for p in parts:
                        if p.isdigit():
                            try:
                                os.kill(int(p), 9)
                                log.info(f"Killed existing watchdog (PID {p})")
                                killed += 1
                            except (ProcessLookupError, PermissionError):
                                pass
        else:
            subprocess.run(['pkill', '-f', 'main.py'], capture_output=True, timeout=5)
            killed = 1
    except Exception as e:
        log.warning(f"Process cleanup failed: {e}")

    if killed:
        log.info(f"Cleaned up {killed} existing process(es). Waiting 3s...")
        time.sleep(3)
    else:
        log.info("No existing processes found.")


def run_watchdog(max_restarts: int = 50, cooldown: int = 10, rapid_threshold: int = 30, port: int = None):
    """
    main.pyを監視して自動再起動

    Args:
        max_restarts: 最大連続再起動回数（超えたら停止）
        cooldown: 再起動までの待機秒数
        rapid_threshold: この秒数以内に落ちたら「急速クラッシュ」カウント
        port: ダッシュボードポート（デフォルト: settings.yamlの値）
    """
    restart_count = 0
    rapid_crash_count = 0
    max_rapid = 5

    cmd = [sys.executable, 'main.py']
    if port:
        cmd += ['--port', str(port)]

    # 起動前に既存のmain.pyプロセスを停止
    _kill_existing_main()

    log.info(f"Watchdog started. max_restarts={max_restarts}, cooldown={cooldown}s, port={port or 'default'}")
    log.info(f"Monitoring: {' '.join(cmd)}")

    while restart_count < max_restarts:
        start_time = time.time()
        log.info(f"--- Starting Empire Monitor (restart #{restart_count}) ---")

        try:
            env = dict(os.environ, PYTHONUNBUFFERED='1')
            process = subprocess.Popen(
                cmd,
                cwd=str(Path(__file__).parent.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
                env=env,
            )

            # リアルタイムでログを出力
            crash_log_lines = []
            for line in process.stdout:
                line = line.rstrip()
                print(line)
                # 直近50行をクラッシュ分析用に保持
                crash_log_lines.append(line)
                if len(crash_log_lines) > 50:
                    crash_log_lines.pop(0)

            process.wait()
            exit_code = process.returncode

        except Exception as e:
            exit_code = -1
            crash_log_lines = [str(e)]
            log.error(f"Process launch error: {e}")

        elapsed = time.time() - start_time

        # 正常終了判定（KeyboardInterrupt等）
        if exit_code == 0:
            log.info(f"Empire Monitor exited normally (code 0) after {elapsed:.0f}s")
            break

        # クラッシュ
        restart_count += 1
        log.warning(f"Empire Monitor CRASHED! exit_code={exit_code}, uptime={elapsed:.0f}s, restart #{restart_count}/{max_restarts}")

        # クラッシュ直前のログを記録
        if crash_log_lines:
            log.warning(f"Last output lines:")
            for line in crash_log_lines[-10:]:
                log.warning(f"  | {line}")

        # 急速クラッシュ検出
        if elapsed < rapid_threshold:
            rapid_crash_count += 1
            log.warning(f"Rapid crash detected ({elapsed:.0f}s < {rapid_threshold}s). Count: {rapid_crash_count}/{max_rapid}")

            if rapid_crash_count >= max_rapid:
                wait = cooldown * rapid_crash_count  # バックオフ
                log.error(f"Too many rapid crashes! Waiting {wait}s before retry...")
                time.sleep(wait)
                rapid_crash_count = 0  # リセット
                continue
        else:
            rapid_crash_count = 0  # 正常稼働後はリセット

        # クラッシュログをファイルに保存
        crash_file = LOG_DIR / f'crash_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        with open(crash_file, 'w', encoding='utf-8') as f:
            f.write(f"Exit code: {exit_code}\n")
            f.write(f"Uptime: {elapsed:.0f}s\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write(f"Restart #: {restart_count}\n\n")
            f.write("=== Last 50 lines ===\n")
            for line in crash_log_lines:
                f.write(line + '\n')
        log.info(f"Crash log saved: {crash_file}")

        # cooldown
        log.info(f"Restarting in {cooldown}s...")
        time.sleep(cooldown)

    if restart_count >= max_restarts:
        log.error(f"Max restarts ({max_restarts}) reached. Watchdog stopping.")
    else:
        log.info("Watchdog finished (normal exit).")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Empire Monitor Watchdog')
    parser.add_argument('--max-restarts', type=int, default=50, help='最大再起動回数 (default: 50)')
    parser.add_argument('--cooldown', type=int, default=10, help='再起動待機秒数 (default: 10)')
    parser.add_argument('--port', type=int, default=None, help='ダッシュボードポート (default: settings.yaml)')
    args = parser.parse_args()

    run_watchdog(max_restarts=args.max_restarts, cooldown=args.cooldown, port=args.port)
