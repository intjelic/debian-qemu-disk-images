# This script creates disk images with the Debian version (stretch or buster)
# and architecture (armhf, arm64 and amd64) of your choice, suitable to be
# used with QEMU. It's released under the MIT license.
#
# It must be run on Debian 10 on a classic x86_64 computer and as root. You're
# better off using a Docker container with the --priviledges, -v devdev and
# --foo flags, or simply let Github Actions does the job.
#
# Basic usage of this script:
#
# python3 make-debian-qemu-images.py
#   --arch arm64 \
#   --version buster \
#   --variant standard \
#   --packages build-essentials,cmake,python3-all-dev \
#   --disk-size 4086 \
#   --swap-size 512 \
#   --image-format qcow2 \
#   my-debian-disk.qcow2
#
# Fore more information, run the script with the --help flag.
#
# Written by Jonathan De Wachter <dewachter.jonathan@gmail.com>, May 2021

import sys
import time
import os.path
import subprocess
import tempfile
import shutil
import contextlib

try:
    import click
except ModuleNotFoundError:
    print("missing dependency; the 'python3-click' package must be installed")
    exit(1)

SUPPORTED_ARCHITECTURES = ['armhf', 'arm64', 'amd64']
SUPPORTED_VERSIONS = ['stretch', 'buster']
SUPPORTED_IMAGE_FORMATS = "cloop copy-on-read dmg nbd qcow qcow2 qed quorum raw rbd sheepdog vdi vhdx vmdk vpc vvfat".split(' ')

def check_arguments(args):
    assert args['arch'] in SUPPORTED_ARCHITECTURES, "targetted architecture is incorrect; supported values are 'armhf', 'arm64' and 'amd64'"
    assert args['version'] in SUPPORTED_VERSIONS, "version is incorrect; supported values are 'stretch' or 'buster'"

    assert args['variant'] in ['essential', 'required', 'important', 'standard'], "variant value is incorrect"

    assert args['swap_size'] == 0 or args['swap_size'] >= 256, "swap size should be at least 256MiB according to system minimum requirements"
    assert args['swap_size'] <= args['disk_size'], "swap size should not be bigger than the disk size"

    assert args['disk_size'] >= 2048, "disk size should be at least 2GiB according to system minimum requirements"
    # assert disk_size >= 512 + swap_size + 2048
    assert args['disk_size'] / 2 >= args['swap_size'], "disk size does not seem so right when looking at the swap size"

    assert args['image_format'] in SUPPORTED_IMAGE_FORMATS, "image format not supported"

    if not args['hostname']:
        print(f"No hostname provided, defaulting to '{args['version']}'")
        args['hostname'] = args['version']

def check_dependencies(arch):
    if not shutil.which('mkfs.vfat'):
        print("missing dependency; the 'dosfstools' package must be installed")
        exit(1)

    if not shutil.which('mkfs.ext4'):
        print("missing dependency; the 'e2fsprogs' package must be installed")
        exit(1)

    if not shutil.which('mkswap'):
        print("missing dependency; the 'util-linux' package must be installed")
        exit(1)

    if not shutil.which('parted'):
        print("missing dependency; the 'parted' package must be installed")
        exit(1)

    if not shutil.which('qemu-img'):
        print("missing dependency; the 'qemu-utils' package must be installed")
        exit(1)

    # If targetting a non-x86 architecture, the script requires two more packages
    if arch in ['armhf', 'arm64']:
        if not shutil.which('update-binfmts'):
            print("missing dependency; the 'binfmt-support' package must be installed")
            exit(1)

        if not shutil.which('qemu-arm-static') and not shutil.which('qemu-aarch64-static'):
            print("missing dependency; the 'qemu-user-static' package must be installed")
            exit(1)

def compute_packages(user_packages, args):
    # Start off with Debian keyrings packages (TODO; check if they're really
    # necessary)
    packages = [
        'debian-keyring',
        'debian-archive-keyring'
    ]

    # Kernel and boot loader packages (architecture-specific)
    if args['arch'] == 'armhf':
        packages.append('linux-image-armmp-lpae:armhf')
        packages.append('grub-efi-arm')
    elif args['arch'] == 'arm64':
        packages.append('linux-image-arm64')
        packages.append('grub-efi-arm64')
    elif args['arch'] == 'amd64':
        packages.append('linux-image-amd64')
        packages.append('grub-efi-amd64')

    # Network-related packages
    packages.extend([
        'ifupdown',
        'isc-dhcp-client'
    ])

    # Additional packages (TODO; check if they're really necessary)
    packages.extend([
        'initramfs-tools',
        'kmod',
        'e2fsprogs',
        'btrfs-progs',
        'locales',
        'tzdata',
        'apt-utils',
        'whiptail',
        'debconf-i18n',
        'keyboard-configuration',
        'console-setup'
    ])

    # User-requested additional packages
    if user_packages != '':
        packages.extend(user_packages.split(','))

    # Remove duplicates
    packages = list(set(packages))

    return packages

def compute_summary_message(vars):
    debian_version_map = {
        'stretch': 9,
        'buster': 10
    }
    version_number = debian_version_map[vars['version']]

    message = "\n"
    message += f"You are going to create a disk image of size \
{vars['disk_size']}MiB with Debian {version_number} ({vars['version']}) \
installed on it and for the {vars['arch']} architecture.\n"

    message += "\n"

    message += "The disk will have a GPT table with the following partitions:\n"
    message += "\n"
    for index, (name, size, format, _, _) in enumerate(vars['partitions']):
        message += f"- Partition #{index+1} (name: {name}, size: {size}MiB, format: {format})\n"

    message += "\n"

    message += "The following packages will be explicitly installed (includes \
packages needed to perform the installation and user-requested packages, \
excludes packages implicitly installed by the chosen variant).\n"

    message += "\n"
    for package in vars['packages']:
        message += f"- {package}\n"
    message += "\n"

    message += "Foo\n"
    message += "Bar\n"

    return message

@contextlib.contextmanager
def attach_to_loop_device(disk_path, loop_device):
    print(f"Attach {disk_path} as loopback device {loop_device}")
    subprocess.run(['losetup', loop_device, disk_path])
    subprocess.run(['partprobe', loop_device])
    time.sleep(0.25)

    try:
        yield
    finally:
        print(f"Dettach {loop_device}")
        subprocess.run(['losetup', '-d', loop_device])

@contextlib.contextmanager
def mount_root_partition(loop_device, mount_dir):
    print(f"Mount root partition on {mount_dir}")
    subprocess.run([
        'mount',
        '-t', 'ext4',
        '-o', 'async,lazytime,discard,noatime,nobarrier,commit=3600,delalloc,noauto_da_alloc,data=writeback',
        f'{loop_device}p2', mount_dir])

    try:
        yield
    finally:
        print("Unmount root partition")
        subprocess.run(['umount', mount_dir])

@contextlib.contextmanager
def mount_boot_partition(loop_device, mount_dir):
    boot_mount_dir = os.path.join(mount_dir, "boot/efi")
    os.mkdir(boot_mount_dir) # '/boot' exists but not '/boot/efi'

    print(f"Mount boot partition on {boot_mount_dir}")
    subprocess.run([
        'mount',
        '-o', 'async,discard,lazytime,noatime',
        f'{loop_device}p1', boot_mount_dir])
    try:
        yield
    finally:
        print("Unmount boot partition")
        subprocess.run(['umount', boot_mount_dir])

@contextlib.contextmanager
def mount_transient_files(mount_dir):
    print("mounting transient files")
    time.sleep(0.5)
    subprocess.run(['mount', '--bind', '/dev',     os.path.join(mount_dir, 'dev')])
    time.sleep(0.5)
    subprocess.run(['mount', '--bind', '/dev/pts', os.path.join(mount_dir, 'dev/pts')])
    subprocess.run(['mount', '--bind', '/sys',     os.path.join(mount_dir, 'sys')])
    subprocess.run(['mount', '--bind', '/proc',    os.path.join(mount_dir, 'proc')])
    time.sleep(0.5)

    try:
        yield
    finally:
        subprocess.run(['umount', '-f', os.path.join(mount_dir, 'proc')])
        subprocess.run(['umount', '-f', os.path.join(mount_dir, 'sys')])
        subprocess.run(['umount', '-f', os.path.join(mount_dir, 'dev/pts')])
        subprocess.run(['umount', '-f', os.path.join(mount_dir, 'dev')])

def create_disk_image(tmp_dir, disk_size):
    # The name and format 'disk.img' is temporary; it will be renamed and
    # converted according to user's request later.
    disk_path = os.path.join(tmp_dir, 'disk.img')

    process = subprocess.run([
        'qemu-img', 'create',
        '-f', 'raw',
        '-o', 'preallocation=off',
        '-o', 'nocow=off',
        disk_path,
        f'{disk_size}M' # QEMU only supports the M prefix which is equivalent to MiB
    ])
    assert process.returncode == 0, "failed to create the raw disk image"

    return disk_path

def partition_disk(disk_path, disk_size, swap_size):

    # Partitioning the disk (three partitions under a GPT table).
    process = subprocess.run(['parted', disk_path, 'mktable', 'gpt'])
    assert process.returncode == 0, "failed to create gpt table"
    print("Disk's GPT table created")

    process = subprocess.run(['parted', disk_path, 'mkpart', 'ESP', 'fat32', '0%', '512MiB'])
    assert process.returncode == 0, "failed to create the boot partition"
    print("Disk's partition #1 created (fat32, 512MiB, named 'ESP')")

    between = str(disk_size - swap_size)
    partition_size = disk_size - 512 - swap_size
    process = subprocess.run(['parted', disk_path, 'mkpart', 'ROOT', 'ext4', '512MiB', f'{between}MiB'])
    assert process.returncode == 0, "failed to create the root partition"
    print(f"Disk's partition #2 created (ext4, {partition_size}MiB, named 'ROOT')")

    process = subprocess.run(['parted', disk_path, 'mkpart', 'SWAP', 'linux-swap', f'{between}MiB', '100%'])
    assert process.returncode == 0, "failed to create the swap partition"
    print(f"Disk's partition #3 created (swap, {swap_size}MiB)")

def format_partitions(loop_device):
    subprocess.run(['mkfs.vfat', '-F', '32', '-n', 'ESP', f'{loop_device}p1'])
    print("Partition #1 is formatted (fat32)")

    subprocess.run(['mkfs.ext4', f'{loop_device}p2'])
    print("Partition #2 is formatted (ext4)")

    subprocess.run(['mkswap', '-L', 'SWAP', f'{loop_device}p3'])
    print("Partition #3 is formatted (swap)")

def create_chroot_environment(mount_dir, arch, version, variant, mirror, packages):
    mmdebstrap_args = [
        'mmdebstrap',
        '--architectures', arch,
        '--variant', variant,
        '--components', '"main"',
        '--include', ','.join(packages),
        version,
        mount_dir
    ]
    if mirror:
        mmdebstrap_args.append(mirror)

    subprocess.run(mmdebstrap_args)

def run_chroot_command(command, mount_dir, arch):
    chroot_command = [
        'chroot',
        mount_dir
    ]

    if arch == 'armhf':
        chroot_command.apend('qemu-arm-static')
    elif arch == 'arm64':
        chroot_command.append('qemu-aarch64-static')

    chroot_command.extend(['/bin/bash', '-c'])

    chroot_command.append('"' + ' '.join(command) + '"')

    print("running command " + str(chroot_command))
    os.system(' '.join(chroot_command))

def configure_hostname(mount_dir, name):
    file = open(os.path.join(mount_dir, 'etc/hostname'), 'w')
    file.write(name + '\n')
    file.close()

def configure_fstab(mount_dir):
    file = open(os.path.join(mount_dir, 'etc/fstab'), 'w')
    file.writelines([
        'LABEL=ROOT / ext4 rw,async,lazytime,discard,strictatime,nobarrier,commit=3600 0 1\n',
        'LABEL=ESP /boot/efi vfat rw,async,lazytime,discard 0 2\n',
        'LABEL=SWAP none swap sw,discard 0 0\n'
    ])
    file.close()

def configure_network_interfaces(mount_dir):
    file = open(os.path.join(mount_dir, 'etc/network/interfaces'), 'w')
    file.writelines([
        'auto eth0\n',
        'iface eth0 inet dhcp\n'
    ])
    file.close()

@click.command()
@click.option('--arch',          default='amd64',    help='The architecture to target (amd64, armhf or arm64).')
@click.option('--version',       default='buster',   help='The Debian version to install (stretch or buster).')
@click.option('--variant',       default='standard', help='The kind of packages to install by default (essential, required, important or standard). Consult mmdebstrap documentation for more information.')
@click.option('--packages',      default='',         help='Additional packages to install (must be a comma-separated value).')
@click.option('--mirror',        default=None,       help='To be written')
@click.option('--disk-size',     default=10240,      help='Size of the disk to create in MiB (by default 10240Mib, which is 10G)')
@click.option('--swap-size',     default=512,          help='Size of the swap to create in MiB (by default 512MiB)')
@click.option('--image-format',  default='raw',      help='The format of the disk image (by default raw, but can be any of QEMU\'s supported formats)')
@click.option('--root-password', default='root',     help='The password of the root system user, by default it\'s \'root\'')
@click.option('--hostname',      default=None,       help='The hostname (by default it\'s the name of the Debian version)')
@click.option('--no-confirm',    default=False,      help='To be written')
@click.argument('output')
def script(arch, version, variant, packages, mirror, disk_size, swap_size, image_format, root_password, hostname, no_confirm, output):
    """ Brief description.

    Long description.
    """

    # Checking validity of the command-line arguments.
    check_arguments(locals())

    # Checking if dependencies for this script are installed.
    check_dependencies(arch)

    # Make sure output value is correct and we won't run into any issue at the
    # final step (moving the result to its final location). We check the file
    # does not exist, and if its parent directory does exist.
    output = os.path.abspath(output)
    assert not os.path.exists(output), "output value is incocrect; destination exists"
    assert os.path.isdir(os.path.dirname(output)), "output value is incorrect; parent folder does not exist"

    # Compute partitions info (todo; compute actual infos)
    partitions = [
        ('esp',  512, 'fat32', 42, 42),
        ('root', 512, 'ext4',  42, 42),
        ('swap', 512, 'swap',  42, 42)
    ]

    # Compute list of packages that will be explicitly installed.
    packages = compute_packages(packages, locals())

    # Printing summary and asking for confirmation.
    summary_mesage = compute_summary_message(locals())

    if not no_confirm:
        summary_mesage += \
            "\nPass the --no-confirm flag if you don't want to be prompted for confirmation.\n"

    print(summary_mesage)

    if not no_confirm:
        is_confirmed = input("Do you confirm those options ? [y/n] ")
        if not is_confirmed.lower().startswith('y'):
            print("Abort!")
            exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"Creating a raw disk image of size {disk_size}MiB")
        disk_path = create_disk_image(tmp_dir, disk_size)

        print("Partitioning the disk...")
        partition_disk(disk_path, disk_size, swap_size)

        loop_device = '/dev/loop42'
        with attach_to_loop_device(disk_path, loop_device):
            print("Formatting partitions...")
            format_partitions(loop_device)

            mount_dir = os.path.join(tmp_dir, 'mnt')
            os.mkdir(mount_dir)

            with mount_root_partition(loop_device, mount_dir):
                create_chroot_environment(mount_dir, arch, version, variant, mirror, packages)

                # In order to chroot into a filesystem with an architecture
                # different than the host, we need to install a binary
                # interpreter.
                if arch == 'armhf':
                    print("Copying qemu-arm-static to the chroot environment")
                    shutil.copy2('/usr/bin/qemu-arm-static', os.path.join(mount_dir, 'usr/bin/'))
                elif arch == 'arm64':
                    print("Copying qemu-aarch64-static to the chroot environment")
                    shutil.copy2('/usr/bin/qemu-aarch64-static', os.path.join(mount_dir, 'usr/bin/'))

                with mount_boot_partition(loop_device, mount_dir):
                    with mount_transient_files(mount_dir):
                        # Configure the GRUB boot loader.
                        if arch == 'armhf':
                            grub_package = 'grub-efi-arm'
                            grub_target = 'arm-efi'
                        elif arch == 'arm64':
                            grub_package = 'grub-efi-arm64'
                            grub_target = 'arm64-efi'
                        elif arch == 'amd64':
                            grub_package = 'grub-efi-amd64'
                            grub_target = 'x86_64-efi'

                        update_system_cmd = ['apt-get', 'update']
                        run_chroot_command(update_system_cmd, mount_dir, arch)

                        install_grub_pkg_cmd = ['apt-get', 'install', '-y', '--install-recommends', grub_package]
                        run_chroot_command(install_grub_pkg_cmd, mount_dir, arch)

                        purge_osprober_cmd = ['apt-get', '--autoremove', '-y', 'purge', 'os-prober']
                        run_chroot_command(purge_osprober_cmd, mount_dir, arch)

                        # Adjust the '/etc/default/grub' file
                        with open(os.path.join(mount_dir, 'etc/default/grub'), 'r') as file:
                            text = file.read()

                        # TODO; adjust text variable

                        with open(os.path.join(mount_dir, 'etc/default/grub'), 'w') as file:
                            file.write(text)

                        grub_mkconfig_cmd = ['grub-mkconfig', '-o', '/boot/grub/grub.cfg']
                        run_chroot_command(grub_mkconfig_cmd, mount_dir, arch)

                        grub_install_cmd = [
                            'grub-install',
                            f'--target={grub_target}',
                            '--force-extra-removable',
                            '--no-nvram',
                            '--no-floppy',
                            '--modules=\\"part_msdos part_gpt\\"',
                            '--grub-mkdevicemap=/boot/grub/device.map',
                            loop_device
                        ]
                        run_chroot_command(grub_install_cmd, mount_dir, arch)

                    print("Updating /etc/hostname")
                    configure_hostname(mount_dir, 'foo')

                    print("Updating /etc/fstab")
                    configure_fstab(mount_dir)

                    print("Updating /etc/network/interfaces")
                    configure_network_interfaces(mount_dir)

                # TODO; run user provided script here...

                # Remove the binary interpreter from the chroot environment.
                if arch == 'armhf':
                    print("Removing qemu-arm-static from the chroot environment")
                    os.remove(os.path.join(mount_dir, 'usr/bin/qemu-arm-static'))
                elif arch == 'arm64':
                    print("Removing qemu-aarch64-static from the chroot environment")
                    os.remove(os.path.join(mount_dir, 'usr/bin/qemu-aarch64-static'))

        # Convert raw disk image to the requested format and and move the result to
        # the requested location.
        if image_format != 'raw':
            print(f"Converting disk image to {image_format} format...")

            new_disk_path = os.path.join(tmp_dir, 'disk.' + image_format)
            subprocess.run([
                'qemu-img', 'convert',
                '-f', 'raw',
                '-O', image_format,
                disk_path, new_disk_path
            ])

            disk_path = new_disk_path

        shutil.move(disk_path, output)

        print("Done!")

if __name__ == '__main__':
    script()
