# s6patch相机 — EEBBK S6 (P20H130 / sm6150) 相机修复

适用：`android_kernel_eebbk_sm6150`（msm-4.14，sm6150/sdmmagpiep）
状态：**已在真机验证通过** ✅

## 补丁

| 文件 | 作用 | 是否必须 |
|---|---|---|
| `0001-camera-info-proc-nodes.patch` | 补回原厂 `/proc/driver/BackCamera_info`、`/proc/driver/FrontCamera_info` | 是（就是本次要修的相机问题） |
| `0002-vmlinux.lds.S-fix-bss-rtic-layout.patch` | 把 `.bss.rtic` 放回内核镜像内（`_end` 之前） | **必须**，否则重新编译的内核根本起不来 |

## 应用

```bash
cd android_kernel_eebbk_sm6150
git apply s6patch相机/0001-camera-info-proc-nodes.patch
git apply s6patch相机/0002-vmlinux.lds.S-fix-bss-rtic-layout.patch
```

## 补丁 0001 做了什么（从原厂内核二进制逆向还原，逐字对齐）

在 `cam_eeprom_dev.c` 中：

* `proc_create("driver/BackCamera_info", 0664, NULL, &fops)`、`"driver/FrontCamera_info"`（权限位与原厂一致）
* seq_file 输出格式：
  * `Module Vendor: <厂商> %s, Image Sensor: ...`；`buf[20]==1` 时 `%s = "(" + buf[21..36] 的 16 字节 + ")"`
  * 寄存器行 `reg[0x%04x] = 0x%02x, `：下标 <20 用 `i`，否则用 `i+0xADD`（后摄）/ `i+0x6EF`（前摄）
  * 厂商判定表：后摄 s5k3l6（Q Tech/TSP/Coe125/Truly/unknown）；前摄 ov16a10（Q Tech/TSP/H110 TSP）与 s5k4h7（LiteArray/Truly/unknown）
* 在 `cam_eeprom_platform_driver_probe()` 里读 `cell-index`（→`pdev->id`）、`qcom,slave-addr`、`qcom,i2c-freq-mode`，取电源配置后调用
  `cam_eeprom_parse_read_memory_map()` 上电读取 EEPROM，再按实例号建节点（后摄 id=0、前摄 id=1，对应 DTBO 里 `eeprom_rear=eeprom@0` / `eeprom_front=eeprom@1`）

## 真机验证结果（设备：EEBBK S6，Android 11）

| 检查 | 结果 |
|---|---|
| 刷入后内核启动 | ✅（`Linux version 4.14.190-perf … clang version 11.1.0-6, LLD 11.1.0`） |
| `/proc/driver/BackCamera_info` / `FrontCamera_info` | ✅ 两个节点都创建成功 |
| 后摄枚举 | ✅ `dumpsys media.camera` = 1（后摄） |
| 节点内容 | ✅ 与原厂格式一致（厂商行 + `reg[0x…]` 寄存器表） |
| 前摄 | ⚠ 未枚举到（需要原厂私有的前摄 sensor 代码，本仓库没有） |

## 补丁 0002（为什么必须）

厂商脚本把 `.bss.rtic`（含 `selinux_state`）放在零地址调试段之后：

* binutils 2.27 会把它合并进 `.bss`，所以原厂没事；
* GNU ld 2.38 / lld 要么直接链接失败（`relocation R_AARCH64_ADR_PREL_PG_HI21 out of range`），要么把它放到 `_end` 之外 —— 真机实测**卡第一屏**（`nm` 证据：`selinux_state == _end`，被页分配器覆盖）。

修法：放到 `BSS_SECTION(0, 0, 0)` 之后、`_end` 之前。

修复后在 `TECHPACK=y` 的最终构建里复核过（链接布局随配置会变，必须每次确认）：

```
__bss_rtic_start = 0xffffff800a623000
selinux_state    = 0xffffff800a623000
_end             = 0xffffff800a62b000     ← selinux_state 在 _end 之内 ✓
```

## 构建脚本

本目录的 `build_eebbk_clang11.sh` 与 `s6patch声音/` 里的是同一份（把音频栈编进内核的
`TECHPACK=y` 版本）。相机补丁本身与构建方式无关，但重新编译时**必须**用这个脚本，
因为 `LD=ld.lld` 与 `.bss.rtic` 修复是配套的。

## 补丁集自检（已验证）

在**原始 zip 的全新解压树**（`android_kernel_eebbk_sm6150-main.zip`）上逐个试打：

```
--- s6patch相机 ---
  0001-camera-info-proc-nodes.patch                 APPLIES CLEANLY
  0002-vmlinux.lds.S-fix-bss-rtic-layout.patch      APPLIES CLEANLY
--- s6patch声音 ---
  0001-kernel-module-accept-vendor-crc.patch        APPLIES CLEANLY
  0002-config-add-factory-config.patch              APPLIES CLEANLY
  0003-build-script-clang11-audio-builtin.patch     APPLIES CLEANLY
  0004-sm6150-aw882xx-speaker-codec.patch           APPLIES CLEANLY

post-apply: module.c 放行 ✓ · sm6150.c 的 tfa98xx hack 已清除 ✓ ·
            awinic_codecs 保留 ✓ · TECHPACK_MODE 默认 = y ✓ ·
            h130_factory.config = 160118 字节 ✓ · BackCamera_info 已加入 ✓ ·
            vmlinux.lds.S 的 bss.rtic 修复已在 ✓ · .rej/.orig 残留 0 ✓
RESULT: ALL 6 PATCHES APPLY CLEANLY TO THE PRISTINE ORIGINAL TREE
```
