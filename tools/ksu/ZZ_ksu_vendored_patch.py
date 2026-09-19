#!/usr/bin/env python3
"""Two vendoring fixes for KernelSU/kernel/Kbuild in this kernel tree.

1) KernelSU hard-errors out unless KernelSU/.git exists:

       LOCAL_GIT_EXISTS := $(shell test -e $(KSU_SRC)/../.git && echo 1 || echo 0)
       ifeq ($(LOCAL_GIT_EXISTS),0)
       $(error You should use $(REPO_NAME) as a git submodule ...)
       endif

   Upstream expects `KernelSU/setup.sh` to clone KernelSU as a real submodule.
   This kernel ships KernelSU *inside* the kernel repository instead (a
   submodule would not survive the tarball/zip handoff used here, and git
   refuses to track any path with a ".git" component), so the version values
   are fixed instead of being derived from git.

2) KernelSU includes the SELinux internals (compat/kernel_compat.h ->
   ss/policydb.h -> ss/sidtab.h -> "flask.h").  flask.h and
   av_permissions.h are *generated* by security/selinux/Makefile into the
   object tree; upstream builds in-tree, where $(objtree) == $(srctree) and
   `-I$(srctree)/security/selinux` finds them.  This tree is always built with
   `make O=out_*`, so the object tree has to be on the include path as well
   (build_eebbk_clang11.sh generates the two headers before the kernel build,
   which also removes the parallel-build race between security/ and drivers/).

Every chunk is anchored and idempotent; nothing is written unless the anchor
matches exactly once.
"""
import io, os, sys

KBUILD = 'KernelSU/kernel/Kbuild'

CHUNKS = [
    # (name, marker meaning "already applied", old, new)
    ('git-submodule check',
     'vendored inside this kernel tree',
     '''ifeq ($(LOCAL_GIT_EXISTS),0)
$(info -- Can't find $(REPO_NAME) git submodule!)
$(info -- If you are using bazel to build this kernel,)
$(info -- Please go to Kbuild and change KSU_SRC to the absolute path of the KSU kernel folder.)
$(error You should use $(REPO_NAME) as a git submodule instead of copying code directly)
endif
''',
     '''ifeq ($(LOCAL_GIT_EXISTS),0)
$(info -- $(REPO_NAME) is vendored inside this kernel tree: no KernelSU/.git)
$(info -- Using fixed version values; see EEBBK_S6_changes.md / docs.)
endif
'''),

    ('git-derived version values',
     'EEBBK S6: vendored copy',
     '''$(shell cd $(KSU_SRC); [ -f ../.git/shallow ] && $(GIT_BIN) fetch --unshallow)
KSU_LOCAL_VERSION := $(shell cd $(KSU_SRC); $(GIT_BIN) rev-list --count HEAD)
KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)

KSU_TAG_NAME    := $(shell cd $(KSU_SRC); $(GIT_BIN) describe --abbrev=0 --tags 2>/dev/null || echo "v4.1.0")
KSU_COMMIT_SHA  := $(shell cd $(KSU_SRC); $(GIT_BIN) rev-parse --short=8 HEAD 2>/dev/null || echo "unknown")
ifneq ($(shell cd $(KSU_SRC); $(GIT_BIN) diff-index --quiet HEAD; echo $$?),0)
KSU_COMMIT_SHA  := $(KSU_COMMIT_SHA)-dirty
endif
KSU_BRANCH_NAME := $(shell cd $(KSU_SRC); $(GIT_BIN) branch --show-current 2>/dev/null || echo "unknown")
''',
     '''ifeq ($(LOCAL_GIT_EXISTS),1)
$(shell cd $(KSU_SRC); [ -f ../.git/shallow ] && $(GIT_BIN) fetch --unshallow)
KSU_LOCAL_VERSION := $(shell cd $(KSU_SRC); $(GIT_BIN) rev-list --count HEAD)
KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)

KSU_TAG_NAME    := $(shell cd $(KSU_SRC); $(GIT_BIN) describe --abbrev=0 --tags 2>/dev/null || echo "v4.1.0")
KSU_COMMIT_SHA  := $(shell cd $(KSU_SRC); $(GIT_BIN) rev-parse --short=8 HEAD 2>/dev/null || echo "unknown")
ifneq ($(shell cd $(KSU_SRC); $(GIT_BIN) diff-index --quiet HEAD; echo $$?),0)
KSU_COMMIT_SHA  := $(KSU_COMMIT_SHA)-dirty
endif
KSU_BRANCH_NAME := $(shell cd $(KSU_SRC); $(GIT_BIN) branch --show-current 2>/dev/null || echo "unknown")
else
# EEBBK S6: vendored copy, no git metadata available.
KSU_LOCAL_VERSION := 0
KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)
KSU_TAG_NAME    := v4.1.0
KSU_COMMIT_SHA  := vendored
KSU_BRANCH_NAME := vendored
endif
'''),

    ('SELinux headers from the object tree',
     'flask.h lives in $(objtree)',
     '''ccflags-y += -I$(srctree)/security/selinux -I$(srctree)/security/selinux/include
''',
     '''ccflags-y += -I$(srctree)/security/selinux -I$(srctree)/security/selinux/include
# EEBBK S6: with `make O=out_*` the generated SELinux headers (flask.h lives in
# $(objtree)/security/selinux) are not in $(srctree), where upstream finds them.
ccflags-y += -I$(objtree)/security/selinux
'''),

    ('version code must satisfy the manager',
     'KSU_LOCAL_VERSION := 4444',
     '''# EEBBK S6: vendored copy, no git metadata available.
KSU_LOCAL_VERSION := 0
KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)
KSU_TAG_NAME    := v4.1.0
KSU_COMMIT_SHA  := vendored
KSU_BRANCH_NAME := vendored
''',
     '''# EEBBK S6: vendored copy, no git metadata available.
# Upstream derives this from the commit count: 30000 + commits + 700, the same
# number the manager APK carries.  The vendored snapshot is main at/after
# v4.2.0-rc2 (its uapi/ is byte-identical to that tag), and the official
# manager refuses kernels below Natives.MINIMAL_SUPPORTED_KERNEL = 35002, so
# report the v4.2.0-rc2 release number 35144 and install that manager APK.
KSU_LOCAL_VERSION := 4444
KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)
KSU_TAG_NAME    := v4.2.0-rc2
KSU_COMMIT_SHA  := vendored
KSU_BRANCH_NAME := vendored
'''),
]

def read(p):
    return io.open(p, encoding='utf-8', errors='surrogateescape').read()

def write(p, s):
    io.open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)

def main():
    tree = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    full = os.path.join(tree, KBUILD)
    s = read(full)
    out = s
    bad = 0
    for name, marker, old, new in CHUNKS:
        if marker in out:
            print('SKIP (already applied)  %s' % name)
            continue
        n = out.count(old)
        if n != 1:
            print('ANCHOR x%-3d            %s' % (n, name))
            bad += 1
            continue
        out = out.replace(old, new, 1)
        print('OK                     %s' % name)
    if bad:
        print('\n%d chunk(s) failed - nothing written' % bad)
        return 1
    if out != s:
        write(full, out)
        print('\nwrote %s' % KBUILD)
    else:
        print('\nnothing to do')
    return 0

if __name__ == '__main__':
    sys.exit(main())
