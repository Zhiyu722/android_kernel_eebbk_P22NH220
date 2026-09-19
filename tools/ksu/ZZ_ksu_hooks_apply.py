#!/usr/bin/env python3
"""Apply the ReSukiSU manual hooks (4 files) to this 4.14 tree.

Why only 4 files:
  * setresuid / init.rc read / input hooks are provided by the LSM based AUTO
    options (CONFIG_KSU_MANUAL_HOOK_AUTO_* default y),
  * the SELinux "static symbol export" section is unnecessary because this
    config already sets CONFIG_KALLSYMS_ALL=y,
  * CONFIG_KSU_SUSFS is off, so the non-SUSFS prototype variants apply.

Hook sources (kernel 3.14+ / 4.19- branches of the official doc):
  https://resukisu.org/guide/manual-integrate.md
Verified against KernelSU/kernel/tools/manual_hook_check.mk, which is what the
build enforces: ksu_handle_execveat (fs/exec.c), ksu_handle_faccessat
(fs/open.c), ksu_handle_stat + ksu_handle_newfstat_ret + ksu_handle_fstat64_ret
(fs/stat.c), ksu_handle_sys_reboot (kernel/reboot.c).

Every edit is anchored and counted first; nothing is written unless all match.
"""
import io, sys, os

HOT = '__attribute__((hot))\n'

def read(p):
    return io.open(p, encoding='utf-8', errors='surrogateescape').read()

def write(p, s):
    io.open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)

EDITS = []
def edit(path, old, new, tag):
    EDITS.append((path, old, new, tag))

STAT_EXTERNS = '''#ifdef CONFIG_KSU_MANUAL_HOOK
''' + HOT + '''extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
				int *flags);

extern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf_ptr);
#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)
extern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf_ptr);
#endif
#endif

'''

STAT_CALL = '''#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_stat(&dfd, &filename, &flag);
#endif
'''

# ------------------------------------------------------------------ fs/stat.c
edit('fs/stat.c',
'''#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)
SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,''',
     STAT_EXTERNS +
'''#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)
SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,''',
     'fs/stat.c externs')

edit('fs/stat.c',
'''SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,
		struct stat __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

	error = vfs_fstatat(dfd, filename, &stat, flag);''',
'''SYSCALL_DEFINE4(newfstatat, int, dfd, const char __user *, filename,
		struct stat __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

''' + STAT_CALL + '''	error = vfs_fstatat(dfd, filename, &stat, flag);''',
     'fs/stat.c newfstatat')

edit('fs/stat.c',
'''SYSCALL_DEFINE4(fstatat64, int, dfd, const char __user *, filename,
		struct stat64 __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

	error = vfs_fstatat(dfd, filename, &stat, flag);''',
'''SYSCALL_DEFINE4(fstatat64, int, dfd, const char __user *, filename,
		struct stat64 __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

''' + STAT_CALL + '''	error = vfs_fstatat(dfd, filename, &stat, flag);''',
     'fs/stat.c fstatat64')

edit('fs/stat.c',
'''COMPAT_SYSCALL_DEFINE4(newfstatat, unsigned int, dfd,
		       const char __user *, filename,
		       struct compat_stat __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

	error = vfs_fstatat(dfd, filename, &stat, flag);''',
'''COMPAT_SYSCALL_DEFINE4(newfstatat, unsigned int, dfd,
		       const char __user *, filename,
		       struct compat_stat __user *, statbuf, int, flag)
{
	struct kstat stat;
	int error;

#ifdef CONFIG_KSU_MANUAL_HOOK /* 32-bit su */
	ksu_handle_stat((int *)&dfd, &filename, &flag);
#endif
	error = vfs_fstatat(dfd, filename, &stat, flag);''',
     'fs/stat.c compat newfstatat')

edit('fs/stat.c',
'''	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat(&stat, statbuf);

	return error;''',
'''	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat(&stat, statbuf);

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_newfstat_ret(&fd, &statbuf);
#endif
	return error;''',
     'fs/stat.c newfstat ret')

edit('fs/stat.c',
'''	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat64(&stat, statbuf);

	return error;''',
'''	int error = vfs_fstat(fd, &stat);

	if (!error)
		error = cp_new_stat64(&stat, statbuf);

#ifdef CONFIG_KSU_MANUAL_HOOK /* 32-bit su */
	ksu_handle_fstat64_ret(&fd, &statbuf);
#endif
	return error;''',
     'fs/stat.c fstat64 ret')

# ------------------------------------------------------------------ fs/exec.c
# 3.14+ hook names (manual_hook_check.mk rejects ksu_handle_execve on >3.14).
# This tree has no __do_execve_file(), the whole body lives in
# do_execveat_common(), so the pre-hook goes at the top and the post-hook at
# the single out_ret: exit.
edit('fs/exec.c',
'''static int do_execveat_common(int fd, struct filename *filename,''',
'''#ifdef CONFIG_KSU_MANUAL_HOOK
''' + HOT + '''extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags);
''' + HOT + '''extern int ksu_handle_post_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags, int *retval);
#endif

static int do_execveat_common(int fd, struct filename *filename,''',
     'fs/exec.c externs')

edit('fs/exec.c',
'''	struct files_struct *displaced;
	int retval;

	if (IS_ERR(filename))
		return PTR_ERR(filename);''',
'''	struct files_struct *displaced;
	int retval;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif

	if (IS_ERR(filename))
		return PTR_ERR(filename);''',
     'fs/exec.c pre-execve hook')

edit('fs/exec.c',
'''out_ret:
	putname(filename);
	return retval;''',
'''out_ret:
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);
#endif
	putname(filename);
	return retval;''',
     'fs/exec.c post-execve hook (out_ret)')

# ------------------------------------------------------------------ fs/open.c
# 4.19-: the body of faccessat() is inline in the syscall, so hook it there.
edit('fs/open.c',
'''/*
 * access() needs to use the real uid/gid, not the effective uid/gid.''',
'''#ifdef CONFIG_KSU_MANUAL_HOOK
''' + HOT + '''extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
				int *mode, int *flags);
#endif

/*
 * access() needs to use the real uid/gid, not the effective uid/gid.''',
     'fs/open.c externs')

edit('fs/open.c',
'''	int res;
	unsigned int lookup_flags = LOOKUP_FOLLOW;

	if (mode & ~S_IRWXO)	/* where's F_OK, X_OK, W_OK, R_OK? */''',
'''	int res;
	unsigned int lookup_flags = LOOKUP_FOLLOW;

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
#endif

	if (mode & ~S_IRWXO)	/* where's F_OK, X_OK, W_OK, R_OK? */''',
     'fs/open.c faccessat call')

# -------------------------------------------------------------- kernel/reboot.c
edit('kernel/reboot.c',
'''SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,
		void __user *, arg)
{''',
'''#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);
#endif

SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,
		void __user *, arg)
{''',
     'kernel/reboot.c extern')

edit('kernel/reboot.c',
'''	char buffer[256];
	int ret = 0;''',
'''#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#endif

	char buffer[256];
	int ret = 0;''',
     'kernel/reboot.c call')

def main():
    tree = os.getcwd()
    touched, report = {}, []
    for path, old, new, tag in EDITS:
        full = os.path.join(tree, path)
        if not os.path.exists(full):
            report.append('MISSING FILE   %s' % tag); continue
        s = read(full)
        n = s.count(old)
        if n != 1:
            report.append('ANCHOR x%-3d    %s' % (n, tag)); continue
        touched[path] = touched.get(path, s).replace(old, new, 1)
        report.append('OK             %s' % tag)
    for line in report:
        print(line)
    bad = [r for r in report if not r.startswith('OK')]
    if bad:
        print('\n%d edit(s) failed - nothing written' % len(bad))
        return 1
    for path, s in touched.items():
        write(os.path.join(tree, path), s)
    print('\nwrote %d file(s): %s' % (len(touched), ', '.join(sorted(touched))))
    return 0

if __name__ == '__main__':
    sys.exit(main())
