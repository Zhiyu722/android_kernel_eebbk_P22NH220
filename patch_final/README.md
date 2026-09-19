# EEBBK S6（P20H130 / sm6150）内核补丁集 —— patch final

| 项 | 值 |
|---|---|
| 基线 | 本仓库提交 `525066d92`（`arm64: eebbk: Import the S6 (P20H130) vendor tree and restore the camera info nodes`） |
| 终态 | 仓库 `master` 的当前提交（见根 `README.md` 顶部「本版提交」） |
| 覆盖 | 相对基线的**全部**改动：**166 个文件**（+12 万行，主要是内置的 KernelSU 源码） |

> 基线提交本身是「原厂源码导入」，所以**在这些补丁之前的那棵树就是原厂状态**：
> `git checkout 525066d92` 或直接用厂家的源码包。


> 本补丁集本身不包含在自己的序列里：`patch_final/` 是**派生交付物**（源码才是源头），
> 生成 clean 补丁与 per-commit 序列时都已排除它，否则每次重新生成都会把整个补丁集再塞进提交里。

---

## 一、两种用法

### A. 主题补丁（推荐：8 个文件，按顺序打）

```sh
cd <内核源码根>            # 需要是一个 git 仓库（git apply 也用于校验二进制补丁）
git apply patch_final/0*.patch
```

> ⚠️ 请用 `git apply`。`01`、`03`~`08` 用 `patch -p1` 也能打，但 **`02-audio-techpack.patch` 里带
> 4+4 个 aw882xx 寄存器表 `.bin`（二进制补丁）**，`patch -p1` 处理不了 git 的二进制补丁格式；
> 没有 `git` 时请手动把那 8 个文件（`firmware/` 与
> `techpack/audio/asoc/codecs/awinic/firmware/`）拷进去，再打其余的补丁。

| 顺序 | 补丁 | 内容 | 文件数 | 详见 |
|---|---|---|---|---|
| 1 | `01-build-linker-and-module.patch` | `.bss.rtic` 链接布局修复、放行厂商 DLKM 的签名/CRC、`.scmversion`、版本串、构建脚本 | 7 | 七节 |
| 2 | `02-audio-techpack.patch` | techpack 音频栈与 ADSP loader 编进内核、机驱动换 AW882xx、功放启动与寄存器表（含 4 个 `.bin`）、32bit 采样、TERT MI2S VI feedback mux | 10 | 一~七节 |
| 3 | `03-camera.patch` | `cam_eeprom` 按原厂方式读内存映射并恢复 `/proc/driver/*Camera_info`；`cam_sensor` 接受 1 字节 id | 2 | 七节 |
| 4 | `04-input-touch-hall.patch` | FTS 触摸改用 MSM DRM notifier；新增 `bbk_hall_core` 框架与 MXM1120 驱动（START/待机、卡住判定） | 10 | 八、十、十一节 |
| 5 | `05-elevator-and-debug.patch` | `gpio_pwm` 升降电机驱动、GP 低频频点表、`bbk_debug` 的 `/proc/eebbk_kmsg`、`/proc/eebbk_pins` | 5 | 六、十节 |
| 6 | `06-root-resukisu.patch` | 内置 ReSukiSU（KernelSU 非 GKI 分支，124 个文件）+ 4.14 的六个手动钩子 + 构建接线 + `tools/ksu/` 脚本 | 124 | 十二节、`KernelSU/VENDORED.md` |
| 7 | `07-configs.patch` | `arch/arm64/configs/h130_{debug,release}.config`（KSU、容器支持等；`h130_factory.config` 是原厂基线） | 3 | 十六节 |
| 8 | `08-docs.patch` | 技术总账 `EEBBK_S6_changes.md`、过程记录、根 `README.md`、`docs/` 两份专题报告 | 5 | ⟨全部⟩ |

### B. 完整提交序列（复现历史 / 需要二分定位时）

```sh
git am patch_final/per-commit/*.patch        # 67 个提交
```

这个序列是本项目的真实开发历史，包含文档与整理类提交——其中几次提交会**先加入、后来又删除**
早期的 `patch12/`、`patch+++` 补丁目录（那是被本补丁集取代的旧版），属正常历史，不影响最终树。

---

## 二、打完之后怎么编

```sh
OUT=out_release CONFIG=h130_release.config TECHPACK_MODE=y ./build_eebbk_clang11.sh
# 打包（把 wlan.ko 塞进 ramdisk，WiFi 依赖它）
python3 mkboot3.py out_release/arch/arm64/boot/Image.gz boot.img <wlan.ko>
```

**必须**用仓库自带脚本：手写 `make` 复用旧 `out` 目录编出来的内核在本机实测**不能开机**；
`TECHPACK_MODE` 必须是 `y`（`n` 会把 ADSP loader 挡在内核之外 → 完全没声音）。

---

## 三、注意事项

1. `02-audio-techpack.patch` 里带 4 个 aw882xx 寄存器表 `.bin`，是用 `git diff --binary` 生成的，
   `patch -p1` 与 `git apply` 都能处理。
2. `06-root-resukisu.patch` 中 `drivers/kernelsu` 是指向 `../KernelSU/kernel` 的**符号链接**：
   需要在支持符号链接的文件系统上操作（Linux/WSL），别用会把符号链接变成普通文件的解压/复制方式；
   `git apply` 不受影响。
3. KernelSU 在这里是**内置源码**而不是 git submodule：submodule 在 tar/zip 交付里会丢，
   而且 git 不允许跟踪含 `.git` 的路径；两处适配（版本号、生成头文件路径）见 `KernelSU/VENDORED.md`。
4. 每个补丁的文件清单都写在补丁开头的注释里，方便核对。

---

## 四、真机验证情况（摘要）

| 补丁 | 验证 |
|---|---|
| 01 构建/模块 | 厂商 `wlan.ko`/音频模块能加载；`Image.gz` 正常链接 ✓ |
| 02 音频 | 媒体/通知/锁屏都有声（通知音量需 ≥ 某阈值，见文档九节）；功放启动 ✓ |
| 03 相机 | 前后摄可用，`/proc/driver/{Back,Front}Camera_info` 恢复 ✓ |
| 04 触摸/霍尔 | 锁屏后不卡顿；霍尔 `id=0x9c`、位置可读、升降不再「卡一半」 ✓ |
| 05 升降/调试 | 上升到位、下降贴合（`cali_time=3630`）、`/proc/eebbk_kmsg` 可过滤 ✓ |
| 06 root | `KernelSU: driver version 35144 ... Work mode: Built-in`，`su -c id` → `uid=0 context=u:r:ksu:s0` ✓ |
| 07 配置 | Droidspaces v6.5.0 自检全项 ✓（PID/IPC ns、devtmpfs、user ns） ✓ |
| 08 文档 | — |

未解决项（诚实清单）见根 `README.md` 第五节：扬声器保护回采导致的「用久了全哑」（`spkr_prot`）、
Android 15/16 GSI 的 BPF 缺口、`/vendor` 瘦身未采用。
