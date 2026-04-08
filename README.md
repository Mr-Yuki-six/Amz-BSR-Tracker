# 🛒 Amz-BSR-Tracker Pro: 亚马逊竞品排名自动化追踪系统

这是一个专为亚马逊精细化运营设计的自动化竞争情报系统。通过原生的浏览器指纹伪装技术，精准抓取竞品的 BSR 排名、星级分布及评价数。V2.5 版本已全面升级为 **带 GUI 的现代化桌面应用程序**，支持一键打包、状态记忆、无人值守定时执行与双引擎数据导出。

## ✨ 核心特性

* **🖥️ 现代桌面 UI:** 采用 `customtkinter` 打造暗黑风控制面板，所有爬虫参数、数据库配置均可通过界面热修改并自动记忆。
* **⏰ 无人值守定时器:** 内置守护进程，设定时间后每天自动在后台唤醒浏览器执行抓取任务。
* **🗄️ 双擎数据沉淀:** * 支持静默追加导出至同目录的 `bsr_output.xlsx`（附带精准抓取时间戳）。
  * 深度集成 PostgreSQL，采用 UPSERT 机制自动合并更新商品基础属性，记录具体的小类目名称及排名。
* **🛡️ 工业级容错与调度:**
  * **安全刹车**: 随时点击“停止”按钮，系统将安全地取消队列并关闭正在运行的浏览器。
  * **防冲突机制**: 每次启动随机分配调试端口，并自动清理僵尸进程锁，拒绝崩溃。
* **⭐ 细粒度评价分析:** 具备智能滚屏与懒加载触发机制，精准提取 1-5 星各星级占比百分比。

## 🛠️ 技术栈
* **应用层:** Python 3.10+, `customtkinter`, `schedule`
* **爬虫层:** `DrissionPage` (完美绕过亚马逊无头模式检测)
* **数据层:** PostgreSQL (`psycopg2-binary`), `pandas`, `openpyxl`

## 🚀 快速开始

### 1. 环境准备
```bash
# 克隆项目
git clone [https://github.com/Mr-Yuki-six/Amz-BSR-Tracker.git](https://github.com/Mr-Yuki-six/Amz-BSR-Tracker.git)
cd Amz-BSR-Tracker

# 安装依赖
pip install -r requirements.txt
```

### 2. 初始化数据库 (可选，若仅使用 Excel 导出则无需配置)
在 PostgreSQL 中执行以下 SQL 建立底层数据架构：
```sql
-- 商品基础档案表
CREATE TABLE products (
    asin VARCHAR(20) PRIMARY KEY,
    title TEXT,
    brand VARCHAR(100),
    material VARCHAR(100),
    item_shape VARCHAR(100),
    item_size VARCHAR(100),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- BSR 历史记录表
CREATE TABLE bsr_history (
    id SERIAL PRIMARY KEY,
    asin VARCHAR(20) REFERENCES products(asin),
    main_category VARCHAR(255),
    main_rank INTEGER,
    focus_category_name VARCHAR(255),  
    focus_category_rank INTEGER,       
    other_sub_ranks JSONB,         
    rating NUMERIC(3, 1),
    reviews INTEGER,
    star_5_pct INTEGER,            
    star_4_pct INTEGER,            
    star_3_pct INTEGER,            
    star_2_pct INTEGER,            
    star_1_pct INTEGER,            
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3. 运行软件
```bash
python AmzTracker_GUI.py
```

### 4. 📦 打包为独立可执行程序 (EXE)
使用 PyInstaller 一键打包，方便发给团队成员直接使用：
```bash
pyinstaller -F -w --noconsole --name "AmzTrackerPro" AmzTracker_GUI.py
```
打包完成后，在 `dist/` 文件夹下即可获取开箱即用的 `AmzTrackerPro.exe`。

## 💡 使用指南与避坑

1. **首次初始化向导**: 软件第一次运行时，会自动临时开启**有头模式 (Debug)**。请在弹出的亚马逊页面中，**手动将左上角的配送邮编更改为目标国家邮编（如美国填：10001）**。修改后关闭浏览器，软件会永久记住该设定。
2. **状态自动记忆**: 软件会自动保存您在“抓取看板”上的所有选项。下次打开软件，直接点击开始即可。
3. **Excel 导出注意**: 如果勾选了导出 xlsx，请确保在抓取期间 **不要用 Excel 软件打开 `bsr_output.xlsx`**，否则可能导致程序因无写入权限而报错。

## ⚠️ 免责声明
本项目仅供技术交流与学习使用。请确保抓取频率在目标网站的可接受范围内，并严格遵守相关的法律法规。因滥用本项目导致的一切后果由使用者自行承担。