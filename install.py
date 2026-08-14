#!/usr/bin/env python3
"""
Базовый установщик Arch Linux: разметка/форматирование выбранных
разделов, pacstrap, генерация fstab и передача управления
post-setup.py внутри chroot.

Запускать из Arch install ISO с правами root.
"""
import os
import re
import sys
import shutil
import getpass
import subprocess
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

SCRIPT_DIR = Path(__file__).resolve().parent


def log_info(msg): print(f"{BLUE}==>{NC} {msg}")
def log_ok(msg): print(f"{GREEN}{msg}{NC}")
def log_warn(msg): print(f"{YELLOW}[WARN]{NC} {msg}")
def log_err(msg): print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)


def cleanup():
    """Best-effort размонтирование при ошибке/прерывании."""
    for target in ("/mnt/boot", "/mnt"):
        if os.path.ismount(target):
            subprocess.run(["umount", "-R", target], check=False)


def die(msg, code=1):
    log_err(msg)
    cleanup()
    sys.exit(code)


def abort(msg):
    """Отмена по решению пользователя — не ошибка."""
    log_warn(msg)
    cleanup()
    sys.exit(0)


def run_cmd(cmd, critical=True, capture=False, input_data=None, env=None):
    try:
        res = subprocess.run(
            cmd, check=True, text=True,
            capture_output=capture, input=input_data, env=env,
        )
        return res.stdout.strip() if capture else None
    except FileNotFoundError:
        msg = f"команда не найдена: {cmd[0]}"
        if critical:
            die(msg)
        log_warn(f"{msg} — пропускаю")
        return None
    except subprocess.CalledProcessError:
        msg = f"команда завершилась с ошибкой: {' '.join(cmd)}"
        if critical:
            die(msg)
        log_warn(f"{msg} — пропускаю (не критично)")
        return None


def ask(prompt, default=None, validator=None, error_msg="Некорректное значение"):
    while True:
        suffix = f" [{default}]" if default else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if not val and default is not None:
            val = default
        if not val:
            log_err("Значение не может быть пустым")
            continue
        if validator and not validator(val):
            log_err(error_msg)
            continue
        return val


def main():
    if os.geteuid() != 0:
        die("Запускать только с правами root (из-под sudo/doas или live-ISO)")

    log_info("Поиск доступных дисков...")
    lsblk_out = run_cmd(["lsblk", "-dno", "NAME,SIZE,MODEL"], capture=True)
    available_disks = []
    for line in lsblk_out.splitlines():
        if line.strip() and "loop" not in line:
            print(f"  {line}")
            available_disks.append(line.split()[0])

    if not available_disks:
        die("Диски не найдены")

    disk_name = ask(
        "\nИмя диска (например nvme0n1 или sda)",
        validator=lambda v: v in available_disks,
        error_msg="Такого диска нет в списке выше",
    )
    disk = f"/dev/{disk_name}"
    p = "p" if "nvme" in disk_name else ""

    log_info(f"Текущие разделы {disk}:")
    run_cmd(["lsblk", disk], critical=False)

    print("\n==> Режим установки")
    print("1) Dualboot (существующий EFI, новый root)")
    print("2) Только Linux (диск размечен заранее под чистую установку)")
    mode = ask("Выбор", validator=lambda v: v in ("1", "2"), error_msg="Введите 1 или 2")

    format_efi = mode == "2"
    default_efi_num = "1"
    default_root_num = "4" if mode == "1" else "2"

    # Номера разделов запрашиваем явно — не угадываем их по режиму,
    # чтобы не отформатировать не тот раздел на нестандартной разметке.
    efi_num = ask("Номер EFI-раздела", default=default_efi_num,
                  validator=str.isdigit, error_msg="Введите номер раздела")
    root_num = ask("Номер root-раздела", default=default_root_num,
                   validator=str.isdigit, error_msg="Введите номер раздела")

    efi_part = f"{disk}{p}{efi_num}"
    root_part = f"{disk}{p}{root_num}"

    for part in (efi_part, root_part):
        if not os.path.exists(part):
            die(f"Раздел {part} не существует. Проверь разметку (lsblk / fdisk -l) и попробуй снова.")

    print(f"\n{YELLOW}[WARNING]{NC} Раздел {root_part} будет ОТФОРМАТИРОВАН (ext4).")
    if format_efi:
        print(f"{YELLOW}[WARNING]{NC} Раздел {efi_part} будет ОТФОРМАТИРОВАН (FAT32).")
    print("Все данные на этих разделах будут потеряны безвозвратно.")

    confirm = input(f"\nВведите точное имя root-раздела ({root_part}) для подтверждения: ").strip()
    if confirm != root_part:
        abort("Подтверждение не совпало. Установка отменена.")

    log_info(f"Форматирование root ({root_part}) в ext4...")
    run_cmd(["mkfs.ext4", "-F", root_part])

    if format_efi:
        log_info(f"Форматирование EFI ({efi_part}) в FAT32...")
        run_cmd(["mkfs.fat", "-F", "32", efi_part])

    log_info("Монтирование разделов...")
    if os.path.ismount("/mnt"):
        run_cmd(["umount", "-R", "/mnt"], critical=False)
    run_cmd(["mount", root_part, "/mnt"])
    os.makedirs("/mnt/boot", exist_ok=True)
    run_cmd(["mount", efi_part, "/mnt/boot"])

    log_info("Установка базовой системы (pacstrap)...")
    base_packages = [
        "base", "linux", "linux-firmware", "amd-ucode", "linux-headers",
        "base-devel", "networkmanager", "helix", "efibootmgr", "git",
        "python3", "openssh", "opendoas",
    ]
    run_cmd(["pacstrap", "-K", "/mnt"] + base_packages)

    log_info("Генерация /etc/fstab...")
    fstab_content = run_cmd(["genfstab", "-U", "/mnt"], capture=True)
    os.makedirs("/mnt/etc", exist_ok=True)
    with open("/mnt/etc/fstab", "w") as f:
        f.write(fstab_content + "\n")

    print("\n==> Конфигурация пользователя")
    hostname = ask(
        "Имя хоста",
        validator=lambda v: re.fullmatch(r"[a-zA-Z0-9-]+", v),
        error_msg="Только латиница, цифры и дефис",
    )

    while True:
        root_pass = getpass.getpass("\nПароль root: ")
        root_pass_confirm = getpass.getpass("Повтори пароль root: ")
        if not root_pass.strip():
            log_err("Пароль не может быть пустым")
            continue
        if root_pass != root_pass_confirm:
            log_err("Пароли не совпадают")
            continue
        break

    while True:
        username = input("\nИмя пользователя: ").strip().lower()
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username or ""):
            log_err("Некорректное имя пользователя (латиница в нижнем регистре, начинается с буквы/_)")
            continue
        user_pass = getpass.getpass(f"Пароль для {username}: ")
        user_pass_confirm = getpass.getpass("Повтори пароль: ")
        if not user_pass.strip():
            log_err("Пароль не может быть пустым")
            continue
        if user_pass != user_pass_confirm:
            log_err("Пароли не совпадают")
            continue
        print(f"\n  Хост: {hostname}\n  Пользователь: {username}")
        if input("Всё верно? (y/n): ").strip().lower() == "y":
            break

    log_info("Копирование post-setup.py в chroot...")
    src_post_setup = SCRIPT_DIR / "post-setup.py"
    if not src_post_setup.exists():
        die("post-setup.py не найден рядом с install.py")
    dst_post_setup = Path("/mnt/post-setup.py")
    shutil.copy(src_post_setup, dst_post_setup)
    os.chmod(dst_post_setup, 0o755)

    log_info("Вход в chroot и настройка системы...")
    env = os.environ.copy()
    env["ROOT_PASSWORD"] = root_pass
    env["USER_PASSWORD"] = user_pass
    try:
        run_cmd([
            "arch-chroot", "/mnt", "/post-setup.py",
            username, hostname, root_part,
        ], env=env)
    finally:
        # Пароли больше не нужны в памяти родительского процесса
        del root_pass, user_pass
        env.pop("ROOT_PASSWORD", None)
        env.pop("USER_PASSWORD", None)

    log_ok("\nУстановка завершена! Можно 'umount -R /mnt' и перезагружаться.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("\nПрервано пользователем", code=130)
    except Exception as e:  # последний рубеж — не показываем сырой traceback
        die(f"Неожиданная ошибка: {e}")
