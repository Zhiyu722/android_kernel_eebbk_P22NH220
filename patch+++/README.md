# patch+++ —— EEBBK S6 (P20H130 / sm6150) 内核修复全集

本文件夹是本项目**全部补丁**的合并整理，涵盖声音、后摄、触摸、霍尔、升降前摄、
构建与启动的每一处改动。基于厂商源码导入提交 `525066d92` 之上的完整提交序列生成，
编号连续、无遗漏。

## 应用方式

```bash
git checkout 525066d92            # 或在厂商源码树上
git am /path/to/patch+++/*.patch  # 按编号顺序应用
```

也可以只看某个子系统，例如只应用升降相关：`0033`、`0034`、`0031`、`0032`、`0039`。

## 补丁清单

### 启动 / 构建 / 内核框架
| # | 补丁 | 说明 |
|---|---|---|
| 0001 | arm64: kernel: Keep .bss.rtic inside the image | `.bss.rtic`（含 `selinux_state`）落在 `_end` 之后导致启动死机，移入 `BSS_SECTION` |
| 0002 | module: Accept vendor DLKM signature and symbol CRC mismatches | 厂商 DLKM 的 vermagic/CRC 与自编译内核不一致，放宽校验 |
| 0009 | kbuild: Track an empty .scmversion | 保持版本串 `4.14.190-perf` 不变，避免模块版本失配 |
| 0012 | arm64: configs: Disable the vendor debug panic-on-timeout switches | 关掉厂商的 panic-on-timeout 调试开关 |
| 0025 | misc: Add bring-up helpers behind CONFIG_BBK_DEBUG_BRINGUP | 调试专用：`/proc/eebbk_kmsg` + 宽松 SELinux，正式镜像不编入 |
| 0036 | misc: bbk_debug: Make the log node filterable and add an elevator pin node | 日志可按关键字过滤，`/proc/eebbk_pins` 报告升降引脚电平与时钟频率 |
| 0046→0036 同上 | | |

### 声音（TECHPACK + 功放）
| # | 补丁 | 说明 |
|---|---|---|
| 0003 | techpack: Build the audio stack and the ADSP loader into the kernel | 不编 techpack 就没有 `adsp-loader`，ADSP 不启动、无声卡、卡开机动画 |
| 0004 | ASoC: sm6150: Use the AW882xx speaker codec instead of TFA98xx | 硬编码的 `tfa98xx` 与板上 AW882xx 不符，导致 DAI 未注册、`-EPROBE_DEFER` |

### 相机（后摄修复 + 前摄枚举 + BBK 节点）
| # | 补丁 | 说明 |
|---|---|---|
| 0029 | media: cam_eeprom: Read the memory map the way the factory device tree names it | 兼容 `qcom,` 前缀与裸属性名 |
| 0030 | media: cam_sensor: Accept a one byte sensor id | 前摄 ov16a10 的 id 读取只匹配首字节，否则 `chip id 5616 does not match 56` |
| 0037 | media: cam_eeprom: Read only as many memory map values as the tree provides | 设备树给 6 个值而驱动要 8 个 → `-22`，内存图被拆掉、前摄不枚举 |
| 0005/0006/0008/0013/0015/0018/0019/0021/0024/0026/0038 | docs: … | 变更说明、逆向报告与补丁集文档 |

### 触摸
| # | 补丁 | 说明 |
|---|---|---|
| 0007 | input: touchscreen: focaltech: Register the MSM DRM notifier | FB 与 DRM 同时编入时 FTS 走了 FB 分支，屏幕通知永不触发（**尚未在真机验证**） |

### 霍尔传感器与升降前摄
| # | 补丁 | 说明 |
|---|---|---|
| 0010 | input: misc: Add the iSentek IST8801 hall switch driver | 设备树里有节点，但 2-0018/2-001b 无 ACK（板上未贴） |
| 0011 | arm64: configs: Enable the IST8801 hall switch | 与厂商配置对齐 |
| 0014 | input: misc: Add the Magnachip MXM1120 hall switch driver | 板上真实存在的霍尔（2-000c down / 2-000f up） |
| 0028 | input: misc: mxm1120: Accept the id this board actually reports | 早期误读 0x00 寄存器；已被 0035 取代 |
| 0035 | input: misc: mxm1120: Decode the sample and read the id the way the factory does | **关键**：芯片 ID 在寄存器 `0x09`（值 `0x9c`）；测量值高位取自 `0x10` 块第三字节，之前误取 `0x00` 导致读数恒为 256 |
| 0022 | input: hall: Add the BBK hall sensor framework | `/dev/bbk_hall_core` + 6 个 sysfs 节点 + 标定数据通路 |
| 0023 | misc: Accept the mhall calibration from the hall framework | 设备标定值 `all_time=2790` 由此传入驱动 |
| 0027 | input: hall: Make the bring-up build usable for diagnosis | 调试版放宽探测，便于定位 |
| 0016 | misc: Add the BBK elevator camera motor controller | `soc:bbk_vib_pwm` 升降电机驱动（15 个 sysfs 节点、按键注入） |
| 0017 | misc: Match the vendor elevator driver's timings, states and key events | 时序、状态机、按键与厂商一致 |
| 0020 | misc: Name the elevator driver like the vendor one | 模块名 `gpio_pwm` |
| 0031 | misc: gpio_pwm: Never sleep in the move timer callback | 定时器回调里 `msleep` 导致 `scheduling from the idle thread` + UFS 超时的整机冻结 |
| 0032 | misc: gpio_pwm: Select the pinmux state around every move | `pinctrl_select_state` 会替换状态，移动前必须重新选 `active` 才有时钟输出 |
| **0033** | **clk: qcom: gcc-sdmmagpie: Restore the low frequency GP clock entries** | **升降不工作的根因**，见下节 |
| 0034 | misc: gpio_pwm: Program the chopper rate on the parent RCG and balance the clock | 频率必须设在父 RCG 上；同时修掉 `clk_disable` 计数不平衡的 WARNING |
| 0039 | misc: gpio_pwm: Drop two declarations left unused by the clock change | 编译告警清理 |

## 根因：为什么原厂固件的前摄升降也不工作

本机的时钟控制器是 `compatible = "qcom,gcc-sdmmagpie"`，升降电机的斩波时钟来自
`<&gcc GCC_GP2_CLK>`（`gcc_gp2_clk`，其父是 `gcc_gp2_clk_src` 这个 RCG）。

厂商驱动（以及本项目的忠实复刻）调用 `clk_set_rate(branch, 32000)`，但**分频器在父 RCG 上**，
而源码树里的 GP 频率表只有 `19.2M / 25M / 50M / 100M / 200M` —— 请求 32 kHz 无处落地。
实测确认：**引脚一直输出 19.2 MHz**，电机驱动芯片无法在这个频率下开关，于是只有轻微声音、
没有扭矩，机构纹丝不动。

从原厂 vmlinux 中还原出的真实频率表（同一 RCG 在二进制里有三份副本，本机用的是 sdmmagpie 那份）
包含低频档位，全部由 `bi_tcxo` 经半整数分频 `h` 与 mnd 比例 `m/n` 得到，
即 `clk_rcg2_calc_rate() = (父频 / h) * m / n`：

| 频率 | h | m | n | 验算 |
|---|---|---|---|---|
| 19200 | 16 | 4 | 250 | 19200000/16*4/250 = 19200 |
| **32000** | **16** | **2** | **75** | **19200000/16*2/75 = 32000** |
| 41600 | 15 | 8 | 246 | 19200000/15*8/246 = 41626 |

这三个数字正是厂商驱动里的 `32000`（普通移动）、`19200`（远距离移动第一段）、
`41600`（第二段）—— 补丁 0033 把这张表按原厂二进制逐条还原。

**设备验证**：`gcc_gp2_clk_src -> 32000 Hz`，前摄摄像头**能正常升起、无异响、无卡住** ✓

## 设备验证状态

已经在真机（adb 序列号 7013T3603C41X）确认：

- 声音：声卡 `card0` 及全部 `pcmC0D*` 节点存在，功放 `2-0034 → aw882xx_smartpa` ✓
- 后摄：正常工作；`/proc/driver/BackCamera_info` 输出 `Q Tech (2742EJ36Q0F002DT) s5k3l6` ✓
- 前摄：`Number of camera devices: 2`，`/proc/driver/FrontCamera_info` 输出 `TSP ov16a10` ✓
- 升降：32 kHz 斩波正确、引脚电平正确、pinctrl 状态正确、前摄**能正常升起** ✓
- 触摸：驱动加载 `1-0038 → fts_ts` ✓（行为修复尚未实测）
- 稳定性：连续运行 >5 分钟无重启（此前约 4 分钟必重启，元凶是厂商 `com.eebbk.stresstest`，
  已用 `pm disable-user` 禁用）✓

尚未验证 / 未解决：

- 触摸的 DRM 通知修复未在真机确认
- 霍尔传感器**不产生测量值**：`0x10` 数据块恒为 0，`bbk_hall_data` 上报 `-2000`（芯片能应答
  ID 但未进入转换）。升降的开关环移动不依赖霍尔，故不影响前摄使用
- WiFi 打不开（`Failed to load WiFi driver` / `Wifi HAL start failed`）

