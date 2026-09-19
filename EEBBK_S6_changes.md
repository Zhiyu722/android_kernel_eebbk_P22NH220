# EEBBK S6 (P20H130 / sm6150 / sdmmagpiep) 内核修复说明

修复对象：本仓库（android_kernel_eebbk_sm6150）编译出的内核在真机上
**无声** 与 **后置相机失效** 的问题，并补回原厂
`/proc/driver/BackCamera_info` / `/proc/driver/FrontCamera_info` 相机节点。

参考基准：`imgdata/boot.img`（2023-06-28 由 `cp@ubuntu165` 用 clang 10.0.7 构建，
真机当前正在运行该内核，功能正常）。

---

## 一、根因

### 1. 无声：`TECHPACK=n` 把 ADSP loader 挡在了内核之外

> **更正**：本文档早期版本把根因写成「音频栈被编进内核、与厂商 DLKM 冲突」，
> 那是错的。真机实测证明恰恰相反：**把音频栈编进内核才是修复**，
> 而「不编」（`TECHPACK=n`）正是无声的原因。

真机 `/vendor/lib/modules` 下有 **44 个厂商内核模块**，其中音频框架全部是模块：

```
audio_aw882xx.ko   audio_wcd937x.ko  audio_bolero_cdc.ko
audio_machine_talos.ko  audio_q6.ko   audio_platform.ko ... (33 个音频模块)
qca_cld3_wlan.ko   wil6210.ko  br_netfilter.ko  lcd.ko  llcc_perfmon.ko ...
```

原厂内核镜像里 **没有任何音频字符串**（`aw882xx/wcd937x/bolero` 计数均为 0），
原厂确实是按 DLKM 方式构建的。**但这套 DLKM 在本仓库编出的内核上用不了**：
它们是用厂商内核链接的，`struct module` / 符号 CRC 与本内核不兼容
（实测 `module_layout` 期望 `0xcc8cac52`，本内核算出 `0x021f9ae4`）。

于是本内核必须自带一份 **ABI 自洽** 的音频栈。而早期构建脚本传了 `TECHPACK=n`：

```make
# techpack/Kbuild
TECHPACK?=y
obj-${TECHPACK} += stub/ $(addsuffix /,$(subst $(srctree)/techpack/,,$(techpack-dirs)))
```

传 `n` 就只编 `stub/`。实测两种构建的内核里 techpack 目标文件数：

| 构建 | `out/techpack` 下目标文件 | 结果 |
|---|---|---|
| `TECHPACK=n`（旧，错误） | **1 个**（空的 `techpack/built-in.o`） | 音频代码为 0，**无声卡，卡开机动画** |
| `TECHPACK=y`（修复） | **87+ 个**（`asoc/` `dsp/` `ipc/` …） | 音频栈齐全 |

**决定性的一环是 ADSP loader。** `techpack/audio/config/sm6150auto.conf`
（由 `techpack/audio/Makefile` 在 `CONFIG_ARCH_SM6150=y` 时强制 include 并 export）
里有 `CONFIG_MSM_ADSP_LOADER=y`，对应的
`techpack/audio/dsp/adsp-loader.c` 是**唯一**会去拉起 ADSP 的代码：

```c
/* DT 里 qcom,adsp-state = <0>，且没有 qcom,proc-img-to-load → 走 load_adsp */
adsp_state = apr_get_q6_state();
if (adsp_state == APR_SUBSYS_DOWN) {
        priv->pil_h = subsystem_get("adsp");   /* ← 载入 adsp.mbn，ADSP 起来 */
```

`TECHPACK=n` 时这段代码不在内核里，ADSP 永远不启动，于是真机上出现：

```
adsprpcd: apps_dev_init failed for domain 0, errno Transport endpoint is not connected  ← 死循环
audio_hw_utils: audio_extn_utils_open_snd_mixer: retry, retry_num 18                    ← 无限重试
/sys/class/sound/  → 只有 timer，没有 card0
ServiceManager: Waiting for service 'media.audio_policy' …                              ← 开机永远完不成
```

`/dev/fastrpc-*` 打不开并返回 ENOTCONN，含义就是 **ADSP 远程处理器没在运行**。
厂商的 `audio_adsp_loader.ko` 顶不上（同上，ABI 不兼容）。

**修复 = 构建时不要再传 `TECHPACK=n`**（`techpack/Kbuild` 里 `TECHPACK?=y`
本来就是默认值）。详见 `s6patch声音/README.md`。

#### 1.1 设备树侧的证据（全部核对过，**无需改 DT**）

`imgdata/boot.img` 的 dtb 段含 10 棵基础树，其中 `boot08` = **SDMMAGPIEP SoC**（本机）；
`dtbo.img` 含 9 个覆盖层，其中带 `qcom,hall`（BBK 升降霍尔）与 bbk/h130 标记的
`dtbo02/04/05/07` 是 BBK 的覆盖层。四处关键节点：

```
boot08.dts:17336   qcom,msm-adsp-loader { status="ok"; compatible="qcom,adsp-loader";
                                          qcom,adsp-state = <0x00>; }
boot08.dts:~4471   qcom,lpass@62400000 { compatible="qcom,pil-tz-generic";
                                          qcom,pas-id=<0x01>;
                                          qcom,firmware-name="adsp";      ← 载入 adsp.mbn
                                          mbox-names="adsp-pil"; }
boot08.dts:17226   sound { compatible = "qcom,sm6150-asoc-snd"; … }       ← 匹配内置 sm6150.c
dtbo04.dts:4342    fragment@54 → __overlay__ { qcom,model = "sm6150-wcd9375-snd-card";
                                               compatible = "qcom,sm6150-asoc-snd";
                                               status = "ok"; }
```

* 内置机驱动 `techpack/audio/asoc/sm6150.c` 用
  `snd_soc_of_parse_card_name(card, "qcom,model")` 取卡名 →
  运行时卡名就是 **`sm6150-wcd9375-snd-card`**（ALSA 截断为 `sm6150wcd9375sn`），
  与厂商音频 HAL 的 `get_sndcard_id()` 期望一致；
* 打包 `boot.img` 时 **dtb 段逐字节保留原厂**
  （`mkboot2.py` 自检含 `chk("dtb == factory")`），且不刷 `dtbo`，
  所以设备实际使用的树一定包含上述节点；
* `adsp-loader.c` 的判定路径：DT `qcom,adsp-state = <0>`、无 `qcom,proc-img-to-load`
  → `goto load_adsp` → `apr_get_q6_state()` 为 `APR_SUBSYS_DOWN`
  → **`subsystem_get("adsp")`** → 绑定 `qcom,lpass@62400000` 载入 `adsp.mbn`。

#### 1.2 第二层根因：机驱动硬编码了 TFA98xx，而本机是 AW882xx

把音频栈编进内核后，日志给出了更具体的报错（关键两行）：

```
<6>[ 1.462112] [Awinic][2-0034]aw882xx_dai_drv_append_suffix: dai name [aw882xx-aif-2-34]
<3>[10.442602] sm6150-asoc-snd ...: ASoC: CODEC DAI tfa98xx-aif-2-34 not registered
```

`techpack/audio/asoc/sm6150.c` 的 `populate_snd_card_dailinks()` 里有一段**本地改动**
（带中文注释），把两个 MI2S 后端 link 的 legacy 单 codec 字段硬编码成 TFA98xx：

```c
msm_mi2s_be_dai_links[0].codec_name     = "tfa98xx.2-0034";
msm_mi2s_be_dai_links[0].codec_dai_name = "tfa98xx-aif-2-34";
msm_mi2s_be_dai_links[1].codec_name     = "tfa98xx.2-0036";
msm_mi2s_be_dai_links[1].codec_dai_name = "tfa98xx-aif-2-36";
```

本机（P20H130）的功放**不是 TFA98xx**，而是 i2c 2-0034 / 2-0036 上的
**AWINIC AW882xx**（驱动 probe 时打印 `aw882xx 1852 detected`），
注册的 DAI 是 `aw882xx-aif-2-34` / `aw882xx-aif-2-36`。

致命机制在 `sound/soc/soc-core.c`：

```c
static int snd_soc_init_multicodec(struct snd_soc_card *card,
				   struct snd_soc_dai_link *dai_link)
{
	/* Legacy codec/codec_dai link is a single entry in multicodec */
	if (dai_link->codec_name || dai_link->codec_of_node ||
	    dai_link->codec_dai_name) {
		dai_link->num_codecs = 1;
		dai_link->codecs[0].name     = dai_link->codec_name;
		dai_link->codecs[0].dai_name = dai_link->codec_dai_name;
	}
```

只要 legacy 字段非空，link 就被收缩成「1 个 codec」，`codecs[0]` 被整体覆盖 →
**同一文件里本来就正确的**表被丢弃：

```c
/* sm6150.c:6900，由 CONFIG_SND_SOC_AWINIC_AW882XX 选中 */
struct snd_soc_dai_link_component awinic_codecs[] = {
	{ .dai_name = "aw882xx-aif-2-34", .name = "aw882xx_smartpa.2-0034" },
	{ .dai_name = "aw882xx-aif-2-36", .name = "aw882xx_smartpa.2-0036" },
};
```

→ `snd_soc_register_card()` 永远 `-EPROBE_DEFER` → 无 `card0` →
音频 HAL 在 `get_sndcard_id()` 段错误 → 卡第二屏。

**反证（原厂怎么做）**：从 `super_5.img` 提取的原厂机驱动 `machine_dlkm.ko`：

* **没有** `dual speaker configured (34 & 36)` 这条字符串 → 那 4 行不是原厂代码；
* 符号表里有 `aw882xx_dails`（**48 字节 = 2 × `snd_soc_dai_link_component`**）、
  `tfa98xx_dails`、`fs16xx_codecs` → 原厂**一律用 `.codecs`/`.num_codecs` 组件表**，
  从不走 legacy 字段。

**修复**：删掉那 4 行，让 `awinic_codecs` 生效（`s6patch声音/0004`）。

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

* **`TECHPACK=y`（关键，不要传 `TECHPACK=n`）**：让 `techpack/audio` 编进内核，
  从而带上 ADSP loader 与整套音频栈 —— **这就是无声问题的修复**（见第一节）；
  脚本里还加了编后自检，确认 `adsp-loader`/`bolero`/`wcd937x`/`aw882xx`
  等符号真的进了 `Image.gz`；
* `LD=ld.lld`：发行版自带的 aarch64 GNU ld 2.38 会把 `.bss.rtic`
  放错位置，链接报
  `relocation truncated to fit: R_AARCH64_ADR_PREL_PG_HI21`，
  用 LLVM lld 11 链接即可（原厂用的是 binutils 2.27，行为不同）；
* `CONFIG_MODULE_SIG_FORCE=n`：厂商模块用原厂密钥签名，本内核验签必然失败；
* clang 11（`/usr/bin/clang-11`，即 Ubuntu clang 11.1.0）+ GNU binutils 汇编器。

---

### 4. `arch/arm64/kernel/vmlinux.lds.S`（链接布局修复，必须）

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

### 5. `.scmversion`（vermagic 修复，必须）

源码树里存在 `.git` 时，`scripts/setlocalversion` 会给出 `4.14.190-perf+`，
而厂商 DLKM 模块记录的是 `4.14.190-perf`，**vermagic 不匹配会导致全部厂商模块
拒绝加载**（实测：`lsmod` 只有 1 行、`sys.boot_completed` 一直为空、无声音）。

修法：在源码根目录放一个空的 `.scmversion`（本仓库已包含），
`make kernelrelease` 即回到 `4.14.190-perf`，与厂商模块一致。
（用本仓库 `.github/workflows/build.yml` 的 CI 方式构建时没有 `.git`，不受影响。）

### 6. `kernel/module.c`（放行厂商 DLKM 的符号 CRC，必须）

厂商模块带 `CONFIG_MODVERSIONS` 的符号 CRC，且是在完整厂商树里算出来的
（实测 `module_layout` 期望 `0xcc8cac52`，本内核算出 `0x021f9ae4`）。
`CONFIG_MODVERSIONS` 不能关——`modversions` 是 vermagic 字符串的一部分，
关掉会变成 `… mod_unload aarch64`，与厂商模块
`… mod_unload modversions aarch64` 不匹配，反而更糟。

修法：把 `check_version()` 的 `bad_version` 分支改为「只警告、返回 1（接受）」，
等价 `modprobe --force`。实测 `lsmod` 从 1 → 35，
厂商音频 HAL 也不再在 `get_sndcard_id()` 段错误。

> 注意：这一步**只解决「模块装不上」，不解决「没声音」**。
> 真正让声音回来的还是第 3 条的 `TECHPACK=y`。

---

## 三、真机验证结果（adb / fastboot）

设备：EEBBK S6（`ro.boot.serialno=2fa7c794`，Android 11，非 A/B，boot 分区 64MB）

| 检查项 | 原厂内核 | 旧构建 `TECHPACK=n` | `TECHPACK=y`（未修 codec 名） | **最终 `boot_audio2.img`（实测）** |
|---|---|---|---|---|
| 内核启动 | ✓ | ✓ | ✓ | ✓ `clang 11.1.0 / LLD` `#2` |
| `/proc/driver/BackCamera_info` | 存在 | ✓ | ✓ | **✓** |
| `/proc/driver/FrontCamera_info` | 存在 | ✓ | ✓ | **✓** |
| `dumpsys media.camera` | 2 | 1（仅后摄） | 1 | **1（仅后摄，前摄需原厂私有 sensor 代码）** |
| `/sys/class/sound/card0` | 有 | **无（只有 `timer`）** | **无（只有 `timer`）** | **有 ✅ 23 个 `pcmC0D*p` 播放设备 + 12 个 `comprC0D*`** |
| 声卡名 | `sm6150-wcd9375-snd-card` | — | — | **HAL 打印 `snd_card_name: sm6150-wcd9375-snd-card`，`Opened sound card:0` ✅** |
| 音频 HAL 崩溃 | 无 | `get_sndcard_id+572` SIGSEGV 反复 | 同左 | **无 ✅** |
| `adsprpcd` | 正常 | `Transport endpoint is not connected` 死循环 | 不再报错 | **不再报错，3 进程稳定 ✅** |
| `sys.boot_completed` | 1 | **空（卡开机动画）** | **空（卡开机动画）** | **`1` ✅** |
| `init.svc.bootanim` | stopped | running | running | **stopped ✅** |
| 框架路由到扬声器 | ✓ | ✗ | ✗ | **`AudioFlinger: Output thread AudioOut_D → Output devices: 0x2 (AUDIO_DEVICE_OUT_SPEAKER)`，`CFG_EVENT_CREATE_AUDIO_PATCH: new device 0x2` ✅** |
| 升降/霍尔等 BBK 节点 | 有驱动 | 无驱动 | 无驱动 | 无驱动（源码缺 BBK 私有驱动） |

### 关键差异：内核里有没有 ADSP loader

```
旧构建（TECHPACK=n）Image.gz 里的音频符号：
  aw882xx 0    wcd937x 0    bolero 0    adsp-loader 0    q6afe 0     ← 全部为 0

新构建（TECHPACK=y）Image.gz 里的音频符号：
  adsp-loader 2    q6afe 8    bolero 19    wcd937x 30    aw882xx 27
```

旧构建「卡开机动画」的完整因果链：

```
TECHPACK=n → 内核无 adsp-loader.c → qcom,adsp-loader 节点无人绑定
          → subsystem_get("adsp") 从不调用 → ADSP 不启动
          → /dev/fastrpc-* 返回 ENOTCONN → adsprpcd 死循环
          → 音频 HAL 的 open_snd_mixer 无限重试（retry_num 18…）
          → audioserver 无法发布 media.audio_policy
          → SystemServer 一直等 → 开机永远完不成
```

这也解释了为什么「CRC 放行让厂商模块装上（`lsmod` 1 → 35）」之后仍然无声：
模块装得上，但 **ADSP 依然没人去拉起**。

刷机要点（实测）：

* 本机 **只有在 fastbootd 模式下** `fastboot flash boot` 才被接受
  （bootloader 模式返回 `unknown command`）；
* fastbootd 下 `fastboot getvar is-userspace` 返回 `yes`、
  `getvar product` 返回 `sm6150`（**据此判断当前模式**）；
* 原厂 `imgdata/boot.img` 可直接刷回恢复，功能正常。

> 提醒：本仓库源码缺少 BBK 私有驱动，因此自编译内核在真机上会
> 丢失升降前摄/霍尔/传感器/ramext 等功能。但**声音与相机这两项不依赖它们**，
> 由本仓库自带的音频栈 + 相机 proc 补丁实现。


## 四、已知未覆盖项（源码本身缺失，非本次改动引入）

* BBK 私有驱动：`CONFIG_BBK_RAMEXT*`、`BBK_VIP_THREAD`、`BBK_BINDER_*`、
  `INPUT_IST8801`、`INPUT_MXM1120`、`INPUT_HALL`（真机上存在
  `/sys/class/misc/bbk_hall_core`、`m1120_*`，说明原厂内核有这些驱动）；
* camera_v2 sensor 框架里的 `ov16a10_reg_addr` 等 sysfs 调试属性；
* 真机 `/system/app/BBKCamera.apk` 是 BBK 加密的 BPK 格式，其逻辑无法直接分析。

这些都不影响本次两项修复，但如果后续需要完全还原原厂功能，需要补齐上述驱动。

## 五、触摸：锁屏后卡顿 + 触摸乱上报（第三项修复）

症状：**锁屏后系统非常卡**，日志里**触摸事件乱上报**。

### 根因

`drivers/input/touchscreen/focaltech_touch/focaltech_core.c` 用 `#if/#elif` 链
选择「熄屏通知器」：

```c
#if defined(CONFIG_FB)
    ts_data->fb_notif.notifier_call = fb_notifier_callback;
    ret = fb_register_client(&ts_data->fb_notif);          /* ← 实际编译进了这条 */
#elif defined(CONFIG_DRM)
    ts_data->fb_notif.notifier_call = drm_notifier_callback;
#if defined(CONFIG_DRM_PANEL)
    ... drm_panel_notifier_register(active_panel, ...)
#else
    ... msm_drm_register_client(&ts_data->fb_notif)
#endif
#endif
```

本内核 **`CONFIG_FB=y` 与 `CONFIG_DRM=y` 同时开启**，屏幕由 **MSM DRM（SDE）** 驱动，
所以注册的是**旧的 fb_notifier** —— MSM DRM 显示**永远不会触发** FB blank 事件。
本树里的直接证据：

```
drivers/gpu/drm/msm/msm_atomic.c:266  msm_drm_notifier_call_chain(MSM_DRM_EARLY_EVENT_BLANK, ...)
drivers/gpu/drm/msm/msm_atomic.c:287  msm_drm_notifier_call_chain(MSM_DRM_EVENT_BLANK, ...)
```

而 `fts_ts_suspend()` / `fts_ts_resume()` 的调用点**只**在这些通知回调里
（`fb_notifier_callback` / `drm_notifier_callback`），i2c 驱动上也没有
`dev_pm_ops`（`FTS_PATCH_COMERR_PM == 0`）：

```c
#if defined(CONFIG_PM) && FTS_PATCH_COMERR_PM
        .pm = &fts_dev_pm_ops,
#endif
```

结果熄屏后触摸控制器**一直醒着、IRQ 一直开着**：

* IRQ 持续触发 → 线程化中断反复做 i2c 读 → CPU 被反复唤醒 → **锁屏后很卡**；
* 读回的脏数据被当成触摸点上报 → **触摸乱上报**。

> 驱动来源：`README.txt` 自述「取自 Firefly RK3399 公开源码…**本驱动在 EEBBK S5 测试可用**
> By XiKoTaSu」，是从 S5 移植的第三方通用版本，显示框架不匹配正是此类移植的典型坑。

### 修法

按**本树自己的既有约定**判别与注册，不引入新机制：

* `st/fts.c`：只在 `CONFIG_FB_MSM`（旧 MSM framebuffer）时才走 fb 路径；
* `hxchipset/himax_common.c`：`#ifdef CONFIG_DRM` + `msm_drm_register_client()`。

因此把判别条件由 `CONFIG_FB` 改为 `CONFIG_FB_MSM`，注册 msm_drm 客户端：

```c
#elif defined(CONFIG_DRM) || defined(CONFIG_MSM_DRM)
    ts_data->fb_notif.notifier_call = drm_notifier_callback;
    ret = msm_drm_register_client(&ts_data->fb_notif);
    if (ret)
        FTS_ERROR("[DRM]Unable to register msm_drm notifier: %d\n", ret);
    else
        FTS_INFO("[DRM]msm_drm notifier registered for blank/unblank");
```

同时修掉两个同源问题：

* `<linux/msm_drm_notify.h>` 原先只被包含在**不可达**的 `CONFIG_DRM_PANEL` 的 `#else` 分支里；
* 只匹配 `DRM_PANEL_*` 事件的那个 `drm_notifier_callback` 变体被排除，改用匹配
  `MSM_DRM_*` 事件的变体（与 `msm_drm_register_client()` 配对）。

### 验证（离线，已通过）

```
focaltech_core.o 重新编译：0 warning / 0 error
Image.gz 内：
  msm_drm_register_client / msm_drm_unregister_client      1 / 1
  msm_drm notifier registered for blank/unblank            1
  Unable to register fb_notifier                           0   ← 旧 fb 路径已不再编译
  adsp-loader 2 · driver/BackCamera_info 1                      ← 音频/相机修复未受影响
打包：kernel == Image.gz / ramdisk == factory / dtb == factory   → ALL CHECKS PASSED
```

刷入后锁屏应能看到 `logcat -s FTS_TS` 出现
`[DRM]msm_drm notifier registered for blank/unblank` 与 `DRM event:…,blank:…`，
且熄屏后 `getevent -lt /dev/input/event2` 不再有事件。

## 六、升降前摄（“打开相机自动升起”）结论

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

## 七、真机刷机排查全过程（最终结论：`TECHPACK=n` 把 ADSP loader 挡在内核之外）

按顺序踩到并解决/定位的问题，全部有真机证据：

| # | 现象 | 根因 | 状态 |
|---|---|---|---|
| 1 | 刷入后卡**第一屏** | `.bss.rtic`（含 `selinux_state`）被链接到 `_end` 之外，运行时被页分配器覆盖 | 已修（`vmlinux.lds.S`） |
| 2 | 卡**第二屏**、`lsmod` 只有 1 行 | 源码树带 `.git` → vermagic 变 `4.14.190-perf+`，厂商模块拒装 | 已修（空 `.scmversion`） |
| 3 | 仍 `lsmod`=1 | `CONFIG_MODULE_SIG_FORCE=y` 只认本内核密钥签名的模块 | 已修（`SIG_FORCE=n`，vermagic 不变） |
| 4 | 仍 `lsmod`=1 | `CONFIG_MODVERSIONS` 符号 CRC 不匹配（源码缺 BBK 补丁） | 已修（`kernel/module.c` 的 `bad_version` 改为接受，等价 `modprobe --force`；保留 `MODVERSIONS=y` 维持 vermagic） |
| 5 | 模块终于装上（35 个）、音频 HAL 不再崩，但**声卡仍建不出来** → 卡第二屏 | `/sys/class/sound/` 只有 `timer`；`audio_extn_utils_open_snd_mixer` 无限重试；`adsprpcd` 报 `Transport endpoint is not connected` → **ADSP 没起来**；i2c `2-0034` 无驱动绑定 | 已定位：内核里没有 ADSP loader |
| 6 | 上述根因 | 构建脚本传了 `TECHPACK=n` → `techpack/Kbuild` 只编 `stub/` → 内核里没有 `adsp-loader.c`，`subsystem_get("adsp")` 从不调用；厂商 `audio_adsp_loader.ko` 又因 ABI 不兼容顶不上 | **已修**：改为 `TECHPACK=y`（即不传 `TECHPACK=n`），音频栈 + ADSP loader 全部内置 |

对照原厂内核（同机实测）：`sys.boot_completed=1`、**36 个模块全部加载**、
`/proc/asound/cards` 有 `sm6150-wcd9375-snd-card`、`aw882xx_dlkm` 工作中。
本修复不依赖那批厂商模块，而是让内核自带一份 ABI 自洽的音频栈。

### 交付与交接建议

* 相机 proc 补丁 + 链接布局修复：`s6patch相机/`、`dist/eebbk_s6_camera_proc.patch`
* 声音修复：`s6patch声音/`
* 构建要点：clang-11 + `ld.lld`、**`TECHPACK=y`（不要传 `n`）**、空 `.scmversion`；
  还需 `CONFIG_MODULE_SIG_FORCE=n` + `module.c` CRC 放行（供非音频的厂商模块加载）
* 可刷镜像：`dist/boot_native.img`（`TECHPACK=y`，音频栈已内置并自检通过）
* 设备恢复：`fastboot flash boot imgdata/boot.img`

### 刷机备忘（本机特有）

* 只有 **fastbootd**（`fastboot getvar is-userspace` = `yes` 且接受 `flash`）能刷 `boot`；
  实测三种模式的差别：
  | 进入方式 | `fastboot devices` 序列号 | `flash boot` 结果 |
  |---|---|---|
  | **手动进入 fastbootd** | `2fa7c794` | ✅ 成功 |
  | `adb reboot fastboot` | `0123456789ABCDEF` | ✗ `Unrecognized command download` |
  | 上一步后再 `fastboot reboot bootloader` | `2fa7c794` | ✗ `unknown command`（这是 ABL） |
* 刷自定义 boot 会覆盖 Magisk 的 ramdisk（root 消失）
* 原厂 `imgdata/boot.img`（64 MB，与分区等大）随时可刷回

### 关于 QMMI（高通的工厂测试 App，与本次内核改动无关）

用本内核时曾出现「开机后进入 QMMI 测试界面」的现象，实测**不是内核造成的**：

* 原厂内核下 QMMI 进程**同样**会在开机时被拉起
  （`ActivityManager: Start proc ... for broadcast {com.qualcomm.qti.qmmi/com.qualcomm.qti.qmmi.framework.QmmiReceiver}`）；
* 差别只在于是否抢占前台：原厂内核下前台是 `com.bbk.studyos.launcher`，那次是本内核下
  `QmmiReceiver.startMainActivity` 被调用、QMMI 的 `MainActivity` 成了前台。
* QMMI 监听 `android.intent.action.BOOT_COMPLETED` 与 `android_secret_code`（`7664` = QMMI），
  属于 ROM/工厂测试状态，不是启动模式；`fastboot flash boot imgdata/boot.img` 并正常重启后已回到桌面。

排查中同时确认：QMMI 的 APK（`/system_ext/app/Qmmi/Qmmi.apk`）是**加密封装**
（`unzip` 报 "End-of-central-directory signature not found"），
与之前 `BBKCamera.apk` 的 BPK 情况一致，无法直接静态分析。

---

## 八、升降前摄接口（供后续逆向重写驱动）

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

---

## 九、通知声 / 锁屏提示音 / 升降下降凸起（2026-09-19 补充）

本节针对真机上另外三个问题，全部实测确认；本节结论**不涉及本仓库源码改动**
（升降下降那条走的是原厂校准接口），因此仓库里的 `drivers/misc/gpio_pwm.c` 保持原样。

### 1. 通知声没有（已修复）

通知走 **混音通路**（`AudioOut_D`，`AUDIO_OUTPUT_FLAG_PRIMARY|FAST`），媒体走
**offload 直通 DSP** 通路（`usecase(3: compress-offload-playback)`），两者音量互不影响，
所以会出现“媒体一直正常、只有通知不响”。

| 现象 | 证据（真机） | 处理 |
|---|---|---|
| 扬声器的铃声/通知音量只有 3/15 | `AF::Track: setFinalVolume:0.063096`（≈ -24 dB） | `settings put system volume_ring_speaker 15` + 音量键，增益升到 `0.39~1.0` |
| 用久了所有声音全哑（含媒体） | HAL 的 awinic VI feedback 每次启动都失败：`pcm start for TX failed` → `iv_feedback_count = 2, can't stop feedback!`；内核对应 `SM6150 ASM Loopback: ASoC: no backend DAIs enabled` | 重启即恢复（已实测）；根治见第 4 条 |

### 2. 锁屏提示音没有（已修复）

该 ROM 的锁屏音取自设置项里的**文件路径**，为空时回退到 framework 中并不存在的
`R.raw.lock`（解析 `framework-res.apk` 的 `resources.arsc` 可确认 raw 类型只有
loaderror / nodomain / color_fade_* / fallback_categories / fallbackring 六个条目）。

```bash
settings put global lock_sound   /product/media/audio/ui/Lock.ogg
settings put global unlock_sound /product/media/audio/ui/Unlock.ogg
```

`/product/media/audio/ui/` 里本就有完整的 Lock.ogg / Unlock.ogg；`/system/media/audio/ui/`
只剩 3 个文件，所以截屏声正常而锁屏声缺失。实测锁屏、解锁各产生一次 SoundPool 播放
（`setFinalVolume 0.126` / `0.309`）。

### 3. 升降前摄降到底后仍有明显凸起（已修复）

机制：驱动按 `all_time`（校准里的 `cali_time`）开环驱动，应用请求 `MID→DOWN` 时
下降时长与上升相同：

```
vib_pwm_move_to: want 1, current 0 -> up for 1941 ms, retry 3
vib_pwm_move_to: want 0, current 1 -> down for 1941 ms, retry 3
```

实际驱动时间 = `time_ms × 6/10`（`VIB_PWM_MOVE_NUM/DEN`，19200 Hz 标称值折算到 32000 Hz）。
原厂靠霍尔闭环（`add_time` 重试）补上下降行程，而本机霍尔一直 standby
（`bbk_hall_data = up:-2000 down:-2000`），闭环失效 → 每次下降都差一截。

**修法（不改内核、不刷机）**：`/dev/bbk_hall_core` 是 0666 的 misc 设备，其 ioctl 会把
56 字节校准结构体拷进内核并调用 `set_vib_all_time()`：

| ioctl | 作用 |
|---|---|
| `0x40046000` `BBK_HALL_CORE_IOCTL_SET_CALI` | 写入并持久化到 `/mnt/vendor/persist/sensors/cali_hall` |
| `0x40046001` `BBK_HALL_CORE_IOCTL_TRANS_CALI` | 只改内存（重启还原，适合试值） |

`struct hall_cali_data` 共 56 字节，`int cali_time` 位于 `+0x34`。
工具源码见 `patch+++/tools/elev.c`，静态 aarch64 二进制随交付。

```bash
adb push elev /data/local/tmp/elev && adb shell chmod 755 /data/local/tmp/elev
adb shell /data/local/tmp/elev trans 3630   # 试值：重启还原
adb shell /data/local/tmp/elev set   3630   # 定值：写入 persist，重启保持
```

**采用值：`cali_time` 2790 → 3630（+30%）**，实测升降时长 1941 → 2526 ms，
相机 App 升起→退出后**降到底贴合、无凸起**，升起高度正常。回退：
`/data/local/tmp/elev set 2790`。

> 注意：用 sysfs 直接写 `vib_pwm_camera_state` 与相机 App 的真实流程结果不同，
> 只有直接写 sysfs 时会看到凸起；以相机 App 的实测为准。

### 4. 未完成项与风险

* **awinic VI feedback / `SM6150 ASM Loopback` 无后端 DAI 未根治**：这是“用久了全哑”的
  根源。HAL（`/vendor/lib64/hw/audio.primary.sm6150.so`）里的
  `audio_extn_aw882xx_start_feedback` 用 `msm-pcm-loopback`（MultiMedia6）做 VI feedback，
  该 FE 没有后端 DAI 导致 `pcm start for TX failed`。根治方向：给该 FE 配后端 DAI，
  或在 HAL 侧关掉 feedback（该库含 `vendor.audio.feature.dsm_feedback.enable` 等字符串）。
* **内核重编后两次卡开机**（原因未查明）：两次分别用“增量重编”和“删除 out_native 全新编译”
  构建，均卡在开机画面（USB 不枚举），对照刷回旧镜像立刻正常。已排除：编译配置
  （内嵌 `.config` 逐行相同）、编译器（clang 11.1.0-6 / LLD 11.1.0）、链接器、模块兼容性
  （`wlan.ko` 的 387 个符号 CRC 与新版 `Module.symvers` 全部一致）、源码差异
  （仅 `gpio_pwm.c`/`kernel.h`/`module.c` 三处良性改动）。因此升降的下降补偿改用校准方案。
  未验证的 `down_extra_permille` 改动保留为
  `patch+++/optional-elevator-down-margin.patch`，**未合入**。
* **霍尔仍 standby**（`up:-2000 down:-2000`），闭环未恢复。

---

## 十、霍尔传感器：驱动层已修好，但服务侧闭环会让升降“卡一半”（2026-09-19）

### 1. 结论先说
* **硬件和驱动都没坏**：两颗 MXM1120（`magnachip@0c`=down、`magnachip@0f`=up，I2C-2）
  ID 都是 `0x9c`，I2C 读写正常。
* 之前霍尔一直“standby（`bbk_hall_data` 显示 -2000）”是**本仓库驱动的有意行为**：
  `drivers/input/misc/mxm1120.c` 的 `m1120_set_operation_mode()` 只写了模式位 `0x40`，
  没有置原厂的 START 位（`mode | 0x09`），芯片因此从不开始转换，
  `0x10` 块的 DRDY（bit0）永远为 0 → 每个采样都被判为无效。
* 置上 START 后**霍尔立即正常工作**（见下），但一旦有有效采样，
  `com.eebbk.camera` 的竖升只会到 **MID（约 70%）就停住**（用户所说“卡一半”），
  这正是当年把霍尔留在 standby 的原因。服务侧（camera 服务内的
  `EEBBK/ElevatorCmdQueThread`）我们改不了，所以**霍尔改动暂不合入**。

### 2. 实测：置 START 后霍尔数据有效且随位置变化
`opmode 0x49`（= `0x40 | 0x09`）后，`/sys/bus/i2c/drivers/mxm1120/…/dump` 的 `0x10` 块
读到 `[10]=01`（DRDY 置位），`bbk_hall_data` 不再是 -2000：

| 升降位置 | up | down |
|---|---|---|
| DOWN (0) | 1 | -721 |
| MID (1) | 1 | -542 |
| FULL (2) | -513 | -515 |
| HOLDER (7) | -513 | -514 |
| 再回 DOWN | 1 | -723（可复现） |

### 3. 过程中发现并修正的一件事
之前为了改行程时间用 `SET_CALI` 持久化时，把同一块 56 字节 blob 里
**霍尔位置标定点写成了 0**（原本是负值）。虽然实测它**不是**“卡一半”的原因
（重建标定后 App 仍然卡一半），但 0 值标定本身是错的，现已按上表实测值重建并写回
`/mnt/vendor/persist/sensors/cali_hall`：

```
pos0   up=1  down=-721  diff=722      pos1   up=1  down=-718  diff=719
pos24  up=1  down=-659  diff=660      pos6   up=1  down=-706  diff=707
pos48  up=1  down=-598  diff=599      pos696 up=1  down=-542  diff=543
cali_time = 3630
```

写 blob 的工具：`/data/local/tmp/elev setfile <blob>`（源码见 `patch+++/tools/elev.c`）。

### 4. 顺便解决：内核重编后“卡在开机画面”的原因
仓库自带的 `build_eebbk_clang11.sh` **能编出正常开机的内核**（本次实测
`boot_hall.img`，内核 `#1`，正常启动）。之前两次卡开机是我用临时 `make` 命令
（复用既有 `out_native/.config`、没有先删 out 目录、没有走脚本的两遍 `olddefconfig`
与 `CONFIG_MODULE_SIG_FORCE` 处理）造成的构建状态问题。
**以后一律用该脚本构建**，配置用 `arch/arm64/configs/` 下的文件
（新增 `h130_debug.config` = 带 `CONFIG_BBK_DEBUG_BRINGUP=y` 的调试配置）。

### 5. 当前状态与后续
* 设备已刷回 `boot_elev_dbg.img`（内核 #52），霍尔回到 standby，
  相机/升降行为与修复前一致（下降贴合靠 `cali_time=3630`）。
* 霍尔补丁保留为 `patch+++/optional-hall-enable-start-bit.patch`，**未合入**。
* 若将来要让霍尔闭环生效，需要继续做：查清 camera 服务在有有效采样时为何只升到 MID
  （可能需要补它真正调用的接口或它的状态机所依赖的节点），以及把厂家的
  `vib_pwm_state_move_sate`/`vib_pwm_state_init` 闭环路径补全。
