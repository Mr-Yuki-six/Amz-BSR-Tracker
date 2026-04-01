# 🛒 Amz-BSR-Tracker: 亚马逊竞品排名自动化追踪系统

这是一个专为亚马逊精细化运营设计的自动化竞争情报爬虫系统。利用原生的浏览器指纹伪装技术，突破高强度反爬限制，精准抓取竞品的 BSR (Best Sellers Rank)、评分、评论数以及多级类目排名，并自动沉淀至 PostgreSQL 数据库，为后续的数据分析与可视化提供结构化支持。

## ✨ 核心特性

* **🛡️ 究极防爬伪装 (Anti-Bot Bypass):** 采用 `DrissionPage` 接管真实浏览器，拥有完美的真实买家特征（指纹、显卡渲染、TCP/IP 堆栈），配合独立 `bot_data` 缓存区，完美绕过亚马逊 WAF 与无头模式检测。
* **🗄️ 核心/长尾类目解耦 (JSONB Storage):** 支持将自定义的核心类目（如 `Yoga Mats`）独立抽离为数值列，同时利用 `JSONB` 格式打包存储所有长尾类目，兼顾报表导出便利性与数据完整性。
* **⚙️ 智能配置脱敏 (JSONC Support):** 引入 `config.json` 配置文件，支持在 JSON 中直接使用 `//` 编写注释，程序运行时自动过滤。无需修改代码即可快速切换监控类目和调整爬虫强度。
* **📊 实时可视化进度:** 集成 `tqdm` 动态进度条，实时显示当前抓取位置 `(当前/总数)`、百分比、当前速率及预估剩余时间 (ETA)。
* **🚩 任务审计报告:** 程序运行结束自动输出汇总报告，包含总耗时、平均速率、抓取成功率等关键指标，方便监控系统健康度。
* **🛠️ 工业级容错与调试:** * 支持命令行参数一键切换 **有头/无头** 模式。
    * 调试模式下支持 **延迟关屏**，方便人工介入观察。
    * 抓取失败自动触发 **现场截图** 并存入 `debug/` 目录，实现精准故障回溯。

## 🛠️ 技术栈
* **脚本层:** Python 3.10+, `DrissionPage`, `pandas`, `tqdm`
* **存储层:** PostgreSQL, `psycopg2-binary`
* **配置管理:** `python-dotenv`, `argparse`

## 🚀 快速开始

### 1. 环境准备
```bash
# 克隆项目
git clone [https://github.com/Mr-Yuki-six/Amz-BSR-Tracker.git](https://github.com/Mr-Yuki-six/Amz-BSR-Tracker.git)
cd Amz-BSR-Tracker

# 安装依赖
pip install -r requirements.txt
```

### 2. 初始化数据库
在 PostgreSQL 中执行以下 SQL 建立底层数据架构：
```sql
-- 商品基础档案表
CREATE TABLE products (
    asin VARCHAR(20) PRIMARY KEY,
    title TEXT,
    brand VARCHAR(100),
    material VARCHAR(100),
    back_material VARCHAR(100),
    item_shape VARCHAR(100),
    item_size VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- BSR 历史记录表
CREATE TABLE bsr_history (
    id SERIAL PRIMARY KEY,
    asin VARCHAR(20) REFERENCES products(asin),
    main_category VARCHAR(255),
    main_rank INTEGER,
    focus_category_rank INTEGER,   -- 核心关注类目的排名（对应 config.json 中的设置）
    other_sub_ranks JSONB,         -- 其他类目排名打包
    rating NUMERIC(3, 1),
    reviews INTEGER,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3. 应用配置
1. **环境变量**: 复制 `.env.example` 为 `.env`，填入数据库凭证。
2. **核心设置**: 复制 `config.example.json` 为 `config.json`，根据需求修改 `target_category`（目标类目）和其他性能参数。

### 4. 运行指令

* **常规模式 (推荐 24h 部署)**:
  ```bash
  python main.py
  ```
* **有头调试模式 (查看浏览器操作过程)**:
  ```bash
  python main.py --debug --limit 1
  ```
* **采样测试 (仅运行前 5 个 ASIN)**:
  ```bash
  python main.py --limit 5
  ```

## 💡 运维与避坑指南

1. **邮编定位 (重要)**: 首次运行建议带上 `--debug`，手动在弹出的浏览器中将亚马逊配送邮编改为美国地址（如 `10001`），该设置会永久保存在 `bot_data` 中。
2. **并发建议**: `max_workers` 建议设置为 3-5。过高的并发可能导致亚马逊触发更严格的验证码校验。
3. **数据库列名**: 本系统使用通用的 `focus_category_rank` 存储你关注的类目。如果你之前使用的列名是 `bath_rugs_rank`，请执行 SQL 进行更名：`ALTER TABLE bsr_history RENAME COLUMN bath_rugs_rank TO focus_category_rank;`
4. **隐私安全**: `config.json` 和 `bot_data/` 已被列入 `.gitignore`，请确保不要将包含真实密码和监控策略的文件上传至公开仓库。

## ⚠️ 免责声明
本项目仅供技术交流与学习使用。请确保抓取频率在目标网站的可接受范围内，并严格遵守相关的法律法规。因滥用本项目导致的一切后果由使用者自行承担。