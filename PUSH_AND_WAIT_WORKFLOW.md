# 本地推送模式 + 服务器自动处理

## 概述

这个方案用于**本地主动推送数据到服务器**，并由服务器自动处理。不需要 venus3 反向连接本地。

整个流程：
1. **本地**：按日期推送数据 → 创建 `.ready` 标记 → **等待** `.done` 标记
2. **服务器**：监听 `.ready` 标记 → 启动推理 → 创建 `.done` 标记 → 清理临时数据
3. **本地**：检测到 `.done` → 继续推送下一天

## 文件说明

| 文件 | 位置 | 用途 |
|---|---|---|
| `push_and_wait.py` | 本地 | 按日期推送数据，等待处理完成 |
| `server_batch_process.py` | 服务器 | 监听并处理每天数据 |
| `manifest.csv` | 本地或服务器 | 要处理的视频文件列表 |

## 快速开始

### 第 1 步：准备本地 manifest.csv

在本地创建或编辑 `manifest.csv`，列出要处理的所有视频：

```csv
video
/media/zekai/Expansion/Experiment data CHAO_MAI/2025_9_1/DJI_0001.MP4
/media/zekai/Expansion/Experiment data CHAO_MAI/2025_9_1/DJI_0002.MP4
/media/zekai/Expansion/Experiment data CHAO_MAI/2025_9_2/DJI_0101.MP4
/media/zekai/Expansion/Experiment data CHAO_MAI/2025_9_2/DJI_0102.MP4
```

脚本会自动从路径中提取日期（如 `2025_9_1`），并按日期分组。

### 第 2 步：在服务器上启动守护进程

在 venus3 上**后台启动**处理守护进程：

```bash
# SSH 进入服务器
ssh venus3

# 创建必要的目录
mkdir -p /srv/light_batch/{work,db,logs}

# 启动守护进程（后台运行）
nohup python3 /path/to/light/server_batch_process.py \
  --work-root /srv/light_batch/work \
  --db-root /srv/light_batch/db \
  --log-root /srv/light_batch/logs \
  --infer-script /path/to/light/infer_origin.py \
  --poll-interval 5 \
  > /srv/light_batch/logs/daemon.log 2>&1 &

# 验证守护进程已启动
ps aux | grep server_batch_process
```

### 第 3 步：本地执行推送和等待

在本地运行推送脚本：

```bash
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai \
  --server-root /srv/light_batch \
  --local-user zekai \
  --poll-interval 10 \
  --poll-timeout 3600
```

脚本会：
1. 推送第一天的所有视频文件到 `/srv/light_batch/work/2025_9_1/`
2. 创建 `.ready` 标记
3. **轮询等待** `.done` 标记（每 10 秒检查一次，最多等 1 小时）
4. 检测到 `.done` 后，继续推送第二天
5. 重复直到所有日期处理完成

## 工作流详解

### 标记文件机制

```
/srv/light_batch/work/
├── 2025_9_1/
│   ├── DJI_0001.MP4
│   ├── DJI_0002.MP4
│   ├── .ready          ← 本地创建：表示"该天数据已准备就绪"
│   └── .done           ← 服务器创建：表示"该天处理完成"
├── 2025_9_2/
│   ├── DJI_0101.MP4
│   ├── .ready
│   └── .done
└── ...
```

### 本地脚本流程（`push_and_wait.py`）

```
对每一天：
1. rsync 推送该天所有视频和 JSON 文件到服务器 /srv/light_batch/work/{date}/
2. 创建 .ready 标记告诉服务器可以开始处理
3. 轮询检查 .done 标记：
   - 每 poll_interval 秒检查一次
   - 最多等待 poll_timeout 秒
   - 如果检测到 .done，继续下一天
   - 如果超时，输出警告并跳过该日期
4. 清理本地临时文件（可选）
```

### 服务器脚本流程（`server_batch_process.py`）

```
守护进程持续运行：
1. 每 poll_interval 秒扫描 /srv/light_batch/work/ 目录
2. 找到有 .ready 标记（且没有 .done）的目录
3. 对该目录执行：
   a. 启动推理任务（调用 infer_origin.py）
   b. 等待推理完成
   c. 删除临时视频和 JSON 文件（保留数据库）
   d. 创建 .done 标记
4. 所有日志写入 /srv/light_batch/logs/{date}.log
```

## 使用示例

### 示例 1：推送并等待全部完成

```bash
# 本地
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai
```

输出示例：
```
📋 共 2 天数据待处理
   2025_9_1: 10 个文件
   2025_9_2: 8 个文件

============================================================

[1/2] 处理日期 2025_9_1
============================================================
📤 [14:30:20] 推送 2025_9_1 (10 个文件)...
  $ rsync -avz --partial '/media/zekai/Expansion/...' chmai@venus3.ihpc.uts.edu.au:/srv/light_batch/work/2025_9_1/
  ✅ 2025_9_1 所有文件推送完成
  创建 .ready 标记...
  ⏳ 等待服务器处理 2025_9_1...
     (轮询间隔：10s，超时：3600s)
     [14:30:31] 已等待 10s...
     [14:31:00] 已等待 40s...
     ...
  ✅ 2025_9_1 处理完成！(耗时: 240s)
  清理 2025_9_1 临时数据...

[2/2] 处理日期 2025_9_2
...

============================================================
✅ 所有日期处理完成！
```

### 示例 2：仅处理单个日期

```bash
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai \
  --date 2025_9_1    # 仅推送这一天
```

### 示例 3：模拟运行（测试）

```bash
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai \
  --dry-run           # 显示命令但不执行
```

### 示例 4：在服务器上处理单个日期（不等待）

```bash
# 服务器上
python3 server_batch_process.py \
  --work-root /srv/light_batch/work \
  --db-root /srv/light_batch/db \
  --date 2025_9_1     # 仅处理这一天，不进入守护模式
```

## 参数参考

### `push_and_wait.py` 参数

| 参数 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `--manifest` | ✅ | - | manifest.csv 本地路径 |
| `--server` | ✅ | - | 服务器地址（主机名或 IP） |
| `--server-user` | ✅ | - | 服务器 SSH 用户（如 chmai） |
| `--server-root` | | `/srv/light_batch` | 服务器工作根目录 |
| `--local-user` | ✅ | - | 本地 SSH 用户（如 zekai） |
| `--poll-interval` | | `10` | 轮询间隔（秒） |
| `--poll-timeout` | | `3600` | 单日处理超时（秒，默认 1 小时） |
| `--dry-run` | | - | 模拟运行，不真正执行 |
| `--date` | | - | 仅处理指定日期 |
| `--skip-cleanup` | | - | 不清理临时数据 |

### `server_batch_process.py` 参数

| 参数 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `--work-root` | | `/srv/light_batch/work` | 工作目录（存放视频） |
| `--db-root` | | `/srv/light_batch/db` | 数据库目录 |
| `--log-root` | | `/srv/light_batch/logs` | 日志目录 |
| `--infer-script` | | `/home/chmai/.../infer_origin.py` | 推理脚本路径 |
| `--poll-interval` | | `5` | 轮询间隔（秒） |
| `--date` | | - | 仅处理指定日期（不进入守护模式） |

## 日志

### 本地日志

本地脚本会在终端输出进度：

```
📤 推送 2025_9_1 (10 个文件)...
✅ 2025_9_1 所有文件推送完成
⏳ 等待服务器处理 2025_9_1...
✅ 2025_9_1 处理完成！(耗时: 240s)
```

### 服务器日志

服务器日志保存在 `/srv/light_batch/logs/{date}.log`：

```
[2025-05-08 14:30:30] ========== BEGIN 2025_9_1 ==========
[2025-05-08 14:30:30] 输入目录: /srv/light_batch/work/2025_9_1
[2025-05-08 14:30:30] 找到 10 个视频文件
[2025-05-08 14:30:30] ========== INFER START ==========
[2025-05-08 14:30:30] 命令: python3 infer_origin.py --video-dir ... --db-path ...
[2025-05-08 14:35:00] ✅ 推理完成 (耗时: 270s)
[2025-05-08 14:35:00] ========== CLEANUP START ==========
[2025-05-08 14:35:05] ========== CLEANUP DONE ==========
[2025-05-08 14:35:05] ✅ 创建 .done 标记
[2025-05-08 14:35:05] ========== END 2025_9_1 ==========
```

### 守护进程日志

守护进程日志保存在 `/srv/light_batch/logs/daemon.log`：

```
[2025-05-08 14:30:15] 🚀 服务器批处理守护进程启动
[2025-05-08 14:30:15] 监听中...
[2025-05-08 14:30:25] 🔔 检测到 2025_9_1 待处理
[2025-05-08 14:35:10] 🔔 检测到 2025_9_2 待处理
```

## 故障排查

### 1. 本地脚本卡在"等待服务器处理"

**原因**：服务器上未启动守护进程，或守护进程已崩溃。

**解决**：
```bash
# 检查服务器守护进程状态
ssh venus3 "ps aux | grep server_batch_process"

# 如果没有，重新启动
ssh venus3 "nohup python3 /path/to/light/server_batch_process.py ... > /srv/light_batch/logs/daemon.log 2>&1 &"

# 查看最近的日志
ssh venus3 "tail -50 /srv/light_batch/logs/daemon.log"
```

### 2. 推理失败，未生成 .done 标记

**原因**：infer_origin.py 执行出错。

**解决**：
```bash
# 查看推理日志
ssh venus3 "tail -100 /srv/light_batch/logs/2025_9_1.log"

# 手动运行推理测试
ssh venus3 "python3 /path/to/light/infer_origin.py --help"
```

### 3. 数据库文件损坏或不完整

**原因**：推理过程中中断或磁盘满。

**解决**：
```bash
# 检查数据库文件大小
ssh venus3 "ls -lh /srv/light_batch/db/infer_results_2025_9_1.db"

# 验证数据库完整性
ssh venus3 "sqlite3 /srv/light_batch/db/infer_results_2025_9_1.db 'SELECT COUNT(*) FROM detections;'"
```

### 4. 磁盘空间不足

**原因**：累积了多天的临时数据和数据库。

**解决**：
```bash
# 查看磁盘使用情况
ssh venus3 "du -sh /srv/light_batch/*"

# 手动清理（谨慎！）
ssh venus3 "rm -rf /srv/light_batch/work/*/.ready /srv/light_batch/work/*/.done"

# 重新启动守护进程
ssh venus3 "pkill -f server_batch_process"
ssh venus3 "nohup python3 ... > /srv/light_batch/logs/daemon.log 2>&1 &"
```

## 推荐配置

基于实际场景的建议配置：

### 小规模（每天 < 100 个视频）

```bash
# 本地
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai \
  --poll-interval 10      # 每 10 秒检查一次
  --poll-timeout 1800     # 最多等 30 分钟

# 服务器（后台）
nohup python3 server_batch_process.py \
  --poll-interval 5 \
  > /srv/light_batch/logs/daemon.log 2>&1 &
```

### 大规模（每天 > 100 个视频）

```bash
# 本地
python3 push_and_wait.py \
  --manifest manifest.csv \
  --server venus3.ihpc.uts.edu.au \
  --server-user chmai \
  --poll-interval 30      # 每 30 秒检查一次（减少网络开销）
  --poll-timeout 7200     # 最多等 2 小时

# 服务器（后台，多个 worker）
# 需修改 server_batch_process.py 以支持多个工作进程
```

## 完整工作流检查清单

- [ ] 本地 SSH 服务已启动：`systemctl status ssh.socket`
- [ ] 服务器能 SSH 连接到本地：`ssh venus3 "ssh zekai@localhost 'id'"`（或配置 /etc/hosts）
- [ ] 本地已准备 `manifest.csv`
- [ ] 服务器目录已创建：`/srv/light_batch/{work,db,logs}`
- [ ] `infer_origin.py` 支持 `--video-dir` 和 `--db-path` 参数（或修改脚本）
- [ ] 服务器守护进程已启动：`ps aux | grep server_batch_process`
- [ ] 本地执行 `push_and_wait.py`

## 相关文件

- [push_and_wait.py](push_and_wait.py) — 本地推送脚本
- [server_batch_process.py](server_batch_process.py) — 服务器处理脚本
- [manifest.csv](manifest.csv) — 文件列表示例
- [SERVER_BATCH_WORKFLOW_SPEC.md](SERVER_BATCH_WORKFLOW_SPEC.md) — 完整需求文档
