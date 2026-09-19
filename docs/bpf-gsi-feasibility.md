# 在 EEBBK S6（sm6150 / kernel 4.14.190）上跑 Android 15/16 GSI：BPF 反向移植可行性评估

日期：2026-09-19　设备：EEBBK S6（adb `7013T3603C41X`，fastboot `2fa7c794`，已解锁）
内核：本仓库自编 `4.14.190-perf`（clang 11.1.0 + lld，已带 ReSukiSU）
触发来源：酷安帖 `https://www.coolapk.com/feed/64983795`（作者 tiffanyy，2025-05-25，「补 bpf」）

---

## 0. 结论先说

1. **纯 BPF 层面：技术上可行，但工作量是「千级提交」量级，不是一次改动能收的。**
   * 实测同类机型：小米 sm8250（4.19 内核）的 `backport-5.10-bpf` 分支相对它的 A15 分支
     **+1444 个提交**（GitHub compare API：`ahead_by = 1444`）。
   * 4.14 的参考实现（MTK 天玑 1200 的 `jsdizkcksv/android_kernel_aresin`，默认分支就是 **A16**）
     的 `kernel/bpf/` 已经从 4.14 原生的一小撮文件扩到含 **`btf.c`、`local_storage.c`、`cpumap.c`、
     `disasm.c`、`offload.c`** —— 也就是把 5.x 的 BPF 子系统整体搬了进来。
2. **但 BPF 不是唯一门槛。** A15/A16 GSI 还要过 Treble / vendor API 级别 / VNDK / HAL 这几关，
   本机 vendor 是 Android 11（API 30）原厂。这一层过不去的话，BPF 做完也开不了机。
3. **建议路线：先拿 A13 / A14 GSI 验证整条链路**（社区经验：4.14 内核原本能开 A13），
   确认真机硬件/HAL 能跑起来，再决定是否为 A15/A16 做这笔 BPF 大移植。

---

## 1. 官方硬要求（已核实，不是传言）

| 项 | 内容 | 证据 |
|---|---|---|
| AOSP 提交 | **"NetBpfLoad: enforce kernel 5.4 for Android W"**，Merged 2025-01-14 | `platform/packages/modules/Connectivity` change **3285058**（`android-review.googlesource.com` 查询，作者 Maciej Żenczykowski / Patrick Rohr） |
| 后果 | 内核 < 5.4 时 bpf loader 拒绝加载，重启日志 `bpfloader-failed`，表现为「一屏重启回主系统」 | 同上 + 酷安帖描述 |
| 两条路 | ① 内核反向移植 A15/A16 所需的 BPF（社区叫「合并 BPF」）；② system 层用 GSI 里已处理好的 BPF | 酷安帖；作者明确说 A16 阶段 ② 暂不可行（BPF 程序终究要内核接受） |

---

## 2. 我们这棵 4.14.190 现在的 BPF 家底（实测，非推测）

**配置（`out_ksu_rel/.config`）——帖子里列的 8 项依赖我们全都有：**

```
CONFIG_CGROUP_BPF=y            CONFIG_BPF=y
CONFIG_BPF_SYSCALL=y           CONFIG_BPF_JIT_ALWAYS_ON=y
CONFIG_NETFILTER_XT_MATCH_BPF=y CONFIG_NET_CLS_BPF=y
CONFIG_BPF_JIT=y               CONFIG_HAVE_EBPF_JIT=y
（CONFIG_BPF_EVENTS=y；CONFIG_DEBUG_INFO_BTF 没有）
```

**`kernel/bpf/` 现有文件（4.14 原生规模）**
`arraymap.c bpf_lru_list.c cgroup.c core.c devmap.c hashtab.c helpers.c inode.c lpm_trie.c
 map_in_map.c percpu_freelist.c sockmap.c stackmap.c syscall.c tnum.c verifier.c`

**map 类型（16）**：ARRAY、HASH、PERCPU_ARRAY/HASH、LRU_HASH、LRU_PERCPU_HASH、LPM_TRIE、
ARRAY_OF_MAPS、HASH_OF_MAPS、PROG_ARRAY、PERF_EVENT_ARRAY、CGROUP_ARRAY、DEVMAP、SOCKMAP、STACK_TRACE

**prog 类型（17）**：SOCKET_FILTER、KPROBE、SCHED_CLS、SCHED_ACT、TRACEPOINT、RAW_TRACEPOINT、
XDP、PERF_EVENT、CGROUP_SKB、CGROUP_SOCK、LWT_IN/OUT/XMIT、SK_SKB、SOCK_OPS

**`bpf()` 命令只有 3 个**：`MAP_CREATE`、`PROG_LOAD`、`PROG_TEST_RUN`
（没有 `BTF_LOAD`、没有 `LINK_CREATE`）

**明确缺失**：BTF（`btf.c`/`BTF_KIND_*`）、`RINGBUF`、`SK_STORAGE`、`QUEUE`/`STACK`、`STRUCT_OPS`、
`bpf_link`、`BPF_JMP32`、`bpf_iter`、`BPF_PROG_TYPE_EXT/LSM`、`BPF_FUNC_ringbuf_*`、`BPF_FUNC_spin_lock` 等

---

## 3. 缺口清单（按依赖顺序，也就是要合的东西）

1. **基础设施**：BTF 全套（`kernel/bpf/btf.c`、`BTF_LOAD`、`BTF_KIND_*`、verifier 里的 BTF 校验、
   `CONFIG_DEBUG_INFO_BTF`）——A16 的「ebpf 模块」按帖子说就要 BTF。
2. **新 map 类型**：`RINGBUF`（5.8）、`SK_STORAGE`（5.2）、`QUEUE`/`STACK`（4.20）、
   `STRUCT_OPS`（5.6）、`CGROUP_STORAGE`，以及 `BPF_F_LOCK`/`bpf_spin_lock` 语义。
3. **新 prog 类型与挂载方式**：`BPF_PROG_TYPE_EXT`（5.6）、`STRUCT_OPS`（5.6）、`LSM`（5.7）、
   `bpf_link` / `LINK_CREATE`（5.7）——A15/A16 的 libbpf/bpfloader 会用到。
4. **指令集与 verifier**：`BPF_JMP32`（5.1）、有界循环验证（5.3）、verifier 精度跟踪与状态裁剪
   （5.x 对 `verifier.c` 是大改，冲突最重的一块）、`BPF_PSEUDO_MAP_VALUE` 等。
5. **arch 侧**：`arch/arm64/net/bpf_jit_comp.c` 支持新指令（JMP32 等）与 `bpf_jit_binary_*` 新接口。
6. **顺带被带进来的非 BPF 部分**：参考分支的 diff 里能看到 RCU、timekeeping、cgroup v2、
   LSM/SafeSetID、`Documentation/*` 等——因为 5.10 的 BPF 代码依赖这些较新的内核基础设施。
   **这一条是最容易被低估的成本**：不是「只改 BPF 目录」，而是「把内核若干个核心子系统抬到 5.x 水位」。

---

## 4. 参考实现（可直接作为移植来源）

| 仓库 | 分支 | 机型 / 内核 | 用途 |
|---|---|---|---|
| `jsdizkcksv/android_kernel_aresin` | **A16** | 小米 POCO F3 GT / K40 GE（MTK 天玑 1200，**内核 4.14**） | **和我们最接近**：4.14 + A16 的完整树，`kernel/bpf/` 已含 `btf.c`、`local_storage.c`、`cpumap.c`、`disasm.c`、`offload.c` |
| `ApartTUSITU/kernel_xiaomi_sm8250_mod` | `backport-5.10-bpf` | 小米 sm8250（4.19） | 已量化：相对其 A15 分支 **+1444 提交**；另有 `backport-5.4-bpf` |
| `MTK6893/lineage_kernel_xiaomi_sdm845` | `lineage-23.0` | sdm845（4.9/4.19） | 4.9→5.10 的参考（帖子 25.9.14 更新） |
| `jsdizkcksv/android_kernel_xiaomi_sdm660` | `main` / `BACKPORT/erofs` | sdm660 | 4.4→5.10 的参考 |

**做法**：不是从零写，而是选一棵最接近的树（aresin，4.14+A16）做 **BPF 相关提交的筛选与 cherry-pick**，
逐条对照我们这棵树（mtk vs qcom 的 arch/JIT 差异、我们的 techpack 音频栈等）解决冲突。

---

## 5. 工作量与风险（诚实评估）

* **量级**：千级提交；`kernel/bpf` 从 16 个文件扩到 5.x 规模（20+），`verifier.c` 几乎重写。
* **风险**：BPF verifier 是安全敏感区，合错会导致内核不稳定/开机循环；每轮验证要刷机 8~10 分钟
  （本机刷 boot 已很熟练，回滚镜像齐全）。
* **分阶段建议**：
  * **P1（低风险，1~2 天）**：先合「被 bpfloader 硬校验」的最小集（BTF + `BTF_LOAD` + `bpf_link` +
    `JMP32` + `ringbuf`），编一版内核看 A15 的 bpf 程序能否被接受；预期仍会因 verifier 差异失败，
    但能拿到真实的失败点（`dmesg` 里的 verifier 报错），为 P2 定范围。
  * **P2（大头）**：按 aresin 树把 verifier / 其余 map / prog 类型补齐（这就是那 1444 提交的主体）。
  * **P3**：A16 特有（BTF 强依赖、ebpf 模块要求）+ 边界情况。
* **验证手段**：`logcat | grep -i bpfloader`、`ls -l /sys/fs/bpf`、`dmesg | grep -i bpf`、
  `getprop ro.kernel.version`；设备上没有 `bpftool`，需要的话我可以静态编一个塞进 ramdisk。

---

## 6. 非 BPF 门槛（必须先确认，否则 BPF 白做）

1. **Vendor API level / VNDK**：本机 vendor 是 Android 11。A15/A16 GSI 对 vendor API level 有要求，
   且 VNDK 版本要对得上；对不上会卡在 `linker`/HAL 加载。
2. **HAL 兼容**：相机（含升降前摄服务）、音频（techpack + awinic）、传感器等 OEM HAL 都是 A11 时代的，
   GSI 只能用 `android.hardware.*@2.x` 这一代的接口；哪几个能跑要实测。
3. **分区布局**：本机 `super` 里有 system/product/vendor 等逻辑分区，GSI 刷 system 分区即可，
   不动 vendor；刷前建议先 `fastboot fetch` 回读校验（我们踩过「刷完卡第一屏、只能按键进 fastboot 恢复」的坑，
   见 `vendor-mod-attempt.md`）。

---

## 7. 建议的下一步（可执行）

1. **先做 A13/A14 GSI 试刷**（只动 system 分区，风险低、可快速回滚），验证「非 BPF 门槛」；
   这一步完全不需要改内核，能立刻给出「这台机器到底能不能跑新版 Android」的答案。
2. 同时我把 `aresin` 树 **BPF 相关提交清单**导出（按 `kernel/bpf`、`include/linux/bpf*`、
   `include/uapi/linux/bpf.h`、`net/core/filter.c`、`arch/arm64/net/bpf_jit_comp.c` 分文件统计），
   逐条标注「可直接 cherry-pick / 需手工改 / 与我们无关」，把「1444 提交」变成可执行的移植计划。
3. 拿到 1、2 的结果再决定要不要开工 P1/P2。

---

## 附：怎么自己精确拿到「GSI 的 BPF 程序需要哪些特性」

GSI 里 `com.android.tethering` / `system/bpf` 的预编译 `*.o` 就在 APEX 内：
`/apex/com.android.tethering/etc/bpf/*.o`、`/system/etc/bpf/*.o`。把它们拉出来，
用 `llvm-objdump -h` 看 section（`cgroup_skb/ingress`、`sched_cls/...` 等），
再看 `maps` section 里的 `BPF_MAP_TYPE_*` 与重定位到 `bpf_*` 的 helper 列表，
就能得到**精确**的需求清单（比读源码更可靠）。需要的话我写个脚本一键出表。
