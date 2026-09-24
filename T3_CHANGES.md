# EEBBK T3 (P22NH220) 内核自编译改动说明

本仓库基于 [Zhiyu722/android_kernel_eebbk_sm6150](https://github.com/Zhiyu722/android_kernel_eebbk_sm6150)
（原目标 EEBBK **S6 / P20H130**，Linux 4.14.190），用于适配 **EEBBK T3（P22NH220）**。

## 设备信息

| 项 | 值 |
|---|---|
| 型号 | EEBBK **T3** (P22NH220) |
| 平台 | Qualcomm **SM6150 / sdmmagpiep**（PM6150 + PM6150L，IDP） |
| Android | 11（SDK 30，`RKQ1.200826.002/V1.0.0_230215`，user / release-keys） |
| 指纹 | `EEBBK/sm6150/sm6150:11/RKQ1.200826.002/V1.0.0_230215:user/release-keys` |
| 原厂内核 | `4.14.180-perf (cp@ubuntu165) #2 SMP PREEMPT Wed Feb 15 17:34:51 CST 2023` |
| 面板 | `dsi_dual_sharp_wqhd_video_display`（dual-DSI video mode，`bl_ctrl_wled`，bl_max=3925） |
| 触摸 | FocalTech `focaltech@38`（i2c-1 0x38） |
| 功放 | 双 **NXP TFA9894**（i2c-2 0x34 / 0x36） |
| 屏偏压 | **TI TPS65132**（device tree 节点 `ti65132s@3e`，compatible `ti,ti65132`） |
| 分区 | A-only，无 slot；`boot=sde11`、`dtbo=sde17`、`vbmeta=sde16`、`bootbak=sde30` |

## 编译

```bash
export ARCH=arm64 SUBARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu-
export TARGET_PRODUCT=sm6150 KBUILD_BUILD_USER=cp KBUILD_BUILD_HOST=ubuntu165

# .config 以设备真实 /proc/config.gz 为基准，另加：
#   CONFIG_MODULE_SIG_FORCE=n          （允许加载原厂 vendor 模块）
#   # CONFIG_TOUCHSCREEN_NT36XXX is not set   （见下文，必须保持关闭）
#   # CONFIG_TOUCHSCREEN_HIMAX_CHIPSET is not set
#   # CONFIG_KSU is not set
#   CONFIG_QCA_CLD_WLAN=y / CONFIG_REGULATOR_TPS65132=y

make -j8 O=out CC=clang-11 LD=ld.lld TECHPACK=y DTC=dtc olddefconfig
make -j8 O=out CC=clang-11 LD=ld.lld TECHPACK=y DTC=dtc Image.gz
```

打包：**保留原厂 ramdisk 与 dtb 原样**，只替换 `Image.gz`。

烧写（该机型 bootloader **不支持** `fastboot flash`/`fastboot boot`，必须走 fastbootd）：

```bash
adb reboot fastboot
fastboot flash boot boot-t3-final.img
fastboot reboot
```

## 相对上游的改动

### 1. `Makefile`：`SUBLEVEL 190 -> 180`
T3 原厂内核是 4.14.**180**，而内核模块（`qca_cld3_wlan.ko`、`audio_*.ko` 等）的
vermagic 按 4.14.180 生成。把树内版本号改成 180 才能让 vendor 模块通过 vermagic 校验。
（符号 CRC 仍不完全一致，所以驱动以 in-tree 方式编译为主。）

### 2. `drivers/input/touchscreen/nt36xxx`（新增，**必须保持 `default n`**）
从其它机型移植的 Novatek NT36xxx 触摸驱动。**T3 不使用它**（实际是 FocalTech），
device tree 里的 `novatek@62` 是给别的屏留的幽灵节点。如果打开：
驱动 probe "成功" 后，关机时 `nvt_ts_shutdown()` 空指针 Oops
（`Process init (pid: 1), pc : nvt_ts_shutdown+0x60/0x124`），
`device_shutdown()` 被打断 -> 系统没走完关机流程 -> bootloader 落到 QMMI/DIAG，
Windows 显示 `Qualcomm HS-USB Diagnostics 900E`，重启要 ~100 秒。
**因此 Kconfig 里显式写了 `default n` 并加了警告注释。**

### 3. `drivers/regulator/tps65132-regulator.c`：补 `of_match_table`
上游驱动没有 `of_device_id`，无法绑定 T3 的 `ti65132s@3e`（`compatible = "ti,ti65132"`），
导致面板偏压 rail 起不来。新增 `"ti,ti65132"` / `"ti,tps65132"` 匹配项。

### 4. `drivers/gpu/drm/msm/dsi-staging/dsi_panel.c`：关闭 ESD 检测
该面板节点里没有可用的 `qcom,mdss-dsi-panel-status-*` 寄存器组，
`register_read` 校验永远失败，驱动每 ~5 秒报一次
`[drm:dsi_display_validate_status] *ERROR* mismatch: 0x0` 并 `report_panel_dead`
（表现为屏幕周期性黑一下再亮）。改为 `esd_config->esd_enabled = false`。

### 5. `techpack/audio/asoc/sm6150.c` + `msm-pcm-routing-v2.c`：T3 音频通路
- TERT_MI2S_RX 后端改挂 **双 TFA9894**（`tfa98xx.2-0034` / `tfa98xx.2-0036`）而不是 stub codec；
- 补回被早前补丁弄丢的 `.no_pcm / .dpcm_playback / .id = MSM_BACKEND_DAI_TERTIARY_MI2S_RX`
  （缺了会在每次播放时报 `can't get playback BE for Tertiary MI2S Playback`，功放不启动）；
- `intercon_mi2s[]` 里 TFA9874 分支的 `VI_FB_MUX` 路由名字修正为 `TERT_MI2S_RX_VI_FB_MUX`。

### 6. `techpack/audio/config/sm6150{auto.conf,autoconf.h}`：去掉 AW882xx
T3 用的是 TFA9894，AW882xx 的宏留着会干扰 machine driver 的 codec 选择。

### 7. `techpack/audio/dsp/q6afe.c`：`send_tfa_cal_in_band()` 直接返回 0
ADSP 对本树的 `AFE_PARAM_ID_TFADSP_RX_CFG` 返回 EBADPARAM
（树内 tfa98xx 是 v6.5.2，原厂是 v6.7.4，参数布局不同），跳过以免把 AFE port 留在坏状态。

### 8. **`tfa_dsp.c`：强制每次播放走冷启动（修复"只有开机后第一次有声音"）**
`techpack/audio/asoc/codecs/tfa9874/src/tfa_dsp.c`（以及未被编译的
`sound/soc/codecs/tfa_dsp.c` 副本）里 `tfa_dev_start()`：

```c
- err = tfaRunSpeakerBoost(tfa, 0, next_profile);
+ err = tfaRunSpeakerBoost(tfa, 1, next_profile);
```

原因：`tfa_dev_stop()` 里的 `tfa98xx_powerdown()` **不会恢复 ACS 位**，
于是 `tfa_is_cold()` 在第一次之后恒返回 0（warm），
`tfaRunSpeakerStartup()`（DSP 补丁 + profile 下载）被整段跳过 ——
功放照样 `tfa_dev_start success (0)`、状态机也进 `operating_state`，**但就是不出声**。

日志对照：
```
[ 49.46] Startup of device [R] is a coldstart   <- 开机后第一次，有声音
[ 58.13] Startup of device [R] is a warmstart   <- 之后每次都跳过初始化，没声音
```
原厂内核（v6.7.4）每次播放都打印 `tfa cold boot patch`，即每次都做冷启动。
改成 `force=1` 后会走 `tfaRunColdStartup()` -> `tfaRunStartup()` +
`tfaRunColdboot(tfa,1)`（置 ACS）+ `tfaRunStartDSP()`，与原厂行为一致。

### 9. **\`cam_eeprom_dev.c\`：前置摄像头模组识别修正（修复前摄打不开）**

T3 的 CamX HAL 只带这些前摄资源：

\`\`\`
/vendor/lib64/camera/com.qti.sensor.ov8856.so
/vendor/lib64/camera/com.qti.sensormodule.tsp_ov8856.bin
/vendor/lib64/camera/com.qti.eeprom.tsp_p24c64g_ov8856.so
\`\`\`

也就是前摄是 **OmniVision OV8856**。CamX 会读内核导出的
\`/proc/driver/FrontCamera_info\`，把里面的 "Module Vendor / Image Sensor"
拿去和 \`com.qti.sensormodule.*.bin\` 逐个比对：

| 内核 | FrontCamera_info | 结果 |
|---|---|---|
| 原厂 | \`Module Vendor: TSP, Image Sensor: OmniVision ov8856(8M)...\` | ✅ 匹配 \`tsp_ov8856.bin\` |
| 本仓库修改前 | \`Module Vendor: TSP, Image Sensor: OmniVision ov16a10(16M)...\` | ❌ 所有 bin 都 "check module vendor failed" |

匹配全部失败 → CamX 不创建前摄 → \`dumpsys media.camera\` 里
\`Number of camera devices: 1\`（只有后摄）。

修改 \`techpack\` 路径下的
\`drivers/media/platform/msm/camera/cam_sensor_module/cam_eeprom/cam_eeprom_dev.c\`：
新增 \`BBK_FRONT_OV8856()\`，把 TSP 前摄模组的分支从 ov16a10 改为 **ov8856**
（\`buf[1] == 0x0a\` 的 TSP 分支、以及 len 不足时的 TSP 兜底分支）。

修复后：

\`\`\`
Number of camera devices: 2
    Device 0 maps to "0"   Facing: Back   Orientation: 90
    Device 1 maps to "1"   Facing: Front  Orientation: 270
\`\`\`

实测前置摄像头可以正常打开。

## 验证结果（T3 实机）

| 项目 | 结果 |
|---|---|
| 重启 | **14~15 秒**，无 900E（修复前 ~100 秒且必进 900E；原厂 stock 约 19 秒） |
| 关机 | 正常，`device_shutdown()` 走完全部设备，无 Oops |
| 音频 | 连续多次播放日志全部 `coldstart`（10 次 cold / 0 次 warm），**声音正常且持续** |
| 显示 | 面板点亮、无 ESD 复位；`/sys/class/backlight/` 下 `backlight` 与 `panel0-backlight` 都在 |
| 触摸 | FocalTech FT 正常 |
| 摄像头 | 后摄 + **前摄** 均被枚举（Device0 Back/90°, Device1 Front/270°），前摄实测可打开 |
| Wi-Fi | `qca_cld3` in-tree 驱动可连 5GHz |
| dmesg | 无 `Internal error` / `Kernel panic` |

## 已知问题 / 未完成

- 音频 HAL 仍会打印 `check_and_set_gain_dep_cal: Failed to set gain dep cal level`、
  `ACDB_CMD_GET_AUDPROC_INSTANCE_GAIN_DEP_STEP_TABLE_SIZE Returned = -19`、
  `Unable to get Power service` —— **原厂 stock 内核也有同样日志**，目前不影响发声。
- 只支持 fastbootd 烧写（bootloader 不认 `fastboot flash boot`）。
- 这是 **A-only** 机型，刷错 boot 只能靠 `fastboot reboot fastboot` 回刷原厂 boot.img。

## 回滚

```bash
adb reboot fastboot
fastboot flash boot <原厂 boot.img>
fastboot reboot
```
