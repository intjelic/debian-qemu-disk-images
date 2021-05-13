# Debian QEMU Disk Images

This repository provides a script that produces ready-to-use Debian disk images
for the common supported architectures, and comes with the instructions to
be used with QEMU. It's also making some of those disk images
ready-to-download and are configured with 10G disk space, 512M swap (available
for stretch, buster, armhf, arm64 and amd64).

> This script was written to run on Debian 10 running on a classic x86_64 computer and as root. It's unlikely to complete successfully if your environment is different and you're advised to use a Docker container with extended privileges (pass the --privileged flag), or just let **Gihtub Actions** does the work for you by forking this repository.

**Download Images:** https://github.com/intjelic/debian-qemu-disk-images/actions (pick the last executed workflow and then pick the variation of the artifact you're interested in).

Making those kind of images can already be complex enough as there are billions
of customizations, and things that can go wrong. That said, most people just
want a decent, working, and simple to use, with the instructions provided. This
is why this script is meant to run on a specific environment and doesn't alow
hundreds of configuration possible. You're free to adjust the scripts according
to your needs though.

```
python3 make-debian-qemu-images.py \
  --arch arm64 \         # default is amd64
  --version buster \     # default is buster
  --variant essential \
  --packages foo,bar \
  --disk-size 10240 \
  --swap-size 512 \ in MiB
  --image-format \
  my-image.img
```

The output will be foobar.

The script will produce unconditionally a GTP table, with 3 partitions which
are...

- a boot loader partition with size 512Mib and format fat32 named ESP
- a swap partition of custom size (use the `--swap-size` flag)
- a main partition using the remaining size of the disk with format ext4

And they are to be used with QEMU provided EFI (no use of u-boot).


