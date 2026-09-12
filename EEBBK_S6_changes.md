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

## 三、构建

```bash
# 在 WSL/Linux 里（clang-11、ld.lld、dtc、bison、flex、libssl-dev、bc 已装）
cd android_kernel_eebbk_sm6150
./build_eebbk_clang11.sh
# 产物：out/arch/arm64/boot/Image.gz  （vermagic 4.14.190-perf）
```

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

