# Part II 已完成内容与使用方法

当前完成的是：原仿真运行、LLM 接口实现、离线控制实验、故障回退验证，以及真实智谱模型试验。
使用的是官方标为免费的 `glm-4-flash-250414`，没有选择付费模型。
**离线规则结果与真实 LLM 结果分别记录，不能混用。**

## 先看这些文件

- `PART2_REPORT.md`：英文技术报告草稿，包含方法、真实离线结果、问题与局限。
- `PART2_GUIDE.md`：完整运行说明、模型接口配置、指标定义。
- `PART2_ZHIPU_RESULTS.md`：真实智谱试验结果、API 接入问题和性能分析。
- `part2-results/comparison-seed-1.png`：三种控制方式的速度对比。
- `part2-results/seed-1/guarded/time-space.png`：时空图。
- `part2-results/seed-1/guarded/target.png`：受控车辆的速度、加速度、车距。
- `part2-results/summary.csv`：1 秒决策间隔的数值结果。
- `part2-interval2/summary.csv`：2 秒决策间隔的数值结果。
- `part2-failure/summary.json`：故障注入结果。

## 已验证的实验

每次仿真 500 秒，步长 0.1 秒，实验 1（临时瓶颈），第 20 辆车作为受控车。

1. IDM、离线规则、规则加保护：三个随机种子，共 9 次。
2. 决策间隔改为 2 秒，重复上述组合，共 9 次。
3. 每次决策故意抛出超时异常，验证回退到 IDM，共 3 次。

21 次记录中没有检测到车辆重叠。保护机制增加了受控车的最小车距，
也增大了加速度变化；报告保留了这一代价，没有把保护结果全部归因于实验策略。
15 项测试通过。HTTP 测试使用模拟响应，不是实际模型调用。

## 重新运行

在仓库根目录打开 PowerShell，使用 Python 3.11 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r car-following-simulation/requirements.txt
$env:MPLCONFIGDIR = "$PWD/car-following-simulation/.mplconfig"
python car-following-simulation/run_part2.py
```

原始入口仍可使用：

```powershell
python car-following-simulation/main.py --experiment 1 --time-max 500 --output car-following-simulation/results/idm-original.png --no-show
```

全车轨迹 CSV 比较大，只保存在本机，不推送到 GitHub；重新运行可以生成。
受控车轨迹、逐步控制日志、决策日志、摘要和图表均保留在库中。

## 后续真实 LLM 实验

`LLM_BASE_URL`、`LLM_MODEL`、可选 `LLM_API_KEY` 通过环境变量配置。
默认禁止 API 调用；只有显式传入 `--policy api --allow-api` 才启用。
详细命令见英文指南。对本地模型同样需要一个已经运行的兼容服务；
代码不会自动下载模型。真实智谱结果与延迟在 `part2-zhipu` 中单独记录。

作业允许有记录的探索过程，即使未实现理想目标也可提交；但是否补做真实模型实验，
应结合课程要求和你自己的进度判断，不能把离线规则实验写成真实模型结果，
也不能把有 IDM 保护介入的轨迹称为完全由 LLM 独立控制。

## 提交前你需要完成

- 阅读代码和图表，核实自己能解释输入、输出、IDM 回退和保护机制。
- 补充姓名、学号和你实际参与的开发过程；不要把自动生成的草稿原样当作个人经历。
- **Personal reflection 和 Conclusions 必须由你独立撰写，草稿已留空。**
- 如需 Word/PDF，先完成这两节，再排版导出。
