# s6patch霍尔 — EEBBK S6 (P20H130) 霍尔传感器 / 升降摄像头子系统

状态：**逆向与重写进行中**（① IST8801 与 ② MXM1120 驱动已落地并编译通过，③④ 待写）

## 一、问题：四个私有驱动在源码里完全不存在

原厂内核里有一套完整的 BBK 霍尔/升降子系统，但**本仓库源码树一个字的实现都没有**：

```
grep -rl 'mxm1120|ist8801|magnachip|isentek|bbk_hall|hall_queue' <源码树>  →  0 命中
find -iname '*mxm1120*' -o -iname '*ist8801*'                          →  无驱动文件
```

而原厂内核里它们是**编进内核的**（不是模块），所以 `/vendor/lib/modules` 里也拿不到：

```
原厂 config:
  CONFIG_INPUT_HALL=y                  ← BBK 霍尔框架 bbk_hall_core
  CONFIG_INPUT_MXM1120_UP=y            ← Magnachip MXM1120（升）
  # CONFIG_INPUT_MXM1120_MIDDLE is not set
  CONFIG_INPUT_MXM1120_DOWN=y          ← Magnachip MXM1120（降）
  CONFIG_INPUT_IST8801=y               ← iSentek IST8801（3D 霍尔开关）
  CONFIG_VIB_PWM=y                     ← 升降电机 PWM（bbk_vib_pwm）
```

原厂设备上可见的痕迹：input 设备 `m1120_up` / `m1120_down` / `h110-vib-input`、
`/sys/module/bbk_hall_queue`、`/sys/devices/platform/soc/soc:bbk_vib_pwm/*`。

DT 侧节点（在 BBK 的 dtbo 覆盖层里，已随原厂 dtbo 保留）：

```dts
magnachip@0c { compatible = "magnachip,mxm1120,down"; reg = <0x0c>; magnachip,init-interval = <0x01>; };
magnachip@0f { compatible = "magnachip,mxm1120,up";   reg = <0x0f>; magnachip,init-interval = <0x01>; };
dhall@18 { status = "okay"; compatible = "isentek,ist8801-0"; reg = <0x18>; data-range = <0x00>;
           hall,bias_support = <0x00>; hall,bias-ratio = <0x5a>; };
dhall@1b { status = "okay"; compatible = "isentek,ist8801-2"; reg = <0x1b>; data-range = <0x00>;
           hall,bias_support = <0x00>; hall,bias-ratio = <0x5a>; };
ti65132s@3e { compatible = "ti,ti65132"; reg = <0x3e>; }   /* LCD 电源 IC，与本子系统无关 */
```

## 二、逆向方法（可复现）

1. **把原厂 Image 还原成带符号的 ELF**（原厂内核的 kallsyms 完整保留）：

   ```bash
   pip3 install peewee                       # vmlinux-to-elf 的依赖
   cd vmlinux-to-elf && PYTHONPATH=. python3 -m vmlinux_to_elf.scripts.vmlinux_to_elf \
        imgdata/boot_unpacked/Image /root/factory_vmlinux.elf
   # -> 37 MB ELF，115367 个符号
   ```

2. **按函数名反汇编**（符号表里函数名齐全，直接定位）：

   ```bash
   aarch64-linux-gnu-objdump -d --no-show-raw-insn \
       --start-address=0x... --stop-address=0x... /root/factory_vmlinux.elf
   ```

3. **机械抽取接口**：遍历每个 `i2c_master_send` / `i2c_transfer` 调用点，
   打印其前 16 条指令 → 得到「寄存器 + 值」；遍历 `bl` → 得到调用序列。
   工具在 `work/tools/`：`hall_disasm.py`、`hall_i2cmap.py`、`hall_readsites.py`、
   `hall_trace.py`、`hall_show.py`。

4. **反查字符串常量**：字符串常量由 `adrp xN, PAGE` + `add xN, xN, #PAGE_OFF`
   两条指令拼出地址，把该地址丢给
   `aarch64-linux-gnu-objdump -s --start-address=ADDR --stop-address=ADDR+0x40`
   就能在十六进制/ASCII 双列输出里读出字符串（本文件里的 DT 属性名、
   持久化路径、日志格式串都是这样拿到的）。

5. **`.data` 里的结构体**（例如 `dev_attr_vib_pwm_*`、`*_misc_dev_fops`）
   可以直接 `objdump -s` 转储再按小端指针解码：`struct device_attribute`
   是 `{name, mode, show, store}`，`struct file_operations` 开头是
   `owner, llseek, read, write, ...`，解出来就能直接跳到对应处理函数的地址。

## 三、已还原：IST8801（iSentek 3D 霍尔开关）

原厂符号（19 个）：`ist8801_i2c_probe`、`ist8801_i2c_read_block`、
`ist8801_set_operation_mode`、`ist8801_set_detection_mode`、`ist8801_hall_enable`、
`ist8801_hall_getdata`、`ist8801_get_data`、`ist8801_get_id`、`ist8801_reset_device`、
`ist8801_dump_reg`、`ist8801_i2c_suspend/resume`、`ist8801_ranges_1/_2` 等。

### I2C 协议

```
写： buf[0]=reg, buf[1]=value ; i2c_master_send(client, buf, 2)
     由全局 ist8801_i2c_mutex 串行化
读： ist8801_i2c_read_block(data, reg, buf, len)   /* len <= 0x11，超出返回 -EINVAL */
     msg[0] = {client->addr, flags=0,          len=1,   buf=&reg}
     msg[1] = {client->addr, flags=I2C_M_RD,   len=len, buf=buf}
     i2c_transfer(adapter, msgs, 2)
```

（`ist8801_i2c_read_block` 已逐条指令核对：栈上 `msgs` 布局、`I2C_M_RD=1`、
`client->addr` 取自 `client+2`、`adapter` 取自 `client+24`。）

### 寄存器映射（从写点/读点逐条抽出）

| 寄存器 | 写入值 | 读 | 推断含义 |
|---|---|---|---|
| `0x01` | `0x00` / `0x01` | — | 控制：复位 / 检测使能 |
| `0x07` | `0x01` | — | 控制 |
| `0x08` | `0x00` / `0x40` / `0x80` | — | **工作模式**：掉电 / 测量模式 / 触发一次测量 |
| `0x09` | — | 1B | **device id**（复位后 `msleep(20)` 再读，读两次） |
| `0x10` | — | **5B** | 数据块（`ist8801: data [%02X x5]`，首字节 ST1） |
| `0x20` | `0x00` / `0x02` | — | 控制 |
| `0x40` | — | 1B | 状态/模式（测量前后各读一次） |
| `0x54` | — | 1B | 状态 |
| `0x00..0x13` | — | 1B×20 | `ist8801_dump_reg` 的调试导出 |

### 数据通路

```
ist8801_hall_enable  →  set_detection_mode + set_operation_mode
ist8801_hall_getdata →  读 0x40 → 写 {0x08,0x80} 触发测量
                        → usleep_range(2000, 2500)
                        → 读 0x10 起 5 字节 → 读 0x40 → dump 0x00..0x13 → 读 0x54
                        → 组包成文本："ist8801 [%x], z=%6d, zc=%6d, t=%6d, t25=%6d."
                          （框架侧按文本行消费，另有 ist8801_get_zdata_compensation /
                            ist8801_get_t25 做 Z 轴温度补偿）
```

> 说明：`zc`/`t25` 的补偿公式在二进制里被内联展开，第一版驱动先按
> `z`（16bit LE，取自 0x10 块）与 `t` 原样上报，补偿待后续按
> `ist8801_get_zdata_compensation` / `ist8801_get_t25` 的反汇编补齐。

## 四、已还原：MXM1120（Magnachip，升降左右两个端点）

原厂符号：`m1120_i2c_drv_probe`(up/down 两份)、`m1120_i2c_set_reg(_up)`、
`m1120_measure(_up)`、`m1120_init_device`、`m1120_set_operation_mode`、
`m1120_irq_handler`、`m1120_update_interrupt_threshold(_up)`、
`m1120_misc_dev_ioctl`、`m1120_data_show`、`m1120_dump_show`、
`m1120_input_dev_init` 等共 18 个。

### I2C 协议

```
写： buf[0]=reg, buf[1]=value，单条 i2c_msg，i2c_transfer(adapter, &msg, 1)
读： i2c_smbus_read_i2c_block_data(client, reg, len, buf)
```

### 寄存器映射

| 寄存器 | 操作 | 含义 |
|---|---|---|
| `0x00` | 读 1B | **device id / 状态**，健康值为 `0x9c`；10bit 模式下 bit7:6 是该字段的高两位 |
| `0x00` | 写 `0x40` | 初始化 |
| `0x01` | 写 `0x00`，再读改写 `(v & 0x7f)` | 控制 |
| `0x07` | 写 `0x01` | 控制（初始化第一步） |
| `0x08` | 写 `0x40`（测量）/ `(v & 0xfe)` | **工作模式** |
| `0x10` | 读 **3B** | 测量块：`[0]`状态（bit0 = DRDY）、`[1]`低位、`[2]`高位 |
| `0x00..0x0a` | 读 | `m1120_dump_show` 调试导出 |

### 探测（probe）时序 —— 逐条指令照抄

```
write 0x07 = 0x01
read  0x00  → 必须 == 0x9c，否则 dev_err("current device id(0x%02X) is not M1120 device id(0x%02X)") 并 -ENODEV
write 0x00 = 0x40
write 0x01 = 0x00
write 0x08 = 0x40
read 0x01 → write 0x01 = (v & 0x7f)
read 0x08 → write 0x08 = (v & 0xfe)
```

### 测量与解码（`m1120_measure`）

```
smbus_read(0x10, 3, buf)         /* buf[0] bit0 = DRDY，未就绪时 dev_err("damon st1(0x%02X) is not DRDY") */
smbus_read(0x00, 1, &extra)
10bit 模式：v = buf[1] | (((extra >> 6) & 0x3) << 8)   然后按 bit9 做符号扩展
 8bit 模式：v = buf[2] & 0x7f                           然后按 bit7 做符号扩展
*(s16 *)out = v                  /* strh w16，即 16 位有符号 */
```

结果通过 input 设备上报：原厂 input 设备名就是 **`m1120_up` / `m1120_down`**，
能力 `EV_ABS` + `ABS_X`，范围 `-32768..32767`，`bustype = 0x18 (BUS_I2C)`。

### DT 属性（原厂解析的就是这四个）

| 属性 | 类型 | 原厂行为 |
|---|---|---|
| `magnachip,init-interval` | u32 | `data->init_interval`，读到 0 时强制为 1；probe 随后以 **20** 为延迟排队工作队列 |
| `magnachip,use-interrupt` | bool | 中断模式开关（原厂 DT 未设） |
| `magnachip,gpio-int` | gpio | 中断脚（原厂 DT 未设） |
| `magnachip,use-hrtimer` | bool | hrtimer 模式开关（原厂 DT 未设） |

原厂 DT 只给了 `magnachip,init-interval = <1>`，即纯轮询。

### ioctl（misc 设备，未在本实现中暴露）

```
M1120_IOCTL_{GET,SET}_REG / _ENABLE / _DELAY / _INTERRUPT /
GET_CALIBRATED_DATA / SET_CALIBRATION
日志:  [M1120-DBG] reg.map.intsrs = 0x%02X / threshold : (0x%02X%02X, 0x%02X%02X)
       [M1120-INFO] operation mode was chnaged to OPERATION_MODE_{MEASUREMENT,
                    POWERDOWN,FUSEROMACCESS}
       "wait 5ms after vdd power up"  /  "sw-reset was failed"
```

## 五、已探明：升降电机 `vib_pwm` 的硬件

DT 节点（在基础 DTB 的 `&soc` 下，设备路径即 `/sys/devices/platform/soc/soc:bbk_vib_pwm`）：

```dts
bbk_vib_pwm {
        compatible = "bbk,vib_pwm_control";
        boost-gpio  = <&tlmm 0x18 0>;   /* GPIO24 升压使能 */
        enable-gpio = <&tlmm 0x17 0>;   /* GPIO23 驱动使能 */
        sleep-gpio  = <&tlmm 0x1d 0>;   /* GPIO29 驱动 nSLEEP */
        dir-gpio    = <&tlmm 0x1a 0>;   /* GPIO26 方向 */
        id-gpio     = <&tlmm 0x19 0>;   /* GPIO25 机型识别 */
        pinctrl-names = "vib_pwm_active", "vib_pwm_suspend", "vib_pwm_idconfig";
        clocks = <&gcc 0x24>; clock-names = "gp2_clk";
};
```

关键点：**没有 pwm 控制器引用**，驱动波形来自通用时钟输出：

- `pinctrl-0 = vib_pwm_active`：把 **GPIO21 复用成 `gcc_gp2`**（时钟输出脚）→
  电机驱动芯片的输入波形就是 GP2 时钟，所以频率由 `vib_pwm_freq` 决定。
- `pinctrl-1 = vib_pwm_suspend`：GPIO21 还原成 gpio、下拉。
- `pinctrl-2 = vib_pwm_idconfig`：**GPIO25（id-gpio）配置成 gpio、上拉** →
  `vib_pwm_id` 靠外部下拉/上拉电阻读电平来识别升降模组型号。

时钟号 `0x24 = 36 = GCC_GP2_CLK`（见 `include/dt-bindings/clock/qcom,gcc-sdmmagpie.h`），
`gcc-sdmmagpie.c` 的 `gcc_gp2_clk` 带 `CLK_SET_RATE_PARENT`，
频率表 `ftbl_gcc_gp1_clk_src` 只有 **19.2 / 25 / 50 / 100 / 200 MHz** 五档 ——
即 `clk_set_rate()` 只会落到这五档上，`vib_pwm_freq` 必须按这个来。

## 六、用户态必须对齐的接口（本实现自定内部 ABI，但这层不能变）

1. `bbk_hall_core` 的 misc 设备 + sysfs（`enable`/`delay`/`data`/`vendor`/`cali_time`）
2. `vib_pwm` 的 sysfs —— 已从原厂设备完整抓到：
   ```
   vib_pwm_camera_state(0=收回 1=升起 2=升起并偏转)  vib_pwm_elevator_mode
   vib_pwm_elevator_row_shift  vib_pwm_holder_mode  vib_pwm_cali
   vib_pwm_clear_cali_data  vib_pwm_up_down_count  vib_pwm_count  vib_pwm_dir
   vib_pwm_freq  vib_pwm_time  vib_pwm_enable  vib_pwm_id  vib_pwm_state_init
   vib_pwm_abort_notify
   ```
   状态机字符串：`[LYQ-damon-vib]`、`damon enter vib_pwm_set_camera`、
   `RESTART_CAMERA_ELEVATOR to elevator_mode %d`、`damon enter handle input
   KEY_CAMERA_PRESS_MOVE & because: hall_up - hall_down < (cali_data.position1.hall_up_down_diff …)`；
   校准数据在 `/mnt/vendor/persist/sensors/`（`cali_hall`、`cali_mhall_final`）。

`bbk_hall_core` 侧已抓到的字符串：

```
bbk_hall_core: register up down hall Done,so add platform devices
---------ioctl: BBK_HALL_CORE_IOCTL_SET_MHALL_CALI_DAEMON -------
---------ioctl: BBK_HALL_CORE_IOCTL_SET_CALI after Hall Cali-------
---------ioctl: BBK_HALL_CORE_IOCTL_SET_MHALL_CALI after Hall Cali-------
---------ioctl: BBK_HALL_CORE_IOCTL_TRANS_CALI -------
bbk_hall failed kmalloc hall_data failed
bbk_hall_cali_time
```

即存在 `SET_CALI` / `SET_MHALL_CALI` / `SET_MHALL_CALI_DAEMON` / `TRANS_CALI`
四个 ioctl，且带一份「机型校准」数据（`cali_mhall_final`）；
模块参数 `mhall_control_up/_down/_press` 与 `mhall_control2..7` 说明还有一套
机械行程（mhall）标定阈值。

## 七、进度

| 步骤 | 内容 | 状态 |
|---|---|---|
| ① | `ist8801` 传感器驱动（寄存器映射已还原） | **已编译通过**，待真机确认节点/读数 |
| ② | `mxm1120` 传感器驱动（up/down 两实例，协议+解码已还原） | **已编译通过、已提交**，待真机确认节点/读数 |
| ③ | BBK 霍尔框架（misc + sysfs + 校准 + 队列） | 待写（ioctl 名与持久化路径已探明） |
| ④ | `vib_pwm` 升降电机（GPIO+GP2 时钟 + 状态机） | 待写（硬件与用户态接口已抓全） |

每步单独提交、单独编译，都能给出可刷镜像。
