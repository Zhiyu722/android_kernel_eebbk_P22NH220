#!/usr/bin/env python3
"""Dry-run the hook patcher: report how many times each anchor matches.
Usage: python3 ZZ_check_anchors.py <kernel-tree>
Never writes anything.
"""
import importlib.util, io, os, sys

TREE = sys.argv[1] if len(sys.argv) > 1 else '/root/kernel/android_kernel_eebbk_sm6150-main'
PATCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ZZ_ksu_hooks_apply.py')
if not os.path.exists(PATCHER):
    PATCHER = '/mnt/e/s6ke/work/sh/ZZ_ksu_hooks_apply.py'

spec = importlib.util.spec_from_file_location('kp', PATCHER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

cache = {}
bad = 0
for path, old, new, tag in m.EDITS:
    if path not in cache:
        cache[path] = io.open(os.path.join(TREE, path), encoding='utf-8',
                              errors='surrogateescape').read().split('\n')
    lines = cache[path]
    s = '\n'.join(lines)
    n = s.count(old)
    print('%-4s %-45s %s' % (n, tag, path))
    if n != 1:
        bad += 1
        key = [l for l in old.split('\n') if l.strip()][:1]
        key = key[0].strip() if key else ''
        needle = key.split('(')[0][:30]
        for i, l in enumerate(lines):
            if needle and needle in l:
                print('        line %-5d %s' % (i + 1, l))
                for j in range(1, 5):
                    if i + j < len(lines):
                        print('                +%d %s' % (j, lines[i + j]))
                print('        ---')
print('\n%d anchor(s) not unique/found' % bad)
