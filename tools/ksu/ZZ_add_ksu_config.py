#!/usr/bin/env python3
"""Append the ReSukiSU Kconfig block to a kernel config file (idempotent)."""
import io, sys

BLOCK = '''
#
# ReSukiSU (KernelSU fork) -- manual hook, for this 4.14 (msm-4.14) tree
#   KSU_MANUAL_HOOK          : no GKI tracepoints on 4.14, manual hooks required
#   KSU_TRACEPOINT_HOOK      : 5.10+ only, must stay off
#   KSU_MANUAL_HOOK_AUTO_*   : LSM/input-handler setuid+init.rc+input hooks (y)
#   KSU_DEBUG                : verbose KSU logging while testing
#
CONFIG_KSU=y
CONFIG_KSU_MANUAL_HOOK=y
# CONFIG_KSU_TRACEPOINT_HOOK is not set
CONFIG_KSU_DEBUG=y
CONFIG_KSU_MULTI_MANAGER_SUPPORT=y
# CONFIG_KSU_DISABLE_MANAGER is not set
'''

for path in sys.argv[1:]:
    s = io.open(path, encoding='utf-8', errors='surrogateescape').read()
    if 'CONFIG_KSU=y' in s:
        print('%s: KSU block already present' % path)
        continue
    if not s.endswith('\n'):
        s += '\n'
    io.open(path, 'w', encoding='utf-8', errors='surrogateescape').write(s + BLOCK)
    print('%s: appended KSU block' % path)
