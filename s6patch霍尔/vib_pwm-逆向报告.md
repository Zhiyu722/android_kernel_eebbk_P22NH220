# EEBBK S6 `vib_pwm`（升降摄像头）驱动逆向报告

对象：`/root/factory_vmlinux.elf`（AArch64，工厂 vmlinux，地址即链接地址，约 115367 个符号）
方法：`nm` 取符号地址 → 从 `.data` 里的 `struct device_attribute` 解出 name/mode/show/store 指针 → 反汇编对应函数 → 用 `adrp+add` 还原所有字符串常量与全局变量。
本文所有地址均为内核链接地址（`0xffffff80 xxxxxxxx`），可直接用
`aarch64-linux-gnu-objdump -d --no-show-raw-insn --start-address=A --stop-address=B /root/factory_vmlinux.elf` 复现。

> **警告**：`vmlinux-to-elf` 给大量函数贴的名字是错的（例如符号名 `test_data+0x2cd8` 其实是 `vib_pwm_data` 所在的 `.bss` 区域）。本文中**凡是我自己命名的字段/含义都要看"推断依据"**；凡带 `0x…` 地址的都是实测。

---

## 0. 复现步骤（最小集）

```bash
ELF=/root/factory_vmlinux.elf
# 1) 15 个属性的 dev_attr 结构（.data，每个 32 字节：name/mode/show/store）
aarch64-linux-gnu-objdump -s --start-address=0xffffff8009dccf80 --stop-address=0xffffff8009dcd160 $ELF
# 2) 驱动代码区（0xffffff8008aa9710 ~ 0xffffff8008aad908）
aarch64-linux-gnu-objdump -d --no-show-raw-insn --start-address=0xffffff8008aa9710 --stop-address=0xffffff8008aad908 $ELF
# 3) probe / 线程
aarch64-linux-gnu-objdump -d --no-show-raw-insn --start-address=0xffffff8008aac658 --stop-address=0xffffff8008aad908 $ELF
# 4) 字符串常量（vaddr = fileoff - 0x1c0 + 0xffffff8008080000）
```

关键事实（已确认）：

| 项 | 值 |
|---|---|
| 源码文件 | `drivers/input/hall/vib_pwm/gpio_pwm.c`（字符串 @0xffffff80099f6b3e） |
| KBUILD_MODNAME | `gpio_pwm`（模块参数名前缀 `gpio_pwm.` @0xffffff80095f10ec） |
| 私有数据指针（全局） | `vib_pwm_data` @0xffffff8009f755f0（`.bss`，8 字节） |
| 私有数据结构大小 | **680 字节**（probe: `devm_kmalloc(dev, 680, GFP_KERNEL)` @0xffffff8008aac68c） |
| 匹配表 | `vib_pwm_of_match` @0xffffff8009dcd160，`compatible = "bbk,vib_pwm_control"` |
| platform_driver | `vib_pwm_pdrv` @0xffffff8009dcd2f0（probe/remove/shutdown/suspend/resume） |
| 日志前缀 | `[LYQ-damon-vib]:` / `[LYQ-damon-hall]:`（带 KERN 级别前缀 `\0016`=INFO、`\0013`=ERR） |

---

## 1. `struct vib_pwm` 布局（680 字节）

推断手段：probe 的初始化序列、各字段的读写指令（`ldr/str [xN,#off]`）、`container_of` 偏移（`hrtimer_handler` 里 `x19 = x0 - 0x118`，`delay_func` 里 `x19 = &h->work` 即 `h+0x240`）。

| 偏移 | 大小 | 类型（推断） | 字段名（我起的名） | 含义与推断依据 |
|---|---|---|---|---|
| 0x000 | 8 | `struct platform_device *` | `pdev` | probe `stp x20,x19,[x0]` |
| 0x008 | 8 | `struct device *` | `dev` | 同上；`devm_pinctrl_get([h+8])` |
| 0x010 | 4 | `int` | `boost_gpio` | probe 用 DT 名 **`boost-gpio`** 解析后存 `[x22,#16]`（@0x8aac744）；运行时启停时置 1/0 |
| 0x014 | 4 | `int` | `enable_gpio` | DT **`enable-gpio`** → `[x22,#20]`；驱动时置 **0**、停止时置 **1**（低有效） |
| 0x018 | 4 | `int` | `sleep_gpio` | DT **`sleep-gpio`** → `[x22,#24]`；驱动置 1（唤醒）、停止置 0 |
| 0x01C | 4 | `int` | `dir_gpio` | DT **`dir-gpio`** → `[x22,#28]`；`enable==1` 置 0（上行）、`enable==2` 置 1（下行）；`vib_pwm_dir_show` 读它 |
| 0x020 | 4 | `int` | `id_gpio` | DT **`id-gpio`** → `[x22,#32]`；probe 配成输入，`vib_pwm_id_show` 读电平 |
| 0x028 | 8 | `struct pinctrl *` | `pinctrl` | `devm_pinctrl_get()` → `str x0,[x21,#40]` |
| 0x030 | 8 | `struct pinctrl_state *` | `pins_active` | `pinctrl_lookup_state(p,"vib_pwm_active")` |
| 0x038 | 8 | `struct pinctrl_state *` | `pins_suspend` | `"vib_pwm_suspend"`（**查出来但从不 select**） |
| 0x040 | 8 | `struct pinctrl_state *` | `pins_idconfig` | `"vib_pwm_idconfig"` |
| 0x048 | 8 | `struct clk *` | `pwm_clk` | `devm_clk_get(dev,"gp2_clk")`；所有 `clk_*` 调用都用它 |
| 0x050 | 0xC0 | `struct wakeup_source` | `vib_wake_lock` | `wakeup_source_prepare(&h[0x50],"vib_wake_lock")`+`add`；`__pm_stay_awake/relax(&h[0x50])` |
| 0x110 | 1 | `bool` | `ws_active` | `ldrb w8,[h+0x110]; tbnz #0` → 已持锁则跳过 `__pm_stay_awake`；`tbz #0` 则跳过 `__pm_relax` |
| 0x118 | 0x40 | `struct hrtimer` | `hrtimer` | `hrtimer_init(&h[0x118], CLOCK_MONOTONIC(1), HRTIMER_MODE_REL_PINNED(3))`；`h[0x140] = hrtimer_handler`（`str x9,[x8,#320]`，即 `hrtimer.function`） |
| 0x158 | 8 | `s64`(ktime_t) | `timer_ns` | `hrtimer_start_range_ns(&h[0x118], h[344], 0, 3)` |
| 0x160 | 4 | `int` | `time` | 本次行程时间（单位见 §4.3，用户态 `vib_pwm_time`） |
| 0x164 | 4 | `int` | `pre_time` | 0 或 **50**（分段驱动的第一段时长） |
| 0x168 | 1 | `u8` | `is_subsection` | 1 = 当前是"预驱动段"，hrtimer 到点后唤醒 `vib_freq_thread` |
| 0x170 | 0x18 | `wait_queue_head_t` | `wait_freq` | `__init_waitqueue_head(&h[0x170],"&vib_pwm_data->wait_freq",&key@0x9f75607)` |
| 0x188 | 8 | `struct task_struct *` | `freq_thread` | `kthread_create_on_node(vib_freq_thread,…)` → `str x20,[x8,#392]` |
| 0x190 | 8 | `u64` | `freq` | `clk_set_rate(clk, h[400])`；probe 默认 **19200** |
| 0x198 | 4 | `int` | `count` | 只被 `vib_pwm_count` show/store 使用（**其他代码从不读，形同废字段**） |
| 0x19C | 4 | `int` | `enable` | 0=停, 1=上行(正向), 2=下行(反向)；`vib_pwm_enable` 属性 + 状态机都写它 |
| 0x1A0 | 4 | `int` | `camera_state` | `get_camera_state()` 返回值；0/1/2/6/7 + 运动标记 4(上行中)/5(下行中) |
| 0x1A4 | 4 | `int` | `target_state` | 目标位置；`delay_func` 结束时 `h[416] = h[420]` |
| 0x1A8 | 4 | `int` | `key_idle` | probe 置 **1**；`vib_update_key()` 置 **0**；`vib_pwm_thread` 用它决定是否自动回位 |
| 0x1AC | 1 | `u8` | `pending_notify` | `vib_update_key`/`abort_notify` 置 1；"RESTART_CAMERA_ELEVATOR" 逻辑用 |
| 0x1B0 | 4 | `int` | `holder_mode` | `vib_pwm_holder_mode`，0..3 |
| 0x1B4 | 4 | `int` | `elevator_mode` | `vib_pwm_elevator_mode`，0..4/6；5 表示"挂起中"（show 特殊处理） |
| 0x1B8 | 32 | `char[32]` | `notify_str` | `abort_notify` 里 `strncpy(h+0x1B8, buf+9, 32)`；show 打印它 |
| 0x1D8 | 4 | `int` | `move_count` | **hrtimer 起停计数**；与全局 `retry_time` 比较决定重试 |
| 0x1DC | 4 | `int` | `sub_phase` | 每次启动置 1，hrtimer 停止时置 0 |
| 0x1E0 | 4 | `int` | `is_move` | `vib_is_move()` 返回它；启动置 1、停止置 0 |
| 0x1E8 | 0x18 | `wait_queue_head_t` | `wait` | `"&vib_pwm_data->wait"`，`vib_pwm_thread` 睡眠于此 |
| 0x200 | 0x18 | `wait_queue_head_t` | `wait_up_down_count` | `"&vib_pwm_data->wait_up_down_count"`，`vib_pwm_up_down_count_thread` 睡眠于此 |
| 0x218 | 1 | `u8` | `stop_flag` | 置 1 → 唤醒 `vib_pwm_thread` 执行"停车+异常处理"流程 |
| 0x219 | 1 | `u8` | `abort_flag` | 由 `cancel_vib_hrtimer(0)` 置 1 → 线程把 `camera_state` 设为 **6** |
| 0x21C | 4 | `int` | `is_in_cali` | `vib_is_in_cali()`；为 1 时 `vib_pwm_set_camera()` 直接返回 |
| 0x220 | 8 | `struct task_struct *` | `thread` | `vib_pwm_thread` |
| 0x228 | 8 | `struct task_struct *` | `up_down_thread` | `vib_pwm_up_down_count_thread` |
| 0x230 | 1 | `u8` | `up_down_flag` | 置 1 → 唤醒计数保存线程 |
| 0x238 | 8 | `workqueue_struct *` | `wq` | `alloc_workqueue("%s",…)`，名字 `vib_wq`（@0x99f7f94） |
| 0x240 | 0x20 | `struct work_struct` | `work` | `INIT_WORK(&h->work, delay_func)`；`delay_func` 里 `x19 = h+0x240` |
| 0x248/0x250 | 16 | `list_head` | `work.entry` | `INIT_LIST_HEAD` |
| 0x258 | 8 | `work_func_t` | — | `delay_func` @0x8aad688 |
| 0x260 | 0x30 | `struct timer_list` | `work.timer` | `init_timer_key(&h[0x260], TIMER_IRQSAFE(0x200000), …)`，function=`delayed_work_timer_fn`(0x80dc1b0)，data=`&h->work` |
| 0x2A0 | 4 | `int` | `up_down_count` | `vib_pwm_up_down_count` show/store 的对象 |
| 0x2A4 | 4 | `int` | `all_count` | 总行程次数；只与 up_down_count 同时 +1，并写入持久化文件 |

**probe 显式初始化的字段**（@0x8aacb10~0x8aacb50）：
`count=0, camera_state=0, is_move=0, freq=19200, pending_notify=0, elevator_mode=0, (u16)stop/abort_flag=0, up_down_flag=0, (u64)move_count/sub_phase=0, time=all_time(2839), is_in_cali=0, up_down_count=0, key_idle=1`。

> **重要缺陷**：`devm_kmalloc`（非 `kzalloc`）分配 680 字节，因此
> `enable(0x19C)`、`target_state(0x1A4)`、`holder_mode(0x1B0)`、`all_count(0x2A4)`、`notify_str(0x1B8..)`
> **没有初始化**。正常情况下 slab 页刚分配是 0，但**如果 `enable` 恰好是残留的 1/2，`vib_pwm_enable_store` 或其它路径可能意外驱动电机**。重写时务必 `kzalloc`。

全局状态变量（`.data`，非结构体成员）：

| 地址 | 符号 | 默认值 | 读/写者 |
|---|---|---|---|
| 0x9dccf68 | `mhall_fake_data4` = 参数 `mhall_control4` | **1000** | `vib_pwm_state_move_sate`(case 7) 时间系数 |
| 0x9dccf6c | `mhall_fake_data_re` = `mhall_control5` | **3** | 状态机/ `set_camera` 写 `retry_time` 的来源 |
| 0x9dccf70 | `mhall_fake_data_add_time` = `mhall_control6` | **20** | `(2,7)` 迁移的时间 |
| 0x9dccf74 | `all_time` = `mhall_control7` | **2839** | `set_vib_all_time()` 写、`set_camera`/`*_show` 读 |
| 0x9dccf78 | `retry_time` | 3（初值） | 状态机/`set_camera`/线程写；`delay_func` 读作重试上限 |
| 0x9f755d8 | `mhall_fake_data_up` = `mhall_control_up` | 0 | 状态机 case 7 的死区阈值 |
| 0x9f755dc | `mhall_fake_data_down` = `mhall_control_down` | 0 | 状态机 case 7 / `row_shift_show` |
| 0x9f755e0 | `mhall_fake_data2` = `mhall_control2` | 0 | `(7,2)/(2,7)` 时间修正 |
| 0x9f755e4 | `mhall_fake_data3` = `mhall_control3` | 0 | case 7 的"目标霍尔读数" |
| 0x9f755e8 | `mhall_fake_data5` = `mhall_control?`（无参数） | 0 | case 2 的距离-时间系数（默认 0 → 走备用分支） |
| 0x9f75600 | `adjust_flag` | 0 | case 7 上行成功后置 1；`set_camera(7,2)` 清 0；只被 `row_shift_show` 读 |
| 0x9f75604 | `still_flag` | 0 | case 7 下行循环中置 1；`delay_func` 读 |
| 0x9f755f8 | `vib_input_dev` | NULL | 输入设备 |
| 0x9f75608 | `mhall_data` | 堆指针(168B) | 霍尔核心结构（`kmem_cache` 分配，见 §5） |
| 0x9f75610 | `g_hall_cali_data` | 全 0（.bss，56B） | 位置标定表，用户态 ioctl 写入 |
| 0x9f75648 | `g_mhall_cali_data` | 全 0（.bss，48B） | 另一套标定表（`elevator_row_shift_show` / 假数据注入） |

---

## 2. 15 个 sysfs 属性

`struct device_attribute` = `{const char *attr_name; umode_t mode; ssize_t (*show)(…); ssize_t (*store)(…);}`
（4 个指针/整数字段共 32 字节，`.data` @0x9dccf80 起，按下面的顺序连续排列）

| # | 属性名（字符串地址） | mode | show | store | 备注 |
|---|---|---|---|---|---|
| 1 | `vib_pwm_id` @0x99f760c | **0444** | `vib_pwm_id_show` @0x8aab128 | — | 只读 |
| 2 | `vib_pwm_freq` @0x99f7617 | 0664 | `vib_pwm_frequency_show` @0x8aab198 | `vib_pwm_frequency_store` @0x8aab1c8 | |
| 3 | `vib_pwm_count` @0x99f7624 | 0664 | `vib_pwm_count_show` @0x8aab248 | `vib_pwm_count_store` @0x8aab278 | |
| 4 | `vib_pwm_enable` @0x99f7632 | 0664 | `vib_pwm_enable_show` @0x8aab2f8 | `vib_pwm_enable_store` @0x8aab328 | 直接启停电机 |
| 5 | `vib_pwm_dir` @0x99f7641 | 0664 | `vib_pwm_dir_show` @0x8aab5e0 | `vib_pwm_dir_store` @0x8aab628 | |
| 6 | `vib_pwm_time` @0x99f764d | 0664 | `vib_pwm_time_show` @0x8aab670 | `vib_pwm_time_store` @0x8aab6a8 | |
| 7 | `vib_pwm_camera_state` @0x99f765a | 0664 | `vib_pwm_camera_state_show` @0x8aab760 | `vib_pwm_camera_state_store` @0x8aab790 | 主入口 |
| 8 | `vib_pwm_state_init` @0x99f766f | 0664 | `vib_pwm_state_init_show` @0x8aab840 | `vib_pwm_state_init_store` @0x8aab870 | |
| 9 | `vib_pwm_abort_notify` @0x99f7682 | 0664 | `vib_pwm_abort_notify_show` @0x8aab928 | `vib_pwm_abort_notify_store` @0x8aab958 | 字符串协议 |
| 10 | `vib_pwm_holder_mode` @0x99f7697 | 0664 | `vib_pwm_holder_mode_show` @0x8aabeb0 | `vib_pwm_holder_mode_store` @0x8aabee0 | |
| 11 | `vib_pwm_elevator_mode` @0x99f76ab | 0664 | `vib_pwm_elevator_mode_show` @0x8aabff8 | `vib_pwm_elevator_mode_store` @0x8aac038 | |
| 12 | `vib_pwm_elevator_row_shift` @0x99f76c1 | 0664 | `vib_pwm_elevator_row_shift_show` @0x8aac1a8 | — | **只读** |
| 13 | `vib_pwm_cali` @0x99f76dc | 0664 | `vib_pwm_cali_show` @0x8aac3f0 | `vib_pwm_cali_store` @0x8aac428 | |
| 14 | `vib_pwm_up_down_count` @0x99f76e9 | 0664 | `vib_pwm_up_down_count_show` @0x8aac4d0 | `vib_pwm_up_down_count_store` @0x8aac508 | |
| 15 | `vib_pwm_clear_cali_data` @0x99f76ff | 0664 | `vib_pwm_clear_cali_data_show` @0x8aac5b0 | `vib_pwm_clear_cali_data_store` @0x8aac5d8 | |

全部用 `device_create_file(&pdev->dev, &dev_attr_vib_pwm_xxx)` 在 probe 末尾依次创建（@0x8aace28~0x8aacf8c），失败只打印 `device_create_file (%s) = %d` 并继续。
属性挂在 platform 设备上，即任务里给的 `/sys/devices/platform/soc/soc:bbk_vib_pwm/`。
所有 `store` 都以 `return count;`（即入参 `count`）结束，不返回负数。

### 2.1 逐个语义（伪 C，`h = dev_get_drvdata(dev)` = `*(void**)(dev+160)` = `vib_pwm_data`）

#### (1) `vib_pwm_id` 0444 — `vib_pwm_id_show` @0x8aab128
```c
struct vib_pwm *h = dev_get_drvdata(dev);
int id;
if (h && h->boost_gpio /* 偏移 0x10 ！厂商 bug，见下 */) {
    printk("\0016[LYQ-damon-vib]:Entry vib_pwm_id_show & get vib id\n");
    id = gpiod_get_raw_value(gpio_to_desc(h->id_gpio));   /* 偏移 0x20，probe 配成输入 */
} else {
    printk("\0016[LYQ-damon-vib]:Error Entry vib_pwm_id_show & id_gpio is null\n");
    id = 0;
}
return sprintf(buf, "vib_id=%d\n", id);
```
> **厂商 bug（实测）**：判断条件读的是 `[x20,#16]`（boost_gpio，@0x8aab140），实际取值的却是 `[x20,#32]`（id_gpio，@0x8aab154）。报错文字却说 "id_gpio is null"。行为上无大碍（两个 GPIO 都在 probe 里 request 成功），重写时应改成判断 `id_gpio`。

#### (2) `vib_pwm_freq` 0664
```c
/* show */ return sprintf(buf, "vib_freq=%d\n", (int)h->freq);           /* 偏移 0x190，64 位 */
/* store */
int val;
if (!buf || !count) return count;
kstrtoint(buf, 10, &val);          /* 不管成败 */
h->freq = val;                     /* 64 位存；失败时 val=0 */
return count;
```
**无任何校验、不调用 `clk_set_rate`**（仅在后续 `vib_pwm_enable_store`/状态机启动时生效）。

#### (3) `vib_pwm_count` 0664
```c
/* show */ return sprintf(buf, "count=%d\n", h->count);   /* 偏移 0x198 */
/* store */
int val = 0;
if (!buf || !count) return count;
if (kstrtoint(buf, 10, &val)) h->count = 0;   /* 编译产物：先写 0 再写 val */
h->count = val;
return count;
```
`h->count` 在驱动其它地方**从不被读取**——是个没用的调试旋钮。

#### (4) `vib_pwm_enable` 0664 — 最直接的启停接口
```c
/* show */ return sprintf(buf, "enable=%d\n", h->enable);   /* 偏移 0x19C */
/* store */
int val;
if (!buf || !count) return count;
if (kstrtoint(buf, 10, &val)) return count;   /* 解析失败直接返回 */
h->enable = val;
printk("\0016[LYQ-damon-vib]:%s enter enable %d,time %d\n", __func__, h->enable, h->time);

if (h->enable == 2) goto do2;
if (h->enable != 1) {                    /* 0 或其它 */
    gpiod_direction_output_raw(gpio_to_desc(h->boost_gpio), 0);
    msleep(5);
    gpiod_direction_output_raw(gpio_to_desc(h->enable_gpio), 1);
    gpiod_direction_output_raw(gpio_to_desc(h->sleep_gpio), 0);
    return count;                        /* 不碰时钟、不碰 hrtimer */
}
/* enable == 1 */
__pm_stay_awake(&h->ws) if (!h->ws_active);
h->timer_ns = ms_to_ns(h->time);          /* 见 §4.3；此处不做 0.6 缩放 */
clk_set_rate(h->pwm_clk, h->freq);
clk_prepare(h->pwm_clk);
printk("\0016[LYQ-damon-vib]:%s enter enable clk_prepare pwm_clk\n", __func__);
if (clk_set_rate_ret < 0) goto err;       /* tbnz w21,#31 */
gpiod_direction_output_raw(gpio_to_desc(h->dir_gpio), 0);
gpiod_direction_output_raw(gpio_to_desc(h->boost_gpio), 1);
msleep(3);
gpiod_direction_output_raw(gpio_to_desc(h->enable_gpio), 0);
gpiod_direction_output_raw(gpio_to_desc(h->sleep_gpio), 1);
msleep(3);
clk_enable(h->pwm_clk);
h->sub_phase = 1;
hrtimer_start_range_ns(&h->hrtimer, h->timer_ns, 0, HRTIMER_MODE_REL_PINNED);
return count;

do2:  /* enable == 2：与 1 相同，唯一区别是 dir_gpio 置 1，且不打印 clk_prepare 日志 */
    … dir_gpio=1; boost=1; msleep(3); enable=0; sleep=1; msleep(3); clk_enable; hrtimer_start …
err:
    printk("\0013%s can't set pwm_clk rate 10KHz ret=%d\n", __func__, ret);
    if (h->ws_active) __pm_relax(&h->ws);
    return count;
```
注意：**enable_store 不动 `is_move(0x1E0)`、不动 `move_count(0x1D8)`、不 enable/disable 霍尔核心、不调 `vib_pwm_set_camera_state`**——这是和状态机路径的关键差异。

#### (5) `vib_pwm_dir` 0664
```c
/* show */ return sprintf(buf, "dir=%d\n", gpiod_get_raw_value(gpio_to_desc(h->dir_gpio)));
/* store */
if (buf && count) {
    int c = buf[0];
    gpiod_set_raw_value(gpio_to_desc(h->dir_gpio), (c == '1'));  /* gpiod_set_raw_value，非 direction_output */
}
return count;
```
即写 `'1'` → dir 高、其它任何内容（含 `'0'`、`'2'`）→ dir 低。

#### (6) `vib_pwm_time` 0664
```c
/* show */ return sprintf(buf, "time=%d all_time=%d\n", h->time, all_time);
/* store */
int val = 0;
if (!buf || !count) return count;
if (kstrtoint(buf, 10, &val)) h->time = all_time;  /* 解析失败 → 恢复默认总时长 */
h->time = val;
if (val == 1300) {                                  /* 0x514 特殊值 */
    printk("time set 1300 ,change %d\n", all_time + 10);
    h->time = all_time + 10;
}
return count;
```

#### (7) `vib_pwm_camera_state` 0664 —— 用户态主入口
```c
/* show */ return sprintf(buf, "%d\n", h->camera_state);   /* 偏移 0x1A0 */
/* store */
int val = 0;
printk("\0016[LYQ-damon-vib]:------------%s want to set camera_state:%s\n",
       "vib_pwm_camera_state_store", buf);   /* 第二个 %s 直接把用户写入的原文打出来 */
if (!buf || !count) return count;
if (kstrtoint(buf, 10, &val)) {
    printk("damon vib_pwm_camera_state_store get error state\n");
    return count;
}
printk("damon vib_pwm_camera_state_store get state %d\n", val);
vib_pwm_set_camera(val);          /* 见 §3.2 */
return count;
```

#### (8) `vib_pwm_state_init` 0664
```c
/* show */ return sprintf(buf, "%d\n", h->camera_state);   /* 与 camera_state_show 完全相同 */
/* store */
int val = 0;
if (!buf || !count) return count;
if (kstrtoint(buf, 10, &val)) return count;
if (bbk_hall_get_status() != 1) return count;   /* 霍尔核心没 probe 成功 → 什么都不做 */
if (val != 0) return count;                     /* 只接受 0 */
bbk_hall_core_enable(1);
msleep(10);
if (vib_pwm_state_move_sate(0 /*目标：回位*/, 0 /*notify*/) == 0)
    h->camera_state = 0;
bbk_hall_core_enable(0);
return count;
```
用途：开机/恢复时把升降台移到 0 位并同步 `camera_state`。

#### (9) `vib_pwm_abort_notify` 0664 —— 字符串命令协议（Android framework ABI）
```c
/* show */ return sprintf(buf, "%s\n", h->notify_str);     /* h+0x1B8，32 字节 */
/* store */
if (!buf || !count) return count;
printk("\0016[LYQ-damon-vib]:-------%s *%s* \n", __func__, buf);
/* 依次 strncmp(buf, K, strlen(K)) 匹配关键字（全部是字面量） */
```
关键字 → 行为（`set_camera` 指 `vib_pwm_set_camera()`）：

| 关键字（地址） | 行为 |
|---|---|
| `"0x27c"`、`"636"` | `set_camera(0)`; `h[428]=1`; 然后注入按键 **636**（日志 "vib update key 636, drop detect"） |
| `"0x27d"`、`"637"` | `set_camera(0)`; `h[428]=1`; 按键 **637**（"angle move"） |
| `"0x27f"`、`"639"` | 按键 **639**（"not holder angle"），不改状态 |
| `"0x280"`、`"640"` | 按键 **640**（"holder angle"） |
| `"0x282"`、`"642"` | 按键 **642** |
| `"0x283"`、`"643"` | `set_camera(0)`; `h[428]=1`; 按键 **643** |
| `"0x284"`、`"644"` | 见下面"RESTART_CAMERA_ELEVATOR"分支（表 A） |
| `"username:"` (0x99f7bf0) | `strncpy(h->notify_str, buf + strlen("username:"), 32)` |
| `"stream on"` (0x99f7bfa) | 按键 **645** (0x285) |
| `"stream off"` (0x99f7c04) | 按键 **646** (0x286) |
| `"888"` (0x9a11926) | 若 `h[428]` 为 1 → 清 0 并返回；否则继续向下匹配 |
| `"666"` (0x99f7b8c) | 若 `h[428]==1` → 按 elevator_mode 重启升降台（表 B） |
| `"com.eebbk.askhomework"` (0x99f7a5f) | 先 `strstr(h->notify_str, "com.eebbk.askhomework")`：命中 → 打印 "current user is com.eebbk.askhomework, maintain blocking" 并只注入按键 **644**；否则若 `h[428]==1` → 按 elevator_mode 重启（表 A） |

"RESTART_CAMERA_ELEVATOR" 按 `elevator_mode`（`h[436]`）分派（两张跳转表 0x95f10e5 / 0x95f10de）：

| elevator_mode | 动作 |
|---|---|
| 0 | `set_camera(0)` |
| 1 | `set_camera(1)` |
| 2 | `set_camera(2)` 然后 `set_camera(7)` |
| 3 | `set_camera(1)` |
| 4 | `set_camera(2)` 然后 `set_camera(7)` |
| 5 | 不动作，只注入按键 641（表 B）/ 644（表 A） |
| 6 | `set_camera(7)` |

以及 `printk("...RESTART_CAMERA_ELEVATOR to elevator_mode %d\n", h[436])`。
按键注入方式（`abort_notify_store` 和 `vib_update_key` 都一样）：`input_event(dev, EV_KEY(1), key, 1); input_event(dev, EV_SYN(0),0,0); input_event(dev, EV_KEY, key, 0); input_event(dev, EV_SYN,0,0)` —— **一次按下+一次抬起，各自带 SYN**。

#### (10) `vib_pwm_holder_mode` 0664
```c
/* show */ return sprintf(buf, "%d\n", h->holder_mode);   /* 偏移 0x1B0 */
/* store */
printk("damon vib_pwm_holder_mode_store holder_mode *%s*\n", buf);
if (!buf || !count) return count;
if      (!strncmp(buf, "0", 1)) { h->holder_mode = 0; }
else if (!strncmp(buf, "1", 1)) { h->holder_mode = 1; }
else if (!strncmp(buf, "2", 1)) { h->holder_mode = 2; vib_pwm_set_camera(0); }
else if (!strncmp(buf, "3", 1)) { h->holder_mode = 3; vib_pwm_set_camera(0); }
return count;
```
（关键字就是 4 个单字符串 `"0"`@0x98ebb25、`"1"`@0x9904df2、`"2"`@0x990dea2、`"3"`@0x98ef7c1。模式 2/3 会**顺带回位**，调用 `set_camera(0)`。）

#### (11) `vib_pwm_elevator_mode` 0664
```c
/* show */ return sprintf(buf, "%d\n", h->pending_notify ? 5 : h->elevator_mode);
/* store */
printk("damon vib_pwm_elevator_mode_store elevator_mode *%s*\n", buf);
if (!buf || !count) return count;
if      (!strncmp(buf,"0",1)) h->elevator_mode = 0;
else if (!strncmp(buf,"1",1)) h->elevator_mode = 1;
else if (!strncmp(buf,"2",1)) h->elevator_mode = 2;
else if (!strncmp(buf,"3",1)) h->elevator_mode = 3;
else if (!strncmp(buf,"4",1)) h->elevator_mode = 4;   /* @0x9908f45 */
else if (!strncmp(buf,"6",1)) h->elevator_mode = 6;   /* @0x98ebb9e */
return count;
```
（没有 `5`；`5` 只作为 show 的"挂起中"标记。）

#### (12) `vib_pwm_elevator_row_shift` 0664，**只读**
```c
s16 up = 0, down = 0;
s16 c8  = *(s16*)(g_mhall_cali_data + 8);    /* 0x9f75648 */
s16 c16 = *(s16*)(g_mhall_cali_data + 16);
s16 c24 = *(s16*)(g_mhall_cali_data + 24);
s16 c32 = *(s16*)(g_mhall_cali_data + 32);
int m0 = abs(((int)c16 + c8 ) / 2);          /* 有符号除 2，向零截断 */
int m1 = abs(((int)c24 + c16) / 2);
int m2 = abs(((int)c32 + c24) / 2);
int ret = bbk_hall_core_read_data(&up, &down);
if (ret) { printk("zya damon %s bbk_hall_core_read_data failed\n", __func__);
           return sprintf(buf, "%d", ret); }
int thr = abs((int)mhall_fake_data3 - (int)mhall_fake_data_down + 2) - 2;
int v   = abs((int)up);
int row;                                   /* 由 m0/m1/m2 (+c8/c16/c24/c32 边界) 分段 */
…见下…
return sprintf(buf, "%d %d %d %d %d %d %d %d",
               row, adjust_flag /*0x9f75600*/,
               (thr >= v), (abs(c16) <= v), (abs(c24) <= v), (abs(c32) <= v),
               v, v - thr);
```
行号分段（我把分支树化简后的结果；编译产物里还额外夹了 `c8/c16/c24/c32` 的边界比较，但有效结果就是这个阶梯）：
`row = 0 if v < m0; 2 if m0<=v<m1; 4 if m1<=v<m2; 6 if v>=m2`，其中
`v < c32 且 m2 <= v` 时也给 6，`c8<=v<m0` 明确给 0。
这个属性是产线/调试用的自检视图（无 store），重写时可以按上式复刻。

#### (13) `vib_pwm_cali` 0664
```c
/* show */ return sprintf(buf, "%d\n", h->is_in_cali);   /* 偏移 0x21C */
/* store */
if (!buf || !count) return count;
if      (!strncmp(buf, "0", 1)) { h->is_in_cali = 0; bbk_hall_core_enable(0); }
else if (!strncmp(buf, "1", 1)) { h->is_in_cali = 1; h->camera_state = 0;
                                  bbk_hall_core_enable(1); }
return count;
```
（`str xzr,[h,#416]` 同时把 `camera_state` 和 `target_state` 清 0。）`is_in_cali==1` 会让 `set_camera()` 以及状态机里的位置修正全部失效。

#### (14) `vib_pwm_up_down_count` 0664
```c
/* show */ return sprintf(buf, "%u\n", h->up_down_count);   /* 偏移 0x2A0 */
/* store */
int val = 0;
if (!buf || !count) return count;
sscanf(buf, "%u", &val);
printk("count:%u\n", val);
h->up_down_count = val;      /* 只写 0x2A0，不动 all_count */
h->up_down_flag = 1;         /* 唤醒保存线程 */
__wake_up(&h->wait_up_down_count, 1, 1, NULL);
return count;
```

#### (15) `vib_pwm_clear_cali_data` 0664
```c
/* show */ return sprintf(buf, "clear");       /* 常量字符串，无参数 */
/* store */
int val = 0;
if (!buf || !count) return count;
sscanf(buf, "%u", &val);
if (val == 1) hall_clear_cali_data();          /* 0x8aad908：memset(g_hall_cali_data,0,56) + mhall_data->[36]=0 */
return count;
```

---

## 3. `camera_state` 状态机

### 3.1 语义（从状态机代码 + 标定命名反推）

| 值 | 含义 | 依据 |
|---|---|---|
| 0 | 收起位（行程 0） | `(1,0)`/`(2,0)` 迁移的时间 = 0.696·all_time / all_time，且 `vib_pwm_thread` 异常流程把 `camera_state` 归 0 |
| 1 | 中间行，**69.6%** 行程 | `(1,0)` 时间 = `all_time*696/1000`；`vib_pwm_state_move_sate(1)` 收敛目标是 `pos=11101 = 0.696×15950`；标定点名 `position_696` |
| 7 | 弹出保持位（holder/standby），介于 1 和 2 之间 | `(7,1)` 走**上行**、`(7,2)` 走**下行**（见 §3.2 表） |
| 2 | 完全伸出位，**100%** 行程 | `(2,0)` 时间 = `all_time`；`state_move_sate(2)` 目标是 `pos=15950`；标定点名 `position_1` |
| 4 | **上行中**（朝 pos 增大方向） | `enable=1`(dir=0)；`is_top_or_bottom()` 在 `distance≈15950` 时对 state 4 返回 1 |
| 5 | **下行中** | `enable=2`(dir=1)；`is_top_or_bottom()` 在 `distance≈0` 时对 state 5 返回 1 |
| 6 | 异常/未知（"only_stop_vib"，hall 刷卡/强推导致的中断） | `vib_pwm_thread` 在 `abort_flag` 时置 6 |
| 3 | 未使用 | 状态机 switch 里 3/4/5/6 直接 `return 0` |

行程顺序：**0 < 1 < 7 < 2**（"上"= pos 增大）。

`int get_camera_state(void)` @0x8aa9930：
```c
struct vib_pwm *h = vib_pwm_data;
if (!h) return -1;
return h->camera_state;     /* +0x1A0 */
```
其它导出给霍尔驱动的查询：`vib_is_move()` → `h->is_move`；`vib_is_in_cali()` → `h->is_in_cali`。

### 3.2 写 `vib_pwm_camera_state` = 0/1/2 ⇒ `vib_pwm_set_camera(v)` @0x8aaa7e0

```c
printk("\0016[LYQ-damon-vib]:%s want to set camera_state: %d, current camera_state:%d, is_in_cali:%d\n",
       "vib_pwm_set_camera", v, h->camera_state, h->is_in_cali);
cur = h->camera_state;
if ((cur & ~1) == 4)  return 0;    /* cur==4 || cur==5：正在动，忽略 */
if (h->is_in_cali == 1) return 0;
h->freq = 32000;                   /* 0x7D00，写 64 位 */
if (cur == v) return 0;            /* 已到位 */
switch ((v, cur)) { … }
```
迁移表（`enable` 决定转向，`target = h[420]`，`camera_state = h[416]`，`time = h[352]`，`retry = retry_time`）：

| (目标, 当前) | time | enable/dir | camera_state | target | 其它 |
|---|---|---|---|---|---|
| (1,0) | `all_time*696/1000` | 1（0，上行） | 4 | 1 | `retry=3`；count++；wake `wait_up_down_count` |
| (2,0) | `all_time` | 1（上行） | 4 | 2 | 同上 |
| (2,1) | `all_time - all_time*696/1000` | 1（上行） | 4 | 2 | 同上 |
| (0,1) | `all_time*696/1000` | 2（1，下行） | 5 | 0 | `retry=3` |
| (0,2) | `all_time` | 2（下行） | 5 | 0 | `retry=3` |
| (1,2) | `all_time - all_time*696/1000` | 2（下行） | 5 | 1 | `retry=3` |
| (7,0) | `all_time - (mhall_fake_data2*10/6)*15/100` | 1（上行） | 4 | 7 | `adjust_flag=0`；`retry=mhall_fake_data_re` |
| (0,7) | 同上 | 2（下行） | 5 | 0 | `retry=3` |
| (7,1) | `all_time - all_time*696/1000 - (fake2*10/6)*15/100` | 1（上行） | 4 | 7 | `retry=mhall_fake_data_re` |
| (1,7) | 同上 | 2（下行） | 5 | 1 | `retry=mhall_fake_data_re` |
| (7,2) | `(mhall_fake_data2*10/6)` | 2（下行） | 5 | 7 | `freq=4800`；`retry=3`；`adjust_flag=0` |
| (2,7) | `(mhall_fake_data_add_time + mhall_fake_data2)*10/6` | 1（上行） | 4 | 2 | `freq=4800`；`retry=3` |
| (≤2, 6) | — | — | — | — | `if (bbk_hall_get_status()!=1) return;`<br>`if (vib_pwm_state_move_sate(v,0)!=0) return; h->camera_state = v;` |
| 其它组合 | — | — | — | — | 什么都不做（仅 freq=32000 已生效） |

以默认参数（`all_time=2839, fake2=0, add_time=20`）为例的实际数值：
`(1,0)=(0,1)=1975`；`(2,0)=(0,2)=2839`；`(2,1)=(1,2)=864`；`(7,0)=(0,7)=2839`；`(7,1)=(1,7)=864`；`(7,2)=0`；`(2,7)=33`。

每个成功分支都做：
```c
h->time = t; h->enable = e; h->camera_state = 4|5; h->target_state = v;
retry_time = …;
bbk_hall_core_enable(0);            /* 先关霍尔采样 */
vib_pwm_set_camera_state(h);        /* 真正启动电机，见 §4 */
if (cur == 0) { h->up_down_count++; h->all_count++; h->up_down_flag = e;   /* 1 */
                __wake_up(&h->wait_up_down_count, 1, 1, NULL); }
if (notify) vib_update_key(0x27B 或 0x27E);
```
注意 `(cur==0)` 的计数逻辑：**up_down_count 与 all_count 一起 +1**（把 `wait_up_down_count` 唤醒去持久化）。

### 3.3 按键注入 `vib_update_key(int key)` @0x8aa9790（导出，供霍尔驱动调用）
```c
h = vib_pwm_data;
if (key-0x27B <= 5) {                       /* 635..640 */
    h->pending_notify = 1;                  /* 0x1AC */
    h->key_idle = 0;                        /* 0x1A8 = 0 */
    h->stop_flag = 1;                       /* 0x218 = 1  → 唤醒停车线程 */
    bbk_hall_core_init_move_queue();
    bbk_hall_core_init_queue();
    __wake_up(&h->wait, 1, 1, NULL);
    switch (key) {   /* 跳转表 0x95f10d0: 00 16 1a 00 1e 22 */
      case 635 /*KEY_CAMERA*/:      printk("…vib update key %d, press\n", 635);   break;
      case 636:                     printk("…vib update key %d, drop detect\n", 636); break;
      case 637:                     printk("…vib update key %d, angle move\n", 637);  break;
      case 638 /*PRESS_MOVE*/:      printk("…vib update key %d, press move\n", 638); break;
      case 639:                     printk("…not holder angle…", 639); break;
      case 640:                     printk("…holder angle…", 640);     break;
    }
}
input_event(vib_input_dev, EV_KEY, key, 1);  input_event(dev, EV_SYN,0,0);
input_event(vib_input_dev, EV_KEY, key, 0);  input_event(dev, EV_SYN,0,0);
return 0;
```

### 3.4 `vib_pwm_state_move_sate(int state, int notify)` @0x8aa9d38（导出）

```c
if (bbk_hall_get_status() != 1) return 0;
if (bbk_hall_core_read_data(&up, &down)) { printk("damon %s bbk_hall_core_read_data failed\n"); return 0; }
d = up - down;
printk("zya damon get raw up %d,down %d\n", up, down);
pos = computer_distance(d, &g_hall_cali_data);       /* 0..15950；标定无效 → -1 */
if (pos == -1) return 0;
switch (state) {                                     /* 跳转表 0x95f10d6: 2d 33 4b 00 00 00 00 85 */
  case 0:   /* 回 0 位 */
    if (pos <= 299) { if (notify) vib_update_key(638); return 0; }
    time = g_hall_cali_data.all_time * pos / 15950;
    printk("damon get all time %d,time %d,distance %d\n", all_time, time, pos);
    target=0; camera_state=5; enable=2; goto start;
  case 1:   /* 收敛到 69.6% */
    if (pos > 11100) {
        if (pos < 12102) return 0;                       /* 死区 ±1000 */
        t = pos - 11101; time = all_time*t/15950;
        printk("damon get 1-down all time …\n");
        target=1; camera_state=5; enable=2; key=635; goto start;
    }
    t = 11101 - pos; if (t < 1001) return 0;
    time = all_time*t/15950;
    printk("damon get 1-up all time …\n");
    target=1; camera_state=4; enable=1; key=635; goto start;
  case 2:   /* 收敛到 100% */
    if (mhall_fake_data5 != 0) {           /* 默认 0，不走这条 */
        tgt = |(s16)g_hall_cali_data[36]|; v = |up|;
        printk("zyha2 distance(up):%d,target_distance:%d\n", v, tgt);
        dd = tgt - v; if (dd <= 0) return 0;
        time = mhall_fake_data5 * dd / 1000;
        printk("zyaato2 damon get 71-up all time …\n");
    } else {
        t = 15950 - pos; if (t < 151) return 0;
        time = all_time * t / 15950;
        printk("damon get 2 all time …\n");
    }
    target=2; camera_state=4; enable=1; key=635; goto start;
  case 7:   /* 用霍尔计数找 holder 位（略，见下） */
  default:  return 0;                    /* state∈{-1,3,4,5,6,>7} 全是空操作 */
}
start:
    h->time = time; h->enable = enable; h->camera_state = camera_state; h->target_state = target;
    if (notify) vib_update_key(key);
    bbk_hall_core_enable(0);
    vib_pwm_set_camera_state(h);
    /* case 1/2/7 会再读一次霍尔并打印 *_fin/*_o 日志 */
    return 1;
```
`case 7` 摘要（`fake_data3` = 目标霍尔读数、`fake_data_up/down` = 死区）：
- `w = |mhall_fake_data3| - |up|`；`w > mhall_fake_data_down` ⇒ **上行**：`time = w*mhall_fake_data4*10/6000`，`target=7, camera_state=4, enable=1`，`adjust_flag=1`，返回 1；
- 否则 **下行**：`w = |up| - |mhall_fake_data3|`，`w > mhall_fake_data_up` ⇒ `time = w*fake_data4*10/6000`，`target=7, camera_state=5, enable=2`；然后**最多 5 次**循环：每次读霍尔、`|up| - fake_data3 >= 5` 就再启动一小段（`still_flag=1`）；循环结束 `still_flag=0`，返回 1。
- 默认参数下（fake_data3=fake_data_up=0）等价于：`time = |up|*1000/600`，下行。

### 3.5 位置换算 `computer_distance(int diff, const struct hall_cali_data *c)` @0x8aa9ab0

```c
printk("…hall Cali_data position_0   up:%d, down:%d, up_down_diff: %d\n", c->p0.up, c->p0.down, c->p0.diff);  /* 同理 24/48/696/1 */
printk("…position diff is %d\n", diff);
if (c->all_time_at_52 == 0 || c->p0.diff == 0) { printk("damon hall sensor is not cali\n"); return -1; }
p0=c->p0.diff; p24=c->p24.diff; p48=c->p48.diff; p696=c->p696.diff; p1=c->p1.diff;
/* 上升段（p0 < p24）：diff 越大位置越大 */
/* 分段线性插值，锚点：p0→0, p24→3828, p48→7656, p696→11101, p1→15950 */
… 结果 clamp 到 [0,15950] …
printk("damon computer distance %d\n", res);
```
常量：`3828 = 0.24×15950`、`7656 = 0.48×15950`、`11101 = 0.696×15950`、`15950 = 全长`、段内斜率用 3445/4849 等。
标定结构 `g_hall_cali_data`（0x9f75610，56 字节，`.bss` 上电全 0，因此**未标定时所有位置类迁移都会被拒绝并打印 "damon hall sensor is not cali"**）：
```
struct hall_cali_data {
    /* +0  ~ +3  : 4 字节未知（本驱动不读） */
    struct { s16 up; s16 down; s32 diff; } p0;    /* +4,  +6,  +8  */
    struct { s16 up; s16 down; s32 diff; } p24;   /* +12, +14, +16 */
    struct { s16 up; s16 down; s32 diff; } p48;   /* +20, +22, +24 */
    struct { s16 up; s16 down; s32 diff; } p696;  /* +28, +30, +32 */
    struct { s16 up; s16 down; s32 diff; } p1;    /* +36, +38, +40 */
    /* +44 ~ +51: 未知 */
    int all_time;                                  /* +52，单位同 all_time（19200 基准的 ms） */
};   /* 56 字节 */
```
它由**用户态通过霍尔核心 misc 设备的 ioctl** 写入（`BBK_HALL_CORE_IOCTL_SET_CALI` 等，@0x8aae338 `bbk_hall_core_misc_dev_ioctl`，`copy_from_user(g_hall_cali_data, arg, 56)`），写入后调用 `set_vib_all_time(cali[52])` 同步全局 `all_time`。本驱动只读。

### 3.6 超时/重试/失败行为

- `retry_time`（0x9dccf78，默认 3；`vib_pwm_thread` 会设成 10）是**每段行程的 hrtimer 启动次数上限**，与 `h->move_count`（每启动一次 hrtimer 就 ++，见 §4）比较。
- `delay_func`（每段行程结束后 1 个 jiffy 执行）的重试判定：
```c
if (h->is_in_cali != 0 || bbk_hall_get_status() != 1) goto finish;
if ((h->camera_state & ~1) != 4) { vib_pwm_state_move_sate(-1, 0); goto finish; }   /* -1 = 空操作 */
switch (h->target_state) {
  case 0: if (h->move_count <  retry_time)      vib_pwm_state_move_sate(0, 0); break;
  case 1:
  case 2: if (h->move_count <= 2)               vib_pwm_state_move_sate(h->target_state, 0); break;
  case 7: if (h->move_count <= 1 || still_flag) vib_pwm_state_move_sate(7, 0); break;
  default: vib_pwm_state_move_sate(-1, 0); break;
}
   /* 若上面某次调用返回 1（已启动新一段）→ 直接 return，不动 camera_state */
finish:
  h->move_count = 0;
  if (target <= 2) { hall_init_move_queue(); hall_init_queue(); if (target==0 && !is_in_cali) bbk_hall_core_enable(0); }
  if (ws_active) __pm_relax(&h->ws);
  h->camera_state = h->target_state;              /* ← 到位确认 */
```
- 追加的"防夹/防强推"检查（`move_count == 3 && target == 2 && 霍尔有效`）：
  `if (up - down - g_hall_cali_data.p1.diff + 25 >= 51)` → 打印
  `"...damon enter handle input KEY_CAMERA_PRESS_MOVE & because: hall_up - hall_down < (cali_data.position1.hall_up_down_diff ± 25)"`，
  复位两个霍尔队列、放 wakelock、`vib_update_key(0x27E)` 并**直接返回（不把 camera_state 设成 target）**。
- 霍尔读失败：各函数打印 `damon %s bbk_hall_core_read_data failed` / `zyh7 damon %s …` / `zyha damon %s …` 并放弃该段。
- `clk_set_rate` 返回负：打印 `\0013%s can't set pwm_clk rate 10KHz ret=%d`，释放 wakelock，**不启动电机**。
- `clk` 获取失败：probe 里 `printk("\0013%s vib_pwm_data->pwm_clk is error")` 之后是 **`brk #0x800` + 死循环 = `BUG()`**（@0x8aacb08/0x8aacb0c），会 panic/挂死。

---

## 4. 电机如何真正被启动/停止

### 4.1 启动：`vib_pwm_set_camera_state(struct vib_pwm *h)` @0x8aaa470

```c
printk("\0016[LYQ-damon-vib]:%s enable %d, time %d,freq %lu\n",
       "vib_pwm_set_camera_state", h->enable, h->time, h->freq);
h->is_subsection = 0;  h->pre_time = 0;
if ((h->enable-1) <= 1 && h->time > 65536) {     /* enable∈{1,2} 且 time 很大 */
    h->is_subsection = 1;  h->pre_time = 50;
    printk("\0016[LYQ-damon-vib]:%s: set is_subsection = true, pre_time:%d, current freq: %lu, all_time:%d\n",
           __func__, 50, h->freq, h->time);
}
if (h->enable == 2)      goto start_down;
else if (h->enable == 1) goto start_up;
else {                                            /* enable 为 0/其它：刹车 */
    gpiod_direction_output_raw(gpio_to_desc(h->boost_gpio),  0);   /* 0x10 */
    msleep(5);
    gpiod_direction_output_raw(gpio_to_desc(h->enable_gpio), 1);   /* 0x14 */
    gpiod_direction_output_raw(gpio_to_desc(h->sleep_gpio),  0);   /* 0x18 */
    return;
}
```
正常启动（enable 1 或 2）：
```
1) if (!h->ws_active) __pm_stay_awake(&h->ws);                 /* 上 wakelock */
2) h->timer_ns = is_subsection ? 50ms_in_ns
                              : ns( (h->time*6/10) ms );       /* 见 4.3 */
3) clk_set_rate(h->pwm_clk /*gp2_clk*/, h->freq);
   if (ret < 0) { printk("\0013…can't set pwm_clk rate 10KHz ret=%d"); relax; return; }
4) bbk_hall_core_enable(0);                                    /* 停霍尔采样 */
5) clk_prepare(h->pwm_clk);                                    /* ← 不是 clk_prepare_enable */
6) GPIO 时序：
     enable==1: dir_gpio=0 ; boost_gpio=1 ; msleep(3) ; enable_gpio=0 ; sleep_gpio=1 ; msleep(3)
     enable==2: dir_gpio=1 ; boost_gpio=1 ; msleep(3) ; enable_gpio=0 ; sleep_gpio=1 ; msleep(3)
7) clk_enable(h->pwm_clk);                                     /* 时钟开始输出 → 电机转 */
8) h->sub_phase = 1;  h->move_count++;
9) hrtimer_start_range_ns(&h->hrtimer, h->timer_ns, 0, HRTIMER_MODE_REL_PINNED /*3*/);
10) bbk_hall_core_enable(1);                                   /* 开霍尔采样 */
11) h->is_move = 1;
```
**唯一的方向来源是 `dir_gpio`（0=正向/上行，1=反向/下行）**，`enable` 只是"用哪个 dir 值启动"的枚举。

### 4.2 停止

三条路径，GPIO 序列一致（`boost→0`，`msleep(5)`，`enable→1`，`sleep→0`），但动作范围不同：

1. **hrtimer 到期且不是分段预驱动**（`hrtimer_handler` @0x8aad430，`x19 = hrtimer - 0x118`）：
```c
if (h->is_subsection) {                      /* 0x168 */
    __wake_up(&h->wait_freq, 1, 1, NULL);    /* 唤醒 vib_freq_thread 起第二段 */
    printk("\0016[LYQ-damon-vib]:++++++++++++ %s: is_subsection = true & wait_up_interrupt to start next vib_freq\n", "hrtimer_handler");
    return HRTIMER_NORESTART;
}
printk("\0016[LYQ-damon-vib]:++++++++++++ %s: vib location is standby & Stop vib +++\n", "hrtimer_handler");
h->is_move = 0;
clk_disable(h->pwm_clk);
h->sub_phase = 0;
gpio(boost)=0; gpio(enable)=1; gpio(sleep)=0;         /* 无 msleep */
queue_delayed_work_on(WORK_CPU_UNBOUND(8), h->wq, &h->work, 1);   /* 1 jiffy 后 delay_func */
return HRTIMER_NORESTART;
```
2. **`vib_pwm_thread`（异常/急停流程）** @0x8aad118：
```c
for (;;) {
  wait_event_interruptible(h->wait, h->stop_flag /*0x218*/);      /* 手写 prepare_to_wait/schedule 循环 */
  printk("\0016[LYQ-damon-vib]:Enter %s: to Handle the Vib exception flow--------\n", …);
  h->is_move = 0;
  hrtimer_cancel(&h->hrtimer);
  cancel_delayed_work(&h->work); flush_delayed_work(&h->work);
  if (__clk_is_enabled(h->pwm_clk))   clk_disable(h->pwm_clk);
  if (__clk_is_prepared(h->pwm_clk))  clk_unprepare(h->pwm_clk);
  printk("damon flush delay work\n");
  gpio(boost)=0; msleep(5); gpio(enable)=1; gpio(sleep)=0;
  if (h->ws_active) __pm_relax(&h->ws);
  if (h->abort_flag /*0x219*/) {          /* cancel_vib_hrtimer(0) 设置的 */
      h->abort_flag=0; h->move_count=0; h->camera_state=6;      /* 异常态 */
      bbk_hall_core_enable(1);
      printk("\0016…---------only_stop_vib & not do anything, camera_state:6 ----");
  } else if (h->key_idle == 0 && (h->camera_state-1) <= 1) {     /* camera_state ∈ {1,2} */
      printk("damon enter vib_pwm_set_camera\n");
      h->key_idle = 1; bbk_hall_core_enable(0);
      vib_pwm_set_camera(0);                                    /* 自动回位 */
  } else {
      h->camera_state = 5; h->move_count = 0; retry_time = 10;
      if (bbk_hall_get_status()==1 && vib_pwm_state_move_sate(0, 1 /*notify*/)==0)
          h->camera_state = 0;
  }
  h->stop_flag = 0;
}
```
3. **`vib_pwm_enable_store` 写 0/其它**：只做 GPIO 刹车（不 cancel hrtimer、不关时钟），见 §2(4)。

`clk` 的成对关系：**`clk_prepare` + `clk_enable`** ↔ **`clk_disable` + `clk_unprepare`**，分别发生在
`set_camera_state`/`enable_store`（prepare+enable）→ `hrtimer_handler`（disable）→ `delay_func`（unprepare，**无条件下调用，@0x8aad6d0**）；
线程里的急停用 `__clk_is_enabled()`/`__clk_is_prepared()` 保护避免重复。
驱动**不使用** `clk_prepare_enable()`/`clk_disable_unprepare()`。

### 4.3 时间单位的换算（重要，很容易抄错）

- `h->time`、全局 `all_time`、`pre_time`、`retry` 都以**标称频率 19200 Hz 下的毫秒**为单位。
- `vib_pwm_enable_store`（直接 sysfs 启停）：
  `timer_ns = (time/1000)*1e9 + (time%1000)*1e6`（**不带任何缩放**）。
- `vib_pwm_set_camera_state`（非分段）：
  ```c
  h->time = h->time * 6 / 10;          /* = 19200/32000，因为此时 freq 被设为 32000 */
  h->timer_ns = (time/1000)*1e9 + (time%1000)*1e6;
  ```
  证据：`add w8,w8,w8,lsl#1`(=3x) + `lsl w8,w8,#1`(=6x) 之后用魔数 `0x66666667>>34`(=÷10) 与 `0x68DB8BAD>>44`(=÷10000)。
- `vib_pwm_set_camera_state`（分段 `is_subsection`）：`timer_ns = 50 ms`，**不改 `h->time`**。
- `vib_freq_thread`（第二段）：
  ```c
  h->freq = 41600;                                  /* 0xA280 */
  clk_set_rate(h->pwm_clk, h->freq);
  t = (h->time - h->pre_time) * 6 / 13;             /* = 19200/41600 */
  h->time = t;
  h->timer_ns = (t/1000)*1e9 + (t%1000)*1e6;
  hrtimer_start_range_ns(&h->hrtimer, h->timer_ns, 0, 3);
  h->is_subsection = 0;
  ```
  日志：`"%s: clk_set_rate=%lu is_subsection==true & Reset to false"`；`clk_set_rate` 失败则打印 `can't set pwm_clk rate…` 并清 `is_subsection`。
- 综合默认参数：启动一段正常行程 = **`time` ms（19200 基准）→ `0.6·time` ms 实际时长 @32000Hz**；若 `time > 65536` 则变成"前 50 ms @32000Hz + 剩余 `(time-50)*6/13` ms @41600Hz"。
- 速度档（`clk_set_rate` 的实参 `h->freq`）：默认 19200；`set_camera` 一律先置 **32000**；`(7,2)/(2,7)` 置 **4800**；第二段置 **41600**；`vib_pwm_freq` 属性可任意改。hrtimer 的"周期"就是每次行程的 `timer_ns`（单次、非周期；模式 `HRTIMER_MODE_REL_PINNED`）。

---

## 5. 霍尔位置获取与 `up_down_count`

### 5.1 调用的 bbk_hall 接口（同一内核镜像里的另一组函数）

| 函数 | 地址 | 语义 |
|---|---|---|
| `int bbk_hall_get_status(void)` | 0x8aadb38 | `return mhall_data->[160]`（0xA0）。**1 = 霍尔核心已 probe 成功**，其它值表示不可用 |
| `int bbk_hall_core_read_data(s16 *up, s16 *down)` | 0x8aad9a0 | 成功返回 **0** 并把**上行/下行霍尔原始读数**写入两个出参；失败返回 **-1**，并把两个出参填成 **-2000(0xF830)**。内部：状态 !=1 → 直接 -1；否则每轮对仍是 -2000 的那个通道调 `hall->ops->get_data()`，最多 **5 轮**，每轮失败 `msleep(1)`，全失败返回 -1 |
| `void bbk_hall_core_enable(int on)` | 0x8aadb48 | 原子地设置/清除核心使能位；0→1 时调两个霍尔设备的 `ops->enable(1)`、复位两个队列，并 `queue_delayed_work_on(8, system_wq, &core->work, 10)`；1→0 时 `cancel_delayed_work_sync` + `ops->enable(0)` + 复位队列。核心未就绪时全是空操作 |
| `void bbk_hall_core_init_queue(void)` | 0x8aad940 | 复位"上行霍尔数据队列"（用 10000 填满 + 计数清零） |
| `void bbk_hall_core_init_move_queue(void)` | 0x8aad970 | 复位"移动检测队列" |
| `void hall_clear_cali_data(void)` | 0x8aad908 | `memset(g_hall_cali_data,0,56); mhall_data->[36]=0;` |

本驱动**不直接读 I2C**：位置全部来自 `up - down` 再经 `computer_distance()` 映射到 0..15950（§3.5）。
注意 `up`/`down` 的取指针顺序：所有调用点都是 `bbk_hall_core_read_data(&第一个, &第二个)`，而 `up = (s16)first`、`down = (s16)second`（例：`is_top_or_bottom` 里 `w19 = (s16)[x29-12] - (s16)[x29-16]`）。

### 5.2 上游写入本驱动的方式（谁在什么时候调 `vib_update_key` / `cancel_vib_hrtimer`）

霍尔驱动（同文件的 `bbk_hal_work_func` @0x8aaea00 区域，`m1120_*`）在采样到"按压/强推"时：
- 普通按压（`queue_data_is_press`）：复位队列 → `vib_update_key(635)`（KEY_CAMERA）；
- 运动中强推（`queue_data_is_move_strong_press`，连续计数 ≥14，`count_press_in_move`）：复位队列 →
  - 状态 4/5 的"WARNING"分支 → **`cancel_vib_hrtimer(1)`**（只停电机，保留 `camera_state`）；
  - 达到 ERROR 阈值分支 → **`cancel_vib_hrtimer(0)`**（停电机并把 `camera_state` 置 6，进入异常态）。
- `cancel_vib_hrtimer(int arg)` @0x8aa98d8：
```c
h = vib_pwm_data;
if (arg == 0) h->abort_flag = 1;    /* 0x219 */
h->stop_flag = 1;                   /* 0x218 → 唤醒 vib_pwm_thread */
bbk_hall_core_init_move_queue(); bbk_hall_core_init_queue();
__wake_up(&h->wait, 1, 1, NULL);
return 0;
```
- 霍尔驱动还会调用 `get_camera_state()`（判断当前状态 4/5/6）、`vib_is_in_cali()`、`vib_update_key()`。

### 5.3 `vib_pwm_up_down_count` 的维护

- 结构体 `up_down_count`(+0x2A0) 与 `all_count`(+0x2A4)。
- **唯一自增点**：`vib_pwm_set_camera()` 里 `(目标, 当前==0)` 的迁移（即"从收起位出发"），两者**同时 +1**，随后 `h->up_down_flag = enable(1或2)` 并唤醒保存线程（`wait_up_down_count`）。
- 保存线程 `vib_pwm_up_down_count_thread` @0x8aad308：
```c
for (;;) {
  wait_event_interruptible(h->wait_up_down_count, h->up_down_flag);
  snprintf(buf, 49, "%u-%u", h->up_down_count, h->all_count);   /* fmt @0x99b0503 */
  f = filp_open("/mnt/vendor/persist/sensors/up_down_count", O_RDWR|O_CREAT|O_TRUNC(0x242), 0600);
  if (IS_ERR(f)) { printk("damon save up_down_count file %s failed\n", path); h->up_down_flag=0; continue; }
  n = __kernel_write(f, buf, len, &f->f_pos);
  if (n < 0) printk("write up_down_count failed ret %ld\n", n);
  else       printk("damon up_down_count %u,all count:%d\n", h->up_down_count, h->all_count);
  filp_close(f, NULL);
  h->up_down_flag = 0;
}
```
- 恢复：霍尔核心 misc ioctl（@0x8aae808 分支）读同一个文件、`sscanf(buf,"%u-%u",…)`，然后调用**导出函数** `set_vib_up_down_count(int up, int down)` @0x8aa9980 → `h->up_down_count = up; h->all_count = down;`。
- `vib_pwm_up_down_count_store` 只写 `up_down_count`（不动 `all_count`）并立刻触发一次保存。
- 相关导出函数 `set_vib_all_time(int t)` @0x8aa9970 → `all_time = t;`（霍尔核心在标定写入后调用）。

---

## 6. probe / DT / pinctrl / 设备注册 / 模块参数

### 6.1 `vib_pwm_probe(struct platform_device *pdev)` @0x8aac658

```c
np   = pdev->dev.of_node;                 /* [pdev+656] */
dev  = &pdev->dev;
printk("\0016[LYQ-damon-vib]:Enter %s\n", "vib_pwm_probe");
h = devm_kmalloc(dev, 680, GFP_KERNEL);   /* 非 kzalloc！ */
vib_pwm_data = h;
if (!h) return -ENOMEM;                   /* -12 */
h->pdev = pdev; h->dev = dev;  pdev->dev.driver_data = h;

/* --- 5 个 GPIO：of_get_named_gpio_flags(np, name, 0 /*index*/, NULL /*flags*/) ---
   GPIO flags 数组传 NULL，所以 cell 里的 flag 被忽略，极性完全由驱动自行处理 */
h->sleep_gpio  = of_get_named_gpio_flags(np, "sleep-gpio",  0, NULL);  /* -> [h+0x18] */
h->enable_gpio = of_get_named_gpio_flags(np, "enable-gpio", 0, NULL);  /* -> [h+0x14] */
h->dir_gpio    = of_get_named_gpio_flags(np, "dir-gpio",    0, NULL);  /* -> [h+0x1C] */
h->boost_gpio  = of_get_named_gpio_flags(np, "boost-gpio",  0, NULL);  /* -> [h+0x10] */
h->id_gpio     = of_get_named_gpio_flags(np, "id-gpio",     0, NULL);  /* -> [h+0x20] */

/* 每个 gpio 若 <= 0x4FF(1279) 认为是有效编号，则申请并设初值： */
if (h->boost_gpio  <= 1279) { gpio_request(h->boost_gpio,  "boost_gpio");  gpiod_direction_output_raw(desc, 0); dev_info("Success request boost-gpio"); }
if (h->id_gpio     <= 1279) { gpio_request(h->id_gpio,     "id_gpio");     gpiod_direction_input(desc);         dev_info("Success request boost-gpio"); /* 文案错误 */ }
if (h->enable_gpio <= 1279) { gpio_request(h->enable_gpio, "enable_gpio"); gpiod_direction_output_raw(desc, 1); dev_info("Success request enable-gpio"); }
if (h->sleep_gpio  <= 1279) { gpio_request(h->sleep_gpio,  "sleep_gpio");  gpiod_direction_output_raw(desc, 0); dev_info("Success request sleep-gpio"); }
if (h->dir_gpio    <= 1279) { gpio_request(h->dir_gpio,    "dir_gpio");    gpiod_direction_output_raw(desc, 1); dev_info("Success request dir-gpio"); }
/* 失败: dev_err("Failed to request xxx GPIO:%d, ERRNO:%d") 后返回 -ENODEV(-19) */

/* --- pinctrl（若 of_node 为空则跳过整段） --- */
h->pinctrl      = devm_pinctrl_get(dev);
h->pins_active  = pinctrl_lookup_state(h->pinctrl, "vib_pwm_active");    /* [h+0x30] */
h->pins_suspend = pinctrl_lookup_state(h->pinctrl, "vib_pwm_suspend");   /* [h+0x38] 只查不用 */
h->pins_idconfig= pinctrl_lookup_state(h->pinctrl, "vib_pwm_idconfig");  /* [h+0x40] */
pinctrl_select_state(h->pinctrl, h->pins_active);
pinctrl_select_state(h->pinctrl, h->pins_idconfig);     /* 注意是 idconfig，不是 suspend */
/* 任一步失败: devm_pinctrl_put + 返回 -EINVAL(-22) */

/* --- 时钟：没有 PWM phandle，用的是通用时钟 --- */
h->pwm_clk = devm_clk_get(dev, "gp2_clk");     /* DT: clocks=<&gcc GCC_GP2_CLK>, clock-names="gp2_clk" */
if (IS_ERR(h->pwm_clk)) { printk("\0013%s vib_pwm_data->pwm_clk is error"); BUG(); }   /* brk #0x800 */

/* --- 默认值 --- */
h->count=0; h->camera_state=0; h->is_move=0; h->freq=19200; h->pending_notify=0;
h->elevator_mode=0; h->stop_flag=h->abort_flag=0; h->up_down_flag=0;
h->move_count=h->sub_phase=0; h->time=all_time(2839); h->is_in_cali=0;
h->up_down_count=0; h->key_idle=1;

/* --- input 设备 --- */
vib_input_dev = input_allocate_device();
dev->name = "h110-vib-input";  dev->phys = "h110-vib/input0";
dev->id = { .bustype = 0x19 /*BUS_HOST*/, .vendor = 1, .product = 1, .version = 0x0100 };
dev->dev.parent = &pdev->dev;
__set_bit(EV_KEY, dev->evbit);        /* set_bit(1, dev+0x28) */
for (k = 635..646) __set_bit(k, dev->keybit);   /* dev+0x30 */
*(u64*)(dev+0x28) = 0x00100002;       /* evbit[0] = BIT(1)|BIT(20)：EV_KEY + bit20 */
input_register_device(dev);           /* 失败 → return w20 */
wakeup_source_prepare(&h->ws, "vib_wake_lock");  wakeup_source_add(&h->ws);
__init_waitqueue_head(&h->wait, "&vib_pwm_data->wait", &key1);
__init_waitqueue_head(&h->wait_up_down_count, "&vib_pwm_data->wait_up_down_count", &key2);
kthread_create_on_node(vib_pwm_thread, h, -1, "vib_pwm_thread");  wake_up_process(...);  h->thread = t;
kthread_create_on_node(vib_pwm_up_down_count_thread, h, -1, "vib_pwm_up_down_count_thread"); wake_up_process(...); h->up_down_thread = t;
hrtimer_init(&h->hrtimer, CLOCK_MONOTONIC, HRTIMER_MODE_REL_PINNED);
h->hrtimer.function = hrtimer_handler;      /* str x9,[h+0x140] */
__init_waitqueue_head(&h->wait_freq, "&vib_pwm_data->wait_freq", &key3);
kthread_create_on_node(vib_freq_thread, h, -1, "vib_freq_thread"); wake_up_process(...); h->freq_thread = t;
h->is_subsection = 0;
printk("\0016%s num=%d\n", "bbk_device_create_attr", 15);
/* 依次 device_create_file 创建 15 个属性（顺序见 §2），失败打印 "device_create_file (%s) = %d" 但继续 */
h->wq = alloc_workqueue("%s", WQ_UNBOUND|WQ_MEM_RECLAIM|(0xE<<16) /*flags=0x000E000A*/, 1, NULL, "vib_wq");
if (!h->wq) { printk("\0013%s failed to create fts workqueue"); return 0; }
INIT_WORK(&h->work, delay_func);
setup_timer(&h->work.timer /*h+0x260*/, delayed_work_timer_fn, &h->work);   /* flags=TIMER_IRQSAFE */
return 0;
```
`vib_pwm_remove` 只做 `wakeup_source_remove/drop(&h->ws)`；`shutdown`/`suspend`/`resume` 只打印 `damon %s` 并返回 0（**没有任何关电机动作**）。

平台设备来源：
- `vib_pwm_mod_init` @0x9be1c20（`__initcall_vib_pwm_mod_init6` @0x9c64a98）只做 `platform_driver_register(&vib_pwm_pdrv)`，失败打印 `%s error`；
- 设备来自 DT（`compatible="bbk,vib_pwm_control"`）。
- 同一编译单元里还有一个 `platform_add_devices(bbk_devices, 1)` + `platform_driver_register(&bbk_hall_core_driver)`（@0x8aae1bc，设备名 `bbk_hall_core`），负责创建霍尔核心平台设备；**它不创建 vib_pwm 设备**。

### 6.2 模块参数（`module_param`，权限一律 **0664**，类型 `int`，`level=-1`）

`struct kernel_param` 位于 0x9b7b880 起、每个 0x28 字节；`+0x10 = param_ops_int(0xffffff80092085a8)`，`+0x18 = 0x00ff01b4`（perm=0x1B4=0664, level=-1, flags=0），`+0x20` = 变量地址。

| 参数名（前缀=模块名） | 变量 | 默认值 | 含义（推断） |
|---|---|---|---|
| `gpio_pwm.mhall_control_up` | `mhall_fake_data_up` @0x9f755d8 | **0** | 状态机 case 7 的"上行死区"阈值 |
| `gpio_pwm.mhall_control_down` | `mhall_fake_data_down` @0x9f755dc | **0** | case 7 下行死区阈值 / `row_shift_show` 阈值 |
| `gpio_pwm.mhall_control2` | `mhall_fake_data2` @0x9f755e0 | **0** | `(7,2)/(2,7)` 迁移的时间修正项（默认 0 ⇒ 修正为 0） |
| `gpio_pwm.mhall_control3` | `mhall_fake_data3` @0x9f755e4 | **0** | case 7 的"holder 位目标霍尔读数" |
| `gpio_pwm.mhall_control4` | `mhall_fake_data4` @0x9dccf68 | **1000** | case 7 时间系数：`time = Δ*fake4*10/6000 = Δ*fake4/600`（ms 每 600 霍尔单位） |
| `gpio_pwm.mhall_control5` | `mhall_fake_data_re` @0x9dccf6c | **3** | `(7,x)`/`(x,7)` 迁移写的 `retry_time` |
| `gpio_pwm.mhall_control6` | `mhall_fake_data_add_time` @0x9dccf70 | **20** | `(2,7)` 迁移的时间 `(add_time+fake2)*10/6` |
| `gpio_pwm.mhall_control7` | `all_time` @0x9dccf74 | **2839** | 满行程默认时间（19200Hz 基准的 ms）；`set_vib_all_time()` 也写它 |
| `bbk_hall_queue.mhall_control_press` | `mhall_press` @0x9dcd990 | **8** | 属于霍尔队列那个编译单元（模块名不同），本驱动不用 |

（sysfs 路径形如 `/sys/module/gpio_pwm/parameters/mhall_control_up`。）

---

## 7. 重写时必须踩对的坑（写错就不工作）

1. **时钟不是 PWM**：`gp2_clk`（`clocks=<&gcc …GP2_CLK>`, `clock-names="gp2_clk"`）直接作为电机驱动频率；`clk_set_rate` 的实参是 `h->freq`（19200/32000/41600/4800）。没有 `pwm` phandle，不能按标准 pwm 驱动写。
2. **`devm_clk_get` 失败 = `BUG()`**（`brk #0x800` + 死循环，@0x8aacb08）。DT 里 clock 必须存在且名字必须是 `gp2_clk`。
3. **GPIO 电平语义**（DT cell 里的 flag 被 `of_get_named_gpio_flags(..., NULL)` 丢弃，全靠代码）：
   - `boost_gpio`(tlmm 0x18)：驱动时 **1**，空闲 **0**；
   - `enable_gpio`(tlmm 0x17)：**低有效**，驱动 **0**、停止 **1**；
   - `sleep_gpio`(tlmm 0x1d)：驱动（唤醒）**1**、停止（睡眠）**0**；
   - `dir_gpio`(tlmm 0x1a)：**0 = 上行(enable=1)，1 = 下行(enable=2)**；
   - `id_gpio`(tlmm 0x19)：输入，用于板型识别（`vib_id`）。
   顺序也很关键：启动 `dir → boost=1 → msleep(3) → enable=0 → sleep=1 → msleep(3) → clk_enable`；停止 `boost=0 → msleep(5) → enable=1 → sleep=0`（停止时**不动 dir**）。
4. **`msleep` 常量**：启动 3 ms + 3 ms；刹车 5 ms；`state_init` 前 10 ms；霍尔重试 1 ms×5；`top_or_bottom` 无延时。
5. **时间基准换算**：`all_time`/`time` 以 19200 Hz 为基准；主驱动段乘 **6/10**（19200/32000），第二段乘 **6/13**（19200/41600）；但 `vib_pwm_enable` 直接写 `enable/time` 启停时**不乘**（按纯 ms 处理）。抄错会导致行程时间差 1.67×或 2.17×。
6. **两段驱动**：`time > 65536` 时先 50 ms（`pre_time`）@32000Hz，hrtimer 到期唤醒 `vib_freq_thread` 改到 41600Hz 再跑 `(time-50)*6/13` ms。少了这一段，长行程电机可能起不来/失步。
7. **hrtimer 用 `HRTIMER_MODE_REL_PINNED`(3)**，句柄回调 `hrtimer_handler` 在非分段到期时只做"停电机 + `queue_delayed_work(1 jiffy)`"，真正的收尾（`clk_unprepare`、重试判定、把 `camera_state = target_state`）在 `delay_func`（work）里，**两者缺一不可**。
8. **收尾时 `camera_state := target_state`**：`camera_state` 4/5 只是"运动中"标记，框架读到的最终状态由 `delay_func` 落定。若重写漏掉这一步，`vib_pwm_camera_state` 会永远停在 4/5，`vib_pwm_set_camera` 会因 `(cur&~1)==4` 而**永久拒绝新命令**。
9. **霍尔依赖**：所有位置类修正都需要 `bbk_hall_get_status()==1` **且** `g_hall_cali_data` 已标定（`p0.diff != 0 && cali[52] != 0`），否则 `computer_distance` 返回 -1 → 打印 "damon hall sensor is not cali" → 迁移被放弃。标定数据由**用户态 ioctl** 写入霍尔核心 misc 设备，不在本驱动里。
10. **位置量纲 15950 与 0.696 锚点**硬编码：`0% / 24% / 48% / 69.6% / 100%` ↔ `0/3828/7656/11101/15950`，段内线性插值；`all_time*696/1000` 直接出现在迁移时间公式里。标定值与这些常数必须匹配，否则电机永远"到不了位"而反复重试（`retry_time` 次）。
11. **input 子系统是 ABI**：设备名 `h110-vib-input`、phys `h110-vib/input0`、bustype 0x19、按键 **635..646**、每个 key 都是"按下+SYN、抬起+SYN"两帧。Android framework 依赖这些键（`KEY_CAMERA` 等）驱动 UI；漏掉就会"相机弹不出来/界面不响应"。
12. **`abort_notify` 的字符串协议是 ABI**（`"0x27c"/"636"/"0x27d"/"637"/"0x27f"/"639"/"0x280"/"640"/"0x282"/"642"/"0x283"/"643"/"0x284"/"644"/"username:"/"stream on"/"stream off"/"888"/"666"/"com.eebbk.askhomework"`），framework 用它做"流开关/用户名/强制重启升降台"。语义表见 §2(9)。
13. **模块参数名与默认值**：`gpio_pwm.mhall_control1..7` 对应 `mhall_fake_data_up/down/2/3/4/re/add_time` 与 `all_time`；`all_time` 默认 2839、`fake_data4` 默认 1000、`add_time` 默认 20、`retry` 默认 3。改了名字/默认值，或改了 `all_time`/`6/10`/`6/13` 的乘法关系，会导致与原厂标定数据不兼容（出厂标定表是按这些常数生成的）。
14. **`vib_pwm_time` 写 1300 是特例**：`h->time = all_time + 10`，不是 1300。
15. **未初始化字段**（`enable`/`target_state`/`holder_mode`/`all_count`/`notify_str`，因为用了 `devm_kmalloc` 而非 `kzalloc`）：重写请清零；其中 `enable` 若残留 1/2，某些路径会意外驱动电机。
16. **无任何锁**：sysfs handler、3 个 kthread、hrtimer、workqueue 之间共享 `h`，只有 `stop_flag/up_down_flag/is_subsection` 之类的 `u8` 标志 + `wake_up`。原厂如此，重写建议加 mutex 并注意不要破坏 `delay_func → camera_state = target` 的时序。
17. **pinctrl 三个状态名固定**：`vib_pwm_active` / `vib_pwm_suspend` / `vib_pwm_idconfig`；probe 依次 select **active 然后 idconfig**（suspend 只 lookup）；注册/唤醒/睡眠回调里**不切换 pinctrl**。
18. **属性 ABI**：15 个名字 + 模式（只有 `vib_pwm_id` 是 0444，其余 0664）+ 打印格式（`vib_id=%d\n`、`vib_freq=%d\n`、`count=%d\n`、`enable=%d\n`、`dir=%d\n`、`time=%d all_time=%d`、camera_state/state_init/holder_mode/elevator_mode/cali 都是 `%d`、`elevator_row_shift` 是 `%d %d %d %d %d %d %d %d`、`up_down_count` 是 `%u\n`、`clear_cali_data` 是常量 `clear`）。产线测试脚本会按这些格式解析。
19. **`vib_pwm_up_down_count` 的持久化路径**：`/mnt/vendor/persist/sensors/up_down_count`（`O_RDWR|O_CREAT|O_TRUNC`，0600，内容 `"<up>-<all>"`），恢复由霍尔核心 ioctl 完成。若重写要保留"行程计数"功能，必须同时实现写入端和读取端。
20. **`vib_pwm_count`、`h->sub_phase`、`retry_time` 的初值**等看起来"没用"的字段也最好原样保留（`sub_phase` 有 hrtimer 侧清零，`count` 纯废字段）。

---

## 8. 不确定项 / 存疑（明确列出证据）

1. **`h->time` 的物理单位**：我只能确定"换算关系"，不能确定厂商原始单位。
   证据：`set_camera_state` 里 `time*6/10`（0xaaa5b8~0xaaa5f0）；`vib_freq_thread` 里 `(time-pre_time)*6/13`（0xaad574~0xaad5a8）；`6/10 = 19200/32000`、`6/13 = 19200/41600`（19200 正是 probe 默认 `freq`、32000/41600 是运行时设置值）。因此"`all_time` 以 19200Hz 为基准的 ms"是最自洽的解释，但厂商也可能只是拍了两个魔数。
2. **`(7,1)/(1,7)` 里的"负魔数"**：编译产物是 `X*15 * 0xAE147AE1 >> 37`，而 `0xAE147AE1 = -0x51EB851F`，即 GCC 为 `(X*15) / -100` 生成的负魔数（`X = mhall_fake_data2*10/6`）。所以两条迁移的时间都是 `基准 - (fake2*10/6)*15/100`（默认 fake2=0 ⇒ 修正为 0）。这是我从 ±魔数对偶推出来的，正确性高，但如果厂商源码用的是别的写法（例如 `(s64)(-100)` 之外的表达式）语义可能略有差别。
3. **`elevator_row_shift_show` 的"行号"分段**：编译出来的分支树里夹杂了 `c8/c16/c24/c32` 与 `m0/m1/m2` 的交叉比较（0x8aac2bc~0x8aac348），我把它化简成 `m0/m1/m2` 阶梯。该属性只读、只用于产线自检，若需要 100% 复刻建议直接照抄反汇编分支；其 8 个输出含义（行号、`adjust_flag`、以及 4 个阈值比较、`|up|`、`|up|-thr`）是确定的。
4. **状态 1/7 的物理位置**：`1 = 69.6%`（`all_time*696/1000`、`11101/15950`、标定点 `position_696` 三重证据，很确定）；`7` 位于 1 与 2 之间，具体百分比我**无法从代码唯一确定**（`(7,1)` 上行、`(7,2)` 下行只能证明排序 1<7<2，且 `(7,x)` 的时间里 `all_time` 部分恰为 30.4%，说明 7 距 2 很近、修正项由 `mhall_fake_data2` 决定）。
5. **`mhall_fake_data5` 的语义**：只在 `state_move_sate` case 2 里作除数（`time = fake5*Δ/1000`），默认 0 ⇒ 该分支默认不可达。它没有对应的 `mhall_control*` 参数（参数表里 6/7 号是 `add_time` 和 `all_time`），所以它是"由 `init_hall_data_fake` 从霍尔标定结构注入"的量（`g_mhall_cali_data+44` 之外没有写入点）——**我找不到默认非零的来源**，判定为默认路径不走它。
6. **`h->count`(0x198)**：除 show/store 外无任何读点，判定为遗留废字段（grep `#408` 已验证）。
7. **模块名**：参数名前缀是 `gpio_pwm.`，因此内建模块名（`KBUILD_MODNAME`）应为 `gpio_pwm`，sysfs 在 `/sys/module/gpio_pwm/parameters/`。若内核实际以其它名字注册内建模块参数，路径名可能不同（参数名前缀是实测的，不会变）。
8. **`vib_pwm_elevator_row_shift` 的"无 store"**：dev_attr 里 store 指针为 0（@0x9dcd0f0 8 字节全 0），确认只读。

---

## 9. 相关地址速查

```
# 驱动函数
init_hall_data_fake        0xffffff8008aa9710   (导出，霍尔核心注入假数据)
vib_update_key             0xffffff8008aa9790   (导出)
cancel_vib_hrtimer         0xffffff8008aa98d8   (导出)
get_camera_state           0xffffff8008aa9930   (导出)
vib_is_in_cali             0xffffff8008aa9950   (导出)
vib_is_move                0xffffff8008aa9960   (导出)
set_vib_all_time           0xffffff8008aa9970   (导出)
set_vib_up_down_count      0xffffff8008aa9980   (导出)
is_top_or_bottom           0xffffff8008aa9998
computer_distance          0xffffff8008aa9ab0
vib_pwm_state_move_sate    0xffffff8008aa9d38   (导出)
vib_pwm_set_camera_state   0xffffff8008aaa470
vib_pwm_set_camera         0xffffff8008aaa7e0   (导出)
vib_pwm_id_show            0xffffff8008aab128
vib_pwm_frequency_show     0xffffff8008aab198  / _store 0xffffff8008aab1c8
vib_pwm_count_show         0xffffff8008aab248  / _store 0xffffff8008aab278
vib_pwm_enable_show        0xffffff8008aab2f8  / _store 0xffffff8008aab328
vib_pwm_dir_show           0xffffff8008aab5e0  / _store 0xffffff8008aab628
vib_pwm_time_show          0xffffff8008aab670  / _store 0xffffff8008aab6a8
vib_pwm_camera_state_show  0xffffff8008aab760  / _store 0xffffff8008aab790
vib_pwm_state_init_show    0xffffff8008aab840  / _store 0xffffff8008aab870
vib_pwm_abort_notify_show  0xffffff8008aab928  / _store 0xffffff8008aab958
vib_pwm_holder_mode_show   0xffffff8008aabeb0  / _store 0xffffff8008aabee0
vib_pwm_elevator_mode_show 0xffffff8008aabff8  / _store 0xffffff8008aac038
vib_pwm_elevator_row_shift_show 0xffffff8008aac1a8  (无 store)
vib_pwm_cali_show          0xffffff8008aac3f0  / _store 0xffffff8008aac428
vib_pwm_up_down_count_show 0xffffff8008aac4d0  / _store 0xffffff8008aac508
vib_pwm_clear_cali_data_show 0xffffff8008aac5b0 / _store 0xffffff8008aac5d8
vib_pwm_probe              0xffffff8008aac658
vib_pwm_remove             0xffffff8008aad068 / shutdown 0x8aad0a0 / suspend 0x8aad0c8 / resume 0x8aad0f0
vib_pwm_thread             0xffffff8008aad118
vib_pwm_up_down_count_thread 0xffffff8008aad308
hrtimer_handler            0xffffff8008aad430
vib_freq_thread            0xffffff8008aad4f0
delay_func                 0xffffff8008aad688
# 霍尔侧（同文件家族）
hall_clear_cali_data       0xffffff8008aad908
bbk_hall_core_init_queue   0xffffff8008aad940
bbk_hall_core_init_move_queue 0xffffff8008aad970
bbk_hall_core_read_data    0xffffff8008aad9a0
bbk_hall_get_status        0xffffff8008aadb38
bbk_hall_core_enable       0xffffff8008aadb48
bbk_hall_core_register_device 0xffffff8008aae0c0
bbk_hall_core_misc_dev_ioctl 0xffffff8008aae338
bbk_hal_work_func          0xffffff8008aaea00
init_hall_queue_array      0xffffff8008aaf0d8
m1120_i2c_drv_probe        0xffffff8008aaf868
# 跳转表
vib_update_key 跳转表      0xffffff80095f10d0 (8 字节: 00 16 1a 00 1e 22 2d 33)
state_move 跳转表          0xffffff80095f10d6 (8 字节: 2d 33 4b 00 00 00 00 85)
abort_notify 跳转表 A      0xffffff80095f10e5 (7 字节: 2e 00 2b 00 2b 2f 2d)
abort_notify 跳转表 B      0xffffff80095f10de (7 字节: 1a 00 17 00 17 1b 19)
# 模块参数
__param_mhall_control_up…  0xffffff8009b7b880 ~ 0xffffff8009b7b9c0 (每个 0x28)
param_ops_int              0xffffff80092085a8
```
