/*
 * Bring-up aid for the EEBBK S6 (P20H130).
 *
 * On this ROM the kernel log is not readable from adb shell: /dev/kmsg is root
 * only, the syslog syscall is restricted and logd's kernel buffer is disabled,
 * so a driver that fails to probe leaves no trace we can see.  This node
 * publishes the whole ring buffer to any reader, which is what
 *
 *     adb shell cat /proc/eebbk_kmsg | grep -i m1120
 *
 * needs during bring-up.  It is compiled in only when CONFIG_BBK_DEBUG_BRINGUP
 * is set, together with the SELinux permissive override in
 * security/selinux/hooks.c, so the normal image is unaffected.
 *
 * SPDX-License-Identifier: GPL-2.0
 */
#include <linux/module.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/proc_fs.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/syslog.h>

#ifndef SYSLOG_ACTION_READ_ALL
#define SYSLOG_ACTION_READ_ALL	3
#endif

/*
 * do_syslog()'s fourth argument.  check_syslog_permissions() lets a caller that
 * claims to come from /proc through without CAP_SYSLOG:
 *
 *	if (source == SYSLOG_FROM_PROC && type != SYSLOG_ACTION_OPEN)
 *		goto ok;
 *
 * which is exactly what this node needs; what remains is security_syslog(),
 * and the bring-up build runs SELinux permissive.
 */
#ifndef SYSLOG_FROM_PROC
#define SYSLOG_FROM_PROC	1
#endif

#define BBK_KMSG_NAME	"eebbk_kmsg"

static ssize_t bbk_kmsg_read(struct file *file, char __user *ubuf,
			     size_t count, loff_t *ppos)
{
	int ret;

	if (!count)
		return 0;

	ret = do_syslog(SYSLOG_ACTION_READ_ALL, ubuf, count, SYSLOG_FROM_PROC);
	if (ret > 0)
		*ppos += ret;
	return ret;
}

static const struct file_operations bbk_kmsg_fops = {
	.owner	= THIS_MODULE,
	.read	= bbk_kmsg_read,
	.llseek	= no_llseek,
};

static int __init bbk_debug_init(void)
{
	struct proc_dir_entry *e;

	e = proc_create(BBK_KMSG_NAME, 0444, NULL, &bbk_kmsg_fops);
	if (!e) {
		pr_err("bbk_debug: cannot create /proc/%s\n", BBK_KMSG_NAME);
		return -ENOMEM;
	}
	pr_info("bbk_debug: /proc/%s ready (bring-up build)\n", BBK_KMSG_NAME);
	return 0;
}
late_initcall(bbk_debug_init);

MODULE_AUTHOR("EEBBK S6 kernel reconstruction");
MODULE_DESCRIPTION("Bring-up kernel log node for the EEBBK S6");
MODULE_LICENSE("GPL v2");
