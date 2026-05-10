#!/bin/bash
set -e

USER=$1
HOST=$2
ROOT=$3

echo "==> Setup time and locale..."
ln -sf /usr/share/zoneinfo/Europe/Warsaw /etc/localtime
hwclock --systohc

echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
echo "ru_RU.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen

echo "LANG=ru_RU.UTF-8" > /etc/locale.conf

echo "$HOST" >> /etc/hostname

echo "==> Creating root password..."
passwd

echo "==> Creating user..."
useradd -m -G wheel -s /bin/bash "$USER"

echo "Enter the password for $USER:"
passwd "$USER"

echo "Now You must manually give permissions for $USER"
echo 'Just uncomment this line ==> "%wheel ALL=(ALL:ALL) ALL"'
read -p "press enter to continue..."
EDITOR=nvim visudo

echo "==> Enabling NetworkManager..."
systemctl enable NetworkManager

echo "==> installing systemd-boot..."
bootctl install

# Получаем UUID для конфига загрузчика
UUID=$(blkid -s UUID -o value "$ROOT")

cat <<EOF > /boot/loader/loader.conf
default  arch.conf
timeout  0
console-mode max
EOF

cat <<EOF > /boot/loader/entries/arch.conf
title   Arch Linux
linux   /vmlinuz-linux
initrd  /amd-ucode.img
initrd  /initramfs-linux.img
options root=UUID=$UUID rw quiet nowatchdog
EOF

echo "==> loading dotfiles..."
su - "$USER" -c "git clone https://github.com/Iem0n/arch_sync.git ~/my-dotfiles"
su - "$USER" -c "cd ~/my-dotfiles && ./install.sh"

echo "==> installing greetd and tuigreet..."
pacman -S --noconfirm greetd greetd-tuigreet

echo "==> Configurating greetd..."
[ -f /etc/greetd/config.toml ] && mv /etc/greetd/config.toml /etc/greetd/config.toml.bak

cat <<EOF > /etc/greetd/config.toml
[terminal]
vt = 1

[default_session]
command = "tuigreet --time --remember --cmd 'dbus-run-session /home/vova/.local/bin/niri-session'"
user = "greeter"
EOF

echo "==> Enabling greetd service..."
systemctl enable greetd.service

echo "==> Generating ZRAM..."
pacman -S zram-generator
cat <<EOF > /etc/systemd/zram-generator.conf
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
EOF

read -p "Do You want edit mkinitcpio.conf? (y/n)" ANS
if [[ $ANS != "y" ]]; then
  echo "==> Ending chroot."
  echo "Your system is installed"
  read -p "Press enter and type 'umount -a' and after 'reboot'"
  exit 1
fi

nvim /etc/mkinitcpio.conf

mkinitcpio -P

echo "==> Ending chroot."
echo "Your system is installed"
read -p "Press enter and type 'umount -a' and after 'reboot'"
