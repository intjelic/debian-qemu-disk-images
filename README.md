# Debian QEMU Disk Images

This repository provides a script that produces ready-to-use Debian disk images
for the common supported architectures, and comes with the instructions to
be used with QEMU. It's also making some of those disk images
ready-to-download and are configured with 10G disk space, 512M swap (available
for stretch, buster, armhf, arm64 and amd64).

> This script was written to run on Debian 10 running on a classic x86_64 computer and as root. It's unlikely to complete successfully if your environment is different and you're advised to use a Docker container with extended privileges (pass the --privileged flag), or just let **Gihtub Actions** does the work for you by forking this repository.

**Download Images:** https://github.com/intjelic/debian-qemu-disk-images/actions (pick the last executed workflow and then pick the variation of the disk image you're interested in).

Making those kind of images is not straight-forward for most of people,
thousands of configurations are possible, and many things that can go wrong.
However, most of us just want a "standard" and working image, and with the
instructions to use with QEMU. This is the problem this script is solving. It's
kept relatively simple and the resulting disk image comes with the command
lines to start experimenting with right away.

Basic usage of this script:

```
python3 make-debian-qemu-images.py \
  --arch arm64 \
  --version buster \
  --variant standard \
  --packages build-essentials,cmake,python3-all-dev \
  --disk-size 10240 \ # in MiB
  --swap-size 512 \   # in MiB
  --image-format qcow2 \
  my-disk.qcow2
```

Fore more information, run the script with the --help flag.

**Note:** The output of `python3 make-debian-qemu-images.py --help` is added to
the end of this README.

**Self-hosted Github runners on ARM/ARM64**

This script was primarily written to provide self-hosted Github runners on
ARM, but with hardware constrained to x86_64 only. The list of supported OSes
by the Github runner is also small and limiting, and Debian 10 turns out to be
one among the few OSes that is able to run the Github runner on the two
variants of the ARM architecture.

Other than the cost of emulation, which can be mitigated by allocating more
resources to the QEMU VMs, the Github runners run perfectly with the images
produced by this script.

Therefore, it's also making a variant of the downloadable images with the
latest version of Docker pre-installed and a user system named `runner`
(because it requires a non-root user).

**Tweaking the QEMU VMs**

To be written.

**Output with the --help flag**

To be written.