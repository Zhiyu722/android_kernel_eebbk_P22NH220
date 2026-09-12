# EEBBK S6 (P20H130 / sm6150 / sdmmagpiep) 内核修复说明

修复对象：本仓库（android_kernel_eebbk_sm6150）编译出的内核在真机上
**无声** 与 **后置相机失效** 的问题，并补回原厂
`/proc/driver/BackCamera_info` / `/proc/driver/FrontCamera_info` 相机节点。

参考基准：`imgdata/boot.img`（2023-06-28 由 `cp@ubuntu165` 用 clang 10.0.7 构建，
真机当前正在运行该内核，功能正常）。

---

## 一、根因

### 1. 无声：音频栈被编进内核，与厂商 DLKM 模块冲突

真机 `/vendor/lib/modules` 下有 **44 个厂商内核模块**，其中音频框架全部是模块：

```
audio_aw882xx.ko   audio_wcd937x.ko  audio_bolero_cdc.ko
audio_machine_talos.ko  audio_q6.ko   audio_platform.ko ... (33 个音频模块)
qca_cld3_wlan.ko   wil6210.ko  br_netfilter.ko  lcd.ko  llcc_perfmon.ko ...
```

真机 `lsmod`（原厂内核运行时）确认这些模块**正在工作**，功放 `aw882xx_dlkm`
引用计数为 3，`/proc/asound/cards` 有 `sm6150-wcd9375-snd-card`。

而本仓库默认构建方式（`.github/workflows/build.yml`：
`make O=out CC=clang vendor/sdmsteppe-perf_defconfig h130.config`）会把
`techpack/audio` **编进内核镜像**：

* `techpack/audio/Makefile` 在 `CONFIG_ARCH_SM6150/ARCH_SDMMAGPIE=y` 时
  无条件 `include techpack/audio/config/sm6150auto.conf` 并 `export`，
  该文件把 `CONFIG_SND_SOC_WCD937X=y`、`CONFIG_SND_SMARTPA_AW882XX=y` 等
  全部置 `y`；
* `techpack/Kbuild` 用 `TECHPACK?=y` 把 `techpack/audio` 挂进 `obj-y`。

结果：内核里有一份完整的 QCOM 音频栈，厂商的 `audio_*.ko` 加载失败
（驱动/i2c 设备重复注册），音频 HAL 拿不到声卡 → **无声**。

原厂内核镜像里 **没有任何音频字符串**（`aw882xx/wcd937x/bolero/msm-pcm-routing`
计数均为 0），证明原厂就是按 DLKM 方式构建的。

### 2. 后置相机失效：原厂相机节点补丁不在源码里

原厂内核（真机）里存在两个 proc 节点，`cam_eeprom` 驱动在 probe 时创建：

```
-rw-rw-r-- 1 root root 0 ... /proc/driver/BackCamera_info
-rw-rw-r-- 1 root root 0 ... /proc/driver/FrontCamera_info
```

真机读取内容（root）：

```
Module Vendor: Q Tech (2742EJ36Q0F002DT), Image Sensor: Samsung s5k3l6(13M)(AF)(RAW)(MIPI)
reg[0x0000] = 0x01, ... reg[0x0013] = 0x02,
reg[0x0af1] = 0x01, ... reg[0x0b03] = 0x00,

（前置）
Module Vendor: TSP , Image Sensor: OmniVision ov16a10(16M)(FF)(RAW)(MIPI)
reg[0x0000] = 0x01, ... reg[0x0013] = 0x42,
reg[0x0703] = 0xff, ...
```

本仓库源码（以及上游 `EEBBK-QMUR-Devs/android-11` 分支）里
`grep -r BackCamera_info` 为 **0 命中**，即该补丁只存在于原厂私有源码树。
相机 HAL 需要该节点识别模组厂商，节点缺失会导致相机初始化失败。

---

## 二、改动内容

### 1. `drivers/media/platform/msm/camera/cam_sensor_module/cam_eeprom/cam_eeprom_dev.c`

按原厂内核二进制反汇编重建并补回（不是猜测：所有格式串、判定分支、
寄存器基址都与原厂镜像逐条对齐，并用真机输出验证）：

* `back_camera_info_create_proc()` / `front_camera_info_create_proc()`
  → `proc_create("driver/BackCamera_info", 0664, NULL, &fops)`（真机权限位一致）
* seq_file show：
  * 厂商行格式 `Module Vendor: <vendor> %s, Image Sensor: ...`；
  * `buf[20] == 0x01` 时 `%s = "(" + buf[21..36] 16 字节 + ")"`
    （真机 `(2742EJ36Q0F002DT)` ✓）；
  * 寄存器行 `reg[0x%04x] = 0x%02x, `：下标 < 20 用 `i`，否则用
    `i + 0xADD`（后摄） / `i + 0x6EF`（前摄）（真机 `0x0af1` / `0x0703` ✓）；
  * 模组厂商判定表：后摄 s5k3l6（Q Tech/TSP/Coe125/Truly/unknown），
    前摄 ov16a10（Q Tech/TSP/H110 TSP）与 s5k4h7（LiteArray/Truly/unknown），
    判定字节序列与分支阈值全部按原厂反汇编还原。
* `bbk_camera_info_read_module_id()`：在 `cam_eeprom_platform_driver_probe()`
  中按原厂流程读取 `cell-index`（写入 `soc_info.pdev->id`）、
  `qcom,slave-addr`、`qcom,i2c-freq-mode`，取电源配置后调用
  `cam_eeprom_parse_read_memory_map()` 上电读取 EEPROM（模组 ID + 校准数据），
  再按实例号创建对应 proc 节点（后摄 id=0、前摄 id=1，与 DTBO 中
  `eeprom_rear=eeprom@0 / eeprom_front=eeprom@1` 对应）。
* 与原厂的差异：原厂仅在读取成功时创建节点；本实现**即使读取失败也创建节点**
  （内容为空表头），保证 HAL 一定能找到文件。

### 2. `arch/arm64/configs/h130_factory.config`（新增）

从原厂内核镜像里提取的 **IKCONFIG 配置**（`BOOT_IMAGE` 内嵌 `.config`，
4907 个符号），与原厂构建时的 `.config` 等价。用它替换仓库的
`h130.config` 可让内核的**内建/模块划分与原厂一致**：

| 符号 | 仓库 h130.config | 原厂 |
|---|---|---|
| CONFIG_QCA_CLD_WLAN | =y（编进内核） | =m（厂商模块） |
| CONFIG_WIL6210 / DVB_MPQ / USB_GSPCA / LCD_CLASS_DEVICE / MSM_RDBG / IR_MSM_GENI / MSM_11AD / LLCC_PERFMON | =y | =m |
| CONFIG_BBK_RAMEXT / BBK_VIP_THREAD / BBK_BINDER_* / INPUT_IST8801 / INPUT_MXM1120 / INPUT_HALL / CGROUP_WORKINGSET / CGROUP_IOLIMIT | 缺失 | =y |

（注：`CONFIG_BBK_*`、`INPUT_MXM1120` 等 BBK 私有驱动**不在本仓库源码里**，
配置项会被 `olddefconfig` 丢弃，属于源码缺失，见第四节。）

### 3. `build_eebbk_clang11.sh`（新增）

可复现构建脚本，关键点：

* `TECHPACK=n`：把 techpack 排除出内核镜像（音频兼容修复的核心）；
* `LD=ld.lld`：发行版自带的 aarch64 GNU ld 2.38 会把 `.bss.rtic`
  放错位置，链接报
  `relocation truncated to fit: R_AARCH64_ADR_PREL_PG_HI21`，
  用 LLVM lld 11 链接即可（原厂用的是 binutils 2.27，行为不同）；
* clang 11（`/usr/bin/clang-11`，即 Ubuntu clang 11.1.0）+ GNU binutils 汇编器。

---

### 3. `arch/arm64/kernel/vmlinux.lds.S`（链接布局修复，必须）

厂商脚本里 `.bss.rtic`（`__rticdata`，含 `selinux_state`）被放在
`STABS_DEBUG`（`.stab 0 : {...}` 显式地址 0 的调试段）之后：

* 当年的 binutils 2.27 会把同名 `.bss` 合并进镜像，所以没问题；
* 现代链接器（GNU ld 2.38 / LLVM lld 11）要么报
  `relocation R_AARCH64_ADR_PREL_PG_HI21 out of range`（段被放到地址 ≈0），
  要么把段放到 `_end` 之后。

**真机实测**：第一版修复（段放在 `_end` 之后）刷入后**卡在第一屏无法开机**。
用 `nm` 检查符号地址确认了根因：

```
__bss_stop       = ffffff800a1e9560
__bss_rtic_start = ffffff800a1f1000
_end             = ffffff800a1f1000   <-- RTIC 段正好在 _end 之外
selinux_state    = ffffff800a1f1000   <-- 会被页分配器复用并覆盖
```

内核只保留 `_text.._end` 的内存，`selinux_state` 落在保留区之外 → 启动即崩溃。
最终修法：把 `.bss.rtic` 放在 `BSS_SECTION(0, 0, 0)` 之后、`_end` 之前
（镜像内部、页对齐），修复后：

```
__bss_rtic_start = ffffff800a1ea000
selinux_state    = ffffff800a1ea000   <-- 在 _end 之内
_end             = ffffff800a1f2000
```

刷入后设备正常开机（`Linux version 4.14.190-perf+ ... clang version 11.1.0-6, LLD 11.1.0`）。

### 4. `.scmversion`（vermagic 修复，必须）

源码树里存在 `.git` 时，`scripts/setlocalversion` 会给出 `4.14.190-perf+`，
而厂商 DLKM 模块记录的是 `4.14.190-perf`，**vermagic 不匹配会导致全部厂商模块
拒绝加载**（实测：`lsmod` 只有 1 行、`sys.boot_completed` 一直为空、无声音）。

修法：在源码根目录放一个空的 `.scmversion`（本仓库已包含），
`make kernelrelease` 即回到 `4.14.190-perf`，与厂商模块一致。
（用本仓库 `.github/workflows/build.yml` 的 CI 方式构建时没有 `.git`，不受影响。）

---

## 三、真机验证结果（adb / fastboot）

设备：EEBBK S6（`ro.boot.serialno=2fa7c794`，Android 11，非 A/B，boot 分区 64MB）

| 检查项 | 原厂内核 | 本仓库修复后（实测） |
|---|---|---|
| 内核启动 | ✓ | ✓（clang 11 + lld，`4.14.190-perf`） |
| `/proc/driver/BackCamera_info` | 存在 | **存在** ✓ |
| `/proc/driver/FrontCamera_info` | 存在 | **存在** ✓ |
| 节点内容 | `Module Vendor: Q Tech (2742EJ36Q0F002DT),…` | 同格式（见第二节还原依据） |
| `dumpsys media.camera` 相机数 | 2 | **1（仅后摄）** ⚠ 前摄需要原厂私有 sensor 代码 |
| 厂商音频 DLKM | 33 个已加载，`aw882xx_dlkm` 工作中 | **未加载**（`lsmod` 仅 1 行）⚠ |
| `sys.boot_completed` | 1 | 空（卡开机动画）⚠ |
| 升降/霍尔等 BBK 节点 | 有驱动 | 只有 DT 里的 platform device，无驱动 ⚠ |

### 当前阻塞点：厂商 DLKM 仍不加载

vermagic 修正后（`4.14.190-perf`，与原厂一致）模块仍未加载，表现为
`lsmod` 只有 1 行、`sys.boot_completed` 为空、停在开机动画（“第二屏”）。
可能原因与下一步：

1. `CONFIG_MODVERSIONS=y`（本内核与原厂一致）会对模块做符号 CRC 校验；
   我们的源码缺 BBK 私有驱动、编译链也不同，CRC 可能不一致
   → 试 `CONFIG_MODVERSIONS=n` 重新构建（内核侧关闭 CRC 校验，模块侧 vermagic 仍匹配）；
2. 需要 `dmesg`（当前无 root，Magisk 因多次失败启动进入保护状态）确认
   具体报错是 `disagrees about version of symbol` 还是 `Unknown symbol`；
3. 若为 `Unknown symbol`，说明模块依赖原厂私有驱动导出的符号，
   那就必须补齐 BBK 源码才能继续。

刷机要点（实测）：

* 本机 **只有在 fastbootd 模式下** `fastboot flash boot` 才被接受
  （bootloader 模式返回 `unknown command` / `Unrecognized command download`）；
* fastbootd 下设备序列号为 `2fa7c794`；recovery/fastbootd 等模式下 adb 序列号
  可能显示为 `0123456789ABCDEF`（**据此判断当前模式，也避免刷错设备**）；
* 原厂 `imgdata/boot.img` 可直接刷回恢复。

> 提醒：本仓库源码缺少 BBK 私有驱动，因此自编译内核在真机上会
> 丢失升降前摄/霍尔/传感器/ramext 等功能，且可能无法让原厂 userspace 完整启动。
> 若目标只是“可用的自定义内核”，建议先拿到完整原厂源码树再动内核。


## 四、已知未覆盖项（源码本身缺失，非本次改动引入）

* BBK 私有驱动：`CONFIG_BBK_RAMEXT*`、`BBK_VIP_THREAD`、`BBK_BINDER_*`、
  `INPUT_IST8801`、`INPUT_MXM1120`、`INPUT_HALL`（真机上存在
  `/sys/class/misc/bbk_hall_core`、`m1120_*`，说明原厂内核有这些驱动）；
* camera_v2 sensor 框架里的 `ov16a10_reg_addr` 等 sysfs 调试属性；
* 真机 `/system/app/BBKCamera.apk` 是 BBK 加密的 BPK 格式，其逻辑无法直接分析。

这些都不影响本次两项修复，但如果后续需要完全还原原厂功能，需要补齐上述驱动。

## 五、升降前摄（“打开相机自动升起”）结论

**这套逻辑确实在内核里，但驱动源码不在本仓库、也不在任何公开仓库中。**

与原厂内核（`imgdata/boot.img` 解出的 Image）做全量字符串比对后，发现原厂内核里内置了
BBK 的私有驱动（作者标记 `LYQ` / `damon` / `CZH`）：

```
6[LYQ-damon-vib]:%s Start change camera_state from [%d] to [%d]
6[LYQ-damon-vib]:damon enter vib_pwm_set_camera
6[LYQ-damon-vib]:damon vib_pwm_abort_notify_store KEY_CAMERA_POWER_ONOFF_PAGE_DISMISS:
                  RESTART_CAMERA_ELEVATOR to elevator_mode %d
6[LYQ-damon-vib]:damon enter handle input KEY_CAMERA_PRESS_MOVE & because:
                  hall_up - hall_down < (cali_data.position1.hall_up_down_diff ...)
6[LYQ-damon-hall]:%s -----detect press ,current camera_state %d-----
damon hall sensor is not cali
bbk_hall_vendor
```

即：**升降摄像头 = 振动 PWM（马达）+ 双霍尔位置反馈 + 输入事件（KEY_CAMERA_*）+ 校准数据**
（`/mnt/vendor/persist/sensors/cali_hall`、`up_down_count`）组成的状态机，编译进内核。

证据与影响：

| 字符串 | 原厂内核 | 本仓库编译结果 |
|---|---|---|
| LYQ-damon-vib | 47 | **0** |
| damon | 110 | **0** |
| bbk_hall | 15 | **0** |
| vib_pwm_set_camera | 3 | **0** |
| CAMERA_ELEVATOR | 2 | **0** |
| ramext / mxm1120 / ist8801 | 11 / 5 / 17 | **0** |

* 本仓库源码里没有这些驱动文件（`grep -r bbk/hall/damon/elevator/ramext/vib_pwm` 无命中）；
* 上游 `EEBBK-QMUR-Devs/android_kernel_eebbk_sm6150`（android-11 分支，73795 个文件）
  同样没有：该分支相对本仓库只多了一个 `drivers/misc/eebbk_caminfo.c`；
* GitHub 全站代码搜索 `RESTART_CAMERA_ELEVATOR` / `bbk_hall_core` / `LYQ-damon-vib`
  均为 0 命中；
* 真机 `/system/app/BBKCamera.apk` 是 BBK 加密的 BPK 格式（`BPK\0LOCAD_FILE` 头），
  无法直接分析；
* 设备树（dtbo.img）里只有 `hall`（GPIO 93 中断）节点，没有马达节点。

因此**无法通过“内核配置”实现**：不是配置开关没打开，而是**编译这些驱动的源码不存在**。
要想恢复升降功能，只有两条路：

1. 拿到 BBK 原厂内核源码树（含 `bbk_hall` / `bbk_vib_pwm`（damon）/ `bbk_ramext` /
   `mxm1120` / `ist8801` 等），放进 `drivers/` 并打开对应 `CONFIG_BBK_*` / `CONFIG_INPUT_*`
   开关（本仓库已附原厂 `.config`，开关值现成）；
2. 依据真机逆向重写该状态机 —— 需要 PWM 通道号、霍尔 ADC/校准格式等硬件细节，
   工作量与风险都很大。

⚠️ **重要提醒**：因为源码缺失，**刷入本仓库编译的内核会失去**
升降前摄、霍尔（`bbk_hall_core`）、`mxm1120`/`ist8801` 传感器、`ramext` 等 BBK 功能
（原厂内核里有这些驱动，自编译内核里没有）。原厂 `imgdata/boot.img` 可随时刷回。

另注：`/proc/driver/BackCamera_info`、`FrontCamera_info` 两个节点在**前后摄**都会创建
（后摄 id=0、前摄 id=1），若 App/HAL 是先读 `FrontCamera_info` 再触发升降机构，
则本次修复对前摄也有帮助。



---

## 六、真机刷机排查全过程（最终结论：缺 BBK 私有驱动）

按顺序踩到并解决/定位的问题，全部有真机证据：

| # | 现象 | 根因 | 状态 |
|---|---|---|---|
| 1 | 刷入后卡**第一屏** | `.bss.rtic`（含 `selinux_state`）被链接到 `_end` 之外，运行时被页分配器覆盖 | 已修（`vmlinux.lds.S`） |
| 2 | 卡**第二屏**、`lsmod` 只有 1 行 | 源码树带 `.git` → vermagic 变 `4.14.190-perf+`，厂商模块拒装 | 已修（空 `.scmversion`） |
| 3 | 仍 `lsmod`=1 | `CONFIG_MODULE_SIG_FORCE=y` 只认本内核密钥签名的模块 | 已修（`SIG_FORCE=n`，vermagic 不变） |
| 4 | 仍 `lsmod`=1 | `CONFIG_MODVERSIONS` 符号 CRC 不匹配（源码缺 BBK 补丁） | 已修（`kernel/module.c` 的 `bad_version` 改为接受，等价 `modprobe --force`；保留 `MODVERSIONS=y` 维持 vermagic） |
| 5 | 模块终于装上（35 个）、音频 HAL 不再崩，但**声卡仍建不出来** → 卡第二屏 | `/sys/class/sound/` 只有 `timer`；`audio_extn_utils_open_snd_mixer` 无限重试；`adsprpcd` ADSP 起不来；i2c `2-0034` 无驱动绑定 | **缺 BBK 私有驱动，本仓库无解** |

对照原厂内核（同机实测）：`sys.boot_completed=1`、**36 个模块全部加载**、
`/proc/asound/cards` 有 `sm6150-wcd9375-snd-card`、`aw882xx_dlkm` 工作中
—— 差的正是源码树里没有的那批 BBK 驱动。

### 交付与交接建议

* 相机 proc 补丁 + 链接布局修复：`dist/eebbk_s6_camera_proc.patch`
* 构建要点：clang-11 + `ld.lld`、`TECHPACK=n`、空 `.scmversion`；
  单独编译时还需 `CONFIG_MODULE_SIG_FORCE=n` + `module.c` CRC 放行
* **最优路径**：向提供原厂包/原厂内核的人索取**完整源码树**（含 BBK 驱动），
  套上本补丁即可得到完全可用的自编译内核
* 设备已刷回原厂 `imgdata/boot.img`，功能正常

### 刷机备忘（本机特有）

* 只有 **fastbootd**（`fastboot devices` 显示 `2fa7c794`）能刷 `boot`；
  bootloader 模式与序列号 `0123456789ABCDEF` 的那种模式都会返回
  `unknown command` / `Unrecognized command download`
* 刷自定义 boot 会覆盖 Magisk 的 ramdisk（root 消失）
* 原厂 `imgdata/boot.img`（64 MB，与分区等大）随时可刷回

---

## 七、升降前摄接口（供后续逆向重写驱动）

真机原厂内核下抓到的完整接口：

```
/sys/devices/platform/soc/soc:bbk_vib_pwm/   driver=bbk_vib_pwm, 带 of_node + input/
  vib_pwm_camera_state      <-- 0=收回 1=升起 2=升起并偏转（用户确认的原厂逻辑）
  vib_pwm_elevator_mode / vib_pwm_elevator_row_shift / vib_pwm_holder_mode
  vib_pwm_cali / vib_pwm_clear_cali_data / vib_pwm_up_down_count / vib_pwm_count
  vib_pwm_dir / vib_pwm_freq / vib_pwm_time / vib_pwm_enable / vib_pwm_id
  vib_pwm_state_init / vib_pwm_abort_notify
```

状态机线索（原厂内核字符串）：`[LYQ-damon-vib] Start change camera_state from [%d] to [%d]`、
`damon enter vib_pwm_set_camera`、`RESTART_CAMERA_ELEVATOR to elevator_mode %d`、
`damon enter handle input KEY_CAMERA_PRESS_MOVE & because: hall_up - hall_down < (cali_data.position1.hall_up_down_diff ...)`、
`[LYQ-damon-hall] detect press`、`damon hall sensor is not cali`；
校准数据在 `/mnt/vendor/persist/sensors/`（`cali_hall`、`up_down_count`）。

设备树：`hall` 节点（`compatible="qcom,hall"`、GPIO93 中断）在 dtbo 覆盖层；
`bbk_vib_pwm` 节点不在 `imgdata` 的 dtbo/boot DTB 里，说明设备上是原厂那份 dtbo
—— **不要刷用本仓库编译的 dtbo，否则 hall/vib 节点会丢**。
