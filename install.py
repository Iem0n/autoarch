#!/usr/bin/env python3
import os
import sys
import subprocess
import getpass
import shutil

def run_cmd(cmd, check=True, text=True, capture=False):
    try:
        res = subprocess.run(cmd, check=check, text=text, capture_output=capture)
        return res.stdout.strip() if capture else None
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Failed: {' '.join(cmd)}\n{e}", file=sys.stderr)
        sys.exit(1)

def main():
    if os.geteuid() != 0:
        print("[ERROR] This script starts only with sudo", file=sys.stderr)
        sys.exit(1)

    print("==> targeting disk type...")

    #unmouting all disks, prevent errors
    run_cmd (["umount", "-a"])

    lsblk_out = run_cmd(["lsblk", "-dno", "NAME,SIZE,MODEL"], capture=True)
    available_disks = []
    
    for line in lsblk_out.splitlines():
        if "loop" not in line and line.strip():
            print(f"  {line}")
            available_disks.append(line.split()[0])

    disk_name = input("\nEnter disk name (nvme0n1 or sda or vda): ").strip()
    if disk_name not in available_disks:
        print(f"[ERROR] Disk {disk_name} not found!")
        sys.exit(1)

    disk = f"/dev/{disk_name}"
    p = "p" if "nvme" in disk_name else ""

    print("\n==> Load optios...")
    print("1) Dualboot")
    print("2) Only Linux (All disk will be foramted)")
    mode = input("(1/2): ").strip()

    if mode == "1":
        efi_part = f"{disk}{p}1"
        root_part = f"{disk}{p}4"
        format_efi = False
        print(f"\nDualboot: EFI ({efi_part}), Root {root_part}.")
    elif mode == "2":
        efi_part = f"{disk}{p}1"
        root_part = f"{disk}{p}2"
        format_efi = True
        print(f"\nOnly Linux: DISK WILL BE FORAMTED, EFI ({efi_part}), Root ({root_part}).")
    else:
        print("[ERROR] Invalid mode!")
        sys.exit(1)

    print(f"\n[WARNING] Part {root_part} will be formated!")
    if input("You sure? (y/n): ").strip().lower() != 'y':
        print("Install aborted.")
        sys.exit(0)

    print("\n==> Formating parts...")
    print(f"Formating root ({root_part}) in ext4...")
    run_cmd(["mkfs.ext4", "-F", root_part])

    if format_efi:
        print(f"Formating EFI ({efi_part}) in FAT32...")
        run_cmd(["mkfs.fat", "-F", "32", efi_part])

    print("\n=== Mounting partitions...")
    if os.path.ismount("/mnt"):
        run_cmd(["umount", "-a"], check=False)

    run_cmd(["mount", root_part, "/mnt"])
    os.makedirs("/mnt/boot", exist_ok=True)
    run_cmd(["mount", efi_part, "/mnt/boot"])

    print("\n==> Installing base system...")
    base_packages = [
        "base", "linux", "linux-firmware", "linux-headers", "amd-ucode",
        "base-devel", "networkmanager", "helix", "efibootmgr", "git", "python3", "openssh"
    ]
    run_cmd(["pacstrap", "-K", "/mnt"] + base_packages)

    print("\n==> Generating /etc/fstab...")
    fstab_content = run_cmd(["genfstab", "-U", "/mnt"], capture=True)
    os.makedirs("/mnt/etc", exist_ok=True)
    with open("/mnt/etc/fstab", "w") as f:
        f.write(fstab_content + "\n")

    print("\n==> User configuration")
    hostname = input("Enter host name: ").strip()

    while True:
        print("\n--- Root configuration ---")
        root_pass = getpass.getpass("Create password for root: ")
        root_pass_confirm = getpass.getpass("Repeat password root: ")
        if root_pass == root_pass_confirm:
            if not root_pass.strip():
                print("[ERROR] password cannot be empty!")
                continue
            break
        print("[ERROR] Passwords is not similar")

    while True:
        print("\n--- User configuration ---")
        username = input("Create username: ").strip().lower()
        if not username:
            print("[ERROR] Username cannot be empty!")
            continue
            
        user_pass = getpass.getpass(f"Create password for {username}: ")
        user_pass_confirm = getpass.getpass(f"Repeat password for {username}: ")
        
        if user_pass != user_pass_confirm:
            print("[ERROR] Passwords is not similar")
            continue
            
        if not user_pass.strip():
            print("[ERROR] Password cannot be empty!")
            continue

        print(f"  Host name:    {hostname}")
        print(f"  User name: {username}")
        if input("(y/n): ").strip().lower() == 'y':
            break

    print("\n==> Entering chroot...")
    shutil_target = "/mnt/post-setup.py"
    if os.path.exists("post-setup.py"):
        shutil.copy("post-setup.py", shutil_target)
    else:
        print("[ERROR] File post-setup.py not found in current directory!", file=sys.stderr)
        sys.exit(1)
        
    os.chmod(shutil_target, 0o755)

    run_cmd([
        "arch-chroot", "/mnt", "./post-setup.py", 
        username, hostname, root_part, root_pass, user_pass
    ])

    print("\nInstallation complete!")

    run_cmd(["umount", "-a"])
    run_cmd(["reboot"])

if __name__ == "__main__":
    main()
