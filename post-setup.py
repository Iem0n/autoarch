#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil

def run_cmd(cmd, check=True, text=True, capture=False, user_input=None):
    try:
        res = subprocess.run(cmd, check=check, text=text, capture_output=capture, input=user_input)
        return res.stdout.strip() if capture else None
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Command failed: {' '.join(cmd)}\n{e}", file=sys.stderr)
        sys.exit(1)

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)

def main():
    if len(sys.argv) < 6:
        print("[ERROR] DONT START THIS SCRIPT MANUALLY!", file=sys.stderr)
        sys.exit(1)

    user = sys.argv[1]
    host = sys.argv[2]
    root_part = sys.argv[3]
    root_pass = sys.argv[4]
    user_pass = sys.argv[5]

    if os.path.exists("/etc/localtime"):
        os.remove("/etc/localtime")
    os.symlink("/usr/share/zoneinfo/Europe/Warsaw", "/etc/localtime")
    run_cmd(["hwclock", "--systohc"])

    with open("/etc/locale.gen", "a") as f:
        f.write("en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n")
    run_cmd(["locale-gen"])

    write_file("/etc/locale.conf", "LANG=ru_RU.UTF-8\n")
    write_file("/etc/hostname", f"{host}\n")

    run_cmd(["passwd"], user_input=f"{root_pass}\n{root_pass}\n")
    run_cmd(["useradd", "-m", "-G", "wheel", "-s", "/bin/bash", user])
    run_cmd(["passwd", user], user_input=f"{user_pass}\n{user_pass}\n")

    sudoers_file = "/etc/sudoers.d/10-wheel"
    write_file(sudoers_file, "%wheel ALL=(ALL:ALL) ALL\n")
    os.chmod(sudoers_file, 0o440)

    run_cmd(["systemctl", "enable", "NetworkManager"])

    run_cmd(["bootctl", "install"])
    uuid = run_cmd(["blkid", "-s", "UUID", "-o", "value", root_part], capture=True)

    write_file("/boot/loader/loader.conf", "default  arch.conf\ntimeout  0\nconsole-mode max\n")
    
    arch_entry = (
        f"title   Arch Linux\n"
        f"linux   /vmlinuz-linux\n"
        f"initrd  /amd-ucode.img\n"
        f"initrd  /initramfs-linux.img\n"
        f"options root=UUID={uuid} rw quiet nowatchdog\n"
    )
    write_file("/boot/loader/entries/arch.conf", arch_entry)

    home_dir = f"/home/{user}"
    ssh_dir = f"{home_dir}/.ssh"
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    
    run_cmd(["chown", "-R", f"{user}:{user}", ssh_dir])

    key_path = f"{ssh_dir}/id_ed25519"
    if not os.path.exists(key_path):
        run_cmd([
            "sudo", "-u", user, "ssh-keygen", 
            "-t", "ed25519", 
            "-C", f"{user}@{host}", 
            "-f", key_path, 
            "-N", ""
        ])

    print("\n" + "="*60)
    print("ДОБАВЬ ЭТОТ ПУБЛИЧНЫЙ КЛЮЧ НА GITHUB:")
    with open(f"{key_path}.pub", "r") as pub_f:
        print(pub_f.read().strip())
    print("="*60 + "\n")

    dotfiles_dir = f"{home_dir}/my-dotfiles"
    if os.path.exists(dotfiles_dir):
        shutil.rmtree(dotfiles_dir)

    run_cmd(["sudo", "-u", user, "git", "clone", "https://github.com/Iem0n/arch_sync.git", dotfiles_dir])
    
    run_cmd(["sudo", "-u", user, "git", "-C", dotfiles_dir, "config", "user.name", "Iem0n"])
    run_cmd(["sudo", "-u", user, "git", "-C", dotfiles_dir, "config", "user.email", "vova.lemon@gmail.com"])
    run_cmd(["sudo", "-u", user, "git", "-C", dotfiles_dir, "remote", "set-url", "origin", "git@github.com:Iem0n/arch_sync.git"])

    if os.path.exists("/post-setup.py"):
        os.remove("/post-setup.py")

if __name__ == "__main__":
    main()
