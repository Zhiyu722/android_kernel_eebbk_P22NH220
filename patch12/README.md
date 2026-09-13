# patch12 —— EEBBK S6 (P20H130) 霍尔传感器 + 升降摄像头 + 霍尔框架 全部补丁

本文件夹是**霍尔子系统与升降摄像头的全部改动**，按可单独应用的顺序排列。
共 **10 个补丁：7 个代码补丁 + 3 个文档补丁（逆向报告）**。

上游仓库：https://github.com/Zhiyu722/android_kernel_eebbk_sm6150
本序列对应的 master 提交：`63c3789f1`
（相机/声音/触摸的补丁在 `s6patch相机/`、`s6patch声音/`、`s6patch触摸/`，与本序列不冲突）

---

## 一、补丁清单

| 编号 | 文件 | 对应提交 | 内容 |
|---|---|---|---|
| 0001 | `0001-input-misc-Add-the-iSentek-IST8801-hall-switch-dri.patch` | `4133ef332` | **IST8801 驱动**：`drivers/input/misc/ist8801.c` + Kconfig + Makefile |
| 0002 | `0002-input-misc-Add-the-Magnachip-MXM1120-hall-switch-dri.patch` | `d29eb7b37` | **MXM1120 驱动**：`mxm1120.c` + Kconfig + Makefile |
| 0003 | `0003-misc-Add-the-BBK-elevator-camera-motor-controller.patch` | `4a463d27f` | **升降电机驱动初版**：`drivers/misc/bbk_vib_pwm.c` + Kconfig + Makefile |
| 0004 | `0004-misc-Match-the-vendor-elevator-driver-s-timings-stat.patch` | `861f832a9` | **升降电机修正**：行程时间表、状态 6/7、`enable` 语义、`abort_notify` 字符串协议、`h110-vib-input` 键注入、模块参数 |
| 0005 | `0005-misc-Name-the-elevator-driver-like-the-vendor-one.patch` | `f795c0fcc` | **改名对齐**：`bbk_vib_pwm.c` → `gpio_pwm.c`（模块参数路径 `/sys/module/gpio_pwm/parameters/`）、属性 `vib_pwm_frequency` → **`vib_pwm_freq`** |
| 0006 | `0006-input-hall-Add-the-BBK-hall-sensor-framework.patch` | `3c08d362e` | **霍尔框架 `bbk_hall_core`**：`drivers/input/hall/{Kconfig,Makefile,bbk_hall_core.c}` + `drivers/input/{Kconfig,Makefile}` 接线 + 两个传感器驱动接入框架 |
| 0007 | `0007-misc-Accept-the-mhall-calibration-from-the-hall-fram.patch` | `63c3789f1` | **校准交接**：电机驱动实现 `init_hall_data_fake()`，把 48 B `cali_mhall_final` 灌进模块参数 |
| 0008 | `0008-docs-Add-the-hall-sensor-reverse-engineering-notes.patch` | `61a6c3815` | 逆向笔记（4 个驱动为何在源码里完全没有、恢复方法、IST8801 寄存器映射） |
| 0009 | `0009-docs-Record-the-MXM1120-protocol-and-the-elevator-ha.patch` | `3b5cc24fe` | MXM1120 协议/解码 + 升降硬件（GPIO、GP2 时钟、pinctrl） |
| 0010 | `0010-docs-Add-the-full-vib_pwm-and-bbk_hall_core-reverse-.patch` | `3f35bcd90` | **两份逐指令级逆向报告**（`vib_pwm-逆向报告.md` 1036 行、`bbk_hall_core-逆向报告.md` 406 行） |

> **没有配置文件补丁**，这是有意的：工厂 config
> （`arch/arm64/configs/h130_factory.config`）本身就已经带着
> `CONFIG_INPUT_HALL=y`、`CONFIG_VIB_PWM=y`、`CONFIG_INPUT_MXM1120_UP=y`、
> `CONFIG_INPUT_MXM1120_DOWN=y`、`CONFIG_INPUT_IST8801=y`。
> 本序列新增的只是这些符号的 **Kconfig 定义**，定义一到位（0006 补丁）这些值就会被
> `olddefconfig` 认下来 —— 实测应用后 `CONFIG_INPUT_HALL=y` 生效。

---

## 二、应用方法

基础树要求：已应用 vendor 树导入提交（`525066d92`，即本仓库的第一个提交）。
本序列**不包含**那个巨大的导入补丁，它假定你已经有了这棵树。

```bash
# 方法一：保留提交信息（推荐）
git am --keep-cr /path/to/patch12/00*.patch

# 方法二：只应用改动、不建提交
for p in /path/to/patch12/00*.patch; do git apply "$p"; done
```

实测（在基于 `525066d92` 的干净工作树里逐条 `git apply --check`）：
**10 个补丁全部 APPLIES，0 失败**。

应用后新增/修改：

```
新增  drivers/input/misc/ist8801.c
新增  drivers/input/misc/mxm1120.c
新增  drivers/input/hall/{Kconfig,Makefile,bbk_hall_core.c}
新增  drivers/misc/gpio_pwm.c
修改  drivers/input/Kconfig / Makefile        （接入 hall/ 子目录）
修改  drivers/input/misc/Kconfig / Makefile   （INPUT_IST8801、INPUT_MXM1120…）
修改  drivers/misc/Kconfig / Makefile         （VIB_PWM）
新增  s6patch霍尔/                            （逆向笔记与报告）
```

---

## 三、Kconfig 接线的关键点

### MXM1120：隐藏符号 + select

工厂 config 里 MXM1120 是**三个板级符号**，所以用一个隐藏符号加 `select`：

```kconfig
config INPUT_MXM1120          # 隐藏；真正编译 mxm1120.o 的是它
	bool
	depends on I2C
config INPUT_MXM1120_UP       # 工厂 config 里的三个可见符号
	bool "Magnachip MXM1120 up hall switch"
	select INPUT_MXM1120
config INPUT_MXM1120_DOWN     # 同理
config INPUT_MXM1120_MIDDLE   # 同理（工厂是 not set）
```

传感器位置由 **DT compatible**（`magnachip,mxm1120,up` / `,down`）决定，
所以同时打开多个也不会重复编译对象。

### 霍尔框架：`CONFIG_INPUT_HALL`

```kconfig
config INPUT_HALL
	tristate "BBK hall sensor framework"
	depends on INPUT
```

可复现性实测：把 `h130_factory.config` 当 `.config` 再跑 `olddefconfig` →

```
CONFIG_INPUT_HALL=y
CONFIG_VIB_PWM=y
CONFIG_INPUT_MXM1120=y   CONFIG_INPUT_MXM1120_UP=y   CONFIG_INPUT_MXM1120_DOWN=y
CONFIG_INPUT_IST8801=y
```

---

## 四、硬件事实速查（逐条从原厂 ELF / DT 还原）

### 霍尔传感器（i2c）

| 器件 | i2c | DT compatible | 注册到框架的名字 | input 设备 |
|---|---|---|---|---|
| MXM1120 (up) | 0x0f | `magnachip,mxm1120,up` | `up-mxm1120`（框架 up 槽） | `m1120_up` |
| MXM1120 (down) | 0x0c | `magnachip,mxm1120,down` | `down-mxm1120`（框架 down 槽） | `m1120_down` |
| IST8801 | 0x18 | `isentek,ist8801-0` | `up-ist8801`（旧 `dhall_*` 路径） | — |
| IST8801 | 0x1b | `isentek,ist8801-2` | `down-ist8801`（同上） | — |

- MXM1120：ID 寄存器 `0x00` 期望 **0x9c**；`0x07=0x01` 起手；`0x08` 工作模式（`0x40` 测量）；
  `0x10` 读 3 字节；10bit 解码 `buf[1] | ((reg00>>6)<<8)` 按 bit9 符号扩展。
- IST8801：`0x01` 控制、`0x07=0x01`、`0x08` 模式（`0x00`/`0x40`/`0x80`）、`0x09` DID、
  `0x10` 五字节数据块、`0x20`、`0x40`/`0x54` 状态。
- 框架按名字前 2/4 字节判定 `"up"` / `"down"`，**先注册的一对生效**，之后忽略。

### 升降电机（DT `soc:bbk_vib_pwm`，compatible `bbk,vib_pwm_control`）

| 资源 | 引脚/时钟 | 驱动/空闲 |
|---|---|---|
| `boost-gpio` | GPIO24 | 驱动 1 / 空闲 0 |
| `enable-gpio` | GPIO23 | **低有效**：驱动 0 / 停止 1 |
| `sleep-gpio` | GPIO29 | 驱动 1 / 空闲 0 |
| `dir-gpio` | GPIO26 | **0 = 上行、1 = 下行** |
| `id-gpio` | GPIO25 | 输入（`vib_pwm_idconfig` 上拉，读机型） |
| `clocks` | `<&gcc 36>` = `GCC_GP2_CLK`（`gp2_clk`） | **不是 PWM**：`vib_pwm_active` 把 GPIO21 复用成 `gcc_gp2`，`clk_set_rate` 定斩波频率 |

一次动作：`clk_set_rate(32000) → hall_core_enable(0) → clk_prepare → dir → boost=1 →
msleep(3) → enable=0 → sleep=1 → msleep(3) → clk_enable → hrtimer_start(REL|PINNED) →
hall_core_enable(1)`；停止：`boost=0 → msleep(5) → enable=1 → sleep=0`（不动 dir）+
`clk_disable`/`clk_unprepare`。

行程时间：`all_time`（`mhall_control7`，默认 **2839**）为满行程；69.6% 位 =
`all_time*696/1000`；主驱动段乘 **6/10**（19200 标称 → 32000 实际）；
`time>65536` 时先 50 ms 预驱动段，再 41600 Hz 跑 `(time-50)*6/13`。

---

## 五、必须对齐的用户态接口

### 升降电机 15 个 sysfs（`/sys/devices/platform/soc/soc:bbk_vib_pwm/`）

```
vib_pwm_id (0444)  vib_pwm_freq  vib_pwm_count  vib_pwm_enable  vib_pwm_dir
vib_pwm_time  vib_pwm_camera_state  vib_pwm_state_init  vib_pwm_abort_notify
vib_pwm_holder_mode  vib_pwm_elevator_mode  vib_pwm_elevator_row_shift (只读)
vib_pwm_cali  vib_pwm_up_down_count  vib_pwm_clear_cali_data
```

- `vib_pwm_camera_state`：**0 = 收回、1 = 升起（69.6% 位）、2 = 升起并偏转（满行程位）**；
  另 `4`=上行中、`5`=下行中（忙态）、`6`=防夹异常、`7`=holder 保持位。
- `vib_pwm_enable` 写 **1 = 上行、2 = 下行**，其它值只刹车。
- `vib_pwm_time` 写 **1300** = `all_time + 10`；`vib_pwm_dir` 只看首字符是否 `'1'`。
- `vib_pwm_abort_notify` 是**字符串关键字协议**：`"0x27c"/"636"`、`"0x27d"/"637"`、
  `"0x27f"/"639"`、`"0x280"/"640"`、`"0x282"/"642"`、`"0x283"/"643"`、`"0x284"/"644"`、
  `"666"`、`"888"`、`"stream on"`、`"stream off"`、`"username:"`、`"com.eebbk.askhomework"`。

### 霍尔框架（`/dev/bbk_hall_core` + `/sys/devices/platform/bbk_hall_core/`）

| 接口 | 语义 |
|---|---|
| ioctl `0x40046000` SET_CALI | 56 B blob → 落盘 `cali_hall` → `cali_valid=1` → `set_vib_all_time(+0x34)` |
| ioctl `0x40046001` TRANS_CALI | 56 B blob，不落盘；并读回 `up_down_count`（`"%u-%u"`） |
| ioctl `0x40046002` SET_MHALL_CALI | 48 B blob → 落盘 `cali_mhall_final` → `init_hall_data_fake()` → `mhall_cali_valid=1` |
| ioctl `0x40046003` SET_MHALL_CALI_DAEMON | 48 B blob，不落盘 |
| 越界命令 / 拷贝失败 | `-ENOTTY` / `-EFAULT`；文件打开或写失败 `-1` |
| `bbk_hall_delay` (0644) | 轮询周期 ms，下限 20；默认 50 |
| `bbk_hall_enable` (0644) | show 使能位；store 只接受 0/1 |
| `bbk_hall_data` (0444) | `"up:%d down:%d\n"`，各重试 10 次、间隔 2 ms |
| `bbk_hall_vendor` (0444) | `"up:%s down:%s\n"` 已注册的传感器名 |
| `bbk_hall_cali_time` (0644) | 内部单位 = 0.6 × 用户单位；写入需 `cali_valid` |
| `bbk_mhall_version` (0444) | `"version:%d\n"` = mhall blob 的 valid 标志 |

### input 设备

`h110-vib-input`（`h110-vib/input0`，bustype 0x19，键 **635–646**）、
`m1120_up`、`m1120_down`。

### 模块参数

```
gpio_pwm.mhall_control_up/_down/_2/_3/_4/_5/_6/_7
bbk_hall_core.mhall_press        (默认 8)
```

---

## 六、编译与打包

```
make O=out_native ARCH=arm64 CC=/usr/bin/clang-11 LD=ld.lld TECHPACK=y DTC=dtc Image.gz
```

配置：把 `arch/arm64/configs/h130_factory.config` 当 `.config`，再 `olddefconfig`。
打包必须用**原厂 ramdisk + 原厂 dtb/dtbo**（BBK 的霍尔/升降节点只在原厂 dtbo 里）。

---

## 七、还差什么（本序列**不含**，务必知悉）

1. ~~`bbk_hall_core` 框架~~ —— **本序列 0006 已补上**（misc + 4 个 ioctl + 标定文件 +
   6 个 sysfs + 队列/轮询 + 注册协议）。
2. ~~传感器接入框架~~ —— **本序列 0006 已补上**（MXM1120 走
   `bbk_hall_core_register_device()` 占 up/down 槽；IST8801 走原厂的 `dhall_register_hall()`）。
3. **升降的位置闭环仍未做**：`gpio_pwm.c` 目前是**时间开环**（按 `all_time` 计时到位，
   留了早停钩子），缺原厂的 `vib_pwm_state_move_sate()`、`computer_distance()`（0/3828/7656/
   11101/15950 五锚点插值）、`is_top_or_bottom()`、retry 循环与防夹逻辑。
4. **标定数据**：`/mnt/vendor/persist/sensors/cali_hall`(56 B)、`cali_mhall_final`(48 B)、
   `up_down_count` 需用户态 daemon 通过 ioctl 0/2 写入；框架只有在 `cali_valid == 1` 时才
   开始轮询并按压判定。**位置闭环依赖它**。
5. **真机验证未做**：全部为编译级验证（10 个补丁干净应用、镜像字符串与导出符号齐全）。
   行程时间（`all_time=2839` 那套）必须实机微调。

---

## 八、参考文档

- 0008/0009/0010 三个文档补丁会落地 `s6patch霍尔/README.md`、
  `vib_pwm-逆向报告.md`、`bbk_hall_core-逆向报告.md`
- 相机/声音/触摸见 `s6patch相机/`、`s6patch声音/`、`s6patch触摸/`
- 总览见仓库根目录 `EEBBK_S6_changes.md`、`EEBBK_S6_progress.md`
