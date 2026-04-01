# 🛒 Amz-BSR-Tracker: 亚马逊竞品排名自动化追踪系统

这是一个专为亚马逊精细化运营设计的自动化竞争情报爬虫系统。利用原生的浏览器指纹伪装技术，突破高强度反爬限制，精准抓取竞品的 BSR (Best Sellers Rank)、评分、评论数以及多级类目排名，并自动沉淀至 PostgreSQL 数据库，为后续的 BI 可视化面板（如 Grafana / Metabase）提供结构化的时间序列数据。

## ✨ 核心特性

* **🛡️ 究极防爬伪装 (Anti-Bot Bypass):** 弃用传统的 Selenium/Playwright 方案，采用底层的 `DrissionPage` 接管真实 Windows 浏览器。通过独立的 `bot_data` 专属缓存区“养号”，完美绕过软验证码 (Soft Captcha) 与无头模式检测。
* **🗄️ 跨维度多类目兼容 (JSONB Storage):** 针对“一个 ASIN 挂载多个小类节点”的经典运营痛点，采用 PostgreSQL 原生的 `JSONB` 格式打包存储长尾类目，并支持将核心品类（如 `Bath Rugs`）独立抽离为数值列，完美兼顾灵活性与查询性能。
* **🔄 智能档案补全 (UPSERT 逻辑):** 将静态属性（标题、品牌、材质、尺寸等）与动态事实（排名、评分、评论）分离存储。使用 `ON CONFLICT DO UPDATE` 语法，只在首次抓取或信息更新时修改商品档案，极大节省数据库 IO。
* **🛠️ 智能调试与容错机制 (Smart Debug):** 内置命令行参数支持一键切换有头/无头模式、限制抓取数量。遇到由于亚马逊改版或反爬导致的抓取失败时，自动保存现场截图至 `debug/` 目录，实现无人值守时的精准故障回溯。
* **⚡ 极速抓取引擎:** 并发线程池 (ThreadPoolExecutor) 调度，无图极速渲染，平均单品抓取耗时 < 3秒。

## 🛠️ 技术栈
* **脚本层:** Python 3.x, `DrissionPage` (浏览器自动化), `pandas` (数据预处理), `argparse` (命令行交互)
* **存储层:** PostgreSQL, `psycopg2` (数据库驱动)
* **配置管理:** `python-dotenv` (环境变量隔离)

## 🚀 快速开始

### 1. 环境准备
强烈建议在 **Windows 环境** 下运行本脚本（以获取最真实的浏览器指纹），数据库可部署在服务器或本地 WSL/Docker 中。

```bash
# 克隆项目
git clone https://github.com/Mr-Yuki-six/Amz-BSR-Tracker
cd Amz-BSR-Tracker

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置数据库与环境变量
根据项目根目录的 `.env.example`，创建一个 `.env` 文件，并填入你的 PostgreSQL 凭证：
```ini
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
```

### 3. 初始化数据库表结构
在你的 PostgreSQL 中执行以下 SQL 语句建立底层数据架构：
```sql
-- 创建商品基础档案表
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

-- 创建 BSR 时间序列记录表
CREATE TABLE bsr_history (
    id SERIAL PRIMARY KEY,
    asin VARCHAR(20) REFERENCES products(asin),
    main_category VARCHAR(255),
    main_rank INTEGER,
    bath_rugs_rank INTEGER,       -- 你的核心关注类目（可自行修改代码适配）
    other_sub_ranks JSONB,        -- 动态打包所有长尾小类
    rating NUMERIC(3, 1),
    reviews INTEGER,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 创建查询索引
CREATE INDEX idx_bsr_asin_time ON bsr_history(asin, captured_at);
```

### 4. 首次运行与“养号调教”
1. 准备你的追踪清单：在 `data/` 目录下放置 `input_asins.xlsx`，确保有一列名为 `ASIN`。
2. 首次运行请务必使用调试模式：`python main.py --debug --limit 1`。
3. 此时程序会自动打开可见的浏览器窗口。**请火速手动介入：将亚马逊网页左上角的配送邮编改为美国邮编（如 10001），语言切换为 English。**
4. 这些设置会永久保存在根目录自动生成的 `bot_data` 文件夹中，为后续的无头模式提供完美的伪装环境。

### 5. 运行与高阶调试指令
本系统内置了灵活的命令行参数，满足不同场景下的运行需求：

* **常规运行 (生产环境默认配置)**：无头模式静默运行，全量抓取。
  ```bash
  python main.py
  ```
* **可视化调试模式**：关闭无头模式，显示浏览器窗口并加载图片，用于排查亚马逊拦截或页面改版。
  ```bash
  python main.py --debug
  ```
* **快速采样测试**：结合调试模式，仅抓取前 N 个 ASIN 进行逻辑验证，避免浪费时间。
  ```bash
  python main.py --debug --limit 5
  ```
> 💡 **提示**: 无论在何种模式下，如果某个 ASIN 数据提取失败，系统会自动在根目录下生成 `debug/error_<ASIN>_<Timestamp>.jpg` 截图，方便事后复盘。

### 6. 自动化部署 (推荐)
利用 Windows 自带的“任务计划程序 (Task Scheduler)”，设置每日凌晨定时触发 `python main.py`，即可实现 24 小时无人值守的竞品监控数据自动流转。

## ⚠️ 免责声明
本项目代码仅供技术交流与学习使用。在抓取数据时，请务必遵守目标网站的 `robots.txt` 协议，并合理控制抓取频率，避免对服务器造成负荷。因滥用本项目导致的一切账号封禁或法律纠纷，开发者概不负责。