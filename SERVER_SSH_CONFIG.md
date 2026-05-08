# Venus3 服务器 SSH 连接信息

## 快速参考

```
host=venus3.ihpc.uts.edu.au
user=chmai
port=22
auth=key
key=/home/zekai/.ssh/id_ed25519
```

## 详细信息

### 主机信息
- **主机名**：`venus3.ihpc.uts.edu.au`
- **用户**：`chmai`
- **SSH 端口**：`22`（默认）
- **时区**：AEST (UTC+10)

### 认证方式
- **类型**：SSH 密钥认证（推荐）
- **私钥路径**：`/home/zekai/.ssh/id_ed25519`
- **公钥指纹**：`SHA256:efDnEoXsV2/FzPaUMQMisvkFDTfkvQBiQqKDLDqbjRc`

### SSH Config 配置（本地已存在）
```
Host venus3
    HostName venus3.ihpc.uts.edu.au
    User chmai
```

## 连接验证

✅ 连接状态：**正常**  
✅ 认证方式：**密钥已加载到 SSH agent**  
✅ 网络延迟：约 1.5 秒

## 在服务器脚本中的使用方式

### 方式一：使用 SSH Config（推荐）
```bash
# 连接
ssh venus3 "command"

# Git pull
ssh venus3 "cd /path/to/repo && git pull origin cropped"

# 上传文件
scp file.txt venus3:/remote/path/
```

### 方式二：显式指定主机
```bash
ssh -i /home/zekai/.ssh/id_ed25519 chmai@venus3.ihpc.uts.edu.au "command"
```

### 方式三：使用 SSH 密钥代理（如果在服务器本地部署）
如果脚本部署在 venus3 服务器上，并需要从 venus3 连回本地或连接其他主机，可以配置：
```bash
# 在 venus3 上添加公钥到 SSH agent 转发
ssh -A venus3  # 启用 agent 转发
```

## 为服务器分支准备的信息

以下是交给"分身"实现服务器脚本时需要的核心信息：

### Git 自动 Pull 配置
```bash
#!/bin/bash
# 在服务器上执行 git pull
REPO_PATH="/path/to/light"
BRANCH="cropped"

ssh venus3 "cd $REPO_PATH && git fetch origin && git checkout $BRANCH && git pull origin $BRANCH"
```

### 批处理脚本框架建议
```python
# server_batch_runner.py 伪代码
import subprocess
import os

SSH_HOST = "venus3.ihpc.uts.edu.au"
SSH_USER = "chmai"
SSH_KEY = "/home/zekai/.ssh/id_ed25519"  # 或使用 SSH agent
REPO_PATH = "/path/to/light"
WORK_DIR = "/srv/light_batch"
DB_DIR = f"{WORK_DIR}/db"
LOG_DIR = f"{WORK_DIR}/logs"

def run_remote(cmd):
    """在服务器上执行命令"""
    ssh_cmd = f'ssh -i {SSH_KEY} {SSH_USER}@{SSH_HOST} "{cmd}"'
    result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr

def pull_latest_code():
    """从服务器分支 pull 最新代码"""
    cmd = f"cd {REPO_PATH} && git fetch origin cropped && git checkout cropped"
    return run_remote(cmd)

def cleanup_work_dir(date_str):
    """清理指定日期的临时目录"""
    cmd = f"rm -rf {WORK_DIR}/work/{date_str}/*"
    return run_remote(cmd)

def cleanup_all():
    """清理所有缓存（谨慎使用）"""
    cmd = f"rm -rf {WORK_DIR}/work/* && rm -rf {WORK_DIR}/db/*"
    return run_remote(cmd)
```

### 本地推送新配置到服务器
```bash
# 将需求文档、脚本推送到服务器
git add SERVER_BATCH_WORKFLOW_SPEC.md
git commit -m "Add server batch workflow spec"
git push origin cropped

# 在服务器上更新
ssh venus3 "cd /path/to/light && git pull origin cropped"
```

## 注意事项

1. **密钥管理**：
   - 私钥文件 `/home/zekai/.ssh/id_ed25519` 禁止上传到公开仓库
   - 在服务器脚本中只需提供"主机"和"用户"信息
   - 密钥认证通过 SSH agent 自动处理

2. **SSH Agent 转发**：
   - 如果服务器脚本需要进一步连接其他系统，可启用 agent 转发
   - 在 SSH 命令中加 `-A` 参数

3. **安全建议**：
   - 服务器脚本中不要硬编码密钥路径
   - 确保 venus3 服务器上的代码权限正确
   - 定期检查服务器上的日志和临时文件

## 相关文件

- [SERVER_BATCH_WORKFLOW_SPEC.md](SERVER_BATCH_WORKFLOW_SPEC.md) - 服务器批处理需求文档
- [compare_human_model.py](compare_human_model.py) - 本地对比脚本
- [README.md](README.md) - 项目文档
