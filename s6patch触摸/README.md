# s6patch触摸 — EEBBK S6 (P20H130 / sm6150) 锁屏后卡顿 + 触摸乱上报

状态：**已定位并修复**（离线验证通过：编译零警告、镜像内符号正确；真机待刷入确认）

## 症状

锁屏后系统非常卡，日志里发现触摸事件乱上报。

## 根因

`drivers/input/touchscreen/focaltech_touch/focaltech_core.c` 用下面的 `#if/#elif`
链选择「熄屏通知器」：

```c
#if defined(CONFIG_FB)
    ts_data->fb_notif.notifier_call = fb_notifier_callback;
    ret = fb_register_client(&ts_data->fb_notif);            /* ← 实际走了这条 */
#elif defined(CONFIG_DRM)
    ts_data->fb_notif.notifier_call = drm_notifier_callback;
#if defined(CONFIG_DRM_PANEL)
    ... drm_panel_notifier_register(active_panel, ...)
#else
    ... msm_drm_register_client(&ts_data->fb_notif)
#endif
#endif
```

本内核 **`CONFIG_FB=y` 与 `CONFIG_DRM=y` 同时开启**，而屏幕由 **MSM DRM（SDE）** 驱动，
所以第一个分支胜出，注册的是**旧的 fb_notifier** —— MSM DRM 显示**永远不会触发** FB blank 事件。
本树里的证据：

```
drivers/gpu/drm/msm/msm_atomic.c:266  msm_drm_notifier_call_chain(MSM_DRM_EARLY_EVENT_BLANK, ...)
drivers/gpu/drm/msm/msm_atomic.c:287  msm_drm_notifier_call_chain(MSM_DRM_EVENT_BLANK, ...)
```

于是 `fts_ts_suspend()` / `fts_ts_resume()` —— 它们的调用点**只**存在于这些通知回调里 ——
**从未被调用**。而 i2c 驱动上也没有 dev_pm_ops（`FTS_PATCH_COMERR_PM == 0`）：

```c
#if defined(CONFIG_PM) && FTS_PATCH_COMERR_PM
        .pm = &fts_dev_pm_ops,
#endif
```

所以熄屏后触摸控制器**一直醒着、IRQ 一直开着**：

* IRQ 持续触发，每个事件都跑线程化中断处理并做 i2c 读 → CPU 被反复唤醒 → **锁屏后很卡**；
* 读回来的数据被当成触摸点上报 → **触摸乱上报**。

> 补充：本驱动的来源也值得注意 —— `README.txt` 写着「取自 Firefly RK3399 公开源码…
> **本驱动在 EEBBK S5 测试可用** By XiKoTaSu」，即从 S5 移植的第三方版本，
> 与信号链的显示框架匹配问题正是这类移植最容易踩的坑。

## 修复

按**本树自己的既有约定**判别与注册：

* `st/fts.c` 只在 `CONFIG_FB_MSM`（旧 MSM framebuffer）时才走 fb 路径；
* `hxchipset/himax_common.c` 用 `#ifdef CONFIG_DRM` + `msm_drm_register_client()`。

所以把判别条件从 `CONFIG_FB` 改成 `CONFIG_FB_MSM`，并注册 msm_drm 客户端：

```c
#elif defined(CONFIG_DRM) || defined(CONFIG_MSM_DRM)
    ts_data->fb_notif.notifier_call = drm_notifier_callback;
    ret = msm_drm_register_client(&ts_data->fb_notif);
    if (ret)
        FTS_ERROR("[DRM]Unable to register msm_drm notifier: %d\n", ret);
    else
        FTS_INFO("[DRM]msm_drm notifier registered for blank/unblank");
```

顺带修掉同源问题：`<linux/msm_drm_notify.h>` 原先只被包含在**不可达**的
`CONFIG_DRM_PANEL` 的 `#else` 分支里；同时把只匹配 `DRM_PANEL_*` 事件的那个
`drm_notifier_callback` 变体排除，改用匹配 `MSM_DRM_*` 事件的变体
（与 `msm_drm_register_client()` 配对）。

## 验证

```
编译：focaltech_core.o 重新编译，0 warning / 0 error
镜像（Image.gz）内：
  msm_drm notifier registered for blank/unblank   1
  Unable to register msm_drm notifier             1
  msm_drm_register_client / msm_drm_unregister_client   1 / 1
  Unable to register fb_notifier                  0    ← 旧 fb 路径已不再编译
  adsp-loader 2 · driver/BackCamera_info 1             ← 音频/相机修复未受影响
打包：kernel == Image.gz / ramdisk == factory / dtb == factory → ALL CHECKS PASSED
```

刷入后锁屏应观察到：`logcat -s FTS_TS` 出现 `[DRM]msm_drm notifier registered for blank/unblank`
与 `DRM event:…,blank:…`，并且熄屏后不再有触摸上报。

## 应用

```bash
cd android_kernel_eebbk_sm6150
git apply s6patch触摸/0001-focaltech-msm-drm-notifier.patch
```
