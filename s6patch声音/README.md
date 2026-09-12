# s6patch声音 — EEBBK S6 (P20H130 / sm6150) 无声问题修复

**根因已定位、修复已完成，并已在真机验证通过 ✅**（`sys.boot_completed=1`、
`/sys/class/sound/card0` 建出 23 个播放设备、音频 HAL 打印
`snd_card_name: sm6150-wcd9375-snd-card` 与 `Opened sound card:0`、
AudioFlinger 已把输出线程路由到 `AUDIO_DEVICE_OUT_SPEAKER`）。

> **两层根因**，缺一层都不行：
> 1. 构建脚本传了 `TECHPACK=n` → 内核里没有音频栈、**尤其没有 ADSP loader** → ADSP 起不来；
> 2. `sm6150.c` 把机驱动的 codec 名硬编码成 **TFA98xx**，而本机功放是 **AW882xx** →
>    声卡永远 `-EPROBE_DEFER`，建不出来。
> 详见下面「证据链」与「真机验证结果」。

---

## 一句话结论

> 之前的构建脚本传了 `TECHPACK=n`，导致 `techpack/` 下**只编译了 `stub/`**——
> 整个内核镜像里音频代码为 0，**尤其是负责拉起 ADSP 的 `adsp-loader.c` 不在内核里**。
> ADSP 起不来 → `adsprpcd` 死循环 → 声卡建不出来 → `media.audio_policy` 起不来 → 卡开机动画。
> **修复 = 不要再传 `TECHPACK=n`**（`techpack/Kbuild` 里 `TECHPACK?=y` 本来就是默认值）。

---

## 证据链

### 1. 旧镜像里 techpack 是空的（实测）

| 构建 | `out/techpack` 下的目标文件 | 结果 |
|---|---|---|
| `TECHPACK=n`（旧） | **1 个**（空的 `techpack/built-in.o`） | 声卡 0 个，卡开机动画 |
| `TECHPACK=y`（新） | **87+ 个**（`asoc/` `dsp/` `ipc/` `bolero` `wcd937x` `awinic` …） | 音频栈齐全 |

`techpack/Kbuild` 原文：

```make
TECHPACK?=y
obj-${TECHPACK} += stub/ $(addsuffix /,$(subst $(srctree)/techpack/,,$(techpack-dirs)))
```

传 `n` 就等于只编 `stub/`。

### 2. 设备实测症状，正好全部指向「ADSP 没起来」

```
adsprpcd : apps_dev_init failed for domain 0, errno Transport endpoint is not connected   ← 死循环
audio_hw_utils: audio_extn_utils_open_snd_mixer: retry, retry_num 18                      ← 无限重试
/sys/class/sound/            → 只有 timer，没有 card0
/sys/bus/i2c/devices/2-0034/driver → 不存在（未绑定）
ServiceManager: Waiting for service 'media.audio_policy' …                                ← 开机永远完不成
```

`/dev/fastrpc-*` 打不开、报 ENOTCONN，含义就是 **ADSP 远程处理器没有运行**。

### 3. 拉起 ADSP 的驱动就在 techpack/audio 里

`techpack/audio/config/sm6150auto.conf`（由 `techpack/audio/Makefile` 在
`CONFIG_ARCH_SM6150=y` 时强制 include 并 export）：

```make
CONFIG_MSM_ADSP_LOADER=y      ← ADSP loader
CONFIG_MSM_QDSP6_SSR=y
CONFIG_MSM_QDSP6_APRV2_RPMSG=y
CONFIG_SND_SOC_SM6150=y       ← 本机声卡机驱动
CONFIG_SND_SOC_BOLERO=y
CONFIG_WSA_MACRO=y / CONFIG_VA_MACRO=y / CONFIG_RX_MACRO=y / CONFIG_TX_MACRO=y
CONFIG_SND_SOC_WCD937X=y
CONFIG_SND_SMARTPA_AW882XX=y
```

`techpack/audio/dsp/adsp-loader.c`：

```c
static const struct of_device_id adsp_loader_dt_match[] = {
	{ .compatible = "qcom,adsp-loader" },
	...
	adsp_state = apr_get_q6_state();
	if (adsp_state == APR_SUBSYS_DOWN) {
		priv->pil_h = subsystem_get("adsp");   /* ← 拉起 ADSP */
```

### 4. 设备树本来就把所有东西都描述好了（**无需改 DT**）

boot.img 里的 dtb 段共 10 棵基础树，其中 `boot08` = **SDMMAGPIEP SoC**（本机），
dtbo.img 里 9 个覆盖层，其中 `dtbo02/04/05/07` 带 `qcom,hall`（BBK 升降霍尔）+ bbk/h130
标记，是 BBK 的覆盖层。关键的四处节点：

```
boot08.dts:17336   qcom,msm-adsp-loader { compatible = "qcom,adsp-loader"; }        ← 匹配内置 adsp-loader.c
boot08.dts:4471    compatible = "qcom,pil-tz-generic";  mbox-names = "adsp-pil";    ← subsystem_get("adsp") 用
boot08.dts:17226   sound { compatible = "qcom,sm6150-asoc-snd"; ... }               ← 匹配内置 sm6150.c
dtbo04.dts:4342    fragment@54 → qcom,model = "sm6150-wcd9375-snd-card";            ← 声卡名（HAL 认这个）
```

`sm6150.c` 用 `snd_soc_of_parse_card_name(card, "qcom,model")` 取卡名，所以运行时
卡名就是 **`sm6150wcd9375sn`**（ALSA 截断到 15 字符），与厂商音频 HAL 的
`get_sndcard_id()` 期望一致。

**boot.img 打包时 dtb 段逐字节保留原厂**（`mkboot2.py` 里 `chk("dtb == factory")`），
所以上述节点一定和设备实际使用的一致。

### 5. 厂商模块顶不上

`/vendor/lib/modules` 里的 `audio_adsp_loader.ko` 等是用**厂商内核**链接的，
与本仓库编出的内核 ABI 不兼容（`struct module` / 符号 CRC 不同），
所以它无法在这里拉起 ADSP —— 必须由内核自己带这份代码。

---

### 6. 机驱动的 codec 名字写错了（**这是第二层根因，缺了它照样无声卡**）

把音频栈编进内核后，日志里出现了新的、更具体的报错：

```
<6>[ 1.458757] [Awinic][2-0034]aw882xx_read_chipid: aw882xx 1852 detected
<6>[ 1.462112] [Awinic][2-0034]aw882xx_dai_drv_append_suffix: dai name [aw882xx-aif-2-34]
<6>[ 1.467360] [Awinic][2-0036]...                                        ← 两颗功放都认到了
<3>[10.442602] sm6150-asoc-snd ...: ASoC: CODEC DAI tfa98xx-aif-2-34 not registered
```

`techpack/audio/asoc/sm6150.c` 的 `populate_snd_card_dailinks()` 里有一段本地改动
（带中文注释），把两个 MI2S 后端 link 的 **legacy 单 codec 字段**硬编码成 TFA98xx：

```c
msm_mi2s_be_dai_links[0].codec_name     = "tfa98xx.2-0034";
msm_mi2s_be_dai_links[0].codec_dai_name = "tfa98xx-aif-2-34";
msm_mi2s_be_dai_links[1].codec_name     = "tfa98xx.2-0036";
msm_mi2s_be_dai_links[1].codec_dai_name = "tfa98xx-aif-2-36";
```

但本机（P20H130）用的**不是 TFA98xx，而是 AWINIC AW882xx**（i2c 2-0034 左 / 2-0036 右），
aw882xx 驱动注册的 DAI 是 `aw882xx-aif-2-34` / `aw882xx-aif-2-36`。

致命之处在于 `sound/soc/soc-core.c` 的 `snd_soc_init_multicodec()`：

```c
	/* Legacy codec/codec_dai link is a single entry in multicodec */
	if (dai_link->codec_name || dai_link->codec_of_node ||
	    dai_link->codec_dai_name) {
		dai_link->num_codecs = 1;
		dai_link->codecs[0].name     = dai_link->codec_name;
		dai_link->codecs[0].dai_name = dai_link->codec_dai_name;
	}
```

只要 legacy 字段非空，link 就被收缩成「1 个 codec」，并且 **`codecs[0]` 被整体覆盖**——
于是同一张表里**本来就正确的** `awinic_codecs[]` 被丢弃：

```c
/* 同一个文件 6900 行，由 CONFIG_SND_SOC_AWINIC_AW882XX 选中，值完全正确 */
struct snd_soc_dai_link_component awinic_codecs[] = {
	{ .dai_name = "aw882xx-aif-2-34", .name = "aw882xx_smartpa.2-0034" },
	{ .dai_name = "aw882xx-aif-2-36", .name = "aw882xx_smartpa.2-0036" },
};
```

结果：`snd_soc_register_card()` 永远返回 `-EPROBE_DEFER` → 声卡建不出来 →
厂商音频 HAL 在 `get_sndcard_id()` 段错误 → `media.audio_policy` 起不来 →
**卡开机动画第二屏**。

**原厂是怎么做的（反证）**：从 `super_5.img` 提取的原厂机驱动 `machine_dlkm.ko`：

* 里面**没有** `dual speaker configured (34 & 36)` 这条字符串（说明那 4 行不是原厂代码）；
* 符号表里有 `aw882xx_dails`（**48 字节 = 2 × `snd_soc_dai_link_component`**）、
  `tfa98xx_dails`、`fs16xx_codecs`——即原厂**一律通过 `.codecs`/`.num_codecs` 组件表**
  提供 codec，从不使用 legacy 字段。

**修复 = 删掉那 4 行赋值**，让 link 表里的 `awinic_codecs` 生效（见补丁 `0004`）。

## 补丁

| 文件 | 作用 |
|---|---|
| `0001-kernel-module-accept-vendor-crc.patch` | `kernel/module.c`：符号 CRC 不匹配时放行厂商 DLKM（等价 `modprobe --force`）。保留 `CONFIG_MODVERSIONS=y`，因为 `modversions` 是 vermagic 的一部分（关掉会变成 `… mod_unload aarch64`，与厂商模块 `… mod_unload modversions aarch64` 不匹配）。实测 `lsmod` 1 → 35，音频 HAL 不再在 `get_sndcard_id()` 段错误。**注意这一条只解决「模块装不上」，不解决无声。** |
| `0002-config-add-factory-config.patch` | 加入原厂内核内嵌的 `.config`（`h130_factory.config`，从 `boot.img` 的 IKCONFIG 提取，160118 字节），保证内建/模块划分与原厂一致。 |
| `0003-build-script-clang11-audio-builtin.patch` | 构建脚本：`TECHPACK=y`（即不传 `TECHPACK=n`），让音频栈 + **ADSP loader** 编进内核；并附编后自检。**第一层根因的修复。** |
| `0004-sm6150-aw882xx-speaker-codec.patch` | `techpack/audio/asoc/sm6150.c`：删掉把 link 硬编码成 TFA98xx 的 4 行，恢复 `awinic_codecs`（AW882xx）。**第二层根因的修复，也是声卡真正建出来的那一步。** |

### 构建条件（脚本已含，但必须知道）

* 源码根目录放一个**空的 `.scmversion`** —— 否则带 `.git` 的树会让 kernelrelease 变成
  `4.14.190-perf+`，厂商模块 vermagic 不匹配 → 全部拒装。
* `CONFIG_MODULE_SIG_FORCE=n` —— 厂商模块用原厂密钥签名，本内核验签必然失败。
* `LD=ld.lld` —— GNU ld 2.38 链接这个 4.14 树会失败（见相机目录的 `vmlinux.lds.S` 补丁）。
* `KBUILD_BUILD_USER=cp KBUILD_BUILD_HOST=ubuntu165` —— 与原厂一致。

### 用法

```bash
# 在一棵全新解压的原始源码树上：
cp -r s6patch声音/*.patch s6patch相机/*.patch <kernel tree>/
cd <kernel tree>
for p in s6patch相机/0*.patch s6patch声音/0*.patch; do git apply "$p" || patch -p1 < "$p"; done
: > .scmversion
./build_eebbk_clang11.sh            # 默认 TECHPACK=y（正确）
# 产物 out/arch/arm64/boot/Image.gz
```

### 补丁集自检（已验证）

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

---

## 新镜像的离线自检结果（`TECHPACK=y`）

```
rc=0
kernelrelease = 4.14.190-perf                      ← vermagic 精确匹配
Linux version 4.14.190-perf (cp@ubuntu165) (Ubuntu clang version 11.1.0-6, LLD 11.1.0) #1 SMP PREEMPT

Image.gz 里的音频符号：
  adsp-loader             2      ← 关键：ADSP loader 在内核里
  q6afe                   8
  bolero                 19
  wcd937x                30
  aw882xx                27
  driver/BackCamera_info  1      ← 相机补丁同时在
  driver/FrontCamera_info 1

boot_native.img 打包自检：
  kernel == Image.gz    OK
  ramdisk == factory    OK
  dtb == factory        OK
  header_version/addr/os OK
  RESULT: ALL CHECKS PASSED
```

对比旧镜像（`TECHPACK=n`）：音频符号**全为 0**。

---

## 真机验证结果（已通过）

`boot_audio2.img` 刷入真机后实测（设备 EEBBK S6 / P20H130，serial `2fa7c794`）：

| 检查项 | 结果 |
|---|---|
| 内核 | `Linux version 4.14.190-perf (cp@ubuntu165) (Ubuntu clang version 11.1.0-6, LLD 11.1.0) #2 SMP PREEMPT` |
| `getprop sys.boot_completed` | **`1`** ✅（旧镜像一直为空、卡开机动画） |
| `getprop init.svc.bootanim` | `stopped` ✅ |
| `ls /sys/class/sound/` | **`card0`** + `controlC0` + **23 个 `pcmC0D*p` 播放设备** + 12 个 `comprC0D*` ✅（旧镜像只有 `timer`） |
| 声卡名 | `audio_hw_utils: audio_extn_utils_open_snd_mixer: snd_card_name: sm6150-wcd9375-snd-card` ✅ |
| HAL 打开声卡 | `audio_hw_utils: audio_extn_utils_open_snd_mixer: Opened sound card:0` ✅（旧镜像是 `retry, retry_num 1..40` 然后 `Unable to find correct sound card, aborting`） |
| 音频 HAL 崩溃 | 无（旧镜像 `audio.horizon.default.so (get_sndcard_id+572)` 反复 SIGSEGV） |
| `adsprpcd` | 不再刷 `Transport endpoint is not connected`，3 个进程稳定 ✅ |
| 框架路由 | `AudioFlinger: Output thread AudioOut_D → Output devices: 0x2 (AUDIO_DEVICE_OUT_SPEAKER)`, `CFG_EVENT_CREATE_AUDIO_PATCH: new device 0x2` ✅ |
| 播放设备配置 | `audio_hw_utils: send_app_type_cfg_for_device PLAYBACK app_type 69937, acdb_dev_id 15, sample_rate 48000, snd_device_be_idx 45` ✅ |
| 相机 proc 节点 | `/proc/driver/BackCamera_info`、`FrontCamera_info` 都在 ✅，`dumpsys media.camera` → `Number of camera devices: 1`（后摄；前摄需原厂私有 sensor 代码） |

即：**开机完整完成 + 声卡正常创建 + 音频 HAL 正常打开并路由到扬声器。**

> 注：shell 无 root，`/dev/snd/*` 属主为 `system:audio`，所以无法用 `tinyplay` 直接放音做「听觉」验证；
> 上面的 HAL / AudioFlinger / 声卡设备节点证据是框架层的完整链路。
> 直观确认只需在设备上放一段音乐或视频。

**回滚**：`fastboot flash boot imgdata/boot.img`

### 刷机备忘（本机特有，实测）

* `adb reboot fastboot` → 序列号 `0123456789ABCDEF`，`flash boot` 报
  `Unrecognized command download`（**不能刷**）；
* 再 `fastboot reboot bootloader` → 序列号变 `2fa7c794`，但若为 ABL bootloader 模式则报
  `unknown command`（**也不能刷**）；
* **只有手动进入的 fastbootd**（`fastboot getvar is-userspace` = `yes` 且 `flash` 被接受）能刷。

---

## 附：不适用本机的参考

Unisoc 平台 `rtyutechstudio/android_kernel_EEBBK_P21H180`（`D:\android_kernel_EEBBK_P21H180-main.zip`）
的两个音频提交 —— `10f2600` 的 `sound/soc/sprd/*` 与 `47f06ca` 的 AW87xxx 爆音修复 ——
**对本机不适用**：平台音频框架不同（Spreadtrum `sound/soc/sprd/ext_hook_arr` vs
高通 `techpack/audio` APR/Q6），且 S6 用的是 AW882xx 而非 AW87xxx，症状也不同
（本机是「没有声卡」，不是「爆音」）。
