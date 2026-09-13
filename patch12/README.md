# patch12 —— EEBBK S6 (P20H130) 霍尔传感器 + 升降摄像头 全部补丁

本文件夹是**霍尔子系统与升降摄像头（升降前摄电机）的全部改动**，按可单独应用的顺序排列。
共 8 个补丁：5 个代码补丁 + 3 个文档补丁（逆向报告）。

上游仓库：https://github.com/Zhiyu722/android_kernel_eebbk_sm6150
本序列对应的 master 提交：`f795c0fcc`
（与相机/声音/触摸相关的补丁在 `s6patch相机/`、`s6patch声音/`、`s6patch触摸/`，
与本序列互不冲突）

---

## 一、补丁清单

| 编号 | 文件 | 对应提交 | 内容 |
|---|---|---|---|
| 0001 | `0001-input-misc-Add-the-iSentek-IST8801-hall-switch-dri.patch` | `4133ef332` | **IST8801 驱动**：新文件 `drivers/input/misc/ist8801.c` + Kconfig + Makefile |
| 0002 | `0002-input-misc-Add-the-Magnachip-MXM1120-hall-switch-dri.patch` | `d29eb7b37` | **MXM1120 驱动**：新文件 `drivers/input/misc/mxm1120.c` + Kconfig + Makefile |
| 0003 | `0003-misc-Add-the-BBK-elevator-camera-motor-controller.patch` | `4a463d27f` | **升降电机驱动初版**：新文件 `drivers/misc/bbk_vib_pwm.c` + Kconfig + Makefile |
| 0004 | `0004-misc-Match-the-vendor-elevator-driver-s-timings-stat.patch` | `861f832a9` | 按深挖结果**修正升降电机**：行程时间表、状态 6/7、`enable` 语义、`abort_notify` 字符串协议、`h110-vib-input` 键注入、模块参数 |
| 0005 | `0005-misc-Name-the-elevator-driver-like-the-vendor-one.patch` | `f795c0fcc` | **改名对齐**：`bbk_vib_pwm.c` → `gpio_pwm.c`（决定模块参数路径 `/sys/module/gpio_pwm/parameters/`）、属性 `vib_pwm_frequency` → **`vib_pwm_freq`** |
| 0006 | `0006-docs-Add-the-hall-sensor-reverse-engineering-notes.patch` | `61a6c3815` | 逆向笔记：为什么这 4 个驱动在源码里完全没有、恢复方法、IST8801 寄存器映射 |
| 0007 | `0007-docs-Record-the-MXM1120-protocol-and-the-elevator-ha.patch` | `3b5cc24fe` | MXM1120 协议与解码 + 升降电机硬件（5 个 GPIO、GP2 时钟、pinctrl）记录 |
| 0008 | `0008-docs-Add-the-full-vib_pwm-and-bbk_hall_core-reverse-.patch` | `3f35bcd90` | **两份逐指令级逆向报告**（`vib_pwm-逆向报告.md` 1036 行、`bbk_hall_core-逆向报告.md` 406 行） |

> **没有配置文件补丁**，这是有意的：工厂 config
> （`arch/arm64/configs/h130_factory.config`）本身就已经带着
> `CONFIG_INPUT_HALL=y`、`CONFIG_VIB_PWM=y`、`CONFIG_INPUT_MXM1120_UP=y`、
> `CONFIG_INPUT_MXM1120_DOWN=y`、`CONFIG_INPUT_IST8801=y`。
> 之前有一条"打开 IST8801"的补丁是多余的（应用后反而多出一行重复配置），
> 已从本序列中移除。

---

## 二、应用方法

基础树要求：已应用 vendor 树导入提交（`525066d92`，即本仓库的第一个提交）。
本序列**不包含**那个巨大的导入补丁，它假定你已经有了这棵树。

```bash
# 方法一：保留提交信息（推荐）
git am --keep-cr /path/to/patch12/000*.patch

# 方法二：只应用改动、不建提交
for p in /path/to/patch12/000*.patch; do git apply "$p"; done
```

实测（在本仓库上，基于 `525066d92` 的干净工作树逐条 `git apply --check`）：
**8 个补丁全部 APPLIES，0 失败**。

应用后新增/修改：

```
新增  drivers/input/misc/ist8801.c
新增  drivers/input/misc/mxm1120.c
新增  drivers/misc/gpio_pwm.c
修改  drivers/input/misc/Kconfig      （+ INPUT_IST8801、INPUT_MXM1120 及三个板级符号）
修改  drivers/input/misc/Makefile     （+ ist8801.o、mxm1120.o）
修改  drivers/misc/Kconfig            （+ VIB_PWM）
修改  drivers/misc/Makefile           （+ gpio_pwm.o）
新增  s6patch霍尔/                     （逆向笔记与报告）
```

---

## 三、Kconfig 接线的关键点（MXM1120）

工厂 config 里 MXM1120 是**三个板级符号**，所以本序列用一个隐藏符号 + `select`：

```kconfig
config INPUT_MXM1120          # 隐藏，真正编译 gpio_pwm.o 的那个
	bool
	depends on I2C

config INPUT_MXM1120_UP       # 工厂 config 里的三个可见符号
	bool "Magnachip MXM1120 up hall switch"
	depends on I2C
	select INPUT_MXM1120
config INPUT_MXM1120_DOWN     # 同理
config INPUT_MXM1120_MIDDLE   # 同理（工厂是 not set）
```

好处：工厂 config 一行都不用改，三个符号都能被识别；传感器位置由 **DT compatible**
（`magnachip,mxm1120,up` / `,down`）决定，所以同时打开多个也不会重复编译对象。

可复现性实测：把 `h130_factory.config` 直接当 `.config` 再跑 `olddefconfig` →

```
CONFIG_INPUT_MXM1120=y
CONFIG_INPUT_MXM1120_UP=y
CONFIG_INPUT_MXM1120_DOWN=y
# CONFIG_INPUT_MXM1120_MIDDLE is not set
CONFIG_INPUT_IST8801=y
CONFIG_VIB_PWM=y
```

`CONFIG_INPUT_HALL` 目前会被 `olddefconfig` 丢弃 —— 因为对应的框架驱动
（`bbk_hall_core`）还没写，Kconfig 里没有这个符号。见第七节。

---

## 四、硬件事实速查（都是从原厂 ELF/DT 逐条还原的）

### 霍尔传感器（i2c）

| 器件 | i2c 地址 | DT compatible | 驱动注册的 input 设备 |
|---|---|---|---|
| IST8801 | 0x18、0x1b | `isentek,ist8801-0` / `-2` | 无 input，走 sysfs/文本上报 |
| MXM1120 (down) | 0x0c | `magnachip,mxm1120,down` | `m1120_down`（`EV_ABS/ABS_X` ±32767，bustype 0x18） |
| MXM1120 (up) | 0x0f | `magnachip,mxm1120,up` | `m1120_up` |

- MXM1120：ID 寄存器 `0x00` 期望 **0x9c**；`0x07=0x01` 起手；`0x08` 工作模式（`0x40` 测量）；
  `0x10` 读 **3 字节**（`[0]` 状态 bit0=DRDY、`[1]` 低位、`[2]` 高位）；
  解码 10bit = `buf[1] | ((reg00>>6)<<8)` 按 bit9 符号扩展，8bit = `buf[2]&0x7f` 按 bit7 扩展。
  DT 属性：`magnachip,init-interval`（0 视为 1，1 单位 = 原厂 20 ms 工作队列延迟）、
  `magnachip,use-interrupt`、`magnachip,gpio-int`、`magnachip,use-hrtimer`。
- IST8801：`0x01` 控制（复位/检测使能）、`0x07=0x01`、`0x08` 模式（`0x00` 掉电 / `0x40` 测量 /
  `0x80` 触发一次）、`0x09` DID、`0x10` 读 5 字节数据块、`0x20`、`0x40`/`0x54` 状态。

### 升降电机（DT `soc:bbk_vib_pwm`，compatible `bbk,vib_pwm_control`）

| 资源 | 引脚/时钟 | 驱动/空闲电平 |
|---|---|---|
| `boost-gpio` | GPIO24 | 驱动 1 / 空闲 0 |
| `enable-gpio` | GPIO23 | **低有效**：驱动 0 / 停止 1 |
| `sleep-gpio` | GPIO29 | 驱动 1 / 空闲 0 |
| `dir-gpio` | GPIO26 | **0 = 上行、1 = 下行** |
| `id-gpio` | GPIO25 | 输入（`vib_pwm_idconfig` pinctrl 上拉，读机型） |
| `clocks` | `<&gcc 36>` = `GCC_GP2_CLK`，名为 `gp2_clk` | **不是 PWM**：`vib_pwm_active` 把 GPIO21 复用成 `gcc_gp2` 输出，`clk_set_rate` 决定斩波频率 |

一次动作的时序（照抄原厂）：

```
clk_set_rate(gp2_clk, freq)      # 普通动作固定 32000 Hz
bbk_hall_core_enable(0)
clk_prepare(gp2_clk)
dir = 0(上行)/1(下行) → boost=1 → msleep(3) → enable=0 → sleep=1 → msleep(3)
clk_enable(gp2_clk)
hrtimer_start(&timer, move_time, HRTIMER_MODE_REL_PINNED)
bbk_hall_core_enable(1)
停止：boost=0 → msleep(5) → enable=1 → sleep=0（不动 dir），再 clk_disable/unprepare
```

行程时间：`all_time`（模块参数 `mhall_control7`，默认 **2839**）为满行程；
69.6% 位 = `all_time*696/1000`；主驱动段统一乘 **6/10**（19200 标称 → 32000 实际）；
`time > 65536` 时先 50 ms 预驱动段，再 41600 Hz 跑 `(time-50)*6/13`。

---

## 五、必须对齐的用户态接口

### `vib_pwm` 的 15 个 sysfs 属性（`/sys/devices/platform/soc/soc:bbk_vib_pwm/`）

```
vib_pwm_id (0444)  vib_pwm_freq  vib_pwm_count  vib_pwm_enable  vib_pwm_dir
vib_pwm_time  vib_pwm_camera_state  vib_pwm_state_init  vib_pwm_abort_notify
vib_pwm_holder_mode  vib_pwm_elevator_mode  vib_pwm_elevator_row_shift (只读)
vib_pwm_cali  vib_pwm_up_down_count  vib_pwm_clear_cali_data
```

- 写 `vib_pwm_camera_state`：**0 = 收回、1 = 升起（69.6% 位）、2 = 升起并偏转（满行程位）**，
  另有 `4`=上行中、`5`=下行中（忙态）、`6`=防夹异常、`7`=holder 保持位。
- `vib_pwm_enable` 写 **1 = 上行、2 = 下行**，其它值只刹车。
- `vib_pwm_time` 写 **1300** 是特例 `=` `all_time + 10`。
- `vib_pwm_dir` 只看首字符是不是 `'1'`。
- `vib_pwm_abort_notify` 是**字符串关键字协议**：`"0x27c"/"636"`、`"0x27d"/"637"`、
  `"0x27f"/"639"`、`"0x280"/"640"`、`"0x282"/"642"`、`"0x283"/"643"`、`"0x284"/"644"`、
  `"666"`、`"888"`、`"stream on"`、`"stream off"`、`"username:"`、`"com.eebbk.askhomework"`。

### input 设备

- 电机驱动注册 **`h110-vib-input`**（`h110-vib/input0`，bustype 0x19），
  注入键 **635–646**（每键"按下+SYN、抬起+SYN"两帧）。Android 侧靠它判断升降状态。
- 霍尔：`m1120_up` / `m1120_down`。

### 模块参数（原厂在 `/sys/module/gpio_pwm/parameters/`）

```
mhall_control_up=0   mhall_control_down=0   mhall_control2=0   mhall_control3=0
mhall_control4=1000  mhall_control5=3       mhall_control6=20  mhall_control7=2839
```

---

## 六、编译与打包

```
cd <内核树>
make O=out_native ARCH=arm64 CC=/usr/bin/clang-11 LD=ld.lld TECHPACK=y DTC=dtc Image.gz
# 配置：把 arch/arm64/configs/h130_factory.config 当 .config，再 olddefconfig
```

打包必须用**原厂 ramdisk + 原厂 dtb/dtbo**（BBK 的霍尔/升降节点只在原厂 dtbo 里，
本仓库编译的 dtbo 没有这些节点）。

---

## 七、还差什么（本序列**不含**，务必知悉）

1. **`bbk_hall_core` 框架驱动（未写）**：`/dev/bbk_hall_core`、ioctl `0x40046000/1/2/3`、
   标定文件 `cali_hall`（56 B）/`cali_mhall_final`（48 B）、6 个 sysfs
   （`/sys/devices/platform/bbk_hall_core/`）、队列与工作队列。
   **规格已完整逆向**（见 0008 补丁里的 `bbk_hall_core-逆向报告.md`），只差代码。
   因为缺它，工厂 config 的 `CONFIG_INPUT_HALL=y` 目前会被丢弃。
2. **传感器没有接入框架**：IST8801/MXM1120 驱动目前只做了 sysfs 与 input，
   **没有**调用原厂的注册接口
   （`struct hall_ops { int (*get_data)(void*, s16*); int (*set_enable)(void*, int); }`、
   `struct hall_dev { char name[24]; ops*; void *data; }`、`bbk_hall_core_register_device()`）。
   没有它，框架拿不到 up/down 读数。
3. **升降的位置闭环未做**：`gpio_pwm.c` 目前是**时间开环**（按 `all_time` 计时到位，
   留了弱符号早停钩子），缺原厂的 `vib_pwm_state_move_sate()`、`computer_distance()`、
   `is_top_or_bottom()`、`init_hall_data_fake()`、retry 循环与防夹逻辑。
4. **标定数据**：`/mnt/vendor/persist/sensors/cali_hall`(56 B) 与 `cali_mhall_final`(48 B)
   需由用户态 daemon 通过 ioctl 写入；位置闭环依赖它。
5. **真机验证未做**：霍尔与升降目前只有编译级验证。行程时间（`all_time=2839` 那套）
   必须实机微调。

---

## 八、参考文档

- 本文件夹 0006/0007/0008 三个文档补丁会落地：`s6patch霍尔/README.md`、
  `s6patch霍尔/vib_pwm-逆向报告.md`、`s6patch霍尔/bbk_hall_core-逆向报告.md`
- 相机/声音/触摸的修复见 `s6patch相机/`、`s6patch声音/`、`s6patch触摸/`
- 总体说明见仓库根目录 `EEBBK_S6_changes.md` 与 `EEBBK_S6_progress.md`
