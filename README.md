1. **「用久了所有声音全哑」**：根因已复现（`EEBBK_S6_changes.md` 第十三节）——
   HAL 的扬声器保护回采流在 ASM Loopback FE 上没有后端 DAI，必然失败 →
   `iv_feedback_count` 泄漏 → 扬声器路由卡死，**重启恢复**。
   闭源 HAL 里的计数改不了，可行修法：把 `/vendor/build.prop` 的
   `vendor.audio.feature.spkr_prot.enable` 改成 `false`（用 KSU 模块 bind-mount 覆盖最稳，未做）。
2. **Android 15/16 GSI**：AOSP 已强制内核 ≥ 5.4（`NetBpfLoad: enforce kernel 5.4`），
   本树只有 4.14 时代的 BPF（无 BTF/ringbuf/bpf_link/JMP32/新 verifier），
   移植量参考同类机型 **约 1444 个提交**，详见 `docs/bpf-gsi-feasibility.md`。
3. **/vendor 瘦身**：镜像本身是对的（逐文件比对只差 26 个 APK + build.prop 一行），
   但刷入卡第一屏（verity 未同步 / 写入被中断），已回滚，`docs/vendor-mod-attempt.md`。
4. 厂家下降闭环重试（`add_time`）未实现，下降贴合靠 `cali_time=3630` 标定。
