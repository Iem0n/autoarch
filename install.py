#!/usr/bin/env python3
import os
import sys
import subprocess
import getpass
import shutil

def run_cmd(cmd, check=True, text=True, capture=False):
    """Безопасный запуск системных команд"""
    try:
        res = subprocess.run(cmd, check=check, text=text, capture_output=capture)
        return res.stdout.strip() if capture else None
    except subprocess.CalledProcessError as e:
        print(f"\n[ОШИБКА] Команда провалилась: {' '.join(cmd)}\n{e}", file=sys.stderr)
        sys.exit(1)

def main():
    if os.geteuid() != 0:
        print("[ОШИБКА] Этот скрипт нужно запускать через sudo: sudo python3 install.py", file=sys.stderr)
        sys.exit(1)

    print("=== Шаг 1: Определение целевого диска ===")
    lsblk_out = run_cmd(["lsblk", "-dno", "NAME,SIZE,MODEL"], capture=True)
    available_disks = []
    
    for line in lsblk_out.splitlines():
        if "loop" not in line and line.strip():
            print(f"  {line}")
            available_disks.append(line.split()[0])

    disk_name = input("\nВведите имя диска для установки (например, nvme0n1 или sda): ").strip()
    if disk_name not in available_disks:
        print(f"[ОШИБКА] Диск {disk_name} не найден в списке доступных!")
        sys.exit(1)

    disk = f"/dev/{disk_name}"
    p = "p" if "nvme" in disk_name else ""

    print("\n=== Шаг 2: Выбор режима разметки ===")
    print("1) Dualboot (EFI уже есть на p1, ставим Linux на p4)")
    print("2) Only Linux (Стираем диск, создаем EFI на p1, Linux на p2)")
    mode = input("Ваш выбор (1/2): ").strip()

    if mode == "1":
        efi_part = f"{disk}{p}1"
        root_part = f"{disk}{p}4"
        format_efi = False
        print(f"\nРежим Dualboot: Используем EFI ({efi_part}) без форматирования. Систему ставим на {root_part}.")
    elif mode == "2":
        efi_part = f"{disk}{p}1"
        root_part = f"{disk}{p}2"
        format_efi = True
        print(f"\nРежим Only Linux: Диск будет переформатирован! EFI ({efi_part}), Root ({root_part}).")
    else:
        print("[ОШИБКА] Неверный выбор режима!")
        sys.exit(1)

    print(f"\n[ВНИМАНИЕ] Раздел {root_part} БУДЕТ ФОРМАТИРОВАН (все данные сотрутся)!")
    if input("Вы уверены? Окончательное подтверждение (y/n): ").strip().lower() != 'y':
        print("Установка отменена.")
        sys.exit(0)

    print("\n=== Шаг 3: Форматирование разделов ===")
    print(f"Форматирование root ({root_part}) в ext4...")
    run_cmd(["mkfs.ext4", "-F", root_part])

    if format_efi:
        print(f"Форматирование EFI ({efi_part}) в FAT32...")
        run_cmd(["mkfs.fat", "-F", "32", efi_part])

    print("\n=== Шаг 4: Монтирование файловой системы ===")
    if os.path.ismount("/mnt"):
        run_cmd(["umount", "-R", "/mnt"], check=False)

    run_cmd(["mount", root_part, "/mnt"])
    os.makedirs("/mnt/boot", exist_ok=True)
    run_cmd(["mount", efi_part, "/mnt/boot"])

    print("\n=== Шаг 5: Установка базовых пакетов (pacstrap) ===")
    base_packages = [
        "base", "linux", "linux-firmware", "linux-headers", "amd-ucode",
        "base-devel", "networkmanager", "micro", "efibootmgr", "git", "python3"
    ]
    run_cmd(["pacstrap", "-K", "/mnt"] + base_packages)

    print("\n=== Шаг 6: Генерация /etc/fstab ===")
    fstab_content = run_cmd(["genfstab", "-U", "/mnt"], capture=True)
    os.makedirs("/mnt/etc", exist_ok=True)
    with open("/mnt/etc/fstab", "w") as f:
        f.write(fstab_content + "\n")

    print("\n=== Шаг 7: Настройка учетных записей ===")
    hostname = input("Введите имя хоста (имя ПК, например, vova-pc): ").strip()

    while True:
        print("\n--- Настройка суперпользователя (root) ---")
        root_pass = getpass.getpass("Введите пароль для root: ")
        root_pass_confirm = getpass.getpass("Повторите пароль для root: ")
        if root_pass == root_pass_confirm:
            if not root_pass.strip():
                print("[ОШИБКА] Пароль не может быть пустым!")
                continue
            break
        print("[ОШИБКА] Пароли для root не совпадают!")

    while True:
        print("\n--- Настройка основного пользователя ---")
        username = input("Введите имя пользователя (например, vova): ").strip().lower()
        if not username:
            print("[ОШИБКА] Имя пользователя не может быть пустым!")
            continue
            
        user_pass = getpass.getpass(f"Введите пароль для {username}: ")
        user_pass_confirm = getpass.getpass(f"Повторите пароль для {username}: ")
        
        if user_pass != user_pass_confirm:
            print("[ОШИБКА] Пароли пользователя не совпадают!")
            continue
            
        if not user_pass.strip():
            print("[ОШИБКА] Пароль не может быть пустым!")
            continue

        print(f"\nПроверьте данные конфигурации:")
        print(f"  Имя хоста:    {hostname}")
        print(f"  Пользователь: {username}")
        if input("Все верно? (y/n): ").strip().lower() == 'y':
            break

    print("\n=== Шаг 8: Запуск Stage 2 внутри chroot ===")
    shutil_target = "/mnt/post-setup.py"
    if os.path.exists("post-setup.py"):
        shutil.copy("post-setup.py", shutil_target)
    else:
        print("[ОШИБКА] Файл post-setup.py не найден в текущей папке!", file=sys.stderr)
        sys.exit(1)
        
    os.chmod(shutil_target, 0o755)

    print(f"\n--> Передаем управление в chroot...")
    run_cmd([
        "arch-chroot", "/mnt", "/usr/bin/python3", "/post-setup.py", 
        username, hostname, root_part, root_pass, user_pass
    ])

    print("\n=== БАЗОВАЯ УСТАНОВКА ЗАВЕРШЕНА ===")
    print("Выполните команды:\n  umount -R /mnt\n  reboot")
    print("\nПосле перезагрузки войдите под своим пользователем, зайдите в папку ~/my-dotfiles и запустите локальный скрипт.")

if __name__ == "__main__":
    main()
