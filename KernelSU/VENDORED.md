# KernelSU/ — vendored ReSukiSU source (not a git submodule)

This directory holds the kernel half of **ReSukiSU**, the community fork of
KernelSU that still supports non-GKI kernels (3.4+).  It is *vendored*: the
files are part of this repository instead of being pulled in as a git
submodule, because this tree is handed around as a tarball/zip and a submodule
would simply be lost.  (A nested `.git` is not an option either — git refuses
to track any path containing a `.git` component.)

## Provenance

| item | value |
|---|---|
| upstream | <https://github.com/ReSukiSU/ReSukiSU> |
| snapshot | `main` at/after tag `v4.2.0-rc2`; `uapi/` is byte-identical to that tag |
| obtained from | `https://codeload.github.com/ReSukiSU/ReSukiSU/tar.gz/refs/heads/main` |
| reported version | `KSU_VERSION = 35144`, `KSU_VERSION_FULL = v4.2.0-rc2-vendored@ReSukiSU` |
| matching manager | `ReSukiSU_v4.2.0-rc2_35144-arm64-v8a-release.apk` |

`35144` is upstream's own numbering (`30000 + commit count + 700`, the same
number the manager APK carries).  The official manager refuses any kernel
below `Natives.MINIMAL_SUPPORTED_KERNEL = 35002`, so the value is pinned in
`kernel/Kbuild` instead of being derived from git.

## What is kept

```
KernelSU/kernel/   the in-kernel driver (Kbuild, sources, tools/*.mk)
KernelSU/uapi/     shared uapi headers, included as "uapi/..."
KernelSU/LICENSE   GPL-2.0
```

`manager/` (Kotlin Android app), `userspace/` (Rust `ksud`), `js/`, `docs/`,
`scripts/`, `.github/` and the APK repacking helpers were removed: the kernel
build never touches them, and they were 26 of the 27 MB.  To update or to get
them back, download the upstream tarball again and repeat the steps below.

## Local changes to the vendored copy

Only `kernel/Kbuild` is modified (applied by
`work/sh/ZZ_ksu_vendored_patch.py`, which is anchored and idempotent):

1. **submodule check** — upstream does
   `test -e $(KSU_SRC)/../.git` and `$(error ...)`s out when it is missing;
   here it only prints a notice.
2. **version values** — git-derived `KSU_LOCAL_VERSION` / `KSU_TAG_NAME` are
   replaced by fixed values (`4444` → `35144`, `v4.2.0-rc2`) when no git
   metadata exists.
3. **SELinux headers** — `ccflags-y += -I$(objtree)/security/selinux`.
   `compat/kernel_compat.h` → `ss/policydb.h` → `ss/sidtab.h` → `"flask.h"`,
   and `flask.h`/`av_permissions.h` are *generated* by
   `security/selinux/Makefile` into the object tree.  Upstream builds in-tree
   (`objtree == srctree`) so its `-I$(srctree)/security/selinux` is enough;
   this tree is always built with `make O=out_*`, so the object tree has to be
   on the include path too, and `build_eebbk_clang11.sh` builds
   `security/selinux/ init/` up front (that also removes a `-j` race with
   `drivers/kernelsu`, which is built in parallel with those directories).

Everything else in `KernelSU/` is upstream code, untouched.

## Layout requirement

`drivers/kernelsu` is a **symlink** to `../KernelSU/kernel` (created exactly
the way upstream's `kernel/setup.sh` does it), and `drivers/Makefile` /
`drivers/Kconfig` reference it.  Clone this repository on a filesystem with
symlink support — e.g. inside WSL/Linux, which is how this kernel is built:

```sh
git clone https://github.com/Zhiyu722/android_kernel_eebbk_sm6150.git
cd android_kernel_eebbk_sm6150
ls -l drivers/kernelsu        # -> ../KernelSU/kernel
grep -n kernelsu drivers/Makefile drivers/Kconfig
```
