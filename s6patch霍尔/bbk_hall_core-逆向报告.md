# EEBBK S6 `bbk_hall_core` 逆向报告（工厂内核 vmlinux-to-elf 符号化分析）

分析对象：`/root/factory_vmlinux.elf`（AArch64，符号地址 = 内核链接地址，~115367 符号）
方法：`aarch64-linux-gnu-nm` 定位 + `objdump -d/-s` 反汇编 + 自写 adrp/add 解析器做交叉引用（脚本见 `/mnt/e/s6ke/work/sh/`，中间产物见 `/mnt/e/s6ke/work/hall2/`）。
所有结论都给出地址；无法确证的地方在文末第 8 节明确标注。

**最关键的三个硬事实（写错就会破坏用户态）**
1. misc 设备名 = `bbk_hall_core` → 节点 `/dev/bbk_hall_core`（字符串 `0xffffff80099f8a58`）。
2. ioctl 命令基址 = `0x40046000`，仅 4 条：`0x40046000`/`0001`/`0002`/`0003`（`sub_ioctl` 里 `w8 = cmd + 0xbffba000; cmp w8, #3; b.hi → -ENOTTY`，@`0x8aae358-0x8aae37c`，跳转表 `0xffffff80095f11b2` = `00 11 48 57`，相对 `0x8aae39c`×4）。
3. 标定文件是**裸二进制、无 magic、无校验和**：`cali_hall` 恰好 56 字节、`cali_mhall_final` 恰好 48 字节；字段偏移见第 3 节。多写/少写一个字节都会让 `hall_up_down_diff` 错位，马达行程计算全错。

---

## 1. 给传感器驱动用的导出 API

模块所在代码区：`0xffffff8008aa9000 – 0xffffff8008ab8000`（同一批 `drivers/input/hall/...` 目标文件），initcall 在 `0xffffff8009be1c90`。

### 1.1 导出符号（`nm` 中 `T`）

| 符号 | 地址 | 推断原型 | 说明 |
|---|---|---|---|
| `bbk_hall_core_register_device` | `0x8aae0c0` | `int bbk_hall_core_register_device(struct hall_dev *dev)` | 传感器注册入口，**永远返回 0** |
| `bbk_hall_core_read_data` | `0x8aad9a0` | `int bbk_hall_core_read_data(s16 *hall_up, s16 *hall_down)` | 读一次上下 hall 值；成功 0，失败 -1 |
| `bbk_hall_core_enable` | `0x8aadb48` | `int bbk_hall_core_enable(int on)` | 开关采集 + 启动/停止 50ms 周期工作，返回 0 |
| `bbk_hall_get_status` | `0x8aadb38` | `int bbk_hall_get_status(void)` | 返回 `mhall_data->inited`（**不是** enable 状态） |
| `bbk_hall_core_set_delay` | `0x8aadcb8` | `int bbk_hall_core_set_delay(int ms)` | `delay = max(ms,20)`，返回 0 |
| `bbk_hall_core_init_queue` | `0x8aad940` | `void bbk_hall_core_init_queue(void)` | 清 hall 队列（size=10） |
| `bbk_hall_core_init_move_queue` | `0x8aad970` | `void bbk_hall_core_init_move_queue(void)` | 清 move 队列（size=5） |
| `hall_clear_cali_data` | `0x8aad908` | `int hall_clear_cali_data(void)` | `memset(g_hall_cali_data,0,56); mhall_data->cali_valid=0;` 返回 0 |
| `init_hall_queue_array` | `0x8aaf0d8` | `int init_hall_queue_array(struct hall_queue *q)` | 全部填哨兵 10000，返回 0 |
| `init_hall_queue` | `0x8aaf130` | `struct hall_queue *init_hall_queue(int n)` | `kmalloc(32)` + 两个 `n` 个 int 的数组 |
| `in_hall_queue` | `0x8aaf210` | `void in_hall_queue(struct hall_queue*,int up,int down)` | 环形写入 |
| `out_hall_queue_up` | `0x8aaf240` | `int out_hall_queue_up(struct hall_queue*,int off)` | `up[(index+off)%size]` |
| `out_hall_queue_down` | `0x8aaf260` | `int out_hall_queue_down(struct hall_queue*,int off)` | 同上，down 数组 |
| `hall_queue_is_inited` | `0x8aaf280` | `int hall_queue_is_inited(struct hall_queue*)` | 有任一元素==10000 则 0 |
| `queue_data_is_move_press` | `0x8aaf2d8` | `int queue_data_is_move_press(struct hall_queue*)` | 见第 6 节 |
| `queue_data_is_move_strong_press` | `0x8aaf3f8` | `int queue_data_is_move_strong_press(struct hall_queue*,int state,int polarity)` | 见第 6 节 |
| `queue_data_is_press` | `0x8aaf550` | `int queue_data_is_press(struct hall_queue*)` | 见第 6 节，阈值变量 `mhall_press`=8 |
| `queue_data_print` | `0x8aaf6a0` | `void queue_data_print(struct hall_queue*)` | 打印两条队列 |
| `dhall_register_hall` | `0x8ab3c18` | `int dhall_register_hall(char *name, void *dev, void *ops)` | 另一个（更老的）hall 框架，只给 ist8801 用 |
| `dhall_unregister_hall` | `0x8ab42c8` | `int dhall_unregister_hall(char *name)` | |
| `dhall_irq_handler` | `0x8ab43b0` | `irqreturn_t dhall_irq_handler(int irq, void *dev)` | |

导出**数据**对象（`T`，vib_pwm 直接读写）：`mhall_data`(`0x9f75608`)、`g_hall_cali_data`(`0x9f75610`)、`g_mhall_cali_data`(`0x9f75648`)、`camera_mhall`(`0x9f75678`)、`mhall_fake_data_up/down/2/3/4/5/re/add_time`、`vib_pwm_data`(`0x9f755f0`)。

### 1.2 `bbk_hall_core_register_device` 的参数结构（重点）

从 `ist8801_i2c_probe`（`0x8ab63b0-0x8ab6404`）与两个 `m1120_i2c_drv_probe`（`0x8ab009c-0x8ab00d0`、`0x8ab2b64-0x8ab2b98`）可 100% 复原：

```c
struct hall_ops {                        /* 各传感器文件里的静态表(ist8801 在 0x9dce330,
                                            m1120-down 0x9dcdb40, m1120-up 0x9dcdd38) */
    int (*get_data)(void *data, s16 *value);   /* +0x00 */
    int (*set_enable)(void *data, int on);     /* +0x08 */
    /* +0x10 之后是驱动自己的 dev_attr 指针等，核心不碰 */
};

struct hall_dev {                        /* 传感器 kmalloc(40, GFP_KERNEL) 自己分配 */
    char        name[24];        /* +0x00  必须以 "up"/"down" 开头 */
    struct hall_ops *ops;        /* +0x18  str x8,[x19,#24] */
    void        *data;           /* +0x20  调用 ops 时的第一个参数 */
};
```

- 核心用 `strncmp(dev, "up", 2)` / `strncmp(dev, "down", 4)` 判断（字面量因字符串后缀合并落在 `0xffffff80099c499e`（"scaled up" 的尾巴）和 `0xffffff80099cccf2`（"a down" 的尾巴），见 `0x8aae0f4-0x8aae16c`）。也就是说**注册对象的头几个字节必须是字符串本体**，不是 `char *`。
- 核心把**指针本身**存进 `mhall_data->hall_up(+0x00)` / `hall_down(+0x08)`，并用 `%s` 打印（`bbk_hall_vendor`），所以该结构体必须**永久有效**（工厂代码从不释放它）。
- 调用约定：`0x8aada40-0x8aada54` 是 `w8 = mhall_data->hall_up; ldp x9,x0,[x8,#24]` → `x9 = ops, x0 = data`，`ldr x8,[x9]` → `ops->get_data(data, &val)`；enable 用 `ldr x8,[x9,#8]` → `ops->set_enable(data, on)`。
  注意：工厂的 m1120 侧 `hall_getdata(void)`（`0x8ab1a40`）是**无参函数**（忽略 `data`，直接读全局 `p_m1120_data_up`），`data` 字段没赋值；ist8801 侧（`0x8ab6fb0`）则是正规矩的 `(data, value)`。重写时按 ist8801 的签名实现即可。
- 当 up 和 down **都**注册好了，用 `mhall_data+0x18`（初值 1）做一次性 `cmpxchg(1→0)` 守卫，然后：
  `platform_add_devices(&bbk_hall_core_device, 1)` + `__platform_driver_register(&bbk_hall_core_driver)`（`0x8aae170-0x8aae1d4`）。
- 如果 `mhall_data->inited(+0xa0)==1`（probe 已完成），直接打印 `damon bbk_hall_core is inited` 并返回 0，**不再注册**（后到的传感器会被静默忽略）。

### 1.3 `bbk_hall_core_read_data` 语义（`0x8aad9a0`）

- 若 `mhall_data->inited(+0xa0/160) != 1` → -1（`0x8aad9c0`；无任何打印）。
- 若 `mhall_data->enabled(+0x1c/28) == 0` → 打印 `damon hall is not enable`（`0x99f87a6`），**把两个输出都写 -2000**(`0xf830`)，返回 -1（`0x8aad9cc-0x8aadb0c`）。
- `mhall_data->busy(+0xa4) = 1`；先把 `*up = *down = -2000`。
- 循环最多 5 次：某个方向仍为 -2000 时调 `ops->get_data()`；返回负数就 `msleep(1)` 再试，5 次都失败 → 返回 -1。
- 退出前 `mhall_data->busy = 0`；成功返回 0。
- 参数是 **s16 指针**（汇编用 `strh` 写、`ldrsh` 读；调用方 `delay_func` 传的是栈上 2 字节槽 `0x8aad7d0-0x8aad7d8`）。

### 1.4 `mhall_data`（`0x9f75608` 指向的对象，`kmalloc(0xa8=168)`，`bbk_hall_core_init` @`0x9be1c90`）

| 偏移 | 类型 | 初值 | 含义 / 证据 |
|---|---|---|---|
| `0x00` | `struct hall_dev *` | 0 | hall_up |
| `0x08` | `struct hall_dev *` | 0 | hall_down |
| `0x18` | int (原子) | **1** | “两路注册完成”一次性守卫（`cmpxchg 1→0`） |
| `0x1c` | int (原子) | 0 | enabled（`cmpxchg 0→1` 开、`1→0` 关） |
| `0x20` | int | **50** | 轮询周期 ms，`set_delay` 下限 20 |
| `0x24` | int | 0 | hall 标定有效标志（ioctl 0/1 后置 1） |
| `0x28` | int | 0 | mhall 标定有效标志（ioctl 2 后置 1） |
| `0x30` | `struct delayed_work` | — | `work.func`=`bbk_hal_work_func`(`0x8aaea00`)，周期 = `delay` ms |
| `0x90` | `struct hall_queue *` | `init_hall_queue(10)` | hall 队列 |
| `0x98` | `struct hall_queue *` | `init_hall_queue(5)` | move 队列 |
| `0xa0` | int | 0 | inited（probe 成功末尾置 1） |
| `0xa4` | int | 0 | busy（read_data 期间为 1） |

---

## 2. misc 设备与 ioctl

### 2.1 设备节点与 fops

- `bbk_hall_core_misc_dev` @`0x9dcd850`：`minor=0xff(MISC_DYNAMIC_MINOR)`，`name=0xffffff80099f8a58`（**`"bbk_hall_core"`**），`fops=0x9dcd8a0`。
  → 节点 **`/dev/bbk_hall_core`**（misc 设备，主设备号 10，动态次设备号）。
- probe 里 `misc_register` 失败时打印 `bbk_hall_core_probe misc_register was failed(%d)`（`0x99f8a66`，`0x8aae2f0`）。
- `bbk_hall_core_misc_dev_fops` @`0x9dcd8a0`。**本内核的 `struct file_operations` 比上游 4.14 多一个指针槽**（用 m1120 的 fops @`0x9dcdc48` 校准）：实测布局是 `read=+0x10, write=+0x18, poll=+0x40, unlocked_ioctl=+0x48, compat_ioctl=+0x50, mmap=+0x58, open=+0x60, flush=+0x68, release=+0x70`。

| 槽位 | 值 | 符号 |
|---|---|---|
| `+0x10` read | `0x8aae320` | `bbk_hall_core_misc_dev_read`（`return 0`） |
| `+0x18` write | `0x8aae328` | `bbk_hall_core_misc_dev_write`（`return 0`） |
| `+0x40` poll | `0x8aae330` | `bbk_hall_core_misc_dev_poll`（`return 0`，**永不报告可读事件**） |
| `+0x48` unlocked_ioctl | `0x8aae338` | `bbk_hall_core_misc_dev_ioctl` |
| `+0x50` compat_ioctl | **0（NULL）** | 32 位进程没有专门的 compat 处理 |
| `+0x60` open | `0x8aae9f0` | `return 0` |
| `+0x70` release | `0x8aae9f8` | `return 0` |

### 2.2 ioctl 命令号与参数

`_IOC` 解码 `0x40046000`：dir=`_IOW`(1)，size 域=4，type=0x60，nr=0 → 形如 `_IOW(0x60, nr, int)`（**size 域写的是 4，但驱动实际拷贝 56/48 字节，属于厂家笔误；重写必须沿用同样的数字**）。

| cmd | 名字（日志字符串） | 用户参数 | 行为 |
|---|---|---|---|
| `0x40046000` | `BBK_HALL_CORE_IOCTL_SET_CALI` | 56 B blob 指针 | `filp_open("/mnt/vendor/persist/sensors/cali_hall", O_WRONLY\|O_CREAT\|O_TRUNC=0x241, 0644)` → 写 56 B → **再**拷进 `g_hall_cali_data` → `mhall_data->cali_valid=1` → `set_vib_all_time(g_hall_cali_data+0x34)` |
| `0x40046001` | `BBK_HALL_CORE_IOCTL_TRANS_CALI` | 56 B blob 指针 | **不落盘**：拷进 `g_hall_cali_data`，`cali_valid=1`，`set_vib_all_time(+0x34)`；然后 `filp_open("/mnt/vendor/persist/sensors/up_down_count", 0, 0x180)` 读 ≤50 B，`sscanf("%u-%u")`，`set_vib_up_down_count(up_down_count, count_all)` |
| `0x40046002` | `BBK_HALL_CORE_IOCTL_SET_MHALL_CALI` | 48 B blob 指针 | 写 `/mnt/vendor/persist/sensors/cali_mhall_final`(48 B) → 拷进 `g_mhall_cali_data` → `+4=1` → `init_hall_data_fake()` → `mhall_data->mhall_cali_valid(+0x28)=1` → 打印 `zyhc mhall ok` |
| `0x40046003` | `BBK_HALL_CORE_IOCTL_SET_MHALL_CALI_DAEMON` | 48 B blob 指针 | **不落盘**：拷进 `g_mhall_cali_data`，`+4=1`，`init_hall_data_fake()` |

其他要点：
- **参数结构就是第 3 节的裸 blob**：cmd `0x40046000`/`0x40046001` 的用户缓冲 = 56 字节 `struct hall_cali_data`（字段偏移见 3.1）；cmd `0x40046002`/`0x40046003` = 48 字节 `struct mhall_cali_data`（见 3.2）。内核只做整块拷贝，不解释字段（`__arch_copy_from_user`，长度硬编码为 `#0x38`/`#0x30`）。
- 命令越界（不是这 4 条）→ 返回 **`-ENOTTY`(-25)**（`0x8aae3d8`）。
- 参数是原始用户指针，直接进 `copy_from_user`；拷贝失败 → 返回 **`-EFAULT`(-14)**，并把它已经改动的全局缓冲区补零（`0x8aae8f0`、`0x8aae920`、`0x8aae940`、`0x8aae97c`、`0x8aae9b8`、`0x8aae9c0`）。注意它**先 memset 全局再 copy**，所以失败一次会把内核里的标定数据清掉。
- 打开/写文件失败 → 返回 **-1**（`cmd 0`/`cmd 2`），`cmd 2` 失败时还会把 `g_mhall_cali_data+4` 清零。
- 成功一律返回 **0**；`cmd 1` 即使 `up_down_count` 文件缺失也只打印 `read %s failed,%ld`（`0x99f8b7f`）并返回 0。
- `filp_open` 的 flags/mode：`cmd 0`/`cmd 2` 用 `0x241`(=O_WRONLY\|O_CREAT\|O_TRUNC)\|0644；`cmd 1` 用 flags 0(只读)、mode 0x180 被忽略。
- 写盘用 `__kernel_write(filp, buf, n, &filp->f_pos)`（偏移 `+0x70`），**没有 fsync/同步**；`O_TRUNC` 保证文件长度恰好 56/48 B。
- 参数结构**不透明**：内核只做整块 56/48 字节拷贝，字段类型来自使用者（vib_pwm）的解读 —— 见第 3 节。

---

## 3. 标定数据在磁盘/内存中的布局

### 3.1 `/mnt/vendor/persist/sensors/cali_hall` —— 56 字节（`g_hall_cali_data`，`0x9f75610`，.bss）

由 `computer_distance`（`0x8aa9ab0`）的调试打印（5 个 `printk` 各读 3 个字段：`ldrsh +0,+2` + `ldr +4`）反推出条目布局 `{s16 hall_up; s16 hall_down; int hall_up_down_diff;}` = 8 字节，条目基地址为 `+0x04/+0x0c/+0x14/+0x1c/+0x24`：

```c
struct hall_cali_data {            /* 56 B, 与磁盘文件同布局，裸拷贝 */
    /* +0x00 */ int  unknown0;                 /* 未在本模块被读取过（不确定） */
    /* +0x04 */ struct { s16 hall_up; s16 hall_down;
                          int hall_up_down_diff; } position0;     /* 打印名 position_0  */
    /* +0x0c */ ... position24;                                    /* position_24 */
    /* +0x14 */ ... position48;                                    /* position_48 */
    /* +0x1c */ ... position696;                                   /* position_696 */
    /* +0x24 */ ... position1;                                     /* position_1  */
    /* +0x2c */ ... position?;                                     /* 第 6 条，名字未知 */
    /* +0x34 */ int  cali_time;                /* 52, 只在 show/store/set_vib_all_time 用 */
};
```

- 关键偏移（有交叉引用证据）：
  - `+0x08 / +0x10 / +0x18 / +0x20 / +0x28` = 上面 5 个 `hall_up_down_diff`，**`computer_distance` 行程曲线的 5 个标定点**（`0x8aa9b4c-0x8aa9d10` 读 `[x19,#8/#16/#24/#32/#40]`）。
  - `+0x24` = `position1.hall_up`(s16)、`+0x28` = `position1.hall_up_down_diff`；`bbk_hal_work_func` 读 `ldrsh [x,+36]=position1.hall_up` 与 `ldrsh [x,+6]=position0.hall_down` 做阈值比较。
  - `+0x34`(52) = `cali_time`：`bbk_hall_cali_time_show` 读它、`..._store` 写它（`0x8aadf9c/0x8aae05c`）、3 个 ioctl 里 `set_vib_all_time()` 的参数也是它（`0x8aae480`、`0x8aae6a8`）。
  - `+0x28`(40) 是 `delay_func` 判定的 `position1.hall_up_down_diff`（`0x8aad824-0x8aad83c`），与日志字符串 `hall_up - hall_down < (cali_data.position1.hall_up_down_diff ± 25)` 完全对应。
- 没有 magic、没有 checksum、没有版本号，也没有长度字段。`cmd 0` 用 `O_TRUNC` 直接写 56 字节，所以**文件长度就是 56**；读侧从不读文件（只在 daemon 调用 ioctl 时把 blob 送进来），因此“文件缺失/被截断”不会触发内核读取错误，只会让 daemon 自己拿到短数据。
- 载入时机：**probe 时不加载**（`bbk_hall_core_probe` 里没有任何 `filp_open`/`kernel_read`，只有 6 个 `device_create_file` + `misc_register`）。唯一入口就是 ioctl 0/1，即“Android 标定守护进程在开机后主动下发”。
- 全零 blob 的后果：`computer_distance` 检查 `+0x34(cali_time)==0 || +0x08(position0.diff)==0` → 打印 `damon hall sensor is not cali` 并返回 **-1**（`0x8aa9b4c-0x8aa9ba0`），马达行程计算被禁用。

### 3.2 `/mnt/vendor/persist/sensors/cali_mhall_final` —— 48 字节（`g_mhall_cali_data`，`0x9f75648`）

由 `init_hall_data_fake`（`0x8aa9710`）与 `vib_pwm_elevator_row_shift_show`（`0x8aac1a8`）反推：

```c
struct mhall_cali_data {           /* 48 B */
    /* +0x00 */ s16 hall_up;        /* → mhall_fake_data_up        */
    /* +0x02 */ s16 hall_down;      /* → mhall_fake_data_down      */
    /* +0x04 */ int valid_or_version;  /* 必须是 1，否则 init_hall_data_fake 返回 -1
                                          并打印 "zyhc set mhall cali data failed"；
                                          内核在拷贝后强制写 1；bbk_mhall_version 显示它 */
    /* +0x08 */ s16 hall_up_1;      /* → mhall_fake_data3         */
    /* +0x10 */ s16 hall_up_2;      /* 被 elevator_row_shift 用    */
    /* +0x18 */ s16 hall_up_3;      /* 同上                        */
    /* +0x20 */ s16 hall_up_4;      /* 同上                        */
    /* +0x28 */ int f2;             /* → mhall_fake_data2         */
    /* +0x2c */ int add_time;       /* → mhall_fake_data_add_time */
};
```
- `init_hall_data_fake` 的完整行为（`0x8aa9710-0x8aa978c`）：
  `if (p[+4] != 1) { printk("zyhc set mhall cali data failed"); return -1; }`
  `mhall_fake_data_up = *(s16*)(p+0); mhall_fake_data_down = *(s16*)(p+2);`
  `mhall_fake_data3 = *(s16*)(p+8); mhall_fake_data2 = *(int*)(p+40); mhall_fake_data_add_time = *(int*)(p+44);`
  `printk("zyhc data_up:%d,data_down:%d,fake_data2:%d,fake_data3:%d,add_time:%d")`；成功返回 1。
- 同 `cali_hall`：无 magic / 无 checksum，长度固定 48；`+4` 这个“有效标志”承担了 magic 的角色。
- `bbk_mhall_version` sysfs 读的就是 `*(int*)(+4)`（`0x8aae0a4`），格式串 `"version:%d\n"`（`0xffffff80099e8c88`，因字符串合并落在别的长串中间）。

### 3.3 `/mnt/vendor/persist/sensors/up_down_count` —— 纯文本

- 写：`vib_pwm_up_down_count_thread`（`0x8aad308`，vib_pwm 线程）`snprintf(buf,49,"%u-%u", vib_pwm_data+672, vib_pwm_data+676)` → `filp_open(...,0x242,0x180)` → `__kernel_write`。
  格式字面量在 `0xffffff80099b0503`（`"%u-%u"`，注意它是 `"%s %u-%u"` 的后缀合并体）。
- 读：ioctl `0x40046001` `sscanf(buf,"%u-%u",&up_down_count,&count_all)`（格式在 `0xffffff8009ae5a09`，是 `"nf-logger-%u-%u"` 的后缀），然后 `set_vib_up_down_count(up_down_count,count_all)`；打印 `damon vib_pwm up_down_count is %u, count_all:%u`。
- 文件缺失 → 只打印 `read %s failed,%ld`，ioctl 仍返回 0。

---

## 4. sysfs 属性

`bbk_hall_core_probe`（`0x8aae1f0`）用 `device_create_file(&pdev->dev, ...)` 建 6 个，pdev 是平台设备 `bbk_hall_core` →
路径 **`/sys/devices/platform/bbk_hall_core/<name>`**（没有独立 class/kobj）。
创建前打印 `printk("\0016%s num=%d\n", "bbk_hall_core_device_create_attr", 6)`，失败打印 `"\0016device_create_file (%s) = %d\n"`（`0x99f84fc`/`0x99f852c`）。

`struct device_attribute` 布局：`+0x00 name`, `+0x08 u16 mode`, `+0x10 show`, `+0x18 store`。

| 符号 | 地址 | name 字面量 | mode | show | store | 语义 |
|---|---|---|---|---|---|---|
| `dev_attr_bbk_hall_delay` | `0x9dcd3a0` | `bbk_hall_delay`(`0x99f88a3`) | 0644 | `0x8aadcd8` | `0x8aadd10` | `sprintf(buf,"delay=%d\n", mhall_data->delay)`（`0x9aaefac`）；store `simple_strtoul(base 10)` 后 `delay = max(val,20)`，**无范围上界** |
| `dev_attr_bbk_hall_enable` | `0x9dcd3c0` | `bbk_hall_enable` | 0644 | `0x8aadd58` | `0x8aadd90` | show `"enable=%d\n"`（`0x9971462`，读 `mhall_data+0x1c`）；store 只在 `val<=1` 时调 `bbk_hall_core_enable(val)`，否则**什么都不做但仍返回 count** |
| `dev_attr_bbk_hall_data` | `0x9dcd3e0` | `bbk_hall_data` | 0444 | `0x8aaddd0` | NULL | 自己直接调 `ops->get_data()`（上/下各重试 10 次、每次 `msleep(2)`），`sprintf(buf,"up:%d down:%d\n")`；全失败输出 `up:-2000 down:-2000` |
| `dev_attr_bbk_hall_vendor` | `0x9dcd400` | `bbk_hall_vendor` | 0444 | `0x8aadf40` | NULL | `sprintf(buf,"up:%s down:%s\n", mhall_data->hall_up, mhall_data->hall_down)`，即注册时用的名字（`up-mxm1120` 等） |
| `dev_attr_bbk_hall_cali_time` | `0x9dcd420` | `bbk_hall_cali_time` | 0644 | `0x8aadf78` | `0x8aadfe8` | 见下 |
| `dev_attr_bbk_mhall_version` | `0x9dcd440` | `bbk_mhall_version` | 0444 | `0x8aae088` | NULL | `sprintf(buf,"version:%d\n", g_mhall_cali_data+4)` |

`bbk_hall_cali_time` 精确语义：
- show（`0x8aadf78`）：若 `mhall_data->cali_valid(+0x24)==0` → 输出 `"cali_time=0\n"`；否则输出 `"cali_time=%d\n"`，值是 **`g_hall_cali_data->cali_time(+0x34) * 6 / 10`**（`smull 0x66666667 / asr 34`）。
- store（`0x8aadfe8`）：`v = simple_strtoul(buf,10)`；`t = (10*v + 5) / 6`（`smull 0x2aaaaaab`，即 `×5/3` 四舍五入）；仅当 `cali_valid!=0 && (10*v+5)>=11`（即 `v>=1`）才写入 `g_hall_cali_data+0x34 = t`，打印 `damon bbk_hall_cali_time_store Set cali time:%d Success` 并调 `set_vib_all_time(t)`；否则打印 `... failed` 且**不写**。返回值始终是 count。
- 也就是内部单位 = 0.6 × 用户单位（用户写 ms，读回来近似同值）。

其它：这三个 `T` 数据符号 `dev_attr_bbk_hall_*` 都在 `.data`，extern 可见，重写时若保留同名符号不会冲突（因为原驱动不再存在），但**必须保持 name/mode/show/store 四元组一致**。

---

## 5. 平台胶水

### 5.1 平台驱动/设备

- `bbk_hall_core_driver` @`0x9dcd468`（`struct platform_driver`，本内核 `device_driver`=120 B，整体 176 B）：
  - `+0x00 .probe = 0x8aae1f0`
  - `+0x08 .remove = 0`、`+0x10 .shutdown = 0`、`+0x18 .suspend = 0`、`+0x20 .resume = 0`
  - `+0x28 .driver.name = 0xffffff80099f8a58` = **`"bbk_hall_core"`**
  - `+0x50 .driver.of_match_table = **NULL**`，`+0x58 acpi = NULL`，`+0xa8 .id_table = NULL`
  - → **没有 compatible 字符串**，纯粹靠平台设备名匹配。
- `bbk_hall_core_device` @`0x9dcd518`（`struct platform_device`）：`name="bbk_hall_core"`、`id=-1`(PLATFORM_DEVID_NONE)、无 resource、`dev.release=NULL`。
- 注册顺序（`bbk_hall_core_register_device`，`0x8aae1b8-0x8aae1d4`）：
  `platform_add_devices(&bbk_hall_core_device, 1)` → `__platform_driver_register(&bbk_hall_core_driver)`，并且打印
  `bbk_hall_core: register up down hall Done,so add platform devices`（`0x99f8946`）。
- `bbk_hall_core_probe`（`0x8aae1f0`）只做三件事：`x20 = pdev+0x10`(= `&pdev->dev`)、6×`device_create_file`、`misc_register(&bbk_hall_core_misc_dev)`，成功后 `mhall_data->inited=1`。**不解析 DT、不创建任何子设备、不申请中断。** 返回 -1 仅当 `misc_register` 失败。
- `bbk_hall_core_init`（initcall4，`0x9be1c90`）：
  `mhall_data = kmalloc(0xa8, GFP_KERNEL)`（失败打印 `bbk_hall failed kmalloc hall_data failed` 并返回 -1）；
  清零 `hall_up/hall_down`；`camera_mhall`(3×int, 12 B) 清零；`memset(mhall_data,0,8)`；`delay=50`；`enabled=0`；`register_flag=1`；`busy=0`；`cali_valid=0`；`inited=0`；`hall_queue=init_hall_queue(10)`；`move_queue=init_hall_queue(5)`；初始化 `INIT_DELAYED_WORK`（`work.func=bbk_hal_work_func`，`timer.function=delayed_work_timer_fn`）；打印 `zyhc mhall BBK_HALL_CORE_IOCTL_SET_MHALL_CALI:1074094082`（即 `0x40046002`，**这是 cmd 数值的第二个确证**）与 `[LYQ-damon-hall]:bbk_hall_core_init success`。
- `bbk_hall_core_exit`（`0x9c10c28`）存在，但内置驱动不会执行。

### 5.2 传感器侧的平台/i2c 名字（DT 必须保持）

| 驱动 | i2c compatible | 平台/i2c 名 | misc 节点 | 注册进 hall core 的名字 |
|---|---|---|---|---|
| MXM1120 down | `magnachip,mxm1120,down` | `m1120_down` | `mxm1120_down` | `down-mxm1120` |
| MXM1120 up | `magnachip,mxm1120,up` | `m1120_up` | `mxm1120_up` | `up-mxm1120` |
| IST8801 | `isentek,ist8801-0/-1/-2` | `ist8801_0/1/2` | —（走 dhall） | `up-ist8801` / `down-ist8801` |

（字符串：`0x95f1258/0x95f1460/0x95f1630`，`0x95f13a8/0x95f15b0/0x95f19c8`，`0x99f9e9b/0x99fa1d5`，`0x99f9395/0x99fa086`，`0x99fa93a/0x99fa945`）
**注意工厂 ist8801 probe 的一个 bug**：`ist8801_i2c_probe` 尾段只对 `w19==0`（`up-ist8801`）和 `w19==2`（`down-ist8801`）做 `strcpy`，`w19==1`（中间那颗）不写名字，于是 name 是未初始化内存 —— 我们重写时可以修正，但要保证 up/down 两个名字前缀正确。

### 5.3 与 `vib_pwm`（马达控制器）的交互

`vib_pwm` = `vib_pwm_pdrv` @`0x9dcd2f0`，`.driver.name` = **`"bbk_vib_pwm"`**（`0x99f7d77`），`of_match_table` = `vib_pwm_of_match`@`0x9dcd160`，compatible = **`"bbk,vib_pwm_control"`**（内联 `char[128]`，`0x9dcd1a0`）；probe/remove/shutdown/suspend/resume = `0x8aac658/0x8aad068/0x8aad0a0/0x8aad0c8/0x8aad0f0`；13 个 `dev_attr_vib_pwm_*` 属性。

**vib_pwm 调用 bbk_hall_core 的导出符号**（由 `bl` 交叉引用得出，`/mnt/e/s6ke/work/hall2/xref_module.txt`）：

| 调用者 | 被调符号 |
|---|---|
| `vib_update_key`(`0x8aa9790`) | `bbk_hall_core_init_move_queue`、`bbk_hall_core_init_queue` |
| `cancel_vib_hrtimer`(`0x8aa98d8`) | 同上两个 |
| `is_top_or_bottom`(`0x8aa9998`) | `bbk_hall_core_read_data` |
| `vib_pwm_state_move_sate`(`0x8aaa470` 区域) | `bbk_hall_get_status`、`bbk_hall_core_read_data`、`bbk_hall_core_enable` |
| `vib_pwm_set_camera_state`(`0x8aaa470`) | `bbk_hall_core_enable` |
| `vib_pwm_set_camera`(`0x8aaa7e0`) | `bbk_hall_core_enable`、`bbk_hall_get_status` |
| `vib_pwm_state_init_store`(`0x8aab870`) | `bbk_hall_get_status`、`bbk_hall_core_enable` |
| `vib_pwm_elevator_row_shift_show` | `bbk_hall_core_read_data` + 直接读 `g_mhall_cali_data` |
| `vib_pwm_cali_store`(`0x8aac428`) | `bbk_hall_core_enable` |
| `vib_pwm_clear_cali_data_store`(`0x8aac5d8`) | `hall_clear_cali_data` |
| `vib_pwm_thread`(`0x8aad118`) | `bbk_hall_core_enable`、`bbk_hall_get_status` |
| `delay_func`(`0x8aad688`) | `bbk_hall_get_status`、`bbk_hall_core_read_data`、`bbk_hall_core_init_queue(_move)`、`bbk_hall_core_enable` |

同时 vib_pwm **直接读写核心的全局数据**：`g_hall_cali_data`（+0x08/+0x10/+0x18/+0x20/+0x24/+0x28/+0x34/+0x38/+0x40）、`g_mhall_cali_data`（+8/+16/+24/+32）、`mhall_data`（+0x20 delay、+0x90/+0x98 队列、+0x28/+0x34 标志），以及 `mhall_press`。
→ **重写时这些符号必须保持同名、同类型、同布局**（`T` 导出 + 同名 `.bss` 对象）。这是最容易踩的坑：只实现 ioctl 而改名/改布局，`vib_pwm` 会读到垃圾。
另外 vib_pwm 侧有 `bbk_hall_core_delay`（非核心）等属性，`g_hall_cali_data+0x34` 被 `bbk_hall_cali_time_store` 和 ioctl 双向写，注意竞争（工厂代码无锁）。

---

## 6. hall 位置/聚合逻辑

### 6.1 队列结构（`init_hall_queue` @`0x8aaf130`，`kmalloc(32)`）

```c
struct hall_queue {          /* 32 B */
    int *up;      /* +0x00  数组, n 个 int */
    int *down;    /* +0x08  数组, n 个 int */
    int size;     /* +0x10  槽数 */
    int index;    /* +0x14  下一个写位置 */
    int count;    /* +0x18  “按压”计数（bbk_hal_work_func 里 ++，>=14 触发告警） */
    int pad;      /* +0x1c */
};
```
- `init_hall_queue(n)`：`n<1` 直接返回 NULL；两个数组用 `__kmalloc(n*4)`；所有元素填 **哨兵 10000 (0x2710)**；`index=count=0`。
- `in_hall_queue(q,up,down)`：写 `q->up[index]=up; q->down[index]=down;`，`index = (index+1==size) ? 0 : index+1`。
- `out_hall_queue_up(q,off)`：`up[(index+off)%size]`；down 同理。
- `hall_queue_is_inited(q)`：size<1 → 0；任一元素 == 10000 → **1**（表示“有哨兵残留、还没采够”）；否则 0。所有 `queue_data_is_*` 开头都有同一段“存在 10000 → return 0”的检查，即**必须先填满队列**。
- 两条队列由 `bbk_hall_core_init` 建：`hall_queue` 大小 10、`move_queue` 大小 5。

### 6.2 判定函数与阈值

- `queue_data_is_press(q)`（`0x8aaf550`）：取 `newest = up[(idx+size-1)%size]`、`oldest = up[idx%size]`、`prev = up[(idx+size-2)%size]`，其中 `T = mhall_press`（`*(int*)0xffffff8009dcd990`，**工厂值 = 8**）：
  - 若 `newest-oldest > 0` 且 `(prev-oldest) > T` 且 `prev>oldest` 且 `(newest-oldest) > T` → 1；
  - 若 `newest-oldest < 0` 且 `(oldest-prev) > T` 且 `prev<oldest` 且 `(oldest-newest) > T` → 1；
  - 否则 0。**down 通道用完全相同的条件**，两个通道都满足才返回 1。
- `queue_data_is_move_press(q)`（`0x8aaf2d8`）：先要求所有相邻样本 `|Δ|² ≤ 1`（即信号“冻结”，抖动 ≤1 LSB），最后要求 `|up[最后]-up[最旧]|² ≤ 1`（^ 同 down）→ 返回 1，表示“机构停住了”（卡住/到位）。
- `queue_data_is_move_strong_press(q, state, polarity)`（`0x8aaf3f8`）：`state != 4` → 0；`polarity==1` 时判 `down[newest]-up[newest] + up[j]-down[j] > 30`（某个 j 成立即 1）；`polarity==0` 时判反向 `>= 31`。`bbk_hal_work_func` 用 `polarity = (cali_valid==1) && (g_hall_cali_data->position0.diff(+8) < position1.diff(+40))`（`0x8aaefc4-0x8aaefec`）。
- `bbk_hal_work_func` 的其它常量：`position0.hall_down(+6)`、`position1.hall_up(+36)` 与实时值的比较阈值 **±10**（`cmp #0xa`，`0x8aaed58-0x8aaee68`）；`move_queue->count >= 14` 时打印告警并清队列 + `cancel_vib_hrtimer(0/1)`；每条路径最后都用 `queue_delayed_work_on(8, system_wq, &mhall_data->hall_work, msecs_to_jiffies(mhall_data->delay))` 重新排程（`0x8aaeecc-0x8aaeee8`）。
- 消费端 `delay_func`（vib_pwm 的定时器回调，`0x8aad688`）里触发“按压/异常”的条件是：
  `(u32)( hall_up - hall_down - g_hall_cali_data->position1.hall_up_down_diff(+0x28) + 25 ) >= 51`
  ⇔ `|hall_up - hall_down - position1.diff| > 25`（`0x8aad820-0x8aad848`），与日志字符串 `damon enter handle input KEY_CAMERA_PRESS_MOVE & because: hall_up - hall_down < (cali_data.position1.hall_up_down_diff ± 25)` 一致。

### 6.3 位置/距离换算（`computer_distance` @`0x8aa9ab0`）

输入 `diff = hall_up - hall_down`（s16），输出 `distance`（int）：
1. 未标定（`cali_time(+0x34)==0 || position0.diff(+0x08)==0`）→ 打印 `damon hall sensor is not cali`，返回 **-1**。
2. 把 5 个标定点按 diff 值排序后做**分段线性插值**，段长为固定的 3828 / 3828 / 3445 / 4849，累计到 **15950**：

| 段 | 常量（十六进制/十进制） |
|---|---|
| 0 → 3828 | `0xef4` = 3828 |
| 3828 → 7656 | `0x1de8` = 7656 |
| 7656 → 11101 | `0x2b5d` = 11101 |
| 11101 → 15950 | `0x3e4e` = 15950 |

   每段内 `dist = base + (diff - dLo) * seg / (dHi - dLo)`，并支持标定点单调递减的“反向”情形（`0x8aa9bc4-0x8aa9cd4`）。
3. 钳位：`diff` 小于最小标定点 → 0；大于最大标定点 → 15950（`csel` 于 `0x8aa9cdc-0x8aa9d10`）。
4. 打印 `damon computer distance %d`（`0x99f6eff`）后返回。
- `is_top_or_bottom()`（`0x8aa9998`）：`dist = computer_distance(...)`；返回 `(dist<=499 || 15950-dist<=499) && camera_mhall/state==4` 的布尔值（阈值 `0x1f3`=499；`vib_pwm_data+0x1a0` 被当作状态读取，`0x8aa9a34-0x8aa9a7c`）。

### 6.4 DT 属性 `data-range` / `hall,bias_support` / `hall,bias-ratio`（重要澄清）

这三个**不是 `bbk_hall_core` 的属性**，而是 **IST8801 传感器驱动自己在 `ist8801_i2c_probe` 里解析**的（字符串 `0x99fa9b0` / `0x99faa99` / `0x99faaab`，代码 `0x8ab5268-0x8ab53e0`）：

| 属性 | API | 存放/含义 |
|---|---|---|
| `data-range` | `of_property_read_u32(node,"data-range",&v)`（`0x8ab5284`） | 低 8 位存入 `ist8801_data+47`；缺失时 `dev_err("%s : data-range is not specified, use default value:0x%x")` 并置 0（`0x8ab52a4-0x8ab52cc`）；后续在阈值/量程计算里用（`0x8ab591c` `ldrb [x20,#47]`） |
| `hall,irq-gpio` | `of_get_named_gpio_flags(...,0,NULL)`（`0x8ab52e8`） | 存入 `ist8801_data+192` |
| `hall,bias_support` | `of_find_property(node,"hall,bias_support",NULL) != NULL`（`0x8ab5390`） | 布尔存 `ist8801_data+205` |
| `hall,bias-ratio` | `of_property_read_variable_u32_array(node,"hall,bias-ratio",...)`（`0x8ab53bc`） | u32 存 `ist8801_data+208`（读失败走默认分支 `0x8ab5b38`） |

`bbk_hall_core` 本身**完全没有 `of_property_*` 调用**（probe 全文只有 printk/device_create_file/misc_register），所以给它写 DT 节点没有意义；它靠“平台设备名”出现。

### 6.5 可调参数（都是 kernel `module_param`，不是 DT）

`__param_*` 表在 `0x9b7b880-0x9b7b9e8`（`struct kernel_param`，ops=`0x92085a8`=`param_ops_int`，perm=**0644**，level=-1）：

| 参数（cmdline 名） | 绑定的全局量 |
|---|---|
| `gpio_pwm.mhall_control_up` | `mhall_fake_data_up` (`0x9f755d8`) |
| `gpio_pwm.mhall_control_down` | `mhall_fake_data_down` (`0x9f755dc`) |
| `gpio_pwm.mhall_control2/3/4/5/6/7` | `mhall_fake_data2/3/4/5/re/add_time` |
| `bbk_hall_queue.mhall_control_press` | **`mhall_press`** (`0x9dcd990`，工厂值 **8**) |

（`mhall_press` 就是 6.2 里 `queue_data_is_press` 的阈值 T；`mhall_fake_data*` 是 ioctl 2/3 灌进去的“假 hall/时间”参数，供 vibrator 调参使用。）

---

## 7. 重写时最容易破坏 BBK 用户态的点（清单）

1. **misc 名**：必须是 `bbk_hall_core`，节点 `/dev/bbk_hall_core`（次设备号混在 misc 动态分配里，不能写死 255 之外的固定值，否则与其它 misc 设备冲突）。
2. **ioctl 号**：`0x40046000/1/2/3`，一个都不能变；越界必须返回 `-ENOTTY`，拷贝失败必须 `-EFAULT`。
3. **ioctl 参数字节数**：cmd0/cmd1 = **56 字节**，cmd2/cmd3 = **48 字节**；内核按此长度 `copy_from_user`，长度不对会把用户栈后面的垃圾算进标定数据（同时 `copy_from_user` 的 `access_ok` 失败判定也会变化）。
4. **文件格式**：`cali_hall` 56 B 裸结构、`cali_mhall_final` 48 B 裸结构、`up_down_count` = `"%u-%u"` 文本；**没有 magic/校验和**，所以任何偏移错位都不会被检测出来，只会表现为旋出位置错乱/行程不对。`cali_mhall_final+4` 必须允许内核写成 1（它是 `init_hall_data_fake` 的准入条件）。
5. **`g_hall_cali_data` 布局**：`+0x34` = cali_time（`bbk_hall_cali_time` 读写、`set_vib_all_time` 入参）；`+0x08/+0x10/+0x18/+0x20/+0x28` = 5 个 `hall_up_down_diff`（行程插值）；`+0x06`/`+0x24`/`+0x28` 被 `bbk_hal_work_func` 当 s16/s16 用。**这 56 字节是与 vib_pwm 共享的 ABI**。
6. **`g_mhall_cali_data`**：`elevator/holder` 模式直接读 `+8/+16/+24/+32`（s16），`bbk_mhall_version` 读 `+4`。
7. **导出的数据符号名与类型**：`mhall_data`、`g_hall_cali_data`、`g_mhall_cali_data`、`camera_mhall`、`mhall_fake_data*`、`vib_pwm_data` 必须同名同布局（vib_pwm 直接引用它们，符号不匹配会链接失败或读到错位数据）。
8. **导出函数集合**：`bbk_hall_core_read_data(s16*,s16*)`、`bbk_hall_core_enable(int)`、`bbk_hall_get_status()`(返回 inited，不是 enable)、`bbk_hall_core_init_queue/_move_queue`、`bbk_hall_core_set_delay`、`bbk_hall_core_register_device`、`hall_clear_cali_data` 及 6 个队列函数必须保留（名字/签名/返回语义），vib_pwm 已经写死这些。
9. **注册结构体**：`struct hall_dev{char name[24]; struct hall_ops *ops; void *data;}`（40 B，`kmalloc`），名字必须以 `up`/`down` 开头（只比较 2/4 字节），核心只保存指针且**永不释放**。若沿用 `down-mxm1120`/`up-ist8801` 这类名字即可无缝工作。
10. **平台设备名**：`bbk_hall_core`（无 compatible）。`bbk_hall_enable`/`bbk_hall_delay`/`bbk_hall_data`/`bbk_hall_vendor`/`bbk_hall_cali_time`/`bbk_mhall_version` 六个属性名与 mode(0644/0444/0644) 要保持；路径是 `/sys/devices/platform/bbk_hall_core/*`，BBK 的 init.rc/daemon 可能直接 chown/chmod 这些路径。
11. **poll 永远返回 0**、read/write 返回 0、open/release 返回 0 —— 若改成“可读事件”语义，可能反而让 daemon 的轮询逻辑变化（保持原样最安全）。
12. **时序**：`enable` 通过 `queue_delayed_work_on(..., 10 jiffies)` 起首轮，之后周期 = `delay`（最小 20 ms）；`enable`/`register` 用原子 `cmpxchg` 做幂等；`bbk_hall_core_enable` 在 `inited!=1` 时是**静默 no-op**，重写时不要返回错误（vib_pwm 不检查返回值也依赖它不阻塞）。
13. **`misc_register` 失败必须返回 -1**（probe 失败），否则 `mhall_data->inited` 会被置 1、`bbk_hall_get_status()` 返回 1 而实际无节点。

---

## 8. 不确定 / 证据不足之处（明确标注）

1. **`g_hall_cali_data+0x00`（4 字节）未被本模块内任何指令读取**（我最初的 `ldrb [g_hall_cali_data]` 命中是 adrp 寄存器复用的假阳性，实际是 `vib_pwm_data+0xc0`）。它属于 56 字节 blob 的一部分，重写时**必须原样保留 56 字节长度**，但语义未知。
2. **第 6 条 position 条目（`+0x2c`，8 字节）与 `+0x34` 的关系**：`+0x34` 被明确当作 `cali_time`（ioctl/sysfs/`set_vib_all_time` 三处证据）。若把 `+0x2c` 视为 `{u16,u16,int}` 条目，则 `+0x34` 会与它的 `diff` 重叠 —— 因此我判断 `+0x34` 是独立 int，`+0x2c` 之后最多只到 `+0x33`（另一种可能是 `+0x2c` 与 `+0x30` 是两个独立 int）。**结论：`+0x34` 一定是 cali_time（高置信）；`+0x2c..+0x33` 的确切切分不确定（低置信）。**
3. **`position0/24/48/696/1` 这些后缀数字的含义不明**（既不像数组下标，也不像距离；696 尤其可疑）。它们是 5 个独立 `printk` 字面量里的名字，只能确定“字段名”而无法确定来源宏。
4. **`struct file_operations` 多出的那一个 8 字节槽**：我用 m1120 的 fops（`0x9dcdc48`，含 read/write/poll/ioctl/open/release 六个已知非零项）实测校准出 `poll=+0x40, unlocked_ioctl=+0x48, compat_ioctl=+0x50, open=+0x60, release=+0x70`。无法从二进制确定这个多出来的字段名（可能是 Qualcomm 的回移字段）。**结论（高置信）：`bbk_hall_core` 的 `unlocked_ioctl` = `0x8aae338`（真 ioctl），`compat_ioctl` = NULL。**
5. `mhall_data` 里两个“标志位”极易混淆，这里给出确证：**`+0x1c`(=28) 是 `enabled`**（`bbk_hall_core_read_data` 判它为 0 时报 `damon hall is not enable`，`0x8aad9cc`；`bbk_hall_enable` 属性 show 也读它，`0x8aadd74`；`bbk_hall_core_enable` 用原子 `cmpxchg` 改它，`0x8aadb88-0x8aadc44`）；**`+0x24`(=36) 是 `cali_valid`**（`bbk_hall_core_enable` 不碰它；3 个 ioctl 与 `bbk_hall_cali_time_show` 读/写它）。第 1.4 节表格与此一致。
6. `camera_mhall`（`0x9f75678`，12 字节，`bbk_hall_core_init` 里清零）在本模块内没有其它访问点，其用途未能确定。
7. `is_top_or_bottom` 读的“状态”是 `vib_pwm_data+0x1a0`，而 `delay_func` 比较的状态是 `vib_pwm_data+0x150`（值域 4/5）。二者的确切命名（`camera_state` vs `move_state`）无法从二进制唯一确定；状态机取值 1..7 由 `bbk_hal_work_func` 的 `get_camera_state()`（`0x8aa9930`）提供。
8. `hall,bias_support`/`hall,bias-ratio` 的**下游用法**（+205/+208 如何在 `ist8801_get_zdata_compensation`/阈值里生效）属于我们已重写的 IST8801 驱动，本报告只确证“由传感器驱动解析、存放偏移、默认分支存在”。

---

## 附：本次分析产出的可复现材料

- 脚本：`E:\s6ke\work\sh\h_syms.sh`、`h_dump.sh`、`h_hex.sh`、`h_scan.sh`+`h_strscan.py`、`h_find.sh`+`h_findstr.py`、`h_callers.py`、`h_xref2.py`（adrp/add/ldr/ldp 地址解析器）
- 反汇编/交叉引用：`E:\s6ke\work\hall2\module.dis`（整个 hall 模块 0x8aa9000-0x8ab6000）、`core.dis`（core 区）、`misc.dis`、`workfunc.dis`、`ist8801full.dis`、`xref_module.txt`、`hallstr.txt`、`propstr.txt`
- 关键数据 dump：`data_dat.txt`（dev_attr/fops/misc/driver/device 结构）、`jumptab.txt`（ioctl 跳转表）
