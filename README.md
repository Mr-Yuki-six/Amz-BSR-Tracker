# 🛒 Amz-BSR-Tracker: 亚马逊竞品排名自动化追踪系统

这是一个专为亚马逊精细化运营设计的自动化竞争情报爬虫系统。利用原生的浏览器指纹伪装技术，突破高强度反爬限制，精准抓取竞品的 BSR (Best Sellers Rank)、评分、评论数以及多级类目排名，并自动沉淀至 PostgreSQL 数据库，为后续的数据分析与可视化提供结构化支持。

## ✨ 核心特性

* **🛡️ 究极防爬伪装 (Anti-Bot Bypass):** 采用 `DrissionPage` 接管真实 Windows 浏览器，拥有完美的真实买家环境特征（字体、显卡渲染、TCP/IP 指纹），通过独立 `bot_data` 缓存区绕过亚马逊高强度 WAF 检测。
* **🗄️ 核心/长尾类目解耦 (JSONB Storage):** 支持将核心关注类目（如 `Bath Rugs`）独立抽离为数值列，同时利用 PostgreSQL 原生的 `JSONB` 格式打包存储其他所有波动的小类目节点，兼顾报表导出便利性与数据完整性。
* **🔄 智能档案 UPSERT 逻辑:** 自动分离静态属性（标题、品牌、材质、尺寸等）与动态事实（排名、评价）。仅在首次抓取或信息变动时更新商品档案，极大地优化了数据库写入效率。
* **🛠️ 工业级调试与容错:** * 支持命令行参数一键切换**有头/无头**模式。
    * 调试模式下支持**延迟关屏**，方便人工介入排查。
    * 抓取失败时自动触发 **现场截图** 并存入 `debug/` 目录，实现精准的故障回溯。
* **⚡ 极速并发引擎:** 基于线程池调度，配合无图加载模式，单品平均抓取耗时 < 3秒。

## 🛠️ 技术栈
* **语言:** Python 3.10+
* **库:** `DrissionPage`, `pandas`, `psycopg2-binary`, `python-dotenv`
* **存储:** PostgreSQL (支持远程映射调用)

## 🚀 快速开始

### 1. 克隆与环境配置
```bash
# 克隆项目
git clone [https://github.com/Mr-Yuki-six/Amz-BSR-Tracker.git](https://github.com/Mr-Yuki-six/Amz-BSR-Tracker.git)
cd Amz-BSR-Tracker

# 安装依赖 (建议在虚拟环境下执行)
pip install -r requirements.txt
```

### 2. 数据库准备
在你的 PostgreSQL 中运行以下 SQL 初始化表结构：
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
    bath_rugs_rank INTEGER,       -- 核心关注类目列
    other_sub_ranks JSONB,        -- 其他长尾类目 JSON
    rating NUMERIC(3, 1),
    reviews INTEGER,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3. 配置环境变量
在根目录新建 `.env` 文件，填入你的数据库连接信息（注意不要有空格）：
```ini
DB_HOST=your_server_ip
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password
```

### 4. 运行指令

* **常规全量运行 (无头模式)**:
  ```bash
  python main.py
  ```
* **调试模式 (显示浏览器，抓取 1 个 ASIN，停留 60 秒)**:
  ```bash
  python main.py --debug --limit 1
  ```
* **快速采样测试**:
  ```bash
  python main.py --limit 5
  ```

## 💡 运营维护建议

1. **首次运行 (重要)**: 务必先使用 `--debug` 模式运行一个 ASIN，在弹出的浏览器中手动将左上角配送邮编改为美国地址（如 `10001`），并确认语言为 English。
2. **24 小时部署**: 建议利用 Windows 的“任务计划程序”设置每日凌晨 2:00 自动触发 `python main.py`。
3. **数据安全**: `.env` 文件和 `bot_data/` 目录已被列入 `.gitignore`，请勿手动将其上传至公开仓库，以免泄露数据库密码或浏览器 Cookie。

## ⚠️ 免责声明
本项目仅供技术交流与学习使用。请确保抓取频率在目标网站的可接受范围内，并严格遵守相关的法律法规。因滥用本项目导致的一切后果由使用者自行承担。