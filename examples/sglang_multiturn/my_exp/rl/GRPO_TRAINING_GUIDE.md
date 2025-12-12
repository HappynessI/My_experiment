# Webshop GRPO Training Guide

## 概述

本指南说明如何在verl框架中使用GRPO算法训练Webshop环境的智能体。

## 架构

```
verl GRPO Trainer
    ↓
ToolAgentLoop (agent_loop)
    ↓
WebshopInteraction (interaction)
    ↓ HTTP
AgentGym Webshop Server (独立进程)
```

### 关键组件

1. **GRPO Trainer** (`verl.trainer.main_ppo`)
   - 使用GRPO算法（Group Relative Policy Optimization）
   - 不需要critic model
   - 使用环境reward直接优化policy

2. **ToolAgentLoop** (`verl.experimental.agent_loop.tool_agent_loop`)
   - 管理多轮对话循环
   - 处理模型生成和环境交互
   - 支持interaction模式

3. **WebshopInteraction** (`verl.interactions.webshop_interaction`)
   - 与Webshop环境服务器通信
   - 提取action并执行
   - 返回observation和reward

4. **Webshop Server** (AgentGym)
   - 独立运行的HTTP服务器
   - 端口: 36003
   - 提供环境状态和reward

## 数据格式

训练数据位于: `/Data/wyh/datasets/Verl-Data/webshop/train.parquet`

格式:
```python
{
    "data_source": "webshop",
    "prompt": [
        {"role": "system", "content": "<system_prompt>"},
        {"role": "user", "content": "Please help me with my shopping task..."}
    ],
    "ability": "shopping",
    "reward_model": {"style": "interaction"},
    "extra_info": {
        "index": 0,
        "interaction_kwargs": {
            "name": "webshop",
            "session_id": 5238
        }
    }
}
```

## 配置文件

### 主配置: `config/webshop_grpo_train.yaml`

关键参数:
```yaml
algorithm:
  adv_estimator: grpo  # 使用GRPO算法

actor_rollout_ref:
  rollout:
    multi_turn:
      enable: True
      max_user_turns: 25
      max_assistant_turns: 25
      interaction_config_path: examples/sglang_multiturn/config/webshop_interaction.yaml
    
    agent:
      default_agent_loop: tool_agent  # 使用ToolAgentLoop
      num_workers: 4

trainer:
  n_gpus_per_node: 4
  total_epochs: 15
  save_freq: 5
  test_freq: 3
```

### Interaction配置: `config/webshop_interaction.yaml`

```yaml
- name: webshop
  _target_: verl.interactions.webshop_interaction.WebshopInteraction
  config:
    env_server_base: "http://127.0.0.1:36003"
    timeout: 600
    max_retries: 3
```

## 训练流程

### 1. 启动Webshop服务器

```bash
conda activate webshop
cd /Data/wyh/AgentGym-RL/AgentGym/agentenv-webshop
python -m uvicorn agentenv_webshop:app --host 0.0.0.0 --port 36003
```

### 2. 测试训练 (推荐先运行)

```bash
cd /Data/wyh/verl
bash examples/sglang_multiturn/run_webshop_grpo_test.sh
```

测试参数:
- Batch size: 8
- Epochs: 1
- Rollout N: 2
- GPUs: 4-7卡

### 3. 完整训练

```bash
cd /Data/wyh/verl
bash examples/sglang_multiturn/run_webshop_grpo_train.sh
```

完整参数:
- Batch size: 128
- Epochs: 15
- Rollout N: 4
- GPUs: 0-3卡

## 训练参数说明

### 关键超参数

| 参数 | 测试值 | 完整值 | 说明 |
|------|--------|--------|------|
| `train_batch_size` | 8 | 128 | 训练batch大小 |
| `micro_batch_size` | 2 | 2 | 每GPU的micro batch |
| `learning_rate` | 5e-7 | 5e-7 | 学习率 |
| `total_epochs` | 1 | 15 | 总训练轮数 |
| `rollout_n` | 2 | 4 | 每个prompt采样次数 |
| `max_user_turns` | 25 | 25 | 最大环境交互轮数 |

### 内存优化

```yaml
fsdp_config:
  param_offload: True      # 参数offload到CPU
  optimizer_offload: True  # 优化器状态offload到CPU
  model_dtype: bfloat16

enable_gradient_checkpointing: True
enable_activation_offloading: True
```

## 输出文件

训练输出目录: `/Data/wyh/datasets/Verl-Data/outputs/webshop_grpo/`

```
outputs/webshop_grpo/
├── logs/
│   └── train_20251212_HHMMSS.log  # 训练日志
├── checkpoints/
│   ├── epoch_5/
│   ├── epoch_10/
│   └── epoch_15/
└── metrics/
    └── training_metrics.json
```

## 监控训练

### 查看实时日志

```bash
tail -f /Data/wyh/datasets/Verl-Data/outputs/webshop_grpo/logs/train_*.log
```

### 关键指标

- **Average Reward**: 平均环境reward (目标: > 0.5)
- **Success Rate**: 任务成功率 (目标: > 0.3)
- **Policy Loss**: 策略损失
- **KL Divergence**: 与reference model的KL散度

## 故障排查

### 问题1: Webshop服务器连接失败

```
ERROR: Webshop server is not running!
```

**解决**: 启动Webshop服务器
```bash
conda activate webshop
cd /Data/wyh/AgentGym-RL/AgentGym/agentenv-webshop
python -m uvicorn agentenv_webshop:app --host 0.0.0.0 --port 36003
```

### 问题2: CUDA OOM

```
RuntimeError: CUDA out of memory
```

**解决**: 
1. 减小`micro_batch_size`
2. 减小`train_batch_size`
3. 启用更多offload选项
4. 减小`rollout_n`

### 问题3: Ray初始化失败

```
RuntimeError: Failed to initialize Ray
```

**解决**: 
```bash
ulimit -n 65535
ray stop  # 停止之前的Ray进程
```

### 问题4: 模型不输出action

参考评估脚本的成功参数:
- `temperature=0.1` (强制简洁输出)
- `max_new_tokens=800` (足够空间)
- System prompt添加强制action要求

## 评估训练后的模型

使用评估脚本测试训练后的checkpoint:

```bash
MODEL_PATH=/Data/wyh/datasets/Verl-Data/outputs/webshop_grpo/checkpoints/epoch_15 \
MAX_SAMPLES=50 \
bash examples/sglang_multiturn/run_lightweight_eval.sh
```

## GRPO vs PPO

| 特性 | GRPO | PPO |
|------|------|-----|
| Critic Model | 不需要 | 需要 |
| 训练速度 | 更快 | 较慢 |
| 内存占用 | 更少 | 更多 |
| 适用场景 | 环境reward明确 | 需要value estimation |

## 参考资料

- verl框架: https://github.com/volcengine/verl
- GRPO论文: Group Relative Policy Optimization
- AgentGym: https://github.com/AgentGym/AgentGym

## 下一步

1. ✅ 运行测试训练验证流程
2. ⏳ 运行完整训练
3. ⏳ 评估训练后的模型
4. ⏳ 调优超参数
5. ⏳ 扩展到其他AgentGym环境

---

**创建时间**: 2024-12-12
**状态**: 准备测试

