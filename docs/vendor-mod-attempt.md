# /vendor 瘦身 + 关 speaker protection：第一次尝试记录（2026-09-19）

## 目标
1. 删掉 `/vendor/dataapp` 里 26 个预装 APK（2.2 GB）。
2. 在 `/vendor/build.prop` 把 `vendor.audio.feature.spkr_prot.enable` 改成 `false`
   （HAL 的 VI 回采捕获流因 ASM Loopback 没有后端 DAI 必然失败 → `iv_feedback_count`
   泄漏 → 扬声器路由卡死 → 全部声音哑；已在真机复现，见下）。

## 做了什么
* `E:\s6ke\vendor\vendor.img`（原厂，2.8 GB，md5 `0294a266a68c1fc6e5be3692b208ff08`）只读挂载 → 整树拷出。
* 删掉 26 个 APK；`build.prop` 第 134 行 `...spkr_prot.enable=true` → `false`（原厂本来就是显式 `true`）。
* 原镜像带 `shared_blocks`（Android 去重特性）→ Linux 只能只读挂载，无法原地改；
  改为用 `mke2fs -d` 从目录树重建（实测 `mke2fs -d` **会保留 security.selinux 等 xattr**）。
* 重建结果：`E:\s6ke\dist\vendor_slim.img`，694906880 字节（662 MiB），
  md5 `1c0b9bf691eaa790d2be43a613f3f6c9`。
* 与工厂镜像逐一对比（2744 → 2718 个文件）：**唯一差异就是那 26 个 APK + build.prop 一行**，
  mode/uid/gid 差异 0、SELinux 标签差异 0、其它文件内容差异 0（symlink 的 mode 位忽略）。

## 结果：刷入后卡在第一屏
刷 `vendor_slim.img` 后平板停在开机动画第一屏，adb 不可用，只能按键进 fastboot 恢复。

恢复过程（已成功）：
```
fastboot devices                       # 2fa7c794 fastboot（用户按键进入，已是 fastbootd）
fastboot flash vendor E:\s6ke\vendor\vendor.img
fastboot reboot
```
恢复后：`sys.boot_completed=1`、`/vendor/dataapp` 26 项、`spkr_prot=true`、
内核仍是 KSU 调试镜像（`#1 ... Sat Sep 19 13:52:09`）。

## 卡住的两个可能原因（未完全区分）
1. **dm-verity**：vendor 的哈希写在 `vbmeta.img` 里，改了镜像但没同步 vbmeta →
   init 挂载 /vendor 时校验失败直接卡住。这是改 super 内逻辑分区的常见后果。
2. **刷写被中断**：那次刷写所在的命令被会话中断（`tool call aborted`），
   vendor 分区可能只写了一半 → 文件系统不完整同样卡第一屏。

## 下次要试的话（按顺序）
1. 先在 fastbootd 里刷完就**校验回读**（避免盲目重启）：
   `fastboot fetch vendor readback.img` 后比对 md5（Android 11 的 fastboot 支持）。
2. 若回读一致仍然卡 → 判定为 dm-verity，先关校验再刷：
   `fastboot --disable-verity --disable-verification flash vbmeta E:\s6ke\imgdata\vbmeta.img`
   （必要时连 `vbmeta_system.img` 一起）。
3. 回滚始终可用：`E:\s6ke\vendor\vendor.img`（未改动）+ `E:\s6ke\work\tools\restore_vendor.ps1`。

## 不刷分区的替代方案（更稳，推荐）
* 应用：`adb shell pm uninstall --user 0 <包名>` 逐个卸掉（只清 /data 里的副本，不动 vendor）。
* 音频属性：做成一个 **KSU 模块**（开机 `post-fs-data.sh` 里 bind-mount 一份
  `spkr_prot=false` 的 build.prop 覆盖 `/vendor/build.prop`），随时可禁用、无刷机风险。
