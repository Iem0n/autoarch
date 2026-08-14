#!/usr/bin/env python3
"""
Выполняется внутри arch-chroot после pacstrap.
Настраивает время, локаль, пользователей, doas, загрузчик,
SSH-ключ и дотфайлы. НЕ запускать вручную.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def log_info(msg): print(f"{BLUE}==>{NC} {msg}")
def log_ok(msg): print(f"{GREEN}{msg}{NC}")
def log_warn(msg): print(f"{YELLOW}[WARN]{NC} {msg}")
def log_err(msg): print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)


def run_cmd(cmd, critical=True, capture=False, input_data=None):
    try:
        res = subprocess.run(cmd, check=True, text=True,
                              capture_output=capture, input=input_data)
        return res.stdout.strip() if capture else None
    except FileNotFoundError:
        msg = f"команда не найдена: {cmd[0]}"
        if critical:
            log_err(msg)
            sys.exit(1)
        log_warn(f"{msg} — пропускаю")
        return None
    except subprocess.CalledProcessError:
        msg = f"команда завершилась с ошибкой: {' '.join(cmd)}"
        if critical:
            log_err(msg)
            sys.exit(1)
        log_warn(f"{msg} — пропускаю (не критично)")
        return None


def write_file(path, content, mode=None):
    with open(path, "w") as f:
        f.write(content)
    if mode is not None:
        os.chmod(path, mode)


def main():
    if len(sys.argv) < 4:
        log_err("Этот скрипт запускается только из install.py, вручную не запускать")
        sys.exit(1)

    user, host, root_part = sys.argv[1:4]
    root_pass = os.environ.pop("ROOT_PASSWORD", None)
    user_pass = os.environ.pop("USER_PASSWORD", None)
    if not root_pass or not user_pass:
        log_err("Пароли не переданы через переменные окружения (ROOT_PASSWORD/USER_PASSWORD)")
        sys.exit(1)

    # --- Время и локаль (не критично для загрузки системы) ---
    log_info("Настройка времени и локали...")
    tz = Path("/usr/share/zoneinfo/Europe/Warsaw")
    if tz.exists():
        localtime = Path("/etc/localtime")
        if localtime.exists() or localtime.is_symlink():
            localtime.unlink()
        localtime.symlink_to(tz)
        run_cmd(["hwclock", "--systohc"], critical=False)
    else:
        log_warn("Часовой пояс Europe/Warsaw не найден, пропускаю")

    try:
        with open("/etc/locale.gen", "a") as f:
            f.write("en_US.UTF-8 UTF-8\n")
        run_cmd(["locale-gen"], critical=False)
        write_file("/etc/locale.conf", "LANG=en_US.UTF-8\n")
    except OSError as e:
        log_warn(f"Не удалось настроить локаль: {e}")

    # --- Хост и пользователи (критично) ---
    log_info("Настройка hostname и пользователей...")
    write_file("/etc/hostname", f"{host}\n")

    run_cmd(["passwd"], input_data=f"{root_pass}\n{root_pass}\n")
    run_cmd(["useradd", "-m", "-G", "wheel", "-s", "/bin/bash", user])
    run_cmd(["passwd", user], input_data=f"{user_pass}\n{user_pass}\n")

    # --- doas вместо sudo ---
    log_info("Настройка doas...")
    run_cmd(["pacman", "-S", "--needed", "--noconfirm", "opendoas"], critical=False)
    # doas требует, чтобы конфиг не был доступен на запись группе/остальным
    write_file("/etc/doas.conf", "permit persist :wheel\n", mode=0o400)

    run_cmd(["systemctl", "enable", "NetworkManager"], critical=False)

    # --- Загрузчик (критично) ---
    log_info("Установка загрузчика (systemd-boot)...")
    run_cmd(["bootctl", "install"])
    uuid = run_cmd(["blkid", "-s", "UUID", "-o", "value", root_part], capture=True)
    if not uuid:
        log_err("Не удалось определить UUID root-раздела")
        sys.exit(1)

    os.makedirs("/boot/loader/entries", exist_ok=True)
    write_file("/boot/loader/loader.conf",
               "default  arch.conf\ntimeout  0\nconsole-mode max\n")
    write_file("/boot/loader/entries/arch.conf", (
        "title   Arch Linux\n"
        "linux   /vmlinuz-linux\n"
        "initrd  /amd-ucode.img\n"
        "initrd  /initramfs-linux.img\n"
        f"options root=UUID={uuid} rw quiet nowatchdog\n"
    ))

    # --- SSH-ключ пользователя (не критично) ---
    log_info("Генерация SSH-ключа...")
    home_dir = f"/home/{user}"
    ssh_dir = f"{home_dir}/.ssh"
    try:
        os.makedirs(ssh_dir, exist_ok=True)
        os.chmod(ssh_dir, 0o700)  # makedirs режется umask, фиксируем явно
        run_cmd(["chown", "-R", f"{user}:{user}", ssh_dir], critical=False)

        key_path = f"{ssh_dir}/id_ed25519"
        if not os.path.exists(key_path):
            # runuser вместо sudo/doas — доверенное переключение пользователя,
            # доступно из коробки, doas.conf ещё может быть не готов к этому моменту
            run_cmd([
                "runuser", "-u", user, "--",
                "ssh-keygen", "-t", "ed25519", "-C", f"{user}@{host}",
                "-f", key_path, "-N", "",
            ], critical=False)

        if os.path.exists(f"{key_path}.pub"):
            print("\n" + "=" * 60)
            print("ДОБАВЬ ЭТОТ ПУБЛИЧНЫЙ КЛЮЧ НА GITHUB:")
            with open(f"{key_path}.pub") as pub_f:
                print(pub_f.read().strip())
            print("=" * 60 + "\n")
        else:
            log_warn("SSH-ключ не создан, пропускаю показ")
    except OSError as e:
        log_warn(f"Не удалось настроить SSH-ключ: {e}")

    # --- Дотфайлы (не критично, зависит от сети) ---
    log_info("Клонирование дотфайлов...")
    dotfiles_dir = f"{home_dir}/.my-dotfiles"
    try:
        if os.path.exists(dotfiles_dir):
            shutil.rmtree(dotfiles_dir)
        run_cmd([
            "runuser", "-u", user, "--",
            "git", "clone", "https://github.com/Iem0n/arch_sync.git", dotfiles_dir,
        ], critical=False)

        if os.path.exists(dotfiles_dir):
            run_cmd(["runuser", "-u", user, "--", "git", "-C", dotfiles_dir,
                     "config", "user.name", "Iem0n"], critical=False)
            run_cmd(["runuser", "-u", user, "--", "git", "-C", dotfiles_dir,
                     "config", "user.email", "vladimirpetrenko1401@gmail.com"], critical=False)
            run_cmd(["runuser", "-u", user, "--", "git", "-C", dotfiles_dir,
                     "remote", "set-url", "origin", "git@github.com:Iem0n/arch_sync.git"], critical=False)
        else:
            log_warn("Клонирование дотфайлов не удалось (нет сети?) — шаг пропущен")
    except OSError as e:
        log_warn(f"Ошибка при работе с дотфайлами: {e}")

    self_path = Path("/post-setup.py")
    if self_path.exists():
        self_path.unlink()

    log_ok("post-setup завершён")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_err("Прервано пользователем")
        sys.exit(130)
    except Exception as e:
        log_err(f"Неожиданная ошибка: {e}")
        sys.exit(1)
